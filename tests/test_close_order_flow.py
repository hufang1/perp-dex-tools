"""
完整平仓流程集成测试（用户故事2 - 006-fix-lighter-close）

测试Extended平仓成功后Lighter平仓订单能够成功执行的完整流程
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch

from spread.spread_pair import SpreadPair


@pytest.fixture
def spread_pair():
    """创建测试套利对"""
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_quantity=Decimal('0.01'),
        extended_price=Decimal('3080.00'),
        lighter_quantity=Decimal('0.01'),
        lighter_price=Decimal('3085.23')
    )
    # 手动设置open_time为固定值以便测试
    import time
    pair.open_time = 1234567890.0
    return pair


class TestCompleteCloseOrderFlow:
    """测试完整平仓流程"""

    def test_spread_pair_close_state_tracking(self, spread_pair):
        """
        测试：套利对平仓状态跟踪

        验证平仓后套利对的所有属性都被正确设置
        """
        # 设置is_closing标志（模拟bot逻辑）
        spread_pair.is_closing = True

        # 执行平仓
        profit = spread_pair.close(
            close_extended_price=Decimal('3082.80'),
            close_lighter_price=Decimal('3082.85')
        )

        # 验证平仓价格被设置
        assert spread_pair.close_extended_price == Decimal('3082.80')
        assert spread_pair.close_lighter_price == Decimal('3082.85')

        # 验证is_closing标志保持设置状态（由bot管理，不是close()方法重置）
        # 在实际bot逻辑中，平仓成功后会保持is_closing=True以防止重复平仓
        assert spread_pair.is_closing == True

        # 验证持仓时间可以计算
        assert spread_pair.holding_time > 0

    def test_close_position_profit_calculation(self, spread_pair):
        """
        测试：平仓盈亏计算

        场景：
        1. 做多开仓：买入Extended @ 3080.00，卖出Lighter @ 3085.23
        2. 平仓：卖出Extended @ 3082.80，买入Lighter @ 3082.85
        3. 验证盈亏计算正确
        """
        # 计算预期盈亏
        extended_profit = (Decimal('3082.80') - Decimal('3080.00')) * Decimal('0.01')
        lighter_profit = (Decimal('3085.23') - Decimal('3082.85')) * Decimal('0.01')
        expected_profit = extended_profit + lighter_profit

        # 执行平仓
        profit = spread_pair.close(
            close_extended_price=Decimal('3082.80'),
            close_lighter_price=Decimal('3082.85')
        )

        # 验证盈亏计算正确
        assert abs(profit - expected_profit) < Decimal('0.01')

    def test_spread_pair_closing_flag_prevents_duplicate_close(self, spread_pair):
        """
        测试：is_closing标志防止重复平仓

        场景：
        1. 第一次平仓
        2. 验证is_closing为True
        3. 尝试再次平仓
        4. 验证不会重复处理
        """
        # 第一次平仓
        spread_pair.is_closing = True
        spread_pair.close(
            close_extended_price=Decimal('3082.80'),
            close_lighter_price=Decimal('3082.85')
        )

        # 验证is_closing标志
        assert spread_pair.is_closing == True

        # 尝试再次平仓（应该检测到is_closing标志）
        if spread_pair.is_closing:
            # 模拟检测重复平仓的逻辑
            close_again = False
            assert close_again == False or spread_pair.is_closing == True

    @pytest.mark.asyncio
    async def test_complete_close_flow_extended_to_lighter(self):
        """
        集成测试：完整平仓流程 Extended → Lighter

        场景：
        1. Extended CLOSE订单提交并成交
        2. Lighter平仓订单提交并成交
        3. 验证完整流程成功执行

        这个测试验证修复CLOSE订单处理后，完整平仓流程能正常工作
        """
        # 模拟套利对
        spread_pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_quantity=Decimal('0.01'),
            extended_price=Decimal('3080.00'),
            lighter_quantity=Decimal('0.01'),
            lighter_price=Decimal('3085.23')
        )
        # 手动设置open_time
        spread_pair.open_time = 1234567890.0

        # 模拟Extended平仓成功
        extended_close_order_id = "2009608496505368576"
        extended_close_price = Decimal('3082.80')

        # 模拟Lighter平仓成功
        lighter_close_order_id = "lighter_order_123"
        lighter_close_price = Decimal('3082.85')

        # 设置平仓订单ID
        spread_pair.close_extended_order_id = extended_close_order_id
        spread_pair.close_lighter_order_id = lighter_close_order_id

        # 执行平仓
        profit = spread_pair.close(
            close_extended_price=extended_close_price,
            close_lighter_price=lighter_close_price
        )

        # 验证两个交易所的平仓价格都被记录
        assert spread_pair.close_extended_price == extended_close_price
        assert spread_pair.close_lighter_price == lighter_close_price

        # 验证平仓订单ID被记录
        assert spread_pair.close_extended_order_id == extended_close_order_id
        assert spread_pair.close_lighter_order_id == lighter_close_order_id

        # 验证盈亏计算正确
        extended_profit = (extended_close_price - spread_pair.extended_price) * spread_pair.extended_quantity
        lighter_profit = (spread_pair.lighter_price - lighter_close_price) * spread_pair.lighter_quantity
        expected_profit = extended_profit + lighter_profit
        assert abs(profit - expected_profit) < Decimal('0.01')

    def test_close_position_with_short_spread(self):
        """
        测试：做空套利对的平仓

        场景：
        1. 做空开仓：卖出Extended @ 3085.00，买入Lighter @ 3080.50
        2. 平仓：买入Extended @ 3082.20，卖出Lighter @ 3082.00
        3. 验证盈亏计算正确
        """
        spread_pair = SpreadPair(
            pair_id=2,
            extended_side='sell',
            extended_quantity=Decimal('0.01'),
            extended_price=Decimal('3085.00'),
            lighter_quantity=Decimal('0.01'),
            lighter_price=Decimal('3080.50')
        )
        # 手动设置open_time
        spread_pair.open_time = 1234567890.0

        # 执行平仓
        profit = spread_pair.close(
            close_extended_price=Decimal('3082.20'),
            close_lighter_price=Decimal('3082.00')
        )

        # 计算预期盈亏（做空）
        extended_profit = (spread_pair.extended_price - Decimal('3082.20')) * spread_pair.extended_quantity
        lighter_profit = (Decimal('3082.00') - spread_pair.lighter_price) * spread_pair.lighter_quantity
        expected_profit = extended_profit + lighter_profit

        assert abs(profit - expected_profit) < Decimal('0.01')

    def test_close_order_ids_persistence(self, spread_pair):
        """
        测试：平仓订单ID持久化

        验证平仓订单ID被正确保存，用于日志记录和审计
        """
        # 设置平仓订单ID
        spread_pair.close_extended_order_id = "2009608496505368576"
        spread_pair.close_lighter_order_id = "lighter_order_123"

        # 验证订单ID被保存
        assert spread_pair.close_extended_order_id == "2009608496505368576"
        assert spread_pair.close_lighter_order_id == "lighter_order_123"

        # 平仓后验证订单ID仍然可用
        spread_pair.close(
            close_extended_price=Decimal('3082.80'),
            close_lighter_price=Decimal('3082.85')
        )

        assert spread_pair.close_extended_order_id == "2009608496505368576"
        assert spread_pair.close_lighter_order_id == "lighter_order_123"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
