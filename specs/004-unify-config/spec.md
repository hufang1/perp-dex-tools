# Feature Specification: Unified Configuration Management

**Feature Branch**: `004-unify-config`
**Created**: 2026-01-09
**Status**: Draft
**Input**: User description: "我现在有一个问题是 我看现在的配置文件整体来说有两个 一个是运行脚本的参数控制比如 python run_spread_arb.py --stop-loss 这类的。另外一种是在config.py中配置。现在的问题是 现在好像都是由 运行脚本时的参数控制。config.py文件中的配置完全是失效的。这和我的核心相违背。其实我并不期望运行脚本时能指定参数，我只希望参数在统一的config文件中配置"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single Configuration File for Spread Arbitrage (Priority: P1)

As a trader running the spread arbitrage bot, I want to configure all trading parameters in a single config.py file so that I can manage my settings centrally without remembering command-line arguments.

**Why this priority**: This is the core user pain point. Currently, command-line arguments override config.py settings, making the config file ineffective. This directly impacts the user's ability to maintain consistent trading configurations.

**Independent Test**: Can be fully tested by running `python spread/run_spread_arb.py` without any arguments and verifying that all parameters are read from `spread/config.py`, with the bot operating correctly using those values.

**Acceptance Scenarios**:

1. **Given** a properly configured `spread/config.py` with all parameters set, **When** I run `python spread/run_spread_arb.py` without any arguments, **Then** the bot starts and uses all values from config.py (ticker, quantity, min_spread, stop_loss, etc.)
2. **Given** a `spread/config.py` with `ticker='BTC'` and `order_quantity_usdt=50`, **When** I run the script, **Then** the bot trades BTC with 50 USDT per order
3. **Given** a `spread/config.py` with `min_spread_rate=Decimal('0.0008')`, **When** the bot evaluates opportunities, **Then** it only opens positions when spread exceeds 0.0008

---

### User Story 2 - Single Configuration File for Hedge Mode (Priority: P1)

As a trader running the hedge mode bot, I want to configure all parameters in a single config.py file so that I can manage settings centrally across different exchanges.

**Why this priority**: Hedge mode is used across multiple exchanges (backpack, extended, apex, grvt, edgex, nado). Consistent configuration management is critical for operational efficiency.

**Independent Test**: Can be fully tested by running `python hedge_mode.py --exchange edgex` with only the exchange parameter and verifying all other settings are read from `hedge/config.py`.

**Acceptance Scenarios**:

1. **Given** a properly configured `hedge/config.py` with `order_quantity=Decimal('0.01')` and `iterations=20`, **When** I run `python hedge_mode.py --exchange edgex`, **Then** the bot uses 0.01 size and runs 20 iterations from config
2. **Given** a `hedge/config.py` with `fill_timeout=10`, **When** the bot waits for order fills, **Then** it times out after 10 seconds as specified in config

---

### User Story 3 - Single Configuration File for Trading Bot (Priority: P1)

As a trader running the modular trading bot, I want to configure all parameters in a single config.py file so that I can manage trading strategies consistently.

**Why this priority**: The trading bot supports multiple exchanges and configurations. Centralized configuration ensures consistency and reduces operational errors.

**Independent Test**: Can be fully tested by running `python runbot.py` without arguments and verifying all parameters are read from `trading_config.py`.

**Acceptance Scenarios**:

1. **Given** a properly configured `trading_config.py` with `exchange='edgex'`, `ticker='ETH'`, and `quantity=Decimal('0.1')`, **When** I run `python runbot.py`, **Then** the bot starts trading ETH on edgex with 0.1 quantity
2. **Given** a `trading_config.py` with `take_profit=Decimal('0.03')`, **When** the bot reaches profit targets, **Then** it closes positions at 0.03 USDT profit

---

### User Story 4 - Environment File Selection (Priority: P2)

As a trader with multiple accounts, I want to specify which .env file to use in the config file so that I can switch between accounts without command-line arguments.

**Why this priority**: Supporting multiple accounts is important for traders managing different portfolios, but it's secondary to the core configuration consolidation.

**Independent Test**: Can be tested by setting `env_file` in config.py and verifying the correct credentials are loaded when running the bot.

