# Data Model: 修复Spread套利脚本价格同步问题

**Feature**: 001-fix-spread-price
**Date**: 2026-01-16

---

## 概述

本文档定义了修复spread套利脚本价格同步问题所涉及的数据模型。

---

## 核心数据模型

### PriceSnapshot（价格快照）

记录某一时刻两个交易所的BBO价格快照，用于确保价格同步和一致性验证。

#### 字段定义

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

@dataclass
class PriceSnapshot:
    """价格快照：记录某一时刻两个交易所的BBO价格

    用途：
    1. 确保两个交易所价格获取的时间差<10ms
    2. 计算带滑点保护的taker订单价格
    3. 验证价格一致性（ext买入价 < lig卖出价）
    """
    # Extended价格
    ext_bid: Decimal          # Ext买一价
    ext_ask: Decimal          # Ext卖一价
    ext_timestamp: float      # Ext价格获取时间戳（Unix timestamp）

    # Lighter价格
    lig_bid: Decimal          # Lig买一价
    lig_ask: Decimal          # Lig卖一价
    lig_timestamp: float      # Lig价格获取时间戳（Unix timestamp）

    # 元数据
    time_delta: float         # 两个时间戳之差的绝对值（秒）

    def is_valid(self) -> bool:
        """验证价格快照是否有效

        验证规则：
        1. 所有价格>0
        2. bid < ask（两边都是）
        3. time_delta < 0.01秒（10ms）

        Returns:
            bool: 价格快照是否有效
        """
        return (
            self.ext_bid > 0 and self.ext_ask > 0 and
            self.lig_bid > 0 and self.lig_ask > 0 and
            self.ext_bid < self.ext_ask and
            self.lig_bid < self.lig_ask and
            self.time_delta < 0.01
        )

    def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]:
        """计算taker订单价格（加入0.2%滑点保护）

        计算公式：
        - Ext买入价 = ext_ask * 1.002（加0.2%滑点）
        - Lig卖出价 = lig_bid * 0.998（减0.2%滑点）

        Returns:
            Tuple[Decimal, Decimal]: (ext_price, lig_price)
        """
        ext_price = self.ext_ask * Decimal('1.002')
        lig_price = self.lig_bid * Decimal('0.998')
        return ext_price, lig_price

    def validate_price_consistency(self) -> bool:
        """验证价格一致性（ext买入价 < lig卖出价）

        这是套利策略的核心验证：确保ext的买入成本低于lig的卖出成本

        Returns:
            bool: 价格是否一致（ext买入 < lig卖出）
        """
        ext_price, lig_price = self.calculate_taker_prices()
        return ext_price < lig_price
```

#### 使用示例

```python
# 创建价格快照
snapshot = PriceSnapshot(
    ext_bid=Decimal('3000.00'),
    ext_ask=Decimal('3000.50'),
    ext_timestamp=1640000000.000,
    lig_bid=Decimal('2999.50'),
    lig_ask=Decimal('3000.00'),
    lig_timestamp=1640000000.005,
    time_delta=0.005
)

# 验证快照
if not snapshot.is_valid():
    logger.warning(f"价格快照无效: time_delta={snapshot.time_delta*1000:.1f}ms")
    return

# 计算taker价格
ext_price, lig_price = snapshot.calculate_taker_prices()
logger.info(f"Taker价格: ext={ext_price:.2f}, lig={lig_price:.2f}")

# 验证价格一致性
if not snapshot.validate_price_consistency():
    logger.error(f"价差异常: ext={ext_price:.2f} >= lig={lig_price:.2f}")
    return
```

---

### OpenPositionRecord（扩展）

扩展现有的开仓记录模型，新增价格快照和实际成交价字段。

#### 新增字段

```python
@dataclass
class OpenPositionRecord:
    """开仓记录（扩展）"""
    # ... 现有字段保持不变 ...
    position_id: str
    open_time: float
    ext_price: Decimal         # 预期价格（用于计算）
    lig_price: Decimal         # 预期价格（用于计算）
    open_spread: Decimal
    quantity: Decimal
    ext_order_id: str
    lig_order_id: str
    is_active: bool

    # ========== 新增字段 ==========
    price_snapshot: PriceSnapshot  # 价格快照（新增）
    ext_execution_price: Decimal     # Ext实际成交价（新增）
    lig_execution_price: Decimal     # Lig实际成交价（新增）
    # =================================

    def get_slippage(self) -> Tuple[Decimal, Decimal]:
        """计算实际滑点（实际成交价 vs 预期价格）

        Returns:
            Tuple[Decimal, Decimal]: (ext_slippage, lig_slippage)
        """
        ext_slippage = abs(self.ext_execution_price - self.ext_price) / self.ext_price
        lig_slippage = abs(self.lig_execution_price - self.lig_price) / self.lig_price
        return ext_slippage, lig_slippage
