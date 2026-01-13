# Data Model: 价差套利程序优化

**Feature**: 016-spread-optimize
**Date**: 2026-01-13

## Overview

本文档定义了价差套利程序优化所需的数据模型扩展。

## Extended Data Models

### 1. BotConfig (扩展)

现有模型在`models.py`中定义，需要添加以下字段：

```python
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class BotConfig:
    """机器人配置（扩展）"""

    # 现有字段（保持不变）
    symbol: str
    target_quantity: Decimal
    min_spread_threshold: Decimal  # 最小开仓阈值 0.2%
    slippage_buffer: Decimal
    min_profit: Decimal  # 盈利目标 0.1%
    max_spread: Decimal  # 最大价差 5%
    single_side_timeout: float
    dry_run: bool = False
    verbose: bool = False

    # 新增字段
    cached_open_spread: Decimal = field(default_factory=lambda: Decimal("0"))
    """
    缓存的开仓价差（用于等差数列策略）
    - 初始值为0
    - 首次开仓时设置为当前价差
    - 后续每次开仓后更新为新的价差
    - 价差缩小时不降低
    """

    spread_step: Decimal = field(default_factory=lambda: Decimal("0.0005"))
    """
    价差步进值（用于等差数列策略）
    - 默认0.05% = 0.0005
    - 下次开仓阈值 = cached_open_spread + spread_step
    """

    balance_check_buffer: float = field(default=3.0)
    """
    仓位平衡检测缓冲期（秒）
    - 默认3秒
    - 开仓后在此时间内验证两边仓位
    - 不平衡时立即平仓
    """

    total_fee_rate: Decimal = field(default_factory=lambda: Decimal("0.0005"))
    """
    总手续费率
    - 默认0.05% = 0.0005
    - 包含两个交易所的开仓和平仓手续费
    - Extended: 0.025% x 2 = 0.05%
    - Lighter: ~0.025% x 2 = 0.05%
    - 总计约0.05%
    """

    def validate(self) -> bool:
        """验证配置有效性"""
        if self.target_quantity <= 0:
            return False
        if self.min_spread_threshold <= 0:
            return False
        if self.spread_step <= 0:
            return False
        if self.balance_check_buffer <= 0:
            return False
        if self.total_fee_rate < 0:
            return False
        return True
```

### 2. SpreadInfo (新增或扩展)

价差信息数据结构，用于实时监控。

```python
@dataclass
class SpreadInfo:
    """实时价差信息"""

    # Extended订单簿价格
    ext_bid: Decimal
    ext_ask: Decimal

    # Lighter订单簿价格
    lig_bid: Decimal
    lig_ask: Decimal

    # 计算的价差
    spread_abs: Decimal  # 绝对价差
    spread_pct: Decimal  # 百分比价差

    # 时间戳
    timestamp: float  # Unix时间戳

    # 计算中间价
    @property
    def ext_mid(self) -> Decimal:
        return (self.ext_bid + self.ext_ask) / 2

    @property
    def lig_mid(self) -> Decimal:
        return (self.lig_bid + self.lig_ask) / 2

    # 验证数据有效性
    def is_valid(self) -> bool:
        """验证价差数据是否有效"""
        if self.ext_bid <= 0 or self.ext_ask <= 0:
            return False
        if self.lig_bid <= 0 or self.lig_ask <= 0:
            return False
        if self.ext_bid >= self.ext_ask:
            return False
        if self.lig_bid >= self.lig_ask:
            return False
        if self.spread_abs < 0:
            return False
        return True

    # 格式化为单行日志
    def format_log(self) -> str:
        """格式化为单行日志字符串"""
        return (
            f"价差: Ext[{self.ext_bid:.1f}/{self.ext_ask:.1f}] "
            f"Lig[{self.lig_bid:.1f}/{self.lig_ask:.1f}] "
            f"= {self.spread_abs:.1f} ({self.spread_pct:.2%})"
        )
```

### 3. OpenPosition (新增)

开仓记录，用于等差数列策略。

