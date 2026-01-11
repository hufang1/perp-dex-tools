# Concurrent Execution API Contract

**Feature**: 011-fix-lighter-hedge
**Version**: 1.0.0
**Date**: 2026-01-11

## Overview

This document defines the API contract for the concurrent execution system that implements dual-leg IOC orders. The API ensures sub-5ms send time gaps and sub-500ms total execution latency.

---

## Core API: ConcurrentExecutor

### `execute_dual_leg_orders()`

Execute Extended and Lighter orders concurrently with IOC behavior.

**Signature**:
```python
async def execute_dual_leg_orders(
    self,
    extended_params: OrderParams,
    lighter_params: OrderParams,
    timeout_ms: float = 500.0
) -> ConcurrentOrderResult
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `extended_params` | `OrderParams` | Yes | Extended order parameters (side, quantity, price, etc.) |
| `lighter_params` | `OrderParams` | Yes | Lighter order parameters (side, quantity, price, etc.) |
| `timeout_ms` | `float` | No | Maximum execution time (default: 500ms) |

**Returns**: `ConcurrentOrderResult`

**Performance Requirements**:
- `send_gap_ms < 5.0` (95th percentile)
- `total_latency_ms < 500.0` (90th percentile)

**Error Handling**:
- `asyncio.TimeoutError`: Raised if execution exceeds `timeout_ms`
- `NetworkError`: Raised if either exchange is unreachable

**Example**:
```python
result = await concurrent_executor.execute_dual_leg_orders(
    extended_params=OrderParams(
        side='buy',
        quantity=Decimal('0.35'),
        price=Decimal('2450.00'),
        post_only=False  # IOC behavior
    ),
    lighter_params=OrderParams(
        side='sell',
        quantity=Decimal('0.35'),
        price=Decimal('2460.00'),
        order_type='IOC'
    ),
    timeout_ms=500.0
)

if result.is_both_filled:
    logger.info(f"双边成交，发送时间差: {result.send_gap_ms:.2f}ms")
elif result.is_legging:
    logger.critical(f"单腿持仓，触发回滚: {result.legging_side}")
```

---

### `emergency_close_position()`

Execute emergency market order close for rollback (used when legging detected).

**Signature**:
```python
async def emergency_close_position(
    self,
    exchange: str,  # 'extended' or 'lighter'
    side: str,      # 'buy' or 'sell'
    quantity: Decimal,
    timeout_ms: float = 500.0
) -> LegRollbackEvent
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `exchange` | `str` | Yes | Target exchange ('extended' or 'lighter') |
| `side` | `str` | Yes | Close side ('buy' to close short, 'sell' to close long) |
| `quantity` | `Decimal` | Yes | Quantity to close |
| `timeout_ms` | `float` | No | Maximum rollback time (default: 500ms) |

**Returns**: `LegRollbackEvent`

**Performance Requirements**:
- `rollback_latency_ms < 500.0` (95th percentile)
- Must use market orders or aggressive pricing to ensure execution

**Example**:
```python
rollback = await concurrent_executor.emergency_close_position(
    exchange='extended',
    side='sell',  # Close long position
    quantity=Decimal('0.35'),
    timeout_ms=500.0
)

if rollback.rollback_success:
    logger.critical(f"闪电回滚成功，延迟: {rollback.rollback_latency_ms:.2f}ms")
else:
    logger.critical(f"闪电回滚失败: {rollback.rollback_error}")
```

---

## Exchange Client APIs

### Lighter Client: `place_ioc_order()`

Place an IOC order on Lighter exchange.

**Signature**:
```python
async def place_ioc_order(
    self,
    contract_id: str,
    quantity: Decimal,
    price: Decimal,
    side: str
) -> OrderResult
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `contract_id` | `str` | Yes | Market symbol (e.g., 'ETH-USD') |
| `quantity` | `Decimal` | Yes | Order quantity |
| `price` | `Decimal` | Yes | Limit price (for IOC) |
| `side` | `str` | Yes | Order side ('buy' or 'sell') |

**Returns**: `OrderResult`

**Behavior**:
- Uses `ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL`
- Returns immediately (no wait loops)
- Supports partial fills

**Example**:
```python
result = await lighter_client.place_ioc_order(
    contract_id='ETH-USD',
    quantity=Decimal('0.35'),
    price=Decimal('2460.00'),
    side='sell'
)

if result.success:
    logger.info(f"IOC订单成交: {result.filled_qty}/{result.size}")
```

---

### Extended Client: `place_open_order()` (existing)

Extended uses existing taker order API (post_only=False) for IOC behavior.

**Signature**:
```python
async def place_open_order(
    self,
    contract_id: str,
    quantity: Decimal,
    direction: str,
    post_only: bool = False  # False = IOC behavior
) -> OrderResult
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `contract_id` | `str` | Yes | Market symbol |
| `quantity` | `Decimal` | Yes | Order quantity |
| `direction` | `str` | Yes | Order direction ('buy' or 'sell') |
| `post_only` | `bool` | No | If False, use taker (IOC behavior) |

**Returns**: `OrderResult`

**Example**:
```python
result = await extended_client.place_open_order(
    contract_id='ETH-USD',
    quantity=Decimal('0.35'),
    direction='buy',
    post_only=False  # IOC: cross spread immediately
)
```

---

## Validation APIs

### `validate_profitability()`

Check if trade is profitable after all costs.

