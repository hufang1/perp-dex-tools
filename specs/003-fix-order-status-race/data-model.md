# Phase 1: 数据模型设计

**功能**: 修复套利机器人订单状态更新的竞态条件bug
**日期**: 2026-01-07

## 概述

本文档描述了修复竞态条件bug所需的数据模型。主要修改是在 `SpreadOrderManager` 类中添加订单状态缓存机制。

## 实体定义

### 1. 订单状态缓存条目 (PendingOrderUpdate)

存储单个订单的状态更新。

**属性**:

| 字段名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| order_data | Dict[str, Any] | 是 | 原始订单数据（来自WebSocket） |
| timestamp | float | 是 | 接收时间戳（Unix时间，秒） |

**验证规则**:
- `timestamp` 必须 > 0
- `order_data` 必须包含 `order_id` 字段
- `order_data` 必须包含 `status` 字段

**示例**:
```python
{
    "order_data": {
        "order_id": "2008773271629754368",
        "status": "FILLED",
        "side": "buy",
        "order_type": "OPEN",
        "size": "0.01",
        "price": "3251.4",
        "contract_id": "ETH-USD",
        "filled_size": "0.010"
    },
    "timestamp": 1736247044.053
}
```

---

### 2. 订单状态缓存 (PendingOrderUpdates)

存储同一订单的所有状态更新（按时间顺序）。

**类型**: `List[PendingOrderUpdate]`

**行为**:
- 按接收时间升序排列
- 去重：相同状态只保留最新的
- 最大长度：10个更新（防止异常情况）

**示例**:
```python
[
    {
        "order_data": {"status": "PARTIALLY_FILLED", "filled_size": "0.005", ...},
        "timestamp": 1736247043.500
    },
    {
        "order_data": {"status": "FILLED", "filled_size": "0.010", ...},
        "timestamp": 1736247044.053
    }
]
```

---

### 3. 缓存索引 (PendingUpdatesIndex)

按订单ID索引的缓存字典。

**类型**: `Dict[str, List[PendingOrderUpdate]]`

**行为**:
- Key: 订单ID（字符串）
- Value: 该订单的状态更新列表
- O(1) 查找、插入、删除

**示例**:
```python
{
    "2008773271629754368": [
        {"order_data": {...}, "timestamp": 1736247044.053}
    ],
    "2008773321807298560": [
        {"order_data": {...}, "timestamp": 1736247056.017}
    ]
}
```

---

### 4. 缓存元数据 (CacheMetadata)

缓存的配置和统计信息。

**属性**:

| 字段名 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| cache_ttl | int | 300 | 缓存生存时间（秒） |
| max_cache_size | int | 100 | 最大缓存订单数 |
| max_updates_per_order | int | 10 | 每个订单最大更新数 |

**统计信息**（运行时）:

| 字段名 | 类型 | 描述 |
|--------|------|------|
| total_cached | int | 当前缓存订单数 |
| total_updates | int | 当前缓存更新总数 |
| hit_count | int | 缓存命中次数（成功应用） |
| miss_count | int | 缓存未命中次数（订单已完成） |

---

## 类设计

### SpreadOrderManager（修改）

**现有属性**（无修改）:

```python
current_order_id: Optional[str]           # 当前订单ID
current_order_status: Optional[str]       # 当前订单状态
filled_quantity: Decimal                  # 已成交数量
filled_price: Decimal                     # 成交价格
```

**新增属性**:

```python
# 缓存存储
_pending_updates: Dict[str, List[Dict]]   # 待应用的订单更新缓存

# 并发控制
_update_lock: asyncio.Lock                # 保护缓存和订单状态的锁

# 缓存配置
_cache_ttl: int = 300                     # 缓存TTL（5分钟）
_max_cache_size: int = 100                # 最大缓存订单数
_max_updates_per_order: int = 10          # 每订单最大更新数

# 统计信息
_cache_hits: int = 0                      # 缓存命中次数
_cache_misses: int = 0                    # 缓存未命中次数
```

**新增方法**:

```python
async def _apply_pending_updates(self, order_id: str) -> None:
    """应用指定订单的缓存更新"""

async def _cleanup_cache(self) -> None:
    """清理过期和超限的缓存"""

async def _get_pending_updates(self, order_id: str) -> Optional[List[Dict]]:
    """获取指定订单的缓存更新"""

def _add_pending_update(self, order_id: str, order_data: Dict) -> None:
    """添加订单更新到缓存"""
```

**修改方法**:

```python
def __init__(self, config, extended_client):
    """初始化：添加缓存相关的属性"""

async def place_spread_maker_order(self, side, price, quantity) -> Dict:
    """下单后：检查并应用缓存更新"""

def update_order_status(self, order_data: Dict) -> None:
    """状态更新：处理早期到达的订单更新"""
```

---

## 状态转换图

### 订单状态转换

```
                    ┌─────────────────┐
                    │  下单前 (None)   │
                    └────────┬────────┘
                             │
                    [WebSocket收到FILLED]
                             │
                    ┌────────▼────────┐
                    │   缓存更新       │
                    │ current_order_id │
                    │   == None       │
                    └────────┬────────┘
                             │
              [place_spread_maker_order返回]
                             │
                    ┌────────▼────────┐
                    │ 设置order_id    │
                    │ 应用缓存更新    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  状态已更新      │
                    │ current_order_  │
                    │   status = FILLED│
                    └─────────────────┘
```

---

## 内存占用估算

### 单个缓存条目

```python
# 订单数据（约200字节）
order_data: Dict ≈ 200 bytes

# 时间戳（8字节）
timestamp: float = 8 bytes

# 总计
条目大小 ≈ 208 bytes
```

### 总缓存占用

| 场景 | 订单数 | 每订单更新数 | 内存占用 |
|------|--------|--------------|----------|
| 正常 | 1 | 1 | ~0.2 KB |
| 高频 | 10 | 3 | ~6 KB |
| 极限 | 100 | 5 | ~100 KB |

**结论**: 内存占用可忽略不计（< 1MB）

---

## 验证规则

### 输入验证

1. **订单ID**:
   - 必须是非空字符串
   - 必须与 `current_order_id` 类型一致

2. **订单数据**:
   - 必须包含 `order_id` 字段
   - 必须包含 `status` 字段
   - `status` 必须是有效值: `OPEN`, `FILLED`, `PARTIALLY_FILLED`, `CANCELLED`, `CANCELED`

3. **时间戳**:
   - 必须 > 0
   - 必须 <= 当前时间（允许1秒时钟偏差）

### 业务规则验证

1. **CLOSE类型订单**:
   - 不应该被缓存（立即返回）

2. **状态转换**:
   - FILLED之后不能再有其他状态
   - CANCELLED之后不能再有其他状态

3. **数量验证**:
   - `filled_size` 必须 <= `size`
   - `filled_size` 必须 >= 0

---

## 总结

本数据模型设计：
- ✅ 最小化修改：仅添加缓存相关属性和方法
- ✅ 向后兼容：不改变现有接口
- ✅ 内存安全：多层防护防止泄漏
- ✅ 高性能：O(1)查找，最小化锁持有时间
