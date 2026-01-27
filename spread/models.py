"""
数据模型：Lighter-Extended 单向价差收敛套利系统

核心数据实体：
- OrderBook: 订单簿数据
- SpreadInfo: 价差信息
- Position: 持仓信息
- BotStats: 机器人统计信息
- BotConfig: 机器人配置
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple
from enum import Enum


class BotState(Enum):
    """机器人状态枚举"""
    IDLE = "IDLE"           # 空闲，等待机会
    OPENING = "OPENING"     # 开仓中
    OPENING_TAKER = "OPENING_TAKER"  # 市价开仓中（立即执行）
    OPENING_MAKER_WAIT = "OPENING_MAKER_WAIT"  # 开仓挂单等待成交（Maker模式）
    OPENING_WAIT = "OPENING_WAIT"  # 开仓后等待确认仓位
    HOLDING = "HOLDING"     # 持仓中
    CLOSING = "CLOSING"     # 平仓中
    CLOSING_MAKER_WAIT = "CLOSING_MAKER_WAIT"  # 平仓挂单等待成交（Maker模式）
    CLOSING_TAKER = "CLOSING_TAKER"   # 市价平仓中（立即执行）
    LIGHTER_HEDGING = "LIGHTER_HEDGING"  # lighter对冲中（Maker模式，Extended成交后对冲）
    CLOSING_WAIT = "CLOSING_WAIT"  # 平仓后等待确认仓位
    PAUSED = "PAUSED"       # 风控暂停模式（API异常时）
    ERROR = "ERROR"         # 错误状态


class PositionState(Enum):
    """持仓状态枚举"""
    NONE = "NONE"           # 无持仓
    LONG = "LONG"           # 多头（Extended买入，Lighter卖出）
    SHORT = "SHORT"         # 空头（Extended卖出，Lighter买入）


@dataclass
class OrderBook:
    """
    订单簿数据类

    验证规则：
    - 所有价格必须 > 0
    - 所有数量必须 >= 0
    - 最佳买价必须 < 最佳卖价
    """
    exchange: str                      # "lighter" 或 "extended"
    symbol: str                        # 交易对，如 "BTC-USD"
    bids: Dict[Decimal, Decimal]       # 价格 -> 数量（买单）
    asks: Dict[Decimal, Decimal]       # 价格 -> 数量（卖单）
    last_update: datetime = field(default_factory=datetime.now)
    sequence: int = 0                  # 序列号，用于验证数据完整性
    is_valid: bool = True              # 数据是否有效

    def get_best_bid(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        获取最佳买价和数量

        Returns:
            (价格, 数量) 元组，如果没有买单则返回 None
        """
        if not self.bids:
            return None
        best_price = max(self.bids.keys())
        return (best_price, self.bids[best_price])

    def get_best_ask(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        获取最佳卖价和数量

        Returns:
            (价格, 数量) 元组，如果没有卖单则返回 None
        """
        if not self.asks:
            return None
        best_price = min(self.asks.keys())
        return (best_price, self.asks[best_price])

    def check_depth(self, quantity: Decimal) -> bool:
        """
        检查订单簿深度是否足够

        Args:
            quantity: 需要检查的数量

        Returns:
            True 如果深度足够，否则 False
        """
        # 检查卖单深度（用于买入）
        total_ask_volume = sum(self.asks.values())
        # 检查买单深度（用于卖出）
        total_bid_volume = sum(self.bids.values())

        return total_ask_volume >= quantity and total_bid_volume >= quantity

    def validate(self) -> bool:
        """
        验证订单簿数据的有效性

        Returns:
            True 如果数据有效，否则 False
        """
        # 检查价格和数量的有效性
        for price, qty in self.bids.items():
            if price <= 0 or qty < 0:
                return False

        for price, qty in self.asks.items():
            if price <= 0 or qty < 0:
                return False

        # 检查最佳买价必须 < 最佳卖价
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid and best_ask:
            if best_bid[0] >= best_ask[0]:
                return False

        return True


@dataclass
class SpreadInfo:
    """
    价差信息数据类

    存储价差计算的完整信息
    """
    open_spread: Optional[Decimal] = None    # 开仓价差
    close_spread: Optional[Decimal] = None   # 平仓价差
    lighter_bid_vwap: Optional[Decimal] = None   # Lighter 买方 VWAP
    lighter_ask_vwap: Optional[Decimal] = None   # Lighter 卖方 VWAP
    extended_bid_vwap: Optional[Decimal] = None  # Extended 买方 VWAP
    extended_ask_vwap: Optional[Decimal] = None  # Extended 卖方 VWAP
    timestamp: datetime = field(default_factory=datetime.now)
    is_reasonable: bool = True               # 价差是否合理（非极端价差）


@dataclass
class Position:
    """
    持仓信息数据类

    验证规则：
    - LONG 状态时：extended_quantity > 0, lighter_quantity < 0
    - SHORT 状态时：extended_quantity < 0, lighter_quantity > 0
    - 数量必须匹配（绝对值相等）
    """
    state: PositionState = PositionState.NONE
    extended_entry_price: Decimal = Decimal("0")
    lighter_entry_price: Decimal = Decimal("0")
    entry_spread: Decimal = Decimal("0")
    entry_time: Optional[datetime] = None
    extended_quantity: Decimal = Decimal("0")
    lighter_quantity: Decimal = Decimal("0")
    extended_order_id: Optional[str] = None
    lighter_order_id: Optional[str] = None

    def is_open(self) -> bool:
        """是否有持仓"""
        return self.state != PositionState.NONE

    def validate(self) -> bool:
        """
        验证持仓数据的有效性

        Returns:
            True 如果数据有效，否则 False
        """
        if self.state == PositionState.NONE:
            return self.extended_quantity == 0 and self.lighter_quantity == 0

        # 检查数量是否匹配（绝对值相等）
        if abs(self.extended_quantity) != abs(self.lighter_quantity):
            return False

        if self.state == PositionState.LONG:
            return self.extended_quantity > 0 and self.lighter_quantity < 0

        if self.state == PositionState.SHORT:
            return self.extended_quantity < 0 and self.lighter_quantity > 0

        return False


@dataclass
class Trade:
    """
    交易记录数据类

    记录单笔交易的详细信息
    """
    trade_id: str                           # 唯一交易 ID
    timestamp: datetime                     # 交易时间
    exchange: str                           # "lighter" 或 "extended"
    side: str                               # "buy" 或 "sell"
    price: Decimal                          # 成交价格
    quantity: Decimal                       # 成交数量
    order_type: str                         # "OPEN" 或 "CLOSE"
    spread: Optional[Decimal] = None        # 当时价差
    profit: Optional[Decimal] = None        # 利润（仅平仓时）

    def to_csv_row(self) -> list:
        """转换为 CSV 行格式"""
        return [
            self.trade_id,
            self.timestamp.isoformat(),
            self.exchange,
            self.side,
            str(self.price),
            str(self.quantity),
            self.order_type,
            str(self.spread) if self.spread else "",
            str(self.profit) if self.profit else ""
        ]


@dataclass
class BotStats:
    """
    机器人统计信息数据类

    跟踪机器人的运行统计
    """
    total_trades: int = 0                   # 总交易次数
    profitable_trades: int = 0              # 盈利交易次数
    total_profit: Decimal = Decimal("0")    # 累计利润
    total_fees: Decimal = Decimal("0")      # 累计手续费
    start_time: Optional[datetime] = None   # 启动时间
    last_trade_time: Optional[datetime] = None  # 最后交易时间

    @property
    def win_rate(self) -> float:
        """胜率"""
        if self.total_trades == 0:
            return 0.0
        return self.profitable_trades / self.total_trades

    @property
    def avg_profit(self) -> Decimal:
        """平均利润"""
        if self.total_trades == 0:
            return Decimal("0")
        return self.total_profit / self.total_trades

    @property
    def net_profit(self) -> Decimal:
        """净利润（扣除手续费）"""
        return self.total_profit - self.total_fees


@dataclass
class BotConfig:
    """
    机器人配置数据类

    配置参数可通过命令行参数、环境变量或默认值设置
    """
    # 交易参数
    symbol: str = "ETH"                                    # 交易对
    target_quantity: Decimal = Decimal("0.01")             # 目标交易数量
    min_spread_threshold: Decimal = Decimal("0.0007")       # 最小价差阈值 0.2%

    # 风控参数
    slippage_buffer: Decimal = Decimal("0.0001")           # 滑点保护 0.05%
    min_profit: Decimal = Decimal("0")                      # 最小利润 0%
    max_spread: Decimal = Decimal("0.05")                  # 极端价差阈值 5%
    single_side_timeout: float = 3.0                       # 单边超时 3 秒

    # 交易所配置
    lighter_account_index: int = 0
    lighter_api_key_index: int = 0
    extended_vault: str = ""

    # 可选参数
    dry_run: bool = False                                  # 模拟运行模式
    verbose: bool = False                                  # 详细日志模式
    enable_telegram: bool = False                          # 启用 Telegram 通知

    # ========== 新增字段 (016-spread-optimize) ==========
    # 等差数列开仓策略相关
    cached_open_spread: Decimal = field(default_factory=lambda: Decimal("0"))
    """
    上次开仓价差（用于等差数列策略）
    - 初始值为0
    - 首次开仓时设置为当前价差
    - 后续每次开仓后更新为新的价差
    - 价差缩小时不降低
    """

    # 注意：spread_step 已移至 003-spreading-improvements 新增字段区域
    # 此处保留注释说明旧逻辑已被阶梯开仓替代

    # 仓位平衡检测相关
    balance_check_buffer: float = 3.0
    """
    仓位平衡检测缓冲期（秒）
    - 默认3秒
    - 开仓后在此时间内验证两边仓位
    - 不平衡时立即平仓
    """

    # 开仓等待确认相关
    open_wait_timeout: float = 10.0
    """
    开仓等待确认超时时间（秒）
    - 默认10秒
    - 开仓后等待确认两边仓位的时间
    - 超时或仓位不一致时强制平仓
    - 等待期间不继续开仓
    """

    # 智能平仓系统相关
    total_fee_rate: Decimal = field(default_factory=lambda: Decimal("0.0005"))
    """
    总手续费率
    - 默认0.05% = 0.0005
    - 包含两个交易所的开仓和平仓手续费
    - Extended: 0.025% x 2 = 0.05%
    - Lighter: ~0.025% x 2 = 0.05%
    - 总计约0.05%
    """

    # ========== 新增字段 (017-ext-maker-mode) ==========
    # Maker模式相关配置
    use_maker_mode: bool = True
    """
    是否使用Maker模式
    - 默认False（使用Taker模式）
    - True: Extended使用Maker挂单模式（串行执行：Extended先成交，然后Lighter对冲）
    - False: Extended使用Taker吃单模式（并发执行：Extended和Lighter同时下单）
    """

    fixed_open_threshold: Decimal = field(default_factory=lambda: Decimal("0.0003"))
    """
    固定开仓阈值（Maker模式使用）
    - 默认0.09% = 0.0009
    - 当前价差 >= 此阈值时触发开仓
    - 替代原有的阶梯式等差数列策略
    """

    fixed_close_threshold: Decimal = field(default_factory=lambda: Decimal("0.0002"))
    """
    固定平仓阈值（Maker模式使用）
    - 默认0.06% = 0.0006
    - 当 开仓价差 - 当前价差 - 手续费 > 此阈值时触发平仓
    - 替代原有的智能平仓策略
    """

    maker_order_timeout: float = 30.0
    """
    Maker挂单超时时间（秒）
    - 默认30秒
    - Extended Maker订单在此时间后仍未成交时的处理策略
    - 根据Edge Case决策：继续等待直到成交或价格不满足条件
    """

    price_monitor_interval: float = 1
    """
    价格监控间隔（秒）
    - 默认0.5秒
    - 监控Extended订单簿BBO价格的频率
    - 用于价格位置优化（检测挂单是否仍处于最优位置）
    """

    reposition_cooldown: float = 2.0
    """
    重挂冷却时间（秒）
    - 默认2.0秒
    - 避免频繁重挂订单
    - 价格偏离后需要等待此时间才能再次重挂
    """

    spread_monitor_interval: float = 1
    """
    价差监控间隔（秒）
    - 默认0.5秒
    - 监控Extended和Lighter实时价差的频率
    - 用于价差保护（价差 < 开仓阈值时取消挂单）
    """

    max_reposition_count: int = 10
    """
    连续重挂次数限制
    - 默认10次
    - 价格频繁波动导致系统不断取消并重新挂单时，超过此次数后取消挂单
    - 防止无限循环重挂
    """

    maker_fee_rate: Decimal = field(default_factory=lambda: Decimal("0.0"))
    """
    Extended Maker手续费率
    - 默认0%（接近0%）
    - 用于统计和利润计算
    - 相比Taker模式0.025%的手续费，Maker模式几乎无手续费
    """

    # ========== 新增字段 (003-spreading-improvements) ==========
    # 杠杆配置
    leverage: Decimal = field(default_factory=lambda: Decimal("20"))
    """
    杠杆倍数
    - 默认20x
    - 可用保证金 x 杠杆 = 最大可开仓位
    """


    # 阶梯价差开仓配置
    initial_open_spread: Decimal = field(default_factory=lambda: Decimal("0.0015"))
    """
    初始开仓价差阈值
    - 默认0.5% = 0.005
    - 第一次开仓使用此阈值
    """

    spread_step: Decimal = field(default_factory=lambda: Decimal("0.00002"))
    """
    开仓步长
    - 默认0.1% = 0.001
    - 第N次开仓阈值 = initial_open_spread + (N-1) * spread_step
    """

    opening_count: int = 0
    """
    当前开仓次数（已弃用，保留用于兼容性）
    - 初始值为0
    - 已被 successful_opening_count 替代
    """

    successful_opening_count: int = 0
    """
    成功开仓次数（方案B：只计算真正成功的开仓）
    - 初始值为0
    - 只在仓位成功添加到Portfolio后递增
    - 所有仓位平仓后重置为0
    - 用于计算当前开仓阈值（阶梯开仓）
    - 不受开仓失败、重试、部分成交影响
    """

    @property
    def current_open_threshold(self) -> Decimal:
        """
        计算当前开仓阈值（使用成功开仓次数）

        阶梯开仓公式：
        - 第1次开仓：initial_open_spread + 0 * spread_step
        - 第2次开仓：initial_open_spread + 1 * spread_step
        - 第N次开仓：initial_open_spread + (N-1) * spread_step

        Returns:
            当前开仓阈值
        """
        return self.initial_open_spread + (self.successful_opening_count * self.spread_step)

    # 双模式平仓配置
    limit_close_spread_a: Decimal = field(default_factory=lambda: Decimal("0.00005"))
    """
    限价平仓阈值A
    - 默认0.005% = 0.00005
    - 用于判断是否使用限价平仓
    """

    market_close_spread_b: Decimal = field(default_factory=lambda: Decimal("0.0001"))
    """
    市价平仓阈值B
    - 默认0.01% = 0.0001
    - 用于判断是否使用市价平仓
    - 必须大于 limit_close_spread_a
    """

    lighter_hedge_slippage_bps: Decimal = field(default_factory=lambda: Decimal("0.002"))
    """
    Lighter对冲VWAP滑点缓冲
    - 默认0.02% = 0.0002
    - 买入时在VWAP基础上上浮，卖出时在VWAP基础上下调
    """

    # ========== 新增字段：布林带动态阈值 ==========
    use_bollinger: bool = True
    """
    是否使用布林带动态阈值
    - True: 开仓/平仓信号基于布林带
    - False: 使用原阶梯阈值
    """

    boll_window_minutes: int = 60
    """布林带统计窗口（分钟）"""

    boll_k: Decimal = field(default_factory=lambda: Decimal("2"))
    """布林带标准差倍数"""

    open_taker_sigma: Decimal = field(default_factory=lambda: Decimal("2.5"))
    """市价开仓触发Sigma倍数（突破该值触发市价开仓）"""

    open_maker_sigma: Decimal = field(default_factory=lambda: Decimal("1.75"))
    """挂单开仓触发Sigma倍数（突破该值触发挂单开仓）"""

    open_sigma_penalty: Decimal = field(default_factory=lambda: Decimal("0.5"))
    """库存倾斜惩罚系数（Sigma上移系数）"""

    open_maker_confirm_seconds: float = 2.0
    """挂单开仓确认窗（秒）"""

    open_maker_hysteresis_sigma: Decimal = field(default_factory=lambda: Decimal("0.75"))
    """挂单开仓撤销滞回（Sigma）"""

    close_limit_hysteresis_sigma: Decimal = field(default_factory=lambda: Decimal("1"))
    """挂单平仓触发阈值（Sigma，入场更严格）"""

    boll_sample_interval: float = 1.0
    """布林带采样间隔（秒）"""

    boll_min_samples: int = 60
    """布林带最小样本数"""

    boll_bandwidth_min: Decimal = field(default_factory=lambda: Decimal("0.001"))
    """布林带宽度阈值（(upper-lower)/midline），低于则不开仓"""

    # ========== 新增字段：腾笼换鸟 ==========
    switch_cost_bps: Decimal = field(default_factory=lambda: Decimal("0.000225"))
    """腾笼换鸟换仓成本（固定）"""

    switch_min_hold_minutes: int = 10
    """腾笼换鸟：持仓最短时间（分钟）"""

    notify_open_trigger: bool = False
    """是否推送开仓触发（信号）"""


    # 已弃用：旧的上轨+gap开仓逻辑，仅保留兼容字段
    open_taker_gap_bps: Decimal = field(default_factory=lambda: Decimal("0.0002"))
    """[deprecated] 旧的上轨+gap开仓参数（布林带σ策略不使用）"""

    open_taker_on_upper: bool = True
    """[deprecated] 旧的上轨市价开仓开关（布林带σ策略不使用）"""

    close_market_on_lower: bool = False
    """
    是否在价差触达下轨时使用市价平仓
    - True: 价差 <= 下轨时市价平仓
    - False: 下轨仅作为参考，不强制市价平仓
    """

    dashboard_ingest_url: str = ""
    """Dashboard数据写入URL（例如: http://localhost:3000/api/ingest）"""

    dashboard_sample_interval: float = 1.0
    """Dashboard采样频率（秒）"""

    dashboard_position_interval: float = 1.0
    """Dashboard仓位/余额采样间隔（秒）"""

    maker_close_fail_threshold: int = 3
    """Maker平仓失败阈值，超过后自动改用市价平仓"""

    def validate(self) -> bool:
        """
        验证配置参数的有效性

        Returns:
            True 如果配置有效，否则 False
        """
        if self.target_quantity <= 0:
            return False
        if self.min_spread_threshold <= 0:
            return False
        if self.slippage_buffer < 0:
            return False
        if self.min_profit < 0:  # 允许 0 利润
            return False
        if self.max_spread <= 0 or self.max_spread > 1:
            return False
        if self.single_side_timeout <= 0:
            return False

        # 检查利润阈值（如果设置了利润）必须大于滑点缓冲 + 手续费
        # Lighter 0% taker fee, Extended 0.025% taker fee
        # 如果 min_profit = 0，则跳过此检查
        if self.min_profit > 0:
            min_required_profit = self.slippage_buffer + Decimal("0.00025")
            if self.min_profit < min_required_profit:
                return False

        # 新增字段验证 (016-spread-optimize)
        if self.spread_step <= 0:
            return False
        if self.balance_check_buffer <= 0:
            return False
        if self.open_wait_timeout <= 0:
            return False
        if self.total_fee_rate < 0:
            return False
        # 只有当设置了利润目标时，才检查利润空间
        if self.min_profit > 0 and self.min_profit <= self.total_fee_rate:
            return False  # 确保有利润空间

        # 新增字段验证 (017-ext-maker-mode)
        if self.fixed_open_threshold <= 0:
            return False
        if self.fixed_close_threshold <= 0:
            return False
        if self.maker_order_timeout <= 0:
            return False
        if self.price_monitor_interval <= 0:
            return False
        if self.spread_monitor_interval <= 0:
            return False
        if self.max_reposition_count <= 0:
            return False
        if self.maker_fee_rate < 0:
            return False
        # 固定开仓阈值应该大于固定平仓阈值
        if self.fixed_open_threshold <= self.fixed_close_threshold:
            return False

        # 新增字段验证 (003-spreading-improvements)
        if self.initial_open_spread <= 0:
            return False
        if self.spread_step <= 0:
            return False
        if self.opening_count < 0:
            return False
        if self.limit_close_spread_a <= 0:
            return False
        if self.market_close_spread_b <= 0:
            return False
        if self.market_close_spread_b <= self.limit_close_spread_a:
            return False
        if self.boll_window_minutes <= 0:
            return False
        if self.boll_k <= 0:
            return False
        if self.open_taker_sigma <= 0:
            return False
        if self.open_maker_sigma <= 0:
            return False
        if self.open_taker_sigma <= self.open_maker_sigma:
            return False
        if self.open_sigma_penalty < 0:
            return False
        if self.open_maker_confirm_seconds < 0:
            return False
        if self.open_maker_hysteresis_sigma < 0:
            return False
        if self.close_limit_hysteresis_sigma < 0:
            return False
        if self.boll_sample_interval <= 0:
            return False
        if self.boll_min_samples <= 0:
            return False
        if self.boll_bandwidth_min < 0:
            return False
        if self.switch_cost_bps < 0:
            return False
        if self.switch_min_hold_minutes < 0:
            return False
        if self.open_taker_gap_bps < 0:
            return False
        if self.dashboard_sample_interval <= 0:
            return False
        if self.dashboard_position_interval <= 0:
            return False
        if self.maker_close_fail_threshold < 1:
            return False

        return True


# ========== 新增数据类 (016-spread-optimize) ==========

class OpenStrategyState(Enum):
    """开仓策略状态"""
    WAITING = "waiting"      # 等待价差
    READY = "ready"          # 满足开仓条件
    EXECUTING = "executing"  # 执行开仓中
    SUCCESS = "success"      # 开仓成功
    FAILED = "failed"        # 开仓失败


@dataclass
class RealTimeSpreadInfo:
    """
    实时价差信息（用于SpreadMonitor）

    与SpreadInfo不同，这个类用于实时监控两个交易所的订单簿价格
    """
    # Extended订单簿价格
    ext_bid: Decimal
    ext_ask: Decimal

    # Lighter订单簿价格
    lig_bid: Decimal
    lig_ask: Decimal

    # 计算的价差
    spread_abs: Decimal     # 绝对价差
    spread_pct: Decimal      # 百分比价差

    # 时间戳
    timestamp: float         # Unix时间戳

    @property
    def ext_mid(self) -> Decimal:
        """Extended中间价"""
        return (self.ext_bid + self.ext_ask) / 2

    @property
    def lig_mid(self) -> Decimal:
        """Lighter中间价"""
        return (self.lig_bid + self.lig_ask) / 2

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

    def format_log(self, open_threshold: Decimal, slippage_buffer: Decimal) -> str:
        """格式化为单行日志字符串

        Args:
            open_threshold: 开仓阈值（如 0.20%）
            slippage_buffer: 滑点保护（如 0.05%）

        Returns:
            格式化的日志字符串
        """
        # 计算实际开仓阈值
        required_threshold = open_threshold + slippage_buffer

        # 判断是否满足开仓条件
        action = "开仓" if self.spread_pct >= required_threshold else "不开仓"

        return (
            f"价差: Ext[{self.ext_bid:.1f}/{self.ext_ask:.1f}] "
            f"Lig[{self.lig_bid:.1f}/{self.lig_ask:.1f}] = "
            f"{self.spread_abs:.1f} ({self.spread_pct:.3%}) "
            f"< {required_threshold:.3%} ({open_threshold:.3%}阈值+{slippage_buffer:.3%}滑点) {action}"
        )


@dataclass
class OpenPosition:
    """
    单笔开仓记录（用于等差数列策略）
    """
    # 基础信息
    position_id: str                    # 唯一标识
    open_time: float                    # 开仓时间戳

    # 价格信息
    ext_price: Decimal                  # Extended开仓价格
    lig_price: Decimal                  # Lighter开仓价格
    open_spread: Decimal                # 开仓价差

    # 数量信息
    quantity: Decimal                   # 开仓数量

    # 订单信息
    ext_order_id: Optional[str] = None
    lig_order_id: Optional[str] = None

    # 状态
    is_active: bool = True              # 是否仍持有（未平仓）
    open_is_taker: bool = False         # 是否市价开仓

    def format_log(self) -> str:
        """格式化为单行日志"""
        status = "持有" if self.is_active else "已平"
        return (
            f"仓位[{self.position_id[:8]}]: "
            f"{status} | "
            f"数量={self.quantity} | "
            f"价差={self.open_spread:.3%} | "
            f"Ext={self.ext_price:.1f} | "
            f"Lig={self.lig_price:.1f}"
        )


@dataclass
class Portfolio:
    """
    仓位组合（支持等差数列多笔仓位）

    管理多笔开仓记录，计算加权平均价差
    """
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

    def has_open_taker(self) -> bool:
        """是否存在市价开仓的持仓"""
        return any(p.is_active and getattr(p, "open_is_taker", False) for p in self.positions)

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
            f"均价差={self.weighted_avg_entry_spread:.3%}"
        )


