# Tasks: Extended Maker模式降低手续费

**Input**: Design documents from `/specs/017-ext-maker-mode/`
**Prerequisites**: plan.md, spec.md
**Feature Branch**: `017-ext-maker-mode`
**Created**: 2026-01-18

**Tests**: 根据spec.md中的要求，本功能包含测试任务（单元测试和集成测试）

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目初始化和分支创建

- [ ] T001 创建feature分支 `017-ext-maker-mode`
- [ ] T002 备份现有Taker模式代码到 `.specify/backups/017-ext-maker-mode/` 目录
- [ ] T003 [P] 在config.py中添加Maker模式配置项（开仓阈值0.09%、平仓阈值0.06%、挂单超时时间、价格监控间隔、价差监控间隔、连续重挂次数限制）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 核心基础设施，必须在任何用户故事实现之前完成

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 扩展BotState枚举，在spread/models.py中添加3个新状态：OPENING_MAKER_WAIT、CLOSING_MAKER_WAIT、LIGHTER_HEDGING
- [ ] T005 在spread/state_manager.py中更新STATE_NAMES_CN映射，添加3个新状态的中文名称
- [ ] T006 [P] 在exchanges/extended.py中添加Extended Maker订单API方法：place_maker_order()、cancel_order()
- [ ] T007 [P] 在exchanges/extended.py中添加Extended WebSocket订单状态订阅和订单簿订阅方法
- [ ] T008 [P] 实现统一状态转换日志函数，格式为`💥 {旧状态中文} -> {新状态中文} | {原因}`，使用print()和logger.info()同时输出
- [ ] T009 创建spread/maker_order_monitor.py模块，实现Extended Maker订单监控器类
- [ ] T010 创建spread/price_monitor.py模块，实现实时价差和价格监控器类

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Extended使用Maker模式降低手续费 (Priority: P1) 🎯 MVP

**Goal**: 将Extended从Taker模式改为Maker模式，实现串行执行流程（Extended先成交，然后Lighter对冲），新增3个状态处理挂单等待和对冲逻辑

**Independent Test**: 可以通过模拟交易测试，验证Extended使用Maker挂单后手续费计算是否正确，以及订单是否正常成交，状态转换是否正确

### Tests for User Story 1

- [ ] T011 [P] [US1] 编写Extended Maker订单API单元测试 in tests/unit/test_extended_maker_mode.py
- [ ] T012 [P] [US1] 编写状态机转换测试（新状态转换流程） in tests/unit/test_state_machine.py
- [ ] T013 [P] [US1] 编写Maker订单监控器单元测试 in tests/unit/test_maker_order_monitor.py
- [ ] T014 [P] [US1] 编写价格监控器单元测试 in tests/unit/test_price_monitor.py
- [ ] T015 [P] [US1] 编写Maker开仓流程集成测试 in tests/integration/test_maker_opening_flow.py
- [ ] T016 [P] [US1] 编写Maker平仓流程集成测试 in tests/integration/test_maker_closing_flow.py

### Implementation for User Story 1

