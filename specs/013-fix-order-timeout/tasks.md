# Tasks: 修复订单执行超时和假阳性成交问题

**Input**: Design documents from `/specs/013-fix-order-timeout/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Note**: This is a bug fix feature for an existing Python project. No setup phase is needed.

---

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Skipped)

**Purpose**: Project initialization and basic structure

**Status**: ⏭️ SKIPPED - Existing project, no setup needed

---

## Phase 2: Foundational (Code Analysis)

**Purpose**: Understand current codebase before making changes

**⚠️ CRITICAL**: Must complete before user story implementation

- [ ] T001 Read and analyze `exchanges/extended.py` `place_open_order()` method (lines 202-342)
- [ ] T002 Read and analyze `exchanges/lighter.py` `place_open_order()` method (lines 315-402)
- [ ] T003 Read and analyze `spread/concurrent_executor.py` logging sections (lines 290-321)
- [ ] T003 [P] Identify `get_order_info()` blocking logic in `exchanges/extended.py` (lines 509-563)
- [ ] T004 [P] Identify `current_order` WebSocket callback in `exchanges/lighter.py` (lines 224-239)
- [ ] T005 [P] Verify `get_inactive_orders()` implementation in `exchanges/lighter.py` (lines 631-653)

**Checkpoint**: Code analysis complete - ready to implement fixes

---

## Phase 3: User Story 1 - Extended订单立即返回不阻塞 (Priority: P1) 🎯 MVP

**Goal**: Extended IOC订单在SDK返回成功后立即返回，不调用阻塞的`get_order_info()`方法

**Independent Test**: Extended IOC订单提交后，系统应在100ms内返回`success=True`且包含有效的`order_id`

### Tests for User Story 1

- [ ] T006 [P] [US1] Create test file `tests/test_extended_fix.py` with test structure
- [ ] T007 [US1] Write test case `test_ioc_order_immediate_return` in `tests/test_extended_fix.py`
- [ ] T008 [US1] Write test case `test_post_only_order_queries_status` in `tests/test_extended_fix.py`
- [ ] T009 [US1] Write test case `test_order_timeout_handling` in `tests/test_extended_fix.py`

### Implementation for User Story 1

- [ ] T010 [US1] Modify `place_open_order()` in `exchanges/extended.py` (line 297-309): Add IOC order immediate return logic
- [ ] T011 [US1] Add debug log `[DEBUG] IOC订单已提交，立即返回成功` in `exchanges/extended.py` (line 301)
- [ ] T012 [US1] Ensure Post-Only orders still call `get_order_info()` in `exchanges/extended.py` (line 311-314)
- [ ] T013 [US1] Verify `order_id` is not None when returning `success=True` in `exchanges/extended.py` (line 302-308)

**Checkpoint**: Extended IOC订单在100ms内返回，不再超时

---

## Phase 4: User Story 2 - Lighter订单状态验证 (Priority: P1)

**Goal**: Lighter订单只有当`order_id`存在时才返回`success=True`

**Independent Test**: Lighter订单完成后，如果`order_id=None`应返回`success=False`

### Tests for User Story 2

- [ ] T014 [P] [US2] Create test file `tests/test_lighter_fix.py` with test structure
- [ ] T015 [US2] Write test case `test_order_id_none_returns_failure` in `tests/test_lighter_fix.py`
- [ ] T016 [US2] Write test case `test_order_id_exists_returns_success` in `tests/test_lighter_fix.py`
- [ ] T017 [US2] Write test case `test_api_fallback_verification` in `tests/test_lighter_fix.py`

### Implementation for User Story 2

- [ ] T018 [US2] Modify `place_open_order()` in `exchanges/lighter.py` (line 335-352): Add `order_id` validation logic
- [ ] T019 [US2] Add warning log `[警告] current_order存在但order_id为None` in `exchanges/lighter.py` (line 349-351)
- [ ] T020 [US2] Ensure `get_inactive_orders()` is called when `order_id=None` in `exchanges/lighter.py` (line 351-402)
- [ ] T021 [US2] Verify `success=False` when `current_order.order_id is None` in `exchanges/lighter.py` (line 335-346)

**Checkpoint**: Lighter不再返回`success=True, order_id=None`

---

## Phase 5: User Story 3 - 增强错误日志诊断 (Priority: P2)

**Goal**: 订单执行失败时，日志应显示详细的失败原因

**Independent Test**: 任何订单执行失败时，日志应包含交易所名称、成功状态、订单ID、错误消息

### Tests for User Story 3

- [ ] T022 [P] [US3] Create test file `tests/test_enhanced_error_logging.py` with test structure
- [ ] T023 [US3] Write test case `test_single_leg_logging_with_error_details` in `tests/test_enhanced_error_logging.py`
- [ ] T024 [US3] Write test case `test_both_failed_logging_with_error_details` in `tests/test_enhanced_error_logging.py`

### Implementation for User Story 3

- [ ] T025 [US3] Modify single-leg logging in `spread/concurrent_executor.py` (line 300-312): Add error message fields
- [ ] T026 [US3] Modify both-failed logging in `spread/concurrent_executor.py` (line 313-321): Add error message fields
- [ ] T027 [US3] Ensure log format includes `success, order_id, error` for both exchanges in `spread/concurrent_executor.py` (line 307-311, 317-320)

**Checkpoint**: 所有失败日志显示具体错误原因

---

## Phase 6: Integration Tests

**Purpose**: End-to-end validation of all fixes together

- [ ] T028 [P] Create integration test file `tests/integration/test_order_timeout_fix_integration.py`
- [ ] T029 [P] Write test case `test_both_orders_succeed` in `tests/integration/test_order_timeout_fix_integration.py`
- [ ] T030 [P] Write test case `test_both_orders_fail_no_legging` in `tests/integration/test_order_timeout_fix_integration.py`
- [ ] T031 [P] Write test case `test_true_legging_triggers_rollback` in `tests/integration/test_order_timeout_fix_integration.py`

**Checkpoint**: 集成测试全部通过

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and documentation

- [ ] T032 [P] Run all unit tests: `pytest tests/test_extended_fix.py tests/test_lighter_fix.py -v`
- [ ] T033 [P] Run integration tests: `pytest tests/integration/test_order_timeout_fix_integration.py -v`
- [ ] T034 Verify Extended IOC订单响应时间 < 100ms in local testing
- [ ] T035 Verify Lighter不再出现`success=True, order_id=None` in local testing
- [ ] T036 Verify 单腿持仓误报率 = 0% in local testing
- [ ] T037 [P] Update CLAUDE.md with 013-fix-order-timeout entry (if applicable)
- [ ] T038 Update feature-summary.md (if exists) with completion status

**Checkpoint**: 功能完整，通过所有验证

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: Skipped - existing project
- **Phase 2 (Foundational)**: No dependencies - code analysis only
- **Phase 3-5 (User Stories)**: Can proceed in parallel after Phase 2 (different files)
- **Phase 6 (Integration)**: Depends on Phase 3-5 completion
- **Phase 7 (Polish)**: Depends on all implementation phases complete

### User Story Dependencies

- **User Story 1 (Extended fix)**: Independent - can complete after Phase 2
- **User Story 2 (Lighter fix)**: Independent - can complete after Phase 2
- **User Story 3 (Logging fix)**: Independent - can complete after Phase 2

### Within Each User Story

- Tests MUST be written before implementation (TDD approach)
- Test file creation [P] can run in parallel with test case writing
- Implementation tasks follow test completion
- Integration tests wait for all user story fixes

### Parallel Opportunities

All Phase 3-5 user stories can proceed in parallel (different files):

```bash
# User Story 1 (Extended) - can run independently:
T006-T010: exchanges/extended.py

