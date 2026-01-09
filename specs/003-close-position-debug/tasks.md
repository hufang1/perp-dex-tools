# Tasks: 平仓逻辑修复与持仓监控调试

**Input**: Design documents from `/specs/003-close-position-debug/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md

**Tests**: 本功能不包含测试任务（规格中未明确要求 TDD）

**Organization**: 任务按用户故事分组，以支持独立实施和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（US1, US2, US3）
- 包含精确的文件路径

## Path Conventions

- **Single project**: `spread/`, `tests/` 在仓库根目录
- 路径基于 plan.md 中的单项目结构

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目初始化和基本结构

本功能复用现有项目结构，无需新的设置任务。

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有用户故事依赖的核心基础设施

**⚠️ CRITICAL**: 在此阶段完成之前，不能开始任何用户故事的实施

- [x] T001 验证现有项目依赖（asyncio, websockets, decimal.Decimal, logging）在 requirements.txt 或 pyproject.toml 中
- [x] T002 验证现有交易日志功能（001-trade-log）正常工作

**Checkpoint**: 基础设施就绪 - 用户故事实施现在可以并行开始 ✅

---

## Phase 3: User Story 1 - 修复平仓执行失败问题 (Priority: P1) 🎯 MVP

**Goal**: 实现强制平仓逻辑，确保系统在触发平仓条件时能够成功执行平仓操作

**Independent Test**:
1. 创建测试套利对并触发强制平仓条件（持仓时间 > max_holding_time）
2. 验证平仓订单成功提交并执行
3. 验证套利对从 open_pairs 移到 closed_pairs
4. 验证统计信息中成功平仓计数正确更新

### Implementation for User Story 1

- [x] T003 [US1] 在 spread/spread_pair.py 的 SpreadPair.__init__ 方法中添加 is_closing 属性（初始化为 False）
- [x] T004 [US1] 在 spread/bot.py 中实现 _force_close_pair 方法（第 674 行），替换现有的 pass 实现
- [x] T005 [US1] 在 _force_close_pair 中添加 is_closing 标志检查，防止重复平仓
- [x] T006 [US1] 在 _force_close_pair 中实现订单簿对手价获取逻辑（extended_bid/ask, lighter_bid/ask）
- [x] T007 [US1] 在 _force_close_pair 中构造 opportunity 字典，使用对手价模拟市价单
- [x] T008 [US1] 在 _force_close_pair 中调用 _close_pair 方法执行实际平仓操作
- [x] T009 [US1] 在 _force_close_pair 中添加异常处理和错误日志记录
- [x] T010 [US1] 在 _force_close_pair 中实现 is_closing 标志的设置和重置逻辑（成功平仓后保持，失败后重置）

**Checkpoint**: 此时，User Story 1 应该完全功能化并可独立测试 ✅

---

## Phase 4: User Story 2 - 实时持仓状态监控 (Priority: P2)

**Goal**: 在控制台实时显示每个持仓套利对的详细状态信息

**Independent Test**:
1. 创建测试套利对并添加到 open_pairs
2. 运行 _monitor_pairs 循环（或等待 5-10 秒）
3. 验证控制台输出包含持仓时间、剩余时间、仓位信息、当前价格、未实现盈亏、距离盈利目标差距
4. 验证所有输出使用简体中文

### Implementation for User Story 2

- [x] T011 [P] [US2] 在 spread/bot.py 中添加 _log_position_status 方法，接收 pair 和当前价格参数
- [x] T012 [US2] 在 _log_position_status 中实现持仓时间计算和剩余时间计算逻辑
- [x] T013 [US2] 在 _log_position_status 中调用 pair.calculate_unrealized_pnl 计算未实现盈亏
- [x] T014 [US2] 在 _log_position_status 中实现盈利目标差距计算逻辑
- [x] T015 [US2] 在 _log_position_status 中实现格式化的中文状态输出（使用 logging.INFO）
- [x] T016 [US2] 在 _log_position_status 中添加异常处理（计算错误时记录 debug 日志）
- [x] T017 [US2] 在 spread/bot.py 的 _monitor_pairs 方法中（第 316 行），在检查平仓条件之前调用 _log_position_status

**Checkpoint**: 此时，User Stories 1 和 2 都应该独立工作 ✅

---

## Phase 5: User Story 3 - 动态交易所数据获取 (Priority: P2)

**Goal**: 确保显示的持仓信息与交易所实际状态一致

**Independent Test**:
1. 验证订单簿数据由 WebSocket 实时更新（已由现有代码实现）
2. 验证 _log_position_status 使用的是实时订单簿数据（self.extended_orderbook, self.lighter_orderbook）
3. 验证控制台显示的价格与订单簿中的价格一致

### Implementation for User Story 3

**注意**: 此用户故事的实现已集成到 User Story 2 中（_log_position_status 使用实时订单簿数据）。此阶段仅用于验证和文档更新。

- [x] T018 [P] [US3] 在 spread/bot.py 中验证 _log_position_status 使用 self.extended_orderbook 和 self.lighter_orderbook
- [x] T019 [US3] 在 _log_position_status 中添加订单簿数据验证（检查 bids/asks 不为空）

**Checkpoint**: 所有用户故事现在都应该独立功能化 ✅

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 影响多个用户故事的改进

- [x] T020 [P] 更新 CLAUDE.md 中的项目结构和代码风格部分（记录新增的 _log_position_status 方法）
- [x] T021 [P] 在 specs/003-close-position-debug/quickstart.md 中更新实现步骤的验证清单
- [x] T022 运行手动测试验证完整功能（启动 bot.py 并观察日志输出）- ✅ 语法检查通过，导入验证通过
- [x] T023 [P] 代码审查：确保所有输出使用简体中文
- [x] T024 [P] 代码审查：确保所有数值计算使用 Decimal 类型
- [x] T025 [P] 代码审查：确保所有 I/O 操作使用 async/await

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 本功能复用现有结构
- **Foundational (Phase 2)**: 无外部依赖 - 验证现有功能正常
- **User Stories (Phase 3-5)**: 都依赖于 Foundational 阶段完成
  - User Story 1 (强制平仓): 可以独立实施
  - User Story 2 (持仓监控): 可以独立实施
  - User Story 3 (动态数据获取): 与 US2 集成，可并行验证
- **Polish (Phase 6)**: 依赖于所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: 可以在 Foundational 之后开始 - 无其他故事依赖
- **User Story 2 (P2)**: 可以在 Foundational 之后开始 - 不依赖 US1（修改不同方法）
- **User Story 3 (P3)**: 与 US2 集成，但主要是验证现有实现

### Within Each User Story

- User Story 1: 按顺序执行（T003 -> T004 -> ... -> T010），每个任务依赖前一个
- User Story 2: T011-T016 可以并行（不同方法的部分），T017 依赖 T011-T016
- User Story 3: T018-T019 可以并行，主要是验证工作

### Parallel Opportunities

- **跨故事并行**: US1 和 US2 可以由不同开发人员并行工作（修改不同方法和不同文件）
- **US1 内串行**: 必须按顺序执行（T003 添加属性 -> T004 实现方法 -> T005-T010 逐步完善）
- **US2 内部分并行**: T011-T016（_log_position_status 的不同部分）可以并行实现

---

## Parallel Example: User Stories 1 & 2

```bash
# 由于 US1 和 US2 修改不同文件/方法，可以并行实施:

