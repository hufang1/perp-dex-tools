# Trade Logger Interface Contract

**Feature**: 001-trade-log
**Version**: 1.0
**Date**: 2026-01-09

## Overview

This document defines the interface contract for the trade logging system. Since this is an internal logging feature (not an external API), the contract specifies the expected behavior and method signatures for the logging functionality.

## Module: TradeLogger

**Location**: `spread/trade_logger.py` (new module)

### Responsibility

Manages all trade-related logging operations with a focus on human-readable verification.

### Interface

```python
class TradeLogger:
    """Handles detailed logging of spread arbitrage trades for verification purposes."""

    def __init__(self, log_file_path: str = "logs/trade.log"):
        """
        Initialize the trade logger.

        Args:
            log_file_path: Path to the trade log file (default: logs/trade.log)

        Raises:
            OSError: If log directory cannot be created
            LoggingError: If logger setup fails (non-fatal)
        """

    def log_opening_trade(self, pair: SpreadPair) -> bool:
        """
        Log a successfully opened spread pair position.

        Args:
            pair: The SpreadPair object containing opening trade details

        Returns:
            True if logging succeeded, False otherwise

        Behavior:
            - Writes formatted opening entry to log file
            - Includes: timestamp, pair_id, direction, exchange details, spread
            - Atomic write (thread-safe)
            - On failure: emits error to console, returns False, never raises

        Example Output:
            === TRADE OPENED ===
            Timestamp: 2026-01-09 12:34:56.789
            Pair ID: 1
            Direction: LONG (Extended BUY, Lighter SELL)
            ...
        """

    def log_closing_trade(self, pair: SpreadPair) -> bool:
        """
        Log a successfully closed spread pair position with PnL calculation.

        Args:
            pair: The SpreadPair object containing closing trade details
                  Must have close_time and closing prices set

        Returns:
            True if logging succeeded, False otherwise

        Behavior:
            - Writes formatted closing entry to log file
            - Includes: timestamp, pair_id, holding time, opening prices (reference),
              closing prices, step-by-step PnL calculation
            - Atomic write (thread-safe)
            - On failure: emits error to console, returns False, never raises

        Example Output:
            === TRADE CLOSED ===
            Timestamp: 2026-01-09 12:35:26.789
            Pair ID: 1
            ...
            Profit/Loss Calculation:
              Extended PnL: ($3451.00 - $3450.50) × 0.0100 = $0.005
              ...
        """

    def log_unhedged_position(self, position: Dict) -> bool:
        """
        Log a warning for an unhedged position (Extended filled, Lighter failed).

        Args:
            position: Dictionary containing:
                - order_id: str
                - side: str ('buy' or 'sell')
                - quantity: Decimal
                - price: Decimal
                - error: str (error message from Lighter)
                - timestamp: float

        Returns:
            True if logging succeeded, False otherwise

        Behavior:
            - Writes formatted warning entry to log file
            - Clearly marked as WARNING for visibility
            - Includes all details needed for manual review
            - Atomic write (thread-safe)
            - On failure: emits error to console, returns False, never raises

        Example Output:
            === WARNING: UNHEDGED POSITION ===
            Timestamp: 2026-01-09 12:34:56.789
            Pair ID: 1 (OPENING INCOMPLETE)
            ...
        """

    def get_log_file_path(self) -> str:
        """
        Get the current log file path.

        Returns:
            Absolute path to the trade log file
        """

    def get_log_stats(self) -> Dict:
        """
        Get statistics about the log file.

        Returns:
            Dictionary containing:
                - file_path: str
                - file_size_bytes: int
                - file_size_mb: float
                - entry_count: int (if countable)
                - last_modified: str (ISO timestamp)

        Behavior:
            - Does not read entire file for efficiency
            - Returns 0 for entry_count if not easily determinable
        """
```

## Integration Points

### 1. Bot Class (`spread/bot.py`)

**Where to instantiate**: `SpreadArbitrageBot.__init__()`

```python
# In __init__ method
self.trade_logger = TradeLogger(log_file_path="logs/trade.log")
```

**Where to call methods**:

1. **Opening Trade** (`_open_new_pair()` method, after line 533):
```python
# After successful pair creation
self.trade_logger.log_opening_trade(pair)
```

2. **Closing Trade** (`_close_pair()` method, after line 628):
```python
# After calculating PnL and updating stats
self.trade_logger.log_closing_trade(pair)
```

3. **Unhedged Position** (`_open_new_pair()` method, after line 500):
```python
# After hedge failure detection
self.trade_logger.log_unhedged_position(unhedged_position)
```

### 2. Error Handling

**Logging failures must not block trading**:

```python
# Example pattern in bot methods
if not self.trade_logger.log_opening_trade(pair):
    self.logger.warning("Trade logging failed for opening, but trading continues")
# Continue with normal execution
```

### 3. Configuration

**No configuration changes required** - log file path is hardcoded to `logs/trade.log` per specification.

## Testing Interface

### Unit Test Interface

```python
# Test helper for creating temporary log files
def create_temp_logger(tmp_path) -> TradeLogger:
    """Create a TradeLogger with a temporary file path for testing."""

# Verification helper for checking log content
def get_log_entries(log_path: str) -> List[str]:
    """Read and parse log file into entry list for assertions."""
```

### Integration Test Interface

```python
# Test fixture for running full trade cycle
def run_trade_cycle(bot) -> Tuple[SpreadPair, str, str]:
    """
    Execute a full open/close cycle and return:
    - The SpreadPair object
    - Opening log entry text
    - Closing log entry text
    """
```

## Error Contract

### Method Return Values

**Success**: Returns `True`

**Failure**: Returns `False` and:
- Logs error message via Python's `logging` module to stderr
- Never raises exceptions (except `__init__` which can raise OSError)
- Never blocks or delays calling code

### Error Messages

**Expected error messages** (for testing):

| Error Condition | Message Pattern |
|-----------------|-----------------|
| Permission denied | "ERROR:trade_logger: Cannot write to log file" |
| Disk full | "ERROR:trade_logger: Disk full when writing trade log" |
| Directory creation failed | "ERROR:trade_logger: Cannot create log directory" |
| Invalid pair data | "ERROR:trade_logger: Invalid pair data for logging" |

## Performance Contract

### Latency

- **Opening log**: <5ms per call
- **Closing log**: <5ms per call
- **Unhedged log**: <5ms per call

### Throughput

- **Concurrent writes**: Supported (thread-safe)
- **Maximum write rate**: >100 entries/second (far exceeds trading volume)

### Resource Usage

- **Memory**: <1 MB for logger instance
- **Disk**: ~300 bytes per trade entry
- **CPU**: Negligible (<1% per log operation)

## Versioning

### Current Version: 1.0

**Compatible with**:
- Python 3.11+
- Existing `SpreadPair` class (as of 2026-01-09)
- Existing `logging` configuration in bot

### Breaking Changes

**None planned**. Future versions will maintain backward compatibility with:
- Log file format (append-only changes)
- Method signatures (additions only)
- Return value types (bool for success)

## Non-Functional Requirements

### Reliability

- **Atomic writes**: Guaranteed by Python's `logging` module
- **No data loss**: Write failures return False but don't crash
- **Thread-safe**: Multiple concurrent trades handled correctly

### Maintainability

- **Single responsibility**: Only handles logging, no business logic
- **Testable**: All methods have clear inputs/outputs
- **Observable**: Errors logged to standard channels

### Usability

- **Human-readable**: Log entries understandable without tools
- **Verifiable**: All data needed for PnL verification present
- **Searchable**: Pair IDs and timestamps enable lookup
