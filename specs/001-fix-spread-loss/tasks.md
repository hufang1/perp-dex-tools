# Tasks: 价差套利磨损修复

**Input**: Design documents from `/specs/001-fix-spread-loss/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: 本项目需要单元测试和集成测试来验证修复效果。

**Organization**: 任务按用户故事组织，使每个故事可以独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 任务所属用户故事（US1, US2, US3...）
- 描述中包含精确的文件路径

## Path Conventions

本项目是单体Python项目结构：
- `spread/` - 价差套利模块
- `exchanges/` - 交易所客户端
- `tests/` - 测试文件
- `logs/` - 日志目录

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和配置准备

- [x] T001 备份当前版本的spread/calculator.py到spread/calculator.py.backup
- [x] T002 备份当前版本的spread/trade_logger.py到spread/trade_logger.py.backup
- [x] T003 备份当前版本的spread/config.py到spread/config.py.backup
- [x] T004 [P] 创建tests/test_calculator.py空文件框架
- [x] T005 [P] 创建tests/test_maker_taker.py空文件框架
- [x] T006 [P] 创建tests/integration/test_fix_validation.py空文件框架
- [x] T007 [P] 创建logs/目录（如果不存在）

---

## Phase 2: Foundational (阻塞性前置条件)

**目的**: 核心基础设施，必须在任何用户故事实现前完成

**⚠️ 关键**: 此阶段完成前，用户故事工作无法开始

- [x] T008 在spread/config.py添加extended_maker_fee_rate配置项（默认0.0001）
- [x] T009 在spread/config.py添加extended_taker_fee_rate配置项（默认0.000225）
- [x] T010 在spread/config.py添加maker_timeout_seconds配置项（默认5）
- [x] T011 在spread/config.py添加maker_timeout_action配置项（默认"convert_to_taker"）
- [x] T012 在spread/config.py添加use_maker_orders配置项（默认True）
- [x] T013 在spread/config.py的__post_init__方法中验证新配置项
- [x] T014 在spread/spread_pair.py添加open_order_type字段（"MAKER"/"TAKER"）
- [x] T015 在spread/spread_pair.py添加close_order_type字段（"MAKER"/"TAKER"）
- [x] T016 在spread/spread_pair.py添加maker_wait_duration_ms字段
- [x] T017 在spread/spread_pair.py添加open_extended_fee_type字段
- [x] T018 在spread/spread_pair.py添加close_extended_fee_type字段

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 修复套利逻辑根本性错误 (Priority: P1) 🎯 MVP

**目标**: 修复calculator.py中使用错误价格方向的致命bug，确保只在正确条件下开仓

**独立测试**: 运行tests/test_calculator.py验证价差计算正确性，构造测试用例验证做多/做空机会计算

### Tests for User Story 1

> **注意**: 先写这些测试，确保它们在实现前失败

- [x] T019 [P] [US1] 在tests/test_calculator.py编写test_long_opportunity_rejects_when_extended_bid_greater_than_lighter_ask测试
- [x] T020 [P] [US1] 在tests/test_calculator.py编写test_long_opportunity_uses_lighter_ask_price测试
- [x] T021 [P] [US1] 在tests/test_calculator.py编写test_short_opportunity_uses_lighter_bid_price测试
- [x] T022 [P] [US1] 在tests/test_calculator.py编写test_short_opportunity_spread_rate_uses_extended_ask_denominator测试
- [x] T023 [P] [US1] 在tests/test_calculator.py编写test_no_opportunity_when_prices_dont_meet_criteria测试

### Implementation for User Story 1

- [x] T024 [US1] 在spread/calculator.py第62-91行修改做多机会逻辑：条件从`lighter_bid > extended_bid`改为`extended_bid < lighter_ask`
- [x] T025 [US1] 在spread/calculator.py第89行修改做多机会lighter_price从`lighter_bid`改为`lighter_ask`
- [x] T026 [US1] 在spread/calculator.py第93-122行修改做空机会逻辑：条件从`extended_ask > lighter_ask`改为`extended_ask > lighter_bid`
- [x] T027 [US1] 在spread/calculator.py第97行修改做空机会lighter_price从`lighter_ask`改为`lighter_bid`
- [x] T028 [US1] 在spread/calculator.py第97行修改做空价差率分母从`lighter_ask`改为`extended_ask`
- [x] T029 [US1] 在spread/calculator.py更新相关注释说明正确的价格方向
- [x] T030 [US1] 运行pytest tests/test_calculator.py -v验证所有测试通过

**检查点**: 此时User Story 1应完全功能且可独立测试

---

## Phase 4: User Story 2 - 实现Maker/Taker混合下单策略 (Priority: P1)

**目标**: Extended使用maker挂单节省手续费，Lighter使用taker立即对冲，最大化利润

**独立测试**: 运行tests/test_maker_taker.py验证超时机制和成交逻辑

### Tests for User Story 2

- [x] T031 [P] [US2] 在tests/test_maker_taker.py编写test_maker_order_timeout_triggers_taker_conversion测试
- [x] T032 [P] [US2] 在tests/test_maker_taker.py编写test_maker_order_fills_within_timeout测试
- [x] T033 [P] [US2] 在tests/test_maker_taker.py编写test_taker_conversion_logs_timeout_event测试
- [x] T034 [P] [US2] 在tests/test_maker_taker.py编写test_lighter_hedge_uses_counter_price测试

### Implementation for User Story 2

- [x] T035 [US2] 在exchanges/extended.py的place_open_order方法添加post_only参数（默认False）
- [x] T036 [US2] 在exchanges/extended.py修改第259行使用传入的post_only参数而非硬编码False
- [x] T037 [US2] 在spread/order_manager.py的place_spread_maker_order方法添加post_only参数
- [x] T038 [US2] 在spread/order_manager.py修改第84行调用place_open_order时传入post_only参数
- [x] T039 [US2] 在spread/order_manager.py添加maker_timeout_wait方法实现超时等待逻辑
- [x] T040 [US2] 在spread/order_manager.py添加convert_to_taker方法实现转taker逻辑
- [x] T041 [US2] 在spread/bot.py修改第467行调用place_spread_maker_order时传入post_only=True
- [x] T042 [US2] 在spread/bot.py添加maker超时处理逻辑：检测超时后调用convert_to_taker
- [x] T043 [US2] 在spread/hedge_manager.py修改对冲逻辑使用对手价（lighter_bid/ask）
- [x] T044 [US2] 在spread/hedge_manager.py添加深度检查验证Lighter订单簿足够深度
- [x] T045 [US2] 运行pytest tests/test_maker_taker.py -v验证所有测试通过

**检查点**: 此时User Stories 1和2都应独立功能

---

## Phase 5: User Story 3 - 修复价差率计算分母错误 (Priority: P1)

**目标**: 确保做空机会的价差率计算使用正确分母

**注意**: 此任务与US1相关联，已在US1中完成（T028），此处标记为完成

- [x] T046 [US3] 验证T028已完成：spread/calculator.py第97行使用extended_ask作为分母

**检查点**: User Story 3完成（已在US1中实现）

---

## Phase 6: User Story 4 - 收集实际交易数据确定成本结构 (Priority: P2)

**目标**: 运行程序收集实际交易数据，确认真实手续费率和滑点

**独立测试**: 分析logs/trade.log提取手续费和滑点数据

- [ ] T047 [P] [US4] 创建scripts/analyze_logs.py脚本用于解析logs/trade.log
- [ ] T048 [P] [US4] 在scripts/analyze_logs.py实现extract_fees函数提取手续费数据
- [ ] T049 [P] [US4] 在scripts/analyze_logs.py实现extract_slippage函数提取滑点数据
- [ ] T050 [P] [US4] 在scripts/analyze_logs.py实现calculate_maker_fill_rate函数计算maker成交率
- [ ] T051 [US4] 运行修复后的程序1小时收集交易数据
- [ ] T052 [US4] 运行python scripts/analyze_logs.py分析日志数据
- [ ] T053 [US4] 根据分析结果更新spread/config.py中的手续费率配置

**检查点**: User Stories 1-4都应独立功能

---

## Phase 7: User Story 5 - 实现详细交易日志记录 (Priority: P1)

**目标**: 在所有关键环节记录详细数据，统一输出到logs/trade.log，用于后续策略优化

**独立测试**: 运行程序并检查logs/trade.log文件格式和内容完整性

### Tests for User Story 5

- [ ] T054 [P] [US5] 在tests/test_trade_logger.py编写test_log_format_is_valid_json测试
- [ ] T055 [P] [US5] 在tests/test_trade_logger.py编写test_all_event_types_present测试
- [ ] T056 [P] [US5] 在tests/test_trade_logger.py编写test_concurrent_writing_preserves_integrity测试

### Implementation for User Story 5

- [ ] T057 [P] [US5] 在spread/trade_logger.py创建StructuredTradeLogger类
- [ ] T058 [P] [US5] 在spread/trade_logger.py实现log_event方法使用JSON Lines格式
- [ ] T059 [P] [US5] 在spread/trade_logger.py添加线程锁保证并发写入安全
- [ ] T060 [P] [US5] 在spread/trade_logger.py实现log_opening_trade便捷方法
- [ ] T061 [P] [US5] 在spread/trade_logger.py实现log_closing_trade便捷方法
- [ ] T062 [US5] 在spread/trade_logger.py添加SYSTEM_START事件日志记录
- [ ] T063 [US5] 在spread/trade_logger.py添加SPREAD_OPPORTUNITY事件日志记录
- [ ] T064 [US5] 在spread/trade_logger.py添加EXTENDED_ORDER_PLACED事件日志记录
- [ ] T065 [US5] 在spread/trade_logger.py添加EXTENDED_FILLED事件日志记录
- [ ] T066 [US5] 在spread/trade_logger.py添加EXTENDED_MAKER_TIMEOUT事件日志记录
- [ ] T067 [US5] 在spread/trade_logger.py添加LIGHTER_HEDGE事件日志记录
- [ ] T068 [US5] 在spread/trade_logger.py添加POSITION_OPENED事件日志记录
- [ ] T069 [US5] 在spread/trade_logger.py添加POSITION_CLOSED事件日志记录
- [ ] T070 [US5] 在spread/trade_logger.py添加HOURLY_STATISTICS事件日志记录
- [ ] T071 [US5] 在spread/bot.py初始化时调用log_event记录SYSTEM_START
- [ ] T072 [US5] 在spread/bot.py价差检测时调用log_event记录SPREAD_OPPORTUNITY
- [ ] T073 [US5] 在spread/order_manager.py下单时调用log_event记录EXTENDED_ORDER_PLACED
- [ ] T074 [US5] 在spread/order_manager.py成交时调用log_event记录EXTENDED_FILLED
- [ ] T075 [US5] 在spread/order_manager.py超时时调用log_event记录EXTENDED_MAKER_TIMEOUT
- [ ] T076 [US5] 在spread/hedge_manager.py对冲时调用log_event记录LIGHTER_HEDGE
- [ ] T077 [US5] 在spread/bot.py开仓完成时调用log_event记录POSITION_OPENED
- [ ] T078 [US5] 在spread/bot.py平仓完成时调用log_event记录POSITION_CLOSED
- [ ] T079 [US5] 在spread/bot.py添加每小时统计逻辑调用log_event记录HOURLY_STATISTICS
- [ ] T080 [US5] 在spread/spread_pair.py添加to_dict方法用于日志序列化
- [ ] T081 [US5] 运行pytest tests/test_trade_logger.py -v验证所有测试通过
- [ ] T082 [US5] 运行程序1小时后检查logs/trade.log格式完整性

**检查点**: User Stories 1-5都应独立功能

---

## Phase 8: User Story 6 - 增强交易监控日志 (Priority: P2)

**目标**: 添加详细的盈亏追踪日志，帮助实时验证算法是否按预期工作

**独立测试**: 运行程序并检查日志输出格式和内容

- [ ] T083 [P] [US6] 在spread/bot.py添加实时盈亏计算逻辑
- [ ] T084 [P] [US6] 在spread/bot.py添加预期vs实际对比日志输出
- [ ] T085 [US6] 在spread/profit_calculator.py增强手续费明细计算
- [ ] T086 [US6] 在spread/profit_calculator.py增强滑点明细计算
- [ ] T087 [US6] 运行程序验证实时盈亏日志正确输出

**检查点**: User Stories 1-6都应独立功能

---

## Phase 9: User Story 7 - 实现动态价差阈值 (Priority: P3)

**目标**: 根据市场波动性和历史滑点数据，动态调整最小开仓阈值

**独立测试**: 通过模拟市场环境测试阈值动态调整逻辑

- [ ] T088 [P] [US7] 在spread/config.py添加dynamic_threshold_enabled配置项（默认False）
- [ ] T089 [P] [US7] 在spread/config.py添加volatility_window配置项（默认100）
- [ ] T090 [P] [US7] 在spread/calculator.py创建VolatilityTracker类
- [ ] T091 [US7] 在spread/calculator.py实现update_volatility方法
- [ ] T092 [US7] 在spread/calculator.py实现calculate_dynamic_threshold方法
- [ ] T093 [US7] 在spread/bot.py集成动态阈值计算逻辑
- [ ] T094 [US7] 在spread/bot.py添加阈值变化日志记录
- [ ] T095 [US7] 运行程序验证动态阈值正确调整

**检查点**: 所有用户故事现在都应独立功能

---

## Phase 10: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [ ] T096 [P] 更新CLAUDE.md添加001-fix-spread-loss相关技术信息
- [ ] T097 [P] 代码清理：移除调试代码和注释掉的代码
- [ ] T098 [P] 添加日志轮转机制使用RotatingFileHandler（单文件<100MB）
- [ ] T099 [P] 性能优化：异步日志写入避免阻塞交易
- [ ] T100 运行完整测试套件：pytest tests/ -v
- [ ] T101 运行quickstart.md验证步骤
- [ ] T102 运行程序1小时验证净盈亏>0
- [ ] T103 检查logs/trade.log验证所有事件类型正确记录

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可以立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-9)**: 都依赖Foundational阶段完成
  - 用户故事可以并行进行（如果有人力）
  - 或按优先级顺序执行（P1 → P2 → P3）
- **Polish (Phase 10)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 3 (P1)**: 在User Story 1中完成（T028）- 无需额外工作
- **User Story 4 (P2)**: 依赖User Stories 1, 2, 5完成（需要程序运行收集数据）
- **User Story 5 (P1)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 6 (P2)**: 依赖User Story 5完成（增强其日志）
- **User Story 7 (P3)**: 可独立实现，但需要US4的数据作为输入

### Within Each User Story

- 测试必须先写并在实现前失败
- 修改calculator.py的逻辑在更新order_manager.py之前
- 核心实现在集成之前
- 故事完成后再进入下一个优先级

### Parallel Opportunities

- Setup阶段所有标记[P]的任务可以并行
- Foundational阶段T014-T018可以并行（不同字段）
- User Story 1测试（T019-T023）可以并行
- User Story 2测试（T031-T034）可以并行
- User Story 4脚本（T047-T050）可以并行
- User Story 5测试（T054-T056）和基础类（T057-T061）可以并行
- User Story 5事件日志（T062-T070）可以并行
- User Story 6任务（T083-T086）可以并行
- User Story 7任务（T088-T089）和类创建（T090）可以并行
- 不同用户故事可以由不同团队成员并行工作

---

## Parallel Example: User Story 1

```bash
# 一起启动User Story 1的所有测试:
Task: "T019 [P] [US1] 在tests/test_calculator.py编写test_long_opportunity_rejects_when_extended_bid_greater_than_lighter_ask测试"
Task: "T020 [P] [US1] 在tests/test_calculator.py编写test_long_opportunity_uses_lighter_ask_price测试"
Task: "T021 [P] [US1] 在tests/test_calculator.py编写test_short_opportunity_uses_lighter_bid_price测试"
Task: "T022 [P] [US1] 在tests/test_calculator.py编写test_short_opportunity_spread_rate_uses_extended_ask_denominator测试"
Task: "T023 [P] [US1] 在tests/test_calculator.py编写test_no_opportunity_when_prices_dont_meet_criteria测试"
```

---

## Parallel Example: User Story 2

```bash
# 一起启动User Story 2的所有测试:
Task: "T031 [P] [US2] 在tests/test_maker_taker.py编写test_maker_order_timeout_triggers_taker_conversion测试"
Task: "T032 [P] [US2] 在tests/test_maker_taker.py编写test_maker_order_fills_within_timeout测试"
Task: "T033 [P] [US2] 在tests/test_maker_taker.py编写test_taker_conversion_logs_timeout_event测试"
Task: "T034 [P] [US2] 在tests/test_maker_taker.py编写test_lighter_hedge_uses_counter_price测试"
```

---

## Parallel Example: User Story 5

```bash
# 一起启动User Story 5的基础类:
Task: "T057 [P] [US5] 在spread/trade_logger.py创建StructuredTradeLogger类"
Task: "T058 [P] [US5] 在spread/trade_logger.py实现log_event方法使用JSON Lines格式"
Task: "T059 [P] [US5] 在spread/trade_logger.py添加线程锁保证并发写入安全"
Task: "T060 [P] [US5] 在spread/trade_logger.py实现log_opening_trade便捷方法"
Task: "T061 [P] [US5] 在spread/trade_logger.py实现log_closing_trade便捷方法"

