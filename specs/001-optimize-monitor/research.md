# Research Document: 优化持仓监控输出

**Feature**: 001-optimize-monitor
**Date**: 2026-01-09
**Status**: Complete

## Overview

本文档记录了"优化持仓监控输出"功能的技术研究和决策过程。所有研究问题已解决，可以进入实施阶段。

---

## R-001: 确定整合输出的最佳格式

### 问题
如何将多个持仓的监控信息整合到单个日志输出中，同时保持可读性和与现有日志系统的兼容性？

### 决策
**使用单个多行logger.info()调用，通过换行符\n整合所有持仓**

### 理由
1. **日志系统兼容性**: 保持单次调用确保时间戳一致，避免多次调用产生的多条日志
2. **可读性**: 换行符在终端中正确显示，用户可以轻松扫描所有持仓
3. **简单性**: 无需引入额外的格式化库或复杂的输出逻辑

### 替代方案及拒绝原因

| 方案 | 描述 | 拒绝原因 |
|------|------|----------|
| 多次logger.info()调用 | 每个持仓调用一次logger.info() | 会产生多个时间戳，不符合"整合输出"需求 |
| 列表格式输出 | 使用Python列表格式输出所有持仓 | 可读性差，不符合现有日志风格 |
| 表格输出格式 | 使用固定宽度的表格格式 | 中文字符宽度不一致，表格对齐困难 |

### 实现示例
```python
# 新的实现方式
def _log_all_positions(self, pairs: List[SpreadPair], prices: Dict):
    output_lines = ["📊 持仓监控汇总"]
    for pair in pairs:
        output_lines.append(f"  持仓 #{pair.pair_id}: ...")
    output_lines.append(f"总持仓: {len(pairs)}")
    self.logger.info("\n".join(output_lines))
```

---

## R-002: 确定已实现收益的计算方法

### 问题
如何组织和实现"当前已实现收益"的计算逻辑，确保代码可测试且符合现有架构？

### 决策
**在SpreadPair类中新增`calculate_realized_pnl(bid_price, ask_price)`实例方法**

### 理由
1. **一致性**: SpreadPair已有`calculate_unrealized_pnl()`方法，保持API对称
2. **封装性**: 计算逻辑封装在数据模型中，符合单一职责原则
3. **可测试性**: 实例方法易于单元测试，无需mock整个bot
4. **复用性**: 其他模块（如统计报告）可以复用此方法

### 替代方案及拒绝原因

| 方案 | 描述 | 拒绝原因 |
|------|------|----------|
| 在bot.py中内联计算 | 直接在_log_position_status中计算 | 难以测试，违反DRY原则，代码重复 |
| 在calculator.py中新增函数 | 创建独立的计算函数 | 违反数据和行为封装原则，SpreadPair应负责自己的计算 |

### 实现示例
```python
# spread/spread_pair.py
class SpreadPair:
    def calculate_realized_pnl(
        self,
        extended_close_price: Decimal,
        lighter_close_price: Decimal
    ) -> Decimal:
        """
        计算使用对手价立即平仓的理论收益

        Args:
            extended_close_price: Extended平仓价格（做多用bid，做空用ask）
            lighter_close_price: Lighter平仓价格（做多用ask，做空用bid）

        Returns:
            已实现盈亏（正数=盈利，负数=亏损）
        """
        # Extended盈亏
        if self.extended_side == 'buy':
            extended_pnl = (extended_close_price - self.extended_price) * self.extended_quantity
        else:
            extended_pnl = (self.extended_price - extended_close_price) * self.extended_quantity

        # Lighter盈亏（与Extended方向相反）
        if self.lighter_side == 'sell':
            lighter_pnl = (self.lighter_price - lighter_close_price) * self.lighter_quantity
        else:
            lighter_pnl = (lighter_close_price - self.lighter_price) * self.lighter_quantity

        return extended_pnl + lighter_pnl
```

---

## R-003: 确定视觉分隔符样式

### 问题
如何在整合输出中清晰分隔多个持仓，同时保持终端显示的美观性？

### 决策
**使用"━━━━━━━━━━━━━━━━━━━━"作为持仓分隔符**

### 理由
1. **简洁性**: 简单的Unicode字符，在所有现代终端中正确显示
2. **一致性**: 与现有日志风格一致（现有日志已使用━━━作为分隔符）
3. **不冲突**: 不会与持仓监控的emoji（📊）产生视觉冲突

### 替代方案及拒绝原因

| 方案 | 描述 | 拒绝原因 |
|------|------|----------|
| 单空行 | 持仓之间使用一个空行 | 在紧凑终端中不够明显，难以快速区分 |
| 表格线 | 使用├─┤等制表符 | 过于复杂，影响可读性，维护成本高 |
| Emoji分隔 | 使用其他emoji作为分隔 | 与📊 emoji冲突，视觉混乱 |

