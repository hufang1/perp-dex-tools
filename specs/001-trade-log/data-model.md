# Data Model: Trade Logging

**Feature**: 001-trade-log
**Date**: 2026-01-09

## Overview

This document defines the data structures and entities for the trade logging system. The logging feature does not introduce new persistent data structures but defines the format and content of log entries.

## Log Entry Entities

### 1. Opening Trade Log Entry

Recorded when a spread pair position is successfully opened.

**Fields**:

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `timestamp` | ISO 8601 datetime | When the trade opened | Required, format: YYYY-MM-DD HH:MM:SS.mmm |
| `pair_id` | integer | Unique spread pair identifier | Required, > 0 |
| `direction` | enum | LONG or SHORT | Required, must be "LONG" or "SHORT" |
| `extended_order_id` | string | Exchange order ID | Required, non-empty |
| `extended_side` | enum | BUY or SELL | Required, matches direction |
| `extended_price` | decimal | Price in USDT | Required, > 0, 2 decimal places |
| `extended_quantity` | decimal | Quantity in base asset | Required, > 0, 4 decimal places |
| `lighter_order_id` | string | Exchange order ID | Required, non-empty |
| `lighter_side` | enum | SELL or BUY (opposite of extended) | Required, opposite of extended_side |
| `lighter_price` | decimal | Price in USDT | Required, > 0, 2 decimal places |
| `lighter_quantity` | decimal | Quantity in base asset | Required, > 0, 4 decimal places |
| `spread_absolute` | decimal | Price difference | Required, calculated: lighter_price - extended_price (for LONG) |
| `spread_rate` | decimal | Spread as percentage | Required, calculated: spread_absolute / extended_price |

**Relationships**:
- Linked to closing entry via `pair_id`
- References existing `SpreadPair` object in memory

### 2. Closing Trade Log Entry

Recorded when a spread pair position is successfully closed.

**Fields**:

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `timestamp` | ISO 8601 datetime | When the trade closed | Required, format: YYYY-MM-DD HH:MM:SS.mmm |
| `pair_id` | integer | Unique spread pair identifier | Required, > 0, matches opening entry |
| `direction` | enum | LONG or SHORT | Required, matches opening entry |
| `holding_time_seconds` | float | Duration position was held | Required, >= 0 |
| `open_extended_price` | decimal | Opening Extended price | Required, copied from opening entry |
| `open_lighter_price` | decimal | Opening Lighter price | Required, copied from opening entry |
| `close_extended_order_id` | string | Exchange order ID | Required, non-empty |
| `close_extended_price` | decimal | Closing Extended price | Required, > 0, 2 decimal places |
| `close_extended_quantity` | decimal | Closing quantity | Required, matches open quantity |
| `close_lighter_order_id` | string | Exchange order ID | Required, non-empty |
| `close_lighter_price` | decimal | Closing Lighter price | Required, > 0, 2 decimal places |
| `close_lighter_quantity` | decimal | Closing quantity | Required, matches open quantity |
| `extended_pnl_formula` | string | Calculation formula | Required, shows formula used |
| `extended_pnl_value` | decimal | Extended profit/loss | Required, can be negative |
| `lighter_pnl_formula` | string | Calculation formula | Required, shows formula used |
| `lighter_pnl_value` | decimal | Lighter profit/loss | Required, can be negative |
| `total_pnl` | decimal | Combined profit/loss | Required, sum of both PnL values |
| `return_rate` | decimal | Return as percentage | Required, total_pnl / position_value |

**Relationships**:
- References opening entry via `pair_id`
- References closed `SpreadPair` object

### 3. Unhedged Position Warning Entry

Recorded when a position cannot be fully hedged (Extended fills but Lighter fails).

**Fields**:

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `timestamp` | ISO 8601 datetime | When failure occurred | Required, format: YYYY-MM-DD HH:MM:SS.mmm |
| `pair_id` | integer | Spread pair identifier | Required, > 0 |
| `extended_order_id` | string | Filled order ID | Required, non-empty |
| `extended_side` | enum | BUY or SELL | Required |
| `extended_price` | decimal | Filled price | Required, > 0 |
| `extended_quantity` | decimal | Filled quantity | Required, > 0 |
| `lighter_error` | string | Error message | Required, non-empty |
| `expected_lighter_side` | enum | Expected hedge side | Required, opposite of extended_side |
| `expected_lighter_price` | decimal | Expected hedge price | Required, > 0 |

