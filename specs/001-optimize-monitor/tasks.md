# Tasks: 优化持仓监控输出

**Input**: Design documents from `/specs/001-optimize-monitor/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/output-format.md

**Tests**: 本功能包含测试任务，需要单元测试和集成测试验证功能正确性。

**Organization**: 任务按用户故事组织，每个故事可以独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可以并行执行（不同文件，无依赖关系）
- **[Story]**: 此任务属于哪个用户故事（如 US1, US2, US3）
- **包含精确的文件路径**

## Path Conventions

- **单项目**: `spread/`, `tests/` 在仓库根目录
- 路径基于 plan.md 中的项目结构

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基本结构准备

- [x] T001 创建测试目录结构 tests/unit/ 和 tests/integration/
- [x] T002 验证开发环境依赖（pytest, Python 3.11+）

---

## Phase 2: Foundational (阻塞性前置任务)

**目的**: 所有用户故事依赖的核心基础设施

**⚠️ 关键**: 此阶段完成前，不能开始任何用户故事的实现

- [x] T003 在 spread/spread_pair.py 中添加 calculate_realized_pnl() 方法框架（空实现）
- [x] T004 在 spread/bot.py 中创建 _log_all_positions() 方法框架（空实现）

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 整合持仓监控输出 (Priority: P1) 🎯 MVP

**目标**: 将所有持仓监控信息整合到单个日志输出中

**独立测试**: 启动机器人并开多个持仓，验证日志输出为单个整合消息块

### Tests for User Story 1

> **注意: 先编写这些测试，确保它们在实现前失败**

- [x] T005 [P] [US1] 创建测试文件 tests/unit/test_monitor_output.py
- [x] T006 [P] [US1] 创建测试文件 tests/integration/test_monitor_integration.py
- [x] T007 [US1] 编写测试用例: 空持仓列表应输出"无活跃持仓" in tests/unit/test_monitor_output.py
- [x] T008 [US1] 编写测试用例: 单个持仓应输出正确格式 in tests/unit/test_monitor_output.py
- [x] T009 [US1] 编写测试用例: 多个持仓应输出为单个日志块 in tests/unit/test_monitor_output.py
- [x] T010 [US1] 编写测试用例: 持仓之间应有正确分隔符 in tests/unit/test_monitor_output.py
- [x] T011 [US1] 编写集成测试: 完整监控循环测试 in tests/integration/test_monitor_integration.py

### Implementation for User Story 1

- [x] T012 [US1] 实现 SpreadPair.calculate_realized_pnl() 方法在 spread/spread_pair.py（做多/做空逻辑）
- [x] T013 [US1] 实现 SpreadArbitrageBot._log_all_positions() 方法在 spread/bot.py（批量遍历持仓）
- [x] T014 [US1] 实现订单簿价格获取逻辑在 spread/bot.py（获取 bid/ask）
- [x] T015 [US1] 实现持仓信息格式化逻辑在 spread/bot.py（多行字符串构建）
- [x] T016 [US1] 实现单个持仓摘要构建逻辑在 spread/bot.py（PositionSummary 数据结构）
- [x] T017 [US1] 实现多个持仓分隔符逻辑在 spread/bot.py（使用 ━━━ 字符）
- [x] T018 [US1] 实现空持仓列表处理在 spread/bot.py（显示"无活跃持仓"）
- [x] T019 [US1] 在 spread/bot.py 的 _monitor_pairs() 循环中替换 _log_position_status() 为 _log_all_positions()
- [x] T020 [US1] 添加异常处理: 单个持仓计算失败不应中断整个输出在 spread/bot.py
- [x] T021 [US1] 运行单元测试并确保所有测试通过 pytest tests/unit/test_monitor_output.py -v
- [x] T022 [US1] 运行集成测试并确保通过 pytest tests/integration/test_monitor_integration.py -v

**检查点**: 此时用户故事1应完整功能且可独立测试

---

## Phase 4: User Story 2 - 新增当前已实现收益字段 (Priority: P2)

**目标**: 在监控输出中显示使用对手价立即平仓的理论收益

**独立测试**: 对比监控输出中的"当前已实现收益"与手动计算结果（Extended平仓收益 + Lighter平仓收益）

### Tests for User Story 2

- [x] T023 [P] [US2] 编写测试用例: 做多持仓已实现收益计算 in tests/unit/test_monitor_output.py
- [x] T024 [P] [US2] 编写测试用例: 做空持仓已实现收益计算 in tests/unit/test_monitor_output.py
- [x] T025 [P] [US2] 编写测试用例: 价格为None时应显示N/A in tests/unit/test_monitor_output.py
- [x] T026 [US2] 编写测试用例: 已实现收益精度验证（误差<0.01%） in tests/unit/test_monitor_output.py

### Implementation for User Story 2

- [x] T027 [US2] 完善 SpreadPair.calculate_realized_pnl() 实现在 spread/spread_pair.py（完整计算逻辑）
- [x] T028 [US2] 实现做多持仓已实现收益计算在 spread/spread_pair.py（bid平仓Extended，ask平仓Lighter）
- [x] T029 [US2] 实现做空持仓已实现收益计算在 spread/spread_pair.py（ask平仓Extended，bid平仓Lighter）
- [x] T030 [US2] 实现价格为None时的处理在 spread/spread_pair.py（返回None）
- [x] T031 [US2] 实现已实现收益格式化在 spread/bot.py（添加到输出中，2位小数）
- [x] T032 [US2] 实现价格缺失时的N/A显示在 spread/bot.py
- [x] T033 [US2] 运行测试并确保通过 pytest tests/unit/test_monitor_output.py::test_realized_pnl -v

**检查点**: 此时用户故事1和2都应独立工作

---

## Phase 5: User Story 3 - 优化字段显示 (Priority: P3)

**目标**: 监控输出字段清晰简洁，去除冗余信息，突出关键数据

**独立测试**: 审查输出格式，确保字段简洁明了

### Tests for User Story 3

- [x] T034 [P] [US3] 编写测试用例: 验证输出格式符合contracts/output-format.md规范 in tests/unit/test_monitor_output.py
- [x] T035 [P] [US3] 编写测试用例: 数字格式验证（时间整数、价格2位小数、数量4位小数） in tests/unit/test_monitor_output.py

### Implementation for User Story 3

- [x] T036 [US3] 实现总持仓摘要行在 spread/bot.py（总持仓数、总未实现盈亏）
- [x] T037 [US3] 实现数字格式化在 spread/bot.py（时间:.0f，价格:.2f，数量:.4f）
- [x] T038 [US3] 实现持仓平仓中标记显示在 spread/bot.py（[平仓中]标记）
- [x] T039 [US3] 优化缩进和对齐在 spread/bot.py（3空格缩进）
- [x] T040 [US3] 添加订单簿数据缺失警告在 spread/bot.py（⚠️ 标记）
- [x] T041 [US3] 运行所有测试并确保通过 pytest tests/unit/test_monitor_output.py -v

**检查点**: 所有用户故事现在都应独立功能

---

## Phase 6: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [x] T042 [P] 代码审查和重构在 spread/bot.py 和 spread/spread_pair.py
- [x] T043 [P] 添加docstring文档在新增的方法中
- [x] T044 运行完整测试套件 pytest tests/ -v
- [x] T045 验证quickstart.md中的示例（手动测试）
- [x] T046 性能验证: 20个持仓日志输出应<50ms
- [x] T047 验证不影响交易逻辑（监控循环不应阻塞）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可以立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3+)**: 都依赖Foundational阶段完成
  - 用户故事可以并行进行（如果有人力）
  - 或按优先级顺序执行（P1 → P2 → P3）
- **Polish (Phase 6)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P2)**: Foundational完成后可开始 - 依赖US1的_log_all_positions方法，但可独立测试
- **User Story 3 (P3)**: Foundational完成后可开始 - 依赖US1和US2的输出格式，但可独立测试

### Within Each User Story

- 测试必须先编写并在实现前失败
- 核心实现（calculate_realized_pnl）在格式化之前
- 格式化在集成之前
- 故事完成后才能进入下一优先级

### Parallel Opportunities

- Setup阶段所有[P]任务可以并行
- Foundational阶段T003和T004可以并行（不同文件）
- 每个用户故事中所有标记[P]的测试可以并行编写
- 不同用户故事可以由不同团队成员并行工作

---

## Parallel Example: User Story 1

```bash
# 一起启动User Story 1的所有测试:
Task: "T005 [P] [US1] 创建测试文件 tests/unit/test_monitor_output.py"
Task: "T006 [P] [US1] 创建测试文件 tests/integration/test_monitor_integration.py"
Task: "T007 [US1] 编写测试用例: 空持仓列表应输出'无活跃持仓'"
Task: "T008 [US1] 编写测试用例: 单个持仓应输出正确格式"
Task: "T009 [US1] 编写测试用例: 多个持仓应输出为单个日志块"
```

---

## Parallel Example: User Story 2

```bash
# 一起启动User Story 2的所有测试:
Task: "T023 [P] [US2] 编写测试用例: 做多持仓已实现收益计算"
Task: "T024 [P] [US2] 编写测试用例: 做空持仓已实现收益计算"
Task: "T025 [P] [US2] 编写测试用例: 价格为None时应显示N/A"
Task: "T026 [P] [US2] 编写测试用例: 已实现收益精度验证"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成 Phase 3: User Story 1
4. **停止并验证**: 独立测试User Story 1
5. 如果准备就绪，部署/演示

