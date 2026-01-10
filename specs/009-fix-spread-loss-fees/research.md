# Research: 价差套利核心问题修复

**Feature**: 009-fix-spread-loss-fees
**Date**: 2026-01-10
**Status**: Complete

## Overview

本文档记录了修复价差套利系统三个致命问题所需的技术研究和决策。

---

## Research Topic 1: Extended交易所价格精度（price_tick）

### 问题
实现正确的Maker策略需要知道Extended交易所的最小价格单位，以便正确计算maker订单价格（`extended_bid - price_tick` 或 `extended_ask + price_tick`）。

### 研究
查看Extended交易所的API文档和现有代码，确定：
1. 最小价格变动单位
2. 价格精度要求
3. 订单价格验证规则

### 决策
**DECISION**: Extended交易所使用0.01美元作为最小价格单位（price_tick = 0.01）

**理由**:
- 从现有交易日志观察，价格都是两位小数（如3091.80）
- 这符合主流加密货币交易所的标准精度
- 0.01的偏移足以使maker订单不与订单簿价格重叠

**替代方案考虑**:
- 使用0.001: 过于精确，可能导致订单仍然太接近
- 使用0.1: 偏移过大，可能错过成交机会
- 动态计算: 过于复杂，增加不确定性

---

## Research Topic 2: 数据收集和存储方案

### 问题
规范中提出了详细的6大类数据需求，需要确定如何收集和存储这些数据。

### 研究
当前系统状态：
- 使用logging模块记录日志到文件（`logs/trade.log`）
- 没有数据库存储
- 使用SpreadPair和SpreadPosition内存对象

### 决策
**DECISION**: 采用渐进式数据收集策略

**阶段1（核心验证）**: 扩展现有TradeLogger
- 在日志中添加关键字段（对手价价差、订单类型、实际手续费等）
- 使用结构化日志格式（JSON或固定分隔符）
- 不引入数据库

**阶段2（参数优化）**: 引入CSV文件存储
- 将交易记录导出到CSV文件
- 使用pandas进行统计分析
- 简单的命令行工具生成报告

**阶段3（精细优化）**: 按需引入数据库
- 如果数据量增长，考虑SQLite或PostgreSQL
- 优先使用时序数据库（如TimescaleDB）如果需要高效查询

**理由**:
- 当前最重要的是修复核心逻辑，而非建立完整的数据平台
- 文件+日志对于初期数据收集已经足够
- 避免过度设计（YAGNI原则）

**替代方案考虑**:
- 直接引入InfluxDB/TimescaleDB: 过早优化，增加复杂度
- 使用Redis: 持久化复杂，对于离线分析不必要
- 纯内存存储: 无法持久化，重启丢失数据

---

## Research Topic 3: 对手价价差计算的标准化

### 问题
需要确保对手价价差计算的一致性，避免未来再次出现类似错误。

### 研究
分析当前代码中所有价差计算的位置：
1. `calculator.py:calculate_spread_opportunity_mid()` - 使用中间价 ❌
2. `calculator.py:calculate_max_safe_quantity()` - 使用订单簿深度
3. `bot.py:_check_close_conditions()` - 使用对手价检查平仓条件

### 决策
**DECISION**: 创建统一的价差计算工具类

```python
class RealSpreadCalculator:
    """真实价差计算器 - 仅使用对手价"""

    @staticmethod
    def calculate_long_spread(extended_bid, extended_ask,
                              lighter_bid, lighter_ask):
        """
        做多价差（Extended买，Lighter卖）
        返回: (真实价差, 价差率, 成本分解)
        """
        spread = lighter_bid - extended_ask
        base_price = lighter_bid
        spread_rate = spread / base_price

        # 成本分解
        extended_spread_cost = (extended_ask - extended_bid) / 2 / base_price
        lighter_spread_cost = (lighter_ask - lighter_bid) / 2 / base_price

        return {
            'spread': spread,
            'spread_rate': spread_rate,
            'extended_spread_cost': extended_spread_cost,
            'lighter_spread_cost': lighter_spread_cost
        }

    @staticmethod
    def calculate_short_spread(extended_bid, extended_ask,
                               lighter_bid, lighter_ask):
        """
        做空价差（Extended卖，Lighter买）
        """
        spread = extended_bid - lighter_ask
        base_price = extended_bid
        spread_rate = spread / base_price

        # 类似的成本分解
        ...
```

