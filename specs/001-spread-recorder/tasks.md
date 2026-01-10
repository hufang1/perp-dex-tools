# Tasks: 价差实时记录器

**Input**: Design documents from `/specs/001-spread-recorder/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: 本项目包含单元测试任务，确保功能正确性和稳定性。

**Organization**: 任务按用户故事组织，支持独立实现和测试每个故事。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可以并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（如US1, US2, US3）
- 描述中包含精确的文件路径

## Path Conventions

本项目是单一Python项目扩展，所有路径相对于仓库根目录：
- 模块: `spread/`
- 测试: `tests/`
- 数据: `data/`
- 日志: `logs/`

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和基础结构

- [X] T001 在 `spread/models.py` 中添加 `SpreadRecord` 数据类（dataclass）
- [X] T002 [P] 在 `spread/config.py` 中添加价差记录器配置字段到 `SpreadArbConfig` 类
- [X] T003 创建 `spread/spread_recorder.py` 文件，定义 `SpreadRecorder` 类的基本结构

---

## Phase 2: Foundational (阻塞先决条件)

**Purpose**: 所有用户故事依赖的核心基础设施

**⚠️ CRITICAL**: 必须完成此阶段才能开始任何用户故事实现

- [X] T004 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._validate_prices` 价格验证方法
- [X] T005 [P] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._get_csv_filename` 文件名生成方法（UTC日期）
- [X] T006 [P] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._write_csv_header` CSV头部写入方法
- [X] T007 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._flush_buffer` 缓冲刷新方法（异步写入CSV）
- [X] T008 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._check_date_change` 日期切换检测方法

**Checkpoint**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 实时价差数据采集和记录 (Priority: P1) 🎯 MVP

**Goal**: 实现核心的价差数据定期采样、CSV写入和终端日志记录功能

**Independent Test**: 运行程序一段时间后，检查 `data/spreads_YYYY_MM_DD.csv` 文件是否正确创建，数据是否完整，终端日志是否正确输出

### Tests for User Story 1

> **NOTE: 先编写测试，确保测试失败后再实现功能**

- [X] T009 [P] [US1] 在 `tests/test_spread_recorder.py` 中编写 `test_spread_record_creation` 测试（SpreadRecord数据类创建）
- [X] T010 [P] [US1] 在 `tests/test_spread_recorder.py` 中编写 `test_price_validation` 测试（价格有效性验证）
- [X] T011 [P] [US1] 在 `tests/test_spread_recorder.py` 中编写 `test_csv_writing` 测试（CSV写入正确性）
- [X] T012 [P] [US1] 在 `tests/test_spread_recorder.py` 中编写 `test_buffer_flushing` 测试（缓冲区刷新逻辑）
- [X] T013 [P] [US1] 在 `tests/test_spread_recorder.py` 中编写 `test_invalid_data_handling` 测试（无效数据处理）

### Implementation for User Story 1

- [X] T014 [P] [US1] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._create_spread_record` 方法（创建SpreadRecord实例）
- [X] T015 [P] [US1] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._calculate_spread` 方法（调用RealSpreadCalculator计算价差）
- [X] T016 [US1] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._write_to_buffer` 方法（将记录添加到缓冲区）
- [X] T017 [US1] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._format_log_message` 方法（格式化终端日志输出，简体中文）
- [X] T018 [US1] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder.record_loop` 异步方法（主记录循环，定时采样）
- [X] T019 [US1] 在 `spread/bot.py` 中添加 `SpreadRecorder` 实例化到 `__init__` 方法
- [X] T020 [US1] 在 `spread/bot.py` 中添加记录器任务到 `run` 方法的任务列表（asyncio.create_task）
- [X] T021 [US1] 在 `spread/spread_recorder.py` 中添加记录器启动/停止的清理逻辑（优雅关闭，刷新缓冲）

**Checkpoint**: 此时用户故事1应完全功能且可独立测试

---

## Phase 4: User Story 2 - 计算公式透明化展示 (Priority: P2)

**Goal**: 在终端日志中显示详细的价差计算公式和中间计算步骤

**Independent Test**: 查看终端日志，确认显示完整的计算公式、输入参数、中间计算步骤和最终结果

### Implementation for User Story 2

- [X] T022 [P] [US2] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._format_long_spread_formula` 方法（做多价差公式展示）
- [X] T023 [P] [US2] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._format_short_spread_formula` 方法（做空价差公式展示）
- [X] T024 [US2] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._format_cost_breakdown` 方法（点差成本分解展示）
- [X] T025 [US2] 在 `spread/spread_recorder.py` 中修改 `_format_log_message` 方法，集成公式展示逻辑
- [X] T026 [US2] 在 `spread/spread_recorder.py` 中添加DEBUG级别的详细计算步骤日志

