# Tasks: 价差套利平仓逻辑修复与磨损优化

**Input**: Design documents from `/specs/008-fix-spread-close/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/api.py

**Tests**: 本功能包含测试任务，需要在实现前编写测试用例。

**组织方式**: 任务按用户故事分组，每个故事可独立实现和测试。

## 格式说明: `[ID] [P?] [Story] 描述`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事（US1, US2, US3, US4）
- 描述中包含精确的文件路径

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基础结构准备

- [ ] T001 创建数据模型类文件 spread/models.py
- [ ] T002 备份当前要修改的文件到 spread/backup/ 目录

---

## Phase 2: Foundational (阻塞性前置条件)

**目的**: 所有用户故事依赖的核心基础设施

**⚠️ 关键**: 本阶段完成前，任何用户故事都无法开始

- [ ] T003 在 spread/models.py 中实现 SpreadSnapshot 数据类（包含timestamp, extended_bid/ask/mid, lighter_bid/ask/mid, spread, spread_rate等字段）
- [ ] T004 [P] 在 spread/models.py 中实现 SpreadChange 数据类（包含open_spread, current_spread, spread_delta, is_converged等字段）
- [ ] T005 [P] 在 spread/models.py 中实现 CloseDecision 数据类（包含pair_id, should_close, priority, reason, spread_change等字段）
- [ ] T006 [P] 在 spread/models.py 中实现 PositionBalance 数据类（包含extended_total_qty, lighter_total_qty, diff_qty, is_imbalanced等字段）
- [ ] T007 在 spread/config.py 中添加新的配置参数（SPREAD_CONVERGENCE_THRESHOLD, CLOSE_PRIORITY_ENABLED, MIN_CLOSE_PROFIT_RATE, MAX_CLOSE_LOSS_RATE, DELAY_CLOSE_THRESHOLD）

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 修复价差方向计算逻辑 (Priority: P1) 🎯 MVP

**目标**: 使用中间价计算价差，根据价差符号决定正确的套利方向

**独立测试**: 使用历史价格数据回测，验证修复后的方向在价差收敛时能够盈利

### 测试 for User Story 1

> **注意: 先编写测试，确保测试失败后再实现功能**

- [ ] T008 [P] [US1] 在 tests/test_calculator_fix.py 中编写测试用例: 测试中间价计算（验证spread = extended_mid - lighter_mid）
- [ ] T009 [P] [US1] 在 tests/test_calculator_fix.py 中编写测试用例: 测试价差符号判断（spread > 0 返回short_spread, spread < 0 返回long_spread）
- [ ] T010 [P] [US1] 在 tests/test_calculator_fix.py 中编写测试用例: 测试做多价差盈利逻辑（开仓spread=-30, 收敛到-10时应盈利）
- [ ] T011 [P] [US1] 在 tests/test_calculator_fix.py 中编写测试用例: 测试做空价差盈利逻辑（开仓spread=+30, 收敛到+10时应盈利）

### 实现 for User Story 1

- [ ] T012 [US1] 在 spread/calculator.py 中实现 calculate_spread_opportunity_mid 函数（计算中间价extended_mid和lighter_mid，计算spread = extended_mid - lighter_mid）
- [ ] T013 [US1] 在 spread/calculator.py 中实现价差符号判断逻辑（spread > 0 → extended_side='sell', spread < 0 → extended_side='buy'）
- [ ] T014 [US1] 在 spread/calculator.py 中修改 calculate_spread_opportunity 函数，调用calculate_spread_opportunity_mid替代原有逻辑
- [ ] T015 [US1] 在 spread/bot.py 中修改 _open_new_pair 函数，使用新的中间价计算机会
- [ ] T016 [US1] 验证价差方向与盈亏计算一致性（在spread_pair.py的calculate_unrealized_pnl中验证价差收敛时盈亏为正）

**检查点**: 此时User Story 1应完全独立可用且可测试

---

## Phase 4: User Story 2 - 修复平仓价格选择逻辑 (Priority: P1)

**目标**: 移除依赖反向机会的平仓逻辑，所有平仓使用当前订单簿对手价

**独立测试**: 模拟不同市场条件，验证平仓价格使用的是对手价而非机会价格

### 测试 for User Story 2

- [ ] T017 [P] [US2] 在 tests/test_closing_logic.py 中编写测试用例: 测试多头仓位平仓价格选择（Extended用bid, Lighter用ask）
- [ ] T018 [P] [US2] 在 tests/test_closing_logic.py 中编写测试用例: 测试空头仓位平仓价格选择（Extended用ask, Lighter用bid）
- [ ] T019 [P] [US2] 在 tests/integration/test_closing_logic.py 中编写集成测试: 测试完整开仓-平仓流程使用市价平仓

### 实现 for User Story 2

- [ ] T020 [US2] 在 spread/bot.py 中实现 _close_pair_with_market_price 函数（使用extended_bid/ask和lighter_bid/ask确定对手价）
- [ ] T021 [US2] 在 spread/bot.py 中修改 _strategy_loop 函数，移除 _find_opposite_pair 和机会平仓逻辑
- [ ] T022 [US2] 在 spread/bot.py 中修改 _monitor_pairs 函数，使用 _close_pair_with_market_price 替代 _close_pair
- [ ] T023 [US2] 在 spread/bot.py 中移除或标记为废弃 _find_opposite_pair 函数

**检查点**: 此时User Stories 1和2都应独立可用

---

## Phase 5: User Story 3 - 增加价差收敛检查 (Priority: P2)

**目标**: 新增价差收敛状态检查函数，优先在价差收敛时平仓获利

**独立测试**: 回测验证只有在价差收敛时才触发平仓

### 测试 for User Story 3

- [ ] T024 [P] [US3] 在 tests/test_spread_convergence.py 中编写测试用例: 测试做多价差收敛判断（spread_delta > 0时返回True）
- [ ] T025 [P] [US3] 在 tests/test_spread_convergence.py 中编写测试用例: 测试做空价差收敛判断（spread_delta < 0时返回True）
- [ ] T026 [P] [US3] 在 tests/test_spread_convergence.py 中编写测试用例: 测试价差扩大情况（返回False且正确标记status）
- [ ] T027 [P] [US3] 在 tests/integration/test_closing_logic.py 中编写集成测试: 测试5级优先级平仓触发条件

### 实现 for User Story 3

- [ ] T028 [US3] 在 spread/spread_pair.py 中实现 is_spread_converged 方法（计算当前中间价差，与open_spread比较，根据extended_side判断收敛）
- [ ] T029 [US3] 在 spread/bot.py 中实现 _check_close_conditions 函数（实现P1-P5五级优先级检查逻辑）
- [ ] T030 [US3] 在 spread/bot.py 中实现 _create_close_decision 辅助函数（创建CloseDecision对象，包含priority, reason_code等）
- [ ] T031 [US3] 在 spread/bot.py 中修改 _monitor_pairs 函数，调用 _check_close_conditions 替代 _check_force_close
- [ ] T032 [US3] 在 spread/bot.py 中实现价差扩大时的延迟平仓逻辑（P5优先级：亏损>=1%时延迟平仓）

**检查点**: 所有用户故事都应独立可用

---

## Phase 6: User Story 4 - 增强诊断日志 (Priority: P3)

**目标**: 在trade.log中记录详细的价差信息，包括开仓快照、平仓对比、持仓状态

**独立测试**: 运行策略后检查trade.log，验证所有关键信息都被记录

### 测试 for User Story 4

- [ ] T033 [P] [US4] 在 tests/test_trade_logger.py 中编写测试用例: 测试价差快照日志格式
- [ ] T034 [P] [US4] 在 tests/test_trade_logger.py 中编写测试用例: 测试平仓分析日志格式
- [ ] T035 [P] [US4] 在 tests/test_trade_logger.py 中编写测试用例: 测试仓位平衡日志格式

### 实现 for User Story 4

- [ ] T036 [US4] 在 spread/trade_logger.py 中实现 log_spread_snapshot 方法（记录=== 价差快照 ===，包含bid/ask/mid/价差率/方向/预期）
- [ ] T037 [US4] 在 spread/trade_logger.py 中实现 log_close_analysis 方法（记录=== 平仓价差分析 ===，包含开仓价差/当前价差/变化量/收敛状态/平仓原因）
- [ ] T038 [US4] 在 spread/trade_logger.py 中实现 log_position_balance 方法（记录=== 仓位平衡状态 ===，包含Extended/Lighter仓位/差异/警告级别）
- [ ] T039 [US4] 在 spread/trade_logger.py 中实现 _format_spread_snapshot 辅助函数（格式化价差快照为简体中文字符串）
- [ ] T040 [US4] 在 spread/trade_logger.py 中实现 _format_close_analysis 辅助函数（格式化平仓分析为简体中文字符串，包含⚠️警告标记）
- [ ] T041 [US4] 在 spread/bot.py 中集成 log_spread_snapshot 到 _open_new_pair 函数（开仓成功后记录价差快照）
- [ ] T042 [US4] 在 spread/bot.py 中集成 log_close_analysis 到 _close_pair_with_market_price 函数（平仓成功后记录分析）
- [ ] T043 [US4] 在 spread/bot.py 中集成 log_position_balance 到 _monitor_pairs 函数（定期记录仓位平衡状态）

---

## Phase 7: Polish & 跨领域优化

**目的**: 影响多个用户故事的改进

- [ ] T044 [P] 更新 CLAUDE.md 文件，记录008-fix-spread-close的修改
- [ ] T045 代码清理和重构（移除废弃的_find_opposite_pair函数及相关注释）
- [ ] T046 [P] 性能优化：优化价差计算函数，确保<100ms延迟
- [ ] T047 [P] 添加更多单元测试（覆盖边界条件：价差=0、bid=ask、极端价差值等）
- [ ] T048 运行 quickstart.md 验证（运行30分钟测试，验证盈亏率改善）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-6)**: 都依赖Foundational阶段完成
  - US1和US2可并行（都是P1优先级）
  - US3依赖US1完成（需要正确的价差方向）
  - US4可独立进行，但集成时需要其他故事完成
- **Polish (Phase 7)**: 依赖所有用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P1)**: Foundational完成后可开始 - 与US1可并行
- **User Story 3 (P2)**: 依赖US1完成（需要正确的价差计算才能判断收敛）
- **User Story 4 (P3)**: 可独立开始，但集成测试需要其他故事

### Within Each User Story

- 测试必须先编写并失败，然后再实现
- US1: 数据模型 → calculator修改 → bot集成
- US2: bot平仓函数 → 机会平仓移除 → monitor集成
- US3: spread_pair收敛检查 → bot条件检查 → monitor集成
- US4: trade_logger函数 → bot集成

### Parallel Opportunities

- Setup阶段: T001, T002可并行
- Foundational阶段: T004, T005, T006可并行（不同数据类）
- US1测试: T008-T011全部可并行
- US1和US2可在Foundational完成后并行开发
- US4测试: T033-T035全部可并行
- Polish阶段: T044, T046, T047可并行

---

## Parallel Example: User Story 1

```bash
# 并行启动User Story 1的所有测试:
Task T008: "在 tests/test_calculator_fix.py 中编写测试用例: 测试中间价计算"
Task T009: "在 tests/test_calculator_fix.py 中编写测试用例: 测试价差符号判断"
Task T010: "在 tests/test_calculator_fix.py 中编写测试用例: 测试做多价差盈利逻辑"
Task T011: "在 tests/test_calculator_fix.py 中编写测试用例: 测试做空价差盈利逻辑"