**Acceptance Scenarios**:

1. **Given** a config.py with `env_file='.env.account1'`, **When** I run the bot, **Then** it loads credentials from `.env.account1`
2. **Given** a config.py with `env_file='.env.production'`, **When** I run the bot, **Then** it uses production account credentials

---

### User Story 5 - Configuration Validation and Error Messages (Priority: P2)

As a trader, I want clear error messages when my configuration is invalid so that I can fix issues quickly without debugging cryptic errors.

**Why this priority**: Good error handling improves user experience and reduces support burden, but the system can function without perfect error messages.

**Independent Test**: Can be tested by intentionally setting invalid values in config.py and verifying helpful error messages are displayed.

**Acceptance Scenarios**:

1. **Given** a config.py with `min_spread_rate=Decimal('-0.001')` (negative value), **When** I run the bot, **Then** I see a clear error message like "min_spread_rate must be greater than 0"
2. **Given** a config.py with `max_holding_time=10` and `time_close_threshold=20` (threshold > max), **When** I run the bot, **Then** I see a clear error message like "max_holding_time must be greater than time_close_threshold"

---

### Edge Cases

- What happens when the config.py file is missing or malformed? → System should exit with a clear error message indicating the config file issue
- What happens when required environment variables are missing from the .env file? → System should exit with a clear error listing missing variables
- What happens when config.py values have invalid types (e.g., string instead of Decimal)? → System should validate types and provide clear error messages
- What happens when a user tries to run with command-line arguments after the change? → System should either ignore arguments or show a message that arguments are deprecated (to be decided in planning)
- What happens when config values are outside acceptable ranges (e.g., negative quantities)? → System should validate ranges and provide specific error messages

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read all trading parameters from `spread/config.py` for the spread arbitrage bot
- **FR-002**: System MUST read all trading parameters from `hedge/config.py` for the hedge mode bot
- **FR-003**: System MUST read all trading parameters from `trading_config.py` for the modular trading bot
- **FR-004**: System MUST NOT require any command-line arguments except for script selection (which bot to run) and exchange selection (for hedge mode)
- **FR-005**: System MUST support env_file configuration within the config.py file to specify which .env file to load
- **FR-006**: System MUST validate all configuration values on startup and exit with clear error messages if validation fails
- **FR-007**: System MUST maintain backward compatibility with existing SpreadArbConfig dataclass structure
- **FR-008**: System MUST support all currently configurable parameters via config.py (ticker, quantity, min_spread, stop_loss, max_pairs, max_holding_time, profit_target, slippage_tolerance, etc.)
- **FR-009**: System MUST respect the SpreadArbConfig.from_env() method for environment variable overrides as a secondary configuration layer
- **FR-010**: Command-line argument parsers MUST be removed or deprecated from run scripts

### Key Entities

- **SpreadArbConfig**: Configuration dataclass containing all spread arbitrage parameters (ticker, order_quantity_usdt, min_spread_rate, latency_buffer, max_open_pairs, max_holding_time, stop_loss_usdt, slippage_tolerance, profit_target_rate, time_close_profit_threshold, etc.)
- **HedgeConfig**: Configuration class for hedge mode parameters (exchange, ticker, order_quantity, iterations, fill_timeout, sleep_time, max_position, env_file)
- **TradingConfig**: Configuration class for modular trading bot parameters (exchange, ticker, quantity, take_profit, direction, max_orders, wait_time, grid_step, stop_price, pause_price, boost_mode)
- **Environment Configuration**: .env file containing API credentials and account-specific settings

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can run any bot (spread arbitrage, hedge mode, trading bot) with zero command-line arguments (except script name and exchange selector for hedge mode)
- **SC-002**: All configuration changes require modifying only the appropriate config.py file, not command-line arguments
- **SC-003**: Configuration validation catches 100% of invalid parameter values before trading begins
- **SC-004**: Error messages clearly indicate which configuration parameter is invalid and why
- **SC-005**: Time to change any trading parameter is reduced to under 30 seconds (edit config.py, save, run script)
- **SC-006**: New users can successfully configure and run a bot by editing only one file (config.py) and referencing existing examples
