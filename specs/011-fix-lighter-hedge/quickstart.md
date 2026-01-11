# Quickstart Guide: 修复Lighter对冲失败和实现双腿并发IOC订单系统

**Feature**: 011-fix-lighter-hedge
**Branch**: `011-fix-lighter-hedge`
**Last Updated**: 2026-01-11

## Overview

This guide helps you get started with the fixed concurrent IOC trading system. The system now correctly executes dual-leg orders with <5ms send gap and <500ms total latency.

---

## What Changed?

### Before (Broken)
- Extended orders: Immediate (~50ms)
- Lighter orders: 10-second wait loop
- **Result**: Sequential execution, 10% success rate

### After (Fixed)
- Extended orders: Immediate (~50ms)
- Lighter orders: IOC immediate (~100ms)
- **Result**: True concurrent execution, >90% success rate target

---

## Prerequisites

1. **Python 3.10+** installed
2. **Exchange credentials** configured in `.env`
3. **Fee rates verified**: Taker fees must sum to <0.06% for profitability
4. **WebSocket connectivity** to both exchanges

---

## Installation

```bash
# Clone and checkout feature branch
git checkout 011-fix-lighter-hedge

# Install dependencies
pip install -r requirements.txt

# Verify installation
pytest tests/test_concurrent_executor.py -v
```

---

## Configuration

### 1. Update `spread/config.py`

```python
@dataclass
class SpreadArbConfig:
    # IOC订单设置
    use_ioc_orders: bool = True  # 启用IOC订单
    ioc_slippage_tolerance_rate: Decimal = Decimal('0.0005')  # 0.05%

    # 并发执行设置
    max_execution_latency_ms: float = 500.0
    order_timeout_ms: int = 500  # IOC订单超时

    # 风险控制
    extended_taker_fee: Decimal = Decimal('0.00025')  # 0.025%
    lighter_taker_fee: Decimal = Decimal('0.00020')   # 0.020%
    min_profit_rate: Decimal = Decimal('0.0002')      # 0.02%

    # 数据时效性
    max_data_delay_ms: float = 500.0  # 最大数据延迟

    # 安全监控
    safety_enabled: bool = True
    safety_hedge_failure_threshold: float = 0.30  # 30%
    safety_position_imbalance_threshold: float = 0.50  # 50%
```

### 2. Verify Fee Rates

```bash
# Check your fee rates before starting
python -c "
from decimal import Decimal
ext_fee = Decimal('0.00025')  # Extended taker fee
lit_fee = Decimal('0.00020')  # Lighter taker fee
total = ext_fee + lit_fee
print(f'Total taker fee: {total:.4%}')
if total > Decimal('0.0006'):
    print('WARNING: Fees too high for 0.07% spreads!')
else:
    print('OK: Fees allow profitability')
"
```

---

## Running the Bot

### Basic Usage

```bash
# Run with default settings
python spread/bot.py --ticker ETH --size 35 --max-pairs 3

# Run with verbose logging
python spread/bot.py --ticker ETH --size 35 --max-pairs 3 --log-level DEBUG

# Run with performance monitoring
python spread/bot.py --ticker ETH --size 35 --max-pairs 3 --enable-perf-mon
```

### Key Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--ticker` | ETH | Trading pair symbol |
| `--size` | 35 | Position size in USDT |
| `--max-pairs` | 3 | Maximum concurrent pairs |
| `--log-level` | INFO | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `--enable-perf-mon` | False | Enable performance monitoring |
| `--dry-run` | False | Simulate trades without execution |

---

## Monitoring

### Real-Time Logs

```bash
# Terminal 1: Watch main logs
tail -f logs/trade.log

# Terminal 2: Watch performance logs
tail -f logs/performance.log

# Terminal 3: Watch for critical events
tail -f logs/trade.log | grep CRITICAL
```

### Key Log Patterns

**Successful Trade**:
```
[INFO] Dual-leg orders sent, gap: 2.3ms ✅
[INFO] Both filled, total latency: 145.6ms ✅
[INFO] Position opened: EXT-12345 / LIT-67890
```

**Legging Detected** (should be rare):
```
[CRITICAL] Legging detected: Extended filled, Lighter failed ⚠️
[CRITICAL] Flash rollback initiated: Extended 0.35 ETH
[INFO] Rollback complete: 234.5ms, closed 0.35 ETH
```

**Performance Warning**:
```
[WARNING] Send gap violation: 8.3ms > 5.0ms threshold
[WARNING] Total latency high: 623.4ms > 500.0ms threshold
```

### Performance Metrics

```bash
# View performance summary (last 5 minutes)
python -c "
from spread.performance_monitor import PerformanceMonitor
pm = PerformanceMonitor()
summary = pm.get_performance_summary(window_seconds=300)
print(summary)
"
```

Expected metrics:
- Send gap: < 5ms (95th percentile)
- Total latency: < 500ms (90th percentile)
- Success rate: > 90%
- Legging rate: < 5%

---

## Data Export

### CSV Files

```bash
# View today's trades
cat data/trades_$(date +%Y_%m_%d).csv

# View today's performance metrics
cat data/performance_$(date +%Y_%m_%d).csv

# View today's operations
cat data/operations_$(date +%Y_%m_%d).csv
```

