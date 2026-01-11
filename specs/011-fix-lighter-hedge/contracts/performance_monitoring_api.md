# Performance Monitoring API Contract

**Feature**: 011-fix-lighter-hedge
**Version**: 1.0.0
**Date**: 2026-01-11

## Overview

This document defines the performance monitoring API for tracking key metrics in the concurrent IOC trading system. All critical trading operations must be monitored with millisecond precision.

---

## Core API: PerformanceMonitor

### `record_order_placement()`

Record order placement with high-precision timestamps.

**Signature**:
```python
def record_order_placement(
    self,
    exchange: str,
    order_id: str,
    send_timestamp: float,
    opportunity_timestamp: float
) -> None
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `exchange` | `str` | Yes | Exchange name ('extended' or 'lighter') |
| `order_id` | `str` | Yes | Unique order identifier |
| `send_timestamp` | `float` | Yes | Order send time (ms since epoch) |
| `opportunity_timestamp` | `float` | Yes | Original opportunity detection time (ms) |

**Metrics Calculated**:
- `tick_to_trade_latency_ms = send_timestamp - opportunity_timestamp`

**Example**:
```python
performance_monitor.record_order_placement(
    exchange='extended',
    order_id='EXT-12345',
    send_timestamp=1704960123456.789,
    opportunity_timestamp=1704960123450.000
)
# tick_to_trade_latency_ms = 6.789ms
```

---

### `record_concurrent_execution()`

Record dual-leg concurrent execution metrics.

**Signature**:
```python
def record_concurrent_execution(
    self,
    extended_order_id: str,
    lighter_order_id: str,
    send_a_ts: float,
    send_b_ts: float,
    result: ConcurrentOrderResult
) -> None
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `extended_order_id` | `str` | Yes | Extended order ID |
| `lighter_order_id` | `str` | Yes | Lighter order ID |
| `send_a_ts` | `float` | Yes | Extended send timestamp (ms) |
| `send_b_ts` | `float` | Yes | Lighter send timestamp (ms) |
| `result` | `ConcurrentOrderResult` | Yes | Execution result |

**Metrics Calculated**:
- `send_gap_ms = abs(send_a_ts - send_b_ts)`
- `total_latency_ms = result.completion_ts - min(send_a_ts, send_b_ts)`

**Example**:
```python
performance_monitor.record_concurrent_execution(
    extended_order_id='EXT-12345',
    lighter_order_id='LIT-67890',
    send_a_ts=1704960123456.100,
    send_b_ts=1704960123456.103,
    result=concurrent_result
)
# send_gap_ms = 0.003ms (3 microseconds)
```

---

### `record_rollback()`

Record emergency rollback execution.

**Signature**:
```python
def record_rollback(
    self,
    exchange: str,
    rollback_event: LegRollbackEvent
) -> None
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `exchange` | `str` | Yes | Exchange being rolled back |
| `rollback_event` | `LegRollbackEvent` | Yes | Rollback event details |

**Metrics Recorded**:
- `rollback_latency_ms` (from event)
- Success/failure status
- Error message if failed

**Example**:
```python
performance_monitor.record_rollback(
    exchange='extended',
    rollback_event=rollback_event
)
```

---

### `get_performance_summary()`

Get performance statistics for a time window.

**Signature**:
```python
def get_performance_summary(
    self,
    window_seconds: int = 60
) -> PerformanceSummary
```

**Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `window_seconds` | `int` | No | Time window (default: 60 seconds) |

**Returns**: `PerformanceSummary`

**Example**:
```python
summary = performance_monitor.get_performance_summary(window_seconds=300)

print(f"总订单数: {summary.total_orders}")
print(f"成功率: {summary.success_rate:.2%}")
print(f"平均发送时间差: {summary.avg_send_gap_ms:.2f}ms")
print(f"平均总延迟: {summary.avg_total_latency_ms:.2f}ms")
print(f"回滚次数: {summary.rollback_count}")
```

---

## Data Models

### `PerformanceSummary`

Performance statistics summary.

```python
@dataclass
class PerformanceSummary:
    # Order counts
    total_orders: int
    successful_orders: int
    failed_orders: int
    rollback_count: int

    # Success rates
    success_rate: float           # successful_orders / total_orders
    legging_rate: float           # rollback_count / total_orders

    # Latency metrics (ms)
    avg_send_gap_ms: float
    p95_send_gap_ms: float
    p99_send_gap_ms: float
    max_send_gap_ms: float

    avg_total_latency_ms: float
    p95_total_latency_ms: float
    p99_total_latency_ms: float
    max_total_latency_ms: float

    avg_tick_to_trade_ms: float
    p95_tick_to_trade_ms: float

    avg_rollback_latency_ms: float
    p95_rollback_latency_ms: float

    # SLA compliance
    send_gap_sla_compliant: bool   # % with send_gap < 5ms
    latency_sla_compliant: bool    # % with latency < 500ms
    rollback_sla_compliant: bool   # % with rollback < 500ms

    # Time window
    window_start_ts: float
    window_end_ts: float
```

### `OrderMetric`

Individual order performance metric.

```python
@dataclass
class OrderMetric:
    order_id: str
    exchange: str
    timestamp: float
    tick_to_trade_latency_ms: float
    send_gap_ms: float            # For concurrent orders
    total_latency_ms: float
    is_success: bool
    is_legging: bool
    is_rollback: bool
    rollback_latency_ms: Optional[float]
