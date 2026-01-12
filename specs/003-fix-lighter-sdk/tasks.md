# Tasks: 修复Lighter SDK初始化错误导致下单失败

**Input**: Design documents from `/specs/003-fix-lighter-sdk/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: 本功能包含测试任务，规格说明要求为每个修复编写单元测试

**Organization**: 任务按用户故事分组，以便独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（如 US1, US2, US3）
- 包含精确的文件路径

## Path Conventions

本功能是Python单项目，路径基于项目根目录：
- 交易所客户端: `exchanges/`
- 业务逻辑: `spread/`
- 测试: `tests/`, `tests/integration/`

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和测试环境准备

- [x] T001 验证Python 3.10+环境和依赖已安装
- [x] T002 [P] 创建测试文件结构 tests/test_lighter_sdk_health.py
- [x] T003 [P] 验证现有测试文件 tests/integration/test_lighter_order_fix_integration.py 存在

---

## Phase 2: Foundational (阻塞前置条件)

**目的**: 核心基础设施，必须在任何用户故事之前完成

**⚠️ CRITICAL**: 在此阶段完成之前不能开始用户故事工作

- [x] T004 检查当前Lighter SDK初始化流程并记录问题在 exchanges/lighter.py
- [x] T005 检查AttributeError错误堆栈并确定根本原因在 exchanges/lighter.py
- [x] T006 检查concurrent_executor.py中_place_order_lighter方法的错误处理

**Checkpoint**: 基础准备就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 修复SDK初始化验证 (优先级: P1) 🎯 MVP

**目标**: 确保SDK初始化时所有关键对象不为None，解决AttributeError导致下单失败的根本问题

**独立测试**: 触发一次套利机会，验证Extended和Lighter都成功返回订单ID，日志显示"双腿成交"而非"单腿持仓"

### Tests for User Story 1

> **NOTE: 先写这些测试，确保它们在实现之前失败**

- [x] T007 [P] [US1] 单元测试: 测试_validate_sdk_objects方法检测所有对象存在性在 tests/test_lighter_sdk_health.py
- [x] T008 [P] [US1] 单元测试: 测试_get_sdk_object_state方法获取对象状态快照在 tests/test_lighter_sdk_health.py
- [x] T009 [P] [US1] 单元测试: 测试SDK初始化失败时明确指出哪个对象为None在 tests/test_lighter_sdk_health.py
- [x] T010 [P] [US1] 集成测试: 测试SDK初始化成功后所有对象不为None在 tests/integration/test_lighter_order_fix_integration.py
- [x] T011 [P] [US1] 集成测试: 测试并发下单两个交易所都成功在 tests/integration/test_lighter_order_fix_integration.py

### Implementation for User Story 1

- [x] T012 [US1] 在LighterClient中添加_validate_sdk_objects方法，验证lighter_client、api_client、rest_client存在性在 exchanges/lighter.py
- [x] T013 [US1] 在LighterClient中添加_get_sdk_object_state方法，获取单个对象的状态快照在 exchanges/lighter.py
- [x] T014 [US1] 修改_initialize_lighter_client方法，在check_client后调用_validate_sdk_objects进行验证在 exchanges/lighter.py
- [x] T015 [US1] 增强初始化失败的错误消息，明确指出哪个对象为None在 exchanges/lighter.py
- [x] T016 [US1] 添加SDK对象状态日志记录，输出每个对象的类型和存在状态在 exchanges/lighter.py

**Checkpoint**: 此时，用户故事1应该完全功能正常且可独立测试

---

## Phase 4: User Story 2 - 增强诊断日志 (优先级: P2)

**目标**: 提供SDK对象状态快照，便于诊断问题，错误日志包含完整的SDK对象状态和异常堆栈

**独立测试**: 查看日志输出，确认所有关键的SDK对象状态都有记录

### Tests for User Story 2

- [x] T017 [P] [US2] 单元测试: 测试_log_sdk_state_snapshot方法记录完整对象状态在 tests/test_lighter_sdk_health.py
- [x] T018 [P] [US2] 单元测试: 测试AttributeError异常时记录SDK状态快照在 tests/test_lighter_sdk_health.py
- [x] T019 [P] [US2] 单元测试: 测试状态快照格式化输出清晰易读在 tests/test_lighter_sdk_health.py

### Implementation for User Story 2

- [x] T020 [US2] 在LighterClient中添加_log_sdk_state_snapshot方法，格式化输出对象状态在 exchanges/lighter.py
- [x] T021 [US2] 在_submit_order_with_retry方法中捕获异常时记录SDK状态快照在 exchanges/lighter.py
- [x] T022 [US2] 增强AttributeError异常处理，记录完整的对象状态和异常堆栈在 exchanges/lighter.py
- [x] T023 [US2] 在place_open_order和place_close_order中添加状态快照日志在 exchanges/lighter.py

**Checkpoint**: 此时，用户故事0和1都应该独立工作

---

## Phase 5: User Story 3 - 添加SDK健康检查机制 (优先级: P3)

**目标**: 在下单前检查SDK健康状态，避免下单时才发现SDK未初始化，提供防御性改进

**独立测试**: 在SDK未初始化时，健康检查应该返回失败状态

### Tests for User Story 3

- [x] T024 [P] [US3] 单元测试: 测试check_sdk_health方法返回正确的健康状态在 tests/test_lighter_sdk_health.py
- [x] T025 [P] [US3] 单元测试: 测试健康检查耗时<100ms在 tests/test_lighter_sdk_health.py
- [x] T026 [P] [US3] 单元测试: 测试健康检查失败时返回明确错误在 tests/test_lighter_sdk_health.py

### Implementation for User Story 3

- [x] T027 [US3] 在LighterClient中添加check_sdk_health方法，检查所有对象和API可用性在 exchanges/lighter.py
- [x] T028 [US3] 在concurrent_executor.py的_place_order_lighter方法中调用健康检查在 spread/concurrent_executor.py
- [x] T029 [US3] 健康检查失败时拒绝下单并记录详细错误在 spread/concurrent_executor.py
- [x] T030 [US3] 添加健康检查结果缓存，避免频繁检查影响性能在 exchanges/lighter.py

**Checkpoint**: 所有用户故事现在应该独立功能正常

---

## Phase 6: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [x] T031 [P] 运行所有测试并确保通过: pytest tests/test_lighter_sdk_health.py tests/integration/test_lighter_order_fix_integration.py -v
- [x] T032 [P] 验证quickstart.md中的所有验证步骤通过
- [x] T033 [P] 检查日志格式统一性：grep日志文件验证所有日志包含正确的SDK对象状态
- [x] T034 代码清理：移除调试日志，统一错误消息格式
- [x] T035 性能验证：确认SDK初始化时间<5秒，健康检查<100ms，并发下单延迟<5ms
- [x] T036 [P] 更新CLAUDE.md记录本次修复的技术栈更新

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-5)**: 都依赖Foundational阶段完成
  - US1 (P1) 是阻塞问题，必须首先完成
  - US2 (P2) 和 US3 (P3) 可以在US1完成后并行进行
- **Polish (Phase 6)**: 依赖所有需要的用户故事完成

### User Story Dependencies

- **User Story 1 (P1 - SDK初始化验证)**: 必须首先完成，阻塞性问题
- **User Story 2 (P2 - 诊断日志)**: 可在US1完成后开始，无其他依赖
- **User Story 3 (P3 - 健康检查)**: 可在US1完成后开始，无其他依赖

### Within Each User Story

- 测试必须在实现之前编写并FAIL
- 核心修复在日志增强之前
- 独立测试验证后才能进入下一故事

### Parallel Opportunities

- Setup阶段所有标记[P]的任务可以并行运行
- 测试阶段所有标记[P]的任务可以并行运行
- US2和US3可以在US1完成后并行进行
- Polish阶段所有标记[P]的任务可以并行运行

---

## Parallel Example: User Story 1 (SDK初始化验证)

```bash
# 并行启动User Story 1的所有测试:
Task: "单元测试: 测试_validate_sdk_objects方法检测所有对象存在性在 tests/test_lighter_sdk_health.py"
Task: "单元测试: 测试_get_sdk_object_state方法获取对象状态快照在 tests/test_lighter_sdk_health.py"
Task: "单元测试: 测试SDK初始化失败时明确指出哪个对象为None在 tests/test_lighter_sdk_health.py"
Task: "集成测试: 测试SDK初始化成功后所有对象不为None在 tests/integration/test_lighter_order_fix_integration.py"
Task: "集成测试: 测试并发下单两个交易所都成功在 tests/integration/test_lighter_order_fix_integration.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only - 强制)

