# Implementation Plan: Trade Logging for Arbitrage Verification

**Branch**: `001-trade-log` | **Date**: 2026-01-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-trade-log/spec.md`

## Summary

Add detailed trade logging to the spread arbitrage system to enable operators to verify calculated profits against actual exchange positions. The system will automatically log all opening and closing trades to `logs/trade.log` with complete price details, order IDs, and step-by-step PnL calculations in a human-readable format.

**Technical Approach**: Create a new `TradeLogger` module using Python's built-in `logging` framework for thread-safe, atomic writes. Integrate into existing `SpreadArbitrageBot` class at trade opening and closing points. No changes to trading logic or data structures.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: Python `logging` module (built-in), existing `SpreadPair` class
**Storage**: Append-only text file (`logs/trade.log`)
**Testing**: pytest (existing framework)
**Target Platform**: Linux/macOS server (where arbitrage bot runs)
**Project Type**: Single project (spread arbitrage bot)
**Performance Goals**: <5ms per log entry, zero trading interruptions
**Constraints**: Thread-safe writes, graceful failure handling (never block trading)
**Scale/Scope**: <10,000 trades/day (~3 MB/day), single-machine deployment

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: ✅ PASSED

The project constitution file (`.specify/memory/constitution.md`) is currently a template without specific principles defined. Based on standard software development practices:

- ✅ **No new dependencies**: Uses Python built-in `logging` module
- ✅ **Minimal complexity**: Single new module, no architectural changes
- ✅ **Backward compatible**: No changes to existing trading logic or data structures
- ✅ **Testable**: Clear inputs/outputs, unit and integration testable
- ✅ **Observable**: Human-readable log format for verification

No violations to justify. Feature aligns with simplicity and observability principles.

## Project Structure

### Documentation (this feature)

```text
specs/001-trade-log/
├── spec.md              # Feature specification
├── plan.md              # This file (implementation plan)
├── research.md          # Phase 0: Technology decisions and rationale
├── data-model.md        # Phase 1: Log entry data structures
├── quickstart.md        # Phase 1: User guide for trade verification
├── contracts/           # Phase 1: Interface contracts
│   └── trade-logger-interface.md
└── checklists/
    └── requirements.md  # Quality validation checklist
```

### Source Code (repository root)

```text
spread/
├── __init__.py           # Existing module init
├── bot.py                # MODIFY: Integrate TradeLogger
├── spread_pair.py        # READ: Access trade data
├── order_manager.py      # UNCHANGED: Used by bot
├── hedge_manager.py      # UNCHANGED: Used by bot
├── calculator.py         # UNCHANGED: Used by bot
├── config.py             # UNCHANGED: Configuration
└── trade_logger.py       # NEW: Trade logging module

tests/
├── test_trade_logger.py         # NEW: Unit tests for TradeLogger
└── integration/
    └── test_trade_logging.py    # NEW: Integration tests

logs/                        # NEW: Created automatically
└── trade.log                # NEW: Human-readable trade records
```

**Structure Decision**: Single project structure matches existing codebase. New `trade_logger.py` module placed in `spread/` directory alongside related modules. No structural changes to existing code.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

N/A - No constitution violations. Feature is intentionally simple:
- Single new module with clear responsibility
- No architectural changes
- No new dependencies
- No data structure modifications
- No trading logic changes

## Phase 0: Research (Complete)

**Output**: [research.md](research.md)

### Key Decisions

1. **Logging Framework**: Python's built-in `logging` module
   - Thread-safe by default
   - Already used throughout codebase
   - No external dependencies

2. **Log Format**: Human-readable structured text
   - Meets requirement for manual verification without tools
   - Clear field labels prevent ambiguity
   - Step-by-step PnL calculations visible

3. **Error Handling**: Never block trading
   - Try-except with console fallback
   - Logging failures emit errors but continue execution
   - Meets SC-005: Zero trading interruptions

4. **Atomic Writes**: Handled by `logging.FileHandler`
   - Built-in thread safety via locks
   - No interleaved entries from concurrent trades
   - Meets FR-009

### Integration Analysis

**SpreadPair Class**: Read-only access to existing trade data
- No data structure changes needed
- All required fields already present

**Bot Class**: Integration at two points
- `_open_new_pair()`: Log after successful opening
- `_close_pair()`: Log after successful closing
- Unhedged position detection: Log warning

## Phase 1: Design (Complete)

### Data Model

**Output**: [data-model.md](data-model.md)

**Log Entry Types**:
1. **Opening Trade Entry**: Records when position established
2. **Closing Trade Entry**: Records when position closed with PnL calculation
3. **Unhedged Position Warning**: Records when hedge fails

**Key Fields**:
- Timestamp, Pair ID, Direction (LONG/SHORT)
- Exchange details: Order ID, Price, Quantity (both exchanges)
- Spread information (opening) or PnL calculation (closing)

### Interface Contract

**Output**: [contracts/trade-logger-interface.md](contracts/trade-logger-interface.md)

**TradeLogger Class**:
```python
class TradeLogger:
    def __init__(self, log_file_path: str = "logs/trade.log")
    def log_opening_trade(self, pair: SpreadPair) -> bool
    def log_closing_trade(self, pair: SpreadPair) -> bool
    def log_unhedged_position(self, position: Dict) -> bool
    def get_log_file_path(self) -> str
    def get_log_stats(self) -> Dict
