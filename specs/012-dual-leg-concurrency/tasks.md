# Tasks: 双腿并发交易重构

**Input**: Design documents from `/specs/012-dual-leg-concurrency/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md

**Tests**: Tests are included as this feature requires validation for performance-critical trading operations.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `spread/` for source code, `tests/` for tests, `exchanges/` for exchange clients
- All paths are relative to repository root: `/Users/hufang/Desktop/web3 project/perp/hufangperp/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and configuration updates

- [X] T001 [P] Add concurrent execution configuration fields to spread/config.py (enable_dual_leg_concurrent, concurrent_order_send_threshold_ms)
- [X] T002 [P] Add IOC order configuration fields to spread/config.py (ioc_slippage_tolerance_rate, ioc_slippage_min_rate, ioc_slippage_max_rate)
- [X] T003 [P] Add leg rollback configuration fields to spread/config.py (enable_leg_rollback, rollback_timeout_ms, rollback_max_retries)
- [X] T004 [P] Add simple close configuration fields to spread/config.py (enable_simple_close, simple_close_target_profit_rate, simple_close_stop_loss_rate)
- [X] T005 [P] Add profit check configuration fields to spread/config.py (enable_enhanced_profit_check, min_net_profit_rate, expected_slippage_cost_rate)
- [X] T006 Add validate_ioc_slippage() method to SpreadArbConfig class in spread/config.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data models that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 Add ConcurrentOrderResult dataclass to spread/models.py (fields: extended_success, lighter_success, send_gap_ms, total_latency_ms, is_both_filled, is_legging, is_both_failed)
- [X] T008 Add LegRollbackEvent dataclass to spread/models.py (fields: trigger_time, legging_side, rollback_latency_ms, rollback_success, exposure_time_ms, is_within_sla() method)
- [X] T009 Add SimpleCloseDecision dataclass to spread/models.py (fields: open_spread_rate, current_spread_rate, should_close, close_reason, calculate_decision() method)
- [X] T010 Add concurrent_result, rollback_event, simple_close_decision fields to SpreadPair class in spread/spread_pair.py

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - 双腿并发下单执行 (Priority: P1) 🎯 MVP

**Goal**: 实现双腿并发下单，发送时间差<5ms，总执行时间<500ms

**Independent Test**: 模拟订单响应验证并发执行，测量发送时间差<5ms，总执行时间<500ms

### Tests for User Story 1

- [ ] T011 [P] [US1] Write test_concurrent_send_gap_under_5ms in tests/test_dual_leg_concurrent.py
- [ ] T012 [P] [US1] Write test_both_filled_success in tests/test_dual_leg_concurrent.py
- [ ] T013 [P] [US1] Write test_execution_latency_under_500ms in tests/test_dual_leg_concurrent.py

### Implementation for User Story 1

- [ ] T014 [US1] Add create_dual_leg_orders() method to IocOrderManager in spread/ioc_order_manager.py (returns tuple of extended/lighter order dicts with timeInForce/time_in_force parameters)
- [ ] T015 [US1] Add handle_partial_fill() method to IocOrderManager in spread/ioc_order_manager.py (detects partial fills, logs warnings)
- [ ] T016 [US1] Add execute_dual_leg_orders() method to ConcurrentExecutor in spread/concurrent_executor.py (uses asyncio.gather, records send_A_ts/send_B_ts, returns ConcurrentOrderResult)
- [ ] T017 [US1] Add get_filled_ratio() method to ConcurrentOrderResult in spread/models.py (calculates extended/lighter fill ratios)
- [ ] T018 [US1] Integrate IocOrderManager.create_dual_leg_orders() in bot._open_new_pair() in spread/bot.py (replace current order creation logic)
- [ ] T019 [US1] Integrate ConcurrentExecutor.execute_dual_leg_orders() in bot._open_new_pair() in spread/bot.py (use concurrent execution instead of serial)
- [ ] T020 [US1] Remove wait_for_fill() calls from spread/order_manager.py (no longer needed with IOC orders)
- [ ] T021 [US1] Add performance logging for send_gap_ms in spread/bot.py (warn if > 5ms)
- [ ] T022 [US1] Add performance logging for total_latency_ms in spread/bot.py (warn if > 500ms)

**Checkpoint**: At this point, User Story 1 should be fully functional - concurrent order execution with <5ms send gap and <500ms total latency

---

## Phase 4: User Story 2 - IOC订单机制与滑点容错 (Priority: P1)

