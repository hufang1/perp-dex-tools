# Order Update Processing Contract

**Feature**: 006-fix-lighter-close
**Module**: `spread/order_manager.py`
**Method**: `SpreadOrderManager.update_order_status()`
**Version**: 1.0 (修复CLOSE订单处理)

## 方法签名

```python
def update_order_status(self, order_data: Dict[str, Any]) -> None:
    """
    更新订单状态 (由 WebSocket 回调调用)

    Args:
        order_data: 订单数据
    """
```

## 输入规范

### order_data 结构

| 字段 | 类型 | 必需 | 描述 | 示例 |
|------|------|------|------|------|
| `order_id` | str | ✅ | 订单唯一标识符 | "2009608496505368576" |
| `status` | str | ✅ | 订单状态 | "FILLED", "OPEN", "PARTIALLY_FILLED", "CANCELLED" |
| `filled_size` | str | ✅ | 已成交数量（字符串格式） | "0.010" |
| `price` | str | ⚠️ | 成交价格（成交时必需） | "3082.8" |
| `order_type` | str | ⚠️ | 订单类型 | "OPEN", "CLOSE" |
| `side` | str | ⚠️ | 订单方向 | "buy", "sell" |
| `contract_id` | str | ❌ | 合约标识符 | "ETH-USD" |

✅ 必需字段
⚠️ 条件必需
❌ 可选字段

## 输出规范

### 返回值

- **类型**: `None`
- **副作用**: 更新实例状态

### 状态修改

当订单更新被应用时，以下实例变量被更新：

| 变量 | 类型 | 更新条件 | 描述 |
|------|------|----------|------|
| `current_order_status` | Optional[str] | order_id匹配时 | 更新为订单状态 |
| `filled_quantity` | Decimal | filled_size > 0时 | 更新为成交数量 |
| `filled_price` | Decimal | filled_size > 0时 | 更新为成交价格 |

## 行为规范

### 处理流程

```
1. 提取order_id
   ↓
2. 【本功能修复】移除CLOSE订单忽略逻辑
   修复前: if order_type == 'CLOSE': return
   修复后: 不区分OPEN/CLOSE，统一处理
   ↓
3. 检查current_order_id是否已设置
   ├─ 未设置: 缓存更新 (_add_pending_update)
   └─ 已设置: 继续
   ↓
4. 检查order_id是否匹配current_order_id
   ├─ 不匹配: 缓存更新 (_add_pending_update)
   └─ 匹配: 继续
   ↓
5. 应用更新
   ├─ 更新current_order_status
   ├─ 如果filled_size > 0:
   │   ├─ 更新filled_quantity
   │   └─ 更新filled_price
   └─ 记录日志
```

### 订单类型处理

**修复前**:
```python
order_type = order_data.get('order_type', '')
if order_type == 'CLOSE':
    # 关闭订单不更新maker_order的状态
    return
```

**修复后**:
```python
# 移除CLOSE订单忽略逻辑
# CLOSE订单与OPEN订单同样处理
```

### 竞态条件处理

**场景**: WebSocket推送订单更新时，`current_order_id`尚未设置

**处理**:
1. 调用`_add_pending_update(order_id, order_data)`缓存更新
2. 在`place_spread_maker_order`设置`current_order_id`后立即调用`_apply_pending_updates(order_id)`
3. 按时间戳升序应用缓存的更新

### 缓存机制

**缓存条目结构**:
```python
{
    "order_data": Dict[str, Any],  # 原始订单数据
    "timestamp": float            # Unix时间戳
}
```

**缓存限制**:
- TTL: 300秒
- 最大缓存订单数: 100
- 每订单最大更新数: 10

## 异常处理

### 原则

- **不抛出异常**: 所有错误通过日志记录，不影响主流程
- **防御性编程**: 字段访问使用`.get()`方法，提供默认值
- **类型安全**: 使用`Decimal(str())`确保数值转换

### 异常场景

| 场景 | 处理方式 |
|------|----------|
| order_id缺失 | 记录错误日志，返回 |
| filled_size无法转换 | 记录警告日志，使用默认值0 |
| price缺失或无效 | 记录警告日志，使用默认值0 |
| 缓存应用失败 | 记录错误日志，继续执行 |

## 日志规范

### 日志级别

| 级别 | 场景 | 示例 |
|------|------|------|
| INFO | 订单状态更新成功 | "✅ 订单状态更新: 2009608496505368576 -> FILLED 已成交: 0.0100 @ 3082.80" |
| INFO | 应用缓存更新 | "✅ 应用缓存的订单更新: order_id=2009608496505368576, status=FILLED" |
| DEBUG | 缓存订单更新 | "[DEBUG] 缓存订单更新: order_id=2009608496505368576, status=FILLED" |
| WARNING | 订单ID不匹配但缓存 | "[DEBUG] 订单ID不匹配: 缓存更新" |
| WARNING | 竞态条件检测 | "⚡ 检测到竞态条件: 缓存订单更新" |
| ERROR | order_id缺失 | "❌ 订单数据缺少order_id字段" |

## 测试合约

### 单元测试要求

**测试用例**:
1. CLOSE订单更新正常处理
2. OPEN订单更新正常处理
3. 竞态条件：订单更新在订单ID设置前到达
4. 订单ID不匹配时的缓存行为
5. filled_size为0时不更新状态
6. 多个订单更新的顺序应用

**预期行为**:
- CLOSE订单与OPEN订单处理方式相同
- 竞态条件通过缓存机制正确处理
- 状态按正确顺序更新

### 集成测试要求

**测试场景**:
1. 完整平仓流程：Extended成交 → Lighter平仓
2. 强制平仓流程：持仓超时触发平仓
3. 多个套利对同时平仓

**预期结果**:
- Extended平仓订单成交状态正确识别
- Lighter平仓订单成功执行
- 套利对从open_pairs移除

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-01-09 | 初始版本，修复CLOSE订单处理逻辑 |

## 依赖

### 内部依赖

- `SpreadArbConfig`: 配置对象
- `asyncio.Lock`: 并发锁
- `Decimal`: 数值精度

### 外部依赖

- `logging`: 日志记录
- `time`: 时间戳
- `typing.Dict`, `typing.Any`: 类型提示

## 注意事项

1. **线程安全**: `_update_lock`保护缓存和状态更新的并发访问
2. **状态重置**: `place_spread_maker_order`开始时重置状态，防止不同订单的状态混淆
3. **订单ID匹配**: 只有匹配`current_order_id`的订单更新才会被应用
4. **缓存应用时机**: 设置`current_order_id`后立即应用缓存，确保不丢失更新
