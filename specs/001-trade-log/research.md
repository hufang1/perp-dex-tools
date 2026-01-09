# Research: Trade Logging for Arbitrage Verification

**Feature**: 001-trade-log
**Date**: 2026-01-09
**Status**: Complete

## Overview

This document consolidates research findings for implementing detailed trade logging in the spread arbitrage system. The goal is to enable operators to verify calculated profits against actual exchange positions.

## Technology Decisions

### 1. Logging Framework

**Decision**: Python's built-in `logging` module

**Rationale**:
- Already used throughout the codebase (`spread/bot.py`, `spread/order_manager.py`, `spread/hedge_manager.py`)
- Thread-safe by default (handles concurrent writes via locks)
- Supports multiple handlers and formatters
- Built-in error handling for write failures
- No external dependencies required

**Alternatives Considered**:
- **loguru**: More feature-rich but adds external dependency
- **Direct file I/O**: Would require manual thread safety and error handling
- **structlog**: Overkill for simple text logging requirement

### 2. Log File Location

**Decision**: `logs/trade.log` in project root

**Rationale**:
- Matches user requirement specification
- Consistent with project conventions (logs directory in root)
- Easy to locate for manual verification
- Separate from system logs (dedicated to trade verification)

**Alternatives Considered**:
- **spread/logs/trade.log**: More modular but harder to find
- **/var/log/hufangperp/trade.log**: System-wide location but requires permissions
- **Database storage**: Overkill for verification requirement, adds complexity

### 3. Log Format

**Decision**: Human-readable structured text with delimiters

**Rationale**:
- Meets requirement for manual verification without special tools
- Can be viewed with any text editor
- Clear field labels prevent misreading
- Delimiters between entries enable parsing if needed later
- Compatible with existing log aggregation tools

**Alternatives Considered**:
- **JSON**: Machine-readable but harder for humans to read without formatting tools
- **CSV**: Good for parsing but less readable for structured data like PnL calculations
- **Binary format**: Not human-readable, violates SC-004

### 4. Atomic Write Strategy

**Decision**: Use Python's `logging` module with `FileHandler` in append mode

**Rationale**:
- `logging.FileHandler` automatically acquires locks on each write
- Built-in atomicity guarantees prevent interleaved log entries
- No need for custom locking mechanisms
- Handles concurrent trade events correctly

**Alternatives Considered**:
- **Custom file locking with fcntl**: More complex, platform-specific
- **Queue-based logging**: Overkill for current volume (<10k trades/day)
- **Separate log process**: Unnecessary complexity for single-machine deployment

### 5. Error Handling Strategy

**Decision**: Try-except with fallback to console logging, never block trading

**Rationale**:
- Meets FR-008 and SC-005: trading continues even if logging fails
- Error notification to operator via console/stderr
- No retry logic (could delay trading operations)
- Simple and predictable behavior

**Alternatives Considered**:
- **Retry with exponential backoff**: Could delay trading decisions
- **Queue for later writing**: Adds complexity and memory overhead
- **Terminate on log failure**: Violates SC-005 (zero trading interruptions)

### 6. Log Entry Structure

**Decision**: Structured sections with clear headers

**Opening Trade Entry**:
```
=== TRADE OPENED ===
Timestamp: 2026-01-09 12:34:56.789
Pair ID: 1
Direction: LONG (Extended BUY, Lighter SELL)

Extended Exchange:
  Order ID: ext_12345
  Price: $3450.50
  Quantity: 0.0100 ETH

Lighter Exchange:
  Order ID: lt_67890
  Price: $3455.75
  Quantity: 0.0100 ETH

Spread Information:
  Absolute Spread: $5.25
  Spread Rate: 0.1521%
=====================
```

**Closing Trade Entry**:
```
=== TRADE CLOSED ===
Timestamp: 2026-01-09 12:35:26.789
Pair ID: 1
Direction: LONG
Holding Time: 30.0 seconds

Opening Prices (Reference):
  Extended: $3450.50
  Lighter: $3455.75

Closing Prices:
  Extended Order ID: ext_12346
  Extended Price: $3451.00
  Lighter Order ID: lt_67891
  Lighter Price: $3455.25

Profit/Loss Calculation:
  Extended PnL: ($3451.00 - $3450.50) × 0.0100 = $0.005
  Lighter PnL: ($3455.75 - $3455.25) × 0.0100 = $0.005
  Total PnL: $0.005 + $0.005 = $0.01
  Return: 0.0290%
======================
```