# 一起启动User Story 5的所有事件日志:
Task: "T062 [P] [US5] 在spread/trade_logger.py添加SYSTEM_START事件日志记录"
Task: "T063 [P] [US5] 在spread/trade_logger.py添加SPREAD_OPPORTUNITY事件日志记录"
Task: "T064 [P] [US5] 在spread/trade_logger.py添加EXTENDED_ORDER_PLACED事件日志记录"
# ... (T065-T070)
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 完成Phase 1: Setup
2. 完成Phase 2: Foundational（关键 - 阻塞所有故事）
3. 完成Phase 3: User Story 1
4. **停止并验证**: 独立测试User Story 1
5. 如准备好则部署/演示

### Incremental Delivery

1. 完成Setup + Foundational → 基础就绪
2. 添加User Story 1 → 独立测试 → 部署/演示（MVP！）
3. 添加User Story 2 → 独立测试 → 部署/演示
4. 添加User Story 5 → 独立测试 → 部署/演示
5. 添加User Story 4/6 → 独立测试 → 部署/演示
6. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy

有多名开发人员时：

1. 团队一起完成Setup + Foundational
2. Foundational完成后:
   - 开发者A: User Story 1
   - 开发者B: User Story 2
   - 开发者C: User Story 5
3. 故事独立完成并集成

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖

## Summary

- **Total Tasks**: 103
- **Setup (Phase 1)**: 7 tasks
- **Foundational (Phase 2)**: 11 tasks
- **User Story 1**: 12 tasks (5 tests + 7 implementation)
- **User Story 2**: 15 tasks (4 tests + 11 implementation)
- **User Story 3**: 1 task (completed in US1)
- **User Story 4**: 7 tasks
- **User Story 5**: 29 tasks (3 tests + 26 implementation)
- **User Story 6**: 5 tasks
- **User Story 7**: 8 tasks
- **Polish**: 8 tasks

**Parallel Opportunities**: 45 tasks marked [P] can run in parallel with appropriate planning

**Independent Test Criteria**:
- US1: 单元测试验证价差计算正确性
- US2: 单元测试验证超时和成交逻辑
- US3: 在US1中验证
- US4: 日志分析脚本提取数据
- US5: 日志格式和内容完整性检查
- US6: 实时盈亏日志输出
- US7: 动态阈值调整验证

**Suggested MVP Scope**: User Story 1（修复套利逻辑）- 这解决了导致亏损的根本问题
