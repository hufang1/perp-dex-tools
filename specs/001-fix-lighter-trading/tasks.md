# Tasks: 修复Lighter交易所下单失败和日志混乱问题

**Input**: Design documents from `/specs/001-fix-lighter-trading/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: 本功能包含测试任务，规格说明要求为每个修复编写单元测试

**Organization**: 任务按用户故事分组，以便独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（如 US0, US1, US2）
- 包含精确的文件路径

## Path Conventions

本功能是Python单项目，路径基于项目根目录：
- 交易所客户端: `exchanges/`
- 日志模块: `helpers/`
- 业务逻辑: `spread/`
- 测试: `tests/`, `tests/integration/`

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和测试环境准备

- [x] T001 验证Python 3.11+环境和依赖已安装
- [x] T002 [P] 创建测试目录结构 tests/test_lighter_client_fix.py
- [x] T003 [P] 创建测试目录结构 tests/test_logger_identifiers.py
- [x] T004 [P] 创建测试目录结构 tests/integration/test_lighter_order_fix_integration.py

---

## Phase 2: Foundational (阻塞前置条件)

**目的**: 核心基础设施，必须在任何用户故事之前完成

**⚠️ CRITICAL**: 在此阶段完成之前不能开始用户故事工作

- [x] T005 检查当前日志格式并记录现有问题在 helpers/logger.py
- [x] T006 检查Lighter SDK初始化流程并记录问题在 exchanges/lighter.py
- [x] T007 检查紧急平仓实现并记录问题在 spread/concurrent_executor.py

**Checkpoint**: 基础准备就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 0 - 修复Lighter交易所下单失败 (优先级: P0 - 阻塞问题) 🎯 MVP

**目标**: 修复Lighter SDK初始化问题，解决`AttributeError: 'NoneType' object has no attribute 'code'`错误，使Lighter下单成功率从0%提升到90%以上

**独立测试**: 触发一次套利机会，验证Extended和Lighter都成功返回订单ID，日志显示"双腿成交"而非"单腿持仓"

### Tests for User Story 0

> **NOTE: 先写这些测试，确保它们在实现之前失败**

- [x] T008 [P] [US0] 单元测试: 测试代理配置正确应用在 tests/test_lighter_client_fix.py
- [x] T009 [P] [US0] 单元测试: 测试SDK初始化成功（check_client返回None）在 tests/test_lighter_client_fix.py
- [x] T010 [P] [US0] 单元测试: 测试AttributeError异常捕获和记录在 tests/test_lighter_client_fix.py
- [x] T011 [P] [US0] 集成测试: 测试并发下单两个交易所都成功在 tests/integration/test_lighter_order_fix_integration.py
- [x] T012 [P] [US0] 集成测试: 测试单腿持仓检测和紧急平仓在 tests/integration/test_lighter_order_fix_integration.py

### Implementation for User Story 0

- [x] T013 [US0] 修复_initialize_lighter_client方法中的代理配置逻辑在 exchanges/lighter.py
- [x] T014 [US0] 添加rest_client.proxy设置的健壮性检查和延迟重试在 exchanges/lighter.py
- [x] T015 [US0] 增强place_open_order中的错误捕获，记录完整SDK异常堆栈在 exchanges/lighter.py
- [x] T016 [US0] 验证check_client()返回None表示成功并添加日志记录在 exchanges/lighter.py
- [x] T017 [US0] 添加代理连接失败的fallback处理（可选：记录警告并继续）在 exchanges/lighter.py

**Checkpoint**: 此时，用户故事0应该完全功能正常且可独立测试

---

## Phase 4: User Story 1 - 统一日志标识清晰区分交易所 (优先级: P1)

**目标**: 增强TradingLogger，确保所有日志包含`[EXTENDED]`或`[LIGHTER]`标识，用户能在30秒内识别问题交易所

**独立测试**: 运行程序并检查日志输出，所有Extended日志包含`[EXTENDED]`，所有Lighter日志包含`[LIGHTER]`

### Tests for User Story 1

- [ ] T018 [P] [US1] 单元测试: 测试日志标识格式为`[EXTENDED] [ETH] message`在 tests/test_logger_identifiers.py
- [ ] T019 [P] [US1] 单元测试: 测试错误日志包含交易所标识和异常类型在 tests/test_logger_identifiers.py
- [ ] T020 [P] [US1] 单元测试: 测试日志可以正确过滤（grep `[EXTENDED]`）在 tests/test_logger_identifiers.py

### Implementation for User Story 1

- [ ] T021 [P] [US1] 修改TradingLogger.log()方法使用新格式`[EXTENDED] [ETH] message`在 helpers/logger.py
- [ ] T022 [P] [US1] 为错误日志添加特殊标识格式`[EXTENDED] ERROR: [类型] 消息`在 helpers/logger.py
- [ ] T023 [US1] 更新spread/concurrent_executor.py中的日志使用新标识格式在 spread/concurrent_executor.py
- [ ] T024 [US1] 更新spread/bot.py中的日志使用新标识格式在 spread/bot.py
- [ ] T025 [US1] 验证exchanges/extended.py和exchanges/lighter.py中所有日志通过TradingLogger

**Checkpoint**: 此时，用户故事0和1都应该独立工作

---

## Phase 5: User Story 2 - 紧急平仓统一使用Taker订单 (优先级: P1)

**目标**: 修改紧急平仓流程，强制使用taker订单（post_only=False）确保立即成交

**独立测试**: 模拟单腿持仓场景，验证紧急平仓订单使用taker模式立即成交

### Tests for User Story 2

- [ ] T026 [P] [US2] 单元测试: 测试紧急平仓使用taker订单在 tests/test_emergency_close_taker.py
- [ ] T027 [P] [US2] 单元测试: 测试_place_order_extended识别CLOSE类型并强制post_only=False在 tests/test_emergency_close_taker.py
- [ ] T028 [P] [US2] 单元测试: 测试_place_order_lighter识别CLOSE类型并强制post_only=False在 tests/test_emergency_close_taker.py
- [ ] T029 [P] [US2] 集成测试: 测试紧急平仓日志明确显示使用taker订单在 tests/integration/test_lighter_order_fix_integration.py

### Implementation for User Story 2

- [ ] T030 [US2] 修改_place_order_extended方法，检测order_type='CLOSE'时强制post_only=False在 spread/concurrent_executor.py
- [ ] T031 [US2] 修改_place_order_lighter方法，检测order_type='CLOSE'时强制post_only=False在 spread/concurrent_executor.py
- [ ] T032 [US2] 更新emergency_close_position方法，添加taker订单日志记录在 spread/concurrent_executor.py
- [ ] T033 [US2] 验证所有平仓操作（包括非紧急）都传递正确的order_type='CLOSE'参数

**Checkpoint**: 所有用户故事现在应该独立功能正常

---

## Phase 6: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [x] T034 [P] 运行所有测试并确保通过: pytest tests/test_lighter_client_fix.py tests/test_logger_identifiers.py tests/integration/test_lighter_order_fix_integration.py -v
- [x] T035 [P] 验证quickstart.md中的所有验证步骤通过
- [x] T036 [P] 检查日志格式统一性：grep日志文件验证所有日志包含正确的交易所标识
- [x] T037 代码清理：移除调试日志，统一错误消息格式
- [x] T038 性能验证：确认并发下单延迟<5ms，订单响应时间<500ms
- [x] T039 [P] 更新CLAUDE.md记录本次修复的技术栈更新

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-5)**: 都依赖Foundational阶段完成
  - US0 (P0) 是阻塞问题，必须首先完成
  - US1 (P1) 和 US2 (P1) 可以在US0完成后并行进行
- **Polish (Phase 6)**: 依赖所有需要的用户故事完成

### User Story Dependencies

- **User Story 0 (P0 - Lighter下单修复)**: 必须首先完成，阻塞性问题
- **User Story 1 (P1 - 日志标识)**: 可在US0完成后开始，无其他依赖
- **User Story 2 (P1 - 紧急平仓)**: 可在US0完成后开始，无其他依赖

### Within Each User Story

- 测试必须在实现之前编写并FAIL
- 核心修复在日志增强之前
- 独立测试验证后才能进入下一故事

### Parallel Opportunities

- Setup阶段所有标记[P]的任务可以并行运行
- 测试阶段所有标记[P]的任务可以并行运行
- US1和US2可以在US0完成后并行进行
- Polish阶段所有标记[P]的任务可以并行运行

---

## Parallel Example: User Story 1 (日志标识)

```bash
# 并行启动User Story 1的所有测试:
Task: "测试日志标识格式为`[EXTENDED] [ETH] message`在 tests/test_logger_identifiers.py"
Task: "测试错误日志包含交易所标识和异常类型在 tests/test_logger_identifiers.py"
Task: "测试日志可以正确过滤（grep `[EXTENDED]`）在 tests/test_logger_identifiers.py"
```

---

## Implementation Strategy

### MVP First (User Story 0 Only - 强制)

1. 完成Phase 1: Setup
2. 完成Phase 2: Foundational (CRITICAL - 阻塞所有故事)
3. 完成Phase 3: User Story 0 (P0阻塞问题)
4. **STOP and VALIDATE**: 独立测试用户故事0
5. 验证Lighter下单成功率>=90%

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 0 → 独立测试 → 部署/演示 (解决阻塞问题!)
3. 添加 User Story 1 → 独立测试 → 部署/演示
4. 添加 User Story 2 → 独立测试 → 部署/演示
5. 每个故事都增加价值且不破坏之前的修复

### Sequential Team Strategy (单开发者)

1. 完成Setup + Foundational
2. 按优先级顺序完成: US0 → US1 → US2
3. 每个故事完成后独立验证
4. 最后完成Polish阶段

---

## Task Summary

- **Total Tasks**: 39
- **Setup (Phase 1)**: 4 tasks
- **Foundational (Phase 2)**: 3 tasks
- **User Story 0 (P0)**: 10 tasks (5 tests + 5 implementation)
- **User Story 1 (P1)**: 8 tasks (3 tests + 5 implementation)
- **User Story 2 (P1)**: 8 tasks (4 tests + 4 implementation)
- **Polish (Phase 6)**: 6 tasks

### Parallel Opportunities

- **Setup阶段**: 3个并行任务 (T002, T003, T004)
- **US0测试**: 5个并行任务 (T008, T009, T010, T011, T012)
- **US1测试**: 3个并行任务 (T018, T019, T020)
- **US1实现**: 2个并行任务 (T021, T022)
- **US2测试**: 4个并行任务 (T026, T027, T028, T029)
- **Polish阶段**: 3个并行任务 (T034, T036, T039)

### Independent Test Criteria

- **US0**: 运行套利机器人，观察日志显示"双腿成交"，Lighter下单成功率>=90%
- **US1**: grep日志文件，所有Extended日志包含`[EXTENDED]`，所有Lighter日志包含`[LIGHTER]`
- **US2**: 触发紧急平仓，日志显示使用taker订单，订单立即成交

### Suggested MVP Scope

**MVP = User Story 0 Only** (修复Lighter下单失败)

理由：
- US0是P0阻塞问题，必须首先解决
- 解决后套利程序才能正常运行
- US1和US2是优化，可以在后续迭代中完成

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
