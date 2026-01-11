# Implementation Plan: 修复Lighter对冲失败和实现双腿并发IOC订单系统

**Branch**: `011-fix-lighter-hedge` | **Date**: 2026-01-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-fix-lighter-hedge/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

**Primary Requirement**: 修复导致"Extended疯狂开仓但Lighter无响应"的严重bug，实现符合需求文档02.md要求的双腿并发IOC订单系统。当前系统开仓成功率仅10%（30次尝试仅3次成功），根本原因是`exchanges/lighter.py`使用限价单+10秒等待成交循环，破坏了并发性。

**Technical Approach**:
1. **实现真正的并发执行**: 使用`asyncio.gather`同时发送Extended和Lighter订单，确保发送时间差<5ms
2. **实现IOC订单支持**: 为Lighter客户端添加`place_ioc_order`方法，替代限价单+等待模式
3. **闪电回滚机制**: 检测到单腿持仓后在500ms内执行市价平仓
4. **动态利润验证**: 严格计算净利（价差率 - 双边手续费 - 滑点成本 - 最小净利要求）
5. **数据时效性检查**: 拒绝延迟>500ms的订单簿数据
6. **简化平仓策略**: 基于净价差变化而非时间优先级

## Technical Context

**Language/Version**: Python 3.10+ (primarily using 3.11+ features)
**Primary Dependencies**:
- `asyncio` - Async programming framework
- `websockets>=12.0` - WebSocket client library
- `decimal.Decimal` - Precise financial calculations
- `pytest` - Unit testing framework with asyncio support
- `lighter-sdk==0.1.4` - Lighter exchange SDK (needs IOC wrapper)
- `x10-python-trading-starknet==0.0.10` - Extended exchange SDK
- `tenacity>=9.1.2` - Retry mechanisms
- `python-dotenv` - Environment variable management
- `pydantic` - Data validation

**Storage**:
- In-memory state storage (订单状态、持仓信息)
- File-based logging (`logs/trade.log`, `logs/performance.log`)
- CSV export (`data/trades_*.csv`, `data/operations_*.csv`)

**Testing**:
- `pytest` with asyncio support
- Unit tests in `tests/` directory
- Integration tests in `tests/integration/`
- Mock exchange clients for isolated testing
- Performance benchmarking with timing assertions

**Target Platform**: Linux server (production), macOS/Windows (development)
**Project Type**: Single project (Python trading bot with spread arbitrage logic)
**Performance Goals**:
- Dual-leg order send time gap < 5ms (95th percentile)
- Total execution latency < 500ms (90th percentile)
- Order placement to fill < 100ms (for IOC orders)
- Single-leg position detection < 100ms
- Flash rollback execution < 500ms (95th percentile)
- Tick-to-trade latency < 50ms

**Constraints**:
- Must use IOC (Immediate or Cancel) orders, no limit orders with wait loops
- Must reject orderbook data older than 500ms
- Must verify net profit > 0 before opening positions
- Must detect and rollback single-leg positions within 500ms
- Taker fee sum must be < 0.06% for 0.07% spread profitability
- No `time.sleep()` or blocking wait loops allowed

**Scale/Scope**:
- Handles up to 10 concurrent spread pairs
- Processes 100+ opportunities per minute
- Manages $35-$1000 USDT trading capital
- Monitors 2 exchanges (Extended, Lighter)
- 287 existing test files to maintain compatibility

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Current Constitution Status**: The constitution file (`.specify/memory/constitution.md`) contains template placeholders without project-specific principles. This is a new constitution that needs to be established.

**Proposed Constitution for this Project**:

### I. Performance-First Trading System
- All trading operations must be non-blocking and async-first
- Latency budgets are non-negotiable (5ms send gap, 500ms total execution)
- Performance metrics must be logged for every trade

### II. Safety-Critical Design
- Single-leg positions are critical failures requiring immediate rollback
- Circuit breakers must halt trading on failure rate thresholds
- No partial state - either both legs succeed or both legs fail

### III. Test-Driven Development (NON-NEGOTIABLE)
- TDD mandatory: Tests written → User approved → Tests fail → Then implement
- Red-Green-Refactor cycle strictly enforced
- All edge cases must have explicit test coverage

### IV. Observability
- Every trade must log complete performance metrics
- [CRITICAL] logs for safety events (legging, rollback, data expiry)
- CSV export for post-trade analysis

