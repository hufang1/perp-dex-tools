# Data Model: 优化持仓监控输出

**Feature**: 001-optimize-monitor
**Date**: 2026-01-09

## Overview

本文档描述"优化持仓监控输出"功能涉及的数据实体、属性和关系。本功能主要修改现有数据结构，不引入新的持久化实体。

---

## Modified Entities

### SpreadPair (spread/spread_pair.py)

**变更类型**: 新增方法

**新增方法**:

```python
def calculate_realized_pnl(
    self,
    extended_close_price: Decimal,
    lighter_close_price: Decimal
) -> Decimal:
    """
    计算使用对手价立即平仓的理论收益

    Args:
        extended_close_price: Extended平仓价格
            - 做多持仓: 使用bid价格（卖出）
            - 做空持仓: 使用ask价格（买入平仓）
        lighter_close_price: Lighter平仓价格
            - 做多持仓时Lighter为做空: 使用ask价格（买入平仓）
            - 做空持仓时Lighter为做多: 使用bid价格（卖出）

    Returns:
        已实现盈亏 (Decimal)
        - 正数: 盈利
        - 负数: 亏损
        - 零: 不盈不亏

    Calculation:
        Extended盈亏 + Lighter盈亏

        做多示例:
            Extended买入 @ $3000, 当前bid $3005 → 盈 $5
            Lighter卖出 @ $2980, 当前ask $3010 → 亏 $20
            已实现收益 = $5 - $20 = -$15

        做空示例:
            Extended卖出 @ $3000, 当前ask $2995 → 盈 $5
            Lighter买入 @ $2980, 当前bid $2975 → 盈 $5
            已实现收益 = $5 + $5 = $10
    """
```

**现有相关方法** (保持不变):

```python
def calculate_unrealized_pnl(
    self,
    current_extended_price: Decimal,
    current_lighter_price: Decimal
) -> Decimal:
    """
    计算未实现盈亏（使用中间价）

    Note: 本功能不修改此方法，仅新增calculate_realized_pnl
    """
```

---

## New Data Structures (Internal)

### PositionSummary (内部使用，不定义为类)

**用途**: 整合输出时临时存储单个持仓的显示信息

**结构** (Python字典/数据类):

```python
@dataclass
class PositionSummary:
    """持仓监控摘要数据"""
    pair_id: int                    # 持仓唯一标识
    direction: str                  # "做多" 或 "做空"
    holding_time: float             # 持仓时间（秒）
    remaining_time: float           # 剩余时间（秒）

    # Extended仓位信息
    extended_quantity: Decimal      # 数量
    extended_price: Decimal         # 开仓价格
    extended_current: Decimal | None  # 当前价格（可能为None）

    # Lighter仓位信息
    lighter_quantity: Decimal       # 数量
    lighter_price: Decimal          # 开仓价格
    lighter_current: Decimal | None # 当前价格（可能为None）

    # 盈亏信息
    realized_pnl: Decimal | None    # 已实现收益（可能为None，当价格缺失时）
    unrealized_pnl: Decimal         # 未实现盈亏
    profit_gap: Decimal             # 距离盈利目标差距
```

**生命周期**: 临时创建，用于日志输出，不持久化

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    _log_all_positions()                      │
│                   (bot.py monitoring loop)                   │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
         ┌──────────────────────────────────────┐
         │  遍历 self.open_pairs                │
         │  (List[SpreadPair])                  │
         └──────────────────────────────────────┘
                              │
                              ▼
         ┌──────────────────────────────────────┐
         │  获取订单簿价格                       │
         │  - extended_bid/ask                  │
         │  - lighter_bid/ask                   │
         └──────────────────────────────────────┘
                              │
                              ▼
         ┌──────────────────────────────────────┐
         │  对每个持仓调用:                      │
         │  pair.calculate_realized_pnl()       │
         │  pair.calculate_unrealized_pnl()     │
         └──────────────────────────────────────┘
                              │
                              ▼
         ┌──────────────────────────────────────┐
         │  构建PositionSummary                 │
         │  (临时数据结构)                       │
         └──────────────────────────────────────┘
                              │
                              ▼
         ┌──────────────────────────────────────┐
         │  格式化为多行字符串                   │
         │  (使用换行符\n)                       │
         └──────────────────────────────────────┘
                              │
                              ▼
         ┌──────────────────────────────────────┐
         │  单次调用 logger.info()              │
         │  输出整合的监控信息                   │
         └──────────────────────────────────────┘
