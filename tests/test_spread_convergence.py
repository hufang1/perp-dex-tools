"""
测试价差收敛检查逻辑 (Phase 5: User Story 3)

测试目标:
1. T024: 测试做多价差收敛判断（spread_delta > 0时返回True）
2. T025: 测试做空价差收敛判断（spread_delta < 0时返回True）
3. T026: 测试价差扩大情况（返回False且正确标记status）
4. T027: 集成测试：测试5级优先级平仓触发条件
"""

import pytest
from decimal import Decimal

from spread.spread_pair import SpreadPair
from spread.models import SpreadChange, CloseDecision


class TestSpreadConvergence:
    """测试价差收敛判断逻辑"""

    def test_long_spread_convergence_positive_delta(self):
        """
        T024: 测试做多价差收敛判断（spread_delta > 0时返回True）

        做多价差：
        - 开仓：Extended买@3000, Lighter卖@3020（spread=20）
        - 当前：Extended=3010, Lighter=3030（spread=20）
        - 中间价：Extended=(3010+3020)/2=3015, Lighter=(3020+3040)/2=3030
        - 当前spread = 3015 - 3030 = -15
        - spread_delta = -15 - 20 = -35 < 0 → 未收敛（需要调整价格）
        """
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),
            lighter_quantity=Decimal('0.1')
        )

        # 当前价格（中间价spread应该变大）
        # Extended中间价=3005, Lighter中间价=3020, spread=-15
        # 需要让spread变大（例如-15 → -5）
        extended_bid = Decimal('3000')
        extended_ask = Decimal('3010')
        lighter_bid = Decimal('2995')
        lighter_ask = Decimal('3005')

        # 检查收敛
        is_converged, status, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # Extended中间价=(3000+3010)/2=3005
        # Lighter中间价=(2995+3005)/2=3000
        # 当前spread=3005-3000=5
        # 开仓spread=3020-3000=20
        # spread_delta=5-20=-15 < 0 → 未收敛

        # 调整为确实收敛的情况
        # Extended中间价=3005, Lighter中间价=2970, spread=35
        extended_bid = Decimal('3000')
        extended_ask = Decimal('3010')
        lighter_bid = Decimal('2965')
        lighter_ask = Decimal('2975')

        is_converged, status, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # Extended中间价=(3000+3010)/2=3005
        # Lighter中间价=(2965+2975)/2=2970
        # 当前spread=3005-2970=35
        # 开仓spread=20
        # spread_delta=35-20=15 > 0 → 收敛

        # 验证结果
        assert is_converged is True
        assert "价差收敛" in status
        assert spread_change.spread_delta == Decimal('15')
        assert spread_change.is_converged is True

    def test_short_spread_convergence_negative_delta(self):
        """
        T025: 测试做空价差收敛判断（spread_delta < 0时返回True）

        做空价差：
        - 开仓：Extended卖@3020, Lighter买@3000（spread=20）
        - 当前：Extended=3010, Lighter=2990（spread=20）
        - spread_delta = 20 - 20 = 0，但如果spread变得更负（<0）则收敛
        """
        pair = SpreadPair(
            pair_id=1,
            extended_side='sell',
            extended_price=Decimal('3020'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3000'),
            lighter_quantity=Decimal('0.1')
        )

        # 当前价格（价差缩小：15 < 20）
        extended_bid = Decimal('3005')
        extended_ask = Decimal('3015')
        lighter_bid = Decimal('2995')
        lighter_ask = Decimal('3005')

        # 检查收敛
        is_converged, status, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 验证结果
        # spread_delta = 3010 - 3000 = 10，开仓spread = 3020 - 3000 = 20
        # spread_delta = 10 - 20 = -10 < 0 → 收敛
        assert is_converged is True
        assert "价差收敛" in status
        assert spread_change.spread_delta < 0
        assert spread_change.is_converged is True

    def test_spread_divergence_long_position(self):
        """
        T026: 测试价差扩大情况（做多仓位）

        做多价差扩大：
        - 开仓：Extended买@3000, Lighter卖@3020（spread=20）
        - 当前：Extended=2990, Lighter=3000（spread=10）
        - spread_delta = 10 - 20 = -10 < 0 → 扩大（不利）
        """
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),
            lighter_quantity=Decimal('0.1')
        )

        # 当前价格（价差缩小：10 < 20）
        extended_bid = Decimal('2985')
        extended_ask = Decimal('2995')
        lighter_bid = Decimal('2995')
        lighter_ask = Decimal('3005')

        # 检查收敛
        is_converged, status, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 验证结果
        assert is_converged is False
        assert "价差扩大" in status
        assert spread_change.spread_delta < 0
        assert spread_change.is_converged is False

    def test_spread_divergence_short_position(self):
        """测试价差扩大情况（做空仓位）"""
        pair = SpreadPair(
            pair_id=1,
            extended_side='sell',
            extended_price=Decimal('3020'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3000'),
            lighter_quantity=Decimal('0.1')
        )

        # 当前价格（价差扩大：30 > 20）
        extended_bid = Decimal('3025')
        extended_ask = Decimal('3035')
        lighter_bid = Decimal('3000')
        lighter_ask = Decimal('3010')

        # 检查收敛
        is_converged, status, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 验证结果
        assert is_converged is False
        assert "价差扩大" in status
        assert spread_change.spread_delta > 0
        assert spread_change.is_converged is False


class TestCloseConditions:
    """测试平仓条件检查逻辑"""

    def test_priority_1_profit_target(self):
        """
        T027-P1: 测试优先级1 - 盈利目标平仓

        当未实现盈亏达到盈利目标时，应立即平仓
        """
        # 这个测试需要bot实例，稍后在集成测试中实现
        pass

    def test_priority_2_time_small_profit(self):
        """
        T027-P2: 测试优先级2 - 时间小额平仓

        持仓超过时间阈值且有小额利润时平仓
        """
        # 这个测试需要bot实例，稍后在集成测试中实现
        pass

    def test_priority_3_break_even_stop_loss(self):
        """
        T027-P3: 测试优先级3 - 回本止损

        持仓超过时间阈值且亏损时，等待回本后平仓
        """
        # 这个测试需要bot实例，稍后在集成测试中实现
        pass

    def test_priority_4_force_close(self):
        """
        T027-P4: 测试优先级4 - 强制平仓

        持仓超过最大时间时强制平仓
        """
        # 这个测试需要bot实例，稍后在集成测试中实现
        pass

    def test_priority_5_spread_divergence_delay(self):
        """
        T027-P5: 测试优先级5 - 价差扩大延迟平仓

        价差扩大时，根据配置决定是否延迟平仓
        """
        # 这个测试需要bot实例，稍后在集成测试中实现
        pass


class TestCloseDecision:
    """测试CloseDecision数据模型"""

    def test_close_decision_creation(self):
        """测试创建CloseDecision对象"""
        spread_change = SpreadChange(
            open_spread=Decimal('20'),
            current_spread=Decimal('25'),
            spread_delta=Decimal('5'),
            spread_change_rate=Decimal('0.25'),
            is_converged=True,
            is_favorable=True,
            status="价差收敛: 20 → 25 (+5)"
        )

        decision = CloseDecision(
            pair_id=1,
            should_close=True,
            priority=1,
            reason="盈利目标达标",
            reason_code="P1_CONVERGE_PROFIT",
            spread_change=spread_change,
            unrealized_pnl=Decimal('2.5'),
            pnl_rate=Decimal('0.083'),
            holding_time=120.0,
            is_warning=False,
            timestamp=1234567890.0,
            extended_close_price=Decimal('3005'),
            lighter_close_price=Decimal('3030')
        )

        # 验证字段
        assert decision.pair_id == 1
        assert decision.should_close is True
        assert decision.priority == 1
        assert decision.reason_code == "P1_CONVERGE_PROFIT"
        assert decision.is_warning is False
        assert decision.extended_close_price == Decimal('3005')
