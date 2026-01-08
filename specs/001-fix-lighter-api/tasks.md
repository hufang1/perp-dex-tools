# Tasks: 修复Lighter API调用失败和持仓不平衡问题

**Input**: Design documents from `/specs/001-fix-lighter-api/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md

**Tests**: 本项目不强制TDD，但建议添加单元测试验证修复

**Organization**: 任务按用户故事分组，确保每个故事可以独立实施和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属用户故事（US1, US2, US3）
- 描述中包含精确文件路径

## Path Conventions

本项目使用单项目结构：
- 源代码在项目根目录的 `exchanges/`, `spread/`, `tests/` 目录

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和环境准备

注意：大多数Setup任务已完成（配置文件已更新）。本阶段仅包含剩余任务。

- [x] T001 验证Lighter SDK版本兼容性（检查`account_inactive_orders`方法可用性）
- [x] T002 [P] 备份当前版本代码到备份分支（以防回滚需要）

---

## Phase 2: Foundational (阻塞性前置条件)

**Purpose**: 所有用户故事依赖的核心基础设施

**⚠️ CRITICAL**: 在此阶段完成前，不能开始任何用户故事的实施

### 配置基础（已在之前会话完成）

- [x] T003 在`spread/config.py`中添加持仓对账配置参数（`max_unhedged_positions`, `auto_close_unhedged`, `unhedged_position_timeout`）
- [x] T004 在`spread/config.py`中添加对冲失败监控配置（`hedge_failure_threshold`, `hedge_failure_window`）
- [x] T005 在`spread/config.py`中添加对账功能配置（`enable_reconciliation`, `reconciliation_interval`）

### 对冲管理器改进（已在之前会话完成）

- [x] T006 改进`spread/hedge_manager.py`中的订单等待逻辑（轮询等待最多5秒）

### 日志和错误处理基础

- [x] T007 在`exchanges/lighter.py`的`get_order_info()`方法中添加详细的DEBUG日志（记录回退路径，已在代码中实现）
- [x] T008 添加API错误记录结构（用于追踪API调用失败，通过现有日志系统实现）

**Checkpoint**: 基础设施就绪 - 用户故事实施现在可以并行开始

---

## Phase 3: User Story 1 - 修复Lighter API订单查询失败 (Priority: P1) 🎯 MVP

**Goal**: 修复导致所有对冲操作失败的API错误

**Independent Test**: 运行套利机器人并验证：
1. 不再出现`'OrderApi' object has no attribute 'account_active_orders'`错误
2. Lighter订单查询返回正确的OrderInfo对象
3. 对冲操作能够成功完成

### 实施User Story 1

- [x] T009 [US1] 修复`exchanges/lighter.py:479`中的API方法名（将`account_active_orders`改为`account_inactive_orders`）
- [x] T010 [US1] 在`exchanges/lighter.py:get_order_info()`中验证`order_id`参数不为空（已在代码中实现）
- [x] T011 [US1] 改进`exchanges/lighter.py:get_order_info()`的回退机制（WebSocket → REST API → 持仓推断，已实现）
- [x] T012 [US1] 添加详细的错误日志到`exchanges/lighter.py:get_order_info()`（记录方法名、参数、错误类型，已实现）
- [x] T013 [US1] 验证修复后的`get_order_info()`在所有回退路径下都能正常工作（代码审查通过）

### 验证User Story 1

- [x] T014 [US1] 创建单元测试`tests/test_lighter_api_fix.py`（Mock API响应，验证修复后的代码路径）
- [x] T015 [US1] 运行单元测试验证（所有6个测试通过，验证修复后的代码路径）
- [x] T016 [US1] 执行quickstart.md中的"快速修复"步骤并验证结果（已验证API方法名修复）

**Checkpoint**: 此时User Story 1应该完全功能正常且可独立测试

---

## Phase 4: User Story 2 - 实施持仓对账机制 (Priority: P2)

**Goal**: 每60秒检查两端持仓是否平衡，超过20%差异时触发警告

**Independent Test**: 模拟持仓不平衡场景并验证：
1. 对账循环每60秒执行一次
2. 当差异超过20%时记录ERROR日志
3. 当差异<20%时记录INFO日志
4. 日志包含所有必要信息（价值、数量、净暴露、差异百分比）

### 实施User Story 2

- [ ] T017 [P] [US2] 在`spread/bot.py`的`__init__`方法中添加`hedge_attempts`列表（用于记录对冲尝试）
- [ ] T018 [P] [US2] 在`spread/bot.py`中实现`_get_extended_position_value()`方法（获取Extended持仓价值）
- [ ] T019 [P] [US2] 在`spread/bot.py`中实现`_get_lighter_position_value()`方法（获取Lighter持仓价值）
- [ ] T020 [P] [US2] 在`spread/bot.py`中实现`_get_current_price()`辅助方法（获取当前市场价格）
- [ ] T021 [US2] 在`spread/bot.py`中实现`_record_hedge_attempt()`方法（记录对冲尝试结果）
- [ ] T022 [US2] 在`spread/bot.py`中实现`_check_hedge_failure_rate()`方法（检查对冲失败率）
- [ ] T023 [US2] 在`spread/bot.py`中实现`_reconciliation_loop()`方法（持仓对账循环，每60秒执行）
- [ ] T024 [US2] 在`spread/bot.py:run()`方法中添加对账任务到任务列表（`asyncio.create_task(self._reconciliation_loop())`）
- [ ] T025 [US2] 在对账循环中添加超时检测逻辑（检测`unhedged_positions`中超过300秒的持仓）
- [ ] T026 [US2] 在`spread/bot.py:_stats_reporter()`中添加对冲失败率显示（当`hedge_attempts`>=5时）

### 验证User Story 2

- [ ] T027 [US2] 创建单元测试`tests/test_position_reconciliation.py`（Mock持仓数据，验证对账逻辑）
- [ ] T028 [US2] 手动测试：运行机器人并观察对账日志输出
- [ ] T029 [US2] 验证不平衡阈值检测（模拟>20%差异，确认ERROR日志触发）

**Checkpoint**: 此时User Stories 1和2都应该独立工作

---

## Phase 5: User Story 3 - 自动平仓不平衡持仓 (Priority: P3)

**Goal**: 当检测到严重不平衡时，提供自动平仓选项或清晰的平仓指引

**Independent Test**: 启用`auto_close_unhedged`配置并验证：
1. 当不平衡超过阈值时，如果启用自动平仓，系统自动执行平仓
2. 如果未启用，系统提供清晰的平仓建议（方向、数量）
3. 自动平仓失败时记录错误并保持熔断状态

### 实施User Story 3

- [ ] T030 [P] [US3] 在`spread/bot.py:_reconciliation_loop()`中实现不平衡检测逻辑（计算`imbalance_ratio`）
- [ ] T031 [P] [US3] 在`spread/bot.py:_reconciliation_loop()`中实现平仓建议计算（确定需要平仓的数量和方向）
- [ ] T032 [US3] 在`spread/bot.py:_reconciliation_loop()`中添加自动平仓逻辑（检查`auto_close_unhedged`配置）
- [ ] T033 [US3] 在自动平仓失败时添加错误处理和熔断保持逻辑
- [ ] T034 [US3] 在对账日志中添加平仓建议输出（格式：`"建议平仓: Lighter空头 0.03 ETH"`）

### 验证User Story 3

- [ ] T035 [US3] 创建单元测试`tests/test_auto_close_unbalanced.py`（测试自动平仓逻辑和错误处理）
- [ ] T036 [US3] 手动测试：设置`auto_close_unhedged=False`，验证平仓建议输出
- [ ] T037 [US3] 手动测试：设置`auto_close_unhedged=True`（谨慎！），验证自动平仓执行

**Checkpoint**: 所有用户故事现在都应该独立功能正常

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 影响多个用户故事的改进和收尾工作

- [ ] T038 [P] 更新`CLAUDE.md`文档（记录新功能和配置项）
- [ ] T039 [P] 代码清理：移除调试日志，优化日志级别
- [ ] T040 性能优化：验证对账循环不影响主交易循环性能
- [ ] T041 [P] 安全加固：添加配置参数验证（确保阈值、间隔等在合理范围）
- [ ] T042 运行quickstart.md验证清单（确认所有修复步骤正确）
- [ ] T043 部署前验证：检查生产环境Lighter SDK版本
- [ ] T044 创建部署回滚计划（如果新版本出现问题）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可以立即开始
- **Foundational (Phase 2)**: 部分任务已完成（T003-T006），剩余任务(T007-T008)应优先完成 - 阻塞所有用户故事
- **User Stories (Phase 3-5)**: 都依赖Foundational阶段完成
  - 用户故事可以并行进行（如果有足够人力）
  - 或按优先级顺序执行（P1 → P2 → P3）
- **Polish (Phase 6)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P2)**: Foundational完成后可开始 - 可与US1集成但应独立测试
- **User Story 3 (P3)**: Foundational完成后可开始 - 依赖US2的对账逻辑（需要`_reconciliation_loop()`存在）

### Within Each User Story

- User Story 1: 按顺序执行（T009 → T013 → T014-T016）
- User Story 2: T017-T020可并行，T021-T026顺序执行
- User Story 3: T030-T031可并行，T032-T034顺序执行

### Parallel Opportunities

- T001-T002（Setup阶段）可并行
- T017-T020（US2的辅助方法）可并行
- T030-T031（US3的计算逻辑）可并行
- T038-T039, T041（Polish阶段）可并行

---

## Parallel Example: User Story 2

```bash
# 可并行的任务（不同的文件）:
Task: "在spread/bot.py的__init__中添加hedge_attempts列表"
Task: "在spread/bot.py中实现_get_extended_position_value()方法"
Task: "在spread/bot.py中实现_get_lighter_position_value()方法"
Task: "在spread/bot.py中实现_get_current_price()辅助方法"

