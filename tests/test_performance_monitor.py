"""
PerformanceMonitor单元测试

测试011-async-ws-ioc-trading的性能监控器功能
"""

import pytest
import time
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch

from spread.config import SpreadArbConfig
from spread.performance_monitor import PerformanceMonitor
from spread.models import (
    DataFreshnessResult,
    SlippageCheckResult,
    ProfitabilityCheckResult,
)


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        max_tick_to_trade_latency_ms=10.0,
        max_execution_latency_ms=300.0,
        max_data_age_ms=500.0,
        concurrent_order_send_threshold_ms=5.0,
        ioc_slippage_tolerance_rate=Decimal('0.0005'),
        min_net_profit_rate=Decimal('0.0002'),
        expected_slippage_cost_rate=Decimal('0.0001'),
        max_slippage_warning_rate=Decimal('0.002'),
        enable_enhanced_logging=True,
        log_all_timestamps=True,
        enable_console_warnings=True,
        enable_data_freshness_check=True,
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


class TestPerformanceMonitorBasics:
    """测试性能监控器基础功能"""

    def test_initialization(self, config):
        """测试初始化"""
        mon = PerformanceMonitor(config)
        assert mon.config == config
        assert mon._timestamps == {}
        assert mon._stats['total_checks'] == 0

    def test_record_timestamp(self, monitor):
        """测试时间戳记录"""
        monitor.record_timestamp('signal')
        assert 'signal' in monitor._timestamps
        assert monitor._timestamps['signal'] > 0

    def test_record_timestamp_with_metadata(self, monitor):
        """测试带元数据的时间戳记录"""
        monitor.record_timestamp('calc', {'log': True})
        assert 'calc' in monitor._timestamps

    def test_get_latency(self, monitor):
        """测试延迟计算"""
        monitor.record_timestamp('start')
        time.sleep(0.01)  # 10ms
        monitor.record_timestamp('end')

        latency = monitor.get_latency('start', 'end')
        assert latency is not None
        assert latency >= 10  # 至少10ms

    def test_get_latency_missing_timestamp(self, monitor):
        """测试缺失时间戳的延迟计算"""
        monitor.record_timestamp('start')
        latency = monitor.get_latency('start', 'nonexistent')
        assert latency is None


class TestTickToTradeLatency:
    """测试行情到交易延迟记录"""

    def test_record_normal_latency(self, monitor):
        """测试正常延迟记录"""
        signal_ts = time.time() * 1000
        send_ts = signal_ts + 8.45  # 8.45ms

        monitor.record_tick_to_trade_latency(signal_ts, send_ts)

        assert len(monitor._stats['tick_to_trade_latencies']) == 1
        # 使用近似比较，因为时间戳有浮点精度问题
        assert monitor._stats['tick_to_trade_latencies'][0] == pytest.approx(8.45, abs=0.01)

    def test_record_high_latency_warning(self, monitor):
        """测试高延迟警告"""
        signal_ts = time.time() * 1000
        send_ts = signal_ts + 15.0  # 超过max_tick_to_trade_latency_ms=10.0

        # 不应该抛出异常，只记录警告
        monitor.record_tick_to_trade_latency(signal_ts, send_ts)
        assert len(monitor._stats['tick_to_trade_latencies']) == 1


class TestExecutionLatency:
    """测试执行延迟记录"""

    def test_record_execution_latency(self, monitor):
        """测试执行延迟记录"""
        send_ts = time.time() * 1000
        ack_ts = send_ts + 250.0  # 250ms

        monitor.record_execution_latency(send_ts, ack_ts)

        assert len(monitor._stats['execution_latencies']) == 1
        assert monitor._stats['execution_latencies'][0] == 250.0