**Relationships**:
- Standalone warning entry
- May be followed by manual close entry

## State Transitions

### Spread Pair Lifecycle

```
[OPENING] → Opening Log Entry → [OPEN] → Closing Log Entry → [CLOSED]
                      ↓
              Unhedged Warning Entry
                      ↓
              [UNHEDGED] (manual intervention)
```

**States**:
1. **OPENING**: Position being established
2. **OPEN**: Both exchanges hedged, normal operation
3. **UNHEDGED**: Only Extended filled, requires manual review
4. **CLOSED**: Position closed, PnL realized

### Log Entry Sequence

For each complete trade:

```
1. Opening Entry (at successful hedge completion)
2. [Optional] Unhedged Warning (if hedge fails)
3. Closing Entry (at position close)
```

## Validation Rules

### Cross-Field Validation

1. **Pair ID Consistency**: Closing entry must reference valid opening entry
2. **Direction Consistency**: Direction must match between open and close
3. **Quantity Conservation**: Closing quantities must equal opening quantities
4. **Side Opposition**: Lighter side must always oppose Extended side
5. **PnL Calculation**: Total PnL must equal sum of component PnL values

### Business Rules

1. **Spread Must Be Positive**: Opening spread must be > 0 (arbitrage opportunity)
2. **Holding Time**: Must be >= 0 seconds
3. **Price Precision**: All prices stored with 2 decimal places (USDT)
4. **Quantity Precision**: All quantities stored with 4 decimal places (crypto)
5. **Order ID Uniqueness**: Each order ID must be unique within the system

## Data Sources

### Existing Structures (Read-Only)

The logging system reads from existing in-memory structures:

**SpreadPair** (`spread/spread_pair.py`):
```python
pair_id: int
extended_side: str  # 'buy' or 'sell'
extended_price: Decimal
extended_quantity: Decimal
lighter_price: Decimal
lighter_quantity: Decimal
open_extended_order_id: Optional[str]
open_lighter_order_id: Optional[str]
close_extended_order_id: Optional[str]
close_lighter_order_id: Optional[str]
open_time: float
close_time: Optional[float]
```

**Bot State** (`spread/bot.py`):
```python
.open_pairs: List[SpreadPair]
.closed_pairs: List[SpreadPair]
.unhedged_positions: List[Dict]
```

### New Structures (Write-Only)

**Log File** (`logs/trade.log`):
- Append-only text file
- One entry per trade event
- Human-readable format
- No modifications to existing structures

## Privacy and Security

### Data Sensitivity

**Non-Sensitive**:
- Timestamps
- Pair IDs (internal identifiers)
- Prices and quantities (public market data)

**Potentially Sensitive**:
- Order IDs (exchange-specific, could be linked to exchange accounts)

**Recommendation**: Order IDs are necessary for verification but should be treated as operational data, not public.

### Data Retention

**Current Scope**: No automatic deletion (logs accumulate)

**Future Consideration**:
- Implement log rotation after reaching size threshold
- Archive old logs to compressed storage
- Define retention period based on compliance requirements

## Performance Characteristics

### Write Patterns

- **Frequency**: On trade events only (not continuous)
- **Volume**: ~300 bytes per entry, <10k entries/day = ~3 MB/day
- **Latency**: <1ms synchronous write (acceptable for trading cadence)
- **Concurrency**: Thread-safe via Python's logging module

### Read Patterns

- **Frequency**: On-demand manual verification
- **Volume**: Sequential scan for specific pair IDs
- **Latency**: Not time-critical (verification is retrospective)

## Error Handling

### Write Failures

**Error Types**:
- Disk full
- Permission denied
- Path too long

**Handling Strategy**:
1. Log error to console/stderr
2. Continue trading (never block)
3. Alert operator via stats reporter

### Data Integrity

**Protection Mechanisms**:
- Atomic writes (logging module locks)
- No partial entries (all-or-nothing)
- Validation before write (check required fields)

**Recovery**:
- No rollback needed (logging is non-critical)
- Corrupted entries are identifiable by format
- Manual review required for discrepancies