**Goal**: 使用IOC订单替代限价单，滑点容错0.03%-0.05%

**Independent Test**: 模拟不同价格波动场景验证IOC定价和成交行为

### Tests for User Story 2

- [ ] T023 [P] [US2] Write test_ioc_buy_price_calculation in tests/test_ioc_order_pricing.py (verifies: buy_price = ask * (1 + slippage))
- [ ] T024 [P] [US2] Write test_ioc_sell_price_calculation in tests/test_ioc_order_pricing.py (verifies: sell_price = bid * (1 - slippage))
- [ ] T025 [P] [US2] Write test_slippage_tolerance_range in tests/test_ioc_order_pricing.py (verifies 0.03%-0.05% range)
- [ ] T026 [P] [US2] Write test_extended_ioc_time_in_force in tests/test_ioc_order_pricing.py (verifies timeInForce parameter)
- [ ] T027 [P] [US2] Write test_lighter_ioc_time_in_force in tests/test_ioc_order_pricing.py (verifies time_in_force parameter)

### Implementation for User Story 2

- [ ] T028 [US2] Implement calculate_ioc_price() in spread/ioc_order_manager.py (buy: ask*(1+slippage), sell: bid*(1-slippage))
- [ ] T029 [US2] Update create_ioc_order() in spread/ioc_order_manager.py to use Extended timeInForce parameter
- [ ] T030 [US2] Update create_ioc_order() in spread/ioc_order_manager.py to use Lighter time_in_force parameter (underscore naming)
- [ ] T031 [US2] Add slippage range validation to SpreadArbConfig.validate_ioc_slippage() in spread/config.py
- [ ] T032 [US2] Remove convert_to_taker logic from spread/order_manager.py (IOC orders don't need conversion)
- [ ] T033 [US2] Set post_only=False in all IOC orders in spread/ioc_order_manager.py
- [ ] T034 [US2] Add logging for IOC order creation with slippage details in spread/ioc_order_manager.py

**Checkpoint**: At this point, User Story 2 should be fully functional - IOC orders with proper slippage pricing

---

## Phase 5: User Story 3 - 单腿成交快速回滚 (Priority: P1)

**Goal**: 单腿持仓1秒内市价平仓，消除风险敞口

**Independent Test**: 模拟一边交易所失败响应验证1秒内回滚

### Tests for User Story 3

- [ ] T035 [P] [US3] Write test_detect_legging_extended_filled in tests/test_leg_rollback.py
- [ ] T036 [P] [US3] Write test_detect_legging_lighter_filled in tests/test_leg_rollback.py
- [ ] T037 [P] [US3] Write test_rollback_under_1s in tests/test_leg_rollback.py
- [ ] T038 [P] [US3] Write test_rollback_retry_on_failure in tests/test_leg_rollback.py
- [ ] T039 [P] [US3] Write test_rollback_logs_critical_marker in tests/test_leg_rollback.py

### Implementation for User Story 3

- [ ] T040 [P] [US3] Create spread/leg_rollback_handler.py with LegRollbackHandler class
- [ ] T041 [US3] Implement detect_legging() method in spread/leg_rollback_handler.py (checks ConcurrentOrderResult for single-side fill)
- [ ] T042 [US3] Implement execute_emergency_close() method in spread/leg_rollback_handler.py (uses MARKET or extreme limit price, max 3 retries)
- [ ] T043 [US3] Add critical logging "[CRITICAL] Legging detected, rolling back position" in spread/leg_rollback_handler.py
- [ ] T044 [US3] Implement is_within_sla() method in LegRollbackEvent in spread/models.py (checks rollback_latency_ms <= 1000)
- [ ] T045 [US3] Integrate LegRollbackHandler.detect_legging() in bot._open_new_pair() after ConcurrentExecutor in spread/bot.py
- [ ] T046 [US3] Integrate LegRollbackHandler.execute_emergency_close() in bot._open_new_pair() when legging detected in spread/bot.py
- [ ] T047 [US3] Store LegRollbackEvent in SpreadPair.rollback_event in spread/bot.py
- [ ] T048 [US3] Add rollback performance monitoring to spread/performance_monitor.py

**Checkpoint**: At this point, User Story 3 should be fully functional - legging detection and <1s emergency rollback

---

## Phase 6: User Story 4 - 利润风控检查 (Priority: P1)

**Goal**: 开仓前严格验证净利，拒绝负利润交易

**Independent Test**: 不同价差率和费率组合验证利润检查逻辑

### Tests for User Story 4

- [ ] T049 [P] [US4] Write test_profit_check_reject_negative in tests/test_profit_check.py
- [ ] T050 [P] [US4] Write test_profit_check_accept_positive in tests/test_profit_check.py
- [ ] T051 [P] [US4] Write test_profit_check_warn_high_fees in tests/test_profit_check.py
- [ ] T052 [P] [US4] Write test_profit_check_fee_calculation in tests/test_profit_check.py

### Implementation for User Story 4

- [ ] T053 [US4] Update validate_profitability() in spread/risk_validator.py with enhanced formula (net_profit = spread - fees - slippage - min_profit)
- [ ] T054 [US4] Add fee rate warning when total > 0.06% in spread/risk_validator.py
- [ ] T055 [US4] Add detailed profit breakdown logging in spread/risk_validator.py (spread rate, fees, slippage, net profit)
- [ ] T056 [US4] Integrate validate_profitability() in bot._open_new_pair() before order creation in spread/bot.py
- [ ] T057 [US4] Add "利润不足" rejection logging when net_profit < 0 in spread/bot.py
- [ ] T058 [US4] Update ProfitabilityCheckResult in spread/models.py with detailed breakdown fields

**Checkpoint**: At this point, User Story 4 should be fully functional - profit validation prevents negative expected value trades

---

## Phase 7: User Story 5 - 数据时效性熔断 (Priority: P2)

**Goal**: 检查订单簿时间戳，超过500ms放弃交易

**Independent Test**: 模拟不同延迟的数据更新验证熔断机制

### Tests for User Story 5

- [ ] T059 [P] [US5] Write test_data_freshness_accept_under_500ms in tests/test_data_freshness.py
- [ ] T060 [P] [US5] Write test_data_freshness_reject_over_500ms in tests/test_data_freshness.py
- [ ] T061 [P] [US5] Write test_data_freshness_both_exchanges in tests/test_data_freshness.py

### Implementation for User Story 5

- [ ] T062 [US5] Verify check_data_freshness() exists in spread/risk_validator.py (from 011-async-ws-ioc-trading)
- [ ] T063 [US5] Verify max_data_age_ms = 500 is configured in spread/config.py
- [ ] T064 [US5] Integrate check_data_freshness() in bot._strategy_loop() before calculate_spread in spread/bot.py
- [ ] T065 [US5] Add "数据过期" warning logging when data_age > 500ms in spread/bot.py

**Checkpoint**: At this point, User Story 5 should be fully functional - stale data rejected at 500ms threshold

---

## Phase 8: User Story 6 - 极简平仓逻辑 (Priority: P2)

**Goal**: 简化平仓决策，基于净价差止盈止损，移除P1-P5复杂系统

**Independent Test**: 模拟价差变化验证平仓触发条件

### Tests for User Story 6

- [ ] T066 [P] [US6] Write test_simple_close_take_profit in tests/test_simple_close.py
- [ ] T067 [P] [US6] Write test_simple_close_stop_loss in tests/test_simple_close.py
- [ ] T068 [P] [US6] Write test_simple_close_hold in tests/test_simple_close.py
- [ ] T069 [P] [US6] Write test_simple_close_concurrent_execution in tests/test_simple_close.py

### Implementation for User Story 6

- [ ] T070 [P] [US6] Create spread/simple_close_strategy.py with SimpleCloseStrategy class
- [ ] T071 [US6] Implement should_close() method in spread/simple_close_strategy.py (checks take_profit and stop_loss conditions)
- [ ] T072 [US6] Implement calculate_decision() method in SimpleCloseDecision in spread/models.py
- [ ] T073 [US6] Implement execute_close() method in spread/simple_close_strategy.py (uses ConcurrentExecutor with IOC)
- [ ] T074 [US6] Integrate SimpleCloseStrategy.should_close() in bot._monitor_pairs() in spread/bot.py
- [ ] T075 [US6] Remove P1-P5 priority logic from bot._check_close_conditions() in spread/bot.py
- [ ] T076 [US6] Remove holding_time > 300s logic from bot._monitor_pairs() in spread/bot.py
- [ ] T077 [US6] Store SimpleCloseDecision in SpreadPair.simple_close_decision in spread/bot.py

**Checkpoint**: At this point, User Story 6 should be fully functional - simplified closing based on net spread only

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Integration, testing, and documentation

- [ ] T078 [P] Write end-to-end integration test in tests/integration/test_dual_leg_integration.py (test_end_to_end_dual_leg_trade)
- [ ] T079 [P] Write integration test for legging rollback flow in tests/integration/test_dual_leg_integration.py (test_legging_rollback_flow)
- [ ] T080 Add exception class ConcurrentExecutionError to spread/models.py
- [ ] T081 Add exception class LegRollbackError to spread/models.py
- [ ] T082 Add exception class IOCOrderError to spread/models.py
- [ ] T083 Add exception class ProfitabilityError to spread/models.py
- [ ] T084 Update CLAUDE.md with new modules (LegRollbackHandler, SimpleCloseStrategy, concurrent execution)
- [ ] T085 Run pytest tests/test_dual_leg_concurrent.py and verify all pass
- [ ] T086 Run pytest tests/test_ioc_order_pricing.py and verify all pass
- [ ] T087 Run pytest tests/test_leg_rollback.py and verify all pass
- [ ] T088 Run pytest tests/test_profit_check.py and verify all pass
- [ ] T089 Run pytest tests/test_data_freshness.py and verify all pass
- [ ] T090 Run pytest tests/test_simple_close.py and verify all pass
- [ ] T091 Run pytest tests/integration/test_dual_leg_integration.py and verify all pass
- [ ] T092 Verify performance metrics: send_gap_ms < 5ms in logs/performance.log
- [ ] T093 Verify performance metrics: total_latency_ms < 500ms in logs/performance.log
- [ ] T094 Verify performance metrics: rollback_latency_ms < 1000ms in logs/performance.log
- [ ] T095 Validate quickstart.md instructions work correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-8)**: All depend on Foundational phase completion
  - User stories US1-US4 (P1) should be completed first as they are MVP-critical
  - User stories US5-US6 (P2) can proceed after P1 stories or in parallel if team capacity allows
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P1)**: Can start after Foundational (Phase 2) - Extends US1 IOC order creation but independently testable
- **User Story 3 (P1)**: Can start after Foundational (Phase 2) - Depends on US1 ConcurrentOrderResult
- **User Story 4 (P1)**: Can start after Foundational (Phase 2) - Independent of other stories
- **User Story 5 (P2)**: Can start after Foundational (Phase 2) - Independent of other stories
- **User Story 6 (P2)**: Can start after Foundational (Phase 2) - Independent of other stories

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD approach)
- Models before services
- Services before integration
- Core implementation before logging/monitoring
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks (T001-T006) can run in parallel
- All Foundational tasks (T007-T010) can run in parallel (different files)
- Once Foundational phase completes, all user stories can start in parallel (if team capacity allows)
- All tests within a user story marked [P] can run in parallel
- All integration tests in Phase 9 can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task T011: "test_concurrent_send_gap_under_5ms"
Task T012: "test_both_filled_success"
Task T013: "test_execution_latency_under_500ms"

