"""
Contract: RealSpreadCalculator Interface

This contract defines the interface for calculating real spread opportunities
using counter-party prices (bid/ask) instead of mid prices.

Purpose: Ensure consistent and correct spread calculation across the system.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal, NamedTuple


class SpreadCosts(NamedTuple):
    """点差成本分解"""
    extended_cost: Decimal    # Extended点差成本
    lighter_cost: Decimal     # Lighter点差成本
    total_cost: Decimal       # 总点差成本
    total_cost_rate: Decimal  # 总成本率


class RealSpreadResult(NamedTuple):
    """真实价差计算结果"""
    is_valid: bool                           # 是否有效
    direction: Literal['long_spread', 'short_spread', 'none']  # 套利方向
    spread: Decimal                          # 真实价差
    spread_rate: Decimal                     # 真实价差率
    extended_entry_price: Decimal            # Extended开仓价
    lighter_entry_price: Decimal             # Lighter开仓价
    extended_exit_price: Decimal             # Extended平仓价（用于计算）
    lighter_exit_price: Decimal              # Lighter平仓价（用于计算）
    costs: SpreadCosts                       # 成本分解


class IRealSpreadCalculator(ABC):
    """真实价差计算器接口"""

    @abstractmethod
    def calculate_long_spread(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> RealSpreadResult:
        """
        计算做多价差（Extended买，Lighter卖）

        算法:
            spread = lighter_bid - extended_ask
            spread_rate = spread / lighter_bid

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            RealSpreadResult: 真实价差计算结果
        """
        pass

    @abstractmethod
    def calculate_short_spread(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> RealSpreadResult:
        """
        计算做空价差（Extended卖，Lighter买）

        算法:
            spread = extended_bid - lighter_ask
            spread_rate = spread / extended_bid

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            RealSpreadResult: 真实价差计算结果
        """
        pass

    @abstractmethod
    def calculate_best_opportunity(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal,
        min_spread_rate: Decimal
    ) -> RealSpreadResult:
        """
        计算最佳套利机会（自动选择做多或做空）

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价
            min_spread_rate: 最小价差率阈值

        Returns:
            RealSpreadResult: 最佳套利机会（如果满足阈值）
        """
        pass

    @abstractmethod
    def calculate_spread_costs(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal,
        direction: Literal['long_spread', 'short_spread']
    ) -> SpreadCosts:
        """
        计算点差成本

        算法:
            对于做多:
                extended_cost = (extended_ask - extended_bid) / 2 / lighter_bid
                lighter_cost = (lighter_ask - lighter_bid) / 2 / lighter_bid

            对于做空:
                extended_cost = (extended_ask - extended_bid) / 2 / extended_bid
                lighter_cost = (lighter_ask - lighter_bid) / 2 / extended_bid

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价
            direction: 套利方向

        Returns:
            SpreadCosts: 点差成本分解
        """
        pass


class ExpectedProfitCalculation(ABC):
    """期望收益计算接口"""

    @abstractmethod
    def calculate_expected_profit(
        self,
        spread_rate: Decimal,
        use_maker: bool,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        spread_costs: SpreadCosts
    ) -> Decimal:
        """
        计算期望收益率

        算法:
            fees = (maker_fee_rate if use_maker else taker_fee_rate) * 2  # 开平仓
            total_costs = fees + spread_costs.total_cost_rate
            expected_profit = spread_rate - total_costs

        Args:
            spread_rate: 价差率
            use_maker: 是否使用maker订单
            maker_fee_rate: Maker手续费率
            taker_fee_rate: Taker手续费率
            spread_costs: 点差成本

        Returns:
            Decimal: 期望收益率（可为负）
        """
        pass

    @abstractmethod
    def should_open_position(
        self,
        spread_rate: Decimal,
        expected_profit: Decimal,
        min_profit_rate: Decimal
    ) -> tuple[bool, str]:
        """
        判断是否应该开仓

        Args:
            spread_rate: 价差率
            expected_profit: 期望收益
            min_profit_rate: 最小收益率阈值

        Returns:
            tuple[bool, str]: (是否开仓, 原因)
        """
        pass
