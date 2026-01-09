# Tasks: 统一持仓监控显示并增加平仓收益实时计算

**Input**: Design documents from `/specs/005-unify-position-monitor/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/README.md

**Tests**: 本功能不包含测试任务（未在规格说明中明确要求）

**Organization**: 任务按用户故事组织，确保每个故事可以独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖关系）
- **[Story]**: 任务所属的用户故事（US1, US2, US3）
- 包含精确的文件路径

## Path Conventions

本功能采用单项目结构，所有模块位于 `spread/` 目录

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和配置更新

- [X] T001 在 `spread/config.py` 中添加手续费率配置字段 `extended_fee_rate: Decimal = Decimal('0.000225')` 和 `lighter_fee_rate: Decimal = Decimal('0.0')`

---

## Phase 2: Foundational (阻塞性前置条件)

**Purpose**: 所有用户故事依赖的核心基础模块

**⚠️ CRITICAL**: 此阶段完成前，不能开始任何用户故事的实现

- [X] T002 [P] 在 `spread/` 目录创建 `position_aggregator.py` 文件，实现持仓聚合器模块框架
- [X] T003 [P] 在 `spread/position_aggregator.py` 中实现 `UnifiedPosition` 数据类（包含direction, pair_ids, total_quantity, extended_avg_price, lighter_avg_price, earliest_open_time, latest_open_time, total_opening_fees字段）
- [X] T004 [P] 在 `spread/position_aggregator.py` 中实现 `aggregate_positions(pairs: List[SpreadPair]) -> Dict[str, UnifiedPosition]` 函数框架
- [X] T005 在 `spread/position_aggregator.py` 中实现按方向分组的持仓聚合逻辑（计算加权平均价格、时间范围、总手续费）
- [X] T006 [P] 在 `spread/` 目录创建 `profit_calculator.py` 文件，实现收益计算器模块框架
- [X] T007 [P] 在 `spread/profit_calculator.py` 中实现 `ProfitBreakdown` 数据类（包含spread_profit, opening_fees, estimated_closing_fees, net_profit, extended_pnl, lighter_pnl字段）
- [X] T008 [P] 在 `spread/profit_calculator.py` 中实现 `calculate_profit(...)` 函数框架（包含position, bid/ask价格, fee_rate参数）
- [X] T009 在 `spread/profit_calculator.py` 中实现平仓收益计算逻辑（价差收益、开仓手续费、平仓手续费、净收益）
- [X] T010 在 `spread/spread_pair.py` 中添加 `calculate_opening_fees(fee_rate: Decimal) -> Decimal` 方法

**Checkpoint**: 基础模块就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 统一持仓监控显示 (Priority: P1) 🎯 MVP

**Goal**: 将多个同向仓位合并显示为一个统一仓位视图

**Independent Test**: 启动套利机器人并开启多个同向仓位，验证监控输出只显示一个合并的仓位信息

### Implementation for User Story 1

- [X] T011 [US1] 在 `spread/bot.py` 中导入 `PositionAggregator` 和 `UnifiedPosition`
- [X] T012 [US1] 在 `SpreadArbitrageBot.__init__()` 中初始化 `self.position_aggregator = PositionAggregator()`
- [X] T013 [US1] 在 `spread/bot.py` 中重构 `_log_position_status()` 方法，替换为新的聚合显示逻辑
- [X] T014 [US1] 在 `spread/bot.py` 的 `_monitor_pairs()` 方法中，将单个pair循环改为聚合后输出
- [X] T015 [US1] 实现统一持仓的格式化输出函数（包含总数量、平均价格、时间范围、pair_id列表）
- [X] T016 [US1] 添加持仓方向判断逻辑（做多/做空分别显示）
- [X] T017 [US1] 处理空持仓列表的边界情况（显示"当前无持仓"）

**Checkpoint**: 此时用户故事1应完全可用且可独立测试

---

## Phase 4: User Story 2 - 实时显示平仓后收益 (Priority: P1)

**Goal**: 计算并显示平仓后的净收益（扣除所有手续费）

**Independent Test**: 开启持仓并查看监控输出，验证"平仓后的收益"字段正确计算并显示

### Implementation for User Story 2

- [X] T018 [P] [US2] 在 `spread/bot.py` 中导入 `ProfitCalculator` 和 `ProfitBreakdown`
- [X] T019 [P] [US2] 在 `SpreadArbitrageBot.__init__()` 中初始化 `self.profit_calculator = ProfitCalculator(config.extended_fee_rate, config.lighter_fee_rate)`
- [X] T020 [US2] 在统一持仓输出中调用 `calculate_profit()` 计算平仓收益（使用当前订单簿的bid/ask价格）
- [X] T021 [US2] 实现平仓收益的格式化输出（价差收益、手续费、净收益）
- [X] T022 [US2] 处理订单簿为空或价格无效的边界情况（显示"价格数据异常"而非错误值）
- [X] T023 [US2] 在 `spread/config.py` 中的 `__post_init__()` 验证手续费率配置（必须 >= 0）

**Checkpoint**: 此时用户故事1和2都应独立可用

---

## Phase 5: User Story 3 - 清晰的持仓信息展示 (Priority: P2)

**Goal**: 优化输出格式，提供清晰易读的中文界面

**Independent Test**: 查看监控输出的格式和内容，验证是否包含所有必要信息且格式清晰

### Implementation for User Story 3

- [X] T024 [P] [US3] 设计新的输出格式模板（使用Unicode全角划线分隔符）
- [X] T025 [P] [US3] 实现中文字段标签（持仓时间、剩余时间、当前价格、未实现盈亏、距离盈利目标、平仓后收益）
- [X] T026 [US3] 实现数值格式化（价格2位小数、数量4位小数、时间整数秒）
- [X] T027 [US3] 添加分隔线和分组标题（"做多仓位 (共N个套利对)"）
- [X] T028 [US3] 实现颜色或符号标识（盈利用+、亏损用-）
- [X] T029 [US3] 优化日志输出层级（使用logger.info输出汇总信息）

**Checkpoint**: 所有用户故事现在都应独立可用

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 跨用户故事的改进和优化

- [X] T030 [P] 在 `CLAUDE.md` 中更新项目技术栈（添加005-unify-position-monitor的Python 3.11+依赖）
- [X] T031 [P] 在 `spread/README.md` 中更新功能描述（新增统一持仓监控和平仓收益计算）
- [X] T032 代码清理和重构（移除旧的 `_log_position_status` 单个pair输出逻辑）
- [X] T033 性能优化（确保持仓聚合和收益计算在100ms内完成）
- [X] T034 运行 `quickstart.md` 验证（确认输出格式与示例一致）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-5)**: 都依赖Foundational阶段完成
  - 用户故事可按优先级顺序实现（P1 → P1 → P2）
  - 或并行实现（如果有资源）
- **Polish (Phase 6)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 不依赖其他故事
- **User Story 2 (P1)**: Foundational完成后可开始 - 可与US1并行，但需集成到统一输出格式
- **User Story 3 (P2)**: 依赖US1和US2的输出内容完成 - 优化格式

### Within Each User Story

- **US1**: T011 → T012 → T013 → T014 → T015 → T016 → T017（顺序执行）
- **US2**: T018/T019可并行 → T020 → T021 → T022 → T023（顺序执行）
- **US3**: T024/T025/T026可并行 → T027 → T028 → T029（顺序执行）

### Parallel Opportunities

- **Phase 2 Foundational**: T002, T003, T004, T006, T007, T008 可并行
- **Phase 2 Foundational**: T005, T009, T010 可并行（依赖前面的数据类定义）
- **US2**: T018, T019 可并行
- **US3**: T024, T025, T026 可并行
- **Phase 6 Polish**: T030, T031 可并行

---

## Parallel Example: User Story 1 & 2

```bash
# User Story 1 核心任务（顺序执行）:
T011: 导入PositionAggregator
T012: 初始化aggregator
T013: 重构_log_position_status
T014: 修改_monitor_pairs循环
T015: 实现格式化输出
T016: 添加方向判断
T017: 处理边界情况

# User Story 2 核心任务（T018/T019并行）:
T018: 导入ProfitCalculator
T019: 初始化calculator
T020: 调用calculate_profit
T021: 格式化收益输出
T022: 处理边界情况
T023: 验证配置
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（CRITICAL - 阻塞所有故事）
3. 完成 Phase 3: User Story 1
4. **停止并验证**: 独立测试用户故事1
5. 如就绪则部署/演示

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（MVP！）
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 每个故事都增加价值且不破坏前序故事

### Sequential Strategy (Recommended for Single Developer)

1. Phase 1: Setup (T001)
2. Phase 2: Foundational (T002-T010)
3. Phase 3: User Story 1 (T011-T017)
4. Phase 4: User Story 2 (T018-T023)
5. Phase 5: User Story 3 (T024-T029)
6. Phase 6: Polish (T030-T034)

---

## Notes

- [P] 任务 = 不同文件，无依赖关系
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应可独立完成和测试
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖
