"""
价差套利数据模型

本模块定义价差套利策略使用的所有数据类，包括:
- SpreadSnapshot: 价差快照
- SpreadChange: 价差变化
- CloseDecision: 平仓决策
- PositionBalance: 仓位平衡状态
- 成功率追踪相关枚举和数据类
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from enum import Enum


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


# ============================================================================
# 001-fix-order-type: 成功率追踪相关枚举和数据类
# ============================================================================

class OperationType(Enum):
    """操作类型枚举 - 定义所有可能的交易操作"""
    OPEN_ATTEMPT = "open_attempt"           # 开仓尝试（识别到机会）
    OPEN_SUCCESS = "open_success"           # 开仓成功
    OPEN_FAILED = "open_failed"             # 开仓失败
    CLOSE_ATTEMPT = "close_attempt"         # 平仓尝试
    CLOSE_SUCCESS = "close_success"         # 平仓成功
    CLOSE_FAILED = "close_failed"           # 平仓失败


class OperationStatus(Enum):
    """操作状态枚举 - 定义操作的执行结果"""
    SUCCESS = "success"                     # 成功
    FAILED = "failed"                       # 失败
    POSITION_LIMIT = "position_limit"       # 仓位上限（特殊标识）
    PENDING = "pending"                     # 进行中


class ExchangeType(Enum):
    """交易所类型枚举"""
    EXTENDED = "extended"
    LIGHTER = "lighter"
    BOTH = "both"


class FailureReason(Enum):
    """失败原因枚举 - 定义所有可能的失败原因"""
    INSUFFICIENT_BALANCE = "insufficient_balance"       # 余额不足
    ORDER_REJECTED = "order_rejected"                   # 订单被拒绝
    NETWORK_TIMEOUT = "network_timeout"                 # 网络超时
    PRICE_SLIPPAGE = "price_slippage"                   # 价格滑点过大
    PARTIAL_FILL = "partial_fill"                       # 部分成交
    POSITION_IMBALANCE = "position_imbalance"           # 仓位不一致
    UNKNOWN_ERROR = "unknown_error"                     # 未知错误


@dataclass
class PositionConsistencyCheck:
    """
    仓位一致性检查结果

    用于验证开仓后Extended和Lighter仓位数量是否一致
    """
    is_consistent: bool                    # 仓位是否一致
    extended_quantity: Decimal             # Extended仓位数量
    lighter_quantity: Decimal              # Lighter仓位数量
    difference: Decimal                    # 差异数量（绝对值）
    difference_rate: float                 # 差异率（百分比）
    threshold_exceeded: bool               # 是否超过阈值

    def __str__(self) -> str:
        """格式化输出"""
        status = "✅ 一致" if self.is_consistent else "⚠️ 不一致"
        return (
            f"{status}: Extended={self.extended_quantity:.4f}, "
            f"Lighter={self.lighter_quantity:.4f}, "
            f"差异={self.difference:.4f}, 差异率={self.difference_rate:.2%}"
        )


# ============================================================================
# 011-async-ws-ioc-trading: 异步重构数据模型
# ============================================================================

@dataclass
class OrderBookSnapshot:
    """
    订单簿快照

    从WebSocket接收的订单簿数据快照，包含时间戳用于数据新鲜度检查。
    """
    exchange: str                              # 交易所标识: 'extended' or 'lighter'
    timestamp_ms: float                        # 数据生成时间戳（毫秒，交易所提供）
    bid_price: Decimal                         # 买一价
    ask_price: Decimal                         # 卖一价
    bid_qty: Decimal                           # 买一量
    ask_qty: Decimal                           # 卖一量
    local_update_time: float = field(default_factory=lambda: __import__('time').time() * 1000)  # 本地更新时间（毫秒）
    is_stale: bool = False                     # 数据过期标记

    def __post_init__(self):
        """验证数据"""
        if self.bid_price <= 0 or self.ask_price <= 0:
            raise ValueError("价格必须大于0")
        if self.bid_qty < 0 or self.ask_qty < 0:
            raise ValueError("数量不能为负")
        if self.bid_price >= self.ask_price:
            raise ValueError(f"买一价({self.bid_price})必须小于卖一价({self.ask_price})")

    @property
    def spread(self) -> Decimal:
        """价差 = ask_price - bid_price"""
        return self.ask_price - self.bid_price

    @property
    def mid_price(self) -> Decimal:
        """中间价 = (bid_price + ask_price) / 2"""
        return (self.bid_price + self.ask_price) / 2


@dataclass
class TimingRecord:
    """
    时间戳记录

    用于记录交易流程中的关键时间点，分析性能瓶颈。
    """
    name: str                                  # 记录名称: 'signal', 'send_A', 'send_B', 'ack_A', 'ack_B'
    timestamp_ms: float                        # 时间戳（毫秒）
    metadata: dict = field(default_factory=dict)  # 附加元数据

    def __str__(self) -> str:
        return f"[{self.name}] {self.timestamp_ms:.2f}ms"

    def latency_to(self, other: 'TimingRecord') -> float:
        """计算到另一个记录的延迟（毫秒）"""
        return other.timestamp_ms - self.timestamp_ms


@dataclass
class DataFreshnessResult:
    """
    数据新鲜度检查结果

    检查订单簿数据是否在可接受的时间窗口内。
    """
    is_fresh: bool                              # 是否新鲜
    data_age_ms: float                         # 数据年龄（毫秒）
    threshold_ms: float                        # 阈值（毫秒）
    exchange: str                              # 交易所标识
    data_timestamp: float                      # 数据时间戳
    check_timestamp: float                     # 检查时间戳

    def __str__(self) -> str:
        status = "✅ 新鲜" if self.is_fresh else "❌ 过期"
        return (
            f"{status} | {self.exchange} | "
            f"数据年龄: {self.data_age_ms:.1f}ms | "
            f"阈值: {self.threshold_ms:.1f}ms"
        )

    @classmethod
    def fresh(cls, exchange: str, data_ts: float, threshold_ms: float = 500) -> 'DataFreshnessResult':
        """创建新鲜结果"""
        current_time = __import__('time').time() * 1000
        data_age = current_time - data_ts
        return cls(
            is_fresh=True,
            data_age_ms=data_age,
            threshold_ms=threshold_ms,
            exchange=exchange,
            data_timestamp=data_ts,
            check_timestamp=current_time
        )

    @classmethod
    def stale(cls, exchange: str, data_ts: float, threshold_ms: float = 500) -> 'DataFreshnessResult':
        """创建过期结果"""
        current_time = __import__('time').time() * 1000
        data_age = current_time - data_ts
        return cls(
            is_fresh=False,
            data_age_ms=data_age,
            threshold_ms=threshold_ms,
            exchange=exchange,
            data_timestamp=data_ts,
            check_timestamp=current_time
        )


@dataclass
class SlippageCheckResult:
    """
    滑点检查结果

    检查预期价格与当前价格的偏差是否在可接受范围内。
    """
    is_acceptable: bool                        # 是否可接受
    expected_price: Decimal                    # 预期成交价
    current_price: Decimal                     # 当前盘口价
    slippage_rate: Decimal                     # 滑点率（绝对值）
    threshold_rate: Decimal                    # 阈值
    side: str                                  # 方向: 'buy' or 'sell'

    def __str__(self) -> str:
        status = "✅ 可接受" if self.is_acceptable else "❌ 超阈值"
        return (
            f"{status} | {self.side} | "
            f"预期价: ${self.expected_price:.4f} | "
            f"当前价: ${self.current_price:.4f} | "
            f"滑点: {self.slippage_rate:.4%} | "
            f"阈值: {self.threshold_rate:.4%}"
        )

    @property
    def slippage_amount(self) -> Decimal:
        """滑点金额（绝对值）"""
        return abs(self.current_price - self.expected_price)


@dataclass
class ProfitabilityCheckResult:
    """
    利润率检查结果

    检查扣除成本后的净利润是否满足要求。
    """
    is_profitable: bool                        # 是否可交易
    spread_rate: Decimal                       # 原始价差率
    total_fees: Decimal                        # 双边手续费总和
    expected_slippage: Decimal                 # 预期滑点成本
    min_net_profit: Decimal                    # 最低净利要求
    net_profit_rate: Decimal                   # 净利润率
    decision: str                              # 决策描述

    def __str__(self) -> str:
        status = "✅ 可交易" if self.is_profitable else "❌ 不足利润"
        return (
            f"{status} | "
            f"价差率: {self.spread_rate:.4%} | "
            f"手续费: {self.total_fees:.4%} | "
            f"预期滑点: {self.expected_slippage:.4%} | "
            f"最小净利: {self.min_net_profit:.4%} | "
            f"净利: {self.net_profit_rate:.4%} | "
            f"决策: {self.decision}"
        )

    @property
    def profit_margin(self) -> Decimal:
        """利润边际 = net_profit_rate - min_net_profit"""
        return self.net_profit_rate - self.min_net_profit


@dataclass
class TradeOperationRecord:
    """
    交易操作记录

    记录开仓/平仓的完整时间戳链和结果，用于性能分析和复盘。
    """
    timestamp: float                           # 记录时间戳
    operation_type: str                        # 操作类型: 'OPEN', 'CLOSE', 'EMERGENCY_CLOSE'
    exchange: str                              # 交易所: 'BOTH', 'EXTENDED', 'LIGHTER'

    # 时间戳链（全部可选）
    signal_ts: Optional[float] = None          # 策略信号触发时间
    data_ts_A: Optional[float] = None          # Extended数据时间
    data_ts_B: Optional[float] = None          # Lighter数据时间
    calc_ts: Optional[float] = None            # 计算完成时间
    send_A_ts: Optional[float] = None          # Extended发送时间
    send_B_ts: Optional[float] = None          # Lighter发送时间
    ack_A_ts: Optional[float] = None           # Extended ACK时间
    ack_B_ts: Optional[float] = None           # Lighter ACK时间

    # 交易数据
    spread_rate: Optional[Decimal] = None      # 价差率
    slippage_rate: Optional[Decimal] = None    # 实际滑点率
    profit_rate: Optional[Decimal] = None      # 利润率

    # 结果
    decision: str = "PENDING"                  # 决策: 'ALLOWED', 'REJECTED', ...
    status: str = "PENDING"                    # 状态: 'SUCCESS', 'FAILED', 'PARTIAL'
    reason: Optional[str] = None               # 失败原因

    # 并发指标
    send_gap_ms: Optional[float] = None        # 并发发送间隔

    def __post_init__(self):
        """设置默认timestamp"""
        if self.timestamp == 0:
            self.timestamp = __import__('time').time()

    @property
    def tick_to_trade_latency_ms(self) -> Optional[float]:
        """行情→交易延迟"""
        if self.signal_ts and self.send_A_ts:
            return self.send_A_ts - self.signal_ts
        return None

    @property
    def execution_latency_ms(self) -> Optional[float]:
        """执行延迟"""
        if self.send_A_ts and self.ack_A_ts:
            return self.ack_A_ts - self.send_A_ts
        return None

    @property
    def data_freshness_A_ms(self) -> Optional[float]:
        """Extended数据年龄"""
        if self.data_ts_A and self.signal_ts:
            return self.signal_ts - self.data_ts_A
        return None

    @property
    def data_freshness_B_ms(self) -> Optional[float]:
        """Lighter数据年龄"""
        if self.data_ts_B and self.signal_ts:
            return self.signal_ts - self.data_ts_B
        return None

    def to_csv_row(self) -> dict:
        """转换为CSV行"""
        return {
            'timestamp': str(int(self.timestamp)),
            'operation_type': self.operation_type,
            'exchange': self.exchange,
            'signal_ts': f"{self.signal_ts:.2f}" if self.signal_ts else '',
            'data_ts_A': f"{self.data_ts_A:.2f}" if self.data_ts_A else '',
            'data_ts_B': f"{self.data_ts_B:.2f}" if self.data_ts_B else '',
            'send_A_ts': f"{self.send_A_ts:.2f}" if self.send_A_ts else '',
            'send_B_ts': f"{self.send_B_ts:.2f}" if self.send_B_ts else '',
            'ack_A_ts': f"{self.ack_A_ts:.2f}" if self.ack_A_ts else '',
            'ack_B_ts': f"{self.ack_B_ts:.2f}" if self.ack_B_ts else '',
            'spread_rate': f"{self.spread_rate:.6f}" if self.spread_rate is not None else '',
            'slippage_rate': f"{self.slippage_rate:.6f}" if self.slippage_rate is not None else '',
            'profit_rate': f"{self.profit_rate:.6f}" if self.profit_rate is not None else '',
            'decision': self.decision,
            'status': self.status,
            'send_gap_ms': f"{self.send_gap_ms:.2f}" if self.send_gap_ms is not None else ''
        }