- [ ] T017 [P] [US1] 在spread/models.py中创建MakerOrder数据类（订单ID、挂单价格、挂单数量、挂单方向、订单状态、成交数量、成交均价、创建时间、最后更新时间、是否为开仓订单）
- [ ] T018 [P] [US1] 在spread/models.py中创建MakerWaitState数据类（当前等待的Maker订单、等待开始时间、价差保护触发次数、价格调整次数、连续重挂次数限制、部分成交累计数量、本次开仓成交记录、是否需要重新挂单）
- [ ] T019 [P] [US1] 在spread/models.py中创建HedgingState数据类（Extended成交数量、Extended成交价格、Lighter对冲订单ID、Lighter对冲数量、对冲开始时间、对冲超时时间）
- [ ] T020 [P] [US1] 在spread/models.py中创建SpreadConfig数据类（开仓阈值、平仓阈值、Maker挂单超时时间、价格监控间隔、价差监控间隔）
- [ ] T021 [P] [US1] 实现MakerOrderMonitor类 in spread/maker_order_monitor.py（监听订单状态变化、处理NEW/PARTIALLY_FILLED/FILLED/CANCELED事件）
- [ ] T022 [P] [US1] 实现PriceMonitor类 in spread/price_monitor.py（监控Extended订单簿BBO价格、计算实时价差、价差保护状态判断、价格偏离检测）
- [ ] T023 [US1] 在spread/trade_executor.py中实现Extended Maker挂单逻辑（OPENING和CLOSING状态下调用place_maker_order()）
- [ ] T024 [US1] 在spread/trade_executor.py中实现LIGHTER_HEDGING状态逻辑（Extended成交后执行Lighter对冲订单）
- [ ] T025 [US1] 在spread/spread_arb_bot.py中实现OPENING_MAKER_WAIT状态逻辑（三路并发监控：价差保护、价格位置优化、订单成交状态）
- [ ] T026 [US1] 在spread/spread_arb_bot.py中实现CLOSING_MAKER_WAIT状态逻辑（监控平仓条件、价格位置优化、订单成交状态）
- [ ] T027 [US1] 在spread/spread_arb_bot.py中实现价差保护机制（实时价差 < 0.09%时取消Extended挂单并回到IDLE状态）
- [ ] T028 [US1] 在spread/spread_arb_bot.py中实现价格位置优化机制（挂单价格不再最优时取消并重新挂单）
- [ ] T029 [US1] 在spread/spread_arb_bot.py中实现部分成交处理逻辑（对冲已成交部分，回到MAKER_WAIT继续等待剩余部分）
- [ ] T030 [US1] 在spread/spread_arb_bot.py中实现连续重挂次数限制（默认10次，超过后取消挂单并回到前序状态）
- [ ] T031 [US1] 在spread/spread_arb_bot.py中实现OPENING_WAIT状态验证失败回滚逻辑（识别较大仓位并回滚本次开仓数量，根据结果决定IDLE或HOLDING）
- [ ] T032 [US1] 在spread/spread_arb_bot.py中实现Lighter对冲失败处理逻辑（只强制平仓本次新开仓的Extended仓位，保留原有持仓，失败则进入PAUSED状态）
- [ ] T033 [US1] 在spread/spread_arb_bot.py中为所有新状态添加中文状态转换日志（使用统一日志函数，格式：`💥 {旧状态中文} -> {新状态中文} | {原因}`）
- [ ] T034 [US1] 在spread/spread_arb_bot.py中为OPENING_MAKER_WAIT状态添加监控日志（实时价差、价格位置、订单状态、价差保护触发、部分成交、重挂次数）
- [ ] T035 [US1] 在spread/spread_arb_bot.py中为CLOSING_MAKER_WAIT状态添加监控日志（平仓条件、价格位置、订单状态、部分成交、重挂次数）
- [ ] T036 [US1] 在spread/trade_executor.py中为LIGHTER_HEDGING状态添加执行日志（对冲订单发送、执行进度、成交结果、失败处理、部分成交对冲）
- [ ] T037 [US1] 修改spread/spread_arb_bot.py中的IDLE状态逻辑（从并发执行OPENING改为进入OPENING → OPENING_MAKER_WAIT → LIGHTER_HEDGING流程）
- [ ] T038 [US1] 修改spread/spread_arb_bot.py中的HOLDING状态逻辑（从并发执行CLOSING改为进入CLOSING → CLOSING_MAKER_WAIT → LIGHTER_HEDGING流程）
- [ ] T039 [US1] 更新logs/spread_arb_state.json持久化逻辑，保存MakerWaitState和HedgingState信息
- [ ] T040 [US1] 添加Extended Maker手续费统计（接近0%），在统计信息中体现手续费节省

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - 固定开仓/平仓价差阈值策略 (Priority: P2)

**Goal**: 将阶梯式等差数列策略改为固定阈值策略（开仓0.09%，平仓0.06%），简化策略逻辑

**Independent Test**: 可以通过回测历史数据验证固定阈值策略的效果，并与现有阶梯策略对比

### Tests for User Story 2

