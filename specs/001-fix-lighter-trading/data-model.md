# Phase 1: 数据模型设计

**功能**: 修复Lighter交易所下单失败和日志混乱问题
**日期**: 2026-01-12

## 概述

本功能主要是bug修复，不引入新的数据模型。以下是现有模型的增强说明。

## 现有模型（无修改）

### OrderResult

位置: `exchanges/base.py`

```python
@dataclass
class OrderResult:
    """订单执行结果"""
    success: bool
    order_id: Optional[str]
    side: Optional[str] = None
    size: Optional[Decimal] = None
    price: Optional[Decimal] = None
    status: Optional[str] = None
    filled_size: Optional[Decimal] = None
    error_message: Optional[str] = None
```

**增强**: 在`error_message`中包含更详细的错误信息（SDK异常类型和堆栈）

---

### ConcurrentOrderResult

位置: `spread/models.py`

```python
@dataclass
class ConcurrentOrderResult:
    """并发订单执行结果"""
    extended_success: bool
    extended_order_id: Optional[str]
    extended_filled_qty: Decimal
    extended_filled_price: Optional[Decimal]
    extended_error: Optional[str]

    lighter_success: bool
    lighter_order_id: Optional[str]
    lighter_filled_qty: Decimal
    lighter_filled_price: Optional[Decimal]
    lighter_error: Optional[str]

    send_a_ts: float
    send_b_ts: float
    send_gap_ms: float
    total_latency_ms: float

    is_both_filled: bool
    is_legging: bool
    is_both_failed: bool
```

**无修改**: 此模型已满足需求

---

## 日志格式规范

### 日志标识格式

**新格式**:
```
[交易所] [交易对] 日志内容
```

**示例**:
```
[EXTENDED] [ETH] 订单已提交: order_id=2010650367611650048
[LIGHTER] [ETH] 订单已提交: order_id=12345
[EXTENDED] [ETH] ERROR: 下单失败: timeout
[LIGHTER] [ETH] ERROR: SDK exception: AttributeError: 'NoneType' object has no attribute 'code'
```

### 错误日志格式

**新格式**:
```
[交易所] ERROR: [错误类型] 错误消息 | 上下文信息
```

**示例**:
```
[LIGHTER] ERROR: [SDK Exception] AttributeError: 'NoneType' object has no attribute 'code' | Function: place_open_order, Line: 548
```

---

## 状态转换（无修改）

### 订单状态

```
NEW → OPEN → PARTIALLY_FILLED → FILLED
                ↓
              CANCELED
```

### 并发下单状态

```
开始 → 并发发送 → 等待响应 → 结果判断
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   双腿成交       单腿持仓      双边失败
        ↓             ↓
    持仓监控      紧急平仓
```

---

## 数据流（无修改）

### 并发下单流程

```
bot.py发现机会
  ↓
concurrent_executor.execute_dual_leg_orders()
  ↓
asyncio.gather(
  _place_order_extended(),
  _place_order_lighter()
)
  ↓
ConcurrentOrderResult
  ↓
判断is_legging
  ↓
紧急平仓（如果需要）
```

---

## 验证规则

### 日志验证

1. 所有Extended日志必须包含`[EXTENDED]`
2. 所有Lighter日志必须包含`[LIGHTER]`
3. 所有错误日志必须包含`ERROR`
4. 错误日志必须包含异常类型

### 订单验证

1. 紧急平仓订单必须设置`post_only=False`
2. 所有订单（包括紧急平仓）必须记录订单ID
3. 所有订单失败必须记录error_message

---

## 无新增模型

本功能不引入新的数据模型，所有修改都是对现有代码的增强。
