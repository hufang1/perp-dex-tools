# Tasks: 价差套利核心问题修复

**Input**: Design documents from `/specs/009-fix-spread-loss-fees/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 本项目使用TDD方法，包含测试任务。

**Organization**: 任务按用户故事分组，每个故事可独立实施和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 任务所属用户故事（如US1, US2, US3）
- 包含精确文件路径

## Path Conventions

本项目为单一Python项目结构：
- 模块代码: `spread/`
- 测试代码: `tests/`
- 集成测试: `tests/integration/`

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基础结构

- [ ] T001 在spread/模块中创建data/目录用于CSV导出
- [ ] T002 在spread/模块中创建__init__.py导出新类
- [ ] T003 [P] 更新.gitignore忽略data/和*.csv文件
- [ ] T004 [P] 创建logs/trade日志轮转配置

---

## Phase 2: Foundational (阻塞性前置条件)

**目的**: 所有用户故事依赖的核心基础设施

**⚠️ 关键**: 在此阶段完成前，不能开始任何用户故事工作

- [ ] T005 创建spread/real_spread_calculator.py实现RealSpreadCalculator类
- [ ] T006 在real_spread_calculator.py中实现calculate_long_spread方法（做多价差对手价计算）
- [ ] T007 在real_spread_calculator.py中实现calculate_short_spread方法（做空价差对手价计算）
- [ ] T008 在real_spread_calculator.py中实现calculate_best_opportunity方法（自动选择最佳方向）
- [ ] T009 [P] 创建spread/cost_calculator.py实现TradeCostBreakdown类
- [ ] T010 [P] 在cost_calculator.py中实现calculate_spread_cost方法（点差成本计算）
- [ ] T011 [P] 在cost_calculator.py中实现calculate_slippage_cost方法（滑点成本计算）
- [ ] T012 [P] 在cost_calculator.py中实现calculate_total_cost方法（总成本汇总）
- [ ] T013 更新spread/config.py添加maker_price_tick配置（默认0.01）
- [ ] T014 更新spread/config.py添加min_profit_threshold配置（默认0.0002）
- [ ] T015 更新spread/config.py将min_spread_rate默认值改为0.0010（0.10%）

**检查点**: 基础设施就绪 - 用户故事实施现在可以并行开始

---

## Phase 3: User Story 1 - 使用对手价计算真实价差 (Priority: P0) 🎯 MVP

**目标**: 修复价差计算逻辑，使用对手价而非中间价，确保只有真正盈利的机会才会开仓

**独立测试**: 通过对比计算结果和实际交易验证，修复后的价差应反映真实交易成本

### Tests for User Story 1 ⚠️

> **注意**: 先写这些测试，确保它们失败后再实施

- [ ] T016 [P] [US1] 在tests/test_real_spread_calculator.py中创建test_calculate_long_spread_positive测试用例
- [ ] T017 [P] [US1] 在tests/test_real_spread_calculator.py中创建test_calculate_long_spread_negative测试用例
- [ ] T018 [P] [US1] 在tests/test_real_spread_calculator.py中创建test_calculate_short_spread_positive测试用例
- [ ] T019 [P] [US1] 在tests/test_real_spread_calculator.py中创建test_calculate_short_spread_negative测试用例
- [ ] T020 [P] [US1] 在tests/test_real_spread_calculator.py中创建test_calculate_best_opportunity_threshold测试用例
- [ ] T021 [P] [US1] 在tests/test_real_spread_calculator.py中创建test_mid_price_vs_real_spread对比测试用例
- [ ] T022 [P] [US1] 在tests/integration/test_real_spread_trading.py中创建test_end_to_end_spread_calculation集成测试

### Implementation for User Story 1

- [ ] T023 [US1] 在spread/real_spread_calculator.py中实现SpreadCosts数据类
- [ ] T024 [US1] 在spread/real_spread_calculator.py中实现RealSpreadResult数据类
- [ ] T025 [US1] 在spread/real_spread_calculator.py中完成calculate_spread_costs方法实现
- [ ] T026 [US1] 在spread/calculator.py中导入RealSpreadCalculator
- [ ] T027 [US1] 在spread/calculator.py中添加calculate_real_spread_opportunity方法包装RealSpreadCalculator
- [ ] T028 [US1] 在spread/calculator.py中添加日志输出显示真实价差vs中间价对比
- [ ] T029 [US1] 在spread/bot.py的_strategy_loop中调用calculate_real_spread_opportunity替代原有方法
- [ ] T030 [US1] 在spread/bot.py中添加DEBUG级别日志记录真实价差计算过程
- [ ] T031 [US1] 在spread/trade_logger.py中添加real_spread字段记录到开仓日志
- [ ] T032 [US1] 在spread/trade_logger.py中添加spread_cost_breakdown字段记录

**检查点**: 此时User Story 1应完全功能且可独立测试

---

## Phase 4: User Story 2 - 实现真正的Maker策略 (Priority: P0) 🎯 MVP

**目标**: 修复maker订单定价逻辑，确保maker订单能被正确识别并享受0手续费

**独立测试**: 通过查看Extended交易所官网的交易历史验证，修复后应有部分订单显示为maker且手续费为0

### Tests for User Story 2 ⚠️

- [ ] T033 [P] [US2] 在tests/test_maker_pricing.py中创建test_calculate_maker_price_buy测试用例
- [ ] T034 [P] [US2] 在tests/test_maker_pricing.py中创建test_calculate_maker_price_sell测试用例
- [ ] T035 [P] [US2] 在tests/test_maker_pricing.py中创建test_maker_price_below_bid测试用例
- [ ] T036 [P] [US2] 在tests/test_maker_pricing.py中创建test_maker_price_above_ask测试用例
- [ ] T037 [P] [US2] 在tests/test_maker_pricing.py中创建test_should_use_maker_decision测试用例
- [ ] T038 [P] [US2] 在tests/test_order_manager.py中创建test_maker_order_timeout_convert测试用例
- [ ] T039 [P] [US2] 在tests/test_order_manager.py中创建test_maker_order_rejection_handling测试用例

### Implementation for User Story 2

- [ ] T040 [US2] 在spread/calculator.py中添加calculate_maker_price方法（实现price_tick偏移）
- [ ] T041 [US2] 在spread/calculator.py中添加should_use_maker方法（决策逻辑）
- [ ] T042 [US2] 在spread/bot.py的_open_new_pair中使用calculate_maker_price设置extended_price
- [ ] T043 [US2] 在spread/bot.py的_open_new_pair中传递post_only=True参数
- [ ] T044 [US2] 在spread/order_manager.py中添加record_maker_attempt方法记录maker尝试
- [ ] T045 [US2] 在spread/order_manager.py中添加record_maker_rejection方法记录拒绝
- [ ] T046 [US2] 在spread/order_manager.py中实现get_maker_success_rate方法
- [ ] T047 [US2] 在spread/order_manager.py中实现should_adjust_price_tick方法
- [ ] T048 [US2] 在spread/order_manager.py的convert_to_taker中添加当前价差检查逻辑
- [ ] T049 [US2] 在spread/order_manager.py中更新日志显示maker订单实际状态
- [ ] T050 [US2] 在spread/trade_logger.py中添加order_type字段（maker/taker）
- [ ] T051 [US2] 在spread/trade_logger.py中添加post_only字段
- [ ] T052 [US2] 在spread/trade_logger.py中添加is_rejected字段

**检查点**: 此时User Stories 1和2都应独立工作

---

## Phase 5: User Story 3 - 修复仓位平衡计算逻辑 (Priority: P1)

**目标**: 修复Extended和Lighter仓位平衡状态的计算逻辑，正确显示仓位是否对等

**独立测试**: 通过查看日志中的"仓位平衡状态"输出验证，修复后差异率应接近0%（而非200%）

### Tests for User Story 3 ⚠️

- [ ] T053 [P] [US3] 在tests/test_position_balance.py中创建test_calculate_balance_equal_positions测试用例
- [ ] T054 [P] [US3] 在tests/test_position_balance.py中创建test_calculate_balance_imbalanced测试用例
- [ ] T055 [P] [US3] 在tests/test_position_balance.py中创建test_calculate_balance_multiple_pairs测试用例
- [ ] T056 [P] [US3] 在tests/test_position_balance.py中创建test_diff_rate_subtraction_not_addition测试用例
- [ ] T057 [P] [US3] 在tests/test_position_balance.py中创建test_imbalance_level_determination测试用例

### Implementation for User Story 3

- [ ] T058 [US3] 在spread/position_aggregator.py中添加PositionSummary数据类
- [ ] T059 [US3] 在spread/position_aggregator.py中添加BalanceResult数据类
- [ ] T060 [US3] 在spread/position_aggregator.py中实现calculate_balance方法（使用相减）
- [ ] T061 [US3] 在spread/position_aggregator.py中实现determine_imbalance_level方法
- [ ] T062 [US3] 在spread/bot.py的_log_position_status中使用新的calculate_balance
- [ ] T063 [US3] 在spread/bot.py中修复第335-349行：将diff_qty改为abs(extended - lighter)
- [ ] T064 [US3] 在spread/bot.py中更新日志输出显示imbalance_level
- [ ] T065 [US3] 在spread/bot.py中添加仓位不平衡警报逻辑

**检查点**: 所有用户故事现在都应独立功能

---

## Phase 6: User Story 4 - 修复平仓价格选择逻辑 (Priority: P1)

**目标**: 修复平仓时的价格选择，避免因价差方向反转导致的巨额亏损

**独立测试**: 通过回测历史数据验证，修复后平仓收益应接近预期

### Tests for User Story 4 ⚠️

- [ ] T066 [P] [US4] 在tests/test_real_spread_calculator.py中创建test_close_price_long_position测试用例
- [ ] T067 [P] [US4] 在tests/test_real_spread_calculator.py中创建test_close_price_short_position测试用例
- [ ] T068 [P] [US4] 在tests/test_bot.py中创建test_should_close_position_profitable测试用例
- [ ] T069 [P] [US4] 在tests/test_bot.py中创建test_should_close_position_timeout测试用例
- [ ] T070 [P] [US4] 在tests/test_bot.py中创建test_should_close_position_diverging测试用例

### Implementation for User Story 4

- [ ] T071 [US4] 在spread/bot.py中实现_calculate_close_pnl方法（使用真实价差）
- [ ] T072 [US4] 在spread/bot.py中实现_is_spread_diverging方法
- [ ] T073 [US4] 在spread/bot.py中实现_should_close_position方法（多级优先级）
- [ ] T074 [US4] 在spread/bot.py的_monitor_pairs中调用_should_close_position
- [ ] T075 [US4] 在spread/bot.py中添加P1-P5优先级平仓逻辑
- [ ] T076 [US4] 在spread/bot.py的_close_pair_with_market_price中使用真实价差验证
- [ ] T077 [US4] 在spread/trade_logger.py中添加close_reason字段
- [ ] T078 [US4] 在spread/trade_logger.py中添加close_priority字段

**检查点**: User Story 4完成，平仓逻辑优化

---

## Phase 7: User Story 5 - 调整最小价差率阈值 (Priority: P1)

**目标**: 提高最小价差率阈值，确保只有真正盈利的机会才会开仓

**独立测试**: 通过观察开仓频率和盈亏比例验证

### Tests for User Story 5 ⚠️

- [ ] T079 [P] [US5] 在tests/test_config.py中创建test_min_spread_rate_default_value测试用例
- [ ] T080 [P] [US5] 在tests/test_config.py中创建test_effective_min_spread_calculation测试用例
- [ ] T081 [P] [US5] 在tests/test_real_spread_calculator.py中创建test_threshold_enforcement测试用例
- [ ] T082 [P] [US5] 在tests/test_real_spread_calculator.py中创建test_below_threshold_rejection测试用例

### Implementation for User Story 5

- [ ] T083 [US5] 在spread/config.py中更新min_spread_rate默认值为Decimal('0.0010')
- [ ] T084 [US5] 在spread/config.py中添加effective_min_spread属性返回min_spread_rate + latency_buffer
- [ ] T085 [US5] 在spread/real_spread_calculator.py中使用effective_min_spread作为阈值
- [ ] T086 [US5] 在spread/bot.py中添加日志显示实际阈值和价差率对比
- [ ] T087 [US5] 在spread/bot.py中添加统计数据记录拒绝开仓次数
- [ ] T088 [US5] 在spread/bot.py中实现_threshold_violation_counter用于监控

**检查点**: User Story 5完成，阈值调整生效

---

## Phase 8: User Story 6 - 实现正确的收益计算和手续费扣除 (Priority: P2)

**目标**: 在收益计算中正确扣除手续费和点差成本，准确反映实际盈亏

**独立测试**: 通过对比计算收益和实际交易所余额验证

### Tests for User Story 6 ⚠️

- [ ] T089 [P] [US6] 在tests/test_cost_calculator.py中创建test_calculate_trade_costs_taker_taker测试用例
- [ ] T090 [P] [US6] 在tests/test_cost_calculator.py中创建test_calculate_trade_costs_maker_taker测试用例
- [ ] T091 [P] [US6] 在tests/test_cost_calculator.py中创建test_calculate_trade_costs_maker_maker测试用例
- [ ] T092 [P] [US6] 在tests/test_profit_calculator.py中创建test_profit_with_cost_breakdown测试用例

### Implementation for User Story 6

- [ ] T093 [US6] 在spread/cost_calculator.py中实现calculate_trade_costs方法
- [ ] T094 [US6] 在spread/cost_calculator.py中添加determine_fee_rate方法（maker/taker）
- [ ] T095 [US6] 在spread/trade_logger.py的log_trade_closing中添加成本分解参数
- [ ] T096 [US6] 在spread/trade_logger.py中添加格式化成本分解的方法
- [ ] T097 [US6] 在spread/profit_calculator.py中使用TradeCostBreakdown计算净收益
- [ ] T098 [US6] 在spread/profit_calculator.py中添加盈亏归因分析

**检查点**: User Story 6完成，收益计算准确

---

## Phase 9: User Story 7 - 优化开仓和平仓策略 (Priority: P2)

**目标**: 基于真实成本结构优化开仓和平仓策略，提高整体盈利能力

**独立测试**: 通过模拟交易验证策略改进

### Tests for User Story 7 ⚠️

- [ ] T099 [P] [US7] 在tests/test_bot.py中创建test_open_condition_insufficient_profit测试用例
- [ ] T100 [P] [US7] 在tests/test_bot.py中创建test_close_delay_on_divergence测试用例
- [ ] T101 [P] [US7] 在tests/test_bot.py中创建test_close_time_small_profit测试用例

### Implementation for User Story 7

- [ ] T102 [US7] 在spread/bot.py中实现_should_open_with_taker方法（检查taker利润）
- [ ] T103 [US7] 在spread/bot.py的_open_new_pair中调用_should_open_with_taker验证
- [ ] T104 [US7] 在spread/bot.py的_check_close_conditions中集成延迟平仓逻辑
- [ ] T105 [US7] 在spread/config.py中添加enable_delay_on_divergence配置
- [ ] T106 [US7] 在spread/bot.py中添加divergence_detection逻辑

**检查点**: User Story 7完成，策略优化生效

---

## Phase 10: User Story 8 - 添加手续费和成本统计 (Priority: P3)

**目标**: 在统计报告中添加手续费和点差成本明细，便于分析和优化策略

**独立测试**: 通过查看统计报告验证

### Tests for User Story 8 ⚠️

- [ ] T107 [P] [US8] 在tests/test_trade_logger.py中创建test_export_trades_csv测试用例
- [ ] T108 [P] [US8] 在tests/test_trade_logger.py中创建test_export_orders_csv测试用例
- [ ] T109 [P] [US8] 在tests/test_data_collector.py中创建test_generate_daily_report测试用例

### Implementation for User Story 8

- [ ] T110 [US8] 创建spread/data_collector.py实现IDataCollector接口
- [ ] T111 [US8] 在spread/data_collector.py中实现export_trades_csv方法
- [ ] T112 [US8] 在spread/data_collector.py中实现export_orders_csv方法
- [ ] T113 [US8] 在spread/data_collector.py中添加collect_order_execution方法
- [ ] T114 [US8] 创建spread/trade_analyzer.py实现ITradeAnalyzer接口
- [ ] T115 [US8] 在spread/trade_analyzer.py中实现calculate_win_rate方法
- [ ] T116 [US8] 在spread/trade_analyzer.py中实现generate_daily_report方法
- [ ] T117 [US8] 在spread/bot.py中集成DataCollector记录所有交易
- [ ] T118 [US8] 在spread/bot.py的_stats报告中添加成本明细输出

**检查点**: 所有用户故事现在都应独立功能

---

## Phase 11: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [ ] T119 [P] 更新CLAUDE.md添加009-fix-spread-loss-fees的Active Technologies
- [ ] T120 [P] 更新README.md说明对手价计算和Maker策略变更
- [ ] T121 代码清理：移除旧的中间价计算代码
- [ ] T122 [P] 添加更多单元测试覆盖边界情况
- [ ] T123 性能优化：确保价差计算性能不低于之前
- [ ] T124 运行quickstart.md中的示例验证修复效果
- [ ] T125 生成最终文档和使用说明

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-10)**: 全部依赖Foundational阶段完成
  - 用户故事可并行进行（如果有人力）
  - 或按优先级顺序执行（P0 → P1 → P2 → P3）
- **Polish (Phase 11)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P0)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P0)**: Foundational完成后可开始 - 可与US1并行
- **User Story 3 (P1)**: Foundational完成后可开始 - 可与US1/US2并行
- **User Story 4 (P1)**: Foundational完成后可开始 - 依赖US1的真实价差计算
- **User Story 5 (P1)**: Foundational完成后可开始 - 可与其他故事并行
- **User Story 6 (P2)**: 依赖US1-US5 - 使用前面故事的成果
- **User Story 7 (P2)**: 依赖US1, US4 - 需要真实价差和平仓逻辑
- **User Story 8 (P3)**: 依赖所有前面的故事 - 汇总所有数据

### Within Each User Story

- 测试必须先写并在实施前失败
- 模型在服务前
- 服务在端点前
- 核心实现在集成前
- 故事完成后进入下一个优先级

### Parallel Opportunities

- Setup阶段所有标记[P]的任务可并行
- Foundational阶段所有标记[P]的任务可并行
- Foundational完成后，P0优先级的US1和US2可完全并行
- 不同用户故事可由不同团队成员并行工作
- 每个用户故事内的测试可并行编写

---

## Parallel Example: User Story 1 & 2 (P0 MVP)

```bash
# 并行启动User Story 1和User Story 2的所有测试:
Task: "在tests/test_real_spread_calculator.py中创建test_calculate_long_spread_positive测试用例"
Task: "在tests/test_real_spread_calculator.py中创建test_calculate_short_spread_positive测试用例"
Task: "在tests/test_maker_pricing.py中创建test_calculate_maker_price_buy测试用例"
Task: "在tests/test_maker_pricing.py中创建test_calculate_maker_price_sell测试用例"

