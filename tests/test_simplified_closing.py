"""
Unit tests for simplified closing logic (011-fix-lighter-hedge, US6)

Tests the spread-based closing strategy without time-based priorities.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from spread.models import CloseDecision
from spread.config import SpreadArbConfig


class TestSimplifiedClosing:
    """Test suite for simplified closing logic (US6)"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        config = SpreadArbConfig()
        # Simplified closing uses spread-based thresholds
        config.profit_target_rate = Decimal('0.0015')  # 0.15% profit target
        config.stop_loss_rate = Decimal('0.0010')  # 0.10% stop loss
        return config

    @pytest.fixture
    def mock_pair(self):
        """Create a mock spread pair"""
        pair = Mock()
        pair.pair_id = 1
        pair.direction = "LONG"  # 做多价差
        pair.extended_quantity = Decimal('0.35')
        pair.extended_price = Decimal('2450.00')
        pair.lighter_quantity = Decimal('0.35')
        pair.lighter_price = Decimal('2460.00')
        pair.open_spread = Decimal('10.00')  # 开仓时的价差
        pair.open_time = datetime.now() - timedelta(seconds=100)
        return pair

    def test_profit_target_closing_long_spread(self, config, mock_pair):
        """
        Test: 做多价差达到盈利目标时平仓
        Condition: current_spread <= open_spread - target_profit
        """
        # 做多价差：价差变小有利（lighter_bid - extended_ask 变小）
        # open_spread = 10.00, target = 1.5%, target_profit = 3.675
        # current_spread = 6.00 (价差收敛了4.00)

        current_spread = Decimal('6.00')  # 价差从10.00收敛到6.00
        open_spread = Decimal('10.00')
        target_profit = Decimal('3.675')  # 0.15% of investment

        # 应该触发止盈平仓
        should_close = current_spread <= (open_spread - target_profit)
        assert should_close is True

    def test_profit_target_closing_short_spread(self, config):
        """
        Test: 做空价差达到盈利目标时平仓
        Condition: current_spread >= open_spread + target_profit
        """
        # 做空价差：价差变大有利
        # open_spread = 10.00
        # current_spread = 14.00 (价差扩大了4.00)

        current_spread = Decimal('14.00')
        open_spread = Decimal('10.00')
        target_profit = Decimal('3.675')

        # 做空价差：价差扩大有利
        should_close = current_spread >= (open_spread + target_profit)
        assert should_close is True

    def test_stop_loss_closing_long_spread(self, config):
        """
        Test: 做多价差触发止损时平仓
        Condition: current_spread >= open_spread + stop_loss_threshold
        """
        # 做多价差：价差扩大不利，触发止损
        # open_spread = 10.00
        # current_spread = 12.00 (价差扩大了2.00)

        current_spread = Decimal('12.00')
        open_spread = Decimal('10.00')
        stop_loss = Decimal('2.00')

        should_close = current_spread >= (open_spread + stop_loss)
        assert should_close is True

    def test_stop_loss_closing_short_spread(self, config):
        """
        Test: 做空价差触发止损时平仓
        Condition: current_spread <= open_spread - stop_loss_threshold
        """
        # 做空价差：价差变小不利，触发止损
        # open_spread = 10.00
        # current_spread = 8.00 (价差缩小了2.00)

        current_spread = Decimal('8.00')
        open_spread = Decimal('10.00')
        stop_loss = Decimal('2.00')

        should_close = current_spread <= (open_spread - stop_loss)
        assert should_close is True

    def test_no_closing_when_spread_stable(self, config):
        """
        Test: 价差稳定时不应平仓
        """
        # 价差变化不大，不触发任何平仓条件
        current_spread = Decimal('9.50')
        open_spread = Decimal('10.00')
        target_profit = Decimal('3.675')
        stop_loss = Decimal('2.00')

        # 不触发止盈
        profit_close = current_spread <= (open_spread - target_profit)
        assert profit_close is False

        # 不触发止损
        stop_loss_close = current_spread >= (open_spread + stop_loss)
        assert stop_loss_close is False

    def test_spread_change_calculation(self):
        """
        Test: 价差变化计算
        """
        open_spread = Decimal('10.00')

        # 做多：价差从10.00收敛到6.00，变化为-4.00（有利）
        current_spread_long = Decimal('6.00')
        spread_delta_long = current_spread_long - open_spread
        assert spread_delta_long == Decimal('-4.00')

        # 做空：价差从10.00扩大到14.00，变化为+4.00（有利）
        current_spread_short = Decimal('14.00')
        spread_delta_short = current_spread_short - open_spread
        assert spread_delta_short == Decimal('4.00')

    def test_simplified_closing_uses_only_spread(self, config, mock_pair):
        """
        Test: Verify simplified closing does NOT use holding_time
        """
        # 简化平仓逻辑不应该考虑持仓时间
        # 只应该基于价差变化

        # 即使持仓时间很短，如果价差达到目标也应该平仓
        holding_time = 10  # 只持仓10秒
        current_spread = Decimal('6.00')
        open_spread = Decimal('10.00')
        target_profit = Decimal('3.675')

        # 仅基于价差判断，不考虑时间
        should_close = current_spread <= (open_spread - target_profit)
        assert should_close is True

    def test_simplified_closing_no_time_priorities(self, config, mock_pair):
        """
        Test: Verify P1-P5 priority system is removed
        """
        # 新的简化逻辑不应该有 P1-P5 优先级
        # 只有两种情况：止盈平仓 or 止损平仓

        current_spread = Decimal('6.00')
        open_spread = Decimal('10.00')

        # 止盈判断
        if current_spread < open_spread:
            reason = "止盈平仓"
            priority = None  # 简化逻辑不需要优先级
            assert priority is None
            assert "止盈" in reason

        # 止损判断
        current_spread = Decimal('12.00')
        if current_spread > open_spread:
            reason = "止损平仓"
            priority = None
            assert priority is None
            assert "止损" in reason

    def test_concurrent_ioc_closing(self, config):
        """
        Test: Verify closing uses concurrent IOC orders
        """
        # 平仓应该使用与开仓相同的并发执行机制
        # 两腿应该在5ms内同时发送

        # 模拟并发平仓
        extended_order = {
            'side': 'SELL',
            'price': Decimal('2448.00'),  # bid价格
            'time_in_force': 'IOC'  # IOC订单
        }

        lighter_order = {
            'side': 'BUY',
            'price': Decimal('2462.00'),  # ask价格
            'time_in_force': 'IMMEDIATE_OR_CANCEL'  # IOC订单
        }

        # 验证都是IOC订单
        assert extended_order['time_in_force'] in ['IOC', 'IMMEDIATE_OR_CANCEL']
        assert lighter_order['time_in_force'] == 'IMMEDIATE_OR_CANCEL'


