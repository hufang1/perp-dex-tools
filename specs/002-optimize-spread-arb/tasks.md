# Tasks: 优化价差套利策略

**Input**: Design documents from `/specs/002-optimize-spread-arb/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: 本功能包含测试任务,使用 pytest 进行单元测试和集成测试。

**Organization**: 任务按用户故事分组,以支持独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行 (不同文件,无依赖)
- **[Story]**: 任务所属的用户故事 (US1, US2, US3, US4)
- 包含精确文件路径

## Path Conventions

本项目使用单一项目结构:
- 源代码: `spread/` (主要修改目录)
- 测试: `tests/` (新增测试文件)
- 配置: `.env` 文件 (环境变量)

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和测试环境准备

- [X] T001 确认开发环境 Python 3.11+ 已安装并激活虚拟环境
- [X] T002 [P] 创建 tests/integration/ 目录用于集成测试
- [X] T003 [P] 确认 pytest 和测试依赖已安装 (pytest, pytest-asyncio, pytest-cov)

---

## Phase 2: Foundational (阻塞性前置条件)

**目的**: 所有用户故事依赖的核心基础设施

**⚠️ 关键**: 此阶段完成前,任何用户故事工作都无法开始

- [X] T004 在 spread/config.py 中新增 `from_env()` 类方法支持环境变量加载
- [X] T005 [P] 在 spread/config.py 中新增平仓策略配置字段 (profit_target_rate, time_close_threshold, max_holding_time)
- [X] T006 [P] 在 spread/config.py 中新增未对冲持仓配置字段 (unhedged_position_timeout)
- [X] T007 在 spread/config.py 中调整 min_spread_rate 默认值为 Decimal('0.0005') (0.05%)
- [X] T008 在 spread/spread_pair.py 中新增订单ID字段 (open_extended_order_id, open_lighter_order_id, close_extended_order_id, close_lighter_order_id)
- [X] T009 更新 spread/spread_pair.py 的 __init__ 方法签名以接受新增的订单ID参数

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 避免单边持仓风险 (优先级: P1) 🎯 MVP

**目标**: 自动检测并处理单边持仓,避免长时间未对冲的敞口风险

**独立测试**: 模拟订单部分成交场景,验证系统在单边持仓时能正确处理

### 测试 for User Story 1

> **注意: 先编写这些测试,确保它们 FAIL 后再实现功能**

- [ ] T010 [P] [US1] 创建 tests/integration/test_unhedged_position.py 测试单边持仓检测
- [ ] T011 [P] [US1] 创建 tests/integration/test_unhedged_position.py 测试单边持仓超时告警
- [ ] T012 [P] [US1] 创建 tests/integration/test_unhedged_position.py 测试单边持仓存在时禁止开新仓

### 实现 for User Story 1

- [ ] T013 [US1] 在 spread/bot.py 的 _strategy_loop() 中增强单边持仓检查 (在开仓前验证 len(unhedged_positions) <= max)
- [ ] T014 [US1] 在 spread/bot.py 的 _reconciliation_loop() 中增加单边持仓超时检测逻辑
- [ ] T015 [US1] 在 spread/bot.py 的 _reconciliation_loop() 中增加单边持仓超时告警日志
- [ ] T016 [US1] 在 spread/hedge_manager.py 中增强对冲失败时的错误信息记录
- [ ] T017 [US1] 在 spread/bot.py 的 _stats_reporter() 中增加未对冲持仓统计显示

**检查点**: 此时 User Story 1 应该完全功能化且可独立测试

---

## Phase 4: User Story 2 - 基于手续费的价差阈值优化 (优先级: P1)

**目标**: 根据实际手续费结构调整开仓阈值,提高交易频率同时保证盈利

**独立测试**: 通过历史数据回测验证,价差超过0.05%时开仓能产生正收益

### 测试 for User Story 2

- [ ] T018 [P] [US2] 创建 tests/test_config.py 测试 min_spread_rate 配置验证
- [ ] T019 [P] [US2] 创建 tests/test_config.py 测试 from_env() 方法正确加载环境变量
- [ ] T020 [P] [US2] 创建 tests/integration/test_spread_threshold.py 测试价差阈值开仓逻辑

### 实现 for User Story 2

- [ ] T021 [US2] 在 spread/config.py 的 __post_init__ 中验证 min_spread_rate > latency_buffer
- [ ] T022 [US2] 在 spread/config.py 的 from_env() 中实现 MIN_SPREAD_RATE 环境变量读取
- [ ] T023 [US2] 在 spread/calculator.py 中调整 effective_min_spread 计算逻辑 (使用新的 min_spread_rate)
- [ ] T024 [US2] 在 spread/calculator.py 中增加价差阈值调试日志 (记录实际使用的阈值)
- [ ] T025 [US2] 在 spread/bot.py 的 _log_config() 中增加 min_spread_rate 配置参数日志输出

**检查点**: 此时 User Stories 1 和 2 都应该独立工作

---

## Phase 5: User Story 3 - 智能平仓策略 (优先级: P1)

**目标**: 根据持仓时间和收益情况执行多层平仓策略,最大化资金利用效率

**独立测试**: 模拟不同市场行情 (快速波动、横盘、趋势) 验证平仓逻辑

### 测试 for User Story 3

- [ ] T026 [P] [US3] 创建 tests/integration/test_closing_strategy.py 测试盈利目标平仓
- [ ] T027 [P] [US3] 创建 tests/integration/test_closing_strategy.py 测试时间小额平仓
- [ ] T028 [P] [US3] 创建 tests/integration/test_closing_strategy.py 测试回本止损平仓
- [ ] T029 [P] [US3] 创建 tests/integration/test_closing_strategy.py 测试强制平仓

### 实现 for User Story 3

- [ ] T030 [US3] 在 spread/bot.py 的 _check_force_close() 中实现盈利目标平仓逻辑 (优先级1)
- [ ] T031 [US3] 在 spread/bot.py 的 _check_force_close() 中实现时间小额平仓逻辑 (优先级2)
- [ ] T032 [US3] 在 spread/bot.py 的 _check_force_close() 中实现回本止损平仓逻辑 (优先级3)
- [ ] T033 [US3] 在 spread/bot.py 的 _check_force_close() 中实现强制平仓逻辑 (优先级4)
- [ ] T034 [US3] 在 spread/bot.py 的 _check_force_close() 中增加平仓原因详细日志
- [ ] T035 [US3] 在 spread/config.py 的 __post_init__ 中验证平仓策略参数 (profit_target_rate, time_close_threshold, max_holding_time)
- [ ] T036 [US3] 在 spread/config.py 的 from_env() 中实现平仓策略环境变量读取 (PROFIT_TARGET_RATE, TIME_CLOSE_THRESHOLD, MAX_HOLDING_TIME)

**检查点**: 所有用户故事现在都应该独立功能化

---

## Phase 6: User Story 4 - 交易价格日志记录 (优先级: P2)

**目标**: 在开仓和平仓时记录详细价格信息,用于后续策略分析和优化

**独立测试**: 执行一次完整套利流程,检查日志中是否包含所有必需的价格字段

### 测试 for User Story 4

- [ ] T037 [P] [US4] 创建 tests/integration/test_trading_logs.py 验证开仓日志包含所有必需字段
- [ ] T038 [P] [US4] 创建 tests/integration/test_trading_logs.py 验证平仓日志包含所有必需字段

### 实现 for User Story 4

- [ ] T039 [US4] 在 spread/bot.py 的 _open_new_pair() 中记录 Extended 开仓订单ID 到 SpreadPair
- [ ] T040 [US4] 在 spread/bot.py 的 _open_new_pair() 中记录 Lighter 开仓订单ID 到 SpreadPair
- [ ] T041 [US4] 在 spread/bot.py 的 _open_new_pair() 中增强开仓日志 (包含交易所、方向、价格、数量、时间戳、订单ID)
- [ ] T042 [US4] 在 spread/bot.py 的 _close_pair() 中记录 Extended 平仓订单ID 到 SpreadPair
- [ ] T043 [US4] 在 spread/bot.py 的 _close_pair() 中记录 Lighter 平仓订单ID 到 SpreadPair
- [ ] T044 [US4] 在 spread/bot.py 的 _close_pair() 中增强平仓日志 (包含平仓价格、持仓时间、realized PnL)
- [ ] T045 [US4] 在 spread/bot.py 的 _close_pair() 中增加交易对总结日志 (开仓价、平仓价、收益率)

**检查点**: 所有用户故事 (包括 US4) 现在都应该完整功能化

---

## Phase 7: Polish & Cross-Cutting Concerns (完善与跨领域关注点)

**目的**: 影响多个用户故事的改进

- [ ] T046 [P] 运行 pytest 生成测试覆盖率报告 (pytest --cov=spread --cov-report=html)
- [ ] T047 [P] 创建 tests/fixtures.py 文件定义测试夹具 (sample_config, sample_spread_pair)
- [ ] T048 更新 .env.example 文件包含所有新增的环境变量
- [ ] T049 运行 quickstart.md 中的验证步骤确保文档准确性
- [ ] T050 代码清理和优化 (移除调试代码,优化日志格式)
- [ ] T051 最终集成测试:运行完整的套利流程验证所有用户故事协同工作

---

## Dependencies & Execution Order

### Phase Dependencies (阶段依赖)

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - 阻塞所有用户故事
- **User Stories (Phase 3-6)**: 全部依赖 Foundational 阶段完成
  - US1 (Phase 3), US2 (Phase 4), US3 (Phase 5) 可并行开发 (如果有足够人力)
  - US4 (Phase 6) 可与其他用户故事并行,但因为优先级 P2 建议最后完成
- **Polish (Phase 7)**: 依赖所有需要的用户故事完成

### User Story Dependencies (用户故事依赖)

- **User Story 1 (P1)**: Foundational 完成后可开始 - 无其他故事依赖
- **User Story 2 (P1)**: Foundational 完成后可开始 - 可与 US1 并行
- **User Story 3 (P1)**: Foundational 完成后可开始 - 可与 US1, US2 并行
- **User Story 4 (P2)**: Foundational 完成后可开始 - 可与其他故事并行

### Within Each User Story (用户故事内部)

- 测试 MUST 先编写并 FAIL 后再实现功能
- 配置更改 before 逻辑更改
- 核心逻辑 before 日志增强
- 故事完成 before 移至下一优先级

### Parallel Opportunities (并行机会)

- Setup 阶段所有 [P] 任务可并行
- Foundational 阶段所有 [P] 任务可并行 (T005-T008)
- Foundational 完成后,所有用户故事可并行开始 (如果团队容量允许)
- 每个用户故事内所有 [P] 测试可并行编写
- 不同用户故事可由不同团队成员并行工作

---

## Parallel Example: User Story 1

```bash
# 并行启动 User Story 1 的所有测试:
Task T010: "创建 tests/integration/test_unhedged_position.py 测试单边持仓检测"
Task T011: "创建 tests/integration/test_unhedged_position.py 测试单边持仓超时告警"
Task T012: "创建 tests/integration/test_unhedged_position.py 测试单边持仓存在时禁止开新仓"
```

---

## Implementation Strategy

### MVP First (仅 User Story 1)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational (关键 - 阻塞所有故事)
3. 完成 Phase 3: User Story 1
4. **停止并验证**: 独立测试 User Story 1
5. 如准备就绪可部署/演示

### Incremental Delivery (增量交付)

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示 (MVP!)
3. 添加 User Story 2 → 独立测试 → 部署/演示
4. 添加 User Story 3 → 独立测试 → 部署/演示
5. 添加 User Story 4 → 独立测试 → 部署/演示
6. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy (并行团队策略)

有多名开发者时:

1. 团队一起完成 Setup + Foundational
2. Foundational 完成后:
   - 开发者 A: User Story 1 (单边持仓风险)
   - 开发者 B: User Story 2 (价差阈值优化)
   - 开发者 C: User Story 3 (智能平仓策略)
3. 故事独立完成并集成

---

## Notes

- [P] 任务 = 不同文件,无依赖
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应该可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免: 模糊任务,同文件冲突,破坏独立性的跨故事依赖

---

## Summary

**总任务数**: 51
**每个用户故事的任务数**:
- User Story 1: 8 tasks (3 tests + 5 implementation)
- User Story 2: 8 tasks (3 tests + 5 implementation)
- User Story 3: 11 tasks (4 tests + 7 implementation)
- User Story 4: 9 tasks (2 tests + 7 implementation)

**并行机会识别**:
- Setup 阶段: 2 个并行任务
- Foundational 阶段: 4 个并行任务
- 各用户故事内部: 多个并行测试编写任务
- 用户故事之间: US1, US2, US3 可完全并行开发

**独立测试标准**:
- US1: 模拟单边持仓场景验证检测和告警
- US2: 历史数据回测验证价差阈值
- US3: 模拟不同市场行情验证平仓逻辑
- US4: 完整套利流程验证日志完整性

**建议 MVP 范围**: User Story 1 (避免单边持仓风险) - 核心风险控制功能

**格式验证**: 所有任务遵循检查清单格式 (checkbox, ID, labels, file paths)
