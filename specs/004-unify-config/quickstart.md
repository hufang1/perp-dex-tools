# Quickstart Guide: Unified Configuration Management

**Feature**: 004-unify-config | **Date**: 2026-01-09

## Overview

This guide shows how to configure and run the trading bots after the unified configuration management feature is implemented. All configuration is done through Python config files - no command-line arguments needed.

---

## Spread Arbitrage Bot

### Basic Usage

```bash
# Run with default configuration (from spread/config.py)
python spread/run_spread_arb.py
```

### Configuration

Edit `spread/config.py` to customize parameters:

```python
# spread/config.py
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class SpreadArbConfig:
    # Basic Configuration
    ticker: str = 'ETH'                    # Trading pair
    order_quantity_usdt: Decimal = Decimal('35')  # Order size
    env_file: str = '.env'                 # Environment file

    # Spread Parameters
    min_spread_rate: Decimal = Decimal('0.0005')   # Minimum spread (0.05%)
    latency_buffer: Decimal = Decimal('0.0001')    # Latency buffer

    # Position Management
    max_open_pairs: int = 3                # Max concurrent positions
    max_holding_time: int = 300            # Max holding time (seconds)

    # Profit/Loss
    profit_target_rate: Decimal = Decimal('0.0005')  # Profit target
    stop_loss_usdt: Decimal = Decimal('5')  # Stop loss amount

    # ... other parameters

# Default configuration instance
config = SpreadArbConfig()
```

### Common Configuration Examples

**Conservative Configuration** (lower risk):
```python
@dataclass
class SpreadArbConfig:
    ticker: str = 'ETH'
    order_quantity_usdt: Decimal = Decimal('20')  # Smaller orders
    min_spread_rate: Decimal = Decimal('0.0008')  # Higher threshold
    max_open_pairs: int = 1                       # Only 1 position
    stop_loss_usdt: Decimal = Decimal('3')        # Tighter stop loss

config = SpreadArbConfig()
```

**Aggressive Configuration** (higher volume):
```python
@dataclass
class SpreadArbConfig:
    ticker: str = 'ETH'
    order_quantity_usdt: Decimal = Decimal('50')  # Larger orders
    min_spread_rate: Decimal = Decimal('0.0003')  # Lower threshold
    max_open_pairs: int = 5                       # More positions
    max_holding_time: int = 600                    # Longer holding

config = SpreadArbConfig()
```

---

## Hedge Mode Bot

### Basic Usage

```bash
# Run hedge mode for a specific exchange
python hedge_mode.py --exchange edgex
python hedge_mode.py --exchange apex
python hedge_mode.py --exchange backpack

# Run GRVT v2 implementation
python hedge_mode.py --exchange grvt --v2
```

**Note**: The `--exchange` argument is required to select which exchange to use. This is the only command-line argument needed.

### Configuration

Create `hedge/config.py`:

```python
# hedge/config.py
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class HedgeConfig:
    exchange: str = 'edgex'
    ticker: str = 'BTC'
    order_quantity: Decimal = Decimal('0.01')
    iterations: int = 20
    fill_timeout: int = 5
    sleep_time: int = 0
    max_position: Decimal = Decimal('0')
    env_file: str = '.env'

# Default configuration instance
config = HedgeConfig()
```

### Common Configuration Examples

**Quick Test Run**:
```python
@dataclass
class HedgeConfig:
    exchange: str = 'edgex'
    ticker: str = 'BTC'
    order_quantity: Decimal = Decimal('0.001')  # Small size
    iterations: int = 5                         # Few iterations
    fill_timeout: int = 3

config = HedgeConfig()
```

**Production Run**:
```python
@dataclass
class HedgeConfig:
    exchange: str = 'edgex'
    ticker: str = 'BTC'
    order_quantity: Decimal = Decimal('0.05')   # Larger size
    iterations: int = 50                        # More iterations
    fill_timeout: int = 10                      # Longer timeout
    max_position: Decimal = Decimal('0.5')      # Position limit

config = HedgeConfig()
```

---

## Trading Bot

### Basic Usage

```bash
# Run with default configuration (from trading_config.py)
python runbot.py
```

### Configuration

Create `trading_config.py` at project root:

```python
# trading_config.py
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class TradingConfig:
    exchange: str = 'edgex'
    ticker: str = 'ETH'
    quantity: Decimal = Decimal('0.1')
    take_profit: Decimal = Decimal('0.02')
    direction: str = 'buy'
    max_orders: int = 40
    wait_time: int = 450
    grid_step: Decimal = Decimal('-100')
    stop_price: Decimal = Decimal('-1')
    pause_price: Decimal = Decimal('-1')
    boost_mode: bool = False
    env_file: str = '.env'

# Default configuration instance
config = TradingConfig()
```

### Common Configuration Examples

**Buy Bot**:
```python
@dataclass
class TradingConfig:
    exchange: str = 'edgex'
    ticker: str = 'ETH'
    quantity: Decimal = Decimal('0.1')
    direction: str = 'buy'
    take_profit: Decimal = Decimal('0.02')

config = TradingConfig()
```

**Sell Bot with Stop Price**:
```python
@dataclass
class TradingConfig:
    exchange: str = 'edgex'
    ticker: str = 'ETH'
    quantity: Decimal = Decimal('0.1')
    direction: str = 'sell'
    take_profit: Decimal = Decimal('0.03')
    stop_price: Decimal = Decimal('3500')  # Stop if ETH hits 3500

config = TradingConfig()
```

