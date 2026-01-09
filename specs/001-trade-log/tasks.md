# Tasks: Trade Logging for Arbitrage Verification

**Input**: Design documents from `/specs/001-trade-log/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/trade-logger-interface.md

**Tests**: Tests are included as this is a financial application requiring verification.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `spread/`, `tests/` at repository root
- Paths shown below match the project structure from plan.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create `spread/trade_logger.py` module file with class stub and docstring
- [X] T002 Create `tests/test_trade_logger.py` test file with pytest imports
- [X] T003 [P] Create `tests/integration/test_trade_logging.py` integration test file

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Implement TradeLogger.__init__() in spread/trade_logger.py with logger setup, directory creation, and FileHandler configuration
- [X] T005 [P] Implement helper methods get_log_file_path() and get_log_stats() in spread/trade_logger.py
- [X] T006 Add error handling wrapper in TradeLogger for graceful failure (try-except, console fallback)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Trade Activity Logging (Priority: P1) 🎯 MVP

**Goal**: Automatically log every opening and closing trade action to `logs/trade.log` with complete trade details (timestamp, pair ID, direction, prices, quantities, order IDs, spread)

**Independent Test**: Run the arbitrage system through one complete open/close cycle and verify that detailed log entries are created in `logs/trade.log` containing all required trade information (FR-001, FR-002, FR-003, FR-006)

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T007 [P] [US1] Unit test for log_opening_trade() in tests/test_trade_logger.py - verify all required fields (timestamp, pair_id, direction, exchange details, spread) are written correctly
- [X] T008 [P] [US1] Unit test for log_closing_trade() in tests/test_trade_logger.py - verify all required fields (timestamp, pair_id, closing prices, quantities, order IDs) are written correctly
- [X] T009 [P] [US1] Unit test for automatic log file creation in tests/test_trade_logger.py - verify logs/ directory and trade.log file are created if they don't exist
- [X] T010 [P] [US1] Integration test for opening trade logging in tests/integration/test_trade_logging.py - run full trade open and verify log entry is created with correct format
- [X] T011 [P] [US1] Integration test for closing trade logging in tests/integration/test_trade_logging.py - run full trade close and verify log entry is created with correct format

### Implementation for User Story 1

- [X] T012 [US1] Implement log_opening_trade() method in spread/trade_logger.py - format and write opening entry with all required fields (FR-003)
- [X] T013 [US1] Implement log_closing_trade() method in spread/trade_logger.py - format and write closing entry with all required fields (FR-004)
- [X] T014 [US1] Import TradeLogger in spread/bot.py and instantiate in SpreadArbitrageBot.__init__() with log_file_path="logs/trade.log"
- [X] T015 [US1] Integrate log_opening_trade() call in spread/bot.py _open_new_pair() method after line 533 (after successful pair creation)
- [X] T016 [US1] Integrate log_closing_trade() call in spread/bot.py _close_pair() method after line 628 (after PnL calculation and stats update)
- [X] T017 [US1] Add error handling for logging failures in spread/bot.py - emit warning but continue trading (FR-008, SC-005)

**Checkpoint**: At this point, User Story 1 should be fully functional - test by running a complete trade cycle and verifying logs/trade.log contains opening and closing entries with all required fields

---

## Phase 4: User Story 2 - Calculation Verification (Priority: P2)

**Goal**: Include complete step-by-step PnL calculation in closing log entries so operators can manually verify the calculation logic

**Independent Test**: Examine a closing log entry and manually verify that each step of the PnL calculation (Extended PnL + Lighter PnL = Total PnL) is clearly documented and mathematically correct for both LONG and SHORT positions

### Tests for User Story 2

- [X] T018 [P] [US2] Unit test for LONG position PnL calculation in tests/test_trade_logger.py - verify formula shows (close_price - open_price) × quantity for Extended and (open_price - close_price) × quantity for Lighter
- [X] T019 [P] [US2] Unit test for SHORT position PnL calculation in tests/test_trade_logger.py - verify formula shows (open_price - close_price) × quantity for Extended and (close_price - open_price) × quantity for Lighter

### Implementation for User Story 2

- [X] T020 [US2] Update log_closing_trade() method in spread/trade_logger.py to add PnL calculation breakdown section with Extended PnL formula and value, Lighter PnL formula and value, and Total PnL sum (FR-005)
- [X] T021 [US2] Add direction-specific formula formatting in spread/trade_logger.py - LONG uses (close - open), SHORT uses (open - close) for Extended PnL

**Checkpoint**: At this point, User Stories 1 AND 2 should both work - closing logs now show step-by-step PnL calculations

---

## Phase 5: User Story 3 - Human-Readable Format (Priority: P3)

**Goal**: Format log entries in a clear, human-readable way with labeled fields, consistent structure, and proper delimiters so operators can quickly understand trade details without special tools

**Independent Test**: Open logs/trade.log in a text editor and verify entries are clearly formatted with labeled fields (e.g., "Extended Open Price: $3450.50"), clear delimiters between entries, and proper currency formatting

### Tests for User Story 3

- [X] T022 [P] [US3] Unit test for opening entry format in tests/test_trade_logger.py - verify field labels, currency symbols, decimal formatting, and visual delimiters
- [X] T023 [P] [US3] Unit test for closing entry format in tests/test_trade_logger.py - verify field labels, currency symbols, decimal formatting, and visual delimiters
- [X] T024 [P] [US3] Unit test for multiple entries in tests/test_trade_logger.py - verify clear delimiters between entries for easy parsing

### Implementation for User Story 3

- [X] T025 [US3] Add visual formatting helpers in spread/trade_logger.py - create format_section_header(), format_field_label(), format_currency_value() helper methods
- [X] T026 [US3] Update log_opening_trade() method in spread/trade_logger.py to use formatted output with section headers ("=== TRADE OPENED ==="), labeled fields, currency symbols ($), and decimal precision (2 for prices, 4 for quantities)
- [X] T027 [US3] Update log_closing_trade() method in spread/trade_logger.py to use formatted output with section headers ("=== TRADE CLOSED ==="), labeled fields, currency symbols, decimal precision, and clear entry delimiters
- [X] T028 [US3] Add visual separator line (=====================) at end of each entry in spread/trade_logger.py

**Checkpoint**: All user stories should now be independently functional - logs are human-readable with clear formatting

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Edge cases, error handling, and documentation improvements

- [X] T029 [P] Implement log_unhedged_position() method in spread/trade_logger.py - format and write warning entry for unhedged positions with all required details (edge case from spec)
- [X] T030 [P] Integrate log_unhedged_position() call in spread/bot.py _open_new_pair() method after line 500 (after hedge failure detection)
- [X] T031 [P] Unit test for error handling in tests/test_trade_logger.py - test permission denied, disk full, directory creation failure scenarios
- [X] T032 [P] Unit test for concurrent writes in tests/test_trade_logger.py - verify thread-safety with multiple simultaneous log calls
- [X] T033 [P] Unit test for log_unhedged_position() in tests/test_trade_logger.py - verify warning entry format and all required fields
- [X] T034 Update CLAUDE.md in repository root with trade logging feature information (add to "Recent Changes" section)
- [ ] T035 Update quickstart.md in specs/001-trade-log/ if needed based on implementation details discovered
- [ ] T036 Run quickstart.md validation - test manual verification workflow by opening logs/trade.log and verifying format matches quickstart examples

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2 → P3)
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories - **MVP SCOPE**
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Extends US1 closing log format - Should complete after US1
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Enhances formatting from US1 and US2 - Should complete after US1 and US2

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Core methods before bot integration
- Bot integration before error handling
- Story complete before moving to next priority

### Parallel Opportunities

- **Setup Phase**: T002 and T003 can run in parallel
- **Foundational Phase**: T005 can run in parallel with T004/T006
- **User Story 1 Tests**: T007, T008, T009, T010, T011 can all run in parallel
- **User Story 2 Tests**: T018 and T019 can run in parallel
- **User Story 3 Tests**: T022, T023, T024 can all run in parallel
- **Polish Phase**: T029, T031, T032, T033 can run in parallel (different test files)
- **User Stories**: Once Foundational phase completes, US1, US2, US3 could theoretically be worked on in parallel (though sequential is recommended due to dependencies)

---

## Parallel Example: User Story 1 Tests

```bash
# Launch all tests for User Story 1 together after T006 completes:
Task: "Unit test for log_opening_trade() in tests/test_trade_logger.py"
Task: "Unit test for log_closing_trade() in tests/test_trade_logger.py"
Task: "Unit test for automatic log file creation in tests/test_trade_logger.py"
Task: "Integration test for opening trade logging in tests/integration/test_trade_logging.py"
Task: "Integration test for closing trade logging in tests/integration/test_trade_logging.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T006) - CRITICAL
3. Complete Phase 3: User Story 1 (T007-T017)
4. **STOP and VALIDATE**: Test User Story 1 independently by running a trade cycle and verifying logs
5. Deploy/demo if ready - basic trade logging is now functional

