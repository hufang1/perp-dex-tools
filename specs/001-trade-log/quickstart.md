# Quickstart Guide: Trade Logging Feature

**Feature**: 001-trade-log
**Branch**: `001-trade-log`
**Last Updated**: 2026-01-09

## Overview

This feature adds detailed trade logging to the spread arbitrage system, enabling operators to verify calculated profits against actual exchange positions. The system automatically records all opening and closing trades with complete price details and step-by-step profit/loss calculations.

## What Changed

### New Module

- **`spread/trade_logger.py`**: New trade logging module that writes detailed trade entries to `logs/trade.log`

### Modified Files

- **`spread/bot.py`**: Integrated trade logging into opening and closing trade flows

### New Directory

- **`logs/`**: Created automatically if it doesn't exist, contains `trade.log` file

## How It Works

### 1. Automatic Logging

The system automatically logs trade events as they occur:

```
Opening Trade → Log Entry Written
Closing Trade → Log Entry Written with PnL Calculation
Unhedged Position → Warning Log Entry Written
```

### 2. Log File Location

```
project-root/
└── logs/
    └── trade.log  ← Human-readable trade records
```

### 3. Log Entry Format

**Opening Entry Example**:
```
=== TRADE OPENED ===
Timestamp: 2026-01-09 12:34:56.789
Pair ID: 1
Direction: LONG (Extended BUY, Lighter SELL)

Extended Exchange:
  Order ID: ext_12345
  Price: $3450.50
  Quantity: 0.0100 ETH

Lighter Exchange:
  Order ID: lt_67890
  Price: $3455.75
  Quantity: 0.0100 ETH

Spread Information:
  Absolute Spread: $5.25
  Spread Rate: 0.1521%
=====================
```

**Closing Entry Example**:
```
=== TRADE CLOSED ===
Timestamp: 2026-01-09 12:35:26.789
Pair ID: 1
Direction: LONG
Holding Time: 30.0 seconds

Opening Prices (Reference):
  Extended: $3450.50
  Lighter: $3455.75

Closing Prices:
  Extended Order ID: ext_12346
  Extended Price: $3451.00
  Lighter Order ID: lt_67891
  Lighter Price: $3455.25

Profit/Loss Calculation:
  Extended PnL: ($3451.00 - $3450.50) × 0.0100 = $0.005
  Lighter PnL: ($3455.75 - $3455.25) × 0.0100 = $0.005
  Total PnL: $0.005 + $0.005 = $0.01
  Return: 0.0290%
======================
```

## Running the System

### 1. Start the Bot

No configuration changes needed. Run as normal:

```bash
cd /Users/hufang/Desktop/web3\ project/perp/hufangperp
python spread/bot.py --ticker ETH --size 35 --max-pairs 3
```

### 2. Verify Logging is Working

After the first trade, check the log file:

```bash
cat logs/trade.log
```

You should see formatted trade entries like the examples above.

### 3. Monitor Log Size

The stats reporter (runs every 60 seconds) shows basic information:

```
📊 统计报告
  持仓套利对: 2
  ...
```

Log file size is not currently tracked in stats but can be checked manually:

```bash
ls -lh logs/trade.log
```

## Manual Verification Workflow

### 1. After a Trade Closes

Open the log file in your text editor:

```bash
code logs/trade.log
# or
vim logs/trade.log
# or
open logs/trade.log
```

### 2. Find the Trade Entry

Search for the Pair ID (e.g., "Pair ID: 1") to find both opening and closing entries.

### 3. Verify Against Exchange Positions

1. **Check Extended Exchange**:
   - Login to your Extended exchange account
   - Find the order by Order ID from the log
   - Verify the price and quantity match

2. **Check Lighter Exchange**:
   - Login to your Lighter exchange account
   - Find the order by Order ID from the log
   - Verify the price and quantity match

3. **Verify PnL Calculation**:
   - Extended PnL = (Close Price - Open Price) × Quantity
   - Lighter PnL = (Open Price - Close Price) × Quantity
   - Total PnL = Extended PnL + Lighter PnL
   - Compare with your actual exchange balances

### 4. Identify Discrepancies

If your calculated profit doesn't match exchange reality:

- Check that both order IDs are found on exchanges
- Verify prices match what was actually executed
- Check that quantities are correct
- Verify fees are accounted for (not in log but affect real PnL)
- Look for unhedged position warnings in the log

## Troubleshooting

### Problem: No Log File Created

**Symptoms**: `logs/trade.log` doesn't exist after trades

**Solutions**:
1. Check if trades actually occurred (look for "✅ 开仓成功" in console)
2. Check file permissions: `ls -la logs/`
3. Check for error messages in console output
4. Verify `spread/trade_logger.py` exists

### Problem: Log File Has No Entries

**Symptoms**: File exists but empty

**Solutions**:
1. Verify trades completed successfully (check console logs)
2. Look for error messages like "Trade logging failed"
3. Check disk space: `df -h`
4. Restart the bot to reinitialize logger

### Problem: Log Entries Incomplete

**Symptoms**: Entries are cut off or malformed

**Solutions**:
1. Check disk space (may be full)
2. Look for write errors in console
3. Verify file wasn't edited externally
4. Check for file system errors

### Problem: Cannot Write to Log File

**Symptoms**: Console shows "Cannot write to log file" errors

**Solutions**:
1. Check directory permissions: `ls -ld logs/`
2. Fix permissions: `chmod 755 logs/`
3. Check if file is locked by another process
4. Verify disk is not read-only

### Problem: PnL Doesn't Match Exchange

**Symptoms**: Calculated profit in log differs from actual exchange balance

**Solutions**:
1. Verify you're looking at the correct order IDs
2. Check if trading fees are applied (fees reduce real profit)
3. Verify price and quantity precision (decimal places)
4. Check for slippage (actual execution vs expected price)
5. Look for unhedged position warnings (partial fills)
6. Verify both exchanges show the same trade

## Development Testing

### 1. Unit Tests

Run the trade logger unit tests:

```bash
pytest tests/test_trade_logger.py -v
```

### 2. Integration Tests

Run with test exchange mocks:

```bash
pytest tests/integration/test_trade_logging_integration.py -v
```

### 3. Manual Testing

Create a test trade cycle:

```bash
# Start bot with small position size
python spread/bot.py --ticker ETH --size 10 --max-pairs 1

# Wait for one complete trade cycle (open + close)

# Verify log file
cat logs/trade.log

# Verify calculations manually
# (See "Manual Verification Workflow" above)
```

## Best Practices

### 1. Regular Log Review

**Frequency**: After each trading session or daily

**Actions**:
- Review all closing entries
- Verify PnL calculations make sense
- Check for unhedged position warnings
- Identify any anomalies

### 2. Log Rotation (Manual)

**When**: Log file approaches 100 MB

**How**:
```bash
# Stop the bot
# Archive old log
mv logs/trade.log logs/trade_2026-01-09.log
gzip logs/trade_2026-01-09.log

# Restart bot (will create new logs/trade.log)
```

### 3. Backup Important Logs

**Before**:
- Clearing log files
- Major system changes
- Exchange migrations

**How**:
```bash
cp logs/trade.log logs/trade_backup_$(date +%Y%m%d).log
```

### 4. Monitor for Errors

**Watch for**:
- "Trade logging failed" messages
- "UNHEDGED POSITION" warnings
- Missing entries (trades without logs)
- Malformed entries

**Action**: Investigate immediately if errors appear

## Next Steps

### For Operators

1. Read your first trade log entry and verify the format
2. Complete one manual verification against exchange positions
3. Establish a regular log review schedule

### For Developers

1. Review `spread/trade_logger.py` implementation
2. Check test coverage in `tests/test_trade_logger.py`
3. Consider adding automated log parsing tools (future feature)

## Support

### Documentation

- **Specification**: `specs/001-trade-log/spec.md`
- **Implementation Plan**: `specs/001-trade-log/plan.md`
- **Data Model**: `specs/001-trade-log/data-model.md`
- **Interface Contract**: `specs/001-trade-log/contracts/trade-logger-interface.md`

### Issues

If you encounter problems not covered in this guide:

1. Check the console output for error messages
2. Review the log file for anomalies
3. Verify your exchange positions match the log
4. Document the issue with log entries and exchange screenshots

## Summary

The trade logging feature runs automatically without configuration. Simply:

1. ✅ Start the bot normally
2. ✅ Trades are logged to `logs/trade.log`
3. ✅ Review logs to verify calculations
4. ✅ Investigate discrepancies immediately

The system is designed to never interrupt trading, even if logging fails. Always verify your actual exchange positions against the log entries.