# 并行启动Foundational阶段的数据模型:
Task T004: "实现 SpreadSnapshot 数据类"
Task T005: "实现 SpreadChange 数据类"
Task T006: "实现 CloseDecision 数据类"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational (关键 - 阻塞所有故事)
3. 完成 Phase 3: User Story 1
4. **停止并验证**: 独立测试User Story 1
5. 如准备好则部署/演示

### 增量交付

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示 (MVP!)
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 添加 User Story 4 → 独立测试 → 部署/演示
6. 每个故事都增加价值而不破坏之前的故事

### 并行团队策略

有多个开发者时:

1. 团队一起完成Setup + Foundational
2. Foundational完成后:
   - 开发者A: User Story 1 (价差计算)
   - 开发者B: User Story 2 (平仓价格) - 与US1并行
3. US1完成后:
   - 开发者A: User Story 3 (价差收敛检查)
   - 开发者C: User Story 4 (诊断日志)
4. 故事独立完成并集成

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免: 模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Summary

- **总任务数**: 48
- **Setup**: 2 任务
- **Foundational**: 5 任务
- **User Story 1**: 9 任务 (4测试 + 5实现)
- **User Story 2**: 7 任务 (3测试 + 4实现)
- **User Story 3**: 9 任务 (4测试 + 5实现)
- **User Story 4**: 11 任务 (3测试 + 8实现)
- **Polish**: 5 任务

**并行机会**: 已标注[P]的任务（约20个可并行）

**MVP范围**: Phase 1-3 (Setup + Foundational + User Story 1) = 16任务

**格式验证**: ✅ 所有任务遵循checklist格式（checkbox, ID, labels, file paths）