```

---

## Validation Rules

### 输入验证
1. **extended_close_price 和 lighter_close_price**:
   - 必须为 Decimal 类型
   - 必须为正数（> 0）
   - 如果为 None，calculate_realized_pnl 应返回 None

2. **持仓数量**:
   - quantity 必须 > 0
   - quantity 精度应与交易所要求一致（通常为4位小数）

3. **开仓价格**:
   - price 必须 > 0
   - price 精度应与交易所要求一致（通常为2位小数）

### 输出验证
1. **已实现收益精度**:
   - 使用 Decimal 计算，避免浮点误差
   - 输出时保留2位小数（如 `$12.34`）

2. **N/A 处理**:
   - 当任一价格为 None 时，该字段显示 "N/A"
   - 已实现收益计算跳过该持仓或返回 None

---

## State Transitions

### 持仓状态 (现有，不修改)

```
OPENED → ACTIVE → CLOSING → CLOSED
                     ↓
                  FAILED
```

### 监控数据状态

```
订单簿数据完整 → 计算已实现收益 → 显示完整信息
                    ↓
订单簿数据缺失 → 显示"N/A" → 跳过已实现收益计算
```

---

## Relationships

```
SpreadPair (1) ←───→ (1) SpreadArbitrageBot
    │
    │ 拥有
    ▼
Position 仓位信息
    - extended_side: 'buy' | 'sell'
    - extended_quantity: Decimal
    - extended_price: Decimal
    - lighter_side: 'sell' | 'buy'
    - lighter_quantity: Decimal
    - lighter_price: Decimal

    │
    │ 计算
    ▼
calculate_realized_pnl() → Decimal | None
calculate_unrealized_pnl() → Decimal
```

---

## Error Handling

### calculate_realized_pnl 异常情况

| 情况 | 处理方式 | 返回值 |
|------|----------|--------|
| 正常计算 | 执行计算 | Decimal (正/负/零) |
| 价格为 None | 跳过计算，返回 None | None |
| 价格 <= 0 | 记录警告日志，返回 None | None |
| 数量 <= 0 | 记录错误日志，返回 None | None |
| 其他异常 | 记录错误日志，返回 None | None |

### 日志输出异常处理

```python
try:
    summary = self._build_position_summary(pair, prices)
    # ... 格式化输出 ...
except Exception as e:
    self.logger.debug(f"持仓 #{pair.pair_id} 状态计算错误: {e}")
    # 继续处理其他持仓，不中断整个监控循环
```

---

## Testing Considerations

### 单元测试覆盖
1. `calculate_realized_pnl`:
   - 做多持仓盈利场景
   - 做多持仓亏损场景
   - 做空持仓盈利场景
   - 做空持仓亏损场景
   - 价格为 None 的边界情况
   - 零收益场景

2. `_log_all_positions`:
   - 空持仓列表输出
   - 单个持仓输出
   - 多个持仓输出
   - 订单簿数据缺失处理
   - 格式验证（换行符、分隔符）

### 集成测试覆盖
1. 完整监控循环测试
2. 与现有交易逻辑的隔离性验证
3. 日志输出可读性验证

---

## Migration Notes

### 向后兼容性
- ✅ 不修改现有的 `calculate_unrealized_pnl` 方法
- ✅ 不修改 SpreadPair 的数据属性
- ✅ 仅新增方法，不影响现有调用方

### 升级路径
1. 部署新代码到测试环境
2. 验证监控输出格式正确
3. 验证已实现收益计算准确性
4. 部署到生产环境
5. 无需数据迁移（无持久化变更）
