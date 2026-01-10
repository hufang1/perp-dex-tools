# Data Model: 价差套利磨损修复

**Feature**: 001-fix-spread-loss
**Date**: 2026-01-10

## 概述

本文档定义修复价差套利磨损功能涉及的数据模型扩展。主要修改集中在现有实体的字段扩展，以及新增日志事件结构。

## 实体定义

### 1. SpreadOpportunity（价差机会）

**位置**: `spread/calculator.py`返回值

**新增字段**：

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `maker_timeout_ms` | int | maker单超时时间（毫秒） | 5000 |
| `use_maker_order` | bool | 是否使用maker单 | True |
| `expected_fill_rate` | float | 预期成交率 | 0.8 |

**完整结构**：
```python
{
    'type': 'buy_extended_sell_lighter' | 'sell_extended_buy_lighter',
    'side': 'buy' | 'sell',
    'spread': Decimal,
    'spread_rate': Decimal,
    'expected_profit_rate': Decimal,
    'extended_price': Decimal,      # Extended挂单价格
    'lighter_price': Decimal,       # Lighter taker预期价格
    'quantity': Decimal,
    'maker_timeout_ms': int,        # 新增
    'use_maker_order': bool,        # 新增
    'expected_fill_rate': float     # 新增
}
```

### 2. SpreadPair（套利对）

**位置**: `spread/spread_pair.py`

**新增字段**：

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `open_order_type` | str | 开仓订单类型 | "MAKER" / "TAKER" |
| `close_order_type` | str | 平仓订单类型 | "MAKER" / "TAKER" |
| `maker_wait_duration_ms` | int | maker单等待时长 | 2340 |
| `open_extended_fee_type` | str | 开仓Extended手续费类型 | "MAKER" / "TAKER" |
| `close_extended_fee_type` | str | 平仓Extended手续费类型 | "MAKER" / "TAKER" |
| `open_extended_fee_amount` | Decimal | 开仓Extended手续费 | 0.00695 |
| `close_extended_fee_amount` | Decimal | 平仓Extended手续费 | 0.00696 |

**状态转换**：
```
[新建] → [开仓中] → [持仓中] → [平仓中] → [已平仓]
         ↓            ↓            ↓
    [开仓失败]    [强制平仓]    [平仓失败]
```

**新增状态**：
- `[maker等待中]` - maker单挂单等待成交
- `[转taker中]` - maker超时后转为taker

### 3. TradeLogEntry（交易日志条目）

**位置**: `spread/trade_logger.py`（新增）

**字段定义**：

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `timestamp` | str | ✅ | ISO 8601格式时间戳 |
| `level` | str | ✅ | DEBUG/INFO/WARN/ERROR |
| `event_type` | str | ✅ | 事件类型（见下表）|
| `data` | dict | ✅ | 事件数据 |

**事件类型列表**：

| event_type | 触发时机 | 关键数据字段 |
|------------|----------|--------------|
| SYSTEM_START | 程序启动 | config |
| SPREAD_OPPORTUNITY | 价差机会检测 | extended_bid/ask, lighter_bid/ask, decision |
| EXTENDED_ORDER_PLACED | Extended下单 | order_type, price, quantity, order_id |
| EXTENDED_FILLED | Extended成交 | filled_price, filled_quantity, wait_duration_ms, fee_type |
| EXTENDED_MAKER_TIMEOUT | Maker单超时 | wait_duration_ms, action |
| LIGHTER_HEDGE | Lighter对冲 | expected_price, actual_price, slippage_usdt |
| POSITION_OPENED | 开仓完成 | pair_id, extended, lighter, open_spread |
| POSITION_CLOSED | 平仓完成 | pair_id, pnl, fees, slippage |
| HOURLY_STATISTICS | 每小时统计 | trading, volume, pnl, fees |

### 4. SpreadArbConfig（配置）

**位置**: `spread/config.py`

**新增字段**：

| 字段名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `extended_maker_fee_rate` | Decimal | 0.0001 | Extended maker费率 |
| `extended_taker_fee_rate` | Decimal | 0.000225 | Extended taker费率 |
| `maker_timeout_seconds` | int | 5 | Maker单超时时间 |
| `maker_timeout_action` | str | "convert_to_taker" | 超时后动作 |
| `use_maker_orders` | bool | True | 是否使用maker单 |

## 数据流

### 开仓流程数据流

```
[价差机会检测]
    ↓
SpreadOpportunity {
    extended_price: 3090.00,
    lighter_price: 3103.00,
    use_maker_order: True
}
    ↓
[Extended下单]
    ↓
TradeLog {
    event_type: EXTENDED_ORDER_PLACED,
    data: { order_type: "MAKER", ... }
}
    ↓
[等待成交/超时]
    ↓
TradeLog {
    event_type: EXTENDED_FILLED 或 EXTENDED_MAKER_TIMEOUT,
    data: { ... }
}
    ↓
[Lighter对冲]
    ↓
TradeLog {
    event_type: LIGHTER_HEDGE,
    data: { slippage_usdt: 0.00226, ... }
}
    ↓
[创建套利对]
    ↓
SpreadPair {
    open_order_type: "MAKER",
    maker_wait_duration_ms: 2340,
    ...
}
    ↓
TradeLog {
    event_type: POSITION_OPENED,
    data: { ... }
}
```

### 平仓流程数据流

```
[平仓机会检测]
    ↓
TradeLog {
    event_type: SPREAD_OPPORTUNITY,
    data: { ... }
}
    ↓
[Extended平仓] + [Lighter平仓]
    ↓
TradeLog { event_type: EXTENDED_FILLED, ... }
TradeLog { event_type: LIGHTER_HEDGE, ... }
    ↓
[计算盈亏]
    ↓
SpreadPair {
    close_extended_fee_type: "MAKER",
    close_extended_fee_amount: 0.00696,
    ...
}
    ↓
TradeLog {
    event_type: POSITION_CLOSED,
    data: {
        pnl: { ... },
        fees: { ... },
        slippage: { ... }
    }
}
```

## 验证规则

### 价差机会验证

```python
# 做多机会
if opportunity['type'] == 'buy_extended_sell_lighter':
    assert opportunity['lighter_price'] == lighter_ask  # 必须用卖一价
    assert opportunity['extended_price'] == extended_bid
    assert opportunity['spread'] == lighter_ask - extended_bid

# 做空机会
if opportunity['type'] == 'sell_extended_buy_lighter':
    assert opportunity['lighter_price'] == lighter_bid  # 必须用买一价
    assert opportunity['extended_price'] == extended_ask
    assert opportunity['spread'] == extended_ask - lighter_bid
```

### 日志格式验证

```python
import json

# 每行必须是有效JSON
for line in open('logs/trade.log'):
    entry = json.loads(line)
    assert 'timestamp' in entry
    assert 'event_type' in entry
    assert 'data' in entry
```

## 性能考虑

### 日志写入性能

- **格式化开销**: JSON序列化 ~1-2ms
- **磁盘写入**: <10ms (SSD)
- **策略**: 异步写入，不阻塞交易

### 内存占用

- **SpreadPair**: ~1KB per instance
- **最大持仓**: 3个 × 1KB = 3KB
- **日志缓冲**: 1MB (滚动缓冲)

---

**数据模型状态**: 已完成，可以进入实施阶段。
