# Tasks: 修复强制平仓时Extended和Lighter都无法正常平仓的问题

**Input**: Design documents from `/specs/006-fix-lighter-close/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: 本功能包含测试任务（规格说明要求验证修复效果）

**Organization**: 任务按用户故事组织，以实现每个故事的独立实施和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（US1, US2）
- 包含精确的文件路径

## Path Conventions

- **单一Python项目**: `spread/`, `tests/` 在仓库根目录
- 本功能为修复性改动，主要修改 `spread/order_manager.py`

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和基本结构（本功能为修复，跳过大部分设置）

- [X] T001 确认当前在 `006-fix-lighter-close` 分支
- [X] T002 验证Python 3.11+环境和pytest已安装

---

## Phase 2: Foundational (阻塞前提条件)

**Purpose**: 核心基础设施（本功能为简单修复，无新的基础设施需求）

**⚠️ CRITICAL**: 无需前置基础设施，可直接进入用户故事实施

**Checkpoint**: 准备就绪 - 用户故事实施可以立即开始

---

## Phase 3: User Story 1 - 修复强制平仓时两个交易所都无法正常平仓 (Priority: P1) 🎯 MVP

**Goal**: 修复CLOSE订单被忽略的问题，使Extended平仓订单成交状态能被正确识别，从而成功执行Lighter平仓

**Independent Test**: 触发强制平仓（设置max-holding-time=70秒），观察Extended平仓订单成交数量是否正确显示（不为0），以及Lighter平仓是否成功执行

### Tests for User Story 1

> **NOTE: 编写测试并确保FAIL，然后再实施修复**

- [X] T003 [P] [US1] CLOSE订单处理单元测试 in tests/test_order_manager.py
- [X] T004 [P] [US1] 竞态条件处理单元测试 in tests/test_order_manager.py
- [X] T005 [P] [US1] 平仓流程集成测试 in tests/integration/test_force_close.py

### Implementation for User Story 1

- [X] T006 [US1] 移除CLOSE订单忽略逻辑 in spread/order_manager.py (删除第242-247行)
- [X] T007 [US1] 验证缓存机制支持CLOSE订单 in spread/order_manager.py (确认_add_pending_update和_apply_pending_updates正常工作)
- [X] T008 [US1] 添加CLOSE订单处理日志 in spread/order_manager.py (更新日志以区分OPEN/CLOSE订单)
- [X] T009 [US1] 验证wait_for_fill正确检测CLOSE订单成交 in spread/order_manager.py (确认FILLED状态检测)

**Checkpoint**: 此时User Story 1应该完全功能化并可独立测试 - Extended平仓订单成交状态正确识别，Lighter平仓成功执行

---

## Phase 4: User Story 2 - 确保Lighter平仓订单能够成功执行 (Priority: P1)

**Goal**: 验证修复CLOSE订单处理后，Lighter平仓流程能够正常工作（主要是验证，不需要修改Lighter代码）

**Independent Test**: 触发强制平仓，验证Extended成交后Lighter平仓订单能成功提交和成交

### Tests for User Story 2

- [X] T010 [P] [US2] 完整平仓流程集成测试 in tests/test_close_order_flow.py
- [X] T011 [P] [US2] 多套利对同时平仓测试 in tests/integration/test_force_close.py

### Implementation for User Story 2

- [X] T012 [US2] 验证Lighter平仓逻辑无需修改 in spread/hedge_manager.py (代码审查确认execute_hedge正常)
- [X] T013 [US2] 验证平仓流程完整执行 in spread/bot.py (确认_close_pair正常调用Extended和Lighter平仓)
- [X] T014 [US2] 添加平仓成功详细日志 in spread/bot.py (记录两个交易所的成交价格、数量、订单ID)

**Checkpoint**: 此时User Stories 1 AND 2都应该独立工作 - 完整的平仓流程能正常执行

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: 影响多个用户故事的改进

- [ ] T015 [P] 更新CLAUDE.md文档（如有新技术引入）
- [X] T016 运行所有测试确保无回归 (104/106通过，2个失败是预存在的test_trade_logging.py问题)
- [ ] T017 [P] 代码清理和格式化
- [ ] T018 按quickstart.md验证修复效果
- [ ] T019 性能验证（检查WebSocket更新处理延迟和Lighter平仓时间）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 无前置阻塞 - 用户故事可立即开始
- **User Stories (Phase 3-4)**: 依赖Setup完成，但无其他阻塞
  - US1和US2可以并行（如果有多人）
  - 或按优先级顺序执行（P1 → P1）
- **Polish (Phase 5)**: 依赖所有用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: 可立即开始 - 无依赖其他故事
- **User Story 2 (P1)**: 可在US1完成后开始 - 依赖US1的CLOSE订单修复
- **注意**: US2主要是验证工作，US1修复后US2应该能自动工作

### Within Each User Story

- 测试必须先编写并FAIL，然后再实施修复
- T003-T005并行编写测试
- T006是核心修复，必须在T008-T009之前
- T006完成后，T007-T009可并行
- US2的T010-T011可并行编写
- T012-T014按顺序执行

### Parallel Opportunities

- Setup阶段: 所有任务可并行
- US1测试阶段: T003, T004, T005可并行编写
- US1实施阶段: T007, T008可并行（都在不同方法中）
- US2测试阶段: T010, T011可并行编写
- Polish阶段: T015, T017, T019可并行

---

## Parallel Example: User Story 1

```bash
# 并行编写所有US1测试:
Task: "CLOSE订单处理单元测试 in tests/test_order_manager.py"
Task: "竞态条件处理单元测试 in tests/test_order_manager.py"
Task: "平仓流程集成测试 in tests/integration/test_force_close.py"