---

## Multiple Accounts

### Setting Up Multiple Account Files

```bash
# Account 1
cp .env .env.account1

# Account 2
cp .env .env.account2

# Production account
cp .env .env.production
```

### Switching Between Accounts

Edit the config file and change `env_file`:

```python
# For account 1
@dataclass
class SpreadArbConfig:
    env_file: str = '.env.account1'
    # ... other parameters

config = SpreadArbConfig()

# For production
@dataclass
class SpreadArbConfig:
    env_file: str = '.env.production'
    # ... other parameters

config = SpreadArbConfig()
```

---

## Environment Variable Overrides

For deployment scenarios, you can override config.py defaults with environment variables:

```bash
# Set environment variables
export TICKER=BTC
export ORDER_QUANTITY_USDT=50
export MIN_SPREAD_RATE=0.0008

# Run with overrides
python spread/run_spread_arb.py
```

Then in your run script, use the `from_env()` classmethod:

```python
# spread/run_spread_arb.py
from spread.config import SpreadArbConfig

# Use environment variable overrides
config = SpreadArbConfig.from_env()
```

---

## Configuration Validation

All configuration classes validate their parameters on startup. If you make an error, you'll get a clear message:

```python
# Invalid configuration
@dataclass
class SpreadArbConfig:
    min_spread_rate: Decimal = Decimal('-0.001')  # Negative!
    # ...

config = SpreadArbConfig()
```

**Error output**:
```
ValueError: min_spread_rate must be greater than 0
```

---

## Migration from Command-Line Arguments

### Before (Old Way)

```bash
python spread/run_spread_arb.py \
    --ticker ETH \
    --quantity 35 \
    --min-spread 0.0005 \
    --max-pairs 3 \
    --stop-loss 5
```

### After (New Way)

Edit `spread/config.py`:

```python
@dataclass
class SpreadArbConfig:
    ticker: str = 'ETH'
    order_quantity_usdt: Decimal = Decimal('35')
    min_spread_rate: Decimal = Decimal('0.0005')
    max_open_pairs: int = 3
    stop_loss_usdt: Decimal = Decimal('5')

config = SpreadArbConfig()
```

Then run:

```bash
python spread/run_spread_arb.py
```

---

## Quick Reference

| Bot | Config File | Run Command |
|-----|-------------|-------------|
| Spread Arbitrage | `spread/config.py` | `python spread/run_spread_arb.py` |
| Hedge Mode | `hedge/config.py` | `python hedge_mode.py --exchange <name>` |
| Trading Bot | `trading_config.py` | `python runbot.py` |

---

## Troubleshooting

**Problem**: Bot doesn't start after changing config

**Solution**: Check for validation errors:
```bash
python -c "from spread.config import config"
```

**Problem**: Wrong account credentials being used

**Solution**: Verify `env_file` setting in config.py points to the correct .env file

**Problem**: Configuration changes not taking effect

**Solution**: Make sure you've edited the correct config file and restarted the bot

---

## Best Practices

1. **Version Control**: Commit config.py files to track configuration changes
2. **Documentation**: Add comments explaining why you chose specific values
3. **Testing**: Test configuration changes in a safe environment first
4. **Backup**: Keep working configurations as comments before making changes
5. **Validation**: Always validate configuration before running in production

---

## Example: Complete Spread Configuration

```python
# spread/config.py
"""
Spread Arbitrage Configuration

This configuration is optimized for ETH-USDT spread trading
between Extended and Lighter exchanges.
"""
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class SpreadArbConfig:
    """
    Configuration for spread arbitrage bot.

    Risk Level: Medium
    Expected Return: 0.05% per trade
    Max Drawdown: $5 USDT
    """

    # ========== Trading Parameters ==========
    ticker: str = 'ETH'                           # Trading pair
    order_quantity_usdt: Decimal = Decimal('35')  # $35 per order
    env_file: str = '.env'                        # Account credentials

    # ========== Spread Settings ==========
    min_spread_rate: Decimal = Decimal('0.0005')  # 0.05% minimum spread
    latency_buffer: Decimal = Decimal('0.0001')   # 0.01% execution buffer

    # ========== Position Management ==========
    max_open_pairs: int = 3                       # Max 3 concurrent positions
    max_holding_time: int = 300                   # Close after 5 minutes

    # ========== Profit/Loss Settings ==========
    profit_target_rate: Decimal = Decimal('0.0005')  # 0.05% profit target
    stop_loss_usdt: Decimal = Decimal('5')        # $5 stop loss per position

    # ========== Risk Control ==========
    slippage_tolerance: Decimal = Decimal('0.001')    # 0.1% max slippage
    max_lighter_depth_ratio: Decimal = Decimal('0.5') # Use 50% of Lighter depth

    # ========== Logging ==========
    log_level: str = 'INFO'

    def __post_init__(self):
        """Validate configuration parameters."""
        if self.min_spread_rate <= 0:
            raise ValueError("min_spread_rate must be greater than 0")
        if self.min_spread_rate <= self.latency_buffer:
            raise ValueError("min_spread_rate must be greater than latency_buffer")
        if self.order_quantity_usdt <= 0:
            raise ValueError("order_quantity_usdt must be greater than 0")
        # ... additional validations

# Default configuration instance
config = SpreadArbConfig()
```

This configuration is ready to use. Simply run:

```bash
python spread/run_spread_arb.py
```