- [ ] T041 [P] [US2] 编写固定阈值策略单元测试 in tests/unit/test_fixed_threshold_strategy.py

### Implementation for User Story 2

- [ ] T042 [US2] 修改spread/arithmetic_open_strategy.py，将阶梯式开仓策略改为固定阈值策略（从配置项读取开仓阈值0.09%）
- [ ] T043 [US2] 修改spread/smart_close_strategy.py，确保使用固定平仓阈值（从配置项读取平仓阈值0.06%，计算公式：开仓价差 - 当前价差 - 手续费 > 阈值）
- [ ] T044 [US2] 移除或注释掉阶梯式等差数列策略相关代码（如果不再需要）
- [ ] T045 [US2] 在config.py中确保固定阈值配置项可调整（开仓阈值、平仓阈值）
- [ ] T046 [US2] 更新spread/spread_arb_bot.py中的开仓和平仓条件判断逻辑，使用固定阈值
- [ ] T047 [US2] 添加配置项变更日志（程序启动时输出当前使用的开仓阈值和平仓阈值）

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Extended挂单监控与价格动态调整 (Priority: P3)

**Goal**: 实现实时价差保护和价格位置优化，确保挂单在有利条件下成交

**Independent Test**: 可以模拟价差快速缩小的场景，验证系统是否在价差 < 0.09%时立即取消挂单并回到IDLE状态

### Tests for User Story 3

- [ ] T048 [P] [US3] 编写价差保护机制单元测试 in tests/unit/test_spread_protection.py
- [ ] T049 [P] [US3] 编写价格位置优化单元测试 in tests/unit/test_price_optimization.py
- [ ] T050 [P] [US3] 编写价差保护集成测试 in tests/integration/test_spread_protection_flow.py

### Implementation for User Story 3

**Note**: User Story 3的核心功能已经在User Story 1中实现（T027价差保护机制、T028价格位置优化机制、T034/T035监控日志）。本阶段主要是完善和优化。

- [ ] T051 [US3] 完善PriceMonitor类的价差监控频率配置（默认0.5秒，可配置）
- [ ] T052 [US3] 完善价差保护触发后的日志输出（在1秒内检测到价差变化并取消挂单，输出警告日志）
- [ ] T053 [US3] 优化价格位置检测算法（确保挂单价格保持最优位置，减少不必要的重挂）
- [ ] T054 [US3] 添加WebSocket连接中断处理（使用REST API备份查询订单状态，重连后恢复监控）
- [ ] T055 [US3] 添加订单取消失败重试机制（最多3次，失败后进入PAUSED状态）
- [ ] T056 [US3] 完善监控日志输出格式（确保价差使用百分比，数量保留3位小数，关键事件包含订单ID、价格、数量等上下文信息）

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 改进和优化多个用户故事相关的功能

- [ ] T057 [P] 更新README.md，说明Maker模式的使用方法和配置项
- [ ] T058 [P] 更新docs/01-opening-logic-analysis.md，添加Maker模式开仓和平仓逻辑文档
- [ ] T059 [P] 创建specs/017-ext-maker-mode/quickstart.md（启动步骤、监控日志示例、故障排查指南）
- [ ] T060 [P] 代码清理和重构（移除未使用的Taker模式代码，优化代码结构）
- [ ] T061 [P] 性能优化（确保状态转换延迟 < 100ms，监控循环处理时间 < 50ms）
- [ ] T062 运行所有单元测试和集成测试，确保测试通过率100%
- [ ] T063 运行回测框架，验证Maker模式相比Taker模式的收益率提升
- [ ] T064 添加配置项切换开关（支持快速切换回Taker模式作为备份）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - **User Story 1 (Phase 3)**: No dependencies on other stories - CORE MVP
  - **User Story 2 (Phase 4)**: Can start after US1 - May integrate with US1 but should be independently testable
  - **User Story 3 (Phase 5)**: Can start after US1 - Core functionality already in US1 (T027, T028, T034, T035), this phase is enhancement
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after US1 - Strategy modification only, should not break US1
- **User Story 3 (P3)**: Can start after US1 - Enhancement to monitoring logic already in US1

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD approach)
- Models before services (T017-T020 before T021-T022)
- Services before integration (T021-T022 before T023-T032)
- Core implementation before logging (T023-T032 before T033-T036)
- Story complete before moving to next priority

