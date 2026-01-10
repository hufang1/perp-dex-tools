"""
Contract: Data Collection and Logging

This contract defines the interface for collecting trade data
for analysis and optimization.

Purpose: Enable data-driven optimization of the trading strategy.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal, NamedTuple, Any
from datetime import datetime


class TradeRecord(NamedTuple):
    """交易记录（用于导出）"""
    trade_id: str
    timestamp: float
    direction: Literal['long_spread', 'short_spread']

    # 开仓
    entry_extended_price: Decimal
    entry_lighter_price: Decimal
    entry_real_spread: Decimal
    entry_real_spread_rate: Decimal

    # 平仓
    exit_extended_price: Decimal | None
    exit_lighter_price: Decimal | None
    exit_real_spread: Decimal | None
    exit_real_spread_rate: Decimal | None

    # 持仓
    holding_time: float | None  # 秒

    # 成本
    entry_extended_fee: Decimal
    entry_lighter_fee: Decimal
    entry_extended_spread_cost: Decimal
    entry_lighter_spread_cost: Decimal
    entry_slippage_cost: Decimal

    exit_extended_fee: Decimal | None
    exit_lighter_fee: Decimal | None
    exit_extended_spread_cost: Decimal | None
    exit_lighter_spread_cost: Decimal | None
    exit_slippage_cost: Decimal | None

    # 收益
    gross_profit: Decimal | None
    net_profit: Decimal | None
    profit_rate: Decimal | None

    # 订单类型
    entry_extended_order_type: Literal['maker', 'taker']
    entry_lighter_order_type: Literal['maker', 'taker']
    exit_extended_order_type: Literal['maker', 'taker'] | None
    exit_lighter_order_type: Literal['maker', 'taker'] | None


class OrderRecord(NamedTuple):
    """订单记录（用于导出）"""
    order_id: str
    trade_id: str
    exchange: Literal['extended', 'lighter']
    timestamp: float
    side: Literal['buy', 'sell']

    # 订单类型
    intended_type: Literal['maker', 'taker']
    actual_type: Literal['maker', 'taker'] | None
    post_only: bool

    # 价格和数量
    limit_price: Decimal
    filled_price: Decimal | None
    quantity: Decimal

    # 执行
    status: Literal['PENDING', 'FILLED', 'PARTIAL', 'CANCELLED', 'REJECTED']
    time_to_fill: float | None

    # 手续费
    expected_fee_rate: Decimal
    actual_fee_rate: Decimal | None
    expected_fee_amount: Decimal
    actual_fee_amount: Decimal | None

    # 特殊事件
    is_rejected: bool
    reject_reason: str | None
    converted_to_taker: bool
    conversion_reason: str | None


class SpreadSnapshotRecord(NamedTuple):
    """价差快照记录（用于分析）"""
    timestamp: float
    spread_mid: Decimal
    spread_real_long: Decimal
    spread_real_short: Decimal
    extended_spread: Decimal
    lighter_spread: Decimal
    volatility: Decimal | None  # 如果计算了


class IDataCollector(ABC):
    """数据收集器接口"""

    @abstractmethod
    def log_trade_opening(
        self,
        trade_id: str,
        direction: str,
        extended_price: Decimal,
        lighter_price: Decimal,
        real_spread: Decimal,
        real_spread_rate: Decimal,
        extended_order_type: str,
        lighter_order_type: str,
        extended_fee: Decimal,
        lighter_fee: Decimal,
        spread_costs: dict,
        slippage_costs: dict
    ):
        """记录交易开仓"""
        pass

    @abstractmethod
    def log_trade_closing(
        self,
        trade_id: str,
        extended_price: Decimal,
        lighter_price: Decimal,
        real_spread: Decimal,
        real_spread_rate: Decimal,
        extended_order_type: str,
        lighter_order_type: str,
        extended_fee: Decimal,
        lighter_fee: Decimal,
        spread_costs: dict,
        slippage_costs: dict,
        holding_time: float,
        gross_profit: Decimal,
        net_profit: Decimal,
        profit_rate: Decimal
    ):
        """记录交易平仓"""
        pass

    @abstractmethod
    def log_order_execution(
        self,
        order_id: str,
        trade_id: str,
        exchange: str,
        side: str,
        intended_type: str,
        actual_type: str,
        limit_price: Decimal,
        filled_price: Decimal,
        quantity: Decimal,
        status: str,
        time_to_fill: float,
        expected_fee: Decimal,
        actual_fee: Decimal,
        is_rejected: bool,
        converted: bool
    ):
        """记录订单执行"""
        pass

    @abstractmethod
    def log_spread_snapshot(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ):
        """记录价差快照"""
        pass

    @abstractmethod
    def export_trades_csv(self, filepath: str):
        """导出交易记录到CSV"""
        pass

    @abstractmethod
    def export_orders_csv(self, filepath: str):
        """导出订单记录到CSV"""
        pass


class ITradeAnalyzer(ABC):
    """交易分析器接口"""

    @abstractmethod
    def calculate_win_rate(self, trades: list[TradeRecord]) -> float:
        """计算胜率"""
        pass

    @abstractmethod
    def calculate_average_profit(self, trades: list[TradeRecord]) -> Decimal:
        """计算平均收益"""
        pass

    @abstractmethod
    def calculate_max_drawdown(self, trades: list[TradeRecord]) -> Decimal:
        """计算最大回撤"""
        pass

    @abstractmethod
    def calculate_sharpe_ratio(
        self,
        trades: list[TradeRecord],
        risk_free_rate: Decimal
    ) -> float:
        """计算夏普比率"""
        pass

    @abstractmethod
    def analyze_pnl_by_time_period(
        self,
        trades: list[TradeRecord],
        period_hours: int
    ) -> dict:
        """按时段分析盈亏"""
        pass

    @abstractmethod
    def generate_daily_report(self, date: datetime) -> dict:
        """生成每日报告"""
        pass


class ISpreadStatistics(ABC):
    """价差统计接口"""

    @abstractmethod
    def record_spread(
        self,
        spread_real_long: Decimal,
        spread_real_short: Decimal,
        extended_spread: Decimal,
        lighter_spread: Decimal
    ):
        """记录价差数据"""
        pass

    @abstractmethod
    def get_percentiles(self) -> dict[str, Decimal]:
        """获取价差分位数 (P25, P50, P75, P90)"""
        pass

    @abstractmethod
    def get_volatility(self, periods: int) -> Decimal:
        """获取波动率"""
        pass

    @abstractmethod
    def recommend_min_spread_rate(
        self,
        safety_margin: Decimal
    ) -> Decimal:
        """
        推荐最小价差率

        算法: P75价差 + 平均成本 + 安全边际
        """
        pass
