"""
成本计算器 - 计算交易成本分解

包括：
- 点差成本
- 滑点成本
- 手续费成本
"""

import logging
from decimal import Decimal
from typing import Literal
from dataclasses import dataclass


@dataclass
class TradeCostBreakdown:
    """交易成本分解"""

    # 开仓成本
    entry_extended_fee: Decimal      # Extended开仓手续费
    entry_lighter_fee: Decimal       # Lighter开仓手续费
    entry_extended_spread_cost: Decimal  # Extended点差成本
    entry_lighter_spread_cost: Decimal   # Lighter点差成本
    entry_slippage_cost: Decimal     # 开仓滑点成本
    total_entry_cost: Decimal        # 总开仓成本

    # 平仓成本
    exit_extended_fee: Decimal       # Extended平仓手续费
    exit_lighter_fee: Decimal        # Lighter平仓手续费
    exit_extended_spread_cost: Decimal   # Extended点差成本
    exit_lighter_spread_cost: Decimal    # Lighter点差成本
    exit_slippage_cost: Decimal      # 平仓滑点成本
    total_exit_cost: Decimal         # 总平仓成本

    # 总成本
    total_fees: Decimal              # 总手续费
    total_spread_cost: Decimal       # 总点差成本
    total_slippage_cost: Decimal     # 总滑点成本
    total_cost: Decimal              # 总成本

    # 收益
    gross_profit: Decimal            # 毛收益（价差收益）
    net_profit: Decimal              # 净收益（扣除总成本）
    profit_rate: Decimal             # 收益率

    def to_dict(self) -> dict:
        """转换为字典（用于日志/导出）"""
        return {
            'entry': {
                'extended_fee': str(self.entry_extended_fee),
                'lighter_fee': str(self.entry_lighter_fee),
                'extended_spread': str(self.entry_extended_spread_cost),
                'lighter_spread': str(self.entry_lighter_spread_cost),
                'slippage': str(self.entry_slippage_cost),
                'total': str(self.total_entry_cost)
            },
            'exit': {
                'extended_fee': str(self.exit_extended_fee),
                'lighter_fee': str(self.exit_lighter_fee),
                'extended_spread': str(self.exit_extended_spread_cost),
                'lighter_spread': str(self.exit_lighter_spread_cost),
                'slippage': str(self.exit_slippage_cost),
                'total': str(self.total_exit_cost)
            },
            'total': {
                'fees': str(self.total_fees),
                'spread_cost': str(self.total_spread_cost),
                'slippage': str(self.total_slippage_cost),
                'total': str(self.total_cost)
            },
            'profit': {
                'gross': str(self.gross_profit),
                'net': str(self.net_profit),
                'rate': str(self.profit_rate)
            }
        }


