"""
单元测试: 监控输出功能

测试整合持仓监控输出的核心功能
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import logging

from spread.spread_pair import SpreadPair
from spread.bot import SpreadArbitrageBot


class TestLogAllPositions:
    """测试 _log_all_positions 方法"""

    @pytest.fixture
    def bot(self):
        """创建测试用的bot实例"""
        # Mock config
        config = Mock()
        config.max_holding_time = 1800  # 30分钟
        config.profit_target_rate = Decimal('0.01')  # 1%
        config.log_level = 'INFO'  # 添加log_level属性

        # Mock clients
        extended_client = Mock()
        lighter_client = Mock()

        bot = SpreadArbitrageBot(config, extended_client, lighter_client)
        return bot

    @pytest.fixture
    def sample_pairs(self):
        """创建测试用的持仓数据"""
        pair1 = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3114.70'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3086.27'),
            lighter_quantity=Decimal('0.01')
        )

        pair2 = SpreadPair(
            pair_id=2,
            extended_side='buy',
            extended_price=Decimal('3115.80'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3087.57'),
            lighter_quantity=Decimal('0.01')
        )

        return [pair1, pair2]

    def test_empty_positions_should_log_no_positions(self, bot, caplog):
        """
        T007: 空持仓列表应输出"无活跃持仓"
        """
        with caplog.at_level(logging.INFO):
            bot._log_all_positions([])

        # 验证日志包含"无活跃持仓"
        assert "无活跃持仓" in caplog.text
        # 验证只有一条日志（整合输出）
        assert caplog.text.count("INFO") == 1

    def test_single_position_should_output_correct_format(self, bot, sample_pairs, caplog):
        """
        T008: 单个持仓应输出正确格式
        """
        single_pair = [sample_pairs[0]]

        with caplog.at_level(logging.INFO):
            bot._log_all_positions(
                single_pair,
                extended_bid=Decimal('3115.50'),
                extended_ask=Decimal('3115.60'),
                lighter_bid=Decimal('3117.00'),
                lighter_ask=Decimal('3118.00')
            )

        # 验证关键字段存在
        assert "📊 持仓监控汇总" in caplog.text
        assert "持仓 #1" in caplog.text
        assert "做多" in caplog.text
        assert "持仓时间:" in caplog.text
        assert "Extended仓位:" in caplog.text
        assert "Lighter仓位:" in caplog.text

        # 验证只有一条整合日志
        assert caplog.text.count("持仓 #1") == 1

    def test_multiple_positions_should_output_single_log_block(self, bot, sample_pairs, caplog):
        """
        T009: 多个持仓应输出为单个日志块
        """
        with caplog.at_level(logging.INFO):
            bot._log_all_positions(
                sample_pairs,
                extended_bid=Decimal('3115.50'),
                extended_ask=Decimal('3115.60'),
                lighter_bid=Decimal('3117.00'),
                lighter_ask=Decimal('3118.00')
            )

        # 验证所有持仓都在一个日志块中
        log_text = caplog.text
        assert "持仓 #1" in log_text
        assert "持仓 #2" in log_text

        # 验证只有一个 INFO 日志（整合输出）
        info_logs = [record for record in caplog.records if record.levelname == 'INFO']
        assert len(info_logs) == 1

        # 验证日志包含汇总标题
        assert "📊 持仓监控汇总" in log_text

    def test_positions_should_have_correct_separators(self, bot, sample_pairs, caplog):
        """
        T010: 持仓之间应有正确分隔符
        """
        with caplog.at_level(logging.INFO):
            bot._log_all_positions(
                sample_pairs,
                extended_bid=Decimal('3115.50'),
                extended_ask=Decimal('3115.60'),
                lighter_bid=Decimal('3117.00'),
                lighter_ask=Decimal('3118.00')
            )

        # 验证存在分隔符
        assert "━━━" in caplog.text

        # 验证分隔符在持仓之间
        log_text = caplog.text
        lines = log_text.split('\n')

        # 找到持仓行和分隔符行的位置
        position1_idx = None
        position2_idx = None
        separator_indices = []

        for i, line in enumerate(lines):
            if '持仓 #1' in line:
                position1_idx = i
            elif '持仓 #2' in line:
                position2_idx = i
            elif '━━━' in line:
                separator_indices.append(i)

        # 验证找到了持仓和分隔符
        assert position1_idx is not None
        assert position2_idx is not None
        assert len(separator_indices) >= 1

        # 验证至少有一个分隔符在两个持仓之间
        has_separator_between = any(
            position1_idx < sep_idx < position2_idx
            for sep_idx in separator_indices
        )
        assert has_separator_between


class TestCalculateRealizedPnl:
    """测试 calculate_realized_pnl 方法"""

    @pytest.fixture
    def long_position(self):
        """创建做多持仓"""
        return SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000.00'),
            extended_quantity=Decimal('0.5'),
            lighter_price=Decimal('2980.00'),
            lighter_quantity=Decimal('0.5')
        )

    @pytest.fixture
    def short_position(self):
        """创建做空持仓"""
        return SpreadPair(
            pair_id=2,
            extended_side='sell',
            extended_price=Decimal('3000.00'),
            extended_quantity=Decimal('0.5'),
            lighter_price=Decimal('2980.00'),
            lighter_quantity=Decimal('0.5')
        )

    def test_long_position_realized_pnl_calculation(self, long_position):
        """
        T023: 做多持仓已实现收益计算

        Extended买入 @ $3000, 当前bid $3005 → 盈 $2.5
        Lighter卖出 @ $2980, 当前ask $3010 → 亏 $15
        已实现收益 = $2.5 - $15 = -$12.5
        """
        result = long_position.calculate_realized_pnl(
            extended_close_price=Decimal('3005.00'),  # bid (卖出价)
            lighter_close_price=Decimal('3010.00')    # ask (买入平仓价)
        )

        # 验证计算结果
        expected = Decimal('-12.50')
        assert result == expected

    def test_short_position_realized_pnl_calculation(self, short_position):
        """
        T024: 做空持仓已实现收益计算

        Extended卖出 @ $3000, 当前ask $2995 → 盈 $2.5
        Lighter买入 @ $2980 (因为short时lighter做多), 当前bid $2975 → 亏 $2.5
        已实现收益 = $2.5 - $2.5 = $0
        """
        result = short_position.calculate_realized_pnl(
            extended_close_price=Decimal('2995.00'),  # ask (买入平仓价)
            lighter_close_price=Decimal('2975.00')    # bid (卖出价)
        )

        # 验证计算结果
        expected = Decimal('0.00')
        assert result == expected

    def test_none_prices_should_return_none(self, long_position):
        """
        T025: 价格为None时应显示N/A
        """
        # 测试extended价格为None
        result1 = long_position.calculate_realized_pnl(
            extended_close_price=None,
            lighter_close_price=Decimal('3010.00')
        )
        assert result1 is None

        # 测试lighter价格为None
        result2 = long_position.calculate_realized_pnl(
            extended_close_price=Decimal('3005.00'),
            lighter_close_price=None
        )
        assert result2 is None

        # 测试两个价格都为None
        result3 = long_position.calculate_realized_pnl(
            extended_close_price=None,
            lighter_close_price=None
        )
        assert result3 is None

    def test_realized_pnl_precision(self, long_position):
        """
        T026: 已实现收益精度验证（误差<0.01%）
        """
        result = long_position.calculate_realized_pnl(
            extended_close_price=Decimal('3005.00'),
            lighter_close_price=Decimal('3010.00')
        )

        # 验证返回Decimal类型
        assert isinstance(result, Decimal)

        # 验证精度（2位小数）
        result_str = f"{result:.2f}"
        assert result_str == "-12.50"


class TestOutputFormat:
    """测试输出格式规范"""

    def test_output_format_matches_spec(self):
        """
        T034: 验证输出格式符合contracts/output-format.md规范
        """
        # TODO: 实现后验证完整输出格式
        pass

    def test_number_formatting(self):
        """
        T035: 数字格式验证（时间整数、价格2位小数、数量4位小数）
        """
        # TODO: 实现后验证数字格式
        pass
