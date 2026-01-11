"""
动态阈值管理器测试

测试AdaptiveThresholdManager的功能：
- 根据对冲成功率动态调整开仓阈值
- 在高成功率时使用降低阈值
- 在低成功率时使用安全阈值
"""

import logging
from decimal import Decimal

import pytest

from spread.config import SpreadArbConfig
from spread.adaptive_threshold_manager import AdaptiveThresholdManager
from spread.safety_monitor import SafetyMonitor


@pytest.fixture
def config():
    """创建配置实例"""
    return SpreadArbConfig()


@pytest.fixture
def safety_monitor(config):
    """创建安全监控器实例"""
    logger = logging.getLogger("test")
    return SafetyMonitor(config, logger)


@pytest.fixture
def adaptive_manager(config, safety_monitor):
    """创建动态阈值管理器实例"""
    return AdaptiveThresholdManager(config, safety_monitor)


class TestAdaptiveThresholdManager:
    """测试动态阈值管理器核心功能"""

    def test_get_effective_min_spread_with_default_config(self, adaptive_manager):
        """测试默认配置下的有效阈值（应该返回基础阈值）"""
        # 默认情况下adaptive_threshold_enabled=False
        min_spread = adaptive_manager.get_effective_min_spread_rate()
        # 应该返回配置的基础阈值
        assert min_spread == adaptive_manager.config.min_spread_rate

    def test_get_effective_min_spread_high_success_rate(self, adaptive_manager):
        """测试高成功率时使用降低阈值"""
        # 模拟高成功率（>90%）
        # 9次成功，1次失败 = 10%失败率，90%成功率
        for _ in range(9):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.1')

        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        min_spread = adaptive_manager.get_effective_min_spread_rate()

        # 高成功率时应该使用降低阈值(0.06%)
        assert min_spread == adaptive_manager.config.reduced_min_spread_rate

    def test_get_effective_min_spread_low_success_rate(self, adaptive_manager):
        """测试低成功率时使用安全阈值"""
        # 模拟低成功率（<80%）
        # 4次成功，6次失败 = 60%失败率，40%成功率
        for _ in range(4):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        for _ in range(6):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.6')

        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        min_spread = adaptive_manager.get_effective_min_spread_rate()

        # 低成功率时应该使用安全阈值(0.15%)
        assert min_spread == adaptive_manager.config.adaptive_min_spread_rate_safe

    def test_get_effective_min_spread_medium_success_rate(self, adaptive_manager):
        """测试中等成功率时使用中间值"""
        # 模拟中等成功率（80%-90%）
        # 8次成功，2次失败 = 20%失败率，80%成功率
        for _ in range(8):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        for _ in range(2):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.2')

        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        min_spread = adaptive_manager.get_effective_min_spread_rate()

        # 中等成功率时应该在降低阈值和安全阈值之间
        assert min_spread > adaptive_manager.config.reduced_min_spread_rate
        assert min_spread < adaptive_manager.config.adaptive_min_spread_rate_safe

    def test_should_enable_reduced_thresholds_high_success(self, adaptive_manager):
        """测试高成功率时应该启用降低阈值"""
        # 模拟高成功率
        for _ in range(9):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.1')
        adaptive_manager.safety_monitor.state.position_imbalance_rate = Decimal('0.05')

        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        should_enable = adaptive_manager.should_enable_reduced_thresholds()
        assert should_enable is True

    def test_should_enable_reduced_thresholds_low_success(self, adaptive_manager):
        """测试低成功率时不应该启用降低阈值"""
        # 模拟低成功率
        for _ in range(5):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        for _ in range(5):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.5')

        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        should_enable = adaptive_manager.should_enable_reduced_thresholds()
        assert should_enable is False

    def test_should_enable_reduced_thresholds_high_imbalance(self, adaptive_manager):
        """测试仓位失衡率高时不应该启用降低阈值"""
        # 模拟高成功率但高仓位失衡
        for _ in range(9):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.1')
        adaptive_manager.safety_monitor.state.position_imbalance_rate = Decimal('0.3')  # 30%失衡

        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        should_enable = adaptive_manager.should_enable_reduced_thresholds()
        assert should_enable is False

    def test_threshold_transition(self, adaptive_manager):
        """测试阈值切换逻辑"""
        # 启用动态阈值
        adaptive_manager.config.adaptive_threshold_enabled = True

        # 从低成功率开始
        for _ in range(5):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        for _ in range(5):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.5')

        min_spread_low = adaptive_manager.get_effective_min_spread_rate()

        # 提升到高成功率
        adaptive_manager.safety_monitor.state.recent_hedge_attempts.clear()
        for _ in range(9):
            adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(True)
        adaptive_manager.safety_monitor.state.recent_hedge_attempts.append(False)
        adaptive_manager.safety_monitor.state.hedge_failure_rate = Decimal('0.1')
        adaptive_manager.safety_monitor.state.position_imbalance_rate = Decimal('0.05')

        min_spread_high = adaptive_manager.get_effective_min_spread_rate()

        # 阈值应该降低
        assert min_spread_high < min_spread_low
