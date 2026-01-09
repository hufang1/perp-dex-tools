# API契约: 订单缓存系统内部接口

**功能分支**: 001-fix-order-match
**创建日期**: 2026-01-09

---

## 概述

本文档定义订单缓存系统的内部API接口。这些接口主要用于：

1. `SpreadOrderManager` 内部的订单更新缓存
2. WebSocket回调处理
3. 熔断机制接口

---

## 接口定义

### 1. OrderManager.update_order_status()

**描述**: 处理来自WebSocket的订单更新

**签名**:
```python
def update_order_status(self, order_data: Dict[str, Any]) -> None
```

**输入参数**:

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `order_data` | Dict[str, Any] | 是 | 订单数据 |
| `order_data.order_id` | str | 是 | 订单ID |
| `order_data.status` | str | 是 | 订单状态 (FILLED, PARTIALLY_FILLED, OPEN, CANCELED) |
| `order_data.side` | str | 是 | 订单方向 (buy, sell) |
| `order_data.size` | str | 是 | 订单数量 |
| `order_data.price` | str | 是 | 订单价格 |
| `order_data.contract_id` | str | 是 | 合约ID |
| `order_data.filled_size` | str | 是 | 已成交数量 |
| `order_data.order_type` | str | 是 | 订单类型 (OPEN, CLOSE) |

**行为**:
1. 检查 `current_order_id` 是否为 None
2. 如果为 None，缓存更新到 `_pending_updates`
3. 如果不为 None 且匹配，直接应用更新
4. 记录详细日志

**返回值**: 无

**异常**: 不抛出异常

---

### 2. OrderManager._apply_pending_updates()

**描述**: 应用指定订单的缓存更新

**签名**:
```python
async def _apply_pending_updates(self, order_id: str) -> None
```

**输入参数**:

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `order_id` | str | 是 | 订单ID |

**行为**:
1. 使用 `_update_lock` 保护操作
2. 检查 `_pending_updates` 中是否有该订单的缓存
3. 如果有，按时间戳升序排序并依次应用
4. 更新 `current_order_status`, `filled_quantity`, `filled_price`
5. 记录缓存统计（命中率等）

**返回值**: 无

**日志**:
- `🔍 检查缓存: order_id={order_id}`
- `✅ 找到缓存: order_id={order_id}, 数量={n}`
- `❌ 无缓存更新: order_id={order_id}`
- `✅ 应用缓存的订单更新: ...`

---

### 3. OrderManager._add_pending_update()

**描述**: 添加订单更新到缓存

**签名**:
```python
def _add_pending_update(self, order_id: str, order_data: Dict[str, Any]) -> None
```

**输入参数**:

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `order_id` | str | 是 | 订单ID |
| `order_data` | Dict[str, Any] | 是 | 订单数据 |

**行为**:
1. 创建缓存条目（包含 order_data 和 timestamp）
2. 初始化该订单的缓存列表（如果不存在）
3. 限制每个订单最多 10 条更新
4. 添加新更新到列表末尾
5. 记录调试日志

**约束**:
- 每个订单最多缓存 10 条更新
- 超出限制时删除最旧的更新

---

### 4. OrderManager._cleanup_cache()

**描述**: 清理过期和超限的缓存

**签名**:
```python
async def _cleanup_cache(self) -> None
```

**输入参数**: 无

**行为**:
1. 使用 `_update_lock` 保护操作
2. 清理超过 TTL（5分钟）的缓存
3. 清理已完成订单（FILLED, CANCELED）的缓存
4. 如果总缓存数超过限制（100），删除最旧的
5. 记录警告日志

**清理条件**:
- TTL 过期：`now - timestamp > 300` 秒
- 订单完成：status 为 FILLED 或 CANCELED
- 总数超限：`len(_pending_updates) > 100`

---

### 5. CircuitBreaker.trigger()

**描述**: 触发熔断

