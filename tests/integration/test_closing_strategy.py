"""
智能平仓策略集成测试

测试多层平仓策略:
- 盈利目标平仓
- 时间小额平仓
- 回本止损
- 强制平仓
"""

import pytest
import time
from decimal import Decimal
from unittest.mock import Mock, patch

from spread.config import SpreadArbConfig
from spread.spread_pair import SpreadPair
from spread.bot import SpreadArbitrageBot


@pytest.fixture
def closing_config():
    """测试配置 - 用于平仓策略测试"""
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),
        # 平仓策略配置
        profit_target_rate=Decimal('0.0005'),    # 0.05% 盈利目标
        time_close_threshold=60,                 # 60秒时间阈值
        max_holding_time=300,                    # 5分钟最大持仓时间
        enable_profit_target=True,
        enable_time_close=True,
        # 传统止损 (可选)
        enable_stop_loss=True,
        stop_loss_usdt=Decimal('5')
    )


@pytest.fixture
def mock_bot(closing_config):
    """创建模拟的机器人实例"""
    extended_client = Mock()
    lighter_client = Mock()

    extended_client.setup_order_update_handler = Mock()

    bot = SpreadArbitrageBot(closing_config, extended_client, lighter_client)
    return bot


@pytest.mark.asyncio
def test_profit_target_closing(mock_bot):
    """
    T026 [US3]: 测试盈利目标平仓

    鉴于 开仓后价差盈利达到0.05%(覆盖2倍手续费)
    当 系统计算PnL
    则 立即平仓锁定利润
    """
    # 创建一个套利对
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟当前价格导致盈利目标达标
    # Extended 买入 @ 2500, Lighter 卖出 @ 2501.25
    # 平仓时: Extended 卖出 @ 2502, Lighter 买入 @ 2500.50
    current_extended = Decimal('2502.00')
    current_lighter = Decimal('2500.50')

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 验证应该平仓 (盈利目标)
    assert should_close is True
    assert '盈利目标' in reason or '达标' in reason