class TestConcurrentSendGap:
    """测试并发发送间隔记录"""

    def test_record_concurrent_send_gap_within_threshold(self, monitor):
        """测试记录在阈值内的并发间隔"""
        send_a = time.time() * 1000
        send_b = send_a + 3.21  # 3.21ms < 5.0ms阈值

        monitor.record_concurrent_send_gap(send_a, send_b)

        assert len(monitor._stats['concurrent_gaps']) == 1
        # 使用近似比较，因为时间戳有浮点精度问题
        assert monitor._stats['concurrent_gaps'][0] == pytest.approx(3.21, abs=0.01)

    def test_record_concurrent_send_gap_exceeds_threshold(self, monitor):
        """测试记录超过阈值的并发间隔"""
        send_a = time.time() * 1000
        send_b = send_a + 7.5  # 7.5ms > 5.0ms阈值

        monitor.record_concurrent_send_gap(send_a, send_b)

        assert len(monitor._stats['concurrent_gaps']) == 1
        assert monitor._stats['concurrent_gaps'][0] == 7.5


class TestDataFreshnessCheck:
    """测试数据新鲜度检查"""

    def test_check_data_freshness_fresh(self, monitor):
        """测试检查新鲜数据"""
        current_time = time.time() * 1000
        data_ts = current_time - 100  # 100ms前，小于500ms阈值

        result = monitor.check_data_freshness('extended', data_ts, current_time)

        assert result.is_fresh is True
        assert result.data_age_ms == 100
        assert result.exchange == 'extended'

    def test_check_data_freshness_stale(self, monitor):
        """测试检查过期数据"""
        current_time = time.time() * 1000
        data_ts = current_time - 600  # 600ms前，超过500ms阈值

        result = monitor.check_data_freshness('lighter', data_ts, current_time)

        assert result.is_fresh is False
        assert result.data_age_ms == 600
        assert result.exchange == 'lighter'

    def test_check_data_freshness_invalid_exchange(self, monitor):
        """测试无效交易所名称"""
        with pytest.raises(ValueError):
            monitor.check_data_freshness('invalid', time.time() * 1000)

    def test_check_both_data_freshness_both_fresh(self, monitor):
        """测试双边数据都新鲜"""
        current_time = time.time() * 1000
        ext_ts = current_time - 100
        lit_ts = current_time - 150

        both_fresh, results = monitor.check_both_data_freshness(ext_ts, lit_ts, current_time)

        assert both_fresh is True
        assert len(results) == 2
        assert all(r.is_fresh for r in results)

    def test_check_both_data_freshness_one_stale(self, monitor):
        """测试一边数据过期"""
        current_time = time.time() * 1000
        ext_ts = current_time - 100  # 新鲜
        lit_ts = current_time - 600  # 过期

        both_fresh, results = monitor.check_both_data_freshness(ext_ts, lit_ts, current_time)

        assert both_fresh is False
        assert results[0].is_fresh is True
        assert results[1].is_fresh is False


class TestSlippageCheck:
    """测试滑点检查"""

    def test_check_slippage_buy_acceptable(self, monitor):
        """测试买入滑点可接受"""
        expected = Decimal('3000.00')
        current = Decimal('3001.50')  # 滑点0.05%，在阈值内

        result = monitor.check_slippage(expected, current, 'buy')

        assert result.is_acceptable is True
        assert result.side == 'buy'

    def test_check_slippage_sell_acceptable(self, monitor):
        """测试卖出滑点可接受"""
        expected = Decimal('3000.00')
        current = Decimal('2998.50')  # 滑点0.05%，在阈值内

        result = monitor.check_slippage(expected, current, 'sell')

        assert result.is_acceptable is True

    def test_check_slippage_exceeds_threshold(self, monitor):
        """测试滑点超过阈值"""
        expected = Decimal('3000.00')
        current = Decimal('3010.00')  # 滑点0.33%，超过0.05%阈值

        result = monitor.check_slippage(expected, current, 'buy')

        assert result.is_acceptable is False
        assert result.slippage_rate > Decimal('0.0005')

    def test_check_slippage_invalid_side(self, monitor):
        """测试无效方向"""
        with pytest.raises(ValueError):
            monitor.check_slippage(Decimal('3000'), Decimal('3001'), 'invalid')