**Signature**:
```python
async def validate_profitability(
    self,
    spread_rate: Decimal,
    extended_price: Decimal,
    lighter_price: Decimal
) -> ProfitabilityCheck
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `spread_rate` | `Decimal` | Yes | Current spread rate (e.g., 0.0010 for 0.10%) |
| `extended_price` | `Decimal` | Yes | Extended price |
| `lighter_price` | `Decimal` | Yes | Lighter price |

**Returns**: `ProfitabilityCheck`

**Validation Rules**:
- `net_profit = spread_rate - total_fees - expected_slippage`
- `is_profitable = (net_profit > min_net_profit)`
- Warning if `total_fees > 0.0006` (0.06%)

**Example**:
```python
check = await profit_calculator.validate_profitability(
    spread_rate=Decimal('0.0010'),  # 0.10%
    extended_price=Decimal('2450.00'),
    lighter_price=Decimal('2460.00')
)

if check.is_profitable:
    logger.info(f"净利润: {check.net_profit_rate:.4%}")
else:
    logger.warning(f"利润不足: {check.rejection_reason}")
```

---

### `check_data_freshness()`

Verify orderbook data is fresh enough for trading.

**Signature**:
```python
async def check_data_freshness(
    self,
    extended_orderbook: Orderbook,
    lighter_orderbook: Orderbook
) -> DataFreshnessResult
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `extended_orderbook` | `Orderbook` | Yes | Extended orderbook snapshot |
| `lighter_orderbook` | `Orderbook` | Yes | Lighter orderbook snapshot |

**Returns**: `DataFreshnessResult`

**Validation Rules**:
- `is_fresh = (max(extended_age, lighter_age) < 500ms)`
- `warning_level`: 0 (fresh), 1 (stale but OK), 2 (too old, reject)

**Example**:
```python
freshness = await data_freshness_checker.check_data_freshness(
    extended_orderbook=extended_orderbook,
    lighter_orderbook=lighter_orderbook
)

if not freshness.is_fresh:
    logger.warning(f"数据过期({freshness.data_age_ms:.0f}ms)，放弃本次机会")
    return
```

---

## Data Models

### `OrderParams`

Order parameters for execution.

```python
@dataclass
class OrderParams:
    side: str              # 'buy' or 'sell'
    quantity: Decimal      # Order quantity
    price: Decimal         # Limit price
    post_only: bool = False  # For Extended (False = IOC)
    order_type: str = 'IOC'   # For Lighter ('IOC' or 'LIMIT')
    slippage_tolerance: Decimal = Decimal('0.0005')  # 0.05%
```

### `ConcurrentOrderResult`

Result of concurrent dual-leg execution.

```python
@dataclass
class ConcurrentOrderResult:
    # Extended results
    extended_success: bool
    extended_order_id: Optional[str]
    extended_filled_qty: Decimal
    extended_filled_price: Optional[Decimal]
    extended_error: Optional[str]

    # Lighter results
    lighter_success: bool
    lighter_order_id: Optional[str]
    lighter_filled_qty: Decimal
    lighter_filled_price: Optional[Decimal]
    lighter_error: Optional[str]

    # Performance metrics
    send_gap_ms: float
    total_latency_ms: float

    # State flags
    is_both_filled: bool
    is_legging: bool
    is_both_failed: bool
```

### `LegRollbackEvent`

Emergency rollback execution result.

```python
@dataclass
class LegRollbackEvent:
    pair_id: int
    legging_side: str
    rollback_latency_ms: float
    rollback_success: bool
    filled_qty: Decimal
    filled_price: Optional[Decimal]
    rollback_error: Optional[str]
```

### `ProfitabilityCheck`

Profitability validation result.

```python
@dataclass
class ProfitabilityCheck:
    spread_rate: Decimal
    total_fees: Decimal
    expected_slippage: Decimal
    min_net_profit: Decimal
    net_profit_rate: Decimal
    is_profitable: bool
    rejection_reason: Optional[str]
```

### `DataFreshnessResult`

Data freshness check result.

```python
@dataclass
class DataFreshnessResult:
    data_age_ms: float
    is_fresh: bool
    extended_age_ms: float
    lighter_age_ms: float
    warning_level: int
    warning_message: Optional[str]
```

---

## Performance SLAs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Send time gap | < 5ms (95th %ile) | `abs(send_a_ts - send_b_ts)` |
| Total latency | < 500ms (90th %ile) | Order placement to result |
| Rollback latency | < 500ms (95th %ile) | Legging detection to close |
| Data freshness check | < 1ms | Timestamp comparison |
| Profitability check | < 1ms | Simple arithmetic |

---

## Error Codes

| Code | Description | Action |
|------|-------------|--------|
| `E001` | Send gap > 5ms | Log warning, continue |
| `E002` | Total latency > 500ms | Log warning, check order status |
| `E003` | Single-leg detected | Trigger rollback immediately |
| `E004` | Rollback failed | Retry up to 3 times, then pause |
| `E005` | Data too old (>500ms) | Skip this opportunity |
| `E006` | Not profitable | Skip this opportunity |
| `E007` | Network timeout | Check connection, retry |

---

## Testing Requirements

### Unit Tests
- Mock exchange clients for isolated testing
- Test timeout scenarios
- Test partial fills
- Test all error codes

### Integration Tests
- Test against sandbox exchanges
- Measure actual send gaps
- Measure actual latencies
- Test rollback with real orders

### Performance Tests
- Load test: 100 orders/minute
- Latency distribution: p50, p95, p99
- Memory leak detection
- Concurrent order limits

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-11 | Initial API definition |