1. 完成Phase 1: Setup
2. 完成Phase 2: Foundational (CRITICAL - 阻塞所有故事)
3. 完成Phase 3: User Story 1 (P0阻塞问题)
4. **STOP and VALIDATE**: 独立测试用户故事1
5. 验证Lighter下单成功率>=90%

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示 (解决阻塞问题!)
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 每个故事都增加价值且不破坏之前的修复

### Sequential Team Strategy (单开发者)

1. 完成Setup + Foundational
2. 按优先级顺序完成: US1 → US2 → US3
3. 每个故事完成后独立验证
4. 最后完成Polish阶段

---

## Task Summary

- **Total Tasks**: 36
- **Setup (Phase 1)**: 3 tasks
- **Foundational (Phase 2)**: 3 tasks
- **User Story 1 (P1)**: 10 tasks (5 tests + 5 implementation)
- **User Story 2 (P2)**: 7 tasks (3 tests + 4 implementation)
- **User Story 3 (P3)**: 7 tasks (3 tests + 4 implementation)
- **Polish (Phase 6)**: 6 tasks

### Parallel Opportunities

- **Setup阶段**: 2个并行任务 (T002, T003)
- **US1测试**: 5个并行任务 (T007, T008, T009, T010, T011)
- **US2测试**: 3个并行任务 (T017, T018, T019)
- **US2实现**: 2个并行任务 (T020, T022)
- **US3测试**: 3个并行任务 (T024, T025, T026)
- **Polish阶段**: 3个并行任务 (T031, T033, T036)

### Independent Test Criteria

- **US1**: 运行套利机器人，观察日志显示"双腿成交"，Lighter下单成功率>=90%
- **US2**: grep日志文件，错误日志包含完整的SDK对象状态快照
- **US3**: 健康检查耗时<100ms，检查失败时拒绝下单

### Suggested MVP Scope

**MVP = User Story 1 Only** (修复SDK初始化验证)

理由：
- US1是P0阻塞问题，必须首先解决
- 解决后套利程序才能正常运行
- US2和US3是优化，可以在后续迭代中完成

MVP完成后系统应该能够：
- Extended和Lighter并发下单都成功
- Lighter下单成功率>=90%
- 单腿持仓率从100%降低到<10%

---

## Notes

- [P]任务 = 不同文件，无依赖
- [Story]标签将任务映射到特定用户故事以便追溯
- 每个用户故事应该可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止独立验证故事
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖
