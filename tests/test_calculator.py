"""
价差计算器单元测试
"""

import pytest
from decimal import Decimal
from spread.calculator import SpreadCalculator
from spread.config import SpreadArbConfig


class TestSpreadCalculator:
    """价差计算器测试"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = SpreadArbConfig(
            min_spread_rate=Decimal('0.0005'),
            latency_buffer=Decimal('0.0001'),
            order_quantity_usdt=Decimal('35')
        )
        self.calculator = SpreadCalculator(self.config)

    def test_long_opportunity_rejects_when_extended_bid_greater_than_lighter_ask(self):
        """
        T019: 验证做多机会在 Extended买一 > Lighter卖一时被拒绝

        场景: Extended买一价高于Lighter卖一价，不应该有套利机会
        - Extended买一: $3000
        - Lighter卖一: $2999
        - 期望: 不应该有做多机会（无法低买高卖）
        """
        # Extended买一 > Lighter卖一，不应该有做多机会
        result = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3001'),
            lighter_bid=Decimal('2998'),
            lighter_ask=Decimal('2999'),
            extended_mid_price=Decimal('3000.5')
        )

        # 应该返回None或做空机会，但不应该是做多机会
        if result is not None:
            assert result['side'] != 'buy', \
                f"当Extended买一({Decimal('3000')}) > Lighter卖一({Decimal('2999')})时不应该有做多机会"

    def test_long_opportunity_uses_lighter_ask_price(self):
        """
        T020: 验证做多机会使用 Lighter卖一价格

        场景: 正确的做多机会应该使用Lighter卖一价作为卖出价格
        - Extended买一: $3000 (买入价格)
        - Lighter卖一: $3010 (卖出价格)
        - 价差: $10
        - 期望: lighter_price应该是Lighter卖一价($3010)
        """
        # 设置正确的机会条件: Extended买一 < Lighter卖一
        result = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3001'),
            lighter_bid=Decimal('3005'),
            lighter_ask=Decimal('3010'),
            extended_mid_price=Decimal('3000.5')
        )

        # 应该有做多机会
        assert result is not None, "应该存在做多机会"
        assert result['side'] == 'buy', "应该是做多方向"

        # 核心验证: lighter_price应该是Lighter卖一价（$3010），不是买一价（$3005）
        assert result['lighter_price'] == Decimal('3010'), \
            f"做多时lighter_price应该使用Lighter卖一价($3010)，实际: ${result['lighter_price']}"

        # 验证价差计算
        expected_spread = Decimal('3010') - Decimal('3000')  # $10
        assert result['spread'] == expected_spread, \
            f"价差应该是${expected_spread}，实际: ${result['spread']}"

    def test_short_opportunity_uses_lighter_bid_price(self):
        """
        T021: 验证做空机会使用 Lighter买一价格

        场景: 正确的做空机会应该使用Lighter买一价作为买入价格
        - Extended卖一: $3010 (卖出价格)
        - Lighter买一: $3000 (买入价格)
        - 价差: $10
        - 期望: lighter_price应该是Lighter买一价($3000)
        """
        # 设置正确的机会条件: Extended卖一 > Lighter买一
        # 注意: 为了触发做空逻辑，需要 extended_ask > lighter_ask
        result = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('2999'),
            extended_ask=Decimal('3010'),
            lighter_bid=Decimal('3000'),
            lighter_ask=Decimal('3005'),
            extended_mid_price=Decimal('3004.5')
        )

        # 应该有做空机会
        assert result is not None, "应该存在做空机会"
        assert result['side'] == 'sell', "应该是做空方向"

        # 核心验证: lighter_price应该是Lighter买一价（$3000），不是卖一价（$3005）
        assert result['lighter_price'] == Decimal('3000'), \
            f"做空时lighter_price应该使用Lighter买一价($3000)，实际: ${result['lighter_price']}"

        # 验证价差计算
        expected_spread = Decimal('3010') - Decimal('3000')  # $10
        assert result['spread'] == expected_spread, \
            f"价差应该是${expected_spread}，实际: ${result['spread']}"

    def test_short_opportunity_spread_rate_uses_extended_ask_denominator(self):
        """
        T022: 验证做空机会的价差率使用 Extended卖一价作为分母

        场景: 做空价差率应该基于Extended卖一价计算
        - Extended卖一: $3010
        - Lighter买一: $3000
        - 价差: $10
        - 期望: spread_rate = 10 / 3010 ≈ 0.003322...
        """
        result = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('2999'),
            extended_ask=Decimal('3010'),
            lighter_bid=Decimal('3000'),
            lighter_ask=Decimal('3005'),
            extended_mid_price=Decimal('3004.5')
        )

        assert result is not None, "应该存在做空机会"
        assert result['side'] == 'sell', "应该是做空方向"

        # 核心验证: 价差率分母应该是Extended卖一价（$3010）
        expected_spread_rate = Decimal('10') / Decimal('3010')
        assert abs(result['spread_rate'] - expected_spread_rate) < Decimal('0.0001'), \
            f"价差率应该基于extended_ask计算，期望约{expected_spread_rate:.6f}，实际: {result['spread_rate']:.6f}"

    def test_no_opportunity_when_prices_dont_meet_criteria(self):
        """
        T023: 验证价格不满足条件时不产生套利机会

        场景1: 做多条件不满足 (Extended买一 >= Lighter卖一)
        场景2: 做空条件不满足 (Extended卖一 <= Lighter买一)
        场景3: 价差率低于阈值
        """
        # 场景1: 做多条件不满足
        result1 = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3001'),
            lighter_bid=Decimal('2999'),
            lighter_ask=Decimal('2999'),
            extended_mid_price=Decimal('3000')
        )
        # 不应该有做多机会
        if result1 is not None:
            assert result1['side'] != 'buy', "Extended买一 >= Lighter卖一时不应该有做多机会"

        # 场景2: 做空条件不满足
        result2 = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3000'),
            lighter_bid=Decimal('3000'),
            lighter_ask=Decimal('2999'),
            extended_mid_price=Decimal('3000')
        )
        # 不应该有做空机会
        if result2 is not None:
            assert result2['side'] != 'sell', "Extended卖一 <= Lighter卖一时不应该有做空机会"

        # 场景3: 价差率低于阈值 (0.04% < 0.05%)
        result3 = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3001'),
            lighter_bid=Decimal('3001'),
            lighter_ask=Decimal('3001.2'),
            extended_mid_price=Decimal('3000.5')
        )
        # 价差太小，不应该有套利机会
        assert result3 is None, "价差率低于阈值时不应该有套利机会"


class TestSpreadCalculatorEdgeCases:
    """价差计算器边界情况测试"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = SpreadArbConfig(
            min_spread_rate=Decimal('0.0005'),
            latency_buffer=Decimal('0.0001'),
            order_quantity_usdt=Decimal('35')
        )
        self.calculator = SpreadCalculator(self.config)

    def test_both_opportunities_exist_returns_best_one(self):
        """当做多和做空机会都存在时，返回利润率更高的那个"""
        result = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3020'),
            lighter_bid=Decimal('3010'),
            lighter_ask=Decimal('3015'),
            extended_mid_price=Decimal('3010')
        )

        assert result is not None, "应该有套利机会"
        # 做空价差: 3020 - 3010 = $10 (0.33%)
        # 做多价差: 3015 - 3000 = $15 (0.50%)
        # 应该返回做多机会（更高利润率）
        assert result['side'] == 'buy', "应该返回利润率更高的做多机会"

    def test_equal_prices_no_opportunity(self):
        """价格相等时不应该有套利机会"""
        result = self.calculator.calculate_spread_opportunity(
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3000'),
            lighter_bid=Decimal('3000'),
            lighter_ask=Decimal('3000'),
            extended_mid_price=Decimal('3000')
        )

        assert result is None, "价格相等时不应该有套利机会"

    def test_min_spread_rate_boundary(self):
        """测试最小价差率边界条件"""
        # 构造一个刚好等于阈值的机会
        # min_spread_rate = 0.05%, latency_buffer = 0.01%
        # 需要 spread_rate = 0.06%
        extended_price = Decimal('3000')
        required_spread = extended_price * Decimal('0.0006')  # $1.8

        result = self.calculator.calculate_spread_opportunity(
            extended_bid=extended_price,
            extended_ask=Decimal('3001'),
            lighter_bid=Decimal('3001'),
            lighter_ask=Decimal(extended_price + required_spread),
            extended_mid_price=Decimal('3000.5')
        )

        # 应该有套利机会（刚好满足阈值）
        assert result is not None, "满足最小价差率时应该有套利机会"