@pytest.mark.asyncio
def test_time_based_small_profit_closing(mock_bot):
    """
    T027 [US3]: 测试时间小额平仓

    鉴于 开仓后在配置的时间阈值(默认60秒)内未达盈利目标但PnL > 0
    当 超过时间阈值
    则 平仓获取小额利润
    """
    pair = SpreadPair(
        pair_id=2,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2500.75'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟持仓超过 60 秒
    pair.open_time = time.time() - 61

    # 模拟小额利润 (未达到盈利目标)
    current_extended = Decimal('2500.50')
    current_lighter = Decimal('2500.40')

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 验证应该平仓 (时间小额)
    assert should_close is True
    assert '时间小额' in reason


@pytest.mark.asyncio
def test_break_even_stop_loss(mock_bot):
    """
    T028 [US3]: 测试回本止损

    鉴于 开仓超过时间阈值后PnL仍 < 0
    当 系统监控PnL
    则 等待PnL转为0时立即平仓止损
    """
    pair = SpreadPair(
        pair_id=3,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2500.50'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟持仓超过 60 秒
    pair.open_time = time.time() - 61

    # 场景 1: 仍在亏损,不应该平仓
    current_extended_loss = Decimal('2499.00')
    current_lighter_loss = Decimal('2500.00')

    should_close, reason = mock_bot._check_force_close(
        pair, current_extended_loss, current_lighter_loss
    )

    # 仍在亏损时不应平仓
    assert should_close is False

    # 场景 2: 回本 (PnL >= 0), 应该平仓
    current_extended_breakeven = Decimal('2500.625')
    current_lighter_breakeven = Decimal('2500.00')

    should_close, reason = mock_bot._check_force_close(
        pair, current_extended_breakeven, current_lighter_breakeven
    )

    # 回本时应该平仓 (时间小额, 因为 PnL >= 0)
    assert should_close is True


@pytest.mark.asyncio
def test_force_close_max_holding_time(mock_bot):
    """
    T029 [US3]: 测试强制平仓

    鉴于 持仓超过最大允许时间(可配置,建议5分钟)
    当 无论PnL如何
    则 强制平仓避免长期风险
    """
    pair = SpreadPair(
        pair_id=4,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟持仓超过最大时间 (301秒 > 300秒)
    pair.open_time = time.time() - 301

    # 即使在亏损状态,也应该强制平仓
    current_extended = Decimal('2495.00')  # 亏损
    current_lighter = Decimal('2500.00')

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 验证应该强制平仓
    assert should_close is True
    assert '强制平仓' in reason


@pytest.mark.asyncio
def test_priority_order_profit_target_first(mock_bot):
    """
    额外测试: 验证盈利目标优先级最高

    即使持仓时间很短,如果达到盈利目标也应该立即平仓
    """
    pair = SpreadPair(
        pair_id=5,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 持仓时间很短 (5秒)
    pair.open_time = time.time() - 5

    # 但盈利目标达标
    current_extended = Decimal('2502.50')
    current_lighter = Decimal('2499.50')

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 应该立即平仓 (盈利目标优先)
    assert should_close is True
    assert '盈利目标' in reason


@pytest.mark.asyncio
def test_no_close_when_conditions_not_met(mock_bot):
    """
    额外测试: 验证不满足条件时不平仓

    持仓时间短且未达盈利目标时,不应平仓
    """
    pair = SpreadPair(
        pair_id=6,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 持仓时间短 (30秒 < 60秒阈值)
    pair.open_time = time.time() - 30

    # 小幅盈利但未达目标
    current_extended = Decimal('2500.20')
    current_lighter = Decimal('2501.00')

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 不应该平仓
    assert should_close is False
    assert reason is None


@pytest.mark.asyncio
def test_traditional_stop_loss_still_works(mock_bot):
    """
    额外测试: 验证传统止损仍然有效

    当亏损超过传统止损线时,应该立即平仓
    """
    pair = SpreadPair(
        pair_id=7,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟大额亏损 (超过 $5 止损线)
    # 使用更大的价格变化确保达到 -5 止损线
    # Extended 买入 @ 2500, 现在跌到 2400, 亏损 100 * 0.014 = $1.4
    # Lighter 卖出 @ 2501.25, 现在涨到 2600, 亏损 98.75 * 0.014 = $1.3825
    # 总亏损约 $2.78, 仍然不够

    # 需要更大的变化: quantity * (extended_change + lighter_change) > 5
    # 0.014 * (ext_change + lighter_change) > 5
    # ext_change + lighter_change > 357
    # 如果 ext_change = lighter_change = 178.5
    # extended_price = 2500 - 200 = 2300
    # lighter_price = 2501.25 + 200 = 2701.25
    current_extended = Decimal('2300.00')
    current_lighter = Decimal('2701.25')

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 应该触发传统止损
    assert should_close is True
    assert '止损' in reason


@pytest.mark.asyncio
def test_sell_side_closing_strategy(mock_bot):
    """
    额外测试: 验证卖出方向的平仓策略

    确保 Extended 卖出方向的平仓逻辑也正确
    """
    pair = SpreadPair(
        pair_id=8,
        extended_side='sell',  # 卖出方向
        extended_price=Decimal('2501.25'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2500.00'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟盈利目标达标
    current_extended = Decimal('2500.00')  # Extended 平仓买入价格更低,盈利
    current_lighter = Decimal('2501.50')  # Lighter 平仓卖出价格更高

    should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

    # 应该触发盈利目标平仓
    assert should_close is True
    assert '盈利目标' in reason


class TestClosingStrategyEdgeCases:
    """测试平仓策略的边界情况"""

    @pytest.mark.asyncio
    async def test_exactly_at_threshold(self, mock_bot):
        """测试恰好等于阈值的情况"""
        pair = SpreadPair(
            pair_id=9,
            extended_side='buy',
            extended_price=Decimal('2500.00'),
            extended_quantity=Decimal('0.014'),
            lighter_price=Decimal('2501.25'),
            lighter_quantity=Decimal('0.014')
        )

        # 恰好 60 秒
        pair.open_time = time.time() - 60

        # 微小利润
        current_extended = Decimal('2500.01')
        current_lighter = Decimal('2501.24')

        should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

        # 应该平仓 (时间小额)
        assert should_close is True

    @pytest.mark.asyncio
    async def test_zero_pnl_after_timeout(self, mock_bot):
        """测试超时后 PnL 恰好为 0 的情况"""
        pair = SpreadPair(
            pair_id=10,
            extended_side='buy',
            extended_price=Decimal('2500.00'),
            extended_quantity=Decimal('0.014'),
            lighter_price=Decimal('2501.25'),
            lighter_quantity=Decimal('0.014')
        )

        pair.open_time = time.time() - 61

        # PnL 恰好为 0
        current_extended = Decimal('2500.625')
        current_lighter = Decimal('2500.625')

        should_close, reason = mock_bot._check_force_close(pair, current_extended, current_lighter)

        # PnL >= 0 应该平仓
        assert should_close is True
