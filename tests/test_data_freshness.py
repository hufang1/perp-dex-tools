"""
数据新鲜度检查测试

测试012-dual-leg-concurrency的数据新鲜度熔断功能
"""

import pytest
import time
from spread.config import SpreadArbConfig
from spread.performance_monitor import PerformanceMonitor


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        max_data_age_ms=500,  # 500ms阈值
        enable_console_warnings=True
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


class TestDataFreshness:
    """测试数据新鲜度检查（T059-T061）"""

    def test_data_freshness_accept_under_500ms(self, monitor):
        """T059: 测试接受新鲜数据（<500ms）"""
        current_time = time.time() * 1000
        data_timestamp = current_time - 300  # 300ms前（新鲜）

        result = monitor.check_data_freshness(
            exchange='extended',
            data_timestamp=data_timestamp,
            current_time=current_time
        )

        assert result.is_fresh is True
        assert result.data_age_ms == 300
        assert result.data_age_ms < 500

    def test_data_freshness_reject_over_500ms(self, monitor):
        """T060: 测试拒绝过期数据（>500ms）"""
        current_time = time.time() * 1000
        data_timestamp = current_time - 800  # 800ms前（过期）

        result = monitor.check_data_freshness(
            exchange='extended',
            data_timestamp=data_timestamp,
            current_time=current_time
        )

        assert result.is_fresh is False
        assert result.data_age_ms == 800
        assert result.data_age_ms > 500

    def test_data_freshness_both_exchanges(self, monitor):
        """T061: 测试两个交易所的数据新鲜度检查"""
        current_time = time.time() * 1000
        extended_ts = current_time - 250  # Extended新鲜
        lighter_ts = current_time - 600   # Lighter过期

        both_fresh, results = monitor.check_both_data_freshness(
            extended_ts=extended_ts,
            lighter_ts=lighter_ts,
            current_time=current_time
        )

        # Extended应该新鲜，Lighter应该过期
        assert both_fresh is False
        assert results[0].is_fresh is True   # Extended
        assert results[1].is_fresh is False  # Lighter
        assert results[0].exchange == 'extended'
        assert results[1].exchange == 'lighter'

    def test_data_freshness_exactly_500ms(self, monitor):
        """测试恰好500ms边界情况"""
        current_time = time.time() * 1000
        data_timestamp = current_time - 500  # 恰好500ms

        result = monitor.check_data_freshness(
            exchange='lighter',
            data_timestamp=data_timestamp,
            current_time=current_time
        )

        # 500ms应该被认为是新鲜的（<= 阈值）
        assert result.is_fresh is True
        assert result.data_age_ms == 500

    def test_data_freshness_invalid_exchange(self, monitor):
        """测试无效的交易所名称"""
        with pytest.raises(ValueError):
            monitor.check_data_freshness(
                exchange='invalid_exchange',
                data_timestamp=time.time() * 1000,
                current_time=time.time() * 1000
            )

    def test_data_freshness_both_fresh(self, monitor):
        """测试双边数据都新鲜"""
        current_time = time.time() * 1000
        extended_ts = current_time - 200  # Extended新鲜
        lighter_ts = current_time - 300   # Lighter新鲜

        both_fresh, results = monitor.check_both_data_freshness(
            extended_ts=extended_ts,
            lighter_ts=lighter_ts,
            current_time=current_time
        )

        assert both_fresh is True
        assert results[0].is_fresh is True
        assert results[1].is_fresh is True

    def test_data_freshness_both_stale(self, monitor):
        """测试双边数据都过期"""
        current_time = time.time() * 1000
        extended_ts = current_time - 1000  # Extended过期
        lighter_ts = current_time - 800    # Lighter过期

        both_fresh, results = monitor.check_both_data_freshness(
            extended_ts=extended_ts,
            lighter_ts=lighter_ts,
            current_time=current_time
        )

        assert both_fresh is False
        assert results[0].is_fresh is False
        assert results[1].is_fresh is False


class TestDataFreshnessIntegration:
    """集成测试：数据新鲜度在交易流程中的作用"""

    def test_should_reject_when_data_stale(self, monitor):
        """测试当数据过期时应该拒绝交易"""
        current_time = time.time() * 1000
        stale_data_ts = current_time - 1000  # 1秒前的数据

        result = monitor.check_data_freshness(
            exchange='extended',
            data_timestamp=stale_data_ts,
            current_time=current_time
        )

        # 过期数据应该导致拒绝
        assert result.is_fresh is False

    def test_statistics_tracking(self, monitor):
        """测试统计数据跟踪"""
        current_time = time.time() * 1000

        # 检查几次新鲜数据
        for i in range(3):
            ts = current_time - 100 * (i + 1)
            monitor.check_data_freshness('extended', ts, current_time)

        # 检查一次过期数据
        monitor.check_data_freshness('lighter', current_time - 1000, current_time)

        stats = monitor.get_stats_summary()

        assert stats['total_checks'] == 4
        assert stats['stale_data_count'] == 1
