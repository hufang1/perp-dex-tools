"""
Bot Integration Contract

bot.py模块的修改接口定义，用于集成成功率追踪和强制taker订单功能
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
from enum import Enum


class OrderType(Enum):
    """订单类型"""
    TAKER = "taker"       # 市价单，立即成交
    MAKER = "maker"       # 限价单，挂单等待


class PositionConsistencyCheck:
    """
    仓位一致性检查结果

    Attributes:
        is_consistent: 仓位是否一致
        extended_quantity: Extended仓位数量
        lighter_quantity: Lighter仓位数量
        difference: 差异数量
        difference_rate: 差异率（百分比）
        threshold_exceeded: 是否超过阈值
    """
    def __init__(
        self,
        is_consistent: bool,
        extended_quantity: Decimal,
        lighter_quantity: Decimal,
        difference: Decimal,
        difference_rate: float,
        threshold_exceeded: bool
    ):
        self.is_consistent = is_consistent
        self.extended_quantity = extended_quantity
        self.lighter_quantity = lighter_quantity
        self.difference = difference
        self.difference_rate = difference_rate
        self.threshold_exceeded = threshold_exceeded


class IOrderPlacementStrategy(ABC):
    """
    订单下单策略接口

    定义开仓时的订单类型选择策略
    """

    @abstractmethod
    def determine_order_type(self, opportunity: Dict[str, Any]) -> OrderType:
        """
        决定使用哪种订单类型开仓

        本功能强制使用TAKER订单，忽略maker订单逻辑

        Args:
            opportunity: 开仓机会信息

        Returns:
            必须返回 OrderType.TAKER
        """
        pass

    @abstractmethod
    def calculate_order_price(
        self,
        side: str,
        bid: Decimal,
        ask: Decimal,
        order_type: OrderType
    ) -> Decimal:
        """
        计算订单价格

        对于taker订单，使用对手价：
        - 买单：使用ask价格
        - 卖单：使用bid价格

        Args:
            side: 'buy' or 'sell'
            bid: 买一价
            ask: 卖一价
            order_type: 订单类型

        Returns:
            订单价格
        """
        pass


class IPositionConsistencyValidator(ABC):
    """
    仓位一致性验证器接口

    定义开仓后的仓位验证逻辑
    """

    @abstractmethod
    def validate_position_consistency(
        self,
        extended_quantity: Decimal,
        lighter_quantity: Decimal,
        threshold: Decimal = Decimal('0.001'),
        rate_threshold: float = 0.1
    ) -> PositionConsistencyCheck:
        """
        验证两个交易所的仓位数量是否一致

        Args:
            extended_quantity: Extended仓位数量
            lighter_quantity: Lighter仓位数量
            threshold: 差异数量阈值（默认0.001 ETH）
            rate_threshold: 差异率阈值（默认10%）

        Returns:
            PositionConsistencyCheck 对象
        """
        pass

    @abstractmethod
    def log_inconsistency_warning(self, check: PositionConsistencyCheck) -> None:
        """
        记录仓位不一致警告

        Args:
            check: 一致性检查结果
        """
        pass


class ISuccessTrackingBot(ABC):
    """
    集成成功率追踪的Bot接口

    定义bot.py需要实现的成功率追踪集成点
    """

    @abstractmethod
    def on_open_opportunity_detected(self, opportunity: Dict[str, Any]) -> None:
        """
        当检测到开仓机会时调用

        Args:
            opportunity: 机会信息
        """
        pass

    @abstractmethod
    def on_open_attempt(
        self,
        side: str,
        quantity: Decimal,
        price: Decimal
    ) -> None:
        """
        当尝试开仓时调用

        Args:
            side: 'buy' or 'sell'
            quantity: 数量
            price: 价格
        """
        pass

    @abstractmethod
    def on_open_success(
        self,
        order_id: str,
        extended_quantity: Decimal,
        lighter_quantity: Decimal,
        price: Decimal
    ) -> None:
        """
        当开仓成功时调用

        Args:
            order_id: Extended订单ID
            extended_quantity: Extended成交数量
            lighter_quantity: Lighter成交数量
            price: 成交价格
        """
        pass

    @abstractmethod
    def on_open_failed(
        self,
        reason: str,
        error_message: Optional[str] = None
    ) -> None:
        """
        当开仓失败时调用

        Args:
            reason: 失败原因（FailureReason枚举值）
            error_message: 详细错误信息
        """
        pass

    @abstractmethod
    def on_position_limit_reached(self, max_pairs: int) -> None:
        """
        当达到仓位上限时调用

        Args:
            max_pairs: 最大持仓数量
        """
        pass

    @abstractmethod
    def on_close_attempt(self, pair_id: int) -> None:
        """
        当尝试平仓时调用

        Args:
            pair_id: 套利对ID
        """
        pass

    @abstractmethod
    def on_close_success(
        self,
        pair_id: int,
        extended_price: Decimal,
        lighter_price: Decimal,
        pnl: Decimal
    ) -> None:
        """
        当平仓成功时调用

        Args:
            pair_id: 套利对ID
            extended_price: Extended平仓价格
            lighter_price: Lighter平仓价格
            pnl: 实现盈亏
        """
        pass

    @abstractmethod
    def on_close_failed(
        self,
        pair_id: int,
        reason: str,
        error_message: Optional[str] = None
    ) -> None:
        """
        当平仓失败时调用

        Args:
            pair_id: 套利对ID
            reason: 失败原因
            error_message: 详细错误信息
        """
        pass


# Integration Points for bot.py modifications

class BotIntegrationPoints:
    """
    bot.py需要修改的集成点清单

    位置1: _open_new_pair() 方法开头
    - 调用 on_open_opportunity_detected()
    - 检查仓位上限，调用 on_position_limit_reached()

    位置2: _open_new_pair() Extended下单前
    - 移除 use_maker = self.calculator.should_use_maker() 调用
    - 强制 use_maker = False
    - 移除 maker_price 计算
    - 调用 on_open_attempt()

    位置3: _open_new_pair() Extended下单成功后
    - 调用 validate_position_consistency()
    - 如果不一致，调用 log_inconsistency_warning()

    位置4: _open_new_pair() Lighter对冲成功后
    - 调用 on_open_success()

    位置5: _open_new_pair() 任何失败时
    - 调用 on_open_failed()

    位置6: _close_pair_with_market_price() 方法
    - 调用 on_close_attempt()
    - 成功后调用 on_close_success()
    - 失败后调用 on_close_failed()

    位置7: __init__() 方法
    - 初始化 SuccessTracker 实例
    - 初始化 IPositionConsistencyValidator 实例

    位置8: _cleanup() 方法
    - 导出成功率统计数据到CSV
    """
    pass
