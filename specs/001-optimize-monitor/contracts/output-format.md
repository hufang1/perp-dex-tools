# Output Format Contract: 持仓监控输出

**Feature**: 001-optimize-monitor
**Version**: 1.0
**Date**: 2026-01-09

## Purpose

本文档定义了持仓监控输出的精确格式规范，确保实现的一致性和可测试性。

---

## Output Format Specification

### Case 1: 无活跃持仓

**触发条件**: `len(open_pairs) == 0`

**输出格式**:
```
📊 持仓监控汇总
   无活跃持仓
```

**示例**:
```
2026-01-09 10:30:45 INFO SpreadArbBot: 📊 持仓监控汇总
   无活跃持仓
```

---

### Case 2: 单个持仓

**触发条件**: `len(open_pairs) == 1`

**输出格式**:
```
📊 持仓监控汇总
   持仓 #1 (做多):
      持仓时间: 123秒 (剩余 1677秒)
      Extended仓位: 0.3500 @ $3114.70
      当前价格: $3115.50
      Lighter仓位: 0.3500 @ $3086.27
      当前价格: $3117.73
      当前已实现收益: $-15.00 ← 新增字段
      未实现盈亏: $-0.31
      距离盈利目标: $0.32
```

**示例日志**:
```
2026-01-09 10:30:45 INFO SpreadArbBot: 📊 持仓监控汇总
   持仓 #1 (做多):
      持仓时间: 89秒 (剩余 1711秒)
      Extended仓位: 0.0100 @ $3114.70
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3086.27
      当前价格: $3117.73
      当前已实现收益: $-0.31
      未实现盈亏: $-0.31
      距离盈利目标: $0.32
```

---

### Case 3: 多个持仓 (2-20个)

**触发条件**: `len(open_pairs) >= 2`

**输出格式**:
```
📊 持仓监控汇总
   持仓 #1 (做多):
      持仓时间: 89秒 (剩余 1711秒)
      Extended仓位: 0.0100 @ $3114.70
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3086.27
      当前价格: $3117.73
      当前已实现收益: $-0.31
      未实现盈亏: $-0.31
      距离盈利目标: $0.32
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   持仓 #2 (做多):
      持仓时间: 83秒 (剩余 1717秒)
      Extended仓位: 0.0100 @ $3115.80
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3087.57
      当前价格: $3117.73
      当前已实现收益: $-0.30
      未实现盈亏: $-0.30
      距离盈利目标: $0.32
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   持仓 #3 (做空):
      持仓时间: 77秒 (剩余 1723秒)
      Extended仓位: 0.0100 @ $3115.80
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3087.62
      当前价格: $3117.73
      当前已实现收益: $0.25
      未实现盈亏: $0.28
      距离盈利目标: $0.02
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   总持仓: 3 | 总未实现盈亏: $-0.33
```

**示例日志**:
```
2026-01-09 10:30:45 INFO SpreadArbBot: 📊 持仓监控汇总
   持仓 #1 (做多):
      持仓时间: 89秒 (剩余 1711秒)
      Extended仓位: 0.0100 @ $3114.70
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3086.27
      当前价格: $3117.73
      当前已实现收益: $-0.31
      未实现盈亏: $-0.31
      距离盈利目标: $0.32
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   持仓 #2 (做多):
      持仓时间: 83秒 (剩余 1717秒)
      Extended仓位: 0.0100 @ $3115.80
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3087.57
      当前价格: $3117.73
      当前已实现收益: $-0.30
      未实现盈亏: $-0.30
      距离盈利目标: $0.32
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   持仓 #3 (做多):
      持仓时间: 77秒 (剩余 1723秒)
      Extended仓位: 0.0100 @ $3115.80
      当前价格: $3115.50
      Lighter仓位: 0.0100 @ $3087.62
      当前价格: $3117.73
      当前已实现收益: $-0.30
      未实现盈亏: $-0.30
      距离盈利目标: $0.32
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   总持仓: 3 | 总未实现盈亏: $-0.91
```

---

### Case 4: 订单簿数据缺失

**触发条件**: `extended_bid/ask` 或 `lighter_bid/ask` 为 `None`

**输出格式**:
```
📊 持仓监控汇总
   ⚠️ Extended订单簿数据不可用
   持仓 #1 (做多):
      持仓时间: 123秒 (剩余 1677秒)
      Extended仓位: 0.3500 @ $3114.70
      当前价格: N/A
      Lighter仓位: 0.3500 @ $3086.27
      当前价格: $3117.73
      当前已实现收益: N/A
      未实现盈亏: N/A
      距离盈利目标: N/A
```

---

### Case 5: 持仓正在平仓 (is_closing=True)

**触发条件**: `pair.is_closing == True`

**输出格式**: 正常显示，但在持仓ID后添加 `(平仓中)` 标记

```
📊 持仓监控汇总
   持仓 #1 (做多) [平仓中]:
      持仓时间: 123秒 (剩余 1677秒)
      ...
```

---

## Format Specifications

### 数字格式

| 字段 | 格式 | 示例 | 说明 |
|------|------|------|------|
| 持仓时间 | 整数，无小数 | `123秒` | 使用 `:.0f` |
| 剩余时间 | 整数，无小数 | `1677秒` | 使用 `:.0f` |
| 数量 | 4位小数 | `0.3500` | 使用 `:.4f` |
| 价格 | 2位小数 | `$3114.70` | 使用 `:.2f` |
| 已实现收益 | 2位小数，带符号 | `$-15.00` | 使用 `:.2f` |
| 未实现盈亏 | 2位小数，带符号 | `$-0.31` | 使用 `:.2f` |
| 盈利目标差距 | 2位小数，正数 | `$0.32` | 使用 `:.2f` |

