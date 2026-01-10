"""
价差计算修复测试 - 测试中间价计算和价差方向判断

本测试模块验证:
1. 使用中间价计算价差
2. 根据价差符号决定正确的套利方向
3. 价差收敛时盈亏计算一致性
"""

import pytest
from decimal import Decimal
from spread.calculator import SpreadCalculator, SpreadArbConfig


class TestMidPriceCalculation:
    """测试中间价计算"""

    def test_spread_calculation_using_mid_price(self):
        """测试: 使用中间价计算价差 spread = extended_mid - lighter_mid"""
        config = SpreadArbConfig()
        calculator = SpreadCalculator(config)

        # 测试数据: Extended贵于Lighter
        extended_bid = Decimal('3090')
        extended_ask = Decimal('3095')
        lighter_bid = Decimal('3060')
        lighter_ask = Decimal('3065')

        # 预期结果
        expected_extended_mid = (Decimal('3090') + Decimal('3095')) / 2  # 3092.5
        expected_lighter_mid = (Decimal('3060') + Decimal('3065')) / 2   # 3062.5
        expected_spread = expected_extended_mid - expected_lighter_mid    # 30

        opportunity = calculator.calculate_spread_opportunity_mid(
            extended_bid=extended_bid,
            extended_ask=extended_ask,
            lighter_bid=lighter_bid,
            lighter_ask=lighter_ask,
            min_spread_rate=Decimal('0.0001')
        )

        assert opportunity is not None
        assert opportunity['spread_mid'] == expected_spread

    def test_negative_spread_calculation(self):
        """测试: 负价差计算（Extended便宜于Lighter）"""
        config = SpreadArbConfig()
        calculator = SpreadCalculator(config)

        # 测试数据: Extended便宜于Lighter
        extended_bid = Decimal('3060')
        extended_ask = Decimal('3065')
        lighter_bid = Decimal('3090')
        lighter_ask = Decimal('3095')

        # 预期结果: spread = 3062.5 - 3092.5 = -30
        expected_extended_mid = (Decimal('3060') + Decimal('3065')) / 2  # 3062.5
        expected_lighter_mid = (Decimal('3090') + Decimal('3095')) / 2   # 3092.5
        expected_spread = expected_extended_mid - expected_lighter_mid    # -30

        opportunity = calculator.calculate_spread_opportunity_mid(
            extended_bid=extended_bid,
            extended_ask=extended_ask,
            lighter_bid=lighter_bid,
            lighter_ask=lighter_ask,
            min_spread_rate=Decimal('0.0001')
        )

        assert opportunity is not None
        assert opportunity['spread_mid'] == expected_spread
        assert opportunity['spread_mid'] < 0


class TestSpreadDirectionDetermination:
    """测试价差方向判断"""

    def test_positive_spread_returns_short_direction(self):
        """测试: spread > 0 返回short_spread（做空价差）"""
        config = SpreadArbConfig()
        calculator = SpreadCalculator(config)

        # Extended贵于Lighter → 应该做空价差
        extended_bid = Decimal('3090')
        extended_ask = Decimal('3095')
        lighter_bid = Decimal('3060')
        lighter_ask = Decimal('3065')

        opportunity = calculator.calculate_spread_opportunity_mid(
            extended_bid=extended_bid,
            extended_ask=extended_ask,
            lighter_bid=lighter_bid,
            lighter_ask=lighter_ask,
            min_spread_rate=Decimal('0.0001')
        )

        assert opportunity is not None
        assert opportunity['spread_mid'] > 0
        assert opportunity['direction'] == 'short_spread'
        assert opportunity['extended_side'] == 'sell'  # 卖出Extended

    def test_negative_spread_returns_long_direction(self):
        """测试: spread < 0 返回long_spread（做多价差）"""
        config = SpreadArbConfig()
        calculator = SpreadCalculator(config)

        # Extended便宜于Lighter → 应该做多价差
        extended_bid = Decimal('3060')
        extended_ask = Decimal('3065')
        lighter_bid = Decimal('3090')
        lighter_ask = Decimal('3095')

        opportunity = calculator.calculate_spread_opportunity_mid(
            extended_bid=extended_bid,
            extended_ask=extended_ask,
            lighter_bid=lighter_bid,
            lighter_ask=lighter_ask,
            min_spread_rate=Decimal('0.0001')
        )

        assert opportunity is not None
        assert opportunity['spread_mid'] < 0
        assert opportunity['direction'] == 'long_spread'
        assert opportunity['extended_side'] == 'buy'  # 买入Extended


