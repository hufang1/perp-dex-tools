# Tasks: 价差套利程序优化

**Input**: Design documents from `/specs/016-spread-optimize/`
**Prerequisites**: plan.md, spec.md, data-model.md, research.md

**Tests**: 本功能规格不强制要求TDD，但建议为每个新组件编写单元测试以确保功能正确性。

**Organization**: 任务按用户故事分组，以支持每个故事的独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖关系）
- **[Story]**: 此任务属于哪个用户故事（如 US1, US2, US3）
- 描述中包含确切的文件路径

## Path Conventions

本项目使用单项目结构：
- `spread/` - 价差套利模块（主要代码）
- `exchanges/` - 交易所客户端（现有，不修改）
- `tests/unit/` - 单元测试
- `tests/integration/` - 集成测试

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基本结构准备

- [X] T001 在spread/目录下创建新组件文件结构：spread_monitor.py, arithmetic_open_strategy.py, smart_close_strategy.py, position_balance_checker.py, logger_config.py
- [X] T002 创建tests目录结构：tests/unit/和tests/integration/
- [X] T003 [P] 在spread/models.py中添加新的配置字段（cached_open_spread, spread_step, balance_check_buffer, total_fee_rate）
- [X] T004 [P] 在spread/models.py中添加新的数据类（SpreadInfo, OpenPosition, Portfolio, BalanceCheckResult, CloseTrigger）

---

## Phase 2: Foundational (阻塞性前置条件)

**目的**: 核心基础设施，必须在任何用户故事实现前完成

**⚠️ 关键**: 在此阶段完成前不能开始任何用户故事工作

- [X] T005 更新spread/state_manager.py以支持Portfolio持久化（添加portfolio字段的保存和加载逻辑）
- [X] T006 [P] 更新spread/env_validator.py精简日志输出（将详细输出改为单行摘要）
- [X] T007 验证state_manager向后兼容性（确保能读取旧的状态文件并转换为新格式）

**Checkpoint**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 精简日志输出 (Priority: P1) 🎯 MVP

**目标**: 程序启动和运行时输出精简的单行日志，关键信息在一行内完整呈现

**独立测试**: 启动程序后检查日志输出，验证启动信息不超过10行且为单行格式

### Implementation for User Story 1

- [X] T008 [P] [US1] 创建spread/logger_config.py模块，配置精简的日志格式（单行紧凑格式）
- [X] T009 [P] [US1] 在spread/env_validator.py中实现单行配置摘要输出：`配置: ETH|0.01|开仓0.20%|盈利0.10%|缓冲3s`
- [X] T010 [US1] 修改spread/spread_arb_bot.py，将非关键日志（初始化详情、组件状态）从INFO降级到DEBUG
- [X] T011 [US1] 更新spread/env_validator.py的check_env_before_start()函数，返回单行摘要而非多行详细输出
- [X] T012 [US1] 在spread/__init__.py中导入并应用logger_config配置

**Checkpoint**: 此时，User Story 1应该完全功能正常且可独立测试

---

## Phase 4: User Story 2 - 实时价差监控 (Priority: P1)

**目标**: 实时监控两个交易所的订单簿，计算并显示价差信息

**独立测试**: 程序运行后持续输出价差信息，验证价格数据准确性和更新频率

### Implementation for User Story 2

- [X] T013 [P] [US2] 创建spread/spread_monitor.py类，实现SpreadMonitor核心逻辑
- [X] T014 [P] [US2] 在spread/spread_monitor.py中实现订阅order_book_manager价格更新的功能
- [X] T015 [P] [US2] 在spread/spread_monitor.py中实现价差计算逻辑（使用SpreadInfo数据模型）
- [X] T016 [P] [US2] 在spread/spread_monitor.py中实现单行日志格式化：`价差: Ext[3325.5/3326.5] Lig[3320.0/3321.0] = 5.5 (0.17%)`
- [X] T017 [US2] 在spread/spread_monitor.py中实现价差数据验证（bid/ask有效性检查，异常时输出ERROR但不中断）
- [X] T018 [US2] 在spread/spread_arb_bot.py中集成SpreadMonitor，在_init_components中初始化并在start中启动
- [X] T019 [US2] 在spread/spread_monitor.py中实现get_current_spread()方法供其他组件使用

