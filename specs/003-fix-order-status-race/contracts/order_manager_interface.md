# SpreadOrderManager 接口契约

**版本**: 1.1.0（添加缓存机制）
**日期**: 2026-01-07
**模块**: `spread.order_manager.SpreadOrderManager`

## 概述

本文档定义了 `SpreadOrderManager` 类的公共接口契约。本次修改添加了**订单状态缓存机制**以修复竞态条件bug，但**不改变公共接口**，仅修改内部实现。

## 类定义

```python
class SpreadOrderManager:
    """Extended 订单管理器"""

    def __init__(
        self,
        config: SpreadArbConfig,
        extended_client: ExtendedClient
    ) -> None:
        """初始化订单管理器"""
```

## 公共方法（无修改）

### 1. place_spread_maker_order()

在 Extended 下价差 Maker 单。

**签名**:
```python
async def place_spread_maker_order(
    self,
    side: str,
    price: Decimal,
    quantity: Decimal
) -> Dict[str, Any]
```

**参数**:

| 参数 | 类型 | 必填 | 约束 | 描述 |
|------|------|------|------|------|
| side | str | 是 | 'buy' 或 'sell' | 订单方向 |
| price | Decimal | 是 | > 0 | 挂单价格（内部未使用，由SDK决定） |
| quantity | Decimal | 是 | > 0 | 下单数量（币数） |

**返回值**:
```python
{
    'success': bool,          # 是否成功
    'order_id': str,          # 订单ID（成功时）
    'price': Decimal,         # 实际价格（成功时）
    'quantity': Decimal,      # 数量（成功时）
    'side': str,              # 方向（成功时）
    'error': str              # 错误信息（失败时）
}
```

**行为**:
1. 重置订单状态（`current_order_status`, `filled_quantity`, `filled_price`）
2. 调用 Extended SDK 下单
3. **[新增]** 设置 `current_order_id` 后检查并应用缓存更新
4. 返回下单结果

**异常**: 无异常抛出，错误通过返回值的 `error` 字段传递

**示例**:
```python
result = await order_manager.place_spread_maker_order(
    side='buy',
    price=Decimal('3251.4'),
    quantity=Decimal('0.01')
)

if result['success']:
    print(f"订单已提交: {result['order_id']}")
else:
    print(f"下单失败: {result['error']}")
```

---

### 2. wait_for_fill()

等待订单成交。

**签名**:
```python
async def wait_for_fill(
    self,
    order_id: str,
    timeout: int,
    allow_partial: bool = True
) -> Dict[str, Any]
```

**参数**:

| 参数 | 类型 | 必填 | 约束 | 描述 |
|------|------|------|------|------|
| order_id | str | 是 | 非空字符串 | 订单ID |
| timeout | int | 是 | > 0 | 超时时间（秒） |
| allow_partial | bool | 否 | - | 是否允许部分成交，默认True |

**返回值**:
```python
{
    'status': 'FILLED' | 'PARTIAL' | 'TIMEOUT' | 'CANCELLED',
    'filled_quantity': Decimal,
    'filled_price': Decimal,
    'remaining': Decimal
}
```

**状态**:

| 状态 | 描述 | filled_quantity | filled_price |
|------|------|-----------------|--------------|
| FILLED | 完全成交 | > 0 | > 0 |
| PARTIAL | 部分成交 | > 0 | > 0 |
| TIMEOUT | 等待超时 | 可能为0 | 可能为0 |
| CANCELLED | 订单已取消 | 可能为0 | 可能为0 |

**行为**:
1. 每500ms检查一次 `current_order_status`
2. 如果 `FILLED`，返回成功
3. 如果 `PARTIALLY_FILLED` 且 `allow_partial=True`，返回部分成交
4. 如果 `CANCELLED`，返回已取消
5. 如果超时，返回 `TIMEOUT`

**异常**: 无异常抛出

**示例**:
```python
result = await order_manager.wait_for_fill(
    order_id='2008773271629754368',
    timeout=10,
    allow_partial=True
)

if result['status'] == 'FILLED':
    print(f"完全成交: {result['filled_quantity']} @ {result['filled_price']}")
elif result['status'] == 'TIMEOUT':
    print("订单超时")
```

