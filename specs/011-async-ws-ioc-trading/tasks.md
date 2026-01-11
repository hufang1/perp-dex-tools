# Tasks: 高频价差套利系统异步重构

**Input**: Design documents from `/specs/011-async-ws-ioc-trading/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/performance_monitor_api.md

**Tests**: 本项目需要测试（根据Constitution检查的"测试优先"原则）

**Organization**: 任务按用户故事分组，以实现每个故事的独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（US1, US2, US3等）
- 包含描述中的确切文件路径

## Path Conventions

- **Python项目**: `spread/`, `exchanges/`, `tests/` 在仓库根目录
- 本项目是单一Python项目，扩展现有模块

---

## Phase 1: Setup (共享基础设施)

**Purpose**: 项目初始化和基本结构，准备异步重构的开发环境

- [ ] T001 验证Python版本 >= 3.11并安装asyncio和websockets依赖
- [ ] T002 在spread/config.py中添加011-async-ws-ioc-trading配置参数（已部分完成，需要验证完整性）
- [ ] T003 [P] 创建logs/performance.log日志文件配置
- [ ] T004 [P] 创建data/目录并准备CSV导出路径（operations_YYYY_MM_DD.csv, performance_YYYY_MM_DD.csv）

---

## Phase 2: Foundational (阻塞性前置条件)

**Purpose**: 核心基础设施，必须在任何用户故事实现前完成

**⚠️ CRITICAL**: 在此阶段完成前，不能开始任何用户故事工作

- [ ] T005 [P] 在spread/models.py中添加OrderBookSnapshot数据类
- [ ] T006 [P] 在spread/models.py中添加TimingRecord数据类
- [ ] T007 [P] 在spread/models.py中添加DataFreshnessResult数据类
- [ ] T008 [P] 在spread/models.py中添加SlippageCheckResult数据类
- [ ] T009 [P] 在spread/models.py中添加ProfitabilityCheckResult数据类
- [ ] T010 [P] 在spread/models.py中添加TradeOperationRecord数据类
- [ ] T011 在spread/performance_monitor.py中实现PerformanceMonitor类框架（初始化、时间戳记录、统计导出）
- [ ] T012 在spread/performance_monitor.py中实现数据新鲜度检查方法（check_data_freshness, check_both_data_freshness）
- [ ] T013 在spread/performance_monitor.py中实现滑点检查方法（check_slippage）
- [ ] T014 在spread/performance_monitor.py中实现利润率检查方法（check_profitability）
- [ ] T015 在spread/performance_monitor.py中实现决策记录方法（log_opening_decision）
- [ ] T016 配置logging模块添加性能日志输出器（logs/performance.log）

**Checkpoint**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - WebSocket行情接入 (优先级: P0) 🎯 MVP

**Goal**: 实时获取交易所订单簿数据，替代HTTP轮询，消除12秒延迟

**Independent Test**: 连接测试WebSocket并验证数据延迟 < 200ms，数据过期时正确标记STALE

### Tests for User Story 1

- [ ] T017 [P] [US1] 单元测试：WebSocketManager连接管理在tests/test_websocket_manager.py
- [ ] T018 [P] [US1] 单元测试：数据新鲜度检查逻辑在tests/test_performance_monitor.py
- [ ] T019 [P] [US1] 集成测试：WebSocket断线重连在tests/integration/test_websocket_reconnect.py
- [ ] T020 [US1] 端到端测试：WebSocket数据延迟验证在tests/integration/test_ws_latency.py

### Implementation for User Story 1

- [ ] T021 [P] [US1] 在spread/websocket_manager.py中实现WebSocketManager类框架
- [ ] T022 [P] [US1] 在spread/websocket_manager.py中实现connect_extended方法（连接Extended WebSocket）
- [ ] T023 [P] [US1] 在spread/websocket_manager.py中实现connect_lighter方法（连接Lighter WebSocket）
- [ ] T024 [P] [US1] 在spread/websocket_manager.py中实现subscribe_orderbook方法（订阅BookTicker频道）
- [ ] T025 [P] [US1] 在spread/websocket_manager.py中实现订单簿消息处理回调（更新本地缓存）
- [ ] T026 [US1] 在spread/websocket_manager.py中实现心跳保活机制（每30秒ping）
- [ ] T027 [US1] 在spread/websocket_manager.py中实现断线检测和指数退避重连（初始1秒，最大60秒）
- [ ] T028 [US1] 在spread/websocket_manager.py中实现get_orderbook和get_orderbook_timestamp方法（获取本地缓存）
- [ ] T029 [US1] 在exchanges/extended.py中添加WebSocket连接URL和认证方法
- [ ] T030 [US1] 在exchanges/lighter.py中添加WebSocket连接URL和认证方法
- [ ] T031 [US1] 在spread/bot.py中集成WebSocketManager（初始化、连接、订阅）
- [ ] T032 [US1] 在spread/bot.py中添加数据新鲜度检查到价差计算前（使用monitor.check_both_data_freshness）

**Checkpoint**: WebSocket实时行情接入完成，数据延迟 < 200ms可验证

---

## Phase 4: User Story 2 - 双腿并发交易执行 (优先级: P0)

**Goal**: 同时向Extended和Lighter发送订单，时间差 < 5ms，避免12秒串行延迟

**Independent Test**: 验证两个订单发送时间戳差值 < 5ms，单腿成交时1秒内紧急平仓

### Tests for User Story 2

- [ ] T033 [P] [US2] 单元测试：并发执行器时间间隔在tests/test_concurrent_executor.py
- [ ] T034 [P] [US2] 单元测试：超时和异常处理在tests/test_concurrent_executor.py
- [ ] T035 [P] [US2] 单元测试：紧急平仓逻辑在tests/test_concurrent_executor.py
- [ ] T036 [US2] 集成测试：双腿并发下单流程在tests/integration/test_concurrent_orders.py

### Implementation for User Story 2

- [ ] T037 [P] [US2] 在spread/concurrent_executor.py中实现ConcurrentExecutor类框架
- [ ] T038 [P] [US2] 在spread/concurrent_executor.py中实现execute_concurrent_orders方法（使用asyncio.gather）
- [ ] T039 [P] [US2] 在spread/concurrent_executor.py中实现execute_concurrent_close方法（并发平仓）
- [ ] T040 [P] [US2] 在spread/concurrent_executor.py中实现emergency_close_position方法（紧急单腿平仓）
- [ ] T041 [P] [US2] 在spread/concurrent_executor.py中实现并发时间戳记录（send_gap_ms计算）
- [ ] T042 [US2] 在spread/concurrent_executor.py中集成PerformanceMonitor.record_concurrent_send_gap
- [ ] T043 [US2] 在spread/bot.py中将_open_new_pair改为异步方法
- [ ] T044 [US2] 在spread/bot.py中集成ConcurrentExecutor到开仓流程
- [ ] T045 [US2] 在spread/bot.py中实现单腿持仓检测（A成交B失败时触发emergency_close）
- [ ] T046 [US2] 在spread/bot.py中添加asyncio.run主循环入口（保持向后兼容）

**Checkpoint**: 双腿并发交易执行完成，时间差 < 5ms可验证

---

## Phase 5: User Story 3 - IOC限价单机制 (优先级: P0)

**Goal**: 使用IOC订单类型替代市价单，激进限价定价，防止大幅滑点

**Independent Test**: 验证IOC订单在无法成交时自动撤销，部分成交正确记录

### Tests for User Story 3

- [ ] T047 [P] [US3] 单元测试：IOC订单价格计算在tests/test_ioc_order_manager.py
- [ ] T048 [P] [US3] 单元测试：部分成交处理在tests/test_ioc_order_manager.py
- [ ] T049 [P] [US3] 集成测试：IOC订单端到端流程在tests/integration/test_ioc_orders.py

### Implementation for User Story 3

- [ ] T050 [P] [US3] 在spread/ioc_order_manager.py中实现IocOrderManager类框架
- [ ] T051 [P] [US3] 在spread/ioc_order_manager.py中实现calculate_ioc_price方法（激进限价：买入=ask*(1+滑点)，卖出=bid*(1-滑点)）
- [ ] T052 [P] [US3] 在spread/ioc_order_manager.py中实现create_ioc_order方法（设置timeInForce='IOC'）
- [ ] T053 [P] [US3] 在spread/ioc_order_manager.py中实现handle_partial_fill方法（记录实际成交数量）
- [ ] T054 [US3] 在exchanges/extended.py中添加IOC订单支持（timeInForce参数）
- [ ] T055 [US3] 在exchanges/lighter.py中添加IOC订单支持（time_in_force参数）
- [ ] T056 [US3] 在spread/bot.py中集成IocOrderManager到下单流程
- [ ] T057 [US3] 在spread/bot.py中移除maker订单超时等待逻辑（使用config.use_ioc_orders控制）

**Checkpoint**: IOC限价单机制完成，自动撤销行为可验证

---

## Phase 6: User Story 4 - 数据时效性与滑点风控 (优先级: P1)

**Goal**: 开仓前检查数据新鲜度、滑点阈值、利润率，拒绝不合格交易

**Independent Test**: 验证过期数据、过大滑点、不足利润被正确拒绝

### Tests for User Story 4

- [ ] T058 [P] [US4] 单元测试：数据新鲜度验证逻辑在tests/test_risk_validator.py
- [ ] T059 [P] [US4] 单元测试：滑点验证逻辑在tests/test_risk_validator.py
- [ ] T060 [P] [US4] 单元测试：利润率验证逻辑在tests/test_risk_validator.py
- [ ] T061 [US4] 集成测试：开仓前风控流程在tests/integration/test_risk_validation.py

### Implementation for User Story 4

- [ ] T062 [P] [US4] 在spread/risk_validator.py中实现RiskValidator类框架
- [ ] T063 [P] [US4] 在spread/risk_validator.py中实现validate_data_freshness方法（委托PerformanceMonitor）
- [ ] T064 [P] [US4] 在spread/risk_validator.py中实现validate_slippage方法（委托PerformanceMonitor）
- [ ] T065 [P] [US4] 在spread/risk_validator.py中实现validate_profitability方法（委托PerformanceMonitor）
- [ ] T066 [P] [US4] 在spread/risk_validator.py中实现validate_opening方法（综合验证）
- [ ] T067 [P] [US4] 在spread/risk_validator.py中实现check_leg_risk方法（单腿持仓检测）
- [ ] T068 [US4] 在spread/bot.py中集成RiskValidator到开仓流程（在execute_concurrent_orders前调用）
- [ ] T069 [US4] 在spread/performance_monitor.py中添加费率过高警告（双边手续费>0.06%时输出ERROR）
- [ ] T070 [US4] 在spread/performance_monitor.py中添加严重滑点红色高亮警告（滑点>0.2%时）

**Checkpoint**: 数据时效性与滑点风控完成，拒绝逻辑可验证

---

## Phase 7: User Story 5 - 增强日志与可观测性 (优先级: P1)

**Goal**: 记录所有关键时间戳和决策依据，支持CSV导出和性能分析

**Independent Test**: 执行交易并验证日志包含所有必需字段，CSV正确导出

### Tests for User Story 5

- [ ] T071 [P] [US5] 单元测试：时间戳记录完整性在tests/test_performance_monitor.py
- [ ] T072 [P] [US5] 单元测试：CSV导出格式在tests/test_performance_monitor.py
- [ ] T073 [P] [US5] 集成测试：端到端日志记录在tests/integration/test_logging_flow.py

### Implementation for User Story 5

- [ ] T074 [P] [US5] 在spread/performance_monitor.py中实现record_tick_to_trade_latency方法（记录延迟并警告）
- [ ] T075 [P] [US5] 在spread/performance_monitor.py中实现record_execution_latency方法（记录延迟并警告）
- [ ] T076 [P] [US5] 在spread/trade_logger.py中扩展交易日志添加时间戳字段（signal_ts, data_ts_A, data_ts_B, send_ts, ack_ts）
- [ ] T077 [P] [US5] 在spread/performance_monitor.py中实现get_stats_summary方法（统计数据）
- [ ] T078 [P] [US5] 在spread/performance_monitor.py中实现log_stats_summary方法（每分钟输出报告）
- [ ] T079 [P] [US5] 在spread/performance_monitor.py中实现export_performance_data方法（导出最近N分钟数据）
- [ ] T080 [P] [US5] 在spread/performance_monitor.py中实现export_decision_records方法（导出决策记录）
- [ ] T081 [US5] 在spread/performance_monitor.py中实现export_latency_distribution方法（导出延迟分布）
- [ ] T082 [P] [US5] 在spread/performance_monitor.py中实现export_slippage_analysis方法（导出滑点分析）
- [ ] T083 [P] [US5] 在spread/performance_monitor.py中实现export_profitability_analysis方法（导出利润率分析）
- [ ] T084 [US5] 在spread/bot.py中集成时间戳记录到开仓流程（记录signal_ts, send_A_ts, send_B_ts, ack_A_ts, ack_B_ts）
- [ ] T085 [US5] 在spread/bot.py中集成TradeOperationRecord记录和CSV导出（data/operations_YYYY_MM_DD.csv）
- [ ] T086 [US5] 在spread/performance_monitor.py中实现性能数据CSV导出（data/performance_YYYY_MM_DD.csv）

**Checkpoint**: 增强日志与可观测性完成，调试输出完整可验证

---

## Phase 8: User Story 6 - 简化平仓逻辑 (优先级: P2)

**Goal**: 监控净价差变化，使用并发IOC订单快速平仓

**Independent Test**: 验证价差回归时止盈、价差扩大时止损

### Tests for User Story 6

- [ ] T087 [P] [US6] 单元测试：简化平仓条件判断在tests/test_bot.py
- [ ] T088 [P] [US6] 集成测试：平仓流程在tests/integration/test_close_flow.py

### Implementation for User Story 6

- [ ] T089 [P] [US6] 在spread/bot.py中实现_simplified_close_check方法（仅监控净价差）
- [ ] T090 [US6] 在spread/bot.py中实现止盈条件：当前价差 <= 开仓价差 - profit_target_rate
- [ ] T091 [US6] 在spread/bot.py中实现止损条件：当前价差 >= 开仓价差 + stop_loss_threshold_rate
- [ ] T092 [US6] 在spread/bot.py中使用ConcurrentExecutor.execute_concurrent_close执行平仓
- [ ] T093 [US6] 在spread/bot.py中使用IocOrderManager创建平仓IOC订单

**Checkpoint**: 简化平仓逻辑完成，快速平仓可验证

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事改进和最终打磨

- [ ] T094 [P] 更新CLAUDE.md项目文档添加011-async-ws-ioc-trading技术栈和配置说明
- [ ] T095 [P] 代码清理：移除未使用的同步轮询代码（HTTP requests）
- [ ] T096 [P] 添加配置验证：在SpreadArbConfig.__post_init__中验证双边手续费总和 < 0.06%
- [ ] T097 [P] 性能优化：确保时间戳记录开销 < 0.001ms
- [ ] T098 运行所有单元测试和集成测试确保通过
- [ ] T099 运行quickstart.md验证流程（配置、输出、测试）
- [ ] T100 最终文档：更新README.md添加异步重构使用说明

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖Setup完成 - 阻塞所有用户故事
- **User Stories (Phase 3-8)**: 都依赖Foundational阶段完成
  - 用户故事可并行进行（如果有人力）
  - 或按优先级顺序执行（P0 → P1 → P2）
- **Polish (Phase 9)**: 依赖所有期望的用户故事完成

### User Story Dependencies

- **User Story 1 (P0)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P0)**: Foundational完成后可开始 - 可与US1并行
- **User Story 3 (P0)**: Foundational完成后可开始 - 可与US1、US2并行
- **User Story 4 (P1)**: Foundational完成后可开始 - 依赖US1、US2、US3（需要WebSocket、并发执行、IOC订单）
- **User Story 5 (P1)**: 依赖US1、US2、US3、US4（需要完整交易流程才能记录）
- **User Story 6 (P2)**: 依赖US1、US2、US3（需要WebSocket、并发执行、IOC订单）

### Within Each User Story

- 测试必须在实现前编写并失败
- 按模块任务编号顺序执行（T021 → T022 → ...）
- 核心实现在集成之前
- 故事完成后验证再进入下一个

### Parallel Opportunities

- Setup阶段所有[P]任务可并行
- Foundational阶段所有数据类创建（T005-T010）可并行
- US1、US2、US3可在Foundational完成后并行开发
- 每个用户故事内的测试可并行
- 不同用户故事可由不同开发者并行工作

---

## Parallel Example: User Story 1

```bash
# 并行启动User Story 1的所有测试：
Task T017: "WebSocketManager连接管理测试"
Task T018: "数据新鲜度检查测试"
Task T019: "WebSocket断线重连测试"
Task T020: "WebSocket数据延迟验证"