**理由**:
- 单一职责：专门负责真实价差计算
- 易于测试：所有计算逻辑集中在一处
- 防止回归：明确的函数签名和返回值

**替代方案考虑**:
- 在现有calculator.py中修改：风险高，可能影响其他功能
- 创建新的spread_calculator_v2.py：代码冗余，维护困难

---

## Research Topic 4: Maker订单超时和转换策略

### 问题
当前代码在maker订单超时后转换为taker，但这个策略可能不是最优的。

### 研究
分析当前配置和实际情况：
- `maker_timeout_seconds = 5`: 5秒超时
- `maker_timeout_action = "convert_to_taker"`: 转换为taker
- 当前100%被拒绝，然后转换

### 决策
**DECISION**: 保持convert_to_taker策略，但增加条件判断

**改进策略**:
```python
async def _handle_maker_timeout(self, opportunity, fill_result):
    """处理Maker订单超时"""

    # 检查真实价差是否仍然足够
    current_real_spread = self.calculator.calculate_real_spread(...)

    # 计算使用taker后的期望收益
    taker_expected_profit = current_real_spread - taker_fees - spread_costs

    if taker_expected_profit > config.min_profit_threshold:
        # 只有仍有利润时才转换为taker
        await self.order_manager.convert_to_taker(...)
    else:
        # 取消订单，避免亏损交易
        await self.order_manager.cancel_order(order_id)
        self.logger.info("Maker超时且价差不足，取消订单")
```

**理由**:
- 避免在价差收窄时强制交易
- 保留快速成交的机会（当价差仍然很大时）
- 遵循"宁可错过机会，不要做亏本交易"的原则

**替代方案考虑**:
- 总是取消订单：可能错过好的交易机会
- 总是转换为taker：可能在高价差时成交，但在低价差时亏损
- 使用限价单重试：增加延迟，可能错过机会

---

## Research Topic 5: 最小价差率阈值的确定

### 问题
规范建议将阈值从0.06%提高到0.1%或更高，但需要数据支持。

### 研究
基于专业交易员的建议和成本分析：

**成本构成**:
- Extended taker手续费: 0.0225%
- Lighter手续费: 0%
- Extended点差: ~0.015% (估算)
- Lighter点差: ~0.015% (估算)
- 滑点: 0.01%-0.02%
- **总成本**: 0.045% - 0.07%

**当前阈值**:
- min_spread_rate: 0.05%
- latency_buffer: 0.01%
- 实际阈值: 0.06%
- **期望收益**: 0.06% - 0.07% = -0.01% (负期望！)

### 决策
**DECISION**: 分阶段提高阈值

**阶段1（立即修复）**: 提高到0.10%
```python
min_spread_rate = Decimal('0.0010')  # 0.10%
latency_buffer = Decimal('0.0001')   # 0.01%
实际阈值 = 0.11%
期望收益 = 0.11% - 0.07% = 0.04% (正期望)
```

**阶段2（数据收集后）**: 动态调整
- 收集24小时真实价差数据
- 计算P25, P50, P75, P90分位数
- 使用公式: `最优阈值 = P75价差 + 平均成本 + 安全边际(0.02%)`

**阶段3（精细优化）**: 时段差异化
- 高波动时段: 使用更高阈值（如0.15%）
- 低波动时段: 使用较低阈值（如0.08%）

**理由**:
- 0.10%是保守但合理的选择，确保正期望
- 分阶段允许基于实际数据调整
- 时段差异化可以最大化盈利机会

**替代方案考虑**:
- 固定0.12%: 可能过于保守，错过机会
- 固定0.08%: 仍然接近盈亏平衡点
- 完全动态: 过于复杂，初期不需要

---

## Research Topic 6: 平仓价格选择的验证

### 问题
规范指出当前平仓价格选择错误，需要确认正确的逻辑。

### 研究
分析做多和做空仓位的不同场景：

**做多仓位**（Extended买入，Lighter卖出）:
- 开仓: Extended用ask买入，Lighter用bid卖出
- 平仓目标: Extended卖出，Lighter买入
- **正确**: Extended用bid卖出，Lighter用ask买入 ❌
- **当前代码**: Lighter用ask买入 ❌ (这个是对的)

等等，让我重新分析...