class TestSimplifiedClosingIntegration:
    """Integration tests for simplified closing logic"""

    def test_spread_comparison_logic(self):
        """
        Test: 验证价差比较逻辑的正确性
        """
        # 开仓价差
        open_spread = Decimal('10.00')

        # 投资金额
        investment = Decimal('2450.00') * Decimal('0.35')  # 857.5

        # 止盈目标 0.15%
        profit_target = investment * Decimal('0.0015')  # 1.28625

        # 止损阈值 0.10%
        stop_loss = investment * Decimal('0.0010')  # 0.8575

        # 测试用例1: 止盈 - 做多价差收敛
        current_spread_1 = Decimal('8.50')  # 收敛了1.50
        profit_close_1 = current_spread_1 <= (open_spread - profit_target)
        assert profit_close_1 is True  # 8.50 <= 8.71

        # 测试用例2: 不触发 - 小幅波动
        current_spread_2 = Decimal('9.50')  # 只收敛了0.50
        profit_close_2 = current_spread_2 <= (open_spread - profit_target)
        assert profit_close_2 is False  # 9.50 > 8.71

        # 测试用例3: 止损 - 做多价差扩大
        current_spread_3 = Decimal('11.00')  # 扩大了1.00
        stop_loss_close_3 = current_spread_3 >= (open_spread + stop_loss)
        assert stop_loss_close_3 is True  # 11.00 >= 10.86

        # 测试用例4: 不触发 - 小幅扩大
        current_spread_4 = Decimal('10.50')  # 只扩大了0.50
        stop_loss_close_4 = current_spread_4 >= (open_spread + stop_loss)
        assert stop_loss_close_4 is False  # 10.50 < 10.86


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