# 核心修复完成后，并行执行验证任务:
Task: "验证缓存机制支持CLOSE订单 in spread/order_manager.py"
Task: "添加CLOSE订单处理日志 in spread/order_manager.py"
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成Phase 1: Setup
2. 跳过Phase 2: Foundational（无需新基础设施）
3. 完成Phase 3: User Story 1
4. **STOP and VALIDATE**: 独立测试User Story 1
5. 如Extended平仓正常识别，即可部署

### Incremental Delivery

1. 完成Setup → 准备就绪
2. 添加User Story 1 → 独立测试 → 部署/演示 (MVP!)
3. 添加User Story 2 → 独立测试 → 部署/演示（完整平仓流程）
4. 添加Polish → 最终验证 → 部署

### 核心修复说明

**T006是唯一的核心修改**：删除3行代码（第242-247行）
```python
# 删除这段代码：
order_type = order_data.get('order_type', '')
if order_type == 'CLOSE':
    # 关闭订单不更新maker_order的状态
    return
```

其他任务主要是验证、测试和日志增强，确保修复正确且不影响其他功能。

---

## Task Summary

- **Total Tasks**: 19
- **Setup Phase**: 2 tasks
- **Foundational Phase**: 0 tasks (无需新基础设施)
- **User Story 1**: 7 tasks (3 tests + 4 implementation)
- **User Story 2**: 5 tasks (2 tests + 3 implementation)
- **Polish Phase**: 5 tasks

**Parallel Opportunities**: 10个任务标记为[P]可并行

**MVP Scope**: User Story 1（7个任务）- 修复CLOSE订单被忽略的问题

---

## Notes

- [P]任务 = 不同文件，无依赖，可并行执行
- [Story]标签将任务映射到特定用户故事以便追溯
- 每个用户故事应该独立完成和可测试
- 在实施前验证测试失败
- 每个任务或逻辑组完成后提交
- 在任何检查点停止以独立验证故事
- 本功能是简单修复，核心只是删除3行代码，大部分工作是验证和测试