**Checkpoint**: 此时，User Story 2应该完全功能正常且可独立测试

---

## Phase 5: User Story 3 - 等差数列开仓策略 (Priority: P1)

**目标**: 当价差超过阈值时执行开仓，之后按等差数列继续开仓

**独立测试**: 设定参数模拟价差变化，验证开仓行为符合预期

### Implementation for User Story 3

- [X] T020 [P] [US3] 创建spread/arithmetic_open_strategy.py类，实现ArithmeticOpenStrategy核心逻辑
- [X] T021 [P] [US3] 在spread/arithmetic_open_strategy.py中实现should_open()方法（首次：spread > min_threshold；后续：spread > cached + step）
- [X] T022 [P] [US3] 在spread/arithmetic_open_strategy.py中实现update_cached_spread()方法（更新BotConfig中的cached_open_spread）
- [X] T023 [P] [US3] 在spread/arithmetic_open_strategy.py中实现单行日志输出：`开仓: 价差0.25% > 阈值0.2%` 或 `价差0.28%未达到开仓条件0.35%`
- [X] T024 [US3] 在spread/spread_arb_bot.py的_process_idle_state()中集成ArithmeticOpenStrategy，替换原有的简单阈值判断
- [X] T025 [US3] 在spread/spread_arb_bot.py中，开仓成功后调用update_cached_spread()更新缓存价差
- [X] T026 [US3] 确保价差缩小时不降低缓存价差（在should_open中实现此逻辑）
- [X] T027 [US3] 更新spread/spread_arb_bot.py的命令行参数解析，添加--spread-step参数支持

**Checkpoint**: 此时，User Story 3应该完全功能正常且可独立测试

---

## Phase 6: User Story 4 - 智能平仓系统 (Priority: P2)

**目标**: 实时监控持仓，当满足平仓条件时执行平仓锁定利润

**独立测试**: 建立模拟仓位，模拟价差变化验证平仓触发

### Implementation for User Story 4

- [X] T028 [P] [US4] 创建spread/smart_close_strategy.py类，实现SmartCloseStrategy核心逻辑
- [X] T029 [P] [US4] 在spread/smart_close_strategy.py中实现add_position()方法，使用Portfolio管理多笔仓位
- [X] T030 [P] [US4] 在spread/smart_close_strategy.py中实现should_close()方法（检查：entry_spread >= current_spread + profit_target + fees）
- [X] T031 [P] [US4] 在spread/smart_close_strategy.py中实现加权平均开仓价差计算（Portfolio._recalculate）
- [X] T032 [P] [US4] 在spread/smart_close_strategy.py中实现单行日志输出：`平仓: 开仓0.3% >= 当前0.15% + 盈利0.1% + 手续费0.05% = 0.3%`
- [X] T033 [US4] 在spread/smart_close_strategy.py中实现持仓监控日志：`持仓: 开仓0.3% vs 当前0.2% (盈利0.1% < 目标0.15%)`
- [X] T034 [US4] 在spread/smart_close_strategy.py中实现价差扩大警告：`价差扩大: 当前0.35% > 开仓0.3%`
- [X] T035 [US4] 在spread/spread_arb_bot.py的_process_holding_state()中集成SmartCloseStrategy
- [X] T036 [US4] 在spread/spread_arb_bot.py中，开仓成功后调用smart_close_strategy.add_position()添加仓位记录
- [X] T037 [US4] 在spread/spread_arb_bot.py的_process_closing_state()中，平仓成功后调用smart_close_strategy.close_all()

