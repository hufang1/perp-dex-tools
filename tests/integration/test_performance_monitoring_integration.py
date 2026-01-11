"""
Performance Monitoring集成测试

测试011-async-ws-ioc-trading的性能监控功能
"""

import pytest
import time
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from spread.config import SpreadArbConfig
from spread.performance_monitor import PerformanceMonitor
from spread.models import TradeOperationRecord


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
        enable_enhanced_logging=True,
        log_all_timestamps=True,
        enable_data_freshness_check=True,
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


class TestTimestampRecording:
    """测试时间戳记录"""

    def test_record_timestamp_chain(self, monitor):
        """测试记录完整时间戳链"""
        # 模拟交易流程中的时间戳记录
        monitor.record_timestamp('signal')
        time.sleep(0.001)  # 1ms
        monitor.record_timestamp('data_A')
        time.sleep(0.001)  # 1ms
        monitor.record_timestamp('data_B')
        time.sleep(0.001)  # 1ms
        monitor.record_timestamp('calc')
        time.sleep(0.001)  # 1ms
        monitor.record_timestamp('send_A')
        time.sleep(0.001)  # 1ms
        monitor.record_timestamp('send_B')

        # 验证所有时间戳都被记录
        assert 'signal' in monitor._timestamps
        assert 'data_A' in monitor._timestamps
        assert 'data_B' in monitor._timestamps
        assert 'calc' in monitor._timestamps
        assert 'send_A' in monitor._timestamps
        assert 'send_B' in monitor._timestamps

    def test_calculate_latencies(self, monitor):
        """测试延迟计算"""
        monitor.record_timestamp('signal')
        time.sleep(0.005)  # 5ms
        monitor.record_timestamp('send_A')

        latency = monitor.get_latency('signal', 'send_A')

        assert latency is not None
        assert latency >= 5  # 至少5ms


class TestDecisionRecording:
    """测试决策记录"""

    def test_record_decision(self, monitor):
        """测试记录决策"""
        record = TradeOperationRecord(
            timestamp=time.time(),
            operation_type='OPEN',
            exchange='BOTH',
            signal_ts=time.time() * 1000,
            data_ts_A=time.time() * 1000,
            data_ts_B=time.time() * 1000,
            calc_ts=time.time() * 1000,
            send_A_ts=time.time() * 1000,
            send_B_ts=time.time() * 1000,
            ack_A_ts=time.time() * 1000,
            ack_B_ts=time.time() * 1000,
            spread_rate=Decimal('0.0010'),
            decision='ALLOWED',
            status='SUCCESS'
        )

        monitor.record_decision(record)

        # 验证记录被保存
        assert len(monitor._decision_records) == 1

    def test_get_recent_decisions(self, monitor):
        """测试获取最近的决策记录"""
        # 记录多条决策
        for i in range(10):
            record = TradeOperationRecord(
                timestamp=time.time(),
                operation_type='OPEN',
                exchange='BOTH',
                decision='ALLOWED',
                status='SUCCESS'
            )
            monitor.record_decision(record)

        # 获取最近5分钟的记录
        recent = monitor.get_decision_records(last_n_minutes=5)

        assert len(recent) == 10


class TestCSVExport:
    """测试CSV导出"""

    def test_export_performance_data(self, monitor, tmp_path):
        """测试导出性能数据"""
        # 添加一些延迟数据
        monitor._stats['tick_to_trade_latencies'] = [8.0, 10.0, 12.0]
        monitor._stats['execution_latencies'] = [200.0, 250.0]
        monitor._stats['concurrent_gaps'] = [2.0, 3.0]

        # 导出数据
        output_file = tmp_path / "test_performance.csv"
        result = monitor.export_performance_data(output_file=str(output_file))

        assert result is not None
        assert output_file.exists()

    def test_export_decision_records(self, monitor, tmp_path):
        """测试导出决策记录"""
        # 添加一些决策记录
        for i in range(5):
            record = TradeOperationRecord(
                timestamp=time.time(),
                operation_type='OPEN',
                exchange='BOTH',
                decision='ALLOWED',
                status='SUCCESS'
            )
            monitor.record_decision(record)

        # 导出数据
        output_file = tmp_path / "test_decisions.csv"
        result = monitor.export_decision_records(output_file=str(output_file))

        assert result is not None
        assert output_file.exists()

    def test_export_latency_distribution(self, monitor):
        """测试导出延迟分布"""
        # 添加延迟数据
        monitor._stats['tick_to_trade_latencies'] = [8.0, 10.0, 12.0, 9.0, 11.0]

        # 导出分布
        distribution = monitor.export_latency_distribution()

        assert distribution is not None
        assert 'count' in distribution
        assert 'min' in distribution
        assert 'max' in distribution
        assert 'mean' in distribution
        assert 'median' in distribution
        assert distribution['count'] == 5