**Checkpoint**: 此时用户故事1和2都应独立工作

---

## Phase 5: User Story 3 - 数据文件管理和归档 (Priority: P3)

**Goal**: 实现按日期自动创建CSV文件，支持程序重启后追加数据

**Independent Test**: 运行程序跨越午夜时，检查是否创建新日期的文件，旧文件是否正确保留

### Implementation for User Story 3

- [X] T027 [P] [US3] 在 `spread/spread_recorder.py` 中实现 `SpreadRecorder._check_existing_file` 方法（检查文件是否已存在）
- [X] T028 [US3] 在 `spread/spread_recorder.py` 中修改 `_write_csv_header` 方法，仅在文件不存在时写入header
- [X] T029 [US3] 在 `spread/spread_recorder.py` 中修改 `record_loop` 方法，集成日期切换逻辑（调用_check_date_change）
- [X] T030 [US3] 在 `spread/spread_recorder.py` 中实现 `_handle_date_rotation` 方法（处理日期切换时的文件轮换）
- [X] T031 [US3] 在 `spread/spread_recorder.py` 中添加文件追加模式的打开逻辑（'a'模式）

**Checkpoint**: 所有用户故事现在应独立功能完整

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 影响多个用户故事的改进

- [X] T032 [P] 在 `tests/integration/test_spread_recorder_integration.py` 中编写与bot.py集成的集成测试
- [X] T033 [P] 在 `spread/spread_recorder.py` 中添加性能日志（记录每次记录操作耗时）
- [X] T034 在 `spread/spread_recorder.py` 中添加单元测试覆盖未测试的边界情况
- [X] T035 更新 `CLAUDE.md` 文档，添加价差记录器相关技术栈说明
- [X] T036 [P] 验证 `quickstart.md` 中的所有示例可以正常运行
- [X] T037 在 `spread/spread_recorder.py` 中添加配置参数验证逻辑（__post_init__）
- [X] T038 代码清理和优化（移除调试代码，优化日志输出）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-5)**: 都依赖Foundational阶段完成
  - 用户故事可以并行进行（如果有足够人力）
  - 或按优先级顺序执行（P1 → P2 → P3）
- **Polish (Phase 6)**: 依赖所有需要的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P2)**: Foundational完成后可开始 - 依赖US1的记录器实例，但应独立测试
- **User Story 3 (P3)**: Foundational完成后可开始 - 依赖US1的CSV写入，但应独立测试

### Within Each User Story

- 测试必须先编写并失败，然后才能实现功能
- 数据模型（SpreadRecord）在服务（SpreadRecorder）之前
- 核心实现在集成之前
- 故事完成后才能进入下一个优先级

### Parallel Opportunities

- Setup阶段所有标记[P]的任务可以并行运行
- Foundational阶段所有标记[P]的任务可以在Phase 2内并行运行
- Foundational完成后，所有用户故事可以并行开始（如果团队容量允许）
- 用户故事内的所有测试标记[P]可以并行运行
- 不同用户故事可以由不同团队成员并行工作

---

## Parallel Example: User Story 1

```bash
# 一起启动User Story 1的所有测试:
Task: "在 tests/test_spread_recorder.py 中编写 test_spread_record_creation 测试"
Task: "在 tests/test_spread_recorder.py 中编写 test_price_validation 测试"
Task: "在 tests/test_spread_recorder.py 中编写 test_csv_writing 测试"
Task: "在 tests/test_spread_recorder.py 中编写 test_buffer_flushing 测试"
Task: "在 tests/test_spread_recorder.py 中编写 test_invalid_data_handling 测试"

# 一起启动User Story 1的模型任务:
Task: "在 spread/spread_recorder.py 中实现 SpreadRecorder._create_spread_record 方法"
Task: "在 spread/spread_recorder.py 中实现 SpreadRecorder._calculate_spread 方法"
```

