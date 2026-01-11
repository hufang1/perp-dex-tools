# API Contracts: 修复订单执行超时和假阳性成交问题

**Feature**: 013-fix-order-timeout
**Date**: 2026-01-11

---

## Overview

本功能不添加新API，修改现有接口的行为以保证正确性。以下是接口行为变更说明。

---

## Modified Interfaces

### 1. `Extended.place_open_order()`

**Location**: `exchanges/extended.py`

**Signature**:
```python
async def place_open_order(
    self,
    contract_id: str,
    quantity: Decimal,
    direction: str,
    post_only: bool = False
) -> OrderResult
```

**Behavior Changes**:

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| IOC订单（`post_only=False`） | 调用`get_order_info()`（阻塞） | 立即返回`success=True` |
| Post-Only订单（`post_only=True`） | 调用`get_order_info()` | 调用`get_order_info()`（不变） |
| SDK返回失败 | 返回`success=False` | 返回`success=False`（不变） |

**New Guarantee**: IOC订单在100ms内返回结果

**Example**:
```python
# IOC订单
result = await extended_client.place_open_order(
    contract_id="ETH-USD",
    quantity=Decimal("0.01"),
    direction="buy",
    post_only=False  # IOC订单
)
# 修复后: 立即返回（<100ms）
assert result.success == True
assert result.order_id is not None
```

---

### 2. `Lighter.place_open_order()`

**Location**: `exchanges/lighter.py`

**Signature**:
```python
async def place_open_order(
    self,
    contract_id: str,
    quantity: Decimal,
    direction: str
) -> OrderResult
```

**Behavior Changes**:

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| `current_order.order_id`存在 | 返回`success=True` | 返回`success=True`（不变） |
| `current_order.order_id`为`None` | 返回`success=True` ❌ | 返回`success=False` ✅ + 查询API |
| WebSocket未到达 | 查询`get_inactive_orders()` | 查询`get_inactive_orders()`（不变） |

**New Guarantee**: `success=True` ⇒ `order_id is not None`

**Example**:
```python
result = await lighter_client.place_open_order(
    contract_id="ETH-USD",
    quantity=Decimal("0.01"),
    direction="sell"
)
# 修复后: 如果order_id为None，返回success=False
if result.success:
    assert result.order_id is not None  # 新保证
```

---

### 3. 并发执行器日志格式

**Location**: `spread/concurrent_executor.py`

**Modified Methods**:
- `execute_concurrent_orders()`
- `execute_dual_leg_orders()`

**Log Format Changes**:

**单腿持仓日志**（修复前）:
```
⚠️ [单腿持仓] Lighter: 成交, Extended: 失败, 间隔: 0.03ms
```

**单腿持仓日志**（修复后）:
```
⚠️ [单腿持仓] Lighter: 成交, Extended: 失败, 间隔: 0.03ms |
Extended: success=False, order_id=None, error=timeout |
Lighter: success=True, order_id=12345, error=None
```

**双边失败日志**（修复前）:
```
❌ [双边失败] Extended: timeout, Lighter: unknown
```

**双边失败日志**（修复后）:
```
❌ [双边失败] Extended: success=False, error=timeout |
Lighter: success=False, error=No order_id in callback |
间隔: 0.03ms
```

---

## Return Value Contracts

### OrderResult

**Invariant**:
```python
# 新增不变量
if result.success:
    assert result.order_id is not None
else:
    assert result.error_message is not None
```

**Validation**:
```python
def validate_order_result(result: OrderResult) -> bool:
    """验证OrderResult合约"""
    if result.success:
        if result.order_id is None:
            raise ValueError("success=True requires order_id")
    return True
```

---

### ConcurrentOrderResult

**State Exclusivity**:
```python
# 三个状态互斥
assert sum([is_both_filled, is_legging, is_both_failed]) == 1

# 修复后的正确判断
is_legging = (extended_success != lighter_success)
is_both_failed = (not extended_success and not lighter_success)
is_both_filled = (extended_success and lighter_success)

# 修复: 验证order_id
if extended_success:
    assert extended_order_id is not None
if lighter_success:
    assert lighter_order_id is not None
```