---

### 3. cancel_order()

取消订单。

**签名**:
```python
async def cancel_order(self, order_id: str) -> bool
```

**参数**:

| 参数 | 类型 | 必填 | 约束 | 描述 |
|------|------|------|------|------|
| order_id | str | 是 | 非空字符串 | 订单ID |

**返回值**:
- `True`: 取消成功
- `False`: 取消失败

**行为**:
1. 调用 Extended SDK 取消订单
2. 返回取消结果

**异常**: 无异常抛出

**示例**:
```python
success = await order_manager.cancel_order('2008773271629754368')
if success:
    print("订单已取消")
else:
    print("取消失败")
```

---

### 4. update_order_status()

更新订单状态（由 WebSocket 回调调用）。

**签名**:
```python
def update_order_status(self, order_data: Dict[str, Any]) -> None
```

**参数**:

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| order_id | str | 是 | 订单ID |
| status | str | 是 | 订单状态 |
| order_type | str | 否 | 订单类型（OPEN/CLOSE） |
| filled_size | Decimal | 否 | 已成交数量 |
| price | Decimal | 否 | 成交价格 |
| side | str | 否 | 方向 |
| contract_id | str | 否 | 合约ID |

**行为**:
1. 检查 `order_type`，如果是 `CLOSE`，直接返回
2. **[修改]** 检查 `current_order_id`:
   - 如果 `None`，缓存更新
   - 如果与 `order_id` 不匹配，也尝试缓存
   - 如果匹配，应用更新
3. 更新 `current_order_status`, `filled_quantity`, `filled_price`

**异常**: 无异常抛出

**示例**:
```python
# WebSocket回调调用
order_manager.update_order_status({
    'order_id': '2008773271629754368',
    'status': 'FILLED',
    'order_type': 'OPEN',
    'filled_size': '0.010',
    'price': '3251.4'
})
```

---

## 私有方法（新增）

### _apply_pending_updates()

应用指定订单的缓存更新。

**签名**:
```python
async def _apply_pending_updates(self, order_id: str) -> None
```

**行为**:
1. 获取该订单的所有缓存更新
2. 按时间戳排序
3. 依次应用每个更新
4. 清理缓存

### _cleanup_cache()

清理过期和超限的缓存。

**签名**:
```python
async def _cleanup_cache(self) -> None
```

**行为**:
1. 清理超过TTL的缓存
2. 清理超过最大限制的缓存
3. 清理已完成订单的缓存

---

## 并发安全性

### 线程安全

- `update_order_status()` 可以被 WebSocket 回调并发调用
- `place_spread_maker_order()` 和 `wait_for_fill()` 是异步的
- **[新增]** 使用 `asyncio.Lock` 保护共享状态

### 锁顺序

1. 获取 `_update_lock`
2. 访问/修改 `_pending_updates`
3. 访问/修改 `current_order_id`, `current_order_status`
4. 释放 `_update_lock`

---

## 性能约束

| 操作 | 最大耗时 | 备注 |
|------|----------|------|
| place_spread_maker_order() | 500ms | 主要耗时在Extended SDK |
| wait_for_fill() | 取决于成交 | 最小500ms检查间隔 |
| update_order_status() | 1ms | 不阻塞WebSocket回调 |
| _apply_pending_updates() | 10ms | 批量应用缓存 |

---

## 错误处理

### 输入验证

| 场景 | 处理方式 |
|------|----------|
| order_id 为 None | 忽略更新 |
| order_id 类型错误 | 尝试转换为字符串 |
| status 无效 | 仍接受并记录 |

### 边界情况

| 场景 | 处理方式 |
|------|----------|
| 订单更新早于 order_id 设置 | 缓存更新 |
| 订单完成后收到更新 | 忽略更新 |
| 缓存超过限制 | 清理最旧的缓存 |

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.1.0 | 2026-01-07 | 添加订单状态缓存机制，修复竞态条件bug |
| 1.0.0 | - | 初始版本 |