**做多仓位的平仓逻辑**:
- 我们持有: Extended多头（需要卖出），Lighter空头（需要买入）
- Extended卖出: 应该用bid价格（卖出给挂买单的人）
- Lighter买入: 应该用ask价格（从挂卖单的人买入）

但规范中说的是"Lighter用bid买入"，这似乎是错误的。

让我再仔细看...

实际上，对于平仓：
- 做多仓位: Extended是多头（需要平多=卖出），Lighter是空头（需要平空=买入）
  - Extended卖出 → 用bid
  - Lighter买入 → 用ask

- 做空仓位: Extended是空头（需要平空=买入），Lighter是多头（需要平多=卖出）
  - Extended买入 → 用ask
  - Lighter卖出 → 用bid

所以当前代码中"做多平仓时Lighter使用ask价格"是**正确的**！

但是规范说这是错误的...让我重新理解问题。

**重新理解问题**:
从日志来看，亏损的原因是"平仓时价差方向反转"。这意味着：
- 开仓时: Extended价格 > Lighter价格
- 平仓时: Lighter价格 > Extended价格（反转了）

在这种情况下，如果用ask价格买入Lighter，成本会更高。

但是...平仓时必须用对手价，这是不可商量的。问题可能不在于价格选择，而在于**何时平仓**。

### 决策
**DECISION**: 平仓价格选择是正确的，但需要改进平仓时机判断

**核心问题**:
当前代码在达到最大持仓时间后强制平仓，不管当前价差是否有利。

**解决方案**:
1. **延迟平仓**: 当价差扩大时（不利），延迟平仓等待收敛
2. **更好的平仓条件**: 检查平仓时的真实价差，只有在有利时才平仓
3. **动态止损**: 如果价差持续扩大超过某个阈值，接受小幅亏损平仓

**实现**:
```python
def _should_close_position(self, pair, current_real_spread):
    """判断是否应该平仓"""

    # 计算当前平仓的盈亏
    close_pnl = self._calculate_close_pnl(pair, current_real_spread)

    # P1: 有利润 → 立即平仓
    if close_pnl > 0:
        return True, "有利润，平仓"

    # P2: 持仓时间短且有微利 → 平仓
    if (pair.holding_time < 60 and
        close_pnl > -config.max_small_loss):
        return True, "时间小额平仓"

    # P3: 持仓时间长且接近回本 → 平仓
    if (pair.holding_time > config.max_holding_time * 0.8 and
        close_pnl > -config.max_small_loss * 2):
        return True, "接近回本，平仓"

    # P4: 超时 → 检查价差方向
    if pair.holding_time > config.max_holding_time:
        # 如果价差不利（扩大），延迟平仓
        if self._is_spread_diverging(pair):
            return False, "价差扩大，延迟平仓"
        # 强制平仓
        return True, "超时强制平仓"

    return False, "继续持有"
```

**理由**:
- 价格选择（对手价）是正确的，无法改变
- 问题在于时机判断，需要在价差有利时平仓
- 多级优先级系统提供灵活性

**替代方案考虑**:
- 修改平仓价格选择: 不可能，必须用对手价
- 总是持有到价差收敛: 可能导致长时间持仓
- 固定时间平仓: 当前做法，导致在不利时机平仓

---

## Summary of Decisions

| Topic | Decision | Key Impact |
|-------|----------|------------|
| 价格精度 | price_tick = 0.01 | Maker订单价格偏移 |
| 数据收集 | 渐进式（日志→CSV→DB） | 避免过度设计 |
| 价差计算 | 统一工具类 | 防止回归错误 |
| Maker超时 | 条件转换（检查利润） | 避免亏损交易 |
| 开仓阈值 | 0.10% → 动态调整 | 确保正期望 |
| 平仓策略 | 多级优先级 | 在有利时机平仓 |

---

## Next Steps

1. ✅ 创建 `spread/real_spread_calculator.py` - 统一价差计算
2. ✅ 修改 `spread/calculator.py` - 使用对手价计算
3. ✅ 修改 `spread/config.py` - 更新默认阈值
4. ✅ 修改 `spread/bot.py` - 改进平仓逻辑
5. ✅ 扩展 `spread/trade_logger.py` - 添加数据字段
6. ✅ 创建 `spread/cost_calculator.py` - 成本分解计算