---

## Performance Contracts

### Response Time SLA

| 操作 | 修复前 | 修复后 | SLA |
|------|--------|--------|-----|
| Extended IOC订单 | >500ms（超时） | <100ms | <100ms |
| Lighter订单（WebSocket回调） | <500ms | <500ms | <500ms |
| Lighter订单（API查询） | <1000ms | <1000ms | <1000ms |
| 并发执行总延迟 | >500ms（超时） | <500ms | <500ms |

---

## Error Handling Contracts

### Extended错误码

| 错误消息 | 场景 | 处理方式 |
|----------|------|----------|
| `timeout` | SDK调用超时（>500ms） | 不重试，记录失败 |
| `Failed to place order` | SDK返回错误 | 检查订单参数 |
| `Invalid bid/ask prices` | 订单簿无效 | 等待订单簿更新 |

### Lighter错误码

| 错误消息 | 场景 | 处理方式 |
|----------|------|----------|
| `No order_id in callback` | WebSocket回调缺失`order_id` | 查询API验证 |
| `IOC order not filled within 0.5s` | 未在inactive订单中找到 | 记录失败 |
| `Failed to query order status` | API查询失败 | 返回失败 |

---

## Backward Compatibility

### 不兼容的变更

1. **Extended `place_open_order()` 返回时机**
   - IOC订单现在立即返回，不再等待状态查询
   - 影响：依赖状态查询的代码需要调整
   - 缓解：IOC订单状态通过WebSocket或API查询获取

2. **Lighter `place_open_order()` 返回条件**
   - `order_id=None`现在返回`success=False`
   - 影响：依赖`success`而不检查`order_id`的代码需要调整
   - 缓解：始终检查`order_id`存在性

### 兼容的变更

1. 日志格式增强（向后兼容）
2. `OrderResult`字段不变（行为变更）
3. `ConcurrentOrderResult`字段不变（验证逻辑变更）

---

## Testing Contracts

### 单元测试契约

```python
# Extended修复测试
async def test_extended_ioc_order_immediate_return():
    """Extended IOC订单应在100ms内返回"""
    start = time.time()
    result = await extended.place_open_order(
        contract_id="ETH",
        quantity=Decimal("0.01"),
        direction="buy",
        post_only=False
    )
    latency = (time.time() - start) * 1000
    assert result.success
    assert result.order_id is not None
    assert latency < 100  # 新SLA

# Lighter修复测试
async def test_lighter_order_id_none_returns_failure():
    """Lighter order_id为None时应返回失败"""
    # 模拟current_order.order_id为None
    lighter.current_order = OrderInfo(
        order_id=None,  # order_id缺失
        status="FILLED",
        ...
    )
    result = await lighter.place_open_order(...)
    assert result.success == False  # 修复后
    assert result.order_id is None
```

### 集成测试契约

```python
async def test_both_orders_fail_no_legging():
    """双边订单失败不应触发单腿持仓"""
    ext_result = {"success": False, "order_id": None}
    lit_result = {"success": False, "order_id": None}

    result = await executor.execute_concurrent_orders(...)

    assert result.is_both_failed == True
    assert result.is_legging == False  # 修复后
    assert result.is_both_filled == False
```

---

## Migration Guide

### 从011-fix-lighter-hedge升级

如果有代码依赖于011版本的旧行为：

1. **Extended IOC订单**：
   ```python
   # 旧代码（阻塞等待）
   result = await extended.place_open_order(...)
   # 后续代码依赖立即的状态查询

   # 新代码（需要手动查询）
   result = await extended.place_open_order(...)
   if result.success:
       # 手动查询状态（如果需要）
       order_info = await extended.get_order_info(result.order_id)
   ```

2. **Lighter订单**：
   ```python
   # 旧代码
   result = await lighter.place_open_order(...)
   if result.success:  # 可能为True但order_id=None
       process_order(result.order_id)

   # 新代码
   result = await lighter.place_open_order(...)
   if result.success and result.order_id:  # 验证order_id
       process_order(result.order_id)
   ```