@dataclass
class BalanceCheckResult:
    """
    仓位平衡检查结果
    """
    is_balanced: bool                    # 是否平衡
    ext_quantity: Decimal                # Extended仓位数量
    lig_quantity: Decimal                # Lighter仓位数量
    check_time: float                    # 检查时间戳

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


@dataclass
class CloseTrigger:
    """
    平仓触发信息
    """
    # 触发条件
    is_triggered: bool                   # 是否触发平仓

    # 价差信息
    entry_spread: Decimal                # 开仓价差（加权平均）
    current_spread: Decimal              # 当前市场价差
    profit_target: Decimal               # 盈利目标
    fee_rate: Decimal                    # 手续费率

    # 计算结果
    expected_profit: Decimal             # 预期利润
    actual_profit: Decimal = field(default_factory=lambda: Decimal("0"))

    # 时间
    trigger_time: float = 0.0            # 触发时间

    def format_log(self) -> str:
        """格式化为单行日志"""
        if self.is_triggered:
            return (
                f"平仓触发: 开仓{self.entry_spread:.3%} >= "
                f"当前{self.current_spread:.3%} + "
                f"盈利{self.profit_target:.3%} + "
                f"手续费{self.fee_rate:.3%} | "
                f"利润={self.actual_profit:.2f}"
            )
        else:
            return (
                f"持仓监控: 开仓{self.entry_spread:.3%} vs "
                f"当前{self.current_spread:.3%} | "
                f"利润={self.expected_profit:.3%}"
            )


