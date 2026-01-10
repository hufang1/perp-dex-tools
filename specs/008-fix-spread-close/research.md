# Research: 价差套利平仓逻辑修复

**Feature**: 008-fix-spread-close
**Date**: 2026-01-10

---

## 研究结论

### R001: 价差计算公式

**决策**: 使用中间价计算价差

```python
extended_mid = (extended_bid + extended_ask) / 2
lighter_mid = (lighter_bid + lighter_ask) / 2
spread = extended_mid - lighter_mid
```

**理由**:
- 中间价反映订单簿的平衡点
- 避免极端值影响
- 行业标准做法

---

### R002: 价差收敛判断

**决策**: 基于持仓方向和价差变化判断

```python
def is_spread_converged(pair, current_spread):
    spread_change = current_spread - pair.open_spread
    if pair.extended_side == 'buy':
        return spread_change > 0  # 做多：价差变大则收敛
    else:
        return spread_change < 0  # 做空：价差变小则收敛
```

**理由**: 价差收敛意味着向有利方向变化，即盈利方向

---

### R003: 平仓触发优先级

**决策**: 5级优先级

| 优先级 | 条件 | 操作 |
|-------|------|------|
| P1 | 价差收敛 + 盈利≥0.05% | 立即平仓 |
| P2 | 价差收敛 + 任意盈利 | 立即平仓 |
| P3 | 60秒 + 价差未扩大 | 平仓 |
| P4 | 60秒 + 亏损<1% | 平仓 |
| P5 | 60秒 + 亏损≥1% | 延迟平仓 |

**理由**: 优先锁定利润，避免确认损失

---

### R004: 日志格式

**决策**: 结构化日志

```
=== 价差快照 ===
时间戳: 2026-01-10 10:20:22
Extended: bid=$3094.20, ask=$3094.30
Lighter: bid=$3066.10, ask=$3066.55
中间价差: $27.93 (0.9024%)
套利方向: 做空价差
=================
```

**理由**: 清晰、可解析、便于分析
