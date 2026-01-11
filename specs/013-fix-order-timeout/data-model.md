# Data Model: 修复订单执行超时和假阳性成交问题

**Feature**: 013-fix-order-timeout
**Date**: 2026-01-11

---

## Overview

本功能不引入新数据模型，修改现有类的行为验证逻辑。核心数据结构保持不变。

---

## Core Entities

### OrderResult

**Location**: `exchanges/base.py`

**Purpose**: 封装订单执行结果

```python
@dataclass
class OrderResult:
    """订单执行结果"""
    success: bool                    # 订单是否成功
    order_id: Optional[str]          # 订单ID（可能为None）
    side: str                        # 订单方向（buy/sell）
    size: Decimal                    # 订单数量
    price: Decimal                   # 订单价格
    status: Optional[str] = None     # 订单状态（OPEN/FILLED/CANCELED等）
    filled_size: Optional[Decimal] = None  # 成交数量
    error_message: Optional[str] = None    # 错误消息
```

**Behavior Changes**:
- **Extended**: `order_id`现在保证在`success=True`时不为`None`（对于IOC订单）
- **Lighter**: `success=True`只有在`order_id`不为`None`时才返回

**Validation Rules**:
- `success=True` ⇒ `order_id`不为`None`（新增约束）
- `success=False` ⇒ `error_message`不为空（增强日志）

---

### ConcurrentOrderResult

**Location**: `spread/models.py`

**Purpose**: 封装并发执行两个交易所订单的结果

```python
@dataclass
class ConcurrentOrderResult:
    """并发订单执行结果"""
    extended_success: bool
    extended_order_id: Optional[str]
    extended_error: Optional[str]
    lighter_success: bool
    lighter_order_id: Optional[str]
    lighter_error: Optional[str]
    send_gap_ms: float
    total_latency_ms: float
    is_both_filled: bool
    is_legging: bool
    is_both_failed: bool
```

**State Transitions**:

```
                    ┌─────────────────┐
                    │  Initial State  │
                    │ is_legging=False │
                    │ is_both_filled=False
                    │ is_both_failed=False
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Execute Orders  │
                    │ (asyncio.gather) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────▼──────┐ ┌────▼─────┐ ┌─────▼──────────┐
    │ ext_success=T │ │ lit_success=T│ │ ext_success=F │
    │ lit_success=F │ │ lit_success=F│ │ lit_success=F │
    └────────┬───────┘ └────┬─────┘ └─────┬──────────┘
             │              │              │
       is_legging=T   is_both_filled=T  is_both_failed=T
```

**Validation Rules**:
- `is_legging=True` ⇒ 一个`success=True`且另一个`success=False`（修正前：未验证`order_id`）
- `is_both_failed=True` ⇒ 两个`success=False`（修正前：可能误判为`is_legging`）

---

### OrderInfo

**Location**: `exchanges/base.py`

**Purpose**: 封装订单详细信息

```python
@dataclass
class OrderInfo:
    """订单信息"""
    order_id: str                   # 订单ID（必须存在）
    side: str                       # 订单方向
    size: Decimal                   # 订单数量
    price: Decimal                  # 订单价格
    status: str                     # 订单状态
    filled_size: Decimal = Decimal('0')    # 成交数量
    remaining_size: Decimal = Decimal('0') # 剩余数量
    cancel_reason: str = ''         # 取消原因
```

**Behavior Changes**:
- **Lighter**: `order_id`现在在被使用前验证存在性

---

## State Machine: 订单执行流程

### Extended IOC订单流程（修复后）

```
开始
  │
  ▼
调用place_open_order(contract_id, quantity, direction, post_only=False)
  │
  ▼
计算订单价格（对手价）
  │
  ▼
调用SDK place_order()
  │
  ├───── 失败 ────▶ 返回 OrderResult(success=False, error_message=...)
  │
  ▼
成功 + 获得order_id
  │
  ▼
[修复点] 不调用get_order_info()
  │
  ▼
立即返回 OrderResult(success=True, order_id=<有效ID>)
  │
  ▼
结束
```

### Lighter订单流程（修复后）

```
开始
  │
  ▼
调用place_open_order(contract_id, quantity, direction)
  │
  ▼
调用place_limit_order() → 设置current_order_client_id
  │
  ▼
等待0.5秒（WebSocket回调）
  │
  ▼
检查current_order
  │
  ├───────── None ──────────▶ 查询get_inactive_orders()
  │                             │
  │                             ▼
  │                         找到FILLED订单？
  │                             │
  │                             ├─ 是 ──▶ 返回 success=True
  │                             │
  │                             └─ 否 ──▶ 返回 success=False
  │
  ▼
不为None
  │
  ▼
[修复点] 检查current_order.order_id
  │
  ├───── None ──────▶ 记录警告 + 查询get_inactive_orders()
  │                          │
  │                          ▼
  │                      找到FILLED订单？
  │                          │
  │                          ├─ 是 ──▶ 返回 success=True
  │                          │
  │                          └─ 否 ──▶ 返回 success=False
  │
  ▼
不为None
  │
  ▼
检查status == 'FILLED'
  │
  ├───── 是 ──────▶ 返回 success=True
  │
  └───── 否 ──────▶ 返回 success=False
```

---

## Data Flow: 单腿持仓检测（修复后）

### 修复前（Bug）

```
并发执行结果：
  Extended: success=False, order_id=None, error=timeout
  Lighter: success=True, order_id=None  ← BUG: order_id=None但success=True

判断逻辑：
  is_legging = (ext_success != lit_success)
            = (False != True)
            = True  ← 误判为单腿持仓
```

### 修复后

```
并发执行结果：
  Extended: success=False, order_id=None, error=timeout
  Lighter: success=False, order_id=None, error="No order_id in callback"  ← 修复

判断逻辑：
  is_legging = (ext_success != lit_success)
            = (False != False)
            = False  ← 正确判断为双边失败
  is_both_failed = (not ext_success and not lit_success)
                 = True  ← 正确
```

---

## Relationships

```
OrderResult (返回值)
    │
    ├── 用于生成 → ConcurrentOrderResult
    │                   │
    │                   ├── extended_* 字段来自 Extended OrderResult
    │                   └── lighter_* 字段来自 Lighter OrderResult
    │
    └── 验证规则 → success=True ⟺ order_id不为None
                              │
                              └── 用于判断 → is_legging
                                            │
                                            └── 触发 → 单腿持仓回滚
```

---

## Constraints

### 必须满足的约束

1. **OrderResult一致性**: `success=True` ⇒ `order_id != None`
2. **并发执行超时**: 总执行时间 < 500ms
3. **日志完整性**: 失败时`error_message`不为空

### 不修改的约束

1. 不修改`OrderResult`字段定义
2. 不修改`ConcurrentOrderResult`字段定义
3. 不引入新的数据类
