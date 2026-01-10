# Data Model: 价差套利平仓逻辑修复

**Feature**: 008-fix-spread-close
**Date**: 2026-01-10

---

## 数据模型

### 1. 价差快照 (SpreadSnapshot)

记录某一时刻的价差状态

```python
@dataclass
class SpreadSnapshot:
    """价差快照"""
    timestamp: float              # 时间戳
    extended_bid: Decimal         # Extended买一价
    extended_ask: Decimal         # Extended卖一价
    extended_mid: Decimal         # Extended中间价
    lighter_bid: Decimal          # Lighter买一价
    lighter_ask: Decimal          # Lighter卖一价
    lighter_mid: Decimal          # Lighter中间价
    spread: Decimal               # 中间价差 (extended_mid - lighter_mid)
    spread_rate: Decimal          # 价差率 (spread / lighter_mid)
    spread_sign: str              # 价差符号: "positive" | "negative" | "zero"
    arbitrage_direction: str      # 套利方向: "long_spread" | "short_spread"
```

**验证规则**:
- 所有价格必须 > 0
- bid <= ask
- spread_rate绝对值 >= 0.05% 才有套利价值

---

### 2. 价差变化 (SpreadChange)

记录价差从开仓到当前的变化

```python
@dataclass
class SpreadChange:
    """价差变化"""
    open_spread: Decimal          # 开仓时价差
    current_spread: Decimal       # 当前价差
    spread_delta: Decimal         # 价差变化 (current - open)
    spread_change_rate: Decimal   # 变化率 (delta / open)
    is_converged: bool            # 是否收敛（有利方向）
    is_favorable: bool            # 当前是否有利于持仓
    status: str                   # 状态描述
```

**收敛判断逻辑**:
- 做多价差 (extended_side='buy'): spread_delta > 0 → 收敛
- 做空价差 (extended_side='sell'): spread_delta < 0 → 收敛

---

### 3. 平仓决策 (CloseDecision)

平仓决策的结果

```python
@dataclass
class CloseDecision:
    """平仓决策"""
    pair_id: int                  # 套利对ID
    should_close: bool            # 是否应该平仓
    priority: int                 # 触发优先级 (1-5)
    reason: str                   # 决策理由
    reason_code: str              # 理由代码: "P1_CONVERGE_PROFIT" | "P2_CONVERGE_ANY" ...
    spread_change: SpreadChange   # 价差变化
    unrealized_pnl: Decimal       # 未实现盈亏
    pnl_rate: Decimal             # 盈亏率
    holding_time: float           # 持仓时间（秒）
    is_warning: bool              # 是否为警告平仓（价差扩大时）
    timestamp: float              # 决策时间戳
```

**优先级代码**:
| 代码 | 含义 |
|-----|------|
| P1_CONVERGE_PROFIT | 价差收敛+盈利目标 |
| P2_CONVERGE_ANY | 价差收敛+任意盈利 |
| P3_TIME_NO_EXPAND | 时间到+价差未扩大 |
| P4_TIME_SMALL_LOSS | 时间到+小亏损 |
| P5_TIME_LARGE_LOSS | 时间到+大亏损（延迟） |

---

### 4. 持仓平衡状态 (PositionBalance)

两个交易所的仓位平衡状态

```python
@dataclass
class PositionBalance:
    """仓位平衡状态"""
    extended_total_qty: Decimal   # Extended总仓位
    lighter_total_qty: Decimal    # Lighter总仓位
    diff_qty: Decimal             # 差异 (extended - lighter)
    diff_rate: Decimal            # 差异率 (diff / lighter)
    is_imbalanced: bool           # 是否失衡
    warning_level: str            # 警告级别: "OK" | "WARN" | "CRITICAL"
    timestamp: float              # 时间戳
```

**失衡判断**:
- 差异率 < 10%: OK
- 差异率 10%-30%: WARN
- 差异率 > 30%: CRITICAL

---

## 状态转换

### SpreadPair 状态

```
[OPENING] → [ACTIVE] → [CLOSING] → [CLOSED]
                 ↓
            [FORCE_CLOSE] (触发时)
```

### 价差状态

```
[DIVERGING] (扩大) ← → [CONVERGED] (收敛)
                ↓
           [STABLE] (稳定)
```
