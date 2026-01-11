"""
价差套利数据模型

本模块定义价差套利策略使用的所有数据类，包括:
- SpreadSnapshot: 价差快照
- SpreadChange: 价差变化
- CloseDecision: 平仓决策
- PositionBalance: 仓位平衡状态
"""

from dataclasses import dataclass, field
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

    timestamp: float              # 时间戳
    extended_total_qty: Decimal   # Extended总仓位
    lighter_total_qty: Decimal    # Lighter总仓位
    diff_qty: Decimal             # 差异 (extended - lighter)
    diff_rate: Decimal = field(init=False)           # 差异率（自动计算）
    is_imbalanced: bool = field(init=False)          # 是否失衡（自动计算）
    warning_level: str = field(init=False)           # 警告级别（自动计算）: "OK" | "WARN" | "CRITICAL"

    def __post_init__(self):
        """计算平衡状态 - 使用绝对值计算真实的仓位失衡率"""
        # 使用绝对值计算总暴露度
        total_exposure = abs(self.extended_total_qty) + abs(self.lighter_total_qty)

        # 计算实际差异（绝对值之间的差异）
        actual_diff_qty = abs(abs(self.extended_total_qty) - abs(self.lighter_total_qty))

        # 计算差异率
        if total_exposure > 0:
            self.diff_rate = actual_diff_qty / total_exposure
        else:
            self.diff_rate = Decimal('0')

        # 判断失衡级别
        if self.diff_rate >= Decimal('0.5'):  # 50%以上
            self.warning_level = 'CRITICAL'
        elif self.diff_rate >= Decimal('0.1'):  # 10%以上
            self.warning_level = 'WARN'
        else:
            self.warning_level = 'OK'

        self.is_imbalanced = self.warning_level != 'OK'


@dataclass
class SafetyState:
    """系统安全状态 - 用于安全监控和熔断决策"""

    # 基本状态
    is_paused: bool = False
    pause_reason: str = ""
    pause_since: Optional[float] = None

    # 对冲失败率监控
    hedge_failure_window: int = 10
    recent_hedge_attempts: list = None
    hedge_failure_rate: Decimal = Decimal('0')

    # 仓位失衡监控
    position_imbalance_rate: Decimal = Decimal('0')
    last_imbalance_check: Optional[float] = None

    # 未对冲仓位
    unhedged_positions: list = None
    total_unhedged_value: Decimal = Decimal('0')

    # 熔断级别
    circuit_breaker_level: int = 0

    # 统计
    total_hedge_attempts: int = 0
    total_hedge_failures: int = 0

    def __post_init__(self):
        """初始化列表字段"""
        if self.recent_hedge_attempts is None:
            self.recent_hedge_attempts = []
        if self.unhedged_positions is None:
            self.unhedged_positions = []


@dataclass
class HedgeFailureTracking:
    """对冲失败跟踪记录"""

    timestamp: float
    pair_id: int
    extended_order_id: str
    extended_fill_qty: Decimal

    # 对冲尝试信息
    hedge_attempts: int = 1
    hedge_order_ids: list = None

    # 失败原因
    failure_reason: str = "unknown"
    failure_details: str = ""

    # 状态
    is_resolved: bool = False
    resolved_at: Optional[float] = None
    resolution_method: Optional[str] = None

    def __post_init__(self):
        """初始化列表字段"""
        if self.hedge_order_ids is None:
            self.hedge_order_ids = []


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