class TestSpreadProfitLogic:
    """测试价差盈利逻辑"""

    def test_long_spread_profit_when_converges(self):
        """测试: 做多价差（开仓spread=-30），收敛到-10时应盈利"""
        from spread.spread_pair import SpreadPair

        # 开仓: 做多价差 (spread = -30)
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',  # 做多
            extended_price=Decimal('3060'),
            extended_quantity=Decimal('1'),
            lighter_price=Decimal('3090'),
            lighter_quantity=Decimal('1')
        )
        # 开仓价差 = -30 (lighter - extended = 3090 - 3060 = 30, 但这是反向...需要修正理解)

        # 收敛到-10: Extended涨到3070, Lighter涨到3080
        # 做多: 买入Extended @ 3060, 卖出Lighter @ 3090
        # 平仓: 卖出Extended @ 3070 (+10), 买入Lighter @ 3080 (-10)
        # 盈亏 = 10 - 10 + 30 = 30 (收敛赚了20)

        # 更准确的测试:
        # 做多价差: Extended买 @ 3060, Lighter卖 @ 3090 (spread = -30)
        # 收敛: Extended卖 @ 3075, Lighter买 @ 3085 (spread = -10)
        # Extended盈亏 = 3075 - 3060 = +15
        # Lighter盈亏 = 3090 - 3085 = +5
        # 总盈亏 = +20 (收敛获利)

        extended_close = Decimal('3075')
        lighter_close = Decimal('3085')

        unrealized_pnl = pair.calculate_unrealized_pnl(extended_close, lighter_close)

        # 做多价差收敛时应盈利
        assert unrealized_pnl > 0, f"Expected profit but got {unrealized_pnl}"

    def test_short_spread_profit_when_converges(self):
        """测试: 做空价差（开仓spread=+30），收敛到+10时应盈利"""
        from spread.spread_pair import SpreadPair

        # 开仓: 做空价差 (spread = +30)
        pair = SpreadPair(
            pair_id=1,
            extended_side='sell',  # 做空
            extended_price=Decimal('3090'),
            extended_quantity=Decimal('1'),
            lighter_price=Decimal('3060'),
            lighter_quantity=Decimal('1')
        )

        # 收敛到+10
        # 做空: Extended卖 @ 3090, Lighter买 @ 3060 (spread = +30)
        # 平仓: Extended买 @ 3075, Lighter卖 @ 3065 (spread = +10)
        # Extended盈亏 = 3090 - 3075 = +15
        # Lighter盈亏 = 3065 - 3060 = +5
        # 总盈亏 = +20 (收敛获利)

        extended_close = Decimal('3075')
        lighter_close = Decimal('3065')

        unrealized_pnl = pair.calculate_unrealized_pnl(extended_close, lighter_close)

        # 做空价差收敛时应盈利
        assert unrealized_pnl > 0, f"Expected profit but got {unrealized_pnl}"

    def test_spread_divergence_causes_loss(self):
        """测试: 价差扩大时应亏损"""
        from spread.spread_pair import SpreadPair

        # 开仓: 做多价差 (spread = -30)
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3060'),
            extended_quantity=Decimal('1'),
            lighter_price=Decimal('3090'),
            lighter_quantity=Decimal('1')
        )

        # 扩大到-50
        extended_close = Decimal('3040')
        lighter_close = Decimal('3090')

        unrealized_pnl = pair.calculate_unrealized_pnl(extended_close, lighter_close)

        # 价差扩大时应亏损
        assert unrealized_pnl < 0, f"Expected loss but got {unrealized_pnl}"
