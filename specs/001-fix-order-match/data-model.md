# 数据模型: 订单更新缓存系统

**功能分支**: 001-fix-order-match
**创建日期**: 2026-01-09

---

## 概述

本文档描述用于解决WebSocket竞态条件的订单更新缓存系统的数据模型。

---

## 核心实体

### 1. OrderUpdateCache (订单更新缓存)

**描述**: 临时存储WebSocket回调中到达但在`pending_orders`中找不到的订单更新消息

**属性**:

| 属性名 | 类型 | 描述 | 示例值 |
|--------|------|------|--------|
| `order_id` | str | 订单唯一标识符 | "2009619315649257472" |
| `status` | str | 订单状态 | "FILLED", "PARTIALLY_FILLED", "OPEN", "CANCELED" |
| `side` | str | 订单方向 | "buy", "sell" |
| `size` | Decimal | 订单数量 | Decimal("0.01") |
| `price` | Decimal | 成交价格 | Decimal("3094.3") |
| `contract_id` | str | 合约标识符 | "ETH-USD" |
| `filled_size` | Decimal | 已成交数量 | Decimal("0.01") |
| `order_type` | str | 订单类型 | "OPEN", "CLOSE" |
| `timestamp` | float | 缓存时间戳 | 1704808356.672 |

**验证规则**:
- `order_id`: 必须非空字符串
- `status`: 必须是有效状态之一
- `size` 和 `filled_size`: 必须 >= 0
- `timestamp`: 必须是当前时间 ±300秒内

**状态转换**:
```
NEW → OPEN → PARTIALLY_FILLED → FILLED
             ↓
           CANCELED
```

---

### 2. PendingUpdateQueue (待处理队列)

**描述**: 按时间顺序排列的订单更新消息队列

**属性**:

| 属性名 | 类型 | 描述 | 默认值 |
|--------|------|------|--------|
| `updates` | Dict[str, List[CacheEntry]] | 订单ID到缓存更新列表的映射 | {} |
| `max_size` | int | 最大缓存订单数量 | 100 |
| `ttl` | int | 缓存生存时间（秒） | 300 |
| `max_updates_per_order` | int | 每订单最大更新数 | 10 |

**CacheEntry 结构**:
```python
{
    "order_data": OrderUpdateCache,
    "timestamp": float
}
```

**操作**:

| 操作 | 描述 | 复杂度 |
|------|------|--------|
| `add(order_id, order_data)` | 添加订单更新到缓存 | O(1) |
| `get(order_id)` | 获取指定订单的缓存 | O(1) |
| `remove(order_id)` | 删除指定订单的缓存 | O(1) |
| `cleanup_expired()` | 清理过期的缓存 | O(n) |
| `cleanup_completed()` | 清理已完成订单的缓存 | O(n) |

**约束**:
- 单个订单最多缓存10条更新
- 总共最多缓存100个订单
- 缓存条目5分钟后过期

---

### 3. CircuitBreakerState (熔断状态)

**描述**: 系统交易状态标志，防止在存在未对冲仓位时继续交易

**属性**:

| 属性名 | 类型 | 描述 | 示例值 |
|--------|------|------|--------|
| `is_tripped` | bool | 熔断是否已触发 | False |
| `reason` | str | 熔断原因 | "Lighter对冲失败: 订单2009619315649257472" |
| `trip_time` | datetime | 熔断触发时间 | datetime(2026, 1, 9, 21, 33, 14) |
| `uncleared_positions` | List[Dict] | 未对冲仓位列表 | [{"exchange": "extended", "order_id": "..."}] |
| `manual_override` | bool | 人工是否已覆盖熔断 | False |

**状态转换**:
```
NORMAL (is_tripped=False)
    ↓ 检测到未对冲仓位
TRIPPED (is_tripped=True)
    ↓ 人工确认 / 仓位清理
NORMAL
```

---

## 关系图

```
┌─────────────────────────────────────────────────────────┐
│                    SpreadOrderManager                    │
│  ┌─────────────────────────────────────────────────────┐│
│  │ current_order_id: Optional[str]                     ││
│  │ current_order_status: Optional[str]                 ││
│  └─────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────┐│
│  │              PendingUpdateQueue                      ││
│  │  ┌─────────────────────────────────────────────┐   ││
│  │  │ _pending_updates: Dict[str, List[CacheEntry]]│   ││
│  │  │   "order_1": [entry1, entry2, ...]           │   ││
│  │  │   "order_2": [entry1, ...]                   │   ││
│  │  └─────────────────────────────────────────────┘   ││
│  │  _update_lock: asyncio.Lock                        ││
│  │  _cache_ttl: int = 300                             ││
│  │  _max_cache_size: int = 100                         ││
│  │  _max_updates_per_order: int = 10                   ││
│  └─────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────┐│
│  │              CircuitBreakerState                    ││
│  │  is_tripped: bool                                   ││
│  │  reason: str                                        ││
│  │  uncleared_positions: List[Dict]                    ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
           │                           │
           ▼                           ▼
┌──────────────────┐         ┌──────────────────┐
│  ExtendedClient  │         │  HedgeManager    │
│  handle_account()│         │  place_hedge()   │
└──────────────────┘         └──────────────────┘
```