# User Story 2 (Lighter) - can run independently:
T014-T018: exchanges/lighter.py

# User Story 3 (Logging) - can run independently:
T022-T025: spread/concurrent_executor.py
```

---

## Parallel Example: User Story 1 (Extended Fix)

```bash
# Launch all test file creation and test case writing together (parallel):
Task T006: Create test file tests/test_extended_fix.py
Task T007: Write test case test_ioc_order_immediate_return
Task T008: Write test case test_post_only_order_queries_status
Task T009: Write test case test_order_timeout_handling

# After tests complete, implement fix:
Task T010: Modify place_open_order() with IOC immediate return logic
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: Code Analysis (T001-T005)
2. Complete Phase 3: User Story 1 (T006-T013)
3. **STOP and VALIDATE**: Test Extended fix independently
4. Verify Extended IOC orders no longer timeout

### Incremental Delivery

1. Phase 2 (Foundational) → Code analysis complete
2. Phase 3 (US1) → Extended fix → Test independently → Verify
3. Phase 4 (US2) → Lighter fix → Test independently → Verify
4. Phase 5 (US3) → Logging fix → Test independently → Verify
5. Phase 6 (Integration) → All fixes together → Validate
6. Phase 7 (Polish) → Final validation and documentation

### Parallel Team Strategy

With multiple developers (if available):

1. Team completes Phase 2 (Foundational) together
2. Once Phase 2 done:
   - Developer A: User Story 1 (Extended fix)
   - Developer B: User Story 2 (Lighter fix)
   - Developer C: User Story 3 (Logging fix)
3. Fixes complete and integrate independently
4. Integration tests validate all fixes together

---

## Task Summary

| Phase | Task Count | Description |
|-------|-----------|-------------|
| Phase 1 | 0 | Skipped (existing project) |
| Phase 2 | 5 | Code analysis and understanding |
| Phase 3 (US1) | 8 | Extended IOC timeout fix |
| Phase 4 (US2) | 8 | Lighter order_id validation fix |
| Phase 5 (US3) | 6 | Enhanced error logging |
| Phase 6 | 4 | Integration tests |
| Phase 7 | 7 | Validation and polish |
| **Total** | **38** | All tasks |

---

## Success Criteria

After completing all tasks:

- ✅ Extended IOC订单在100ms内返回
- ✅ Lighter不再返回`success=True, order_id=None`
- ✅ 所有失败日志显示具体错误原因
- ✅ 单腿持仓误报率 = 0%
- ✅ 订单执行成功率 > 90%
- ✅ 所有单元测试通过
- ✅ 所有集成测试通过

---

## Notes

- [P] tasks = different files, no dependencies
- [US1], [US2], [US3] labels map task to specific user story
- User stories are independently completable (different files)
- Tests written first (TDD approach)
- Stop at any checkpoint to validate story independently
- Files modified: `exchanges/extended.py`, `exchanges/lighter.py`, `spread/concurrent_executor.py`
- Files created: `tests/test_extended_fix.py`, `tests/test_lighter_fix.py`, `tests/test_enhanced_error_logging.py`, `tests/integration/test_order_timeout_fix_integration.py`
