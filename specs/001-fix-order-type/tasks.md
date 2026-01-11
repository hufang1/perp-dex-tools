# Tasks: 修复订单类型问题并增加交易成功率统计

**Input**: Design documents from `/specs/001-fix-order-type/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 本功能使用TDD方法，包含测试任务

**Organization**: 任务按用户故事分组，确保每个故事可以独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 任务所属用户故事（如US1, US2, US3）
- 包含精确文件路径

## Path Conventions

- **单一项目**: `spread/`, `tests/` 在仓库根目录
- 路径基于plan.md中的项目结构

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和基本结构

本功能复用现有项目结构，无需额外的setup任务。直接进入基础阶段。

---

## Phase 2: Foundational (阻塞性前置条件)

**Purpose**: 所有用户故事依赖的核心基础设施

**⚠️ CRITICAL**: 在此阶段完成前，不能开始任何用户故事工作

- [X] T001 [P] 在spread/models.py中添加枚举类型OperationType定义
- [X] T002 [P] 在spread/models.py中添加枚举类型OperationStatus定义
- [X] T003 [P] 在spread/models.py中添加枚举类型ExchangeType定义
- [X] T004 [P] 在spread/models.py中添加枚举类型FailureReason定义
- [X] T005 在spread/success_tracker.py中创建SpreadOperationResult数据类
- [X] T006 在spread/success_tracker.py中创建SuccessTracker类基础结构
- [X] T007 在spread/config.py中添加仓位验证配置项（threshold, rate_threshold）

**Checkpoint**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 统一使用Taker订单进行开仓 (Priority: P1) 🎯 MVP

**Goal**: 强制所有开仓订单使用taker订单类型，确保订单立即成交，避免maker订单挂单未成交导致的仓位失衡

**Independent Test**: 监控订单类型是否正确设置为taker，验证订单是否立即成交，maker_attempts计数器保持为0

### Tests for User Story 1

> **NOTE: 先编写这些测试，确保它们在实现前失败**

- [X] T008 [P] [US1] 在tests/test_order_manager.py中添加强制taker订单测试
- [X] T009 [P] [US1] 在tests/test_hedge_manager.py中添加taker订单测试
- [X] T010 [P] [US1] 在tests/integration/test_taker_order_integration.py中添加taker订单集成测试

### Implementation for User Story 1

- [X] T011 [P] [US1] 在spread/order_manager.py中移除maker订单决策逻辑（约第54-100行相关部分）
- [X] T012 [P] [US1] 在spread/hedge_manager.py中确认taker订单逻辑（execute_hedge方法）
- [X] T013 [US1] 在spread/bot.py的_open_new_pair方法中移除should_use_maker调用（约第877-881行）
- [X] T014 [US1] 在spread/bot.py的_open_new_pair方法中强制设置use_maker=False（约第877行）
- [X] T015 [US1] 在spread/bot.py的_open_new_pair方法中移除maker_price计算逻辑（约第896-906行）
- [X] T016 [US1] 在spread/bot.py的_open_new_pair方法中使用对手价作为taker订单价格（买单用ask，卖单用bid）
- [X] T017 [US1] 在spread/bot.py的_open_new_pair方法中传递post_only=False参数到place_spread_maker_order（约第908-912行）
- [X] T018 [US1] 在spread/bot.py的_open_new_pair方法中移除maker_timeout_wait调用（约第922-958行）
- [X] T019 [US1] 在spread/bot.py的_open_new_pair方法中简化为直接taker订单等待成交（约第959-965行）
- [X] T020 [US1] 在spread/bot.py的_open_new_pair方法中移除convert_to_taker逻辑（约第930-949行）
- [X] T021 [US1] 在spread/calculator.py中保留should_use_maker方法但添加废弃警告注释
- [X] T022 [US1] 在spread/calculator.py中保留calculate_maker_price方法但添加废弃警告注释
- [X] T023 [US1] 在spread/bot.py的统计报告中添加maker订单统计（验证attempts=0）
- [X] T024 [US1] 在spread/config.py中设置use_maker_orders=False（确认默认值）
- [X] T025 [US1] 在spread/trade_logger.py中添加订单类型日志记录（记录"使用taker订单"）

**Checkpoint**: 此时User Story 1应该完全功能且可独立测试 - 所有开仓订单使用taker类型，无maker订单挂单

---

## Phase 4: User Story 2 - 修复开仓仓位数量不一致 (Priority: P1)

**Goal**: 开仓完成后验证Extended和Lighter仓位数量一致性，消除0.01 ETH差异

**Independent Test**: 验证开仓后两个交易所的仓位数量差异为0，不一致时触发警告

### Tests for User Story 2

- [X] T026 [P] [US2] 在tests/test_position_consistency.py中添加仓位一致性验证测试
- [X] T027 [P] [US2] 在tests/integration/test_position_consistency_integration.py中添加仓位一致性集成测试

### Implementation for User Story 2

- [X] T028 [P] [US2] 在spread/position_aggregator.py中添加get_position_balance_for_pair方法
- [X] T029 [P] [US2] 在spread/models.py中添加PositionConsistencyCheck数据类
- [X] T030 [US2] 在spread/bot.py中创建validate_position_consistency方法
- [X] T031 [US2] 在spread/bot.py的_open_new_pair方法中Lighter对冲成功后调用仓位一致性验证
- [X] T032 [US2] 在spread/bot.py的validate_position_consistency方法中计算差异数量和差异率
- [X] T033 [US2] 在spread/bot.py的validate_position_consistency方法中检查阈值（threshold=0.001 ETH, rate_threshold=10%）
- [X] T034 [US2] 在spread/bot.py的validate_position_consistency方法中记录仓位一致日志
- [X] T035 [US2] 在spread/bot.py的validate_position_consistency方法中记录仓位不一致警告日志
- [X] T036 [US2] 在spread/bot.py的_open_new_pair方法中仓位不一致时返回False并清理部分仓位（警告记录，暂不强制清理）
- [X] T037 [US2] 在spread/trade_logger.py中添加仓位一致性状态日志记录

**Checkpoint**: 此时User Story 1和User Story 2都应该独立工作 - 仓位一致性验证功能完成

---

## Phase 5: User Story 3 - 开仓/平仓成功率统计与失败原因追踪 (Priority: P2)

**Goal**: 收集并统计开仓和平仓操作的成功率，记录失败原因，CSV输出使用双语列名

**Independent Test**: 验证CSV文件正确记录每次交易操作的结果和失败原因，列名使用双语格式

### Tests for User Story 3

- [X] T038 [P] [US3] 在tests/test_success_tracker.py中添加成功率追踪器单元测试
- [X] T039 [P] [US3] 在tests/integration/test_success_tracking_integration.py中添加成功率统计集成测试

### Implementation for User Story 3

- [X] T040 [P] [US3] 在spread/success_tracker.py中实现record_operation方法
- [X] T041 [P] [US3] 在spread/success_tracker.py中实现get_success_rate方法
- [X] T042 [P] [US3] 在spread/success_tracker.py中实现get_failure_reason_distribution方法
- [X] T043 [P] [US3] 在spread/success_tracker.py中实现export_operations_csv方法（双语列名）
- [X] T044 [P] [US3] 在spread/success_tracker.py中实现export_summary_csv方法（双语列名）
- [X] T045 [P] [US3] 在spread/success_tracker.py中实现get_stats_summary方法
- [X] T046 [US3] 在spread/success_tracker.py中实现clear_old_records方法
- [X] T047 [US3] 在spread/bot.py的__init__方法中初始化SuccessTracker实例
- [X] T048 [US3] 在spread/bot.py的_open_new_pair方法开头记录开仓机会检测（OPEN_ATTEMPT）
- [X] T049 [US3] 在spread/bot.py的_open_new_pair方法中检查仓位上限并记录（POSITION_LIMIT）
- [X] T050 [US3] 在spread/bot.py的_open_new_pair方法Extended下单前记录开仓尝试（OPEN_ATTEMPT）
- [X] T051 [US3] 在spread/bot.py的_open_new_pair方法开仓成功后记录（OPEN_SUCCESS）
- [X] T052 [US3] 在spread/bot.py的_open_new_pair方法开仓失败时记录失败原因（OPEN_FAILED）
- [X] T053 [US3] 在spread/bot.py的_close_pair_with_market_price方法中记录平仓尝试（CLOSE_ATTEMPT）
- [X] T054 [US3] 在spread/bot.py的_close_pair_with_market_price方法平仓成功后记录（CLOSE_SUCCESS）
- [X] T055 [US3] 在spread/bot.py的_close_pair_with_market_price方法平仓失败时记录失败原因（CLOSE_FAILED）
- [X] T056 [US3] 在spread/bot.py的_cleanup方法中调用export_operations_csv导出数据
- [X] T057 [US3] 在spread/bot.py的_cleanup方法中调用export_summary_csv导出汇总
- [X] T058 [US3] 在spread/bot.py的统计报告中添加成功率统计展示
- [ ] T059 [US3] 在spread/data_collector.py的export_trades_csv方法中添加成功率字段（双语列名）
- [ ] T060 [US3] 在spread/data_collector.py中更新trades CSV的fieldnames（添加open_status, open_failure_reason等）
- [ ] T061 [US3] 在spread/data_collector.py中实现operations CSV导出方法（operations_YYYY_MM_DD.csv）
- [ ] T062 [US3] 在spread/data_collector.py中实现success_stats CSV导出方法（success_stats_YYYY_MM_DD.csv）

**Checkpoint**: 所有用户故事现在都应该独立功能 - 成功率统计功能完成

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 影响多个用户故事的改进

- [X] T063 [P] 在spread/bot.py中添加仓位不一致到success_tracker的失败原因记录
- [X] T064 [P] 在spread/config.py中添加成功率统计相关配置（enable_success_tracking, stats_export_interval）
- [X] T065 运行pytest tests/test_order_manager.py -v验证taker订单测试
- [X] T066 运行pytest tests/test_hedge_manager.py -v验证taker订单测试
- [X] T067 运行pytest tests/test_position_consistency.py -v验证仓位一致性测试
- [X] T068 运行pytest tests/test_success_tracker.py -v验证成功率追踪器测试
- [X] T069 运行pytest tests/integration/ -v验证所有集成测试
- [ ] T070 运行quickstart.md中的验证清单
- [X] T071 [P] 更新CLAUDE.md添加001-fix-order-type功能说明
- [X] T072 检查所有日志输出使用简体中文

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无需额外setup - 可跳过
- **Foundational (Phase 2)**: 无依赖 - 可立即开始 - 阻塞所有用户故事
- **User Stories (Phase 3+)**: 都依赖Foundational阶段完成
  - User Story 1 (P1): 可在Foundational完成后开始
  - User Story 2 (P1): 可在Foundational完成后开始
  - User Story 3 (P2): 可在Foundational完成后开始
- **Polish (Phase 6)**: 依赖于所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P1)**: Foundational完成后可开始 - 可与US1并行或顺序执行
- **User Story 3 (P2)**: Foundational完成后可开始 - 建议在US1和US2之后实现（成功率统计需要记录开仓/平仓操作）

### Within Each User Story

- 测试必须先编写并在实现前失败
- 实现任务按顺序执行（除非标记[P]可并行）
- 核心实现优先于集成
- 故事完成后进入下一个优先级

### Parallel Opportunities

- Foundational阶段：T001-T004可并行（枚举定义），T005-T006可并行
- User Story 1: T008-T010测试可并行，T011-T012可并行
- User Story 2: T026-T027测试可并行，T028-T029可并行
- User Story 3: T038-T039测试可并行，T040-T046可并行
- Phase 6: T063-T064, T071可并行

---

## Parallel Example: User Story 1

```bash
# 一起启动User Story 1的所有测试：
Task: "在tests/test_order_manager.py中添加强制taker订单测试"
Task: "在tests/test_hedge_manager.py中添加taker订单测试"
Task: "在tests/integration/test_taker_order_integration.py中添加taker订单集成测试"