### V. Simplicity and YAGNI
- Complex multi-priority closing logic rejected in favor of simple spread-based rules
- No premature optimization beyond latency requirements
- Remove dead code (e.g., unused maker order logic)

**Gate Evaluation**:
- ✅ No violations detected - feature aligns with proposed constitution
- ⚠️ Constitution needs to be formalized and ratified
- 📋 Re-check after Phase 1 design to ensure technical decisions align

## Project Structure

### Documentation (this feature)

```text
specs/011-fix-lighter-hedge/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── concurrent_execution_api.md
│   └── performance_monitoring_api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
spread/                      # 价差套利模块
├── bot.py                   # 套利机器人主逻辑 (MODIFY: integrate concurrent execution)
├── models.py                # 数据模型 (MODIFY: add ConcurrentOrderResult, LegRollbackEvent, etc.)
├── config.py                # 配置类 (MODIFY: add IOC and rollback settings)
├── hedge_manager.py         # 对冲管理器 (REFACTOR: implement concurrent IOC hedging)
├── concurrent_executor.py   # 并发执行器 (NEW: core IOC order orchestration)
├── ioc_order_manager.py     # IOC订单管理器 (NEW: IOC order pricing and creation)
├── leg_rollback_handler.py  # 单腿回滚处理器 (NEW: flash rollback mechanism)
├── profit_calculator.py     # 利润计算器 (NEW: net profit verification)
├── performance_monitor.py   # 性能监控器 (ENHANCE: add detailed metrics)
└── data_freshness_checker.py # 数据时效性检查器 (NEW: orderbook age validation)

exchanges/                   # 交易所客户端
├── extended.py              # Extended交易所客户端 (VERIFY: IOC support)
└── lighter.py               # Lighter交易所客户端 (MODIFY: add place_ioc_order method)

tests/                       # 测试文件
├── test_concurrent_executor.py      # 并发执行器测试 (NEW)
├── test_ioc_order_manager.py         # IOC订单管理器测试 (NEW)
├── test_leg_rollback_handler.py      # 单腿回滚处理器测试 (NEW)
├── test_profit_calculator.py         # 利润计算器测试 (NEW)
├── test_data_freshness_checker.py    # 数据时效性检查测试 (NEW)
├── test_lighter_ioc_orders.py        # Lighter IOC订单测试 (NEW)
└── integration/
    ├── test_concurrent_opening_integration.py   # 并发开仓集成测试 (NEW)
    ├── test_leg_rollback_integration.py         # 单腿回滚集成测试 (NEW)
    └── test_end_to_end_ioc_trading.py           # 端到端IOC交易测试 (NEW)

logs/                        # 交易日志目录
├── trade.log               # 交易日志文件
└── performance.log         # 性能日志文件 (ENHANCED)

data/                        # 数据导出目录
├── trades_YYYY_MM_DD.csv  # 交易记录导出
├── orders_YYYY_MM_DD.csv  # 订单记录导出
└── performance_YYYY_MM_DD.csv  # 性能指标导出 (NEW)
```

**Structure Decision**: Single project structure with modular spread trading components. The existing `spread/` and `exchanges/` directories will be enhanced with new modules for IOC order handling and concurrent execution. All new code follows the existing async/await patterns and uses the same testing framework.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | No constitution violations | Feature aligns with proposed constitution principles |

## Phase 0: Research & Technical Decisions

### Research Questions

1. **Lighter SDK IOC Order Support**
   - Question: Does `lighter-sdk==0.1.4` natively support IOC orders?
   - Impact: If not supported, need to implement wrapper using limit orders with immediate cancellation
   - Research needed: SDK documentation, source code analysis

2. **Extended IOC Order Implementation**
   - Question: How does `x10-python-trading-starknet` implement IOC orders?
   - Impact: Need to match Extended's IOC pattern for consistency
   - Research needed: Extended client code, SDK examples

3. **WebSocket Order Callback Race Conditions**
   - Question: Can WebSocket callbacks arrive before order ID is set?
   - Impact: Need caching mechanism if true
   - Research needed: Existing WebSocket handling patterns in codebase

4. **Market Order Support for Rollback**
   - Question: Do both exchanges support market orders for emergency rollback?
   - Impact: If not, need aggressive limit pricing strategy
   - Research needed: Exchange API documentation

5. **Orderbook Timestamp Availability**
   - Question: Do orderbook snapshots include millisecond timestamps?
   - Impact: Critical for 500ms freshness check
   - Research needed: WebSocket message structure

### Research Artifacts

See `research.md` for detailed findings and decisions.