# 注意：虽然这些任务都在同一文件中，但它们是独立的方法，
# 可以由AI同时处理并在一次编辑中完成
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成 Phase 3: User Story 1
4. **STOP and VALIDATE**: 独立测试User Story 1
5. 如果验证通过，部署/演示MVP

**MVP价值**: 修复导致所有对冲失败的关键API错误，恢复系统基本功能

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（MVP - 修复API错误！）
3. 添加 User Story 2 → 独立测试 → 部署/演示（添加持仓监控）
4. 添加 User Story 3 → 独立测试 → 部署/演示（添加自动平仓）
5. 每个故事都在不破坏前一故事的情况下增加价值

### Sequential Team Strategy

单人开发（推荐）:

1. 完成 Setup + Foundational
2. 按顺序完成 US1 → US2 → US3
3. 每完成一个故事就测试验证
4. Story之间暂停评估，确保质量

---

## Notes

- [P] 任务 = 不同文件或独立方法，无依赖冲突
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应该可以独立完成和测试
- 建议在每个任务或逻辑组完成后提交代码
- 在任何checkpoint停止以独立验证故事
- 避免：模糊任务、同一文件冲突、破坏独立性的跨故事依赖

---

## Task Summary

- **Total Tasks**: 44
- **Setup Phase**: 2 tasks (T001-T002)
- **Foundational Phase**: 6 tasks (T003-T008), 其中3个已完成(T003-T005)
- **User Story 1 (P1)**: 8 tasks (T009-T016) 🎯 **MVP核心**
- **User Story 2 (P2)**: 13 tasks (T017-T029)
- **User Story 3 (P3)**: 8 tasks (T030-T037)
- **Polish Phase**: 7 tasks (T038-T044)

**Parallel Opportunities**: 11个任务标记为[P]，可并行执行

**Suggested MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 1)
- 完成这些后即可部署，修复最关键的API错误
- User Stories 2和3可以在后续迭代中添加

---

## Format Validation

✅ **所有任务遵循checklist格式**:
- ✅ 每个任务以`- [ ]`开头
- ✅ 每个任务有唯一ID（T001-T044）
- ✅ 可并行任务标记为[P]
- ✅ User Story阶段任务标记为[US1], [US2], [US3]
- ✅ 所有描述包含精确文件路径
- ✅ Setup和Foundational阶段无Story标签
- ✅ Polish阶段无Story标签
