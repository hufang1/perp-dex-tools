# Implementation Plan: 统一持仓监控显示并增加平仓收益实时计算

**Branch**: `005-unify-position-monitor` | **Date**: 2026-01-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-unify-position-monitor/spec.md`

## Summary

优化价差套利机器人的持仓监控输出，将多个同向仓位合并显示为单一统一仓位，并增加实时计算平仓后收益功能（扣除手续费）。

**技术方案**：
1. 创建持仓聚合器，将同交易所同向的多个SpreadPair合并为统一持仓视图
2. 实现平仓收益计算器，使用对手价实时计算扣除手续费后的净收益
3. 重构日志输出格式，提供清晰易读的中文界面

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, logging (Python标准库)
**Storage**: 内存状态存储，日志写入文件
**Testing**: pytest
**Target Platform**: Linux/macOS服务器
**Project Type**: 单项目（价差套利交易机器人）
**Performance Goals**: 持仓监控信息在1秒内完成计算和显示
**Constraints**: 计算过程必须使用Decimal保证金融精度
**Scale/Scope**: 最多3个并发套利对，每秒输出一次监控信息

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**当前项目无宪法文件约束** - `.specify/memory/constitution.md` 为模板文件，未定义具体原则。

## Project Structure

### Documentation (this feature)

```text
specs/005-unify-position-monitor/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
└── contracts/           # Phase 1 输出（本功能不涉及API契约）
```

### Source Code (repository root)

```text
spread/
├── bot.py                    # 修改：持仓监控输出逻辑
├── spread_pair.py            # 修改：增加手续费计算方法
├── position_aggregator.py    # 新增：持仓聚合器
├── profit_calculator.py      # 新增：收益计算器（含手续费）
└── config.py                 # 修改：增加手续费率配置

tests/
├── test_position_aggregator.py     # 新增
└── test_profit_calculator.py       # 新增
```

**Structure Decision**: 采用单项目结构，在现有spread模块内新增聚合器和计算器模块，修改bot.py的监控输出逻辑。

## Phase 0: Research & Decisions

### 0.1 手续费计算规则研究

**待决策问题**：
- Extended交易所手续费率是多少？
- Lighter交易所手续费率是多少？
- 手续费是按成交金额的固定比例还是阶梯费率？

**研究任务**：查阅现有代码和配置，确定手续费计算规则

### 0.2 持仓合并策略研究

**待决策问题**：
- 如何计算合并后仓位的平均开仓价格？（加权平均 vs 最新价格）
- 多个仓位的开仓时间如何显示？（最早时间 vs 时间范围）
- 合并后的pair_id如何显示？（列表 vs 统一编号）

**研究任务**：分析业务需求，确定合理的合并逻辑

### 0.3 对手价获取机制研究

**待决策问题**：
- 当前订单簿数据结构是否包含足够的手对手价信息？
- 如何处理订单簿为空的情况？

**研究任务**：确认bot.py中的orderbook数据结构可用

## Phase 1: Design

### 1.1 数据模型设计

**统一持仓（UnifiedPosition）**：
- 总数量（sum of quantities）
- Extended平均开仓价格（weighted average）
- Lighter平均开仓价格（weighted average）
- 方向（all same direction）
- 包含的pair_id列表
- 开仓时间范围（最早到最晚）
- 总手续费（开仓手续费）

**平仓收益计算输出**：
- 价差收益（price difference profit）
- 开仓手续费（total opening fees）
- 预计平仓手续费（estimated closing fees）
- 净收益（net profit after fees）

### 1.2 模块设计

**PositionAggregator模块**：
- `aggregate_positions(pairs: List[SpreadPair]) -> Dict[str, UnifiedPosition]`
  - 输入：SpreadPair列表
  - 输出：按方向分组的统一持仓字典 {'long': UnifiedPosition, 'short': UnifiedPosition}

**ProfitCalculator模块**：
- `calculate_closing_profit(unified_position: UnifiedPosition, bid: Decimal, ask: Decimal) -> Dict`
  - 输入：统一持仓、对手价
  - 输出：包含价差收益、手续费、净收益的字典

### 1.3 配置设计

在`SpreadArbConfig`中增加：
- `extended_fee_rate: Decimal = Decimal('0.0005')`  # Extended手续费率 0.05%
- `lighter_fee_rate: Decimal = Decimal('0.0005')`   # Lighter手续费率 0.05%

### 1.4 输出格式设计

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

## Complexity Tracking

> 本功能无宪法违规，无需填写复杂性跟踪
