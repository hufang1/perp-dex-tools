# Data Model: 平仓逻辑修复与持仓监控调试

**Date**: 2026-01-09
**Feature**: 003-close-position-debug

## Overview

本功能不需要新的数据模型。所有修改都是对现有类和方法的增强。

## Existing Entities (Used)

### SpreadPair

**文件**: `spread/spread_pair.py`

**现有属性**：
```python
pair_id: int
extended_side: str              # 'buy' or 'sell'
extended_price: Decimal         # 开仓价格
extended_quantity: Decimal      # 开仓数量
lighter_price: Decimal          # Lighter开仓价格
lighter_quantity: Decimal       # Lighter开仓数量
open_time: float                # 开仓时间戳
close_time: float | None        # 平仓时间戳
is_closed: bool                 # 是否已平仓
close_extended_price: Decimal | None   # 平仓价格
close_lighter_price: Decimal | None    # Lighter平仓价格
realized_pnl: Decimal | None    # 已实现盈亏
```

**新增属性**（建议）：
```python
is_closing: bool = False        # 是否正在平仓中（防止重复平仓）
```

**关键方法**：
- `holding_time`: 持仓时间（秒）
- `calculate_unrealized_pnl(current_extended_price, current_lighter_price)`: 计算未实现盈亏
- `close(close_extended_price, close_lighter_price)`: 标记为已平仓

### SpreadArbitrageBot

**文件**: `spread/bot.py`

**修改的方法**：
1. `_force_close_pair(pair)`: 实现强制平仓逻辑
2. `_monitor_pairs()`: 添加持仓状态输出

## Data Flow

### 平仓流程

```
_monitor_pairs (每5秒循环)
    │
    ├─> 获取当前价格（从订单簿）
    │
    ├─> _check_force_close(pair, current_extended, current_lighter)
    │       │
    │       └─> 返回 (should_close: bool, reason: str)
    │
    └─> if should_close:
            └─> _force_close_pair(pair)
                    │
                    ├─> 构造 opportunity 字典（使用对手价）
                    │
                    ├─> _close_pair(pair, opportunity)
                    │       │
                    │       ├─> Extended 平仓（限价单）
                    │       │       │
                    │       │       └─> 等待成交
                    │       │
                    │       ├─> Lighter 平仓（市价单）
                    │       │
                    │       ├─> pair.close() 计算盈亏
                    │       │
                    │       └─> open_pairs.remove(pair)
                    │
                    └─> 返回 success: bool
```

### 持仓监控输出流程

```
_monitor_pairs (每5秒循环)
    │
    ├─> 遍历 self.open_pairs
    │
    ├─> 获取当前价格（从订单簿）
    │
    ├─> 计算状态指标：
    │       ├─> holding_time = pair.holding_time
    │       ├─> remaining_time = max_holding_time - holding_time
    │       ├─> unrealized_pnl = calculate_unrealized_pnl(...)
    │       └─> profit_gap = profit_target - unrealized_pnl
    │
    └─> 输出到控制台（中文格式）
```

## State Transitions

### 套利对状态

```
[开仓] → open_pairs
    │
    ├─→ 持仓中 (is_closing=False)
    │       │
    │       ├─→ _monitor_pairs 检查平仓条件
    │       │       │
    │       │       ├─→ 触发平仓条件？
    │       │       │       │
    │       │       │       ├─ YES → is_closing=True → _close_pair
    │       │       │       │                              │
    │       │       │       │                              ├─> 成功 → closed_pairs
    │       │       │       │                              │
    │       │       │       │                              └─> 失败 → is_closing=False (保留在 open_pairs)
    │       │       │       │
    │       │       │       └─ NO → 继续持仓
    │       │       │
    │       │       └─→ 输出持仓状态（每5秒）
    │       │
    │       └─→ ...
    │
    └─→ [平仓] → closed_pairs
```

## Validation Rules

### 平仓订单验证

1. **价格验证**：
   - Extended 平仓价格必须 > 0
   - Lighter 平仓价格必须 > 0
   - 价格必须来自实时订单簿

2. **数量验证**：
   - 平仓数量 = 开仓数量（完整平仓）
   - 不允许部分平仓

3. **状态验证**：
   - 只平仓 `is_closed=False` 的套利对
   - 检查 `is_closing` 标志，防止重复平仓

### 持仓状态输出验证

1. **时间验证**：
   - `remaining_time` 必须 >= 0
   - 如果 < 0，显示为 "已超时"

2. **盈亏验证**：
   - 使用 Decimal 类型进行计算
   - 显示两位小数

## No New Entities

本功能不引入新的数据实体。所有工作都是对现有代码的增强：

1. **实现缺失的函数**：`_force_close_pair`
2. **增强现有函数**：`_monitor_pairs` 添加状态输出
3. **可选的新属性**：`SpreadPair.is_closing`