**Rationale**:
- Clear section headers with visual delimiters
- Labeled fields prevent ambiguity
- Step-by-step calculation shows formulas
- Currency symbols and formatting (FR-007)
- Opening prices included in close entry for verification

### 7. Unhedged Position Logging

**Decision**: Separate warning entry with full details

**Format**:
```
=== WARNING: UNHEDGED POSITION ===
Timestamp: 2026-01-09 12:34:56.789
Pair ID: 1 (OPENING INCOMPLETE)

Extended Filled:
  Order ID: ext_12345
  Side: BUY
  Price: $3450.50
  Quantity: 0.0100 ETH

Lighter FAILED:
  Error: Connection timeout
  Expected Side: SELL
  Expected Price: $3455.75

⚠️  UNHEDGED POSITION - MANUAL REVIEW REQUIRED
==============================================
```

**Rationale**:
- Clearly distinguished from normal entries
- All information needed for manual review
- Meets edge case requirement in spec

## Integration Points

### 1. SpreadPair Class (`spread/spread_pair.py`)

**Current State**: Has `to_dict()` method with all trade data

**Integration**: Add logging methods that read from existing attributes
- No data structure changes needed
- Use existing properties: `pair_id`, `extended_side`, `extended_price`, `lighter_price`, etc.
- Leverage existing `calculate_unrealized_pnl()` for calculations

### 2. Bot Class (`spread/bot.py`)

**Current State**: Already has logging setup with `self.logger`

**Integration Points**:
- `_open_new_pair()`: Log after successful opening (line 533)
- `_close_pair()`: Log after successful closing (line 628)
- Unhedged position detection (line 500): Log warning

**No Changes Required**:
- Logging configuration already exists
- Trade logic remains unchanged (out of scope)

### 3. Order Manager (`spread/order_manager.py`)

**Current State**: Has logger, tracks order status

**Integration**: None required (bot handles logging after order completion)

### 4. Hedge Manager (`spread/hedge_manager.py`)

**Current State**: Has logger, executes hedges

**Integration**: None required (bot handles logging after hedge completion)

## Performance Considerations

### 1. Log Volume

**Estimate**: <10,000 trades/day × ~300 bytes/entry = ~3 MB/day

**Impact**: Negligible
- Well within file system capabilities
- No rotation needed initially
- Can address rotation when reaching ~100 MB (edge case)

### 2. Write Latency

**Analysis**:
- File I/O is synchronous in Python's `logging` module
- Typical write time: <1ms for 300 bytes on local filesystem
- Trading operations take seconds (network I/O to exchanges)
- Logging overhead is negligible compared to trading latency

**Conclusion**: No performance impact on trading decisions

### 3. Thread Safety

**Status**: Handled by Python's `logging` module
- `FileHandler` uses threading.Lock internally
- No race conditions possible
- FR-009 satisfied

## Testing Strategy

### 1. Unit Tests

**Test Cases**:
- Log entry creation for opening trades (all fields present)
- Log entry creation for closing trades (calculation correctness)
- Unhedged position warning logging
- File creation when `logs/` doesn't exist
- Error handling when log file is unwritable
- Concurrent write safety (multiple threads)

**Approach**: Use pytest with temporary file fixtures

### 2. Integration Tests

**Test Cases**:
- End-to-end trade open produces log entry
- End-to-end trade close produces log entry with calculations
- Log file location is correct (`logs/trade.log`)
- Log format is human-readable

**Approach**: Run actual bot with test exchange mocks

### 3. Manual Verification

**Test Cases**:
- User can open log file in text editor
- User can verify PnL calculation matches exchange data
- User can identify discrepancies

**Approach**: Sample log entries reviewed by user

## Risks and Mitigations

### 1. Disk Space Exhaustion

**Risk**: Log file grows too large

**Mitigation**:
- Monitor file size in stats reporter (bot.py:347)
- Add warning when approaching size threshold
- Manual rotation process documented (future enhancement)

### 2. File Permissions

**Risk**: Cannot write to `logs/trade.log`

**Mitigation**:
- Create directory with proper permissions on startup
- Fall back to console logging with error message
- Never block trading (FR-008, SC-005)

### 3. Concurrent Write Corruption

**Risk**: Interleaved log entries from multiple trades

**Mitigation**:
- Python's `logging` module handles this natively
- Each `log()` call is atomic
- Verified in unit tests

## Open Questions (None)

All technical decisions resolved. Ready to proceed to Phase 1 design.
