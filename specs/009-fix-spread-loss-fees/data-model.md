# Data Model: 价差套利核心问题修复

**Feature**: 009-fix-spread-loss-fees
**Date**: 2026-01-10

## Overview

本文档定义了修复价差套利系统所需的数据模型。这些模型扩展了现有的`SpreadPair`和相关类，增加了对手价价差计算、成本分解和订单类型跟踪功能。

---

## Core Entities

### 1. RealSpreadOpportunity (新实体)

**用途**: 表示使用对手价计算的真实价差机会，替代中间价计算

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

@dataclass
class RealSpreadOpportunity:
    """真实价差机会（使用对手价计算）"""

    # 基本信息
    direction: Literal['long_spread', 'short_spread']  # 套利方向
    is_valid: bool                                      # 是否为有效机会

    # 价格信息
    extended_entry_price: Decimal   # Extended开仓价格（对手价）
    lighter_entry_price: Decimal    # Lighter开仓价格（对手价）

    # 真实价差
    real_spread: Decimal            # 真实价差（对手价计算）
    real_spread_rate: Decimal       # 真实价差率

    # 成本分解
    extended_spread_cost: Decimal   # Extended点差成本
    lighter_spread_cost: Decimal    # Lighter点差成本
    total_entry_cost: Decimal       # 总开仓成本（点差+手续费）

    # 期望收益
    expected_profit_rate: Decimal   # 期望收益率（扣除所有成本后）
    expected_profit_usdt: Decimal   # 期望利润（USDT）

    # 订单定价
    extended_maker_price: Decimal   # Extended Maker订单价格
    extended_taker_price: Decimal   # Extended Taker订单价格（=对手价）
    lighter_hedge_price: Decimal    # Lighter对冲价格

    # 验证
    passes_threshold: bool          # 是否通过开仓阈值
    failure_reason: str | None      # 不通过的原因

    @classmethod
    def from_orderbook(
        cls,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal,
        min_spread_rate: Decimal
    ) -> 'RealSpreadOpportunity':
        """从订单簿数据创建真实价差机会"""
        # 实现见下方

    def calculate_expected_profit(
        self,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        use_maker: bool
    ) -> Decimal:
        """计算期望收益（考虑手续费）"""
        # 实现见下方
```

**状态转换**: 无状态，只读数据类

**验证规则**:
1. `real_spread_rate > 0` 才是有效机会
2. `expected_profit_rate > 0` 才能通过阈值
3. 价格必须大于0

---

### 2. OrderExecutionDetails (新实体)

**用途**: 记录订单执行的详细信息，用于分析和调优

```python
@dataclass
class OrderExecutionDetails:
    """订单执行详情"""

    # 基本信息
    order_id: str
    exchange: Literal['extended', 'lighter']
    timestamp: float

    # 订单类型
    intended_type: Literal['maker', 'taker']   # 预期类型
    actual_type: Literal['maker', 'taker']     # 实际类型
    post_only: bool                             # 是否使用post_only

    # 价格
    limit_price: Decimal            # 限价价格
    filled_price: Decimal | None    # 成交价格
    slippage: Decimal | None        # 滑点 (filled - limit)

    # 执行
    status: Literal['PENDING', 'FILLED', 'PARTIAL', 'CANCELLED', 'REJECTED']
    filled_quantity: Decimal
    time_to_fill: float | None      # 成交耗时（秒）

    # 手续费
    expected_fee_rate: Decimal      # 预期费率
    actual_fee_rate: Decimal | None # 实际费率
    expected_fee_amount: Decimal    # 预期手续费
    actual_fee_amount: Decimal | None  # 实际手续费

    # 特殊事件
    is_rejected: bool               # 是否被拒绝（post_only冲突）
    reject_reason: str | None       # 拒绝原因
    converted_to_taker: bool        # 是否转换为taker
    conversion_reason: str | None   # 转换原因

    @property
    def effective_fee_rate(self) -> Decimal:
        """实际有效费率"""
        if self.actual_fee_amount and self.filled_price and self.filled_quantity:
            trade_value = self.filled_price * self.filled_quantity
            return self.actual_fee_amount / trade_value if trade_value > 0 else Decimal('0')
        return Decimal('0')

    @property
    def actual_slippage_rate(self) -> Decimal:
        """实际滑点率"""
        if self.slippage and self.limit_price:
            return abs(self.slippage / self.limit_price)
        return Decimal('0')
