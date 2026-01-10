# 函数签名契约

**Feature**: 008-fix-spread-close
**Date**: 2026-01-10

---

## calculator.py

### calculate_spread_opportunity_mid

```python
def calculate_spread_opportunity_mid(
    self,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal,
    min_spread_rate: Decimal
) -> Optional[Dict[str, Any]]:
    """
    使用中间价计算价差机会

    Args:
        extended_bid: Extended买一价
        extended_ask: Extended卖一价
        lighter_bid: Lighter买一价
        lighter_ask: Lighter卖一价
        min_spread_rate: 最小价差率阈值

    Returns:
        {
            'spread_mid': Decimal,           # 中间价差
            'spread_rate': Decimal,          # 价差率
            'direction': str,                # 'long_spread' | 'short_spread'
            'extended_side': str,            # 'buy' | 'sell'
            'extended_price': Decimal,       # Extended挂单价格
            'lighter_price': Decimal,        # Lighter对冲价格
            'expected_profit_rate': Decimal  # 预期利润率
        }
        或 None (如果没有机会)

    算法:
        1. 计算中间价
        2. 计算价差 = extended_mid - lighter_mid
        3. 计算价差率 = spread / lighter_mid
        4. 判断方向: spread > 0 → short_spread, spread < 0 → long_spread
        5. 验证价差率是否超过阈值
    """
```

---

## spread_pair.py

### is_spread_converged

```python
def is_spread_converged(
    self,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal
) -> Tuple[bool, str, SpreadChange]:
    """
    检查价差是否收敛

    Args:
        extended_bid: 当前Extended买一价
        extended_ask: 当前Extended卖一价
        lighter_bid: 当前Lighter买一价
        lighter_ask: 当前Lighter卖一价

    Returns:
        (is_converged, status_message, spread_change)

    算法:
        1. 计算当前中间价差
        2. 计算价差变化 = current_spread - open_spread
        3. 根据持仓方向判断收敛:
           - 做多: spread_change > 0 → 收敛
           - 做空: spread_change < 0 → 收敛
    """
```

---

## bot.py

### _check_close_conditions

```python
def _check_close_conditions(
    self,
    pair: SpreadPair,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal
) -> CloseDecision:
    """
    检查平仓条件（新的5级优先级系统）

    Args:
        pair: 套利对
        extended_bid: 当前Extended买一价
        extended_ask: 当前Extended卖一价
        lighter_bid: 当前Lighter买一价
        lighter_ask: 当前Lighter卖一价

    Returns:
        CloseDecision对象

    优先级:
        P1: 价差收敛 + 盈利 >= profit_target
        P2: 价差收敛 + 盈利 > 0
        P3: 持仓 > 60秒 + 价差未扩大
        P4: 持仓 > 60秒 + 亏损 < 1%
        P5: 持仓 > 60秒 + 亏损 >= 1% (延迟平仓)

    算法:
        1. 计算价差变化
        2. 计算未实现盈亏
        3. 按优先级检查条件
        4. 返回最高优先级的决策
    """
```

### _close_pair_with_market_price

```python
async def _close_pair_with_market_price(
    self,
    pair: SpreadPair,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal
) -> bool:
    """
    使用当前市价平仓（替代机会平仓）

    Args:
        pair: 套利对
        extended_bid: 当前Extended买一价
        extended_ask: 当前Extended卖一价
        lighter_bid: 当前Lighter买一价
        lighter_ask: 当前Lighter卖一价

    Returns:
        bool: 平仓是否成功

    算法:
        1. 确定平仓方向
        2. 使用对手价:
           - 做多平仓: Extended用bid卖出, Lighter用ask买入
           - 做空平仓: Extended用ask买入, Lighter用bid卖出
        3. 下单并等待成交
        4. 更新套利对状态
        5. 记录日志
    """
```

---

## trade_logger.py

### log_spread_snapshot

```python
def log_spread_snapshot(
    self,
    snapshot: SpreadSnapshot
) -> bool:
    """
    记录价差快照

    Args:
        snapshot: 价差快照对象

    Returns:
        bool: 记录是否成功

    日志格式:
        === 价差快照 ===
        时间戳: YYYY-MM-DD HH:MM:SS
        Extended: bid=$XXX, ask=$XXX, mid=$XXX
        Lighter: bid=$XXX, ask=$XXX, mid=$XXX
        中间价差: $XXX (X.XX%)
        价差符号: 正/负/零
        套利方向: 做多价差/做空价差
        预期: 价差向X方向收敛时盈利
        =================
    """
```

### log_close_analysis

```python
def log_close_analysis(
    self,
    decision: CloseDecision
) -> bool:
    """
    记录平仓分析

    Args:
        decision: 平仓决策对象

    Returns:
        bool: 记录是否成功

    日志格式:
        === 平仓价差分析 ===
        套利对ID: X
        开仓时价差: $XXX (X.XX%)
        当前价差: $XXX (X.XX%)
        价差变化: $XXX (收敛/扩大)
        价差状态: 收敛/扩大 (有利/不利)
        平仓原因: PX-XXX
        未实现盈亏: $XXX (X.XX%)
        警告: (如适用) ⚠️ 价差扩大平仓
        ===================
    """
```

### log_position_balance

```python
def log_position_balance(
    self,
    balance: PositionBalance
) -> bool:
    """
    记录仓位平衡状态

    Args:
        balance: 仓位平衡对象

    Returns:
        bool: 记录是否成功

    日志格式:
        === 仓位平衡状态 ===
        Extended总仓位: X.XXXX
        Lighter总仓位: X.XXXX
        差异: X.XXXX (X.XX%)
        状态: OK/WARN/CRITICAL
        时间戳: YYYY-MM-DD HH:MM:SS
        ===================
    """
```
