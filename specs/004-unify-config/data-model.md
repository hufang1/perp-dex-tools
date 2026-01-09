# Data Model: Unified Configuration Management

**Feature**: 004-unify-config | **Date**: 2026-01-09

## Overview

This document defines the configuration data models for the three trading bot systems. Each bot has its own configuration class with domain-specific parameters.

## Configuration Classes

### SpreadArbConfig

**Location**: `spread/config.py`

**Purpose**: Configuration for the spread arbitrage bot that trades price differences between Extended and Lighter exchanges.

**Fields**:

| Field | Type | Default | Description | Validation |
|-------|------|---------|-------------|------------|
| `ticker` | `str` | `'ETH'` | Trading pair symbol | N/A |
| `order_quantity_usdt` | `Decimal` | `Decimal('35')` | Order size in USDT | Must be > 0 |
| `min_spread_rate` | `Decimal` | `Decimal('0.0005')` | Minimum spread rate to open position (0.05%) | Must be > 0 and > latency_buffer |
| `latency_buffer` | `Decimal` | `Decimal('0.0001')` | Buffer for execution latency (0.01%) | N/A |
| `max_open_pairs` | `int` | `3` | Maximum concurrent spread pairs | Must be > 0 |
| `max_total_position_usdt` | `Decimal` | `Decimal('25')` | Maximum total position value | N/A |
| `enable_time_close` | `bool` | `True` | Enable time-based position closing | N/A |
| `max_holding_time` | `int` | `300` | Maximum position holding time (seconds) | Must be > time_close_threshold |
| `time_close_threshold` | `int` | `60` | Time threshold for forced closing (seconds) | Must be > 0 |
| `enable_profit_target` | `bool` | `True` | Enable profit target closing | N/A |
| `profit_target_rate` | `Decimal` | `Decimal('0.0005')` | Target profit rate (0.05%) | Must be > 0 |
| `enable_stop_loss` | `bool` | `True` | Enable stop-loss | N/A |
| `stop_loss_usdt` | `Decimal` | `Decimal('5')` | Stop-loss amount in USDT | N/A |
| `time_close_profit_threshold` | `Decimal` | `Decimal('0.0001')` | Minimum profit for time-based close (0.01%) | N/A |
| `allow_negative_close` | `bool` | `False` | Allow closing with negative profit | N/A |
| `max_lighter_depth_ratio` | `Decimal` | `Decimal('0.5')` | Max ratio of Lighter depth to use | Must be in (0, 1] |
| `min_lighter_depth_usdt` | `Decimal` | `Decimal('200')` | Minimum Lighter depth required | N/A |
| `check_depth_layers` | `int` | `3` | Number of orderbook layers to check | N/A |
| `slippage_tolerance` | `Decimal` | `Decimal('0.001')` | Maximum acceptable slippage (0.1%) | N/A |
| `max_unhedged_positions` | `int` | `0` | Maximum allowed unhedged positions | N/A |
| `auto_close_unhedged` | `bool` | `False` | Auto-close unhedged positions | N/A |
| `unhedged_position_timeout` | `int` | `60` | Timeout for unhedged positions (seconds) | N/A |
| `hedge_failure_threshold` | `Decimal` | `Decimal('0.3')` | Hedge failure rate threshold (30%) | N/A |
| `hedge_failure_window` | `int` | `10` | Hedge failure rate window | N/A |
| `enable_reconciliation` | `bool` | `True` | Enable position reconciliation | N/A |
| `reconciliation_interval` | `int` | `60` | Reconciliation interval (seconds) | N/A |
| `extended_fill_timeout` | `int` | `10` | Extended order fill timeout (seconds) | N/A |
| `lighter_hedge_timeout` | `int` | `3` | Lighter hedge timeout (seconds) | N/A |
| `max_consecutive_failures` | `int` | `3` | Maximum consecutive failures before cooldown | N/A |
| `cooldown_period` | `int` | `60` | Cooldown period (seconds) | N/A |
| `prioritize_closing` | `bool` | `True` | Prioritize closing over opening | N/A |
| `enable_partial_fill` | `bool` | `True` | Allow partial order fills | N/A |
| `log_level` | `str` | `'INFO'` | Logging level | N/A |
| `env_file` | `str` | `'.env'` | Environment variables file path | N/A |

**Relationships**:
- Used by: `spread/bot.py` (SpreadArbitrageBot class)
- Reads from: `.env` file (via dotenv)

**State Transitions**: None (configuration is immutable after creation)

