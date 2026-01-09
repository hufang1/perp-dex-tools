# Tasks: Unified Configuration Management

**Input**: Design documents from `/specs/004-unify-config/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests are included as the specification requires configuration validation testing and this is a refactoring that needs verification.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: Repository root with `spread/`, `hedge/`, `exchanges/`, `tests/` modules
- Config files: `spread/config.py`, `hedge/config.py`, `trading_config.py` (root)
- Run scripts: `spread/run_spread_arb.py`, `hedge_mode.py`, `runbot.py`
- Tests: `tests/test_config_*.py`, `tests/integration/test_*.py`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create feature branch `004-unify-config` and verify clean working directory
- [X] T002 Review current configuration files: `spread/config.py`, `spread/run_spread_arb.py`, `hedge_mode.py`, `runbot.py`
- [X] T003 [P] Create tests directory structure: `tests/`, `tests/integration/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Add `env_file` field to existing `SpreadArbConfig` dataclass in `spread/config.py` with default value `'.env'`
- [X] T005 Add module-level `config = SpreadArbConfig()` instance creation at end of `spread/config.py`
- [X] T006 [P] Create `hedge/config.py` file with `HedgeConfig` dataclass containing all hedge mode parameters
- [X] T007 [P] Add module-level `config = HedgeConfig()` instance creation at end of `hedge/config.py`
- [X] T008 [P] Create `trading_config.py` file at project root with `TradingConfig` dataclass containing all trading bot parameters
- [X] T009 [P] Add module-level `config = TradingConfig()` instance creation at end of `trading_config.py`
- [X] T010 Add `from_env()` classmethod to `HedgeConfig` in `hedge/config.py` for environment variable overrides
- [X] T011 Add `from_env()` classmethod to `TradingConfig` in `trading_config.py` for environment variable overrides
- [X] T012 Add `__post_init__()` validation method to `HedgeConfig` in `hedge/config.py` with validation rules from contracts/config-schema.yaml
- [X] T013 Add `__post_init__()` validation method to `TradingConfig` in `trading_config.py` with validation rules from contracts/config-schema.yaml

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Single Configuration File for Spread Arbitrage (Priority: P1) 🎯 MVP

**Goal**: Enable spread arbitrage bot to run entirely from `spread/config.py` without command-line arguments

**Independent Test**: Run `python spread/run_spread_arb.py` without arguments and verify all parameters are read from `spread/config.py`

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T014 [P] [US1] Create unit test for SpreadArbConfig instantiation in `tests/test_config_loading.py`
- [ ] T015 [P] [US1] Create unit test for SpreadArbConfig validation in `tests/test_config_validation.py`
- [ ] T016 [P] [US1] Create integration test for spread bot startup in `tests/integration/test_bot_config.py`

### Implementation for User Story 1

- [X] T017 [US1] Remove `parse_arguments()` function from `spread/run_spread_arb.py`
- [X] T018 [US1] Remove all argparse imports and related code from `spread/run_spread_arb.py`
- [X] T019 [US1] Replace argparse-based config creation with `from spread.config import config` in `spread/run_spread_arb.py`
- [X] T020 [US1] Update `main()` function in `spread/run_spread_arb.py` to use `config.env_file` instead of args.env_file
- [X] T021 [US1] Update `main()` function in `spread/run_spread_arb.py` to pass `config` to SpreadArbitrageBot instead of creating new instance
- [X] T022 [US1] Update `setup_logging()` function in `spread/run_spread_arb.py` to use `config.log_level` instead of args.log_level
- [X] T023 [US1] Remove global `args` variable usage from `spread/run_spread_arb.py`
- [X] T024 [US1] Test spread bot startup: `python spread/run_spread_arb.py` and verify it uses config.py values

**Checkpoint**: At this point, User Story 1 should be fully functional - spread bot runs from config.py only

---

## Phase 4: User Story 2 - Single Configuration File for Hedge Mode (Priority: P1)