```

---

## Performance Thresholds

### Configuration

```python
@dataclass
class PerformanceThresholds:
    # Latency thresholds (ms)
    max_send_gap_ms: float = 5.0
    max_total_latency_ms: float = 500.0
    max_rollback_latency_ms: float = 500.0
    max_tick_to_trade_ms: float = 50.0

    # SLA compliance targets
    send_gap_sla_target: float = 0.95      # 95% must be < 5ms
    latency_sla_target: float = 0.90       # 90% must be < 500ms
    rollback_sla_target: float = 0.95      # 95% must be < 500ms

    # Alert thresholds
    alert_on_legging_rate: float = 0.05    # Alert if > 5% legging
    alert_on_failure_rate: float = 0.10    # Alert if > 10% failure
```

---

## Logging Format

### Performance Log Entry

```
[PERF] ts=1704960123456.789 | event=order_placement | exchange=extended | order_id=EXT-12345 | tick_to_trade=6.789ms
[PERF] ts=1704960123457.123 | event=concurrent_exec | send_gap=0.003ms | total_latency=150.456ms | result=both_filled
[PERF] ts=1704960123500.000 | event=rollback | exchange=extended | latency=234.567ms | success=True
```

### Critical Performance Events

```
[CRITICAL] ts=1704960123456.789 | event=send_gap_violation | send_gap=15.234ms | threshold=5.0ms | order_id=EXT-12345
[CRITICAL] ts=1704960123457.123 | event=latency_violation | latency=850.000ms | threshold=500.0ms | order_id=LIT-67890
[CRITICAL] ts=1704960123500.000 | event=rollback_failed | exchange=extended | error=timeout | retries=3
```

---

## CSV Export Format

### Performance Data Export

File: `data/performance_YYYY_MM_DD.csv`

```csv
timestamp,exchange,order_id,tick_to_trade_ms,send_gap_ms,total_latency_ms,is_success,is_legging,rollback_latency_ms
1704960123456.789,extended,EXT-12345,6.789,0.003,150.456,True,False,
1704960123457.123,lighter,LIT-67890,8.123,0.003,150.456,True,False,
1704960123500.000,extended,EXT-12346,12.456,1.234,520.000,True,True,234.567
```

---

## Alerting

### Alert Conditions

| Alert Type | Condition | Severity | Action |
|------------|-----------|----------|--------|
| `SEND_GAP_VIOLATION` | `send_gap_ms > 5.0` | Warning | Log warning, continue |
| `LATENCY_VIOLATION` | `total_latency_ms > 500.0` | Warning | Log warning, check order |
| `ROLLBACK_SLOW` | `rollback_latency_ms > 500.0` | Critical | Log critical, retry |
| `HIGH_LEGGING_RATE` | `legging_rate > 5%` | Critical | Log critical, pause |
| `HIGH_FAILURE_RATE` | `failure_rate > 10%` | Critical | Log critical, pause |
| `SLA_NON_COMPLIANT` | `sla_compliant < 90%` | Critical | Log critical, alert |

---

## Integration Points

### Bot Integration

```python
# In spread/bot.py

async def _open_new_pair_concurrent(...):
    # Record opportunity time
    opportunity_ts = time.time() * 1000

    # Execute concurrent orders
    result = await self.concurrent_executor.execute_dual_leg_orders(...)

    # Record metrics
    self.performance_monitor.record_concurrent_execution(
        extended_order_id=result.extended_order_id,
        lighter_order_id=result.lighter_order_id,
        send_a_ts=result.send_a_ts,
        send_b_ts=result.send_b_ts,
        result=result
    )

    # Handle rollback if needed
    if result.is_legging:
        rollback = await self.leg_rollback_handler.execute_emergency_close(...)
        self.performance_monitor.record_rollback(
            exchange=rollback.exchange,
            rollback_event=rollback
        )
```

### Reporting Integration

```python
# In main loop or status command

def print_performance_report():
    summary = performance_monitor.get_performance_summary(window_seconds=300)

    print(f"""
    Performance Report (last 5 minutes):
    =====================================
    Total Orders: {summary.total_orders}
    Success Rate: {summary.success_rate:.2%}
    Legging Rate: {summary.legging_rate:.2%}

    Send Gap: {summary.avg_send_gap_ms:.2f}ms avg (p95: {summary.p95_send_gap_ms:.2f}ms)
    Total Latency: {summary.avg_total_latency_ms:.2f}ms avg (p95: {summary.p95_total_latency_ms:.2f}ms)
    Rollback Latency: {summary.avg_rollback_latency_ms:.2f}ms avg

    SLA Compliance:
    - Send Gap < 5ms: {summary.send_gap_sla_compliant}
    - Latency < 500ms: {summary.latency_sla_compliant}
    - Rollback < 500ms: {summary.rollback_sla_compliant}
    """)
```

---

## Performance Targets

| Metric | Target | Threshold | Critical |
|--------|--------|-----------|----------|
| Send gap (p95) | < 3ms | < 5ms | > 10ms |
| Total latency (p90) | < 300ms | < 500ms | > 1000ms |
| Tick-to-trade (p95) | < 30ms | < 50ms | > 100ms |
| Rollback latency (p95) | < 300ms | < 500ms | > 1000ms |
| Success rate | > 95% | > 90% | < 80% |
| Legging rate | < 2% | < 5% | > 10% |

---

## Testing Requirements

### Unit Tests
- Test metric recording accuracy
- Test summary calculation
- Test SLA compliance checking
- Test alert triggering

### Performance Tests
- Test high-frequency recording (1000+ metrics/sec)
- Test memory usage over time
- Test CSV export performance
- Test concurrent metric access

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-11 | Initial API definition |