### Parallel Opportunities

**Phase 1 Setup**:
- T003 can run in parallel with T001, T002

**Phase 2 Foundational**:
- T006, T007, T008 can run in parallel (different files)
- T009, T010 can run in parallel (different files)

**Phase 3 User Story 1 Tests**:
- T011-T016 can all run in parallel (different test files)

**Phase 3 User Story 1 Models**:
- T017-T020 can run in parallel (different models in same file)

**Phase 3 User Story 1 Monitor Classes**:
- T021, T022 can run in parallel (different classes)

**Phase 4 User Story 2 Tests**:
- T041 can run in parallel with US3 tests (T048-T050)

**Phase 5 User Story 3 Tests**:
- T048-T050 can all run in parallel (different test files)

**Phase 6 Polish**:
- T057-T059, T061 can run in parallel (different files/tasks)

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "编写Extended Maker订单API单元测试 in tests/unit/test_extended_maker_mode.py"
Task: "编写状态机转换测试（新状态转换流程） in tests/unit/test_state_machine.py"
Task: "编写Maker订单监控器单元测试 in tests/unit/test_maker_order_monitor.py"
Task: "编写价格监控器单元测试 in tests/unit/test_price_monitor.py"
Task: "编写Maker开仓流程集成测试 in tests/integration/test_maker_opening_flow.py"
Task: "编写Maker平仓流程集成测试 in tests/integration/test_maker_closing_flow.py"

# Launch all models for User Story 1 together:
Task: "在spread/models.py中创建MakerOrder数据类"
Task: "在spread/models.py中创建MakerWaitState数据类"
Task: "在spread/models.py中创建HedgingState数据类"
Task: "在spread/models.py中创建SpreadConfig数据类"

# Launch monitor classes for User Story 1 together:
Task: "实现MakerOrderMonitor类 in spread/maker_order_monitor.py"
Task: "实现PriceMonitor类 in spread/price_monitor.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Test User Story 1 independently
5. Deploy/demo if ready - Extended使用Maker模式，手续费降低50%以上

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!) - Maker模式核心功能
3. Add User Story 2 → Test independently → Deploy/Demo - 固定阈值策略
4. Add User Story 3 → Test independently → Deploy/Demo - 完善监控和优化
5. Polish → Final deployment - 文档、性能优化、测试完善

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - **Developer A**: User Story 1 (Core Maker mode) - PRIORITY 1
   - **Developer B**: User Story 2 (Fixed threshold strategy) - Can start after US1 mostly complete
   - **Developer C**: User Story 3 (Monitoring enhancement) - Can start after US1 mostly complete
3. Stories complete and integrate independently

### Rollback Strategy

如果Maker模式测试失败：
- T064提供配置项切换开关，可以快速切换回Taker模式
- Phase 1中T002备份了现有Taker模式代码，可以恢复
- 状态机设计支持两种模式共存（通过配置开关）

---

## Notes

- **Total Tasks**: 64 tasks
- **Setup**: 3 tasks
- **Foundational**: 7 tasks (BLOCKS all user stories)
- **User Story 1**: 30 tasks (26 implementation + 6 tests) - CORE MVP
- **User Story 2**: 7 tasks (6 implementation + 1 test)
- **User Story 3**: 9 tasks (6 implementation + 3 tests)
- **Polish**: 8 tasks
- **Test Tasks**: 13 total (T011-T016, T041, T048-T050)
- **Implementation Tasks**: 51 total
- **[P] Parallel tasks**: 26 tasks can run in parallel (marked with [P])
- **Independent Test Criteria**: Each user story has clear independent test criteria
- **MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 1) = 40 tasks for MVP
- **Format Validation**: All tasks follow checklist format `- [ ] [TaskID] [P?] [Story?] Description with file path`