### Incremental Delivery

1. Complete Setup + Foundational (T001-T006) → Foundation ready
2. Add User Story 1 (T007-T017) → Test independently → **MVP COMPLETE** - trades are logged
3. Add User Story 2 (T018-T021) → Test independently → PnL calculations now visible in logs
4. Add User Story 3 (T022-T028) → Test independently → Logs are now human-readable and polished
5. Add Polish (T029-T036) → Complete feature with edge cases and documentation

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001-T006)
2. Once Foundational is done:
   - Developer A: User Story 1 (T007-T017) - Core logging functionality
   - Developer B: User Story 2 (T018-T021) - PnL calculation display (after US1)
   - Developer C: User Story 3 (T022-T028) - Formatting polish (after US1/US2)
3. All developers contribute to Polish phase (T029-T036)

---

## Task Summary

**Total Tasks**: 36

**By Phase**:
- Phase 1 (Setup): 3 tasks
- Phase 2 (Foundational): 3 tasks
- Phase 3 (User Story 1 - MVP): 11 tasks
- Phase 4 (User Story 2): 4 tasks
- Phase 5 (User Story 3): 7 tasks
- Phase 6 (Polish): 8 tasks

**By User Story**:
- User Story 1 (Trade Activity Logging): 11 tasks (T007-T017)
- User Story 2 (Calculation Verification): 4 tasks (T018-T021)
- User Story 3 (Human-Readable Format): 7 tasks (T022-T028)

**Parallel Opportunities Identified**: 15 tasks marked [P] can run in parallel with others in their phase

**MVP Scope**: Phases 1-3 (Tasks T001-T017) = 17 tasks for core trade logging functionality

**Independent Test Criteria**:
- US1: Run trade cycle, verify logs/trade.log has opening and closing entries with all fields
- US2: Examine closing entry, verify PnL calculation steps are clear and correct
- US3: View logs/trade.log in text editor, verify formatting is clear and human-readable

---

## Notes

- [P] tasks = different files, no dependencies, can run in parallel
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD approach)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- This feature modifies existing files (spread/bot.py) - use care when integrating
- Log file (logs/trade.log) is created automatically - no manual setup required
- All logging failures are graceful - trading continues even if logging breaks (FR-008, SC-005)
