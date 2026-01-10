"""
价差套利数据模型

本模块定义价差套利策略使用的所有数据类，包括:
- SpreadSnapshot: 价差快照
- SpreadChange: 价差变化
- CloseDecision: 平仓决策
- PositionBalance: 仓位平衡状态
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class SpreadSnapshot:
    """价差快照 - 记录某一时刻的价差状态"""

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

    def __post_init__(self):
        """验证数据有效性"""
        if self.extended_bid <= 0 or self.extended_ask <= 0:
            raise ValueError("Extended价格必须大于0")
        if self.lighter_bid <= 0 or self.lighter_ask <= 0:
            raise ValueError("Lighter价格必须大于0")
        if self.extended_bid > self.extended_ask:
            raise ValueError("Extended bid不能大于ask")
        if self.lighter_bid > self.lighter_ask:
            raise ValueError("Lighter bid不能大于ask")


@dataclass
class SpreadChange:
    """价差变化 - 记录价差从开仓到当前的变化"""

    open_spread: Decimal          # 开仓时价差
    current_spread: Decimal       # 当前价差
    spread_delta: Decimal         # 价差变化 (current - open)
    spread_change_rate: Decimal   # 变化率 (delta / open)
    is_converged: bool            # 是否收敛（有利方向）
    is_favorable: bool            # 当前是否有利于持仓
    status: str                   # 状态描述

    def __post_init__(self):
        """验证数据有效性"""
        if self.open_spread == 0:
            # 避免除零错误
            self.spread_change_rate = Decimal('0')
        else:
            self.spread_change_rate = self.spread_delta / abs(self.open_spread)


@dataclass
class CloseDecision:
    """平仓决策 - 平仓决策的结果"""

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

    # 可选字段
    extended_close_price: Optional[Decimal] = None  # Extended平仓价格
    lighter_close_price: Optional[Decimal] = None   # Lighter平仓价格


@dataclass
class PositionBalance:
    """仓位平衡状态 - 两个交易所的仓位平衡状态"""

    extended_total_qty: Decimal   # Extended总仓位
    lighter_total_qty: Decimal    # Lighter总仓位
    diff_qty: Decimal             # 差异 (extended - lighter)
    diff_rate: Decimal            # 差异率 (diff / lighter, 避免除零)
    is_imbalanced: bool           # 是否失衡
    warning_level: str            # 警告级别: "OK" | "WARN" | "CRITICAL"
    timestamp: float              # 时间戳

    def __post_init__(self):
        """计算平衡状态"""
        # 避免除零错误
        if self.lighter_total_qty == 0:
            if self.extended_total_qty == 0:
                self.diff_rate = Decimal('0')
            else:
                # Lighter为0但Extended不为0，严重失衡
                self.diff_rate = Decimal('999')
        else:
            self.diff_rate = abs(self.diff_qty) / self.lighter_total_qty

        # 判断失衡状态
        if self.diff_rate < Decimal('0.1'):  # 10%
            self.is_imbalanced = False
            self.warning_level = "OK"
        elif self.diff_rate < Decimal('0.3'):  # 30%
            self.is_imbalanced = True
            self.warning_level = "WARN"
        else:
            self.is_imbalanced = True
            self.warning_level = "CRITICAL"


@dataclass
class SpreadRecord:
    """价差记录 - 单次价差采样的完整数据"""

    timestamp: str                # 采样时间戳 (ISO 8601格式, 精确到毫秒)
    extended_bid: Decimal         # Extended买一价
    extended_ask: Decimal         # Extended卖一价
    lighter_bid: Decimal          # Lighter买一价
    lighter_ask: Decimal          # Lighter卖一价
    long_spread: Decimal          # 做多价差值 (lighter_bid - extended_ask)
    long_spread_rate: Decimal     # 做多价差率 (long_spread / lighter_bid)
    short_spread: Decimal         # 做空价差值 (extended_bid - lighter_ask)
    short_spread_rate: Decimal    # 做空价差率 (short_spread / extended_bid)
    extended_spread_cost: Decimal # Extended点差成本率
    lighter_spread_cost: Decimal  # Lighter点差成本率
    total_cost_rate: Decimal      # 总成本率 (extended + lighter)
    status: str                   # 数据状态 ("VALID" 或 "INVALID")