**签名**:
```python
def trigger(self, reason: str, position: Dict[str, Any]) -> None
```

**输入参数**:

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `reason` | str | 是 | 熔断原因 |
| `position` | Dict[str, Any] | 是 | 未对冲仓位信息 |

**行为**:
1. 设置 `is_tripped = True`
2. 记录 `trip_time` 为当前时间
3. 添加未对冲仓位到 `uncleared_positions`
4. 记录错误日志到 `logs/trade.log`
5. 禁止新的套利机会处理

**返回值**: 无

---

### 6. CircuitBreaker.reset()

**描述**: 重置熔断状态

**签名**:
```python
def reset(self, manual_override: bool = False) -> None
```

**输入参数**:

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `manual_override` | bool | 否 | 是否为人工覆盖（默认 False） |

**行为**:
1. 检查是否所有未对冲仓位已清理
2. 如果是，重置 `is_tripped = False`
3. 清空 `uncleared_positions`
4. 如果是人工覆盖，设置 `manual_override = True`
5. 记录信息日志

**返回值**:
- `True`: 熔断已重置
- `False`: 熔断无法重置（仍有未对冲仓位）

---

## 数据结构

### CacheEntry

```python
{
    "order_data": {
        "order_id": str,
        "status": str,
        "side": str,
        "size": str,
        "price": str,
        "contract_id": str,
        "filled_size": str,
        "order_type": str
    },
    "timestamp": float  # Unix timestamp
}
```

### UnclearedPosition

```python
{
    "exchange": str,  # "extended" or "lighter"
    "order_id": str,
    "side": str,  # "buy" or "sell"
    "quantity": str,
    "price": str,
    "detected_at": str  # ISO 8601 timestamp
}
```

---

## 日志格式

### 竞态条件检测

```
⚡ 检测到竞态条件: 缓存订单更新, order_id={order_id}, current_order_id=None
```

### 缓存应用

```
✅ 找到缓存: order_id={order_id}, 数量={n}
✅ 应用缓存的订单更新: order_id={order_id}, status={status}, filled_size={qty}, price={price}
📊 缓存统计: 命中率={rate}%, 命中={hits}, 未命中={misses}
```

### 缓存未命中

```
❌ 无缓存更新: order_id={order_id}
```

### 熔断触发

```
🚨 熔断触发: {reason}
未对冲仓位: {position_details}
已记录到 logs/trade.log
```

### 熔断重置

```
✅ 熔断已重置
方式: {自动/人工覆盖}
```

---

## 错误码

| 错误码 | 描述 | 处理方式 |
|--------|------|----------|
| `CACHE_FULL` | 缓存已满 | 删除最旧的缓存 |
| `CACHE_EXPIRED` | 缓存已过期 | 清理过期缓存 |
| `ORDER_NOT_FOUND` | 订单未找到 | 继续缓存，等待订单ID设置 |
| `CIRCUIT_TRIPPED` | 熔断已触发 | 停止新的交易 |

---

## 性能要求

| 操作 | 最大延迟 | 备注 |
|------|----------|------|
| `update_order_status` | < 1ms | 不应阻塞WebSocket回调 |
| `_apply_pending_updates` | < 50ms | 取决于缓存更新数量 |
| `_cleanup_cache` | < 100ms | 异步执行，不阻塞主流程 |
| `trigger` / `reset` | < 10ms | 简单状态设置 |

---

## 安全考虑

### 并发安全

- 所有对 `_pending_updates` 的访问都通过 `_update_lock` 保护
- WebSocket回调可能在任何时间到达，必须保证线程安全

### 数据一致性

- 缓存更新按时间戳升序应用，确保状态正确
- 完成的订单（FILLED, CANCELED）的缓存会被清理
- TTL 机制防止内存泄漏

### 故障恢复

- 熔断机制防止未对冲仓位累积
- 交易日志记录所有异常情况
- 人工确认机制确保安全恢复
