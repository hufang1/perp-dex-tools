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
    HOLDING = "HOLDING"     # 持仓中
    CLOSING = "CLOSING"     # 平仓中
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
    symbol: str = "BTC"                                    # 交易对
    target_quantity: Decimal = Decimal("0.01")             # 目标交易数量
    min_spread_threshold: Decimal = Decimal("0.002")       # 最小价差阈值 0.2%

    # 风控参数
    slippage_buffer: Decimal = Decimal("0.0005")           # 滑点保护 0.05%
    min_profit: Decimal = Decimal("0.001")                 # 最小利润 0.1%
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
        if self.min_profit <= 0:
            return False
        if self.max_spread <= 0 or self.max_spread > 1:
            return False
        if self.single_side_timeout <= 0:
            return False

        # 检查利润阈值必须大于滑点缓冲 + 手续费
        # Lighter 0% taker fee, Extended 0.025% taker fee
        min_required_profit = self.slippage_buffer + Decimal("0.00025")
        if self.min_profit < min_required_profit:
            return False

        return True