```

**Integration Points**:
- `SpreadArbitrageBot.__init__()`: Instantiate logger
- `SpreadArbitrageBot._open_new_pair()`: Call `log_opening_trade()` after line 533
- `SpreadArbitrageBot._close_pair()`: Call `log_closing_trade()` after line 628
- Unhedged detection: Call `log_unhedged_position()` after line 500

### User Documentation

**Output**: [quickstart.md](quickstart.md)

**Contents**:
- How logging works automatically
- Log file location and format
- Manual verification workflow
- Troubleshooting common issues
- Best practices for log review

## Phase 2: Implementation Tasks (Next)

**Note**: This phase is executed by the `/speckit.tasks` command, not `/speckit.plan`.

### Anticipated Task Breakdown

1. **Create TradeLogger Module** (`spread/trade_logger.py`)
   - Initialize logger with file handler
   - Implement `log_opening_trade()` method
   - Implement `log_closing_trade()` method
   - Implement `log_unhedged_position()` method
   - Add error handling (try-except, console fallback)

2. **Integrate into Bot** (`spread/bot.py`)
   - Import TradeLogger
   - Instantiate in `__init__()`
   - Call `log_opening_trade()` after successful opening
   - Call `log_closing_trade()` after successful closing
   - Call `log_unhedged_position()` on hedge failure

3. **Create Unit Tests** (`tests/test_trade_logger.py`)
   - Test opening trade logging (all fields)
   - Test closing trade logging (PnL calculation)
   - Test unhedged position logging
   - Test file creation when directory doesn't exist
   - Test error handling (permission denied, disk full)
   - Test concurrent write safety

4. **Create Integration Tests** (`tests/integration/test_trade_logging.py`)
   - Test full trade cycle (open + close)
   - Verify log file location
   - Verify log format is human-readable
   - Test with mock exchanges

5. **Update Documentation**
   - Update CLAUDE.md with trade logging info
   - Add logging section to bot documentation
   - Verify quickstart.md accuracy

## Dependencies

### Internal Dependencies

- `spread/spread_pair.py`: Read trade data (SpreadPair class)
- `spread/bot.py`: Integrate logging at trade events

### External Dependencies

- Python 3.11+ `logging` module (built-in)
- Python 3.11+ `pathlib` module (built-in, for file paths)

### No New Dependencies Required

All functionality uses Python standard library.

## Risk Assessment

### Low Risk

- **No trading logic changes**: Logging is non-invasive
- **No new dependencies**: Uses built-in modules
- **Graceful degradation**: Logging failures don't stop trading
- **Thread-safe**: Python logging handles concurrency

### Mitigation Strategies

1. **Log Size**: Monitor file size in stats reporter, add warning when approaching threshold
2. **Disk Space**: Check available space on startup, emit warning if low
3. **Permissions**: Create directory with proper permissions, handle errors gracefully
4. **Performance**: Log writes are <5ms, negligible compared to trading latency

## Success Metrics

### Functional Success

- ✅ 100% of trades logged (opening and closing)
- ✅ All required fields present in log entries
- ✅ PnL calculations clearly documented
- ✅ Human-readable format (verified by manual review)
- ✅ Zero trading interruptions from logging failures

### Non-Functional Success

- ✅ Log writes <5ms per entry
- ✅ Thread-safe (no interleaved entries)
- ✅ Error handling graceful (console fallback)
- ✅ File created automatically if missing

### User Success

- ✅ Operators can verify trades in <5 minutes
- ✅ Discrepancies detectable by comparing logs to exchanges
- ✅ No special tools required to read logs

## Next Steps

1. ✅ **Phase 0 Complete**: Research decisions documented in [research.md](research.md)
2. ✅ **Phase 1 Complete**: Design artifacts created (data-model, contracts, quickstart)
3. ⏭️ **Phase 2 Pending**: Run `/speckit.tasks` to generate implementation tasks
4. ⏭️ **Implementation Pending**: Run `/speckit.implement` to execute tasks

**Ready to proceed**: All design artifacts complete. No clarifications needed. Proceed to `/speckit.tasks`.
