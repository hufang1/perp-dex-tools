# API Contracts: 内部API契约

**Feature**: 001-fix-lighter-api
**Date**: 2026-01-07

---

## 概述

本文档定义了修复过程中涉及的内部API契约。这些是模块之间的接口，不涉及外部HTTP API。

---

## 1. LighterClient.get_order_info()

**模块**: `exchanges/lighter.py`
**方法**: `async def get_order_info(self, order_id: str) -> Optional[OrderInfo]`

**输入**:
```python
order_id: str  # 订单ID (可能是client_order_index或order_index)
```

**输出**:
```python
Optional[OrderInfo]  # 订单信息，如果查询失败返回None
```

**OrderInfo结构**:
```python
class OrderInfo:
    order_id: str          # 订单ID
    side: str             # 'buy' 或 'sell'
    size: Decimal         # 订单数量
    price: Decimal        # 成交价格
    status: str           # 订单状态
    filled_size: Decimal  # 已成交数量
    remaining_size: Decimal  # 剩余数量
    cancel_reason: str    # 取消原因（如有）
```

**契约**:
1. **输入验证**: `order_id`不能为空
2. **输出保证**:
   - 如果订单存在且可查询，返回`OrderInfo`
   - 如果订单不存在或查询失败，返回`None`
3. **副作用**: 无（只读操作）
4. **性能**: <2秒返回
5. **错误处理**:
   - 不抛出异常（捕获所有异常并返回`None`）
   - 记录ERROR级别的日志

**实现顺序（回退机制）**:
1. 检查`self.current_order`（WebSocket更新）
2. 调用`order_api.account_inactive_orders()`（REST API）
3. 从持仓推断（最后手段）

**修复前**:
```python
orders_response = await order_api.account_active_orders(  # ❌ 错误的方法名
    account_index=self.account_index,
    market_id=self.config.contract_id,
    auth=auth_token
)
```

**修复后**:
```python
orders_response = await order_api.account_inactive_orders(  # ✅ 正确的方法名
    account_index=self.account_index,
    market_id=self.config.contract_id,
    auth=auth_token
)
```

---

## 2. SpreadArbitrageBot._reconciliation_loop()

**模块**: `spread/bot.py`
**方法**: `async def _reconciliation_loop(self)`

**输入**: 无

**输出**: 无（纯副作用）

**契约**:
1. **执行频率**: 每`reconciliation_interval`秒（默认60）
2. **副作用**:
   - 记录对账日志
   - 更新内部状态（`is_paused`, `pause_until`）
   - 可能触发自动平仓（如果启用）
3. **异常处理**: 捕获所有异常，记录ERROR日志，继续运行
4. **性能**: <1秒完成一次对账
5. **日志**:
   - INFO: 正常对账结果
   - WARNING: 轻微不平衡
   - ERROR: 严重不平衡

**日志格式**:
```text
INFO: 持仓对账: Extended多头$35.50, Lighter空头$95.72, 净暴露-$60.22, 不平衡63.2%
ERROR: 🚨 持仓不平衡超过阈值! 差异63.2% > 20%
ERROR: 建议平仓: Lighter空头 0.03 ETH
```

---

## 3. HedgeManager.execute_hedge()

**模块**: `spread/hedge_manager.py`
**方法**: `async def execute_hedge(self, side: str, quantity: Decimal, expected_price: Decimal)`

**输入**:
```python
side: str              # 'buy' 或 'sell'
quantity: Decimal      # 对冲数量
expected_price: Decimal # 预期成交价格
```

**输出**:
```python
Dict[str, Any]  # {
    #   'success': bool,
    #   'order_id': str,
    #   'filled_price': Decimal,
    #   'filled_quantity': Decimal,
    #   'slippage': Decimal,
    #   'error': str (如果失败)
    # }
```

**契约**:
1. **输入验证**:
   - `side`必须是'buy'或'sell'
   - `quantity`必须>0
   - `expected_price`必须>0
2. **输出保证**:
   - `success`为True时，`filled_price`和`filled_quantity`有效
   - `success`为False时，`error`字段包含错误信息
3. **性能**: <10秒完成（包括重试）
4. **重试**: 最多3次，间隔1秒
5. **滑点容忍度**: 配置化（默认0.1%）

**已在之前会话修复**:
- 等待WebSocket订单更新（最多5秒轮询）
- 检查`current_order`状态
- 更好的错误日志

---

## 4. 配置参数契约

### 4.1 SpreadArbConfig (新增参数)

**模块**: `spread/config.py`

**新增字段**:

| 参数名 | 类型 | 默认值 | 约束 | 说明 |
|--------|------|--------|------|------|
| `max_unhedged_positions` | int | 0 | >=0 | 最大允许未对冲持仓数量，0=严格禁止 |
| `auto_close_unhedged` | bool | False | - | 是否自动平仓未对冲持仓 |
| `unhedged_position_timeout` | int | 300 | >0 | 未对冲持仓超时(秒) |
| `hedge_failure_threshold` | Decimal | 0.30 | (0,1] | 对冲失败率阈值(30%) |
| `hedge_failure_window` | int | 10 | >0 | 对冲失败率统计窗口 |
| `enable_reconciliation` | bool | True | - | 启用持仓对账 |
| `reconciliation_interval` | int | 60 | >0 | 对账间隔(秒) |

**验证规则**:
```python
assert max_unhedged_positions >= 0
assert 0 < hedge_failure_threshold <= 1
assert unhedged_position_timeout > 0
assert hedge_failure_window > 0
assert reconciliation_interval > 0
```

---

## 数据契约

### 持仓对账记录格式

```python
{
    "timestamp": 1704600000.123,
    "extended_position_value": "35.50",
    "extended_quantity": "0.011",
    "extended_side": "buy",
    "lighter_position_value": "95.72",
    "lighter_quantity": "-0.03",
    "lighter_side": "sell",
    "net_exposure": "-60.22",
    "imbalance_ratio": "0.632",
    "is_imbalanced": true,
    "alert_triggered": true
}
```

### 不平衡警告格式

```python
{
    "timestamp": 1704600000.789,
    "extended_value": "35.50",
    "lighter_value": "95.72",
    "imbalance_amount": "60.22",
    "imbalance_ratio": "0.632",
    "suggested_action": "平仓 Lighter空头 0.03 ETH",
    "auto_closed": false,
    "close_result": null
}
```

---

## 错误码契约

| 错误码 | 错误消息 | 严重性 | 处理方式 |
|--------|---------|--------|---------|
| `E001` | "OrderApi object has no attribute 'account_active_orders'" | ERROR | 使用正确的方法名 |
| `E002` | "Unable to get order info" | ERROR | 重试或回退到持仓推断 |
| `E003` | "Position imbalance exceeded threshold" | ERROR | 触发熔断，建议平仓 |
| `E004` | "Auto close failed" | ERROR | 保持熔断，手动介入 |
| `E005` | "Hedge failure rate too high" | WARNING | 检查连接，考虑暂停 |
