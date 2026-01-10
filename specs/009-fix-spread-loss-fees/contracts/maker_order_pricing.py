"""
Contract: Maker Order Pricing Strategy

This contract defines the interface for calculating maker order prices
that avoid post-only rejection.

Purpose: Ensure maker orders are priced correctly to achieve 0% fees.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal, NamedTuple


class MakerPriceResult(NamedTuple):
    """Maker订单价格计算结果"""
    limit_price: Decimal       # 限价价格
    side: Literal['buy', 'sell']  # 买卖方向
    post_only: bool            # 是否使用post_only
    expected_fill_probability: float  # 预期成交概率 (0-1)
    reason: str                # 定价原因说明


class IMakerPricingStrategy(ABC):
    """Maker定价策略接口"""

    @abstractmethod
    def calculate_maker_price(
        self,
        side: Literal['buy', 'sell'],
        bid: Decimal,
        ask: Decimal,
        price_tick: Decimal
    ) -> MakerPriceResult:
        """
        计算maker订单价格

        算法:
            对于买入:
                price = bid - price_tick (挂在买一价下方)

            对于卖出:
                price = ask + price_tick (挂在卖一价上方)

        Args:
            side: 买卖方向
            bid: 买一价
            ask: 卖一价
            price_tick: 价格精度单位

        Returns:
            MakerPriceResult: Maker订单价格结果
        """
        pass

    @abstractmethod
    def should_use_maker(
        self,
        spread_rate: Decimal,
        expected_profit_with_taker: Decimal,
        expected_profit_with_maker: Decimal
    ) -> bool:
        """
        判断是否应该使用maker订单

        决策逻辑:
            1. 如果maker期望收益 > 0，优先使用maker
            2. 如果只有taker期望收益 > 0，使用taker
            3. 如果都 < 0，拒绝开仓

        Args:
            spread_rate: 价差率
            expected_profit_with_taker: 使用taker的期望收益
            expected_profit_with_maker: 使用maker的期望收益

        Returns:
            bool: 是否使用maker订单
        """
        pass

    @abstractmethod
    def handle_maker_timeout(
        self,
        original_opportunity: dict,
        current_spread_rate: Decimal,
        timeout_seconds: int
    ) -> Literal['convert_to_taker', 'cancel', 'wait_longer']:
        """
        处理maker订单超时

        决策逻辑:
            1. 检查当前价差率
            2. 如果使用taker仍有利润 → convert_to_taker
            3. 如果价差率不足 → cancel
            4. 如果接近阈值 → wait_longer

        Args:
            original_opportunity: 原始开仓机会数据
            current_spread_rate: 当前价差率
            timeout_seconds: 已等待时间

        Returns:
            处理动作
        """
        pass


class MakerOrderMetrics(ABC):
    """Maker订单指标跟踪接口"""

    @abstractmethod
    def record_attempt(self, order_id: str, price: Decimal, bid: Decimal, ask: Decimal):
        """记录maker订单尝试"""
        pass

    @abstractmethod
    def record_rejection(self, order_id: str, reason: str):
        """记录maker订单被拒绝"""
        pass

    @abstractmethod
    def record_fill(self, order_id: str, filled_price: Decimal, time_to_fill: float):
        """记录maker订单成交"""
        pass

    @abstractmethod
    def get_success_rate(self) -> float:
        """获取maker订单成功率"""
        pass

    @abstractmethod
    def get_rejection_rate(self) -> float:
        """获取maker订单拒绝率"""
        pass

    @abstractmethod
    def should_adjust_price_tick(self) -> tuple[bool, Decimal | None]:
        """
        判断是否需要调整price_tick

        调整逻辑:
            - 拒绝率 > 30%: 增加price_tick
            - 拒绝率 < 10%: 减少price_tick
            - 目标: 拒绝率 10-20%

        Returns:
            tuple[bool, Decimal | None]: (是否调整, 新的price_tick)
        """
        pass