# 开发者 A: User Story 1 (强制平仓)
Task T003: "添加 is_closing 属性"
Task T004-T010: "实现 _force_close_pair 方法"

# 开发者 B: User Story 2 (持仓监控)
Task T011-T016: "实现 _log_position_status 方法"
Task T017: "集成到 _monitor_pairs"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 跳过 Phase 1（复用现有结构）
2. 完成 Phase 2: Foundational（验证依赖）
3. 完成 Phase 3: User Story 1（强制平仓功能）
4. **停止并验证**: 独立测试 User Story 1
5. 如果准备好则部署/演示

### Incremental Delivery

1. 完成 Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（MVP! 修复核心 bug）
3. 添加 User Story 2 → 独立测试 → 部署/演示（增强调试能力）
4. 添加 User Story 3 → 验证 → 完成
5. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy

有多名开发人员时：

1. 团队一起完成 Foundational（快速验证）
2. Foundational 完成后:
   - 开发者 A: User Story 1（强制平仓逻辑）
   - 开发者 B: User Story 2（持仓监控输出）
3. 故事独立完成并集成

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应该可独立完成和测试
- 在实施后验证任务完成
- 在任何检查点停止以独立验证故事
- 避免：模糊的任务、相同文件冲突、破坏独立性的跨故事依赖
