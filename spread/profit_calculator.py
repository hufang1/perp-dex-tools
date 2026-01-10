"""
收益计算器 - 计算平仓后的净收益（含手续费）
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .position_aggregator import UnifiedPosition
from .cost_calculator import TradeCostBreakdown


@dataclass
class ProfitBreakdown:
    """收益明细 - 平仓后的收益计算结果"""

    # 价差收益
    spread_profit: Decimal  # 价差收益（不含手续费）

    # 手续费
    opening_fees: Decimal  # 已支付的开仓手续费
    estimated_closing_fees: Decimal  # 预计的平仓手续费

    # 净收益
    net_profit: Decimal  # 扣除所有手续费后的净收益

    # 明细
    extended_pnl: Decimal  # Extended盈亏
    lighter_pnl: Decimal  # Lighter盈亏

    # T097-T098: 成本分解和盈亏归因
    cost_breakdown: Optional[TradeCostBreakdown] = None  # 成本分解详情

    def calculate_net_profit(self) -> Decimal:
        """计算净收益 = spread_profit - opening_fees - estimated_closing_fees"""
        return self.spread_profit - self.opening_fees - self.estimated_closing_fees

    def get_profit_attribution(self) -> dict:
        """
        T098: 盈亏归因分析

        Returns:
            Dict: 盈亏归因分析
        """
        attribution = {
            'spread_profit': float(self.spread_profit),
            'total_fees': float(self.opening_fees + self.estimated_closing_fees),
            'net_profit': float(self.net_profit),
            'fee_impact': float(self.opening_fees + self.estimated_closing_fees) / float(self.spread_profit) if self.spread_profit != 0 else 0,
        }

        # 如果有成本分解，添加更详细的归因
        if self.cost_breakdown:
            attribution.update({
                'entry_fees': float(self.cost_breakdown.entry_extended_fee + self.cost_breakdown.entry_lighter_fee),
                'exit_fees': float(self.cost_breakdown.exit_extended_fee + self.cost_breakdown.exit_lighter_fee),
                'spread_cost': float(self.cost_breakdown.total_spread_cost),
                'slippage_cost': float(self.cost_breakdown.total_slippage_cost),
            })

        return attribution


class ProfitCalculator:
    """收益计算器 - 计算平仓后的净收益"""

    def __init__(self, extended_fee_rate: Decimal, lighter_fee_rate: Decimal):
        """
        初始化收益计算器

        Args:
            extended_fee_rate: Extended手续费率
            lighter_fee_rate: Lighter手续费率
        """
        self.extended_fee_rate = extended_fee_rate
        self.lighter_fee_rate = lighter_fee_rate

    def calculate_profit(
        self,
        position: UnifiedPosition,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> Optional[ProfitBreakdown]:
        """
        计算平仓后的收益（含手续费）

        Args:
            position: 统一持仓
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            ProfitBreakdown对象，如果价格数据无效则返回None
        """
        # 验证价格数据
        if extended_bid <= 0 or extended_ask <= 0 or lighter_bid <= 0 or lighter_ask <= 0:
            return None

        if position.total_quantity <= 0:
            return None

        try:
            # 确定平仓价格（根据方向使用对手价）
            if position.direction == 'long':
                # 做多平仓：卖出Extended（用bid），买入Lighter（用ask）
                extended_close_price = extended_bid
                lighter_close_price = lighter_ask
            else:
                # 做空平仓：买入Extended（用ask），卖出Lighter（用bid）
                extended_close_price = extended_ask
                lighter_close_price = lighter_bid

            # 计算价差收益
            extended_pnl = self._calculate_extended_pnl(position, extended_close_price)
            lighter_pnl = self._calculate_lighter_pnl(position, lighter_close_price)
            spread_profit = extended_pnl + lighter_pnl

            # 计算平仓手续费
            estimated_closing_fees = self._calculate_closing_fees(
                position, extended_close_price, lighter_close_price
            )

            # 计算净收益
            net_profit = spread_profit - position.total_opening_fees - estimated_closing_fees

            return ProfitBreakdown(
                spread_profit=spread_profit,
                opening_fees=position.total_opening_fees,
                estimated_closing_fees=estimated_closing_fees,
                net_profit=net_profit,
                extended_pnl=extended_pnl,
                lighter_pnl=lighter_pnl
            )

        except Exception:
            # 计算异常时返回None
            return None

    def _calculate_extended_pnl(self, position: UnifiedPosition, close_price: Decimal) -> Decimal:
        """
        计算Extended盈亏

        Args:
            position: 统一持仓
            close_price: 平仓价格

        Returns:
            Extended盈亏
        """
        if position.direction == 'long':
            # 做多：买入开仓，卖出平仓
            return (close_price - position.extended_avg_price) * position.total_quantity
        else:
            # 做空：卖出开仓，买入平仓
            return (position.extended_avg_price - close_price) * position.total_quantity

    def _calculate_lighter_pnl(self, position: UnifiedPosition, close_price: Decimal) -> Decimal:
        """
        计算Lighter盈亏

        Args:
            position: 统一持仓
            close_price: 平仓价格

        Returns:
            Lighter盈亏
        """
        if position.direction == 'long':
            # 做多时Lighter为做空：卖出开仓，买入平仓
            return (position.lighter_avg_price - close_price) * position.total_quantity
        else:
            # 做空时Lighter为做多：买入开仓，卖出平仓
            return (close_price - position.lighter_avg_price) * position.total_quantity

    def _calculate_closing_fees(
        self,
        position: UnifiedPosition,
        extended_close_price: Decimal,
        lighter_close_price: Decimal
    ) -> Decimal:
        """
        计算预计的平仓手续费

        Args:
            position: 统一持仓
            extended_close_price: Extended平仓价格
            lighter_close_price: Lighter平仓价格

        Returns:
            预计的平仓手续费
        """
        # Extended平仓手续费
        extended_fee = position.total_quantity * extended_close_price * self.extended_fee_rate

        # Lighter平仓手续费
        lighter_fee = position.total_quantity * lighter_close_price * self.lighter_fee_rate

        return extended_fee + lighter_fee
