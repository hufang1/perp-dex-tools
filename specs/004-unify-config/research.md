# Research: Unified Configuration Management

**Feature**: 004-unify-config | **Date**: 2026-01-09

## Overview

This document captures research findings and technical decisions for consolidating configuration management across three trading bot systems. The current state shows command-line arguments overriding config.py settings, making configuration files ineffective.

## Current State Analysis

### Spread Arbitrage Bot (`spread/run_spread_arb.py`)

**Current Configuration Flow**:
1. `argparse` in `parse_arguments()` defines all parameters with defaults
2. Command-line args are parsed
3. `SpreadArbConfig` is instantiated with argparse values
4. Result: config.py defaults are never used; command-line always wins

**Problem**: The `spread/config.py` file has a `SpreadArbConfig` dataclass with defaults, but `run_spread_arb.py` creates a NEW instance using argparse values, completely ignoring the config.py file.

**Command-line arguments present** (from lines 45-82):
- `--ticker`, `--env-file`, `--quantity`, `--min-spread`, `--latency-buffer`
- `--profit-target`, `--time-close-threshold`, `--max-pairs`, `--max-holding-time`
- `--stop-loss`, `--slippage-tolerance`, `--log-level`, `--no-prioritize-closing`

### Hedge Mode Bot (`hedge_mode.py`)

**Current Configuration Flow**:
1. `argparse` in `parse_arguments()` defines parameters
2. Command-line args are parsed
3. Individual hedge bot classes are instantiated with argparse values
4. Result: No centralized config file exists

**Problem**: No `hedge/config.py` file exists. Configuration is scattered across individual hedge mode implementation files.

**Command-line arguments present** (from lines 49-67):
- `--exchange`, `--ticker`, `--size`, `--iter`, `--fill-timeout`
- `--sleep`, `--env-file`, `--max-position`, `--v2`

### Trading Bot (`runbot.py`)

**Current Configuration Flow**:
1. `argparse` in `parse_arguments()` defines parameters
2. Command-line args are parsed
3. `TradingConfig` is instantiated with argparse values
4. Result: No centralized config file exists

**Problem**: No `trading_config.py` file exists at project root.

**Command-line arguments present** (from lines 22-52):
- `--exchange`, `--ticker`, `--quantity`, `--take-profit`, `--direction`
- `--max-orders`, `--wait-time`, `--env-file`, `--grid-step`
- `--stop-price`, `--pause-price`, `--boost`

## Technical Decisions

### Decision 1: Configuration Pattern - Direct Instantiation

**Decision**: Use direct module-level instantiation of configuration classes

**Rationale**:
- Python's module import system naturally provides singleton behavior
- No need for complex configuration loading logic
- Type-safe through dataclass/type hints
- IDE autocomplete support for configuration options
- Existing `SpreadArbConfig` dataclass can remain unchanged

**Implementation Pattern**:
```python
# spread/config.py
@dataclass
class SpreadArbConfig:
    ticker: str = 'ETH'
    order_quantity_usdt: Decimal = Decimal('35')
    # ... all parameters with defaults

# Module-level default instance
config = SpreadArbConfig()
```

**Alternatives Considered**:
1. **YAML/JSON config files**: Rejected because adds new file format and parsing complexity
2. **Environment variables only**: Rejected because doesn't meet user requirement for "config.py file"
3. **Configuration loader class**: Rejected as over-engineering for simple parameter passing

### Decision 2: Environment File Selection

**Decision**: Support `env_file` parameter within config.py to specify which .env file to load

**Rationale**:
- User story P2 requires multiple account support
- Keeping env_file in config.py allows switching accounts without command-line args
- Consistent with "single source of truth" principle

**Implementation Pattern**:
```python
# spread/config.py
@dataclass
class SpreadArbConfig:
    env_file: str = '.env'  # Default .env file
    ticker: str = 'ETH'
    # ... other parameters
```

**Alternatives Considered**:
1. **Keep --env-file argument**: Rejected because violates "no command-line args" requirement
2. **Multiple config files for different accounts**: Rejected as redundant duplication

### Decision 3: Command-line Argument Handling

**Decision**: Remove argparse parsers entirely from run scripts, except for exchange selector in hedge_mode.py

**Rationale**:
- User explicitly stated: "I don't expect to specify parameters when running the script"
- FR-010 requires: "Command-line argument parsers MUST be removed or deprecated"
- Simplifies code and removes confusion about which config source takes precedence

**Exception**: `hedge_mode.py` retains `--exchange` argument (and `--v2` flag) because:
- Required to determine which hedge bot implementation to use
- Not a trading parameter, but a script selector
- Aligns with FR-004: "except for script selection (which bot to run) and exchange selection"

**Alternatives Considered**:
1. **Keep argparse with deprecation warning**: Rejected as creates technical debt
2. **Support both config.py and args with config.py taking precedence**: Rejected as adds complexity

### Decision 4: Hedge Mode Configuration

**Decision**: Create new `hedge/config.py` with `HedgeConfig` dataclass

**Rationale**:
- No centralized config exists for hedge mode currently
- Consistent pattern with spread module
- Multiple hedge implementations (apex, backpack, edgex, grvt, nado) benefit from shared config

