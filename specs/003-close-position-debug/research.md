# Research: 平仓逻辑修复与持仓监控调试

**Date**: 2026-01-09
**Feature**: 003-close-position-debug

## Decision Summary

| Topic | Decision | Rationale |
|-------|----------|-----------|
| 强制平仓实现方式 | 复用现有 `_close_pair` 函数，使用对手价模拟市价单 | 避免代码重复，保持一致性 |
| 持仓监控输出位置 | 集成到现有 `_monitor_pairs` 循环 | 最小化代码改动，利用现有循环 |
| 实时数据获取 | 直接使用当前订单簿数据（self.extended_orderbook） | 订单簿已由 WebSocket 实时更新，无需额外 API 调用 |

## Detailed Findings

### 1. 强制平仓问题根因分析

**发现问题**：在 `spread/bot.py:674-678`，`_force_close_pair` 函数体只有 `pass`，未实现任何平仓逻辑。

```python
async def _force_close_pair(self, pair: SpreadPair):
    """强制市价平仓"""
    self.logger.warning(f"强制平仓套利对 #{pair.pair_id}")
    # TODO: 实现市价平仓逻辑
    pass  # ← 问题所在：什么都没做！
```

**影响**：
- 当触发平仓条件时（持仓时间 > max_holding_time），系统只打印警告日志
- 套利对永远不会从 `self.open_pairs` 中移除
- 持仓时间持续增长，重复触发平仓警告
- `成功平仓` 统计始终为 0

### 2. 现有平仓流程分析

**`_close_pair` 函数流程**（`bot.py:581-670`）：

```
1. Extended 平仓（使用限价单）
   ├─ 调用 order_manager.place_spread_maker_order()
   ├─ 等待成交 wait_for_fill()
   └─ 超时或失败则返回 False

2. Lighter 平仓对冲
   ├─ 调用 hedge_manager.execute_hedge()
   ├─ 使用市价单快速成交
   └─ 失败则记录错误并返回 False

3. 记录平仓信息
   ├─ 设置 close_extended_order_id, close_lighter_order_id
   ├─ 调用 pair.close() 计算盈亏
   └─ 移除套利对：self.open_pairs.remove(pair)
```

**关键发现**：
- Extended 使用限价单（maker order），需要等待成交
- Lighter 使用市价单（taker order），立即成交
- 平仓成功后会将套利对从 `open_pairs` 移到 `closed_pairs`

### 3. 交易所下单方法研究

#### Extended 交易所

| 方法 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `place_open_order` | extended.py:202 | 限价单 | 开仓使用，自动调整到最优挂单价 |
| `place_close_order` | extended.py:336 | 限价单 | 平仓使用，post_only=True，避免 taker 费用 |

**市价单方案**：Extended 没有直接的市价单方法，但可以使用：
- 方案 A：使用对手价（卖单用 best_bid，买单用 best_ask）
- 方案 B：调用现有的 `place_close_order`，但传入更激进的价格

#### Lighter 交易所

| 方法 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `place_limit_order` | lighter.py:270 | 限价单 | 基础限价单 |
| `place_open_order` | lighter.py:305 | 市价单 | 开仓使用市价单 |
| `place_close_order` | lighter.py:344 | 限价单 | 平仓使用限价单（但会等待5秒） |

**市价单方案**：
- `place_open_order` 实际上是市价单（使用对手价）
- `execute_hedge` 在 hedge_manager.py 中实现了市价对冲

### 4. SpreadPair 类分析

**关键属性**：
```python
pair_id: int                           # 套利对ID
extended_side: str                      # 'buy' or 'sell'
extended_price: Decimal                 # 开仓价格
extended_quantity: Decimal              # 开仓数量
lighter_price: Decimal                  # Lighter开仓价格
lighter_quantity: Decimal               # Lighter开仓数量
open_time: float                        # 开仓时间戳
close_extended_price: Decimal | None    # 平仓价格
close_lighter_price: Decimal | None     # Lighter平仓价格
is_closed: bool                         # 是否已平仓
```

**关键方法**：
- `holding_time` (property): 持仓时间（秒）
- `calculate_unrealized_pnl(extended_price, lighter_price)`: 计算未实现盈亏
- `close(extended_price, lighter_price)`: 标记为已平仓并计算盈亏

### 5. 订单簿数据源