class CostCalculator:
    """成本计算器"""

    def __init__(self):
        """初始化成本计算器"""
        self.logger = logging.getLogger("CostCalculator")

    def calculate_spread_cost(
        self,
        bid: Decimal,
        ask: Decimal,
        quantity: Decimal,
        base_price: Decimal
    ) -> Decimal:
        """
        计算点差成本

        对于买入: 成本 = (ask - bid) / 2 * quantity
        对于卖出: 成本 = (ask - bid) / 2 * quantity

        Args:
            bid: 买一价
            ask: 卖一价
            quantity: 数量
            base_price: 基准价格（用于计算比率）

        Returns:
            Decimal: 点差成本
        """
        spread = ask - bid
        cost = (spread / 2) * quantity

        if base_price > 0:
            cost_rate = cost / base_price
        else:
            cost_rate = Decimal('0')

        self.logger.debug(f"点差成本: spread={spread}, cost={cost}, rate={cost_rate:.6f}")
        return cost

    def calculate_slippage_cost(
        self,
        limit_price: Decimal,
        filled_price: Decimal,
        quantity: Decimal,
        side: Literal['buy', 'sell']
    ) -> Decimal:
        """
        计算滑点成本

        对于买入: 滑点 = (filled - limit) * quantity (如果 filled > limit)
        对于卖出: 滑点 = (limit - filled) * quantity (如果 filled < limit)

        Args:
            limit_price: 限价价格
            filled_price: 成交价格
            quantity: 数量
            side: 买卖方向

        Returns:
            Decimal: 滑点成本（总是正数或零）
        """
        if side == 'buy':
            # 买入：成交价高于限价是不利的
            slippage = max(Decimal('0'), (filled_price - limit_price) * quantity)
        else:  # sell
            # 卖出：成交价低于限价是不利的
            slippage = max(Decimal('0'), (limit_price - filled_price) * quantity)

        self.logger.debug(f"滑点成本: side={side}, limit={limit_price}, filled={filled_price}, slippage={slippage}")
        return slippage

    def calculate_total_cost(
        self,
        entry_fees: Decimal,
        exit_fees: Decimal,
        entry_spread_cost: Decimal,
        exit_spread_cost: Decimal,
        entry_slippage: Decimal,
        exit_slippage: Decimal
    ) -> Decimal:
        """
        计算总成本

        Args:
            entry_fees: 开仓手续费
            exit_fees: 平仓手续费
            entry_spread_cost: 开仓点差成本
            exit_spread_cost: 平仓点差成本
            entry_slippage: 开仓滑点
            exit_slippage: 平仓滑点

        Returns:
            Decimal: 总成本
        """
        total_fees = entry_fees + exit_fees
        total_spread_cost = entry_spread_cost + exit_spread_cost
        total_slippage_cost = entry_slippage + exit_slippage
        total = total_fees + total_spread_cost + total_slippage_cost

        self.logger.debug(
            f"总成本分解: fees={total_fees}, spread={total_spread_cost}, "
            f"slippage={total_slippage_cost}, total={total}"
        )

        return total

    def determine_fee_rate(
        self,
        order_type: Literal['maker', 'taker'],
        exchange: Literal['extended', 'lighter'],
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal
    ) -> Decimal:
        """
        确定费率

        Args:
            order_type: 订单类型（maker/taker）
            exchange: 交易所
            maker_fee_rate: Maker费率
            taker_fee_rate: Taker费率

        Returns:
            Decimal: 费率
        """
        if order_type == 'maker':
            fee_rate = maker_fee_rate
        else:  # taker
            fee_rate = taker_fee_rate

        self.logger.debug(f"费率确定: {exchange} {order_type} = {fee_rate:.6f}")
        return fee_rate

    def calculate_trade_costs(
        self,
        entry_extended_order_type: Literal['maker', 'taker'],
        entry_lighter_order_type: Literal['maker', 'taker'],
        exit_extended_order_type: Literal['maker', 'taker'],
        exit_lighter_order_type: Literal['maker', 'taker'],
        entry_extended_price: Decimal,
        entry_lighter_price: Decimal,
        exit_extended_price: Decimal,
        exit_lighter_price: Decimal,
        quantity: Decimal,
        extended_maker_fee: Decimal,
        extended_taker_fee: Decimal,
        lighter_fee: Decimal
    ) -> TradeCostBreakdown:
        """
        计算完整交易成本

        Args:
            entry_extended_order_type: Extended开仓订单类型
            entry_lighter_order_type: Lighter开仓订单类型
            exit_extended_order_type: Extended平仓订单类型
            exit_lighter_order_type: Lighter平仓订单类型
            entry_extended_price: Extended开仓价格
            entry_lighter_price: Lighter开仓价格
            exit_extended_price: Extended平仓价格
            exit_lighter_price: Lighter平仓价格
            quantity: 数量
            extended_maker_fee: Extended maker费率
            extended_taker_fee: Extended taker费率
            lighter_fee: Lighter费率

        Returns:
            TradeCostBreakdown: 完整成本分解
        """
        # 开仓手续费
        entry_extended_fee_rate = self.determine_fee_rate(
            entry_extended_order_type, 'extended', extended_maker_fee, extended_taker_fee
        )
        entry_lighter_fee_rate = self.determine_fee_rate(
            entry_lighter_order_type, 'lighter', extended_maker_fee, extended_taker_fee
        )

        entry_extended_fee = entry_extended_price * quantity * entry_extended_fee_rate
        entry_lighter_fee = entry_lighter_price * quantity * entry_lighter_fee_rate

        # 平仓手续费
        exit_extended_fee_rate = self.determine_fee_rate(
            exit_extended_order_type, 'extended', extended_maker_fee, extended_taker_fee
        )
        exit_lighter_fee_rate = self.determine_fee_rate(
            exit_lighter_order_type, 'lighter', extended_maker_fee, extended_taker_fee
        )

        exit_extended_fee = exit_extended_price * quantity * exit_extended_fee_rate
        exit_lighter_fee = exit_lighter_price * quantity * exit_lighter_fee_rate

        # 点差成本（简化计算，使用平均价格）
        # 开仓点差成本
        entry_extended_spread = self.calculate_spread_cost(
            Decimal('0'), Decimal('0'), quantity, entry_lighter_price  # 简化
        )
        entry_lighter_spread = self.calculate_spread_cost(
            Decimal('0'), Decimal('0'), quantity, entry_extended_price  # 简化
        )

        # 平仓点差成本
        exit_extended_spread = self.calculate_spread_cost(
            Decimal('0'), Decimal('0'), quantity, exit_lighter_price
        )
        exit_lighter_spread = self.calculate_spread_cost(
            Decimal('0'), Decimal('0'), quantity, exit_extended_price
        )

        # 滑点成本（假设为0，需要实际成交数据才能计算）
        entry_slippage = Decimal('0')
        exit_slippage = Decimal('0')

        # 汇总
        total_entry_cost = entry_extended_fee + entry_lighter_fee + entry_extended_spread + entry_lighter_spread + entry_slippage
        total_exit_cost = exit_extended_fee + exit_lighter_fee + exit_extended_spread + exit_lighter_spread + exit_slippage

        total_fees = entry_extended_fee + entry_lighter_fee + exit_extended_fee + exit_lighter_fee
        total_spread_cost = entry_extended_spread + entry_lighter_spread + exit_extended_spread + exit_lighter_spread
        total_slippage_cost = entry_slippage + exit_slippage
        total_cost = total_entry_cost + total_exit_cost

        # 计算收益（价差收益）
        gross_profit = (exit_lighter_price - entry_extended_price) * quantity  # 简化
        net_profit = gross_profit - total_cost

        if entry_extended_price * quantity > 0:
            profit_rate = net_profit / (entry_extended_price * quantity)
        else:
            profit_rate = Decimal('0')

        return TradeCostBreakdown(
            entry_extended_fee=entry_extended_fee,
            entry_lighter_fee=entry_lighter_fee,
            entry_extended_spread_cost=entry_extended_spread,
            entry_lighter_spread_cost=entry_lighter_spread,
            entry_slippage_cost=entry_slippage,
            total_entry_cost=total_entry_cost,
            exit_extended_fee=exit_extended_fee,
            exit_lighter_fee=exit_lighter_fee,
            exit_extended_spread_cost=exit_extended_spread,
            exit_lighter_spread_cost=exit_lighter_spread,
            exit_slippage_cost=exit_slippage,
            total_exit_cost=total_exit_cost,
            total_fees=total_fees,
            total_spread_cost=total_spread_cost,
            total_slippage_cost=total_slippage_cost,
            total_cost=total_cost,
            gross_profit=gross_profit,
            net_profit=net_profit,
            profit_rate=profit_rate
        )