**Goal**: Enable hedge mode bot to run entirely from `hedge/config.py` with only `--exchange` argument required

**Independent Test**: Run `python hedge_mode.py --exchange edgex` and verify all other parameters are read from `hedge/config.py`

### Tests for User Story 2

- [ ] T025 [P] [US2] Create unit test for HedgeConfig instantiation in `tests/test_config_loading.py`
- [ ] T026 [P] [US2] Create unit test for HedgeConfig validation in `tests/test_config_validation.py`
- [ ] T027 [P] [US2] Create integration test for hedge mode startup in `tests/integration/test_bot_config.py`

### Implementation for User Story 2

- [X] T028 [US2] Modify `parse_arguments()` in `hedge_mode.py` to keep only `--exchange`, `--v2` arguments
- [X] T029 [US2] Remove all other argparse arguments from `hedge_mode.py`: `--ticker`, `--size`, `--iter`, `--fill-timeout`, `--sleep`, `--env-file`, `--max-position`
- [X] T030 [US2] Import `config` from `hedge.config` at top of `hedge_mode.py`
- [X] T031 [US2] Replace argparse-based parameter passing with `config` values in hedge bot instantiation
- [X] T032 [US2] Update `main()` function in `hedge_mode.py` to use `config.env_file` for dotenv.load_dotenv()
- [X] T033 [US2] Handle v2 bot instantiation with config parameters in `hedge_mode.py`
- [X] T034 [US2] Handle backpack/edgex/nado/grvt bot instantiation with config parameters in `hedge_mode.py`
- [X] T035 [US2] Handle apex/extended bot instantiation with config parameters in `hedge_mode.py`
- [X] T036 [US2] Test hedge mode startup: `python hedge_mode.py --exchange edgex` and verify it uses config.py values

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Single Configuration File for Trading Bot (Priority: P1)

**Goal**: Enable trading bot to run entirely from `trading_config.py` without command-line arguments

**Independent Test**: Run `python runbot.py` without arguments and verify all parameters are read from `trading_config.py`

### Tests for User Story 3

- [ ] T037 [P] [US3] Create unit test for TradingConfig instantiation in `tests/test_config_loading.py`
- [ ] T038 [P] [US3] Create unit test for TradingConfig validation in `tests/test_config_validation.py`
- [ ] T039 [P] [US3] Create integration test for trading bot startup in `tests/integration/test_bot_config.py`

### Implementation for User Story 3

- [X] T040 [US3] Remove `parse_arguments()` function from `runbot.py`
- [X] T041 [US3] Remove all argparse imports and related code from `runbot.py`
- [X] T042 [US3] Replace argparse-based config creation with `from trading_config import config` in `runbot.py`
- [X] T043 [US3] Update `main()` function in `runbot.py` to use `config.env_file` instead of args.env_file
- [X] T044 [US3] Update `main()` function in `runbot.py` to pass `config` to TradingBot instead of creating new instance
- [X] T045 [US3] Update `setup_logging()` function call in `runbot.py` to use `config` values
- [X] T046 [US3] Remove boost mode validation from argparse, now handled in TradingConfig.__post_init__()
- [X] T047 [US3] Test trading bot startup: `python runbot.py` and verify it uses trading_config.py values

**Checkpoint**: All three user stories should now be independently functional

---

## Phase 6: User Story 4 - Environment File Selection (Priority: P2)

**Goal**: Support multiple account configuration via `env_file` parameter in config files

**Independent Test**: Set `env_file='.env.account1'` in config.py and verify correct credentials are loaded

### Tests for User Story 4

- [ ] T048 [P] [US4] Create unit test for env_file loading in `tests/test_config_loading.py`
- [ ] T049 [P] [US4] Create integration test for multiple account switching in `tests/integration/test_bot_config.py`

### Implementation for User Story 4

