# Quickstart: 价差套利平仓逻辑修复

**Feature**: 008-fix-spread-close
**Date**: 2026-01-10

---

## 概述

本功能修复价差套利策略的4个核心问题：
1. 价差计算方向错误
2. 平仓价格选择不当
3. 缺乏价差收敛检查
4. 诊断日志不足

---

## 修改的文件

```
spread/
├── calculator.py          # 修改: 使用中间价计算价差
├── spread_pair.py          # 新增: 价差收敛检查函数
├── bot.py                  # 修改: 新的平仓触发逻辑
├── trade_logger.py         # 新增: 增强诊断日志
└── config.py               # 新增: 配置参数

tests/
├── test_calculator_fix.py          # 新增
├── test_spread_convergence.py      # 新增
└── integration/
    └── test_closing_logic.py       # 新增
```

---

## 核心变化

### 1. 价差计算 (calculator.py)

**修改前**:
```python
# 使用买一卖一价差
if extended_bid < lighter_ask:
    spread = lighter_ask - extended_bid  # 可能为负！
```

**修改后**:
```python
# 使用中间价
extended_mid = (extended_bid + extended_ask) / 2
lighter_mid = (lighter_bid + lighter_ask) / 2
spread = extended_mid - lighter_mid

# 根据价差符号决定方向
if spread > 0:
    direction = 'short_spread'  # 做空价差
    extended_side = 'sell'
elif spread < 0:
    direction = 'long_spread'   # 做多价差
    extended_side = 'buy'
```

---

### 2. 价差收敛检查 (spread_pair.py)

**新增函数**:
```python
def is_spread_converged(
    self,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal
) -> Tuple[bool, str]:
    """检查价差是否收敛"""
    # 计算当前价差
    extended_mid = (extended_bid + extended_ask) / 2
    lighter_mid = (lighter_bid + lighter_ask) / 2
    current_spread = extended_mid - lighter_mid

    # 计算变化
    spread_delta = current_spread - self.open_spread

    # 判断收敛
    if self.extended_side == 'buy':
        # 做多：价差变大则收敛
        is_converged = spread_delta > 0
    else:
        # 做空：价差变小则收敛
        is_converged = spread_delta < 0

    return is_converged, f"价差变化: {spread_delta:.2f}"
```

---

### 3. 平仓触发逻辑 (bot.py)

**修改前**:
```python
# 依赖反向机会
close_pair = self._find_opposite_pair(opportunity)
if close_pair:
    await self._close_pair(close_pair, opportunity)
```

**修改后**:
```python
# 基于价差状态和时间触发
decision = self._check_close_conditions(pair, ...)
if decision.should_close:
    await self._close_pair_with_market_price(pair, ...)
```

**新的优先级**:
| P1 | 价差收敛 + 盈利目标 |
| P2 | 价差收敛 + 任意盈利 |
| P3 | 60秒 + 价差未扩大 |
| P4 | 60秒 + 小亏损 |
| P5 | 60秒 + 大亏损(延迟) |

---

### 4. 诊断日志 (trade_logger.py)

**新增日志**:

开仓时:
```
=== 价差快照 ===
时间戳: 2026-01-10 10:20:22
Extended: bid=$3094.20, ask=$3094.30
Lighter: bid=$3066.10, ask=$3066.55
中间价差: $27.93 (0.9024%)
套利方向: 做空价差
=================
```

平仓时:
```
=== 平仓价差分析 ===
套利对ID: 1
开仓时价差: +$27.93
当前价差: +$10.50
价差变化: -$17.43 (收敛)
平仓原因: P2-价差收敛+小额盈利
===================
```

---

## 测试

### 运行测试

```bash
# 单元测试
pytest tests/test_calculator_fix.py -v
pytest tests/test_spread_convergence.py -v

# 集成测试
pytest tests/integration/test_closing_logic.py -v
```

### 验证修复

1. **检查价差方向**:
   - 开仓时查看trade.log中的"套利方向"
   - 验证价差符号与方向一致

2. **检查平仓时机**:
   - 统计trade.log中的平仓记录
   - 验证>80%发生在价差收敛时

3. **检查盈亏**:
   - 运行1小时后统计整体盈亏
   - 目标: 从-2%优化到+0.3%以上

---

## 配置参数

新增/修改的配置参数:

```python
# config.py
SPREAD_CONVERGENCE_THRESHOLD = Decimal('0.001')  # 价差收敛阈值
CLOSE_PRIORITY_ENABLED = True                      # 启用优先级平仓
MIN_CLOSE_PROFIT_RATE = Decimal('0.0005')         # 最小平仓利润率
MAX_CLOSE_LOSS_RATE = Decimal('0.01')             # 最大平仓亏损率
DELAY_CLOSE_THRESHOLD = Decimal('0.01')           # 延迟平仓阈值
```

---

## 回滚计划

如果出现问题，回滚步骤：

1. 恢复修改的文件到修改前版本
2. 重启策略
3. 检查trade.log确认回滚成功

```bash
git checkout HEAD~1 spread/calculator.py
git checkout HEAD~1 spread/spread_pair.py
git checkout HEAD~1 spread/bot.py
git checkout HEAD~1 spread/trade_logger.py
git checkout HEAD~1 spread/config.py
```