---

## 数据流

### 场景1: 正常流程（无竞态条件）

```
1. place_spread_maker_order()
   ↓
2. extended_client.place_open_order()
   ↓
3. SDK返回成功，设置 current_order_id
   ↓
4. _apply_pending_updates(order_id) - 无缓存
   ↓
5. WebSocket消息到达
   ↓
6. current_order_id 已设置，直接应用更新
   ↓
7. wait_for_fill() 检测到成交
   ↓
8. 触发对冲逻辑
```

### 场景2: 竞态条件（WebSocket早于订单ID设置）

```
1. place_spread_maker_order()
   ↓
2. extended_client.place_open_order()
   ↓
3. 【WebSocket消息到达】FILLED
   ↓
4. current_order_id = None → 缓存更新
   ↓
5. SDK返回成功，设置 current_order_id
   ↓
6. _apply_pending_updates(order_id) - 应用缓存
   ↓
7. wait_for_fill() 检测到成交
   ↓
8. 触发对冲逻辑
```

### 场景3: 熔断触发

```
1. Extended订单成交
   ↓
2. Lighter对冲订单失败
   ↓
3. 检测到未对冲仓位
   ↓
4. 记录警告到 trade.log
   ↓
5. 设置 is_tripped = True
   ↓
6. 停止处理新的套利机会
   ↓
7. 人工确认后恢复
```

---

## 性能考虑

### 内存使用

| 组件 | 估算 | 说明 |
|------|------|------|
| 单个CacheEntry | ~200 bytes | 订单数据结构 |
| 最大缓存（100订单 × 10更新） | ~200 KB | 可接受 |
| 熔断状态 | ~1 KB | 可忽略 |

**总计**: ~200 KB，对内存影响可忽略

### 延迟分析

| 操作 | 目标延迟 | 当前延迟 |
|------|----------|----------|
| 缓存查询 | < 1ms | O(1) 字典查找 |
| 缓存应用 | < 50ms | 取决于更新数量 |
| 熔断触发 | < 100ms | 简单状态设置 |

### 并发安全

- 使用 `asyncio.Lock` 保护 `_pending_updates`
- 确保只有一个协程同时修改缓存
- WebSocket回调是异步的，但受锁保护

---

## 测试数据

### 测试用例1: 竞态条件

```python
# 模拟WebSocket消息在订单ID设置前到达
order_data = {
    'order_id': '2009619315649257472',
    'status': 'FILLED',
    'side': 'buy',
    'size': '0.01',
    'price': '3094.3',
    'contract_id': 'ETH-USD',
    'filled_size': '0.01',
    'order_type': 'OPEN'
}

# 在 current_order_id = None 时调用
order_manager.update_order_status(order_data)
# 预期: 更新被缓存

# 设置订单ID
order_manager.current_order_id = '2009619315649257472'
# 应用缓存
await order_manager._apply_pending_updates('2009619315649257472')
# 预期: 状态更新为 FILLED
assert order_manager.current_order_status == 'FILLED'
```

### 测试用例2: 缓存TTL

```python
# 添加一个6秒前的缓存
old_time = time.time() - 360  # 6分钟前
cache_entry = {
    'order_data': {...},
    'timestamp': old_time
}

# 清理过期缓存
await order_manager._cleanup_cache()
# 预期: 旧缓存被删除
assert '2009619315649257472' not in order_manager._pending_updates
```

---

## 监控指标

### 缓存统计

| 指标 | 描述 | 目标 |
|------|------|------|
| `cache_hits` | 缓存命中次数 | 监控 |
| `cache_misses` | 缓存未命中次数 | 监控 |
| `hit_rate` | 缓存命中率 | > 50% |
| `pending_queue_size` | 待处理队列大小 | < 10 |

### 熔断统计

| 指标 | 描述 | 目标 |
|------|------|------|
| `trips_count` | 熔断触发次数 | 0 |
| `avg_trip_duration` | 平均熔断持续时间 | < 1小时 |
| `uncleared_positions_count` | 未对冲仓位数量 | 0 |

---

## 依赖关系

### 外部依赖

- `asyncio`: 异步编程支持
- `decimal.Decimal`: 精确的金融数值计算
- `logging`: 日志记录
- `time`: 时间戳和TTL计算

### 内部依赖

- `spread.config.SpreadArbConfig`: 配置对象
- `exchanges.extended.ExtendedClient`: Extended客户端
- `spread.hedge_manager.HedgeManager`: 对冲管理器