```python
@dataclass
class OpenPosition:
    """单笔开仓记录"""

    # 基础信息
    position_id: str  # 唯一标识
    open_time: float  # 开仓时间戳

    # 价格信息
    ext_price: Decimal  # Extended开仓价格
    lig_price: Decimal  # Lighter开仓价格
    open_spread: Decimal  # 开仓价差

    # 数量信息
    quantity: Decimal  # 开仓数量

    # 订单信息
    ext_order_id: Optional[str] = None
    lig_order_id: Optional[str] = None

    # 状态
    is_active: bool = True  # 是否仍持有（未平仓）

    def format_log(self) -> str:
        """格式化为单行日志"""
        status = "持有" if self.is_active else "已平"
        return (
            f"仓位[{self.position_id[:8]}]: "
            f"{status} | "
            f"数量={self.quantity} | "
            f"价差={self.open_spread:.2%} | "
            f"Ext={self.ext_price:.1f} | "
            f"Lig={self.lig_price:.1f}"
        )
```

### 4. Portfolio (新增)

仓位组合，管理多笔开仓记录。

```python
@dataclass
class Portfolio:
    """仓位组合（支持等差数列多笔仓位）"""

    # 持仓列表
    positions: list[OpenPosition] = field(default_factory=list)

    # 统计信息
    total_quantity: Decimal = field(default_factory=lambda: Decimal("0"))
    weighted_avg_entry_spread: Decimal = field(default_factory=lambda: Decimal("0"))

    # 时间范围
    first_open_time: Optional[float] = None
    last_open_time: Optional[float] = None

    def add_position(self, position: OpenPosition) -> None:
        """添加新仓位"""
        self.positions.append(position)
        self._recalculate()

    def close_position(self, position_id: str) -> Optional[OpenPosition]:
        """平仓指定仓位"""
        for pos in self.positions:
            if pos.position_id == position_id and pos.is_active:
                pos.is_active = False
                self._recalculate()
                return pos
        return None

    def close_all(self) -> list[OpenPosition]:
        """平掉所有仓位"""
        closed = []
        for pos in self.positions:
            if pos.is_active:
                pos.is_active = False
                closed.append(pos)
        self._recalculate()
        return closed

    def get_active_positions(self) -> list[OpenPosition]:
        """获取所有活跃仓位"""
        return [p for p in self.positions if p.is_active]

    def get_total_entry_spread(self) -> Decimal:
        """获取加权平均开仓价差"""
        return self.weighted_avg_entry_spread

    def _recalculate(self) -> None:
        """重新计算统计信息"""
        active = self.get_active_positions()
        if not active:
            self.total_quantity = Decimal("0")
            self.weighted_avg_entry_spread = Decimal("0")
            self.first_open_time = None
            self.last_open_time = None
            return

        # 计算总数量和加权平均价差
        total_qty = Decimal("0")
        weighted_spread = Decimal("0")

        times = [p.open_time for p in active]

        for pos in active:
            total_qty += pos.quantity
            weighted_spread += pos.open_spread * pos.quantity

        self.total_quantity = total_qty
        self.weighted_avg_entry_spread = weighted_spread / total_qty if total_qty > 0 else Decimal("0")
        self.first_open_time = min(times) if times else None
        self.last_open_time = max(times) if times else None

    def format_log(self) -> str:
        """格式化为单行日志"""
        active_count = len(self.get_active_positions())
        return (
            f"持仓: {active_count}笔 | "
            f"总量={self.total_quantity} | "
            f"均价差={self.weighted_avg_entry_spread:.2%}"
        )
```

### 5. BalanceCheckResult (新增)

仓位平衡检查结果。

```python
@dataclass
class BalanceCheckResult:
    """仓位平衡检查结果"""

    is_balanced: bool  # 是否平衡
    ext_quantity: Decimal  # Extended仓位数量
    lig_quantity: Decimal  # Lighter仓位数量
    check_time: float  # 检查时间戳

    # 差异信息
    quantity_diff: Decimal = field(default_factory=lambda: Decimal("0"))
    diff_percentage: Decimal = field(default_factory=lambda: Decimal("0"))

    def format_log(self) -> str:
        """格式化为单行日志"""
        if self.is_balanced:
            return f"仓位平衡: Ext {self.ext_quantity} / Lig {self.lig_quantity}"
        else:
            return (
                f"仓位不平衡: Ext {self.ext_quantity} != Lig {self.lig_quantity} | "
                f"差异={self.quantity_diff} ({self.diff_percentage:.1%})"
            )
```

### 6. CloseTrigger (新增)

平仓触发信息。