```

**状态转换**: `PENDING` → `FILLED` | `PARTIAL` | `CANCELLED` | `REJECTED`

---

### 3. TradeCostBreakdown (新实体)

**用途**: 详细的成本分解，用于盈亏归因分析

```python
@dataclass
class TradeCostBreakdown:
    """交易成本分解"""

    # 开仓成本
    entry_extended_fee: Decimal      # Extended开仓手续费
    entry_lighter_fee: Decimal       # Lighter开仓手续费
    entry_extended_spread_cost: Decimal  # Extended点差成本
    entry_lighter_spread_cost: Decimal   # Lighter点差成本
    entry_slippage_cost: Decimal     # 开仓滑点成本
    total_entry_cost: Decimal        # 总开仓成本

    # 平仓成本
    exit_extended_fee: Decimal       # Extended平仓手续费
    exit_lighter_fee: Decimal        # Lighter平仓手续费
    exit_extended_spread_cost: Decimal   # Extended点差成本
    exit_lighter_spread_cost: Decimal    # Lighter点差成本
    exit_slippage_cost: Decimal      # 平仓滑点成本
    total_exit_cost: Decimal         # 总平仓成本

    # 总成本
    total_fees: Decimal              # 总手续费
    total_spread_cost: Decimal       # 总点差成本
    total_slippage_cost: Decimal     # 总滑点成本
    total_cost: Decimal              # 总成本

    # 收益
    gross_profit: Decimal            # 毛收益（价差收益）
    net_profit: Decimal              # 净收益（扣除总成本）
    profit_rate: Decimal             # 收益率

    def to_dict(self) -> dict:
        """转换为字典（用于日志/导出）"""
        return {
            'entry': {
                'extended_fee': str(self.entry_extended_fee),
                'lighter_fee': str(self.entry_lighter_fee),
                'extended_spread': str(self.entry_extended_spread_cost),
                'lighter_spread': str(self.entry_lighter_spread_cost),
                'slippage': str(self.entry_slippage_cost),
                'total': str(self.total_entry_cost)
            },
            'exit': {
                'extended_fee': str(self.exit_extended_fee),
                'lighter_fee': str(self.exit_lighter_fee),
                'extended_spread': str(self.exit_extended_spread_cost),
                'lighter_spread': str(self.exit_lighter_spread_cost),
                'slippage': str(self.exit_slippage_cost),
                'total': str(self.total_exit_cost)
            },
            'total': {
                'fees': str(self.total_fees),
                'spread_cost': str(self.total_spread_cost),
                'slippage': str(self.total_slippage_cost),
                'total': str(self.total_cost)
            },
            'profit': {
                'gross': str(self.gross_profit),
                'net': str(self.net_profit),
                'rate': str(self.profit_rate)
            }
        }
```

**计算逻辑**:
```python
# 点差成本计算
def calculate_spread_cost(bid: Decimal, ask: Decimal, quantity: Decimal) -> Decimal:
    """
    计算点差成本

    对于买入: 成本 = (ask - mid) * quantity = ask - bid / 2 * quantity
    对于卖出: 成本 = (mid - bid) * quantity = ask - bid / 2 * quantity
    """
    spread = ask - bid
    return (spread / 2) * quantity

# 滑点成本计算
def calculate_slippage(limit_price: Decimal, filled_price: Decimal, quantity: Decimal) -> Decimal:
    """
    计算滑点成本

    对于买入: 滑点 = (filled - limit) * quantity (如果 filled > limit)
    对于卖出: 滑点 = (limit - filled) * quantity (如果 filled < limit)
    """
    if filled_price > limit_price:  # 买入不利
        return (filled_price - limit_price) * quantity
    else:  # 卖出不利
        return (limit_price - filled_price) * quantity
