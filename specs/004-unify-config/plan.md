# Implementation Plan: Unified Configuration Management

**Branch**: `004-unify-config` | **Date**: 2026-01-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-unify-config/spec.md`

## Summary

Consolidate configuration management across three trading bot systems (spread arbitrage, hedge mode, and modular trading bot) by removing command-line argument dependencies and making config.py files the single source of truth. Currently, command-line arguments override config.py settings, making configuration files ineffective. The solution will modify run scripts to read exclusively from config.py files while maintaining backward compatibility with existing configuration dataclasses and supporting environment variable overrides as a secondary layer.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, logging, python-dotenv, pydantic, pytest
**Storage**: In-memory configuration from Python config.py files; .env files for credentials
**Testing**: pytest for unit and integration tests
**Target Platform**: Linux/macOS server environments for trading bots
**Project Type**: Single project with multiple bot modules (spread, hedge, trading_bot)
**Performance Goals**: Configuration loading must complete in <100ms; no impact on trading execution speed
**Constraints**: Must maintain backward compatibility with SpreadArbConfig dataclass; cannot break existing from_env() method
**Scale/Scope**: Affects 3 run scripts, 3+ config files, ~15-20 configuration parameters across all bots

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: ⚠️ No constitution file exists in `.specify/memory/constitution.md`

The constitution template is present but not yet configured. Since no governing principles are defined, this feature proceeds with:
- Python dataclass pattern (existing in SpreadArbConfig)
- Configuration file as single source of truth (user requirement)
- Backward compatibility with existing structures (FR-007)

## Project Structure

### Documentation (this feature)

```text
specs/004-unify-config/
├── spec.md              # Feature specification
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── config-schema.yaml  # Configuration validation schema
└── checklists/
    └── requirements.md  # Specification quality checklist
```

### Source Code (repository root)

```text
# Existing project structure (to be modified)
spread/                      # Spread arbitrage module
├── config.py               # MODIFIED: Add default instance creation
├── run_spread_arb.py       # MODIFIED: Remove argparse, use config.py
├── bot.py                  # Uses SpreadArbConfig
├── calculator.py
├── order_manager.py
└── hedge_manager.py

hedge/                       # Hedge mode module
├── config.py               # NEW: Create hedge configuration class
├── hedge_mode.py           # MODIFIED: Remove argparse, use config.py
├── hedge_mode_bp.py
├── hedge_mode_apex.py
├── hedge_mode_edgex.py
├── hedge_mode_grvt.py
└── hedge_mode_nado.py

exchanges/                   # Exchange clients
├── extended.py
├── lighter.py
├── apex.py
├── backpack.py
├── edgex.py
├── grvt.py
└── nado.py

tests/                       # Test files
├── test_config_loading.py  # NEW: Test configuration loading
├── test_config_validation.py # NEW: Test configuration validation
└── integration/
    └── test_bot_config.py  # NEW: Integration tests for config

# Root level files
runbot.py                    # MODIFIED: Remove argparse, use trading_config.py
trading_bot.py              # Uses TradingConfig
```

**Structure Decision**: Single project structure with three bot modules (spread, hedge, trading_bot). Each module will have its own config.py file. Run scripts will be modified to remove argparse and directly instantiate from config files. No new directory structure needed - this is a refactoring of existing configuration loading patterns.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No complexity tracking required - no constitution violations identified.