### 实现示例
```python
output_parts = []
for i, pair in enumerate(pairs):
    if i > 0:
        output_parts.append("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    output_parts.append(f"   持仓 #{pair.pair_id}: ...")
```

---

## R-004: 处理订单簿数据缺失的策略

### 问题
当WebSocket订单簿数据缺失或延迟时，如何处理监控输出以确保系统稳定性？

### 决策
**使用"N/A"显示价格，跳过已实现收益计算**

### 理由
1. **稳定性**: 避免异常导致监控循环中断，保证交易逻辑持续运行
2. **诚实性**: 明确告知用户数据不可用，而非显示可能误导的最后已知价格
3. **可恢复性**: 当订单簿数据恢复时，下次监控周期会正常显示

### 替代方案及拒绝原因

| 方案 | 描述 | 拒绝原因 |
|------|------|----------|
| 使用最后已知价格 | 缓存最后一次有效的订单簿价格 | 可能产生严重误导，用户可能基于过时价格做决策 |
| 抛出异常并中断 | 当数据缺失时抛出异常 | 会中断监控循环，影响交易系统稳定性 |
| 跳过整个持仓 | 不显示任何信息 | 用户无法知道持仓存在，失去监控意义 |

### 实现示例
```python
def _log_all_positions(self, pairs: List[SpreadPair]):
    extended_bid = self.extended_orderbook['bids'].get_best_bid()
    extended_ask = self.extended_orderbook['asks'].get_best_ask()

    if extended_bid is None or extended_ask is None:
        self.logger.warning("📊 持仓监控: Extended订单簿数据不可用")
        return

    # 正常计算和显示
    ...
```

---

## R-005: 处理大量持仓(>10个)的策略

### 问题
当持仓数量较多时（接近20个上限），如何设计输出格式以避免日志过长影响可读性？

### 决策
**无限制完整输出，在末尾提供摘要行（总持仓数、总未实现盈亏）**

### 理由
1. **假设验证**: spec.md假设持仓不超过20个，完整输出仍然可读
2. **完整性**: 用户需要看到每个持仓的详细信息，截断会失去监控价值
3. **摘要辅助**: 末尾摘要帮助用户快速了解整体状况

### 替代方案及拒绝原因

| 方案 | 描述 | 拒绝原因 |
|------|------|----------|
| 分页输出 | 每次只显示5个持仓，轮换显示 | 日志不适合交互式分页，用户可能错过关键信息 |
| 仅显示摘要 | 只显示总持仓数和总盈亏 | 失去详细监控的目的，无法看到单个持仓的风险 |
| 截断显示 | 超过10个时只显示前10个 | 用户无法知道被截断的持仓状况 |

### 实现示例
```python
def _log_all_positions(self, pairs: List[SpreadPair]):
    output_lines = ["📊 持仓监控汇总"]

    total_unrealized_pnl = Decimal('0')

    for pair in pairs:
        # ... 计算单个持仓信息 ...
        output_lines.append(f"  ...")
        total_unrealized_pnl += unrealized_pnl

    # 摘要行
    output_lines.append(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    output_lines.append(f"  总持仓: {len(pairs)} | 总未实现盈亏: ${total_unrealized_pnl:.2f}")

    self.logger.info("\n".join(output_lines))
```

---

## 研究总结

### 核心设计原则
1. **保持一致性**: 与现有代码风格、日志格式、API设计保持一致
2. **优先稳定性**: 确保监控输出异常不会影响交易核心逻辑
3. **简单直接**: 避免过度设计，使用最简单的实现方案

### 技术选型汇总
| 决策点 | 选择 | 关键理由 |
|--------|------|----------|
| 输出格式 | 单次多行logger.info | 时间戳一致、可读性好 |
| 计算方法 | SpreadPair实例方法 | 可测试、可复用、符合OOP |
| 分隔符 | ━━━━ Unicode字符 | 简洁、兼容性好 |
| 数据缺失 | 显示N/A、跳过计算 | 稳定性优先 |
| 大量持仓 | 完整输出+摘要 | 完整性优先 |

### 风险评估
| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 日志输出过长 | 低 | 假设<20个持仓，末尾摘要辅助 |
| 计算性能 | 低 | O(n)复杂度，20个持仓<50ms |
| 订单簿异常 | 中 | 异常处理，显示N/A，不影响交易 |
| 编码问题 | 低 | 使用标准Unicode字符 |

### 下一步
所有技术决策已确定，可以进入Phase 1设计阶段：
- 创建data-model.md（数据模型）
- 创建contracts/output-format.md（输出格式规范）
- 创建quickstart.md（使用指南）