**MVP交付物**: 整合的持仓监控输出（无已实现收益字段）

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（MVP!）
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 每个故事都在不破坏前一个故事的情况下增加价值

### Parallel Team Strategy

有多个开发者时:

1. 团队一起完成 Setup + Foundational
2. Foundational完成后:
   - 开发者A: User Story 1（T005-T022）
   - 开发者B: User Story 2（T023-T033）
   - 开发者C: User Story 3（T034-T041）
3. 故事独立完成并集成

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

## Task Summary

- **总任务数**: 47
- **Setup任务**: 2
- **Foundational任务**: 2
- **User Story 1任务**: 18（7个测试，11个实现）
- **User Story 2任务**: 11（4个测试，7个实现）
- **User Story 3任务**: 8（2个测试，6个实现）
- **Polish任务**: 6

### Parallel Opportunities

- **Foundational**: 2个任务可并行（T003, T004）
- **US1 Tests**: 2个文件创建可并行（T005, T006）
- **US2 Tests**: 4个测试用例可并行（T023-T026）
- **US3 Tests**: 2个测试用例可并行（T034, T035）
- **Polish**: 2个代码审查任务可并行（T042, T043）

### Independent Test Criteria

- **US1**: 启动机器人，开3个持仓，验证单条日志包含所有持仓
- **US2**: 手动计算已实现收益，验证与输出匹配
- **US3**: 审查输出格式，验证符合contracts/output-format.md

### Suggested MVP Scope

**MVP = User Story 1 only** (T001-T022)

- 提供整合的持仓监控输出
- 减少日志噪音
- 提高可读性
- 可以独立部署和价值验证

User Story 2和3可以在MVP后增量交付。