# 并行实现RealSpreadCalculator和Maker定价:
Task: "在spread/real_spread_calculator.py中实现calculate_long_spread方法"
Task: "在spread/real_spread_calculator.py中实现calculate_short_spread方法"
Task: "在spread/calculator.py中添加calculate_maker_price方法"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2 Only, P0 Priority)

1. 完成Phase 1: Setup
2. 完成Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成Phase 3: User Story 1（对手价计算）
4. 完成Phase 4: User Story 2（Maker策略）
5. **停止并验证**: 独立测试User Story 1和2
6. 如果准备就绪，部署/演示

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 + 2 → 独立测试 → 部署/演示（MVP！）
3. 添加 User Story 3 + 4 + 5 → 独立测试 → 部署/演示
4. 添加 User Story 6 + 7 → 独立测试 → 部署/演示
5. 添加 User Story 8 → 独立测试 → 最终部署
6. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy

有多位开发人员时：

1. 团队一起完成 Setup + Foundational
2. Foundational完成后:
   - 开发者 A: User Story 1（对手价）
   - 开发者 B: User Story 2（Maker策略）
   - 开发者 C: User Story 3（仓位平衡）
3. 故事独立完成并集成

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应可独立完成和测试
- 在实施前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Summary

- **Total Tasks**: 125
- **Tasks per User Story**:
  - US1 (对手价计算): 17 tasks
  - US2 (Maker策略): 20 tasks
  - US3 (仓位平衡): 13 tasks
  - US4 (平仓逻辑): 13 tasks
  - US5 (阈值调整): 10 tasks
  - US6 (收益计算): 10 tasks
  - US7 (策略优化): 8 tasks
  - US8 (成本统计): 12 tasks
- **Setup Tasks**: 4
- **Foundational Tasks**: 11
- **Polish Tasks**: 7
- **Parallel Opportunities**:
  - Phase 1: 3 parallel tasks
  - Phase 2: 6 parallel tasks
  - US1 & US2 (P0): 可完全并行
  - US3-US5 (P1): 可部分并行
- **Independent Test Criteria**: 每个用户故事都有明确的独立测试标准
- **Suggested MVP Scope**: User Story 1 + 2（P0优先级）- 核心价差计算和Maker策略
- **Format Validation**: ✅ 所有任务遵循checklist格式（checkbox, ID, labels, file paths）