class TestProfitabilityCheck:
    """测试利润率检查"""

    def test_check_profitability_profitable(self, monitor):
        """测试利润率足够"""
        spread_rate = Decimal('0.0010')  # 0.10%

        result = monitor.check_profitability(spread_rate)

        assert result.is_profitable is True
        assert result.spread_rate == spread_rate
        # 净利润 = 0.10% - 0.04%(手续费) - 0.01%(预期滑点) = 0.05% > 0.02%
        assert result.net_profit_rate >= result.min_net_profit

    def test_check_profitability_not_profitable(self, monitor):
        """测试利润率不足"""
        spread_rate = Decimal('0.0004')  # 0.04%

        result = monitor.check_profitability(spread_rate)

        assert result.is_profitable is False
        # 净利润 = 0.04% - 0.04% - 0.01% = -0.01% < 0.02%

    def test_check_profitability_custom_fees(self, monitor):
        """测试自定义手续费"""
        spread_rate = Decimal('0.0008')
        ext_fee = Decimal('0.0002')
        lighter_fee = Decimal('0.0002')

        result = monitor.check_profitability(
            spread_rate,
            extended_fee=ext_fee,
            lighter_fee=lighter_fee
        )

        # 净利润 = 0.08% - 0.04% - 0.01% = 0.03% > 0.02%
        assert result.total_fees == ext_fee + lighter_fee


class TestStatsSummary:
    """测试统计摘要"""

    def test_get_stats_summary_empty(self, monitor):
        """测试空统计摘要"""
        stats = monitor.get_stats_summary()

        assert stats['total_checks'] == 0
        assert stats['stale_data_count'] == 0
        assert stats['slippage_rejections'] == 0

    def test_get_stats_summary_with_data(self, monitor):
        """测试有数据的统计摘要"""
        # 添加一些数据
        monitor._stats['tick_to_trade_latencies'] = [8.0, 10.0, 12.0]
        monitor._stats['execution_latencies'] = [200.0, 250.0]
        monitor._stats['stale_data_count'] = 2
        monitor._stats['total_checks'] = 100

        stats = monitor.get_stats_summary()

        assert stats['total_checks'] == 100
        assert stats['stale_data_count'] == 2
        assert stats['stale_data_rate'] == 0.02
        assert stats['avg_tick_to_trade_latency_ms'] == 10.0
        assert stats['max_tick_to_trade_latency_ms'] == 12.0
        assert stats['avg_execution_latency_ms'] == 225.0

    def test_log_stats_summary(self, monitor, caplog):
        """测试日志输出统计摘要"""
        import logging
        caplog.set_level(logging.INFO)

        monitor.log_stats_summary()

        # 检查日志包含统计信息
        assert '性能监控统计' in caplog.text or '统计报告' in caplog.text


class TestOpeningDecisionLog:
    """测试开仓决策日志"""

    def test_log_opening_decision_allowed(self, monitor, caplog):
        """测试记录允许开仓决策"""
        import logging
        caplog.set_level(logging.INFO)

        opportunity = {
            'type': '做多价差',
            'side': 'buy',
            'spread_rate': Decimal('0.0010'),
            'extended_price': Decimal('3000.00'),
            'lighter_price': Decimal('3003.00')
        }

        freshness = [
            DataFreshnessResult.fresh('extended', time.time() * 1000 - 50),
            DataFreshnessResult.fresh('lighter', time.time() * 1000 - 60)
        ]

        monitor.log_opening_decision(
            opportunity,
            freshness,
            final_decision='允许开仓'
        )

        # 检查日志包含决策信息
        assert '开仓决策详情' in caplog.text
        assert '做多价差' in caplog.text
        assert '允许开仓' in caplog.text

    def test_log_opening_decision_rejected(self, monitor, caplog):
        """测试记录拒绝开仓决策"""
        import logging
        caplog.set_level(logging.INFO)

        opportunity = {
            'type': '做空价差',
            'side': 'sell',
            'spread_rate': Decimal('0.0005'),
        }

        freshness = []

        monitor.log_opening_decision(
            opportunity,
            freshness,
            final_decision='拒绝开仓（数据过期）'
        )

        assert '拒绝开仓' in caplog.text