**Validation Rules**:
```python
def __post_init__(self):
    # Value validations
    if self.min_spread_rate <= 0:
        raise ValueError("min_spread_rate must be greater than 0")
    if self.min_spread_rate <= self.latency_buffer:
        raise ValueError("min_spread_rate must be greater than latency_buffer")
    if self.max_open_pairs <= 0:
        raise ValueError("max_open_pairs must be greater than 0")
    if self.order_quantity_usdt <= 0:
        raise ValueError("order_quantity_usdt must be greater than 0")
    if not (0 < self.max_lighter_depth_ratio <= 1):
        raise ValueError("max_lighter_depth_ratio must be in (0, 1] range")
    if self.profit_target_rate <= 0:
        raise ValueError("profit_target_rate must be greater than 0")
    if self.time_close_threshold <= 0:
        raise ValueError("time_close_threshold must be greater than 0")
    if self.max_holding_time <= self.time_close_threshold:
        raise ValueError("max_holding_time must be greater than time_close_threshold")
```

**Methods**:
- `from_env() -> SpreadArbConfig`: Class method to create instance from environment variables
- `effective_min_spread -> Decimal`: Property returning min_spread_rate + latency_buffer

---

### HedgeConfig

**Location**: `hedge/config.py` (NEW)

**Purpose**: Configuration for hedge mode bots that simultaneously trade on a primary exchange and hedge on Lighter.

**Fields**:

| Field | Type | Default | Description | Validation |
|-------|------|---------|-------------|------------|
| `exchange` | `str` | `'edgex'` | Primary exchange name | Must be in supported list |
| `ticker` | `str` | `'BTC'` | Trading pair symbol | N/A |
| `order_quantity` | `Decimal` | `Decimal('0.01')` | Order size in tokens | Must be > 0 |
| `iterations` | `int` | `20` | Number of trading iterations | Must be > 0 |
| `fill_timeout` | `int` | `5` | Order fill timeout (seconds) | Must be > 0 |
| `sleep_time` | `int` | `0` | Sleep time between iterations (seconds) | Must be >= 0 |
| `max_position` | `Decimal` | `Decimal('0')` | Maximum position size (0 = unlimited) | Must be >= 0 |
| `env_file` | `str` | `'.env'` | Environment variables file path | N/A |

**Supported Exchanges**: `'backpack'`, `'extended'`, `'apex'`, `'grvt'`, `'edgex'`, `'nado'`

**Relationships**:
- Used by: `hedge/hedge_mode.py` (main entry point)
- Used by: Individual hedge implementations (hedge_mode_bp.py, hedge_mode_apex.py, etc.)
- Reads from: `.env` file (via dotenv)

**State Transitions**: None (configuration is immutable after creation)

**Validation Rules**:
```python
def __post_init__(self):
    supported = ['backpack', 'extended', 'apex', 'grvt', 'edgex', 'nado']
    if self.exchange not in supported:
        raise ValueError(f"exchange must be one of {supported}")
    if self.order_quantity <= 0:
        raise ValueError("order_quantity must be greater than 0")
    if self.iterations <= 0:
        raise ValueError("iterations must be greater than 0")
    if self.fill_timeout <= 0:
        raise ValueError("fill_timeout must be greater than 0")
    if self.sleep_time < 0:
        raise ValueError("sleep_time must be non-negative")
    if self.max_position < 0:
        raise ValueError("max_position must be non-negative")
```

**Methods**:
- `from_env() -> HedgeConfig`: Class method to create instance from environment variables

---

### TradingConfig

**Location**: `trading_config.py` (NEW)

**Purpose**: Configuration for the modular trading bot that supports multiple exchanges.

**Fields**:

| Field | Type | Default | Description | Validation |
|-------|------|---------|-------------|------------|
| `exchange` | `str` | `'edgex'` | Exchange name | Must be in supported list |
| `ticker` | `str` | `'ETH'` | Trading pair symbol | N/A |
| `contract_id` | `str` | `''` | Contract ID (set at runtime) | N/A |
| `tick_size` | `Decimal` | `Decimal('0')` | Minimum price increment (set at runtime) | N/A |
| `quantity` | `Decimal` | `Decimal('0.1')` | Order quantity | Must be > 0 |
| `take_profit` | `Decimal` | `Decimal('0.02')` | Take profit amount in USDT | Must be > 0 |
| `direction` | `str` | `'buy'` | Trading direction | Must be 'buy' or 'sell' |
| `max_orders` | `int` | `40` | Maximum active orders | Must be > 0 |
| `wait_time` | `int` | `450` | Wait time between orders (seconds) | Must be > 0 |
| `grid_step` | `Decimal` | `Decimal('-100')` | Grid step percentage | N/A |
| `stop_price` | `Decimal` | `Decimal('-1')` | Stop trading price (-1 = disabled) | N/A |
| `pause_price` | `Decimal` | `Decimal('-1')` | Pause trading price (-1 = disabled) | N/A |
| `boost_mode` | `bool` | `False` | Enable boost mode (aster/backpack only) | N/A |
| `env_file` | `str` | `'.env'` | Environment variables file path | N/A |

