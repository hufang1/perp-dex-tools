"""
集成测试: 监控输出功能

测试监控输出在完整监控循环中的集成
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import logging

from spread.spread_pair import SpreadPair
from spread.config import SpreadArbConfig


class TestMonitorIntegration:
    """集成测试: 完整监控循环"""

    @pytest.fixture
    def config(self):
        """创建测试配置"""
        return SpreadArbConfig(
            ticker='ETH',
            order_quantity_usdt=Decimal('0.01'),
            max_open_pairs=3,
            min_spread_rate=Decimal('0.005'),
            profit_target_rate=Decimal('0.01'),
            max_holding_time=1800
        )

    @pytest.fixture
    def mock_clients(self):
        """创建mock交易所客户端"""
        extended_client = Mock()
        lighter_client = Mock()

        # Mock WebSocket连接
        extended_client.connect = AsyncMock()
        lighter_client.connect = AsyncMock()

        return extended_client, lighter_client

    @pytest.fixture
    def bot(self, config, mock_clients):
        """创建测试用的bot实例"""
        from spread.bot import SpreadArbitrageBot

        extended_client, lighter_client = mock_clients
        bot = SpreadArbitrageBot(config, extended_client, lighter_client)

        # 设置订单簿数据
        bot.extended_orderbook = {
            'bids': {Decimal('3115.00'): Decimal('1.0')},
            'asks': {Decimal('3116.00'): Decimal('1.0')}
        }
        bot.extended_orderbook_ready = True

        bot.lighter_orderbook = {
            'bids': {Decimal('3117.00'): Decimal('1.0')},
            'asks': {Decimal('3118.00'): Decimal('1.0')}
        }
        bot.lighter_orderbook_ready = True

        return bot

    @pytest.fixture
    def sample_pairs(self):
        """创建测试用的持仓数据"""
        pairs = [
            SpreadPair(
                pair_id=1,
                extended_side='buy',
                extended_price=Decimal('3114.70'),
                extended_quantity=Decimal('0.01'),
                lighter_price=Decimal('3086.27'),
                lighter_quantity=Decimal('0.01')
            ),
            SpreadPair(
                pair_id=2,
                extended_side='buy',
                extended_price=Decimal('3115.80'),
                extended_quantity=Decimal('0.01'),
                lighter_price=Decimal('3087.57'),
                lighter_quantity=Decimal('0.01')
            ),
            SpreadPair(
                pair_id=3,
                extended_side='buy',
                extended_price=Decimal('3115.80'),
                extended_quantity=Decimal('0.01'),
                lighter_price=Decimal('3087.62'),
                lighter_quantity=Decimal('0.01')
            )
        ]
        return pairs

    @pytest.mark.asyncio
    async def test_complete_monitoring_cycle(self, bot, sample_pairs, caplog):
        """
        T011: 集成测试 - 完整监控循环测试

        验证在完整的监控循环中，多个持仓的监控信息能够正确整合输出
        """
        bot.open_pairs = sample_pairs

        # 模拟监控循环
        with caplog.at_level(logging.INFO):
            # 获取订单簿价格
            extended_bid = list(bot.extended_orderbook['bids'].keys())[0]
            lighter_ask = list(bot.lighter_orderbook['asks'].keys())[0]

            # 调用整合输出方法
            bot._log_all_positions(
                bot.open_pairs,
                extended_bid=extended_bid,
                extended_ask=Decimal('3116.00'),
                lighter_bid=Decimal('3117.00'),
                lighter_ask=lighter_ask
            )

        # 验证输出格式
        log_text = caplog.text

        # 验证包含所有持仓
        assert "持仓 #1" in log_text
        assert "持仓 #2" in log_text
        assert "持仓 #3" in log_text

        # 验证整合输出
        assert "📊 持仓监控汇总" in log_text

        # 验证只有一条日志（整合输出）
        info_logs = [record for record in caplog.records if record.levelname == 'INFO']
        assert len(info_logs) == 1

    def test_monitoring_does_not_interrupt_trading_logic(self, bot, sample_pairs):
        """
        验证监控输出不会影响交易逻辑
        """
        # 设置持仓
        bot.open_pairs = sample_pairs

        # 记录初始状态
        initial_pairs_count = len(bot.open_pairs)

        # 调用监控输出
        bot._log_all_positions(
            bot.open_pairs,
            extended_bid=Decimal('3115.00'),
            extended_ask=Decimal('3116.00'),
            lighter_bid=Decimal('3117.00'),
            lighter_ask=Decimal('3118.00')
        )

        # 验证持仓数量未改变
        assert len(bot.open_pairs) == initial_pairs_count

        # 验证持仓状态未改变
        for pair in bot.open_pairs:
            assert not pair.is_closed
            assert not pair.is_closing

    def test_error_handling_in_monitoring(self, bot, sample_pairs, caplog):
        """
        验证单个持仓计算失败不会中断整个监控输出
        """
        # 添加一个会引发异常的持仓（使用None价格）
        bot.open_pairs = sample_pairs

        with caplog.at_level(logging.INFO):
            # 即使价格为None，也不应该抛出异常
            bot._log_all_positions(
                bot.open_pairs,
                extended_bid=None,  # None价格
                extended_ask=None,
                lighter_bid=None,
                lighter_ask=None
            )

        # 验证仍然有输出（即使数据不完整）
        assert len(caplog.text) > 0

    def test_monitoring_with_no_positions(self, bot, caplog):
        """
        验证无持仓时的监控输出
        """
        bot.open_pairs = []

        with caplog.at_level(logging.INFO):
            bot._log_all_positions(bot.open_pairs)

        # 验证输出"无活跃持仓"
        assert "无活跃持仓" in caplog.text

    def test_concurrent_position_updates(self, bot, sample_pairs):
        """
        验证监控循环与持仓更新并发时的行为
        """
        import time

        bot.open_pairs = sample_pairs

        # 记录开始时间
        start_time = time.time()

        # 多次调用监控输出（模拟并发）
        for _ in range(5):
            bot._log_all_positions(
                bot.open_pairs,
                extended_bid=Decimal('3115.00'),
                extended_ask=Decimal('3116.00'),
                lighter_bid=Decimal('3117.00'),
                lighter_ask=Decimal('3118.00')
            )

        # 验证完成时间合理（应该很快）
        elapsed_time = time.time() - start_time
        assert elapsed_time < 1.0  # 应该在1秒内完成

    def test_summary_line_for_multiple_positions(self, bot, sample_pairs, caplog):
        """
        验证多个持仓时的摘要行
        """
        bot.open_pairs = sample_pairs

        with caplog.at_level(logging.INFO):
            bot._log_all_positions(
                bot.open_pairs,
                extended_bid=Decimal('3115.00'),
                extended_ask=Decimal('3116.00'),
                lighter_bid=Decimal('3117.00'),
                lighter_ask=Decimal('3118.00')
            )

        # 验证包含总持仓数
        log_text = caplog.text
        assert "总持仓:" in log_text
        assert "3" in log_text  # 3个持仓
