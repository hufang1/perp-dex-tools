# Quickstart: 平仓逻辑修复与持仓监控调试

**Date**: 2026-01-09
**Feature**: 003-close-position-debug

## Overview

本功能修复了价差套利机器人的强制平仓逻辑，并添加了详细的持仓状态监控输出。主要工作包括：

1. 实现 `_force_close_pair` 函数（之前只有 `pass`）
2. 在 `_monitor_pairs` 中添加持仓状态输出
3. 添加 `is_closing` 标志防止重复平仓

## Development Setup

### 环境要求

- Python 3.11+
- asyncio
- decimal.Decimal
- logging
- pytest (用于测试)

### 相关文件

```
spread/
├── bot.py                 # 主要修改文件
├── spread_pair.py         # 添加 is_closing 属性（可选）
├── order_manager.py       # 平仓订单管理（参考）
└── hedge_manager.py       # 对冲管理（参考）

tests/
├── test_force_close.py    # 新增：强制平仓测试
└── integration/
    └── test_close_flow.py # 新增：完整平仓流程测试
```

## Implementation Steps

### Step 1: 实现 `_force_close_pair` 函数

**文件**: `spread/bot.py:674`

```python
async def _force_close_pair(self, pair: SpreadPair) -> bool:
    """
    强制平仓套利对

    使用对手价模拟市价单，快速平仓以避免进一步损失。
    """
    try:
        self.logger.info(f"[强制平仓] 开始平仓套利对 #{pair.pair_id}")

        # 1. 防止重复平仓
        if getattr(pair, 'is_closing', False):
            self.logger.warning(f"套利对 #{pair.pair_id} 正在平仓中，跳过")
            return False

        # 设置标志
        pair.is_closing = True

        # 2. 获取当前对手价（模拟市价单）
        if not self.extended_orderbook['bids'] or not self.extended_orderbook['asks']:
            self.logger.error("订单簿数据不足，无法平仓")
            pair.is_closing = False
            return False

        extended_bid = max(self.extended_orderbook['bids'].keys())
        extended_ask = min(self.extended_orderbook['asks'].keys())
        lighter_bid = max(self.lighter_orderbook['bids'].keys())
        lighter_ask = min(self.lighter_orderbook['asks'].keys())

        # 确定平仓价格（使用对手价）
        if pair.extended_side == 'buy':
            close_extended_price = extended_bid
            close_lighter_price = lighter_ask
        else:
            close_extended_price = extended_ask
            close_lighter_price = lighter_bid

        # 3. 构造 opportunity 字典（复用 _close_pair 的接口）
        opportunity = {
            'side': 'sell' if pair.extended_side == 'buy' else 'buy',
            'extended_price': close_extended_price,
            'lighter_price': close_lighter_price
        }

        # 4. 调用现有的平仓逻辑
        success = await self._close_pair(pair, opportunity)

        if not success:
            self.logger.error(f"强制平仓失败！套利对 #{pair.pair_id} 仍持仓")
            pair.is_closing = False  # 重置标志，允许重试
            return False

        # 5. 平仓成功
        self.logger.info(f"✅ 强制平仓成功！套利对 #{pair.pair_id}")
        return True

    except Exception as e:
        self.logger.error(f"强制平仓异常: {e}")
        pair.is_closing = False
        return False
```

### Step 2: 添加持仓状态输出

**文件**: `spread/bot.py:316` (_monitor_pairs 方法)

在 `for pair in self.open_pairs[:]:` 循环内添加：

```python
# 🆕 新增：输出持仓状态（在检查平仓条件之前）
self._log_position_status(pair, current_extended, current_lighter)
```

添加新方法：

```python
def _log_position_status(
    self,
    pair: SpreadPair,
    current_extended_price: Decimal,
    current_lighter_price: Decimal
) -> None:
    """输出持仓状态信息到控制台"""
    try:
        # 计算指标
        holding_time = pair.holding_time
        remaining_time = max(0, self.config.max_holding_time - holding_time)

        # 计算未实现盈亏
        unrealized_pnl = pair.calculate_unrealized_pnl(
            current_extended_price,
            current_lighter_price
        )

        # 计算盈利目标差距
        profit_target = pair.extended_quantity * current_extended_price * self.config.profit_target_rate
        profit_gap = profit_target - unrealized_pnl

        # 输出格式化的状态信息（中文）
        self.logger.info(
            f"📊 持仓监控 #{pair.pair_id}:\n"
            f"   持仓时间: {holding_time:.0f}秒 (剩余 {remaining_time:.0f}秒)\n"
            f"   Extended仓位: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}\n"
            f"   当前价格: ${current_extended_price:.2f}\n"
            f"   Lighter仓位: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}\n"
            f"   当前价格: ${current_lighter_price:.2f}\n"
            f"   未实现盈亏: ${unrealized_pnl:.2f}\n"
            f"   距离盈利目标: ${profit_gap:.2f}"
        )

    except Exception as e:
        self.logger.debug(f"持仓状态输出错误: {e}")
```

### Step 3: 添加 is_closing 属性（可选）

**文件**: `spread/spread_pair.py:67`

在 `__init__` 方法中添加：

```python
self.is_closing = False  # 是否正在平仓中
```

## Testing

### 单元测试

**文件**: `tests/test_force_close.py`

```python
import pytest
from decimal import Decimal
from spread.bot import SpreadArbitrageBot
from spread.spread_pair import SpreadPair
from spread.config import SpreadArbConfig

@pytest.mark.asyncio
async def test_force_close_pair_success():
    """测试强制平仓成功"""
    # TODO: 实现 mock 和测试逻辑
    pass

@pytest.mark.asyncio
async def test_force_close_pair_prevents_duplicate():
    """测试防止重复平仓"""
    # TODO: 测试 is_closing 标志
    pass
```

### 集成测试

**文件**: `tests/integration/test_close_flow.py`

```python
import pytest
from decimal import Decimal

@pytest.mark.asyncio
async def test_full_close_flow():
    """测试完整平仓流程"""
    # 1. 创建套利对
    # 2. 等待触发强制平仓条件
    # 3. 验证平仓执行
    # 4. 验证套利对从 open_pairs 移到 closed_pairs
    pass
```

### 手动测试

1. 启动机器人：
   ```bash
   python spread/bot.py --ticker ETH --size 35 --max-pairs 1
   ```

2. 观察控制台输出：
   - 每 5 秒应看到持仓状态输出
   - 触发平仓条件后应看到强制平仓日志
   - 套利对应成功从持仓中移除

3. 验证日志：
   ```bash
   cat logs/trade.log
   ```

## Verification Checklist

- [x] `_force_close_pair` 函数已实现
- [x] `_log_position_status` 函数已添加
- [x] `is_closing` 属性已添加到 SpreadPair
- [x] 持仓状态每 5 秒输出一次
- [ ] 触发平仓条件后成功平仓（需手动测试）
- [ ] 平仓后套利对从 open_pairs 移除（需手动测试）
- [ ] 统计信息正确更新（成功平仓计数）（需手动测试）
- [x] 交易日志正确记录（已有 001-trade-log 功能）
- [x] 不会重复触发平仓（is_closing 标志）
- [x] 所有输出使用简体中文

## Rollback Plan

如果出现问题：
1. 回滚 `spread/bot.py` 中的修改
2. 回滚 `spread/spread_pair.py` 中的修改（如果添加了 is_closing）
3. 恢复到原有代码（`_force_close_pair` 保持 `pass`）

## Next Steps

实施完成后：
1. 运行测试套件
2. 在测试环境运行完整周期
3. 验证日志输出
4. 合并到主分支