**Relationships**:
- Used by: `runbot.py` (main entry point)
- Used by: `trading_bot.py` (TradingBot class)
- Reads from: `.env` file (via dotenv)

**State Transitions**: None (configuration is immutable after creation)

**Validation Rules**:
```python
def __post_init__(self):
    if self.exchange not in ExchangeFactory.get_supported_exchanges():
        raise ValueError(f"Unsupported exchange: {self.exchange}")
    if self.quantity <= 0:
        raise ValueError("quantity must be greater than 0")
    if self.take_profit <= 0:
        raise ValueError("take_profit must be greater than 0")
    if self.direction not in ['buy', 'sell']:
        raise ValueError("direction must be 'buy' or 'sell'")
    if self.max_orders <= 0:
        raise ValueError("max_orders must be greater than 0")
    if self.wait_time <= 0:
        raise ValueError("wait_time must be greater than 0")
    if self.boost_mode and self.exchange not in ['aster', 'backpack']:
        raise ValueError("boost_mode is only supported for aster and backpack exchanges")
```

**Methods**:
- `from_env() -> TradingConfig`: Class method to create instance from environment variables

## Configuration Loading Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        User Action                           │
│                   Run: python spread/run_spread_arb.py      │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Import Statement                          │
│              from spread.config import config               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│            spread/config.py Module Execution                │
│                                                             │
│  1. Load .env file (config.env_file or default '.env')     │
│  2. Create SpreadArbConfig instance with defaults          │
│  3. Validate via __post_init__()                            │
│  4. Export as module-level 'config' variable               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   run_spread_arb.py                         │
│                                                             │
│  1. Import config from spread.config                        │
│  2. Pass config to SpreadArbitrageBot                       │
│  3. Start trading                                           │
└─────────────────────────────────────────────────────────────┘
```

## Environment Variable Override Flow

```
┌─────────────────────────────────────────────────────────────┐
│              Optional: Environment Variables                │
│                   (e.g., for deployment)                    │
│                                                             │
│  TICKER=BTC ORDER_QUANTITY_USDT=50 MIN_SPREAD_RATE=0.0008  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│         SpreadArbConfig.from_env() Class Method             │
│                                                             │
│  1. Read environment variables                              │
│  2. Use config.py defaults if env var not set              │
│  3. Return new SpreadArbConfig instance                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   User Code Override                        │
│                                                             │
│  from spread.config import SpreadArbConfig                 │
│  config = SpreadArbConfig.from_env()  # Override defaults  │
└─────────────────────────────────────────────────────────────┘
```

## Multi-Account Support

```
Account 1 (.env.account1)          Account 2 (.env.production)
┌─────────────────────────┐        ┌─────────────────────────┐
│ EXTENDED_API_KEY=abc    │        │ EXTENDED_API_KEY=xyz    │
│ EXTENDED_SECRET=key1    │        │ EXTENDED_SECRET=key2    │
│ LIGHTER_API_KEY=def     │        │ LIGHTER_API_KEY=uvw     │
└─────────────────────────┘        └─────────────────────────┘
         │                                     │
         │ Switch via config.env_file          │
         ▼                                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    spread/config.py                         │
│                                                             │
│  # For Account 1:                                           │
│  config = SpreadArbConfig(env_file='.env.account1')         │
│                                                             │
│  # For Account 2:                                           │
│  config = SpreadArbConfig(env_file='.env.production')       │
└─────────────────────────────────────────────────────────────┘
```

## Data Type Summary

| Type | Usage | Example |
|------|-------|---------|
| `str` | Ticker symbols, file paths, enums | `'ETH'`, `'.env'`, `'buy'` |
| `int` | Counts, timeouts, thresholds | `3`, `300`, `60` |
| `Decimal` | Financial values, rates, percentages | `Decimal('35')`, `Decimal('0.0005')` |
| `bool` | Feature flags | `True`, `False` |

**Note**: `Decimal` is used for all financial calculations to avoid floating-point precision errors.