- [ ] T050 [US4] Update `spread/run_spread_arb.py` to pass `config.env_file` to `dotenv.load_dotenv()`
- [ ] T051 [US4] Update `hedge_mode.py` to pass `config.env_file` to `dotenv.load_dotenv()`
- [ ] T052 [US4] Update `runbot.py` to pass `config.env_file` to `dotenv.load_dotenv()`
- [ ] T053 [US4] Create example `.env.account1` and `.env.production` file templates in project root
- [ ] T054 [US4] Test multiple account switching by modifying config.env_file and running each bot

**Checkpoint**: Environment file selection now works across all three bots

---

## Phase 7: User Story 5 - Configuration Validation and Error Messages (Priority: P2)

**Goal**: Provide clear error messages for invalid configuration values

**Independent Test**: Set invalid values in config.py and verify helpful error messages are displayed

### Tests for User Story 5

- [ ] T055 [P] [US5] Create unit test for negative min_spread_rate validation error in `tests/test_config_validation.py`
- [ ] T056 [P] [US5] Create unit test for max_holding_time < time_close_threshold validation error in `tests/test_config_validation.py`
- [ ] T057 [P] [US5] Create unit test for invalid exchange validation error in `tests/test_config_validation.py`
- [ ] T058 [P] [US5] Create unit test for boost_mode with invalid exchange validation error in `tests/test_config_validation.py`

### Implementation for User Story 5

- [ ] T059 [US5] Verify all validation rules in `SpreadArbConfig.__post_init__()` produce clear error messages in `spread/config.py`
- [ ] T060 [US5] Verify all validation rules in `HedgeConfig.__post_init__()` produce clear error messages in `hedge/config.py`
- [ ] T061 [US5] Verify all validation rules in `TradingConfig.__post_init__()` produce clear error messages in `trading_config.py`
- [ ] T062 [US5] Add validation error handling with user-friendly messages in each bot's main() function
- [ ] T063 [US5] Test validation by setting invalid values and verifying error messages

**Checkpoint**: All configuration validation provides clear, actionable error messages

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T064 [P] Update CLAUDE.md with unified configuration approach in section "Configuration Management"
- [ ] T065 [P] Create example configuration files with comments: `spread/config.example.py`, `hedge/config.example.py`, `trading_config.example.py`
- [ ] T066 [P] Add docstrings to all configuration classes explaining usage and from_env() method
- [ ] T067 Run all test suites: `pytest tests/test_config_*.py tests/integration/test_bot_config.py -v`
- [ ] T068 Verify quickstart.md examples work for all three bots
- [ ] T069 Create git commit with all changes for feature branch `004-unify-config`
- [ ] T070 Update CLAUDE.md Recent Changes section with feature 004-unify-config entry

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-7)**: All depend on Foundational phase completion
  - User Stories 1, 2, 3 (P1) can proceed in parallel after Foundational
  - User Stories 4, 5 (P2) depend on P1 stories being complete
- **Polish (Phase 8)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1) - Spread Arbitrage**: Can start after Foundational - No dependencies on other stories
- **User Story 2 (P1) - Hedge Mode**: Can start after Foundational - No dependencies on other stories
- **User Story 3 (P1) - Trading Bot**: Can start after Foundational - No dependencies on other stories
- **User Story 4 (P2) - Environment File Selection**: Depends on US1, US2, US3 (all three bots need env_file support)
- **User Story 5 (P2) - Validation**: Depends on US1, US2, US3 (all config classes need validation)

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD approach)
- Tests for different config classes can run in parallel
- Implementation tasks must follow sequential order within each story
- Story complete before moving to next priority (if working sequentially)

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- All Foundational tasks marked [P] can run in parallel (T006, T007, T008; T010, T011; T012, T013)
- Once Foundational phase completes, all P1 user stories (US1, US2, US3) can start in parallel
- All tests for a user story marked [P] can run in parallel
- Different user stories can be worked on in parallel by different team members
- US4 and US5 can run in parallel after P1 stories are complete

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Create unit test for SpreadArbConfig instantiation in tests/test_config_loading.py"
Task: "Create unit test for SpreadArbConfig validation in tests/test_config_validation.py"
Task: "Create integration test for spread bot startup in tests/integration/test_bot_config.py"
```

---

## Parallel Example: Foundational Phase

```bash
# Create all three config files in parallel:
Task: "Create hedge/config.py file with HedgeConfig dataclass"
Task: "Create trading_config.py file with TradingConfig dataclass"
Task: "Add env_file field to existing SpreadArbConfig dataclass"