### CSV Format

**Trades** (`data/trades_YYYY_MM_DD.csv`):
```csv
timestamp,pair_id,extended_order_id,lighter_order_id,open_price,close_size,profit_usd,profit_pct
1704960123456,1,EXT-12345,LIT-67890,0.10,35.0,3.50,0.45
```

**Performance** (`data/performance_YYYY_MM_DD.csv`):
```csv
timestamp,send_gap_ms,total_latency_ms,tick_to_trade_ms,is_success,is_legging
1704960123456,2.3,145.6,12.3,True,False
```

---

## Testing

### Unit Tests

```bash
# Run all unit tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_concurrent_executor.py -v
pytest tests/test_ioc_order_manager.py -v
pytest tests/test_leg_rollback_handler.py -v
pytest tests/test_profit_calculator.py -v
pytest tests/test_data_freshness_checker.py -v
```

### Integration Tests

```bash
# Run integration tests
pytest tests/integration/ -v

# Test concurrent execution
pytest tests/integration/test_concurrent_opening_integration.py -v

# Test rollback mechanism
pytest tests/integration/test_leg_rollback_integration.py -v
```

### Performance Tests

```bash
# Run performance benchmarks
pytest tests/test_performance_benchmarks.py -v

# Test latency distribution
pytest tests/test_latency_distribution.py -v --benchmark-only
```

---

## Troubleshooting

### Issue: "Send gap too high"

**Symptoms**: Send gap consistently > 5ms

**Diagnosis**:
```bash
# Check system load
top

# Check network latency
ping -c 10 exchange-api.com
```

**Solutions**:
- Reduce system load
- Use wired network connection
- Move closer to exchange servers

---

### Issue: "High legging rate"

**Symptoms**: > 5% of trades result in single-leg positions

**Diagnosis**:
```bash
# Check exchange connection status
# View legging logs
grep "Legging detected" logs/trade.log | tail -20
```

**Solutions**:
- Verify WebSocket connectivity
- Check exchange API status
- Increase slippage tolerance slightly
- Reduce position size

---

### Issue: "Not profitable"

**Symptoms**: All opportunities rejected with "not profitable"

**Diagnosis**:
```bash
# Check current spread
python -c "
from decimal import Decimal
spread = Decimal('0.0007')  # 0.07%
fees = Decimal('0.00045')   # 0.045%
min_profit = Decimal('0.0002')  # 0.02%
required = fees + min_profit
print(f'Spread: {spread:.4%}')
print(f'Required: {required:.4%}')
print(f'Profitable: {spread > required}')
"
```

**Solutions**:
- Verify fee rates are correct
- Increase spread threshold if needed
- Negotiate lower fees with exchanges

---

### Issue: "Data too old"

**Symptoms**: Frequent "data expired" warnings

**Diagnosis**:
```bash
# Check WebSocket connectivity
grep "WebSocket" logs/trade.log | tail -20
```

**Solutions**:
- Check internet connection
- Restart WebSocket connections
- Increase `max_data_delay_ms` slightly (not recommended)

---

## Performance Tuning

### Optimize for Low Latency

```python
# In spread/config.py
ioc_slippage_tolerance_rate: Decimal = Decimal('0.0003')  # Lower slippage
max_execution_latency_ms: float = 300.0  # Stricter timeout
```

### Optimize for High Success Rate

```python
# In spread/config.py
ioc_slippage_tolerance_rate: Decimal = Decimal('0.0008')  # Higher slippage
max_execution_latency_ms: float = 1000.0  # Looser timeout
```

### Optimize for Small Capital

```python
# In spread/config.py
min_profit_rate: Decimal = Decimal('0.0003')  # Higher min profit
ioc_slippage_tolerance_rate: Decimal = Decimal('0.0003')  # Lower slippage
```

---

## Safety Features

### Circuit Breaker

The system automatically pauses trading when:
- Failure rate > 30% (configurable)
- Legging rate > 50% (configurable)
- Data delay > 500ms consistently

```bash
# Check circuit breaker status
grep "Circuit breaker" logs/trade.log | tail -5
```

### Flash Rollback

Automatic rollback of single-leg positions within 500ms:

```bash
# View rollback events
grep "Flash rollback" logs/trade.log | tail -10
```

### Data Freshness Check

Prevents trading on stale data:

```bash
# View data freshness warnings
grep "data expired" logs/trade.log | tail -10
```

---

## Next Steps

1. **Verify configuration**: Check all settings in `spread/config.py`
2. **Run unit tests**: Ensure all tests pass
3. **Start with dry-run**: Test without real money
4. **Monitor logs**: Watch for CRITICAL events
5. **Start small**: Begin with minimum position size
6. **Scale gradually**: Increase position size as confidence grows

---

## Getting Help

- **Documentation**: See `CLAUDE.md` for detailed architecture
- **API Contracts**: See `specs/011-fix-lighter-hedge/contracts/`
- **Research**: See `specs/011-fix-lighter-hedge/research.md`
- **Requirements**: See `docs/requirement/02.md`

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-11 | Initial quickstart guide |
