"""
测试平仓价格选择逻辑 (Phase 4: User Story 2)

测试目标:
1. T017: 测试多头仓位平仓价格选择（Extended用bid, Lighter用ask）
2. T018: 测试空头仓位平仓价格选择（Extended用ask, Lighter用bid）
3. T019: 集成测试：测试完整开仓-平仓流程使用市价平仓
"""

import pytest
from decimal import Decimal

from spread.spread_pair import SpreadPair


class TestClosingPriceSelection:
    """测试平仓价格选择逻辑"""

    def test_long_position_closing_prices(self):
        """
        T017: 测试多头仓位平仓价格选择

        做多仓位：
        - Extended买入开仓，平仓时卖出，使用bid价格
        - Lighter卖出开仓，平仓时买入，使用ask价格

        场景：
        - 开仓：Extended买入@3000, Lighter卖出@3020（价差20，Extended价格更低）
        - 当前价格：bid=3005, ask=3010
        - 预期：Extended平仓用bid(3005), Lighter平仓用ask(3015)
        """
        # 创建做多仓位（Extended买入@3000, Lighter卖出@3020）
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),  # Lighter价格更高，价差为正
            lighter_quantity=Decimal('0.1')
        )

        # 验证开仓价差（3020 - 3000 = 20）
        assert pair.open_spread == Decimal('20')

        # 当前订单簿价格
        extended_bid = Decimal('3005')
        extended_ask = Decimal('3010')
        lighter_bid = Decimal('3010')
        lighter_ask = Decimal('3015')

        # 计算已实现收益（使用对手价）
        realized_pnl = pair.calculate_realized_pnl(
            extended_close_price=extended_bid,  # 做多平仓：卖出Extended用bid
            lighter_close_price=lighter_ask     # 做多平仓：买入Lighter用ask
        )

        # 验证计算结果
        # Extended盈亏 = (3005 - 3000) * 0.1 = 0.5
        # Lighter盈亏 = (3020 - 3015) * 0.1 = 0.5
        # 总盈亏 = 0.5 + 0.5 = 1.0
        assert realized_pnl == Decimal('1.0')

    def test_short_position_closing_prices(self):
        """
        T018: 测试空头仓位平仓价格选择

        做空仓位：
        - Extended卖出开仓，平仓时买入，使用ask价格
        - Lighter买入开仓，平仓时卖出，使用bid价格

        场景：
        - 开仓：Extended卖出@3000, Lighter买入@3020
        - 当前价格：bid=2995, ask=3000
        - 预期：Extended平仓用ask(3000), Lighter平仓用bid(2995)
        """
        # 创建做空仓位
        pair = SpreadPair(
            pair_id=1,
            extended_side='sell',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),
            lighter_quantity=Decimal('0.1')
        )

        # 当前订单簿价格
        extended_bid = Decimal('2995')
        extended_ask = Decimal('3000')
        lighter_bid = Decimal('2990')
        lighter_ask = Decimal('2995')

        # 计算已实现收益（使用对手价）
        realized_pnl = pair.calculate_realized_pnl(
            extended_close_price=extended_ask,  # 做空平仓：买入Extended用ask
            lighter_close_price=lighter_bid     # 做空平仓：卖出Lighter用bid
        )

        # 验证计算结果
        # Extended盈亏 = (3000 - 3000) * 0.1 = 0
        # Lighter盈亏 = (2990 - 3020) * 0.1 = -3
        # 总盈亏 = 0 - 3 = -3
        assert realized_pnl == Decimal('-3')

    def test_closing_prices_with_none(self):
        """测试价格为None时的处理"""
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('2980'),
            lighter_quantity=Decimal('0.1')
        )

        # 价格为None时应返回None
        result = pair.calculate_realized_pnl(
            extended_close_price=None,
            lighter_close_price=Decimal('3010')
        )
        assert result is None

        result = pair.calculate_realized_pnl(
            extended_close_price=Decimal('3005'),
            lighter_close_price=None
        )
        assert result is None

    def test_closing_prices_with_invalid_values(self):
        """测试无效价格的处理"""
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('2980'),
            lighter_quantity=Decimal('0.1')
        )

        # 价格<=0时应返回None
        result = pair.calculate_realized_pnl(
            extended_close_price=Decimal('0'),
            lighter_close_price=Decimal('3010')
        )
        assert result is None

        result = pair.calculate_realized_pnl(
            extended_close_price=Decimal('3005'),
            lighter_close_price=Decimal('-10')
        )
        assert result is None


class TestClosingPriceIntegration:
    """集成测试：完整开仓-平仓流程"""

    def test_open_close_workflow_with_market_prices(self):
        """
        T019: 集成测试：测试完整开仓-平仓流程使用市价平仓

        场景：
        1. 开仓：做多价差（Extended买@3000, Lighter卖@3020）
        2. 持仓期间价差收敛
        3. 平仓：使用对手价模拟市价单
        """
        # 1. 开仓做多（Extended买入@3000, Lighter卖出@3020）
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),  # Lighter价格更高
            lighter_quantity=Decimal('0.1')
        )

        # 验证开仓价差（3020 - 3000 = 20）
        assert pair.open_spread == Decimal('20')

        # 2. 持仓期间（当前价格）
        extended_bid = Decimal('3005')
        extended_ask = Decimal('3010')
        lighter_bid = Decimal('3010')
        lighter_ask = Decimal('3015')

        # 计算未实现盈亏
        unrealized_pnl = pair.calculate_unrealized_pnl(
            current_extended_price=extended_bid,  # 做多：当前可以用bid卖出
            current_lighter_price=lighter_ask     # 做多：当前需要用ask买入
        )

        # 验证未实现盈亏
        # Extended: (3005 - 3000) * 0.1 = 0.5
        # Lighter: (3020 - 3015) * 0.1 = 0.5
        # 总计: 1.0
        assert unrealized_pnl == Decimal('1.0')

        # 3. 平仓（使用对手价）
        close_extended_price = extended_bid
        close_lighter_price = lighter_ask

        profit = pair.close(
            close_extended_price=close_extended_price,
            close_lighter_price=close_lighter_price
        )

        # 验证平仓结果
        assert pair.is_closed
        assert pair.close_extended_price == extended_bid
        assert pair.close_lighter_price == lighter_ask
        assert profit == unrealized_pnl

    def test_short_position_open_close_workflow(self):
        """测试做空仓位的完整流程"""
        # 1. 开仓做空
        pair = SpreadPair(
            pair_id=1,
            extended_side='sell',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),
            lighter_quantity=Decimal('0.1')
        )

        # 2. 当前价格
        extended_bid = Decimal('2995')
        extended_ask = Decimal('3000')
        lighter_bid = Decimal('2990')
        lighter_ask = Decimal('2995')

        # 3. 计算平仓价格（做空：Extended用ask, Lighter用bid）
        close_extended_price = extended_ask
        close_lighter_price = lighter_bid

        profit = pair.close(
            close_extended_price=close_extended_price,
            close_lighter_price=close_lighter_price
        )

        # 验证结果
        # Extended: (3000 - 3000) * 0.1 = 0
        # Lighter: (2990 - 3020) * 0.1 = -3
        assert profit == Decimal('-3')