# Add from_env() methods in parallel:
Task: "Add from_env() classmethod to HedgeConfig"
Task: "Add from_env() classmethod to TradingConfig"

# Add validation in parallel:
Task: "Add __post_init__() validation to HedgeConfig"
Task: "Add __post_init__() validation to TradingConfig"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only - P1 Critical)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (Spread Arbitrage)
4. **STOP and VALIDATE**: Test spread bot runs from config.py only
5. Deploy/demo if ready

**MVP Value**: Core user pain point solved - spread arbitrage works from single config file

### Incremental Delivery (All P1 Stories)

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 (Spread) → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 (Hedge) → Test independently → Deploy/Demo
4. Add User Story 3 (Trading Bot) → Test independently → Deploy/Demo
5. Each story adds value without breaking previous stories

### Full Feature Delivery (All Stories)

1. Complete MVP (P1 stories above)
2. Add User Story 4 (Environment File Selection) → Multi-account support
3. Add User Story 5 (Validation) → Better error messages
4. Polish phase → Documentation and examples
5. Complete feature ready for production

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (Spread)
   - Developer B: User Story 2 (Hedge)
   - Developer C: User Story 3 (Trading Bot)
3. After P1 stories complete:
   - Developer A: User Story 4 (Environment)
   - Developer B: User Story 5 (Validation)
4. Team converges for Polish phase

---

## Summary

**Total Tasks**: 70 tasks

**Tasks by User Story**:
- Setup: 3 tasks
- Foundational: 10 tasks
- User Story 1 (Spread): 11 tasks (3 tests + 8 implementation)
- User Story 2 (Hedge): 12 tasks (3 tests + 9 implementation)
- User Story 3 (Trading Bot): 11 tasks (3 tests + 8 implementation)
- User Story 4 (Environment): 7 tasks (2 tests + 5 implementation)
- User Story 5 (Validation): 9 tasks (4 tests + 5 implementation)
- Polish: 7 tasks

**Parallel Opportunities Identified**:
- Setup: 2 tasks can run in parallel
- Foundational: 6 tasks can run in parallel
- User Story 1: 3 tests can run in parallel
- User Story 2: 3 tests can run in parallel
- User Story 3: 3 tests can run in parallel
- User Story 4: 2 tests can run in parallel
- User Story 5: 4 tests can run in parallel
- Polish: 3 tasks can run in parallel

**Independent Test Criteria**:
- US1: `python spread/run_spread_arb.py` works without arguments
- US2: `python hedge_mode.py --exchange edgex` works with only exchange arg
- US3: `python runbot.py` works without arguments
- US4: Modifying `env_file` in config switches .env file used
- US5: Invalid config values produce clear error messages

**Suggested MVP Scope**: Phase 1 (Setup) + Phase 2 (Foundational) + Phase 3 (User Story 1 - Spread Arbitrage)

This delivers the core value proposition: one bot running entirely from config.py without command-line arguments.

---

## Format Validation

✅ All tasks follow the required checklist format:
- Checkbox: `- [ ]` present on all tasks
- Task ID: Sequential T001-T070 present on all tasks
- [P] marker: Applied to parallelizable tasks
- [Story] label: Applied to all user story phase tasks (US1-US5)
- File paths: Included in all task descriptions
- Setup/Foundational/Polish phases: No story labels (as required)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Tests are written FIRST (TDD approach) to ensure they fail before implementation
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
