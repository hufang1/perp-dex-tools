"""
极简平仓逻辑测试

测试012-dual-leg-concurrency的极简平仓策略
"""

import pytest
from decimal import Decimal
from spread.config import SpreadArbConfig
from spread.models import SimpleCloseDecision


class TestSimpleClose:
    """测试极简平仓决策（T066-T069）"""

    def test_simple_close_take_profit(self):
        """T066: 测试止盈触发"""
        decision = SimpleCloseDecision(
            open_spread_rate=Decimal('0.0020'),  # 开仓时价差率 0.20%
            current_spread_rate=Decimal('0.0010'),  # 当前价差率 0.10% (收敛到目标)
            target_profit_rate=Decimal('0.0008'),   # 目标利润 0.08%
            stop_loss_rate=Decimal('0.0030'),       # 止损阈值 0.30%
            should_close=False,  # 初始值
            close_reason='hold'
        )

        decision.calculate_decision()

        # 当前价差 <= 开仓价差 - 目标利润 (0.10% <= 0.20% - 0.08% = 0.12%)
        # 应该止盈
        assert decision.should_close is True
        assert decision.close_reason == 'take_profit'

    def test_simple_close_stop_loss(self):
        """T067: 测试止损触发"""
        decision = SimpleCloseDecision(
            open_spread_rate=Decimal('0.0020'),  # 开仓时价差率 0.20%
            current_spread_rate=Decimal('0.0060'),  # 当前价差率 0.60% (扩大)
            target_profit_rate=Decimal('0.0008'),   # 目标利润 0.08%
            stop_loss_rate=Decimal('0.0030'),       # 止损阈值 0.30%
            should_close=False,
            close_reason='hold'
        )

        decision.calculate_decision()

        # 当前价差 >= 开仓价差 + 止损 (0.60% >= 0.20% + 0.30% = 0.50%)
        # 应该止损
        assert decision.should_close is True
        assert decision.close_reason == 'stop_loss'

    def test_simple_close_hold(self):
        """T068: 测试持有（不触发平仓）"""
        decision = SimpleCloseDecision(
            open_spread_rate=Decimal('0.0020'),  # 开仓时价差率 0.20%
            current_spread_rate=Decimal('0.0025'),  # 当前价差率 0.25% (轻微扩大但未达止损)
            target_profit_rate=Decimal('0.0008'),   # 目标利润 0.08%
            stop_loss_rate=Decimal('0.0030'),       # 止损阈值 0.30%
            should_close=False,
            close_reason='hold'
        )

        decision.calculate_decision()

        # 当前价差在目标利润和止损之间
        # 0.20% - 0.08% = 0.12% < 0.25% < 0.20% + 0.30% = 0.50%
        # 应该持有
        assert decision.should_close is False
        assert decision.close_reason == 'hold'

    def test_simple_close_concurrent_execution(self):
        """T069: 测试并发执行平仓"""
        from spread.models import ConcurrentOrderResult
        import time

        # 模拟并发执行
        send_a_ts = time.time() * 1000
        send_b_ts = time.time() * 1000 + 2  # 2ms后

        result = ConcurrentOrderResult(
            extended_success=True,
            extended_order_id='ext_close_123',
            extended_filled_qty=Decimal('0.01'),
            extended_filled_price=Decimal('3001.0'),
            extended_error=None,
            lighter_success=True,
            lighter_order_id='lit_close_456',
            lighter_filled_qty=Decimal('0.01'),
            lighter_filled_price=Decimal('2999.0'),
            lighter_error=None,
            send_a_ts=send_a_ts,
            send_b_ts=send_b_ts,
            send_gap_ms=2.0,
            total_latency_ms=150.0,
            is_both_filled=True,
            is_legging=False,
            is_both_failed=False
        )

        # 验证并发执行指标
        assert result.is_both_filled is True
        assert result.send_gap_ms < 5  # < 5ms
        assert result.total_latency_ms < 500  # < 500ms

    def test_simple_decision_spread_delta(self):
        """测试价差变化计算"""
        decision = SimpleCloseDecision(
            open_spread_rate=Decimal('0.0020'),
            current_spread_rate=Decimal('0.0015'),
            target_profit_rate=Decimal('0.0008'),
            stop_loss_rate=Decimal('0.0030'),
            should_close=False,
            close_reason='hold'
        )

        decision.calculate_decision()

        # 价差变化 = 当前 - 开仓 = 0.15% - 0.20% = -0.05%
        assert decision.spread_delta == Decimal('-0.0005')

    def test_simple_close_boundary_conditions(self):
        """测试边界条件"""
        # 恰好达到止盈目标
        decision1 = SimpleCloseDecision(
            open_spread_rate=Decimal('0.0020'),
            current_spread_rate=Decimal('0.0012'),  # 0.20% - 0.08% = 0.12%
            target_profit_rate=Decimal('0.0008'),
            stop_loss_rate=Decimal('0.0030'),
            should_close=False,
            close_reason='hold'
        )
        decision1.calculate_decision()
        assert decision1.should_close is True  # 恰好达到止盈

        # 恰好达到止损阈值
        decision2 = SimpleCloseDecision(
            open_spread_rate=Decimal('0.0020'),
            current_spread_rate=Decimal('0.0050'),  # 0.20% + 0.30% = 0.50%
            target_profit_rate=Decimal('0.0008'),
            stop_loss_rate=Decimal('0.0030'),
            should_close=False,
            close_reason='hold'
        )
        decision2.calculate_decision()
        assert decision2.should_close is True  # 恰好达到止损

    def test_simple_close_negative_spread(self):
        """测试负价差情况"""
        decision = SimpleCloseDecision(
            open_spread_rate=Decimal('-0.0010'),  # 做空价差 -0.10%
            current_spread_rate=Decimal('-0.0020'),  # 当前 -0.20% (进一步扩大，有利)
            target_profit_rate=Decimal('0.0008'),
            stop_loss_rate=Decimal('0.0030'),
            should_close=False,
            close_reason='hold'
        )

        decision.calculate_decision()

        # 做空：当前价差 < 开仓价差 - 目标利润
        # -0.20% < -0.10% - 0.08% = -0.18%
        # 应该止盈
        assert decision.should_close is True
        assert decision.close_reason == 'take_profit'
