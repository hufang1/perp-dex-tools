# Research: 修复订单执行超时和假阳性成交问题

**Feature**: 013-fix-order-timeout
**Date**: 2026-01-11
**Status**: Complete

---

## Research Summary

基于现有代码分析和用户日志，确认了两个根本原因：

1. **Extended超时**：`get_order_info()`方法最坏情况需要25秒（50次重试 × 0.5秒）
2. **Lighter假阳性**：`current_order.order_id`为`None`时仍返回`success=True`

---

## Decision 1: 跳过Extended `get_order_info()` 调用

**Decision**: IOC订单在SDK返回成功后立即返回，不调用`get_order_info()`

**Rationale**:
- `get_order_info()`使用阻塞的HTTP请求，最多重试50次，每次等待0.5秒
- 最坏情况需要25秒，远超500ms并发执行器超时
- IOC订单使用对手价（`best_ask`买单、`best_bid`卖单）会立即成交
- Post-Only订单仍需查询状态（检测是否被拒绝）

**Alternatives Considered**:
1. 减少`get_order_info()`重试次数 - 仍可能导致超时
2. 增加并发执行器超时 - 与性能目标冲突
3. 实现Extended WebSocket回调 - 超出范围

**Implementation**:
```python
if not post_only:  # IOC订单
    return OrderResult(success=True, order_id=order_id, ...)
# Post-Only订单继续查询状态
```

---

## Decision 2: 验证Lighter `order_id` 存在性

**Decision**: 只有当`current_order.order_id`不是`None`时才返回`success=True`

**Rationale**:
- 日志显示`success=True, order_id=None`，这是不可能的状态
- `current_order`可能在WebSocket回调中被设置，但`order_id`字段缺失
- 必须验证`order_id`存在性才能确认订单成功

**Alternatives Considered**:
1. 保持现有逻辑 - 导致假阳性和单腿持仓误报
2. 查询API验证所有订单 - 增加延迟
3. 使用`order_id`作为成功标志 - 选定方案

**Implementation**:
```python
if self.current_order is not None:
    if self.current_order.order_id is not None:
        return OrderResult(success=True, ...)
    else:
        # order_id为None，查询API验证
        self.logger.log("[警告] current_order存在但order_id为None", "WARNING")
```

---

## Decision 3: 使用 `get_inactive_orders()` 验证订单

**Decision**: 当`order_id`为`None`时，使用`get_inactive_orders()`查询订单状态

**Rationale**:
- `get_active_orders()`返回空列表（已确认）
- `get_inactive_orders()`可以查询已成交/已取消订单
- 适用于IOC订单场景（立即成交或取消）

**Alternatives Considered**:
1. 假设订单失败 - 可能错过实际成交的订单
2. 实现新的API端点 - 超出范围
3. 使用WebSocket确认 - 已有但不可靠

**Implementation**:
```python
inactive_orders = await self.get_inactive_orders(contract_id)
for order in inactive_orders:
    if order.order_id == order_result.order_id and order.status == 'FILLED':
        return OrderResult(success=True, ...)
```

---

## Decision 4: 增强错误日志格式

**Decision**: 日志必须包含：交易所、成功状态、订单ID、错误消息

**Rationale**:
- 当前日志只显示`success=False`，没有具体原因
- 用户日志显示`Extended: success=False, order_id=None, error=timeout`
- 需要统一格式便于问题诊断

**Alternatives Considered**:
1. 保持现有日志 - 问题诊断困难
2. 添加单独的错误日志文件 - 过度设计
3. 增强现有日志格式 - 选定方案

**Implementation**:
```python
self.logger.warning(
    f"⚠️ [单腿持仓] {success_side}: 成交, {fail_side}: 失败 | "
    f"Extended: success={ext_success}, order_id={ext_order_id}, error={ext_error} | "
    f"Lighter: success={lit_success}, order_id={lit_order_id}, error={lit_error}"
)
```

---

## Technical Findings

### Extended `get_order_info()` 性能分析

**代码位置**: `exchanges/extended.py:509-563`

```python
async def get_order_info(self, order_id: str) -> Optional[OrderInfo]:
    attempt = 0
    while not order_info and attempt < 50:  # 最多50次
        attempt += 1
        # ... HTTP请求 ...
        await asyncio.sleep(0.5)  # 每次等待0.5秒
    return order_info
```

**性能特征**:
- 最佳情况：1次重试 = 0.5秒
- 平均情况：10次重试 = 5秒
- 最坏情况：50次重试 = 25秒

**结论**: 必须跳过此调用才能满足500ms超时要求

---

### Lighter `current_order` 竞态条件分析

**代码位置**: `exchanges/lighter.py:224-239`

```python
# WebSocket回调
if order_data['client_order_index'] == self.current_order_client_id:
    current_order = OrderInfo(
        order_id=order_data.get('order_index'),  # 可能为None
        ...
    )
    self.current_order = current_order
```

**问题场景**:
1. WebSocket回调到达但`order_data['order_index']`缺失
2. `current_order.order_id`被设置为`None`
3. `place_open_order()`检查`current_order is not None`（True）
4. 返回`success=True, order_id=None`

**结论**: 必须验证`order_id`存在性

---

### `get_inactive_orders()` 可用性验证

**代码位置**: `exchanges/lighter.py:631-653`

```python
async def get_inactive_orders(self, contract_id: str) -> List[OrderInfo]:
    order_list = await self._fetch_orders_with_retry()
    # 转换为OrderInfo列表
    return contract_orders
```

**确认**:
- 方法已存在且正常工作
- 可以查询已成交/已取消订单
- 适用于IOC订单验证

---

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Extended订单实际未成交但返回成功 | 低 | 高 | WebSocket成交确认会修正状态 |
| Lighter API查询失败 | 中 | 中 | 添加异常处理和错误日志 |
| 性能回归 | 低 | 低 | 新API查询在现有代码中已使用 |

---

## Open Questions

**无** - 所有关键问题已通过代码分析和用户日志确认
