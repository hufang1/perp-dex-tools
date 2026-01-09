# Data Model: 统一持仓监控显示并增加平仓收益实时计算

**Feature**: 005-unify-position-monitor
**Date**: 2026-01-09

## 核心实体

### 1. UnifiedPosition（统一持仓）

表示同一方向多个套利对的聚合视图。

```python
@dataclass
class UnifiedPosition:
    """统一持仓 - 聚合同方向的多个SpreadPair"""

    # 基本信息
    direction: str                          # 'long' 或 'short'
    pair_ids: List[int]                     # 包含的套利对ID列表

    # 仓位信息
    total_quantity: Decimal                 # 总数量
    extended_avg_price: Decimal             # Extended平均开仓价格（加权平均）
    lighter_avg_price: Decimal              # Lighter平均开仓价格（加权平均）

    # 时间信息
    earliest_open_time: float               # 最早开仓时间
    latest_open_time: float                 # 最晚开仓时间

    # 手续费
    total_opening_fees: Decimal             # 总开仓手续费

    def calculate_holding_time_range(self) -> tuple:
        """返回持仓时间范围 (最早, 最晚, 单位: 秒)"""

    def calculate_average_holding_time(self) -> float:
        """返回平均持仓时间 (秒)"""
```

**计算规则**：

1. **总数量**：`sum(pair.extended_quantity for pair in pairs)`
2. **加权平均价格**：`sum(q × p) / sum(q)`
3. **开仓手续费**：`sum(quantity × price × fee_rate)`

### 2. ProfitBreakdown（收益明细）

表示平仓后的收益计算结果。

```python
@dataclass
class ProfitBreakdown:
    """收益明细 - 平仓后的收益计算结果"""

    # 价差收益
    spread_profit: Decimal                  # 价差收益（不含手续费）

    # 手续费
    opening_fees: Decimal                   # 已支付的开仓手续费
    estimated_closing_fees: Decimal         # 预计的平仓手续费

    # 净收益
    net_profit: Decimal                     # 扣除所有手续费后的净收益

    # 明细
    extended_pnl: Decimal                   # Extended盈亏
    lighter_pnl: Decimal                    # Lighter盈亏

    def calculate_net_profit(self) -> Decimal:
        """计算净收益 = spread_profit - opening_fees - estimated_closing_fees"""
```

**计算规则**：

1. **价差收益**：Extended盈亏 + Lighter盈亏
2. **开仓手续费**：`quantity × avg_price × extended_fee_rate + quantity × avg_price × lighter_fee_rate`
3. **平仓手续费**：`quantity × current_price × extended_fee_rate + quantity × current_price × lighter_fee_rate`
4. **净收益**：价差收益 - 开仓手续费 - 平仓手续费

## 实体关系图

```
SpreadPair (1..*) ──聚合──> UnifiedPosition (1..2)
                                      │
                                      ├──> long UnifiedPosition
                                      └──> short UnifiedPosition

UnifiedPosition (1) ──计算──> ProfitBreakdown (1)
                                    │
                                    ├──> spread_profit
                                    ├──> opening_fees
                                    ├──> estimated_closing_fees
                                    └──> net_profit
```

## 数据流向

```
[SpreadPair列表]
      │
      ▼
[PositionAggregator.aggregate_positions()]
      │
      ▼
[UnifiedPosition (按方向分组)]
      │
      ▼
[ProfitCalculator.calculate_profit()]
      │
      ▼
[ProfitBreakdown]
      │
      ▼
[格式化输出到日志]
```

## 验证规则

### UnifiedPosition验证

1. `total_quantity > 0`：数量必须为正
2. `extended_avg_price > 0` 和 `lighter_avg_price > 0`：价格必须为正
3. `len(pair_ids) > 0`：至少包含一个套利对
4. `earliest_open_time <= latest_open_time`：时间范围有效

### ProfitBreakdown验证

1. 手续费 >= 0：手续费不能为负
2. `net_profit = spread_profit - opening_fees - estimated_closing_fees`：计算一致性
3. 当订单簿为空时，返回None或特殊标记

## 状态转换

UnifiedPosition是只读视图，不涉及状态转换。

ProfitBreakdown每次都是重新计算，不存储状态。

## 扩展性考虑

1. **支持多交易所**：如果增加更多交易所，UnifiedPosition可以扩展为`exchange_positions: Dict[str, ExchangePosition]`
2. **支持复杂手续费**：可以添加`FeeCalculator`策略模式，支持阶梯费率
3. **支持部分平仓**：可以添加`partial_close_quantity`字段