# After tests pass, launch implementation tasks:
Task T014: "create_dual_leg_orders in IocOrderManager"
Task T015: "handle_partial_fill in IocOrderManager"
```

---

## Implementation Strategy

### MVP First (User Stories 1-4)

1. Complete Phase 1: Setup (T001-T006)
2. Complete Phase 2: Foundational (T007-T010) - CRITICAL
3. Complete Phase 3: User Story 1 - Concurrent execution (T011-T022)
4. Complete Phase 4: User Story 2 - IOC orders (T023-T034)
5. Complete Phase 5: User Story 3 - Leg rollback (T035-T048)
6. Complete Phase 6: User Story 4 - Profit check (T049-T058)
7. **STOP and VALIDATE**: Test P1 stories independently
8. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 (Concurrent) → Test → MVP core functionality
3. Add User Story 2 (IOC) → Test → Enhanced order mechanism
4. Add User Story 3 (Rollback) → Test → Risk mitigation
5. Add User Story 4 (Profit) → Test → Profitability guard
6. Add User Story 5 (Data freshness) → Test → Data quality
7. Add User Story 6 (Simple close) → Test → Simplified closing
8. Polish & integrate

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 + 2 (Order execution)
   - Developer B: User Story 3 (Rollback)
   - Developer C: User Story 4 (Profit check)
3. After P1 stories complete:
   - Developer A: User Story 5 (Data freshness)
   - Developer B: User Story 6 (Simple close)
4. All converge for Phase 9 integration and testing

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Tests use TDD approach: write failing tests first, then implement
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Performance-critical: All P1 stories must meet latency targets (<5ms, <500ms, <1s)