**Checkpoint**: 此时，User Story 4应该完全功能正常且可独立测试

---

## Phase 7: User Story 5 - 仓位平衡检测与保护 (Priority: P2)

**目标**: 开仓后验证两边仓位平衡，不平衡时立即平仓保护

**独立测试**: 执行开仓后模拟不平衡情况，验证检测和保护机制

### Implementation for User Story 5

- [X] T038 [P] [US5] 创建spread/position_balance_checker.py类，实现PositionBalanceChecker核心逻辑
- [X] T039 [P] [US5] 在spread/position_balance_checker.py中实现verify_balance()方法（查询两个交易所的仓位数量）
- [X] T040 [P] [US5] 在spread/position_balance_checker.py中实现start_monitoring()方法（异步缓冲期监控）
- [X] T041 [P] [US5] 在spread/position_balance_checker.py中实现单行日志输出：`仓位平衡: Ext 0.01 / Lig 0.01` 或 `仓位不平衡: Ext 0.01 != Lig 0.005，紧急平仓`
- [X] T042 [P] [US5] 在spread/position_balance_checker.py中实现紧急平仓逻辑（检测到不平衡时立即调用trade_executor平仓）
- [X] T043 [US5] 在spread/position_balance_checker.py中处理一侧交易所失败的情况（立即平仓另一侧）
- [X] T044 [US5] 在spread/spread_arb_bot.py的_process_opening_state()中集成PositionBalanceChecker
- [X] T045 [US5] 在spread/spread_arb_bot.py中，开仓后启动balance_checker.start_monitoring()，等待缓冲期验证
- [X] T046 [US5] 在spread/spread_arb_bot.py中，验证通过后才将状态切换到HOLDING
- [X] T047 [US5] 更新spread/spread_arb_bot.py的命令行参数解析，添加--balance-buffer参数支持

**Checkpoint**: 此时，User Story 5应该完全功能正常且可独立测试

---

## Phase 8: User Story 6 - 统一Taker交易模式 (Priority: P3)

**目标**: 所有套利交易使用taker模式，确保即时执行

**独立测试**: 执行开仓和平仓操作，验证订单以taker方式提交

### Implementation for User Story 6

- [X] T048 [P] [US6] 在spread/trade_executor.py中创建taker模式的订单价格计算逻辑（买入用ask+tick，卖出用bid-tick）
- [X] T049 [P] [US6] 修改spread/trade_executor.py的execute_open_position()方法，移除post_only参数
- [X] T050 [P] [US6] 修改spread/trade_executor.py的execute_close_position()方法，使用对手价确保即时成交
- [X] T051 [US6] 在spread/trade_executor.py中添加taker成交日志标注
- [X] T052 [US6] 验证与exchanges/extended.py和exchanges/lighter.py的兼容性（确保taker订单能正确提交）

**Checkpoint**: 此时，User Story 6应该完全功能正常且可独立测试

---

## Phase 9: Polish & Cross-Cutting Concerns

**目的**: 完善功能、优化性能、处理边界情况

- [ ] T053 添加程序重启时的状态恢复逻辑（从state.json恢复cached_open_spread和Portfolio）
- [ ] T054 实现WebSocket连接断开时的优雅处理和自动重连
- [ ] T055 [P] 添加价差在阈值附近剧烈波动时的保护逻辑（避免频繁开仓）
- [ ] T056 [P] 添加交易所API返回延迟或超时时的处理逻辑
- [ ] T057 [P] 添加状态文件的校验和备份机制
- [ ] T058 实现市场极端价格（暴涨暴跌）时的资金保护机制
- [ ] T059 优化性能：确保价差监控延迟<100ms，开仓/平仓决策延迟<200ms
- [ ] T060 更新spread/README.md文档，说明新功能的使用方法
- [ ] T061 创建quickstart参考文档（如果尚未存在）

---

## Dependencies

