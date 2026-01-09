# API Contracts: 平仓逻辑修复与持仓监控调试

**Date**: 2026-01-09
**Feature**: 003-close-position-debug

## Overview

本功能不涉及新的外部 API。所有修改都是内部方法实现。

## Internal API Changes

### Modified Methods

#### 1. `SpreadArbitrageBot._force_close_pair`

**位置**: `spread/bot.py`

**修改前**：
```python
async def _force_close_pair(self, pair: SpreadPair):
    """强制市价平仓"""
    self.logger.warning(f"强制平仓套利对 #{pair.pair_id}")
    # TODO: 实现市价平仓逻辑
    pass
```

**修改后**：
```python
async def _force_close_pair(self, pair: SpreadPair) -> bool:
    """
    强制平仓套利对

    使用对手价模拟市价单，快速平仓以避免进一步损失。

    Args:
        pair: 需要平仓的套利对

    Returns:
        bool: 平仓是否成功

    Flow:
        1. 检查 is_closing 标志，防止重复平仓
        2. 获取当前订单簿的对手价
        3. 构造 opportunity 字典
        4. 调用 _close_pair 执行平仓
        5. 记录结果到统计和日志
    """
```

#### 2. `SpreadArbitrageBot._monitor_pairs`

**位置**: `spread/bot.py`

**修改内容**：在检查平仓条件之前，添加持仓状态输出

```python
async def _monitor_pairs(self):
    """监控套利对,检查强制平仓条件"""
    while not self.stop_flag:
        try:
            for pair in self.open_pairs[:]:
                # ... 现有代码：获取当前价格 ...

                # 🆕 新增：输出持仓状态
                self._log_position_status(pair, current_extended, current_lighter)

                # ... 现有代码：检查平仓条件 ...
```

#### 3. `SpreadArbitrageBot._log_position_status` (新增方法)

**位置**: `spread/bot.py`

```python
def _log_position_status(
    self,
    pair: SpreadPair,
    current_extended_price: Decimal,
    current_lighter_price: Decimal
) -> None:
    """
    输出持仓状态信息到控制台

    Args:
        pair: 套利对
        current_extended_price: 当前 Extended 价格
        current_lighter_price: 当前 Lighter 价格

    Output Format (简体中文):
        📊 持仓监控 #1:
           持仓时间: 123秒 (剩余 1677秒)
           Extended仓位: 0.35 @ $2450.00
           当前价格: $2448.50
           Lighter仓位: 0.35 @ $2460.00
           当前价格: $2461.20
           未实现盈亏: $1.23
           距离盈利目标: $8.77
    """
```

### Optional: SpreadPair Enhancement

**新增属性**：
```python
is_closing: bool = False  # 是否正在平仓中
```

**用途**：防止多个监控循环同时触发平仓

## Method Signatures

### _force_close_pair

```python
async def _force_close_pair(self, pair: SpreadPair) -> bool:
    """
    强制平仓套利对

    Args:
        pair (SpreadPair): 需要平仓的套利对

    Returns:
        bool: True=平仓成功, False=平仓失败

    Raises:
        无异常抛出（内部处理所有错误）

    Side Effects:
        - 调用 _close_pair 执行实际平仓操作
        - 成功时将 pair 从 open_pairs 移到 closed_pairs
        - 更新 self.stats 统计信息
        - 记录到 trade_logger
    """
```

### _log_position_status

```python
def _log_position_status(
    self,
    pair: SpreadPair,
    current_extended_price: Decimal,
    current_lighter_price: Decimal
) -> None:
    """
    输出持仓状态信息

    Args:
        pair (SpreadPair): 套利对
        current_extended_price (Decimal): 当前 Extended 价格
        current_lighter_price (Decimal): 当前 Lighter 价格

    Returns:
        None

    Side Effects:
        - 向控制台输出格式化的状态信息（中文）
        - 使用 logging.INFO 级别
    """
```

## Error Handling

### _force_close_pair 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 订单簿为空 | 记录错误，返回 False |
| 平仓订单提交失败 | 记录错误，保持 is_closing=False，允许下次重试 |
| 部分成交（Extended） | 等待完整成交或超时取消 |
| Lighter 对冲失败 | 记录错误到 unhedged_positions |

### _log_position_status 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 价格数据无效 | 跳过输出，记录 debug 日志 |
| 计算溢出 | 使用 Decimal 的异常处理 |

## Logging Format

### 持仓状态输出格式

```
📊 持仓监控 #1:
   持仓时间: 123秒 (剩余 1677秒)
   Extended仓位: 0.35 @ $2450.00
   当前价格: $2448.50
   Lighter仓位: 0.35 @ $2460.00
   当前价格: $2461.20
   未实现盈亏: $1.23
   距离盈利目标: $8.77
```

### 强制平仓日志格式

```
⚠️ 套利对 #1 触发强制平仓: 强制平仓 (持仓1900秒 > 最大1800秒, PnL=$-0.31)
[平仓中...]
💰 平仓成功! 套利对 #1
   盈亏: $-0.31 (-1.2%)
   持仓时间: 1900秒
   ...
```

## No External APIs

本功能不涉及：
- ❌ 新的 HTTP 端点
- ❌ 新的 WebSocket 消息类型
- ❌ 新的数据库查询
- ❌ 新的第三方 API 调用

所有功能都是对现有内部方法实现的完善。