# 一起启动User Story 1的order_manager和hedge_manager修改：
Task: "在spread/order_manager.py中移除maker订单决策逻辑"
Task: "在spread/hedge_manager.py中确认taker订单逻辑"
```

---

## Parallel Example: User Story 2

```bash
# 一起启动User Story 2的所有测试：
Task: "在tests/test_position_consistency.py中添加仓位一致性验证测试"
Task: "在tests/integration/test_position_consistency_integration.py中添加仓位一致性集成测试"

# 一起启动User Story 2的模型创建：
Task: "在spread/position_aggregator.py中添加get_position_balance_for_pair方法"
Task: "在spread/models.py中添加PositionConsistencyCheck数据类"
```

---

## Parallel Example: User Story 3

```bash
# 一起启动User Story 3的所有测试：
Task: "在tests/test_success_tracker.py中添加成功率追踪器单元测试"
Task: "在tests/integration/test_success_tracking_integration.py中添加成功率统计集成测试"

# 一起启动User Story 3的SuccessTracker方法实现：
Task: "在spread/success_tracker.py中实现record_operation方法"
Task: "在spread/success_tracker.py中实现get_success_rate方法"
Task: "在spread/success_tracker.py中实现get_failure_reason_distribution方法"
Task: "在spread/success_tracker.py中实现export_operations_csv方法"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成 Phase 2: Foundational (T001-T007)
2. 完成 Phase 3: User Story 1 (T008-T025)
3. **停止并验证**: 独立测试User Story 1
4. 如就绪则部署/演示