```

---

### 4. PositionBalance (修改现有实体)

**用途**: 正确计算Extended和Lighter的仓位平衡

```python
@dataclass
class PositionBalance:
    """仓位平衡状态（修复版）"""

    # 仓位信息
    extended_total_qty: Decimal      # Extended总仓位
    lighter_total_qty: Decimal       # Lighter总仓位

    # 差异计算（修复：使用相减而非绝对值相加）
    net_position: Decimal            # 净仓位 = extended - lighter
    abs_net_position: Decimal        # 净仓位绝对值
    diff_rate: Decimal               # 差异率 = abs_net / total_position

    # 状态
    is_balanced: bool                # 是否平衡（差异<1%）
    imbalance_level: Literal['NONE', 'LOW', 'MEDIUM', 'HIGH']

    @classmethod
    def from_pairs(cls, pairs: List[SpreadPair]) -> 'PositionBalance':
        """从SpreadPair列表计算仓位平衡"""
        extended_long = sum(p.extended_quantity for p in pairs if p.extended_side == 'buy')
        extended_short = sum(p.extended_quantity for p in pairs if p.extended_side == 'sell')
        extended_total = extended_long - extended_short

        lighter_long = sum(p.lighter_quantity for p in pairs if p.lighter_side == 'buy')
        lighter_short = sum(p.lighter_quantity for p in pairs if p.lighter_side == 'sell')
        lighter_total = lighter_long - lighter_short

        # 修复：使用相减
        net = extended_total - lighter_total
        total_position = abs(extended_total) + abs(lighter_total)

        if total_position == 0:
            diff_rate = Decimal('0')
        else:
            diff_rate = abs(net) / total_position

        is_balanced = diff_rate < Decimal('0.01')  # 1%阈值

        # 确定不平衡级别
        if diff_rate < Decimal('0.01'):
            imbalance_level = 'NONE'
        elif diff_rate < Decimal('0.05'):
            imbalance_level = 'LOW'
        elif diff_rate < Decimal('0.10'):
            imbalance_level = 'MEDIUM'
        else:
            imbalance_level = 'HIGH'

        return cls(
            extended_total_qty=extended_total,
            lighter_total_qty=lighter_total,
            net_position=net,
            abs_net_position=abs(net),
            diff_rate=diff_rate,
            is_balanced=is_balanced,
            imbalance_level=imbalance_level
        )
```

---

## Relationships

```
RealSpreadOpportunity (1)
    ├── leads to → OrderExecutionDetails (2+, one per exchange)
    └── becomes → TradeCostBreakdown (1, after both sides filled)

SpreadPair (existing)
    ├── extends → uses RealSpreadOpportunity
    ├── tracks → OrderExecutionDetails (2+)
    └── calculates → TradeCostBreakdown

PositionBalance
    └── aggregates → from multiple SpreadPair
```

---

## Storage Strategy

### Phase 1: 内存 + 结构化日志
- 所有实体在内存中创建和使用
- 关键数据通过TradeLogger记录到`logs/trade.log`
- 使用JSON格式便于后续解析

### Phase 2: CSV导出
- TradeCostBreakdown定期导出到CSV
- OrderExecutionDetails累积到CSV
- 使用pandas进行分析

### Phase 3: 数据库（按需）
- SQLite存储历史交易
- 表结构映射到上述实体
- 支持时序查询和统计分析

---

## Validation Rules

| Entity | Rule | Enforcement |
|--------|------|-------------|
| RealSpreadOpportunity | real_spread_rate > 0 | __post_init__ |
| RealSpreadOpportunity | expected_profit_rate > 0 (to pass threshold) | Validation method |
| OrderExecutionDetails | filled_price > 0 if FILLED | __post_init__ |
| TradeCostBreakdown | total_cost = sum of all costs | Calculation method |
| PositionBalance | diff_rate = abs_net / total (if total > 0) | Calculation method |

---

## Migration Path

### Step 1: 添加新实体
- 创建 `spread/models_v2.py` 包含上述实体
- 保留旧的 `spread/models.py` 用于向后兼容

### Step 2: 更新现有代码
- 修改 `calculator.py` 返回 `RealSpreadOpportunity`
- 修改 `order_manager.py` 记录 `OrderExecutionDetails`
- 修改 `trade_logger.py` 接受 `TradeCostBreakdown`

### Step 3: 更新SpreadPair
- 扩展 `SpreadPair` 使用新实体
- 添加向后兼容的属性访问器

### Step 4: 更新bot.py
- 使用新的 `PositionBalance` 计算
- 集成所有新实体

### Step 5: 清理
- 移除旧的中间价计算代码
- 删除不再需要的向后兼容代码
- 更新所有测试