class TestPerformanceMonitoringIntegration:
    """测试性能监控集成"""

    def test_full_monitoring_workflow(self, monitor):
        """测试完整监控工作流"""
        # 1. 记录信号时间戳
        monitor.record_timestamp('signal')

        # 2. 模拟数据获取
        time.sleep(0.001)
        monitor.record_timestamp('data_A')
        monitor.record_timestamp('data_B')

        # 3. 模拟计算
        time.sleep(0.001)
        monitor.record_timestamp('calc')

        # 4. 模拟订单发送
        time.sleep(0.001)
        monitor.record_timestamp('send_A')
        monitor.record_timestamp('send_B')

        # 5. 模拟订单确认
        time.sleep(0.001)
        monitor.record_timestamp('ack_A')
        monitor.record_timestamp('ack_B')

        # 6. 记录决策
        record = TradeOperationRecord(
            timestamp=time.time(),
            operation_type='OPEN',
            exchange='BOTH',
            signal_ts=monitor._timestamps.get('signal'),
            data_ts_A=monitor._timestamps.get('data_A'),
            data_ts_B=monitor._timestamps.get('data_B'),
            calc_ts=monitor._timestamps.get('calc'),
            send_A_ts=monitor._timestamps.get('send_A'),
            send_B_ts=monitor._timestamps.get('send_B'),
            ack_A_ts=monitor._timestamps.get('ack_A'),
            ack_B_ts=monitor._timestamps.get('ack_B'),
            spread_rate=Decimal('0.0010'),
            decision='ALLOWED',
            status='SUCCESS'
        )
        monitor.record_decision(record)

        # 7. 获取统计
        stats = monitor.get_stats_summary()

        assert stats['total_checks'] > 0

        # 8. 导出数据（实际文件会在data/目录创建）
        # 这里只验证方法可以调用
        monitor.export_performance_data()
        monitor.export_decision_records()


class TestPerformanceMonitoringWithRealWorldScenario:
    """测试真实世界场景"""

    def test_high_latency_warning(self, monitor):
        """测试高延迟警告"""
        # 记录高延迟
        monitor.record_tick_to_trade_latency(
            time.time() * 1000,
            time.time() * 1000 + 15.0  # 15ms，超过10ms阈值
        )

        # 验证延迟被记录
        assert len(monitor._stats['tick_to_trade_latencies']) == 1

    def test_concurrent_gap_tracking(self, monitor):
        """测试并发间隔跟踪"""
        send_a = time.time() * 1000
        send_b = send_a + 3.21  # 3.21ms间隔

        monitor.record_concurrent_send_gap(send_a, send_b)

        assert len(monitor._stats['concurrent_gaps']) == 1
        # 使用近似比较，因为时间戳有浮点精度问题
        assert monitor._stats['concurrent_gaps'][0] == pytest.approx(3.21, abs=0.01)

    def test_data_freshness_tracking(self, monitor):
        """测试数据新鲜度跟踪"""
        current_time = time.time() * 1000
        data_ts = current_time - 100  # 100ms前

        result = monitor.check_data_freshness('extended', data_ts, current_time)

        assert result.is_fresh is True
        assert result.data_age_ms == 100


class TestPerformanceMonitoringLogging:
    """测试性能监控日志"""

    def test_stats_summary_logging(self, monitor, caplog):
        """测试统计摘要日志"""
        import logging
        caplog.set_level(logging.INFO)

        # 添加一些统计数据
        monitor._stats['tick_to_trade_latencies'] = [8.0, 10.0, 12.0]
        monitor._stats['total_checks'] = 100

        # 记录统计摘要
        monitor.log_stats_summary()

        # 验证日志包含统计信息
        assert '性能监控统计' in caplog.text or '统计报告' in caplog.text


class TestPerformanceMonitoringMaxRecords:
    """测试最大记录限制"""

    def test_max_records_limit(self, monitor):
        """测试最大记录限制"""
        # 记录超过最大限制的决策
        for i in range(15000):  # 超过10000限制
            record = TradeOperationRecord(
                timestamp=time.time(),
                operation_type='OPEN',
                exchange='BOTH',
                decision='ALLOWED',
                status='SUCCESS'
            )
            monitor.record_decision(record)

        # 验证记录数量被限制
        assert len(monitor._decision_records) <= 10000
