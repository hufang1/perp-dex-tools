"""
真实价差计算器 - 使用对手价（bid/ask）计算真实价差

关键修复：
- 不使用中间价（mid price），因为中间价是"买不到也卖不出"的价格
- 使用对手价计算：做多价差 = lighter_bid - extended_ask
- 考虑点差成本和手续费成本
"""

import logging
from decimal import Decimal
from typing import Literal, NamedTuple

from .config import SpreadArbConfig


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
    expected_profit_rate: Decimal            # 期望收益率（扣除成本后）
    failure_reason: str | None = None        # 不通过的原因


class RealSpreadCalculator:
    """真实价差计算器 - 使用对手价计算"""

    def __init__(self, config: SpreadArbConfig):
        """
        初始化真实价差计算器

        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = logging.getLogger("RealSpreadCalculator")

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

        做多价差意味着：
        - 在Extended买入（支付ask价格）
        - 在Lighter卖出（获得bid价格）
        - 只有当lighter_bid > extended_ask时才盈利

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            RealSpreadResult: 真实价差计算结果
        """
        # 计算真实价差（对手价）
        spread = lighter_bid - extended_ask

        # 计算价差率
        if lighter_bid > 0:
            spread_rate = spread / lighter_bid
        else:
            self.logger.warning("Lighter bid <= 0，无法计算价差率")
            return RealSpreadResult(
                is_valid=False,
                direction='none',
                spread=Decimal('0'),
                spread_rate=Decimal('0'),
                extended_entry_price=Decimal('0'),
                lighter_entry_price=Decimal('0'),
                extended_exit_price=Decimal('0'),
                lighter_exit_price=Decimal('0'),
                costs=SpreadCosts(Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')),
                expected_profit_rate=Decimal('0'),
                failure_reason="Lighter bid <= 0"
            )

        # 计算点差成本
        extended_spread = extended_ask - extended_bid
        lighter_spread = lighter_ask - lighter_bid

        # 对于做多：
        # - Extended买入成本点差 = (ask - bid) / 2 = extended_spread / 2
        # - Lighter卖出成本点差 = (ask - bid) / 2 = lighter_spread / 2
        extended_cost = (extended_spread / 2) / lighter_bid if lighter_bid > 0 else Decimal('0')
        lighter_cost = (lighter_spread / 2) / lighter_bid if lighter_bid > 0 else Decimal('0')
        total_cost_rate = extended_cost + lighter_cost

        costs = SpreadCosts(
            extended_cost=extended_cost,
            lighter_cost=lighter_cost,
            total_cost=extended_cost + lighter_cost,
            total_cost_rate=total_cost_rate
        )

        # 计算期望收益（扣除手续费和点差）
        # 假设使用taker: 双边手续费 = extended_taker_fee_rate * 2
        taker_fees = self.config.extended_taker_fee_rate * 2
        expected_profit_rate = spread_rate - taker_fees - total_cost_rate

        is_valid = spread_rate > 0

        return RealSpreadResult(
            is_valid=is_valid,
            direction='long_spread',
            spread=spread,
            spread_rate=spread_rate,
            extended_entry_price=extended_ask,   # 做多：Extended用ask买入
            lighter_entry_price=lighter_bid,    # 做多：Lighter用bid卖出
            extended_exit_price=extended_bid,   # 平仓：Extended用bid卖出
            lighter_exit_price=lighter_ask,    # 平仓：Lighter用ask买入
            costs=costs,
            expected_profit_rate=expected_profit_rate
        )

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

        做空价差意味着：
        - 在Extended卖出（获得bid价格）
        - 在Lighter买入（支付ask价格）
        - 只有当extended_bid > lighter_ask时才盈利

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            RealSpreadResult: 真实价差计算结果
        """
        # 计算真实价差（对手价）
        spread = extended_bid - lighter_ask

        # 计算价差率
        if extended_bid > 0:
            spread_rate = spread / extended_bid
        else:
            self.logger.warning("Extended bid <= 0，无法计算价差率")
            return RealSpreadResult(
                is_valid=False,
                direction='none',
                spread=Decimal('0'),
                spread_rate=Decimal('0'),
                extended_entry_price=Decimal('0'),
                lighter_entry_price=Decimal('0'),
                extended_exit_price=Decimal('0'),
                lighter_exit_price=Decimal('0'),
                costs=SpreadCosts(Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')),
                expected_profit_rate=Decimal('0'),
                failure_reason="Extended bid <= 0"
            )

        # 计算点差成本
        extended_spread = extended_ask - extended_bid
        lighter_spread = lighter_ask - lighter_bid

        # 对于做空：
        # - Extended卖出获得点差收益，但买入时有成本
        # - Lighter买入支付点差成本
        extended_cost = (extended_spread / 2) / extended_bid if extended_bid > 0 else Decimal('0')
        lighter_cost = (lighter_spread / 2) / extended_bid if extended_bid > 0 else Decimal('0')
        total_cost_rate = extended_cost + lighter_cost

        costs = SpreadCosts(
            extended_cost=extended_cost,
            lighter_cost=lighter_cost,
            total_cost=extended_cost + lighter_cost,
            total_cost_rate=total_cost_rate
        )

        # 计算期望收益（扣除手续费和点差）
        taker_fees = self.config.extended_taker_fee_rate * 2
        expected_profit_rate = spread_rate - taker_fees - total_cost_rate

        is_valid = spread_rate > 0

        return RealSpreadResult(
            is_valid=is_valid,
            direction='short_spread',
            spread=spread,
            spread_rate=spread_rate,
            extended_entry_price=extended_bid,   # 做空：Extended用bid卖出
            lighter_entry_price=lighter_ask,    # 做空：Lighter用ask买入
            extended_exit_price=extended_ask,   # 平仓：Extended用ask买入
            lighter_exit_price=lighter_bid,    # 平仓：Lighter用bid卖出
            costs=costs,
            expected_profit_rate=expected_profit_rate
        )

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
        # 计算做多和做空价差
        long_result = self.calculate_long_spread(extended_bid, extended_ask, lighter_bid, lighter_ask)
        short_result = self.calculate_short_spread(extended_bid, extended_ask, lighter_bid, lighter_ask)

        # 选择价差率更大的方向
        if long_result.is_valid and short_result.is_valid:
            if long_result.spread_rate >= short_result.spread_rate:
                result = long_result
            else:
                result = short_result
        elif long_result.is_valid:
            result = long_result
        elif short_result.is_valid:
            result = short_result
        else:
            # 没有有效机会
            return RealSpreadResult(
                is_valid=False,
                direction='none',
                spread=Decimal('0'),
                spread_rate=Decimal('0'),
                extended_entry_price=Decimal('0'),
                lighter_entry_price=Decimal('0'),
                extended_exit_price=Decimal('0'),
                lighter_exit_price=Decimal('0'),
                costs=SpreadCosts(Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')),
                expected_profit_rate=Decimal('0'),
                failure_reason="价差率不足或为负"
            )

        # 检查是否满足阈值
        if result.is_valid and result.expected_profit_rate < min_spread_rate:
            result = RealSpreadResult(
                is_valid=False,
                direction=result.direction,
                spread=result.spread,
                spread_rate=result.spread_rate,
                extended_entry_price=result.extended_entry_price,
                lighter_entry_price=result.lighter_entry_price,
                extended_exit_price=result.extended_exit_price,
                lighter_exit_price=result.lighter_exit_price,
                costs=result.costs,
                expected_profit_rate=result.expected_profit_rate,
                failure_reason=f"期望收益率{result.expected_profit_rate:.4%}低于阈值{min_spread_rate:.4%}"
            )

        return result

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

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价
            direction: 套利方向

        Returns:
            SpreadCosts: 点差成本分解
        """
        extended_spread = extended_ask - extended_bid
        lighter_spread = lighter_ask - lighter_bid

        if direction == 'long_spread':
            base_price = lighter_bid
        else:  # short_spread
            base_price = extended_bid

        if base_price <= 0:
            return SpreadCosts(Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0'))

        extended_cost = (extended_spread / 2) / base_price
        lighter_cost = (lighter_spread / 2) / base_price

        return SpreadCosts(
            extended_cost=extended_cost,
            lighter_cost=lighter_cost,
            total_cost=extended_cost + lighter_cost,
            total_cost_rate=extended_cost + lighter_cost
        )