# ========== 新增数据类 (017-ext-maker-mode) ==========

@dataclass
class MakerOrder:
    """
    Extended Maker挂单订单数据类

    Attributes:
        order_id: 订单ID
        price: 挂单价格
        quantity: 挂单数量
        side: 挂单方向 (buy/sell)
        status: 订单状态 (NEW, OPEN, PARTIALLY_FILLED, FILLED, CANCELED)
        filled_quantity: 成交数量
        avg_fill_price: 成交均价
        created_at: 创建时间
        updated_at: 最后更新时间
        is_opening: 是否为开仓订单（True=开仓, False=平仓）
        context_id: 本次Maker上下文ID（用于补对冲校验）
    """
    order_id: str
    price: Decimal
    quantity: Decimal
    side: str  # 'buy' or 'sell'
    status: str = 'NEW'
    filled_quantity: Decimal = field(default_factory=lambda: Decimal('0'))
    avg_fill_price: Decimal = field(default_factory=lambda: Decimal('0'))
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    is_opening: bool = True  # True for opening, False for closing
    context_id: Optional[str] = None

    def update_from_websocket(self, order_data: dict) -> None:
        """
        从WebSocket更新订单状态

        Args:
            order_data: WebSocket订单数据字典，包含：
                - id: 订单ID
                - status: 订单状态
                - filledQty: 成交数量
                - price: 成交价格
        """
        self.updated_at = datetime.now()

        # 更新状态
        new_status = order_data.get('status', self.status)
        if new_status in ['NEW', 'OPEN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'CANCELLED']:
            if new_status == 'CANCELLED':
                self.status = 'CANCELED'
            else:
                self.status = new_status

        # 更新成交数量和均价
        filled_qty = order_data.get('filledQty', '0')
        if filled_qty:
            new_filled = Decimal(str(filled_qty))
            if new_filled > self.filled_quantity:
                # 计算新的平均价格
                old_total = self.avg_fill_price * self.filled_quantity
                fill_price = Decimal(str(order_data.get('price', '0')))
                new_total = old_total + (fill_price * (new_filled - self.filled_quantity))
                self.avg_fill_price = new_total / new_filled if new_filled > 0 else Decimal('0')
                self.filled_quantity = new_filled

    @property
    def remaining_quantity(self) -> Decimal:
        """获取剩余未成交数量"""
        return self.quantity - self.filled_quantity

    @property
    def is_fully_filled(self) -> bool:
        """是否完全成交"""
        return self.status == 'FILLED' or self.filled_quantity >= self.quantity

    @property
    def is_partially_filled(self) -> bool:
        """是否部分成交"""
        return (
            self.status == 'PARTIALLY_FILLED' or
            (self.filled_quantity > 0 and self.filled_quantity < self.quantity)
        )

    @property
    def is_canceled(self) -> bool:
        """是否已取消"""
        return self.status == 'CANCELED'

    @property
    def is_active(self) -> bool:
        """是否活跃（未成交且未取消）"""
        return self.status in ['NEW', 'OPEN', 'PENDING'] and not self.is_canceled


@dataclass
class MakerWaitState:
    """
    Maker等待状态数据类（用于OPENING_MAKER_WAIT和CLOSING_MAKER_WAIT状态）

    Attributes:
        current_order: 当前等待的Maker订单
        start_time: 等待开始时间
        spread_protection_triggers: 价差保护触发次数
        reposition_count: 价格调整次数（连续重挂计数）
        max_reposition_count: 连续重挂次数限制
        cumulative_filled: 部分成交累计数量
        this_opening_filled: 本次开仓成交记录（用于识别"本次开仓"部分）
        needs_reposition: 是否需要重新挂单
        last_reposition_time: 上次重挂时间戳（用于冷却时间检查）
        is_repositioning: 是否正在重挂中（防止并发调用）
        context_id: 本次Maker上下文ID（用于补对冲校验）
    """
    current_order: Optional[MakerOrder] = None
    start_time: datetime = field(default_factory=datetime.now)
    spread_protection_triggers: int = 0
    reposition_count: int = 0
    max_reposition_count: int = 10
    cumulative_filled: Decimal = field(default_factory=lambda: Decimal('0'))
    this_opening_filled: list = field(default_factory=list)  # 记录每次成交的订单ID和数量
    needs_reposition: bool = False
    last_reposition_time: float = 0.0  # 上次重挂时间戳
    is_repositioning: bool = False  # 防止并发重挂
    ext_position_before: Optional[Decimal] = None  # 下单前Ext仓位
    lig_position_before: Optional[Decimal] = None  # 下单前Lig仓位
    context_id: Optional[str] = None

    def reset(self) -> None:
        """重置状态"""
        self.current_order = None
        self.start_time = datetime.now()
        self.spread_protection_triggers = 0
        self.reposition_count = 0
        self.cumulative_filled = Decimal('0')
        self.this_opening_filled = []
        self.needs_reposition = False
        self.last_reposition_time = 0.0
        self.is_repositioning = False  # 重置重挂标志
        self.ext_position_before = None
        self.lig_position_before = None
        self.context_id = None

    def add_fill_record(self, order_id: str, filled_qty: Decimal) -> None:
        """添加成交记录"""
        self.this_opening_filled.append({
            'order_id': order_id,
            'filled_qty': filled_qty,
            'timestamp': datetime.now().isoformat()
        })
        self.cumulative_filled += filled_qty

    def get_this_opening_filled(self) -> Decimal:
        """获取本次开仓的累计成交数量"""
        return sum(record['filled_qty'] for record in self.this_opening_filled)

    def can_reposition(self) -> bool:
        """是否可以继续重挂"""
        return self.reposition_count < self.max_reposition_count


@dataclass
class HedgingState:
    """
    对冲状态数据类（用于LIGHTER_HEDGING状态）

    Attributes:
        ext_filled_quantity: Extended成交数量
        ext_filled_price: Extended成交价格
        lighter_order_id: Lighter对冲订单ID
        lighter_quantity: Lighter对冲数量
        start_time: 对冲开始时间
        timeout: 对冲超时时间（默认3秒）
    """
    ext_filled_quantity: Decimal = field(default_factory=lambda: Decimal('0'))
    ext_filled_price: Decimal = field(default_factory=lambda: Decimal('0'))
    lighter_order_id: Optional[str] = None
    lighter_quantity: Decimal = field(default_factory=lambda: Decimal('0'))
    start_time: datetime = field(default_factory=datetime.now)
    timeout: float = 3.0

    def is_timeout(self) -> bool:
        """是否超时"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return elapsed > self.timeout

    def reset(self) -> None:
        """重置状态"""
        self.ext_filled_quantity = Decimal('0')
        self.ext_filled_price = Decimal('0')
        self.lighter_order_id = None
        self.lighter_quantity = Decimal('0')
        self.start_time = datetime.now()


@dataclass
class SpreadConfig:
    """
    价差配置数据类（固定阈值策略）

    Attributes:
        open_threshold: 开仓阈值（默认0.09%）
        close_threshold: 平仓阈值（默认0.06%）
        maker_order_timeout: Maker挂单超时时间（默认30秒）
        price_monitor_interval: 价格监控间隔（默认0.5秒）
        spread_monitor_interval: 价差监控间隔（默认0.5秒）
        max_reposition_count: 连续重挂次数限制（默认10次）
    """
    open_threshold: Decimal = field(default_factory=lambda: Decimal('0.0009'))  # 0.09%
    close_threshold: Decimal = field(default_factory=lambda: Decimal('0.0006'))  # 0.06%
    maker_order_timeout: float = 30.0
    price_monitor_interval: float = 1
    spread_monitor_interval: float = 1
    max_reposition_count: int = 10

    def validate(self) -> bool:
        """验证配置有效性"""
        return (
            self.open_threshold > 0 and
            self.close_threshold > 0 and
            self.open_threshold > self.close_threshold and
            self.maker_order_timeout > 0 and
            self.price_monitor_interval > 0 and
            self.spread_monitor_interval > 0 and
            self.max_reposition_count > 0
        )


# ========== 新增数据类 (仓位监控) ==========

@dataclass
class ExchangePositionBalance:
    """
    单个交易所的仓位余额信息

    Attributes:
        exchange: 交易所名称 ("lighter" 或 "extended")
        current_position: 当前持仓数量（绝对值）
        available_balance: 可用余额（保证金）
        total_balance: 总余额（保证金）
        max_position: 最大可开仓数量（基于可用余额和杠杆）
        leverage: 杠杆倍数
        margin_used: 已使用保证金
        timestamp: 查询时间戳
    """
    exchange: str
    current_position: Decimal = field(default_factory=lambda: Decimal('0'))
    available_balance: Decimal = field(default_factory=lambda: Decimal('0'))
    total_balance: Decimal = field(default_factory=lambda: Decimal('0'))
    max_position: Decimal = field(default_factory=lambda: Decimal('0'))
    leverage: Decimal = field(default_factory=lambda: Decimal('1'))
    margin_used: Decimal = field(default_factory=lambda: Decimal('0'))
    timestamp: float = field(default_factory=lambda: __import__('time').time())

    @property
    def remaining_capacity(self) -> Decimal:
        """剩余可开仓量"""
        return max(Decimal('0'), self.max_position - self.current_position)

    @property
    def utilization_rate(self) -> Decimal:
        """仓位利用率"""
        if self.max_position > 0:
            return self.current_position / self.max_position
        return Decimal('0')

    def format_log(self) -> str:
        """格式化为日志字符串"""
        exchange_name = "Lig" if self.exchange == "lighter" else "Ext"
        return (
            f"{exchange_name}: "
            f"持仓={self.current_position:.4f} | "
            f"可用={self.available_balance:.2f} | "
            f"最大={self.max_position:.4f} | "
            f"剩余={self.remaining_capacity:.4f}"
        )


@dataclass
class PositionBalanceSnapshot:
    """
    仓位余额快照（包含两个交易所的完整信息）

    Attributes:
        lighter: Lighter交易所仓位余额
        extended: Extended交易所仓位余额
        timestamp: 快照时间戳
    """
    lighter: Optional[ExchangePositionBalance] = None
    extended: Optional[ExchangePositionBalance] = None
    timestamp: float = field(default_factory=lambda: __import__('time').time())

    def is_valid(self) -> bool:
        """检查快照是否有效"""
        return self.lighter is not None and self.extended is not None

    def format_log(self) -> str:
        """格式化为单行日志字符串"""
        if not self.is_valid:
            return "仓位余额: 数据获取中..."
        return (
            f"📊 仓位余额 | {self.lighter.format_log()} | {self.extended.format_log()}"
        )

    def format_compact_log(self) -> str:
        """格式化为紧凑日志字符串（用于状态栏）"""
        if not self.is_valid:
            return "Lig: - | Ext: -"
        lig_rem = self.lighter.remaining_capacity
        ext_rem = self.extended.remaining_capacity
        return f"Lig剩余={lig_rem:.4f} | Ext剩余={ext_rem:.4f}"


# ========== 新增数据类 (003-spreading-improvements) ==========

@dataclass
class CancelOrderResult:
    """
    取消订单操作结果

    Attributes:
        order_id: 被取消的订单ID
        canceled: 是否成功取消
        attempts: 尝试次数
        total_time: 总耗时（秒）
        final_status: 最终订单状态
        error_message: 错误信息
    """
    order_id: str
    canceled: bool
    attempts: int
    total_time: float

    final_status: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def is_successful(self) -> bool:
        """是否成功"""
        return self.canceled

    def format_log(self) -> str:
        """格式化为日志字符串"""
        if self.canceled:
            return (
                f"订单取消成功 | ID={self.order_id[:12]}... | "
                f"尝试={self.attempts}次 | 耗时={self.total_time:.1f}秒"
            )
        else:
            return (
                f"订单取消失败 | ID={self.order_id[:12]}... | "
                f"尝试={self.attempts}次 | "
                f"最终状态={self.final_status} | "
                f"错误={self.error_message or '未知'}"
            )


@dataclass
class TieredOpeningState:
    """
    阶梯开仓策略状态

    Attributes:
        current_count: 当前开仓次数
        current_threshold: 当前开仓阈值
        next_threshold: 下次开仓阈值
        initial_spread: 初始开仓价差
        step_size: 步长
        opening_history: 开仓历史记录
    """
    current_count: int = 0
    current_threshold: Decimal = field(default_factory=lambda: Decimal("0"))
    next_threshold: Decimal = field(default_factory=lambda: Decimal("0"))

    initial_spread: Decimal = field(default_factory=lambda: Decimal("0.005"))
    step_size: Decimal = field(default_factory=lambda: Decimal("0.001"))

    opening_history: list = field(default_factory=list)

    def calculate_threshold(self, count: int) -> Decimal:
        """计算指定次数的阈值"""
        return self.initial_spread + (count - 1) * self.step_size

    def advance(self) -> None:
        """推进到下一级"""
        self.current_count += 1
        self.current_threshold = self.calculate_threshold(self.current_count)
        self.next_threshold = self.calculate_threshold(self.current_count + 1)

    def reset(self) -> None:
        """重置（所有仓位平仓后）"""
        self.current_count = 0
        self.current_threshold = self.initial_spread
        self.next_threshold = self.calculate_threshold(1)
        self.opening_history.clear()

    def record_opening(self, actual_spread: Decimal) -> None:
        """记录一次开仓"""
        import time
        self.opening_history.append({
            'count': self.current_count,
            'threshold': self.current_threshold,
            'actual_spread': actual_spread,
            'timestamp': time.time()
        })

    def format_log(self) -> str:
        """格式化为日志字符串"""
        return (
            f"阶梯开仓 | 次数={self.current_count} | "
            f"当前阈值={self.current_threshold:.3%} | "
            f"下次阈值={self.next_threshold:.3%} | "
            f"初始={self.initial_spread:.3%} | "
            f"步长={self.step_size:.3%}"
        )


@dataclass
class CloseModeDecision:
    """
    双模式平仓决策结果

    Attributes:
        should_close: 是否应该平仓
        use_market: True=市价平仓, False=限价平仓
        total_position_spread: 总开仓仓位的价差
        current_spread: 当前市场价差
        market_threshold: 市价平仓阈值
        limit_threshold: 限价平仓阈值
        expected_profit_limit: 限价平仓预期利润
        expected_profit_market: 市价平仓预期利润
        decision_time: 决策时间
    """
    should_close: bool
    use_market: bool

    total_position_spread: Decimal = field(default_factory=lambda: Decimal("0"))
    current_spread: Decimal = field(default_factory=lambda: Decimal("0"))
    market_threshold: Decimal = field(default_factory=lambda: Decimal("0"))
    limit_threshold: Decimal = field(default_factory=lambda: Decimal("0"))

    expected_profit_limit: Decimal = field(default_factory=lambda: Decimal("0"))
    expected_profit_market: Decimal = field(default_factory=lambda: Decimal("0"))

    decision_time: float = field(default_factory=lambda: __import__('time').time())

    @property
    def close_mode_name(self) -> str:
        """平仓模式名称"""
        return "市价" if self.use_market else "限价"

    @property
    def reason(self) -> str:
        """决策原因"""
        if not self.should_close:
            return "不满足平仓条件"

        if self.use_market:
            return (
                f"市价平仓 | 利润大 | "
                f"利润{self.expected_profit_market:.3%} >= 市价阈值{self.market_threshold:.3%}"
            )
        else:
            return (
                f"限价平仓 | 利润小 | "
                f"利润{self.expected_profit_limit:.3%} >= 限价阈值{self.limit_threshold:.3%}"
            )

    def format_log(self) -> str:
        """格式化为日志字符串"""
        if not self.should_close:
            return (
                f"持仓监控 | 总开仓={self.total_position_spread:.3%} | "
                f"利润={self.expected_profit_limit:.3%} | "
                f"限价阈值={self.limit_threshold:.3%} | "
                f"市价阈值={self.market_threshold:.3%}"
            )
        else:
            return (
                f"平仓触发 | {self.close_mode_name} | {self.reason} | "
                f"总开仓={self.total_position_spread:.3%}"
            )


@dataclass
class BalanceAvailabilityResult:
    """
    开仓前余额可用性检测结果 (003-spreading-improvements: User Story 4)

    验证两个交易所的可用余额是否足够支持目标开仓数量。

    Attributes:
        is_sufficient: 余额是否充足（两个交易所都必须充足）
        ext_available: Extended可用USDT余额
        ext_required: Extended所需USDT金额
        lig_available: Lighter可用代币余额
        lig_required: Lighter所需代币数量
        check_time: 检查时间戳
        failure_reason: 失败原因（哪个交易所不足）
        shortage_amount: 缺少金额（USDT或代币数量）
        max_position: 最大可开仓位（考虑杠杆）
    """
    is_sufficient: bool
    ext_available: Decimal
    ext_required: Decimal
    lig_available: Decimal
    lig_required: Decimal
    check_time: float

    failure_reason: Optional[str] = None
    shortage_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    max_position: Decimal = field(default_factory=lambda: Decimal("0"))

    def format_log(self) -> str:
        """格式化为简洁日志字符串"""
        if self.is_sufficient:
            return (
                f"余额充足 Ext:{self.ext_available:.1f}/{self.ext_required:.1f} "
                f"Lig:{self.lig_available:.2f}/{self.lig_required:.2f} "
                f"最大可开{self.max_position:.3f}"
            )
        else:
            return (
                f"{self.failure_reason} "
                f"Ext:{self.ext_available:.1f}/{self.ext_required:.1f} "
                f"Lig:{self.lig_available:.2f}/{self.lig_required:.2f}"
            )
