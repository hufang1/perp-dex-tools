# hufangperp Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-19

## Active Technologies
- Python 3.10.19 + asyncio, aiohttp, websockets, lighter-sdk, x10-python-trading-starknet, pydantic, tenacity (016-spread-optimize)
- JSON文件状态持久化 (logs/spread_arb_state.json) (016-spread-optimize)
- (002-spread-arb)
- (003-spreading-improvements)

## Project Structure

```text
spread/              # Core spread arbitrage bot module
├── spread_arb_bot.py       # Main bot controller
├── trade_executor.py       # Trade execution with cancel verification
├── arithmetic_open_strategy.py  # Tiered opening thresholds
├── smart_close_strategy.py # Dual-mode close (market/limit)
├── balance_checker.py      # Balance availability checker (NEW)
├── maker_order_monitor.py  # Maker order monitoring
├── state_manager.py        # State persistence with tiered opening
├── models.py               # Data models with new classes
├── spread_monitor.py       # Spread monitoring
├── price_monitor.py        # Price monitoring
└── order_book_manager.py   # Order book management

tests/
├── unit/                   # Unit tests
└── integration/            # Integration tests
```

## Commands

# Add commands for

## Code Style

: Follow standard conventions

## Recent Changes
- 016-spread-optimize: Added Python 3.10.19 + asyncio, aiohttp, websockets, lighter-sdk, x10-python-trading-starknet, pydantic, tenacity
- 002-spread-arb: Added spread arbitrage bot with portfolio management
- 003-spreading-improvements: Added four user stories:
  1. **Cancel Order Verification**: Fixed duplicate order bug by verifying cancellation before creating new orders
  2. **Tiered Opening**: Progressive opening thresholds (0.5%, 0.6%, 0.7%...) based on opening_count
  3. **Dual-Mode Close**: Market close for large profits, limit close for small profits
  4. **Balance Checker**: Validates available balance on both exchanges before opening

## New Configuration Parameters (003-spreading-improvements)

### Tiered Opening (ArithmeticOpenStrategy)
```python
BotConfig.initial_open_spread = Decimal("0.005")  # Initial opening threshold (0.5%)
BotConfig.spread_step = Decimal("0.001")           # Opening threshold step (0.1%)
BotConfig.opening_count = 0                        # Current opening tier (0, 1, 2, ...)
BotConfig.current_open_threshold                   # Computed: initial + (count * step)
```

### Dual-Mode Close (SmartCloseStrategy)
```python
BotConfig.limit_close_spread_a = Decimal("0.002")  # Limit close threshold A (0.2%)
BotConfig.market_close_spread_b = Decimal("0.004") # Market close threshold B (0.4%)
```

### New Bot States
```python
BotState.CLOSING_LIMIT   # Limit close in progress
BotState.CLOSING_MARKET  # Market close in progress
```

## New Data Classes (003-spreading-improvements)

```python
@dataclass
class CancelOrderResult:
    """Result of order cancellation with verification"""
    order_id: str
    canceled: bool
    attempts: int
    total_time: float
    final_status: Optional[str] = None
    error_message: Optional[str] = None

@dataclass
class TieredOpeningState:
    """Current tiered opening state snapshot"""
    current_count: int
    current_threshold: Decimal
    next_threshold: Decimal
    initial_spread: Decimal
    step_size: Decimal
    opening_history: list

@dataclass
class CloseModeDecision:
    """Dual-mode close decision result"""
    should_close: bool
    use_market: bool  # True=market, False=limit
    total_position_spread: Decimal
    current_spread: Decimal
    market_threshold: Decimal
    limit_threshold: Decimal
    expected_profit_limit: Decimal
    expected_profit_market: Decimal

@dataclass
class BalanceAvailabilityResult:
    """Balance availability check result before opening"""
    is_sufficient: bool
    ext_available: Decimal
    ext_required: Decimal
    lig_available: Decimal
    lig_required: Decimal
    check_time: float
    failure_reason: Optional[str] = None
    shortage_amount: Decimal = Decimal("0")
```

## Key Workflow Changes

### Opening Flow (with Balance Check)
1. Check spread threshold (tiered)
2. Risk management validation
3. **NEW**: Balance availability check
4. Execute opening (Maker/Taker mode)
5. **NEW**: Increment opening_count on success

### Closing Flow (Dual-Mode)
1. Get total position spread (from exchange API or local)
2. Calculate market/limit thresholds
3. **NEW**: Select close mode based on profit size
4. Execute market close (fast) OR limit close (cheaper)
5. **NEW**: Reset opening_count when all positions closed

### Maker Order Modification (with Cancel Verification)
1. Detect price change
2. **NEW**: Cancel old order with verification
3. **NEW**: Verify cancellation before creating new order
4. Create new order at updated price

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
