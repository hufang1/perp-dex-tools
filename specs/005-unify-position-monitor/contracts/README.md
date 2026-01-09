# Contracts: 统一持仓监控显示并增加平仓收益实时计算

**Feature**: 005-unify-position-monitor
**Date**: 2026-01-09

## 说明

本功能不涉及外部API契约，所有修改都是内部模块重构。

## 内部接口契约

### PositionAggregator.aggregate_positions()

```python
def aggregate_positions(
    pairs: List[SpreadPair]
) -> Dict[str, UnifiedPosition]:
    """
    聚合同方向的持仓

    Args:
        pairs: SpreadPair列表

    Returns:
        按方向分组的统一持仓字典
        - 'long': UnifiedPosition (如果有做多持仓)
        - 'short': UnifiedPosition (如果有做空持仓)

    Raises:
        ValueError: 当pairs为空或数据无效时
    """
```

### ProfitCalculator.calculate_profit()

```python
def calculate_profit(
    position: UnifiedPosition,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal,
    extended_fee_rate: Decimal,
    lighter_fee_rate: Decimal
) -> Optional[ProfitBreakdown]:
    """
    计算平仓后的收益（含手续费）

    Args:
        position: 统一持仓
        extended_bid: Extended买一价
        extended_ask: Extended卖一价
        lighter_bid: Lighter买一价
        lighter_ask: Lighter卖一价
        extended_fee_rate: Extended手续费率
        lighter_fee_rate: Lighter手续费率

    Returns:
        ProfitBreakdown对象，如果价格数据无效则返回None
    """
```

### 配置接口

```python
# SpreadArbConfig新增字段
extended_fee_rate: Decimal = Decimal('0.000225')  # Extended taker费率
lighter_fee_rate: Decimal = Decimal('0.0')         # Lighter费率
```

## 输出格式契约

### 持仓监控输出格式

```
📊 持仓监控汇总

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
做多仓位 (共3个套利对):
   总数量: 0.0300 ETH
   Extended平均价格: $3087.10
   Lighter平均价格: $3058.93
   持仓时间: 37-49秒 (剩余 1751秒)
   当前价格: Extended $3087.00 / Lighter $3089.42
   未实现盈亏: -$0.92
   距离盈利目标: $0.96
   平仓后收益: -$1.22 (含手续费 $0.30)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**格式规则**：
- 使用简体中文
- 价格保留2位小数
- 数量保留4位小数
- 时间显示为整数秒
- 收益保留2位小数（支持负数）
- 分隔线使用Unicode全角划线