---

## Parallel Example: User Story 2

```bash
# 一起启动User Story 2的公式格式化任务:
Task: "在 spread/spread_recorder.py 中实现 SpreadRecorder._format_long_spread_formula 方法"
Task: "在 spread/spread_recorder.py 中实现 SpreadRecorder._format_short_spread_formula 方法"
Task: "在 spread/spread_recorder.py 中实现 SpreadRecorder._format_cost_breakdown 方法"
```

---

## Parallel Example: User Story 3

```bash
# 一起启动User Story 3的文件管理任务:
Task: "在 spread/spread_recorder.py 中实现 SpreadRecorder._check_existing_file 方法"
Task: "在 spread/spread_recorder.py 中修改 _write_csv_header 方法"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成Phase 1: Setup
2. 完成Phase 2: Foundational (CRITICAL - 阻塞所有故事)
3. 完成Phase 3: User Story 1
4. **停止并验证**: 独立测试User Story 1
5. 如果准备就绪，部署/演示

### Incremental Delivery

1. 完成Setup + Foundational → 基础就绪
2. 添加User Story 1 → 独立测试 → 部署/演示 (MVP!)
3. 添加User Story 2 → 独立测试 → 部署/演示
4. 添加User Story 3 → 独立测试 → 部署/演示
5. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy

有多个开发者时：

1. 团队一起完成Setup + Foundational
2. Foundational完成后:
   - 开发者A: User Story 1 (T009-T021)
   - 开发者B: User Story 2 (T022-T026)
   - 开发者C: User Story 3 (T027-T031)
3. 故事独立完成和集成

---

## Summary

- **Total Tasks**: 38 tasks
- **Setup Phase**: 3 tasks (T001-T003)
- **Foundational Phase**: 5 tasks (T004-T008)
- **User Story 1 Phase**: 13 tasks (T009-T021) - 5 tests + 8 implementation
- **User Story 2 Phase**: 5 tasks (T022-T026)
- **User Story 3 Phase**: 5 tasks (T027-T031)
- **Polish Phase**: 7 tasks (T032-T038)

### Task Count per User Story

| User Story | Tests | Implementation | Total |
|------------|-------|----------------|-------|
| US1 - 数据采集记录 | 5 | 8 | 13 |
| US2 - 公式展示 | 0 | 5 | 5 |
| US3 - 文件管理 | 0 | 5 | 5 |

### Parallel Opportunities Identified

- **Setup Phase**: 2 parallel tasks (T002, T003)
- **Foundational Phase**: 2 parallel task groups (T005-T006)
- **US1 Tests**: 5 parallel tasks (T009-T013)
- **US1 Implementation**: 2 parallel task groups (T014-T015, T022-T024, T027)
- **US2 Implementation**: 3 parallel tasks (T022-T024)
- **US3 Implementation**: 2 parallel tasks (T027-T028)
- **Polish Phase**: 2 parallel tasks (T032, T033, T036)

### Independent Test Criteria per Story

- **US1**: 运行程序，检查CSV文件创建和数据完整性，验证终端日志输出
- **US2**: 查看终端日志，确认公式展示完整且正确
- **US3**: 运行程序跨越午夜，验证新文件创建和旧文件保留

### Suggested MVP Scope

**MVP = Phase 1 + Phase 2 + Phase 3 (User Story 1)**

- 21个任务完成核心价差记录功能
- 支持定期采样、CSV写入、终端日志
- 可独立部署和演示
- 后续故事（US2, US3）增量增强功能

---

## Notes

- [P]任务 = 不同文件，无依赖
- [Story]标签将任务映射到特定用户故事以便追溯
- 每个用户故事应独立可完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免: 模糊任务、同文件冲突、破坏独立性的跨故事依赖