**Structure**:
```python
# hedge/config.py
@dataclass
class HedgeConfig:
    # Common parameters
    exchange: str = 'edgex'
    ticker: str = 'BTC'
    order_quantity: Decimal = Decimal('0.01')
    iterations: int = 20
    fill_timeout: int = 5
    sleep_time: int = 0
    max_position: Decimal = Decimal('0')
    env_file: str = '.env'

    # V2 flag for grvt (handled in hedge_mode.py, not config)
```

**Alternatives Considered**:
1. **Separate config for each exchange**: Rejected as duplicates common parameters
2. **Keep current scattered approach**: Rejected as fails to address user requirement

### Decision 5: Trading Bot Configuration

**Decision**: Create new `trading_config.py` at project root with `TradingConfig` class

**Rationale**:
- `runbot.py` currently uses argparse but has no config file
- Trading bot is at project root level (not in spread/ or hedge/ directories)
- Consistent pattern with other bots

**Structure**:
```python
# trading_config.py
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
```

**Alternatives Considered**:
1. **Put in trading_bot.py**: Rejected as mixes configuration with logic
2. **Use SpreadArbConfig**: Rejected as parameters don't align

### Decision 6: Configuration Validation Strategy

**Decision**: Keep existing validation in `SpreadArbConfig.__post_init__()` and add similar validation to other config classes

**Rationale**:
- Existing validation in lines 75-103 of spread/config.py is comprehensive
- Dataclass `__post_init__` is ideal place for validation
- Provides clear error messages before bot starts trading

**Validation Requirements** (from spec):
- min_spread_rate > 0
- min_spread_rate > latency_buffer
- max_open_pairs > 0
- order_quantity_usdt > 0
- max_lighter_depth_ratio in (0, 1]
- profit_target_rate > 0
- max_holding_time > time_close_threshold

**Implementation Pattern**:
```python
def __post_init__(self):
    if self.min_spread_rate <= 0:
        raise ValueError("min_spread_rate must be greater than 0")
    if self.min_spread_rate <= self.latency_buffer:
        raise ValueError("min_spread_rate must be greater than latency_buffer")
    # ... additional validations
```

**Alternatives Considered**:
1. **Pydantic models**: Rejected as adds dependency and changes existing SpreadArbConfig structure
2. **Separate validation function**: Rejected as less integrated with dataclass

### Decision 7: Environment Variable Overrides

**Decision**: Keep existing `SpreadArbConfig.from_env()` classmethod and add similar methods to other config classes

**Rationale**:
- FR-009 requires: "System MUST respect the SpreadArbConfig.from_env() method"
- Provides flexibility for deployment environments
- Secondary configuration layer (config.py primary, env vars secondary)

**Usage Pattern**:
```python
# Primary: Use config.py defaults
from spread.config import config

# Secondary: Override with environment variables if needed
from spread.config import SpreadArbConfig
config = SpreadArbConfig.from_env()
```

**Alternatives Considered**:
1. **Remove from_env() support**: Rejected as breaks backward compatibility (FR-007)
2. **Make from_env() the default**: Rejected as violates "config.py as single source of truth"

## Implementation Phases

### Phase 1: Spread Arbitrage (P0 - Critical Path)
1. Modify `spread/config.py`: Add module-level `config` instance
2. Modify `spread/run_spread_arb.py`: Remove argparse, import `config` from config.py
3. Add tests for config loading and validation

### Phase 2: Hedge Mode (P1)
1. Create `hedge/config.py` with `HedgeConfig` dataclass
2. Modify `hedge_mode.py`: Remove most argparse args, import from hedge.config
3. Keep `--exchange` and `--v2` args only
4. Add tests for hedge config loading

### Phase 3: Trading Bot (P1)
1. Create `trading_config.py` with `TradingConfig` dataclass
2. Modify `runbot.py`: Remove argparse, import from trading_config
3. Add tests for trading config loading

## Dependencies and Integrations

### Dependencies
- **python-dotenv**: Already in use for .env file loading
- **decimal.Decimal**: Already in use for financial calculations
- **dataclasses**: Standard library (Python 3.7+)

### Integration Points
1. **SpreadArbConfig**: Used by `spread/bot.py`, must maintain compatibility
2. **TradingConfig**: Used by `trading_bot.py`, must maintain compatibility
3. **Environment loading**: Must integrate with existing dotenv.load_dotenv() calls

## Testing Strategy

### Unit Tests
- Test configuration class instantiation
- Test validation error messages
- Test default values
- Test from_env() overrides

### Integration Tests
- Test run scripts execute correctly with config.py
- Test error handling for invalid config
- Test env_file switching
- Test that no command-line args are required

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing workflows | High | Comprehensive testing; document migration clearly |
| Users forget to update config.py | Medium | Provide example config files with clear comments |
| Validation too strict | Low | Make validation match existing requirements exactly |
| Performance regression | Very Low | Configuration loading is one-time at startup |

## Summary

All technical decisions align with user requirements:
- ✅ Config.py is single source of truth
- ✅ No command-line arguments (except script/exchange selection)
- ✅ Backward compatible with existing dataclasses
- ✅ Support for multiple accounts via env_file
- ✅ Clear validation error messages