```python
@dataclass
class CloseTrigger:
    """平仓触发信息"""

    # 触发条件
    is_triggered: bool  # 是否触发平仓

    # 价差信息
    entry_spread: Decimal  # 开仓价差（加权平均）
    current_spread: Decimal  # 当前市场价差
    profit_target: Decimal  # 盈利目标
    fee_rate: Decimal  # 手续费率

    # 计算结果
    expected_profit: Decimal  # 预期利润
    actual_profit: Decimal  # 实际利润（如已平仓）

    # 时间
    trigger_time: float  # 触发时间

    def format_log(self) -> str:
        """格式化为单行日志"""
        if self.is_triggered:
            return (
                f"平仓触发: 开仓{self.entry_spread:.2%} >= "
                f"当前{self.current_spread:.2%} + "
                f"盈利{self.profit_target:.2%} + "
                f"手续费{self.fee_rate:.2%} | "
                f"利润={self.actual_profit:.2f}"
            )
        else:
            return (
                f"持仓监控: 开仓{self.entry_spread:.2%} vs "
                f"当前{self.current_spread:.2%} | "
                f"利润={self.expected_profit:.2%}"
            )
```

## State Machine Extensions

### BotState (无变化)

现有状态机保持不变：
- IDLE: 空仓，等待开仓机会
- OPENING: 开仓中
- HOLDING: 持仓中，等待平仓机会
- CLOSING: 平仓中
- ERROR: 错误状态

### OpenStrategyState (新增)

等差数列开仓策略状态：

```python
class OpenStrategyState(Enum):
    """开仓策略状态"""
    WAITING = "waiting"  # 等待价差
    READY = "ready"  # 满足开仓条件
    EXECUTING = "executing"  # 执行开仓中
    SUCCESS = "success"  # 开仓成功
    FAILED = "failed"  # 开仓失败
```

## Data Flow

### 开仓流程

```
1. spread_monitor检测到价差更新
2. arithmetic_open_strategy检查是否满足开仓条件
   - 首次: spread > min_threshold
   - 后续: spread > cached + step
3. 满足条件 → 触发trade_executor执行开仓
4. 开仓后 → position_balance_checker验证平衡
5. 平衡 → 创建Portfolio记录
6. 不平衡 → 立即平仓保护
```

### 平仓流程

```
1. 持仓状态下，spread_monitor持续更新价差
2. smart_close_strategy检查平仓条件
   - entry_spread >= current_spread + profit_target + fees
3. 满足条件 → 触发trade_executor执行平仓
4. 平仓后 → 更新Portfolio统计
```

## Persistence

### 状态文件扩展

需要在`logs/spread_arb_state.json`中添加：

```json
{
  "state": "IDLE",
  "position": {
    // 现有字段保持不变
  },
  "portfolio": {
    // 新增：仓位组合
    "positions": [
      {
        "position_id": "uuid",
        "open_time": 1234567890.123,
        "ext_price": 3325.5,
        "lig_price": 3320.0,
        "open_spread": 0.0025,
        "quantity": 0.01,
        "ext_order_id": "xxx",
        "lig_order_id": "yyy",
        "is_active": true
      }
    ],
    "total_quantity": 0.01,
    "weighted_avg_entry_spread": 0.0025,
    "first_open_time": 1234567890.123,
    "last_open_time": 1234567890.123
  },
  "config": {
    // 现有字段
    // 新增字段
    "cached_open_spread": 0.0025,
    "spread_step": 0.0005,
    "balance_check_buffer": 3.0,
    "total_fee_rate": 0.0005
  },
  "stats": {
    // 现有统计信息保持不变
  }
}
```

## Validation Rules

### 配置验证

- `min_spread_threshold` > 0
- `spread_step` > 0
- `balance_check_buffer` > 0
- `total_fee_rate` >= 0
- `min_profit` > `total_fee_rate`（确保有利润空间）

### 价差数据验证

- bid > 0, ask > 0
- bid < ask（有效订单簿）
- spread_abs >= 0
- spread_pct在合理范围内（0 ~ max_spread）

### 仓位数据验证

- quantity > 0
- ext_price > 0, lig_price > 0
- open_spread > 0（套利才有意义）
- 两边数量相等（平衡检查）

## Migration Notes

从现有模型迁移到新模型：

1. **向后兼容**: 现有单仓位Position模型保持不变
2. **渐进式增强**: 新增Portfolio类支持多仓位
3. **状态迁移**: 读取旧状态文件时，将Position转换为包含单个OpenPosition的Portfolio
4. **配置兼容**: 新增配置字段使用默认值，不影响现有配置