### 文本格式

| 字段 | 可能值 | 说明 |
|------|--------|------|
| 方向 | `做多`, `做空` | 基于 `extended_side` |
| 当前价格缺失 | `N/A` | 当价格为 `None` 时 |
| 盈亏缺失 | `N/A` | 当计算无法完成时 |

### 对齐和缩进

- **缩进**: 所有持仓详情使用3个空格缩进 (`   `)
- **分隔符**: 持仓之间使用 `   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━`
- **字段对齐**: 字段标签左对齐，值右对齐（可选）

---

## Field Definitions

### 新增字段

#### 当前已实现收益

**含义**: 如果立即使用对手价平仓的理论收益

**计算逻辑**:
```
做多持仓:
  Extended盈亏 = (bid - extended_price) × extended_quantity
  Lighter盈亏 = (lighter_price - ask) × lighter_quantity
  已实现收益 = Extended盈亏 + Lighter盈亏

做空持仓:
  Extended盈亏 = (extended_price - ask) × extended_quantity
  Lighter盈亏 = (bid - lighter_price) × lighter_quantity
  已实现收益 = Extended盈亏 + Lighter盈亏
```

**显示格式**:
- 正数: `$12.34` (绿色，如果终端支持)
- 负数: `$-12.34` (红色，如果终端支持)
- 零: `$0.00`
- 缺失: `N/A`

**与未实现盈亏的区别**:
- 已实现收益: 使用**对手价**（bid/ask），反映实际平仓价格
- 未实现盈亏: 使用**中间价**或标记价格，反映理论盈亏

---

## Output Structure (Pseudo-Code)

```python
def _log_all_positions(pairs: List[SpreadPair]):
    if not pairs:
        logger.info("📊 持仓监控汇总\n   无活跃持仓")
        return

    lines = ["📊 持仓监控汇总"]
    total_unrealized_pnl = Decimal('0')

    for i, pair in enumerate(pairs):
        if i > 0:
            lines.append("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # 计算指标
        holding_time = pair.holding_time
        remaining_time = max(0, config.max_holding_time - holding_time)

        # 获取价格
        extended_bid = orderbook['extended']['bids'].get_best_bid()
        extended_ask = orderbook['extended']['asks'].get_best_ask()
        lighter_bid = orderbook['lighter']['bids'].get_best_bid()
        lighter_ask = orderbook['lighter']['asks'].get_best_ask()

        # 计算已实现收益
        if extended_bid and lighter_ask and pair.extended_side == 'buy':
            extended_close = extended_bid
            lighter_close = lighter_ask
            realized_pnl = pair.calculate_realized_pnl(extended_close, lighter_close)
        else:
            realized_pnl = None

        # 计算未实现盈亏
        if extended_bid and lighter_ask:
            unrealized_pnl = pair.calculate_unrealized_pnl(
                extended_bid, lighter_ask
            )
            total_unrealized_pnl += unrealized_pnl
        else:
            unrealized_pnl = None

        # 格式化输出
        direction = "做多" if pair.extended_side == 'buy' else "做空"
        closing_mark = " [平仓中]" if pair.is_closing else ""

        lines.append(f"   持仓 #{pair.pair_id} ({direction}){closing_mark}:")
        lines.append(f"      持仓时间: {holding_time:.0f}秒 (剩余 {remaining_time:.0f}秒)")
        lines.append(f"      Extended仓位: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}")
        lines.append(f"      当前价格: ${extended_bid:.2f}" if extended_bid else "      当前价格: N/A")
        lines.append(f"      Lighter仓位: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}")
        lines.append(f"      当前价格: ${lighter_ask:.2f}" if lighter_ask else "      当前价格: N/A")
        lines.append(f"      当前已实现收益: ${realized_pnl:.2f}" if realized_pnl is not None else "      当前已实现收益: N/A")
        lines.append(f"      未实现盈亏: ${unrealized_pnl:.2f}" if unrealized_pnl is not None else "      未实现盈亏: N/A")

        # 计算盈利目标差距
        if unrealized_pnl is not None:
            profit_target = pair.extended_quantity * extended_bid * config.profit_target_rate
            profit_gap = profit_target - unrealized_pnl
            lines.append(f"      距离盈利目标: ${profit_gap:.2f}")
        else:
            lines.append("      距离盈利目标: N/A")

    # 末尾摘要（多个持仓时）
    if len(pairs) > 1:
        lines.append("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"   总持仓: {len(pairs)} | 总未实现盈亏: ${total_unrealized_pnl:.2f}")

    logger.info("\n".join(lines))
```

---

## Test Cases

### TC-001: 无持仓输出
- **输入**: `open_pairs = []`
- **预期输出**: `📊 持仓监控汇总\n   无活跃持仓`

### TC-002: 单个持仓完整输出
- **输入**: 1个做多持仓，订单簿数据完整
- **预期输出**: 包含所有字段，无分隔符，无摘要行

### TC-003: 多个持仓完整输出
- **输入**: 3个持仓（2个做多，1个做空）
- **预期输出**: 包含分隔符和摘要行

### TC-004: 订单簿缺失处理
- **输入**: 1个持仓，`extended_bid = None`
- **预期输出**: 价格和收益显示 `N/A`

### TC-005: 已实现收益计算验证
- **输入**: 做多持仓，Extended $3000 → bid $3005, Lighter $2980 → ask $3010
- **预期输出**: 已实现收益 `$-15.00`

### TC-006: 零收益场景
- **输入**: 价格无变化
- **预期输出**: 已实现收益 `$0.00`

### TC-007: 正负收益混合
- **输入**: 3个持仓，盈利、亏损、不盈不亏
- **预期输出**: 总未实现盈亏正确累加

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-09 | 初始版本 |