```

#### 使用示例

```python
# 创建开仓记录（新增字段）
record = OpenPositionRecord(
    position_id=str(uuid.uuid4()),
    open_time=datetime.now().timestamp(),
    ext_price=Decimal('3001.50'),
    lig_price=Decimal('3000.50'),
    open_spread=Decimal('0.001'),
    quantity=Decimal('0.21'),
    ext_order_id="ext_123",
    lig_order_id="lig_456",
    is_active=True,
    # 新增字段
    price_snapshot=snapshot,
    ext_execution_price=Decimal('3001.80'),
    lig_execution_price=Decimal('2999.80')
)

# 计算实际滑点
ext_slippage, lig_slippage = record.get_slippage()
logger.info(f"实际滑点: ext={ext_slippage:.4%}, lig={lig_slippage:.4%}")
```

---

## 数据流图

```
┌─────────────────────┐
│ SpreadMonitor        │
│ (价差监控)            │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ execute_open_position│
│                       │
│ 1. 并发获取价格       │
│    - ext.fetch_bbo   │
│    - lig.fetch_bbo   │
│                       │
│ 2. 创建PriceSnapshot │
│    - 验证time_delta  │
│    - 计算taker价格   │
│    - 验证一致性      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 并发发送订单          │
│                       │
│ - Ext Taker订单       │
│ - Lig Taker订单       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 记录OpenPositionRecord│
│                       │
│ - price_snapshot     │
│ - ext_execution_price│
│ - lig_execution_price│
└─────────────────────┘
```

---

## 状态转换

### PriceSnapshot状态

```
[创建]
   │
   ├─→ [验证] → time_delta >= 10ms → [无效] → 跳过开仓
   │
   ├─→ [验证] → ext_ask >= lig_bid → [无效] → 跳过开仓
   │
   └─→ [有效] → 计算taker价格 → 验证一致性 → [使用]
```

### 开仓流程状态

```
[IDLE]
   │
   ├─→ 检测套利机会
   │
   ├─→ [OPENING]
   │     │
   │     ├─→ 创建PriceSnapshot
   │     │     │
   │     │     ├─→ 无效 → [IDLE] (跳过)
   │     │     │
   │     │     └─→ 有效 → 计算价格
   │     │           │
   │     │           ├─→ 不一致 → [IDLE] (跳过)
   │     │           │
   │     │           └─→ 一致 → 并发下单
   │     │                 │
   │     │                 ├─→ 成功 → [HOLDING]
   │     │                 │
   │     │                 └─→ 失败 → [OPENING_WAIT]
   │     │
   │     └─→ [OPENING_WAIT]
   │           │
   │           ├─→ 仓位确认 → [HOLDING]
   │           │
   │           └─→ 超时 → 强平 → [IDLE]
   │
   └─→ [HOLDING]
         │
         ├─→ 检测平仓机会 → [CLOSING]
         │
         └─→ 检测加仓机会 → [OPENING]
```

---

## 验证规则

### 价格快照验证

| 规则 | 条件 | 目的 |
|------|------|------|
| 价格有效性 | bid>0, ask>0, bid<ask | 防止无效价格 |
| 时间同步性 | time_delta<10ms | 确保价格同步 |
| 套利一致性 | ext_ask*1.002 < lig_bid*0.998 | 确保套利空间 |

### 开仓记录验证

| 规则 | 条件 | 目的 |
|------|------|------|
| 仓位平衡 | abs(ext_position - lig_position) < 0.001 | 确保套利对冲 |
| 价格合理性 | ext_entry < lig_entry | 确保套利逻辑正确 |
| 滑点合理性 | slippage < 1% | 防止异常滑点 |

---

## 数据持久化

### 状态文件

现有的 `logs/spread_arb_state.json` 保持不变，继续存储：
- BotState（机器人状态）
- Position（当前持仓）
- OpenPosition[]（开仓记录列表）

### 新增字段

在 `OpenPosition` 的JSON序列化中新增字段：
```json
{
  "position_id": "...",
  "open_time": 1640000000.0,
  "ext_price": "3000.50",
  "lig_price": "2999.50",
  "open_spread": "0.001",
  "quantity": "0.21",
  "ext_order_id": "ext_123",
  "lig_order_id": "lig_456",
  "is_active": true,

  "price_snapshot": {
    "ext_bid": "3000.00",
    "ext_ask": "3000.50",
    "ext_timestamp": 1640000000.000,
    "lig_bid": "2999.50",
    "lig_ask": "3000.00",
    "lig_timestamp": 1640000000.005,
    "time_delta": 0.005
  },

  "ext_execution_price": "3001.80",
  "lig_execution_price": "2999.80"
}
```

---

## 相关模型

### 现有模型（保持不变）

- `BotState`：机器人状态枚举
- `Position`：当前持仓
- `SpreadInfo`：价差信息
- `Trade`：交易记录
- `Portfolio`：投资组合

### 模型关系

```
PriceSnapshot
    ├── 用于：execute_open_position
    ├── 生成：OpenPositionRecord
    └── 验证：is_valid(), validate_price_consistency()

OpenPositionRecord
    ├── 继承：现有的OpenPosition
    ├── 扩展：price_snapshot, ext_execution_price, lig_execution_price
    └── 关联：Portfolio
```

---

**版本**: 1.0
**最后更新**: 2026-01-16