### Incremental Delivery

1. 完成 Foundational (Phase 2) → 基础就绪
2. 添加 User Story 1 (Phase 3) → 独立测试 → 部署/演示 (MVP!)
3. 添加 User Story 2 (Phase 4) → 独立测试 → 部署/演示
4. 添加 User Story 3 (Phase 5) → 独立测试 → 部署/演示
5. 每个故事都增加价值且不破坏之前的故事

### Parallel Team Strategy

有多个开发者时：

1. 团队一起完成Foundational (Phase 2)
2. Foundational完成后:
   - 开发者A: User Story 1 (Taker订单)
   - 开发者B: User Story 2 (仓位一致性)
3. 故事完成后，开发者A/B: User Story 3 (成功率统计)
4. 故事独立完成和集成

---

## Notes

- [P]任务 = 不同文件，无依赖
- [Story]标签将任务映射到特定用户故事以便追踪
- 每个用户故事应该可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何checkpoint停止以独立验证故事
- 避免: 模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Summary

- **Total Tasks**: 72 tasks
- **Setup (Phase 1)**: 0 tasks (复用现有结构)
- **Foundational (Phase 2)**: 7 tasks
- **User Story 1 (Phase 3)**: 18 tasks (含3个测试)
- **User Story 2 (Phase 4)**: 12 tasks (含2个测试)
- **User Story 3 (Phase 5)**: 25 tasks (含2个测试)
- **Polish (Phase 6)**: 10 tasks
- **Parallel Opportunities**: 15+ tasks marked [P]
- **MVP Scope**: Phase 2 + Phase 3 = 25 tasks (强制taker订单)

**Format Validation**: ✅ All tasks follow the checklist format (- [ ] [ID] [P?] [Story] Description with file path)