**当前实现**：
- `self.extended_orderbook`: 由 WebSocket 回调实时更新
- `self.lighter_orderbook`: 由 WebSocket 回调实时更新
- 结构：`{'bids': {price: quantity}, 'asks': {price: quantity}}`

**最佳实践**：
- 直接使用内存中的订单簿数据（无需额外 API 调用）
- 在 `_monitor_pairs` 循环中已经每 5 秒更新一次
- 可以从中提取 best_bid 和 best_ask

## Alternatives Considered

### 强制平仓实现方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 复用 `_close_pair` | 代码一致，经过测试 | 使用限价单，可能等待成交 | ✅ 选择（平衡） |
| B. 实现新的市价平仓 | 成交速度快 | 需要新代码，增加复杂度 | ❌ |
| C. 在 Extended 添加市价单方法 | 最彻底 | 需要修改交易所客户端，范围扩大 | ❌ |

### 持仓监控输出方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 集成到 `_monitor_pairs` | 利用现有循环，最小改动 | 输出频率固定（5秒） | ✅ 选择 |
| B. 创建独立的监控任务 | 灵活控制频率 | 增加复杂度，可能重复计算 | ❌ |
| C. 添加到 `_stats_reporter` | 已有的统计输出 | 频率太低（60秒） | ❌ |

## Implementation Recommendations

### 1. 修复强制平仓逻辑

**方法 A：复用 `_close_pair`（推荐）**
```python
async def _force_close_pair(self, pair: SpreadPair):
    """强制平仓 - 使用对手价快速成交"""
    # 获取当前对手价（模拟市价单）
    extended_bid = max(self.extended_orderbook['bids'].keys())
    extended_ask = min(self.extended_orderbook['asks'].keys())
    lighter_bid = max(self.lighter_orderbook['bids'].keys())
    lighter_ask = min(self.lighter_orderbook['asks'].keys())

    # 构造机会字典（复用 _close_pair 的接口）
    if pair.extended_side == 'buy':
        close_price = extended_bid  # 买入平仓用 bid 价
        lighter_close_price = lighter_ask
    else:
        close_price = extended_ask  # 卖出平仓用 ask 价
        lighter_close_price = lighter_bid

    opportunity = {
        'side': 'sell' if pair.extended_side == 'buy' else 'buy',
        'extended_price': close_price,
        'lighter_price': lighter_close_price
    }

    # 调用现有的平仓逻辑
    success = await self._close_pair(pair, opportunity)

    if not success:
        # 记录失败，防止无限重试
        self.logger.error(f"强制平仓失败！套利对 #{pair.pair_id} 仍持仓")
```

### 2. 添加持仓监控输出

**在 `_monitor_pairs` 中添加状态输出**：
```python
# 在检查平仓条件之前，输出持仓状态
for pair in self.open_pairs:
    # 计算未实现盈亏
    unrealized_pnl = pair.calculate_unrealized_pnl(current_extended, current_lighter)
    remaining_time = self.config.max_holding_time - pair.holding_time

    # 输出中文状态信息
    self.logger.info(
        f"📊 持仓监控 #{pair.pair_id}:\n"
        f"   持仓时间: {pair.holding_time:.0f}秒 (剩余 {remaining_time:.0f}秒)\n"
        f"   Extended仓位: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}\n"
        f"   当前价格: ${current_extended:.2f}\n"
        f"   Lighter仓位: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}\n"
        f"   当前价格: ${current_lighter:.2f}\n"
        f"   未实现盈亏: ${unrealized_pnl:.2f}\n"
        f"   距离盈利目标: ${profit_target - unrealized_pnl:.2f}"
    )
```

### 3. 防止重复平仓

**添加平仓状态追踪**：
```python
# 在 SpreadPair 中添加属性
self.is_closing = False  # 是否正在平仓中

# 在 _force_close_pair 中检查
if pair.is_closing:
    self.logger.warning(f"套利对 #{pair.pair_id} 正在平仓中，跳过")
    return

pair.is_closing = True
try:
    await self._close_pair(pair, opportunity)
finally:
    pair.is_closing = False
```

## Open Questions / Clarifications

无。所有需要的信息都已通过代码分析获得。

## Next Steps

1. ✅ 研究完成，可以进入 Phase 1（设计阶段）
2. 创建 data-model.md（如果需要新的数据结构）
3. 创建 contracts/（API 契约，虽然此功能不涉及新 API）
4. 创建 quickstart.md（开发快速开始指南）