# 并行启动User Story 1的所有WebSocket方法实现：
Task T022: "connect_extended方法"
Task T023: "connect_lighter方法"
Task T024: "subscribe_orderbook方法"
Task T025: "订单簿消息处理回调"
```

---

## Implementation Strategy

### MVP First (User Stories 1-3 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational (CRITICAL - 阻塞所有故事)
3. 完成 Phase 3: User Story 1 (WebSocket行情接入)
4. 完成 Phase 4: User Story 2 (双腿并发交易执行)
5. 完成 Phase 5: User Story 3 (IOC限价单机制)
6. **停止并验证**: 测试核心交易流程独立运行
7. 如果就绪则部署/演示

### Incremental Delivery

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示（实时行情）
3. 添加 User Story 2 → 独立测试 → 部署/演示（并发交易）
4. 添加 User Story 3 → 独立测试 → 部署/演示（IOC订单）
5. 添加 User Story 4 → 独立测试 → 部署/演示（风控检查）
6. 添加 User Story 5 → 独立测试 → 部署/演示（调试输出）
7. 添加 User Story 6 → 独立测试 → 部署/演示（简化平仓）
8. 每个故事增加价值而不破坏之前的故事

### Parallel Team Strategy

多开发者场景：

1. 团队一起完成 Setup + Foundational
2. Foundational完成后：
   - 开发者 A: User Story 1 (WebSocket) + User Story 4 (风控)
   - 开发者 B: User Story 2 (并发) + User Story 6 (平仓)
   - 开发者 C: User Story 3 (IOC) + User Story 5 (日志)
3. 故事独立完成并集成

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应独立可完成和可测试
- 如果需要测试，在实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同一文件冲突、破坏独立性的跨故事依赖

## Summary

- **总任务数**: 100
- **Phase 1 (Setup)**: 4 任务
- **Phase 2 (Foundational)**: 12 任务（阻塞性）
- **Phase 3 (US1 - WebSocket)**: 16 任务
- **Phase 4 (US2 - 并发执行)**: 14 任务
- **Phase 5 (US3 - IOC订单)**: 11 任务
- **Phase 6 (US4 - 风控)**: 13 任务
- **Phase 7 (US5 - 日志)**: 16 任务
- **Phase 8 (US6 - 平仓)**: 7 任务
- **Phase 9 (Polish)**: 7 任务

**并行机会**: 约50%的任务标记为[P]可并行执行

**独立测试标准**: 每个用户故事都有明确的独立验证标准

**建议MVP范围**: User Stories 1-3 (P0优先级) - 核心交易能力