### User Story Dependencies

```
US1 (日志精简) - 无依赖，可独立实现
US2 (价差监控) - 无依赖，可独立实现
US3 (等差开仓) - 依赖 US2 (需要SpreadMonitor提供价差数据)
US4 (智能平仓) - 依赖 US2, US3 (需要价差数据和仓位记录)
US5 (平衡检测) - 依赖 US1 (需要精简日志输出)
US6 (Taker模式) - 无依赖，可独立实现
```

### Story Completion Order

1. **First (可以并行开始)**: US1, US2, US6
2. **Second**: US3 (等待US2完成)
3. **Third**: US4 (等待US2, US3完成)
4. **Fourth**: US5 (等待US1完成)

---

## Parallel Execution Opportunities

### Phase 1 (Setup) - 并行任务
- T003, T004 可以并行执行（修改同一个文件的不同部分）

### Phase 2 (Foundational) - 并行任务
- T006 可以与 T005 并行执行

### Phase 3 (US1) - 并行任务
- T008, T009 可以并行执行（不同文件）
- T010, T011, T012 可以并行执行（不同文件）

### Phase 4 (US2) - 并行任务
- T013, T014, T015, T016 可以并行执行（不同方法）

### Phase 5 (US3) - 并行任务
- T020, T021, T022, T023 可以并行执行（不同方法）

### Phase 6 (US4) - 并行任务
- T028, T029, T030, T031, T032, T033, T034 可以并行执行（不同方法）

### Phase 7 (US5) - 并行任务
- T038, T039, T040, T041, T042, T043 可以并行执行（不同方法）

### Phase 8 (US6) - 并行任务
- T048, T049, T050, T051 可以并行执行（不同方法）

### Phase 9 (Polish) - 并行任务
- T055, T056, T057 可以并行执行（不同边界情况）

---

## Implementation Strategy

### MVP Scope (建议的首个交付版本)

**MVP = US1 + US2 + US3**

这个组合提供：
- 精简的日志输出（US1）
- 实时价差监控（US2）
- 等差数列开仓策略（US3）

完成后，用户可以：
1. 启动程序并看到清晰的日志
2. 实时监控两个交易所的价差
3. 自动执行等差数列开仓策略

### Incremental Delivery

1. **Sprint 1**: US1 (日志精简) - 1-2天
2. **Sprint 2**: US2 (价差监控) - 2-3天
3. **Sprint 3**: US3 (等差开仓) - 2-3天
4. **Sprint 4**: US4 (智能平仓) - 2-3天
5. **Sprint 5**: US5 (平衡检测) - 2-3天
6. **Sprint 6**: US6 (Taker模式) - 1-2天
7. **Sprint 7**: Polish & Testing - 2-3天

**总估算**: 约15-20个工作日

---

## Task Summary

| 阶段 | 任务数 | 用户故事 |
|------|--------|----------|
| Phase 1: Setup | 4 | 共享基础设施 |
| Phase 2: Foundational | 3 | 阻塞性前置条件 |
| Phase 3: US1 | 5 | 精简日志输出 |
| Phase 4: US2 | 7 | 实时价差监控 |
| Phase 5: US3 | 8 | 等差数列开仓策略 |
| Phase 6: US4 | 10 | 智能平仓系统 |
| Phase 7: US5 | 10 | 仓位平衡检测 |
| Phase 8: US6 | 5 | 统一Taker交易模式 |
| Phase 9: Polish | 9 | 完善和优化 |
| **总计** | **61** | **6个用户故事** |

---

## Format Validation

✅ 所有任务遵循checklist格式：`- [ ] [ID] [P?] [Story] Description`
✅ 所有任务包含确切的文件路径
✅ 用户故事阶段任务包含Story标签（US1, US2, etc.）
✅ Setup和Foundational阶段任务无Story标签
✅ Polish阶段任务无Story标签
✅ 可并行任务标记为[P]
