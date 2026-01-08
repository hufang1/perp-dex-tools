"""
配置参数单元测试

测试配置类功能:
- min_spread_rate 配置验证
- from_env() 方法正确加载环境变量
"""

import os
import pytest
from decimal import Decimal
from spread.config import SpreadArbConfig


@pytest.mark.env
class TestConfigValidation:
    """测试配置验证逻辑"""

    def test_min_spread_rate_validation(self):
        """
        T018 [US2]: 测试 min_spread_rate 配置验证

        鉴于 配置对象被创建
        当 min_spread_rate 不满足验证规则
        则 抛出 ValueError 异常
        """
        # 测试 min_spread_rate <= 0
        with pytest.raises(ValueError, match="min_spread_rate 必须大于 0"):
            SpreadArbConfig(min_spread_rate=Decimal('0'))

        with pytest.raises(ValueError, match="min_spread_rate 必须大于 0"):
            SpreadArbConfig(min_spread_rate=Decimal('-0.001'))

    def test_min_spread_rate_greater_than_latency_buffer(self):
        """
        T021 [US2]: 测试 min_spread_rate 必须大于 latency_buffer

        鉴于 配置对象被创建
        当 min_spread_rate <= latency_buffer
        则 抛出 ValueError 异常
        """
        with pytest.raises(ValueError, match="min_spread_rate 必须大于 latency_buffer"):
            SpreadArbConfig(
                min_spread_rate=Decimal('0.0001'),
                latency_buffer=Decimal('0.0001')
            )

        # 测试有效的配置应该成功
        config = SpreadArbConfig(
            min_spread_rate=Decimal('0.0005'),
            latency_buffer=Decimal('0.0001')
        )
        assert config.min_spread_rate == Decimal('0.0005')
        assert config.effective_min_spread == Decimal('0.0006')

    def test_profit_target_rate_validation(self):
        """
        T035 [US3]: 测试 profit_target_rate 配置验证

        鉴于 配置对象被创建
        当 profit_target_rate <= 0
        则 抛出 ValueError 异常
        """
        with pytest.raises(ValueError, match="profit_target_rate 必须大于 0"):
            SpreadArbConfig(profit_target_rate=Decimal('0'))

        # 有效配置应该成功
        config = SpreadArbConfig(profit_target_rate=Decimal('0.0005'))
        assert config.profit_target_rate == Decimal('0.0005')

    def test_time_close_threshold_validation(self):
        """
        T035 [US3]: 测试 time_close_threshold 配置验证

        鉴于 配置对象被创建
        当 time_close_threshold <= 0
        则 抛出 ValueError 异常
        """
        with pytest.raises(ValueError, match="time_close_threshold 必须大于 0"):
            SpreadArbConfig(time_close_threshold=0)

        with pytest.raises(ValueError, match="time_close_threshold 必须大于 0"):
            SpreadArbConfig(time_close_threshold=-10)

    def test_max_holding_time_greater_than_time_close_threshold(self):
        """
        T035 [US3]: 测试 max_holding_time 必须大于 time_close_threshold

        鉴于 配置对象被创建
        当 max_holding_time <= time_close_threshold
        则 抛出 ValueError 异常
        """
        with pytest.raises(ValueError, match="max_holding_time 必须大于 time_close_threshold"):
            SpreadArbConfig(
                time_close_threshold=60,
                max_holding_time=60
            )

        with pytest.raises(ValueError, match="max_holding_time 必须大于 time_close_threshold"):
            SpreadArbConfig(
                time_close_threshold=60,
                max_holding_time=30
            )

        # 有效配置应该成功
        config = SpreadArbConfig(
            time_close_threshold=60,
            max_holding_time=300
        )
        assert config.time_close_threshold == 60
        assert config.max_holding_time == 300


@pytest.mark.env
class TestConfigFromEnv:
    """测试环境变量加载功能"""

    def test_from_env_default_values(self):
        """
        T019 [US2]: 测试 from_env() 方法默认值

        鉴于 未设置任何环境变量
        当 调用 from_env() 方法
        则 返回带有默认值的配置对象
        """
        # 清除相关环境变量
        for key in ['MIN_SPREAD_RATE', 'PROFIT_TARGET_RATE', 'TIME_CLOSE_THRESHOLD',
                   'MAX_HOLDING_TIME', 'UNHEDGED_TIMEOUT']:
            os.environ.pop(key, None)

        config = SpreadArbConfig.from_env()

        # 验证默认值
        assert config.min_spread_rate == Decimal('0.0005')
        assert config.profit_target_rate == Decimal('0.0005')
        assert config.time_close_threshold == 60
        assert config.max_holding_time == 300
        assert config.unhedged_position_timeout == 60

    def test_from_env_loads_min_spread_rate(self):
        """
        T022 [US2]: 测试 from_env() 加载 MIN_SPREAD_RATE 环境变量

        鉴于 设置了 MIN_SPREAD_RATE 环境变量
        当 调用 from_env() 方法
        则 使用环境变量值而非默认值
        """
        os.environ['MIN_SPREAD_RATE'] = '0.0008'
        try:
            config = SpreadArbConfig.from_env()
            assert config.min_spread_rate == Decimal('0.0008')
        finally:
            os.environ.pop('MIN_SPREAD_RATE', None)

    def test_from_env_loads_profit_target_rate(self):
        """
        T036 [US3]: 测试 from_env() 加载 PROFIT_TARGET_RATE 环境变量

        鉴于 设置了 PROFIT_TARGET_RATE 环境变量
        当 调用 from_env() 方法
        则 使用环境变量值
        """
        os.environ['PROFIT_TARGET_RATE'] = '0.001'
        try:
            config = SpreadArbConfig.from_env()
            assert config.profit_target_rate == Decimal('0.001')
        finally:
            os.environ.pop('PROFIT_TARGET_RATE', None)

    def test_from_env_loads_time_close_threshold(self):
        """
        T036 [US3]: 测试 from_env() 加载 TIME_CLOSE_THRESHOLD 环境变量

        鉴于 设置了 TIME_CLOSE_THRESHOLD 环境变量
        当 调用 from_env() 方法
        则 使用环境变量值
        """
        os.environ['TIME_CLOSE_THRESHOLD'] = '120'
        try:
            config = SpreadArbConfig.from_env()
            assert config.time_close_threshold == 120
        finally:
            os.environ.pop('TIME_CLOSE_THRESHOLD', None)

    def test_from_env_loads_max_holding_time(self):
        """
        T036 [US3]: 测试 from_env() 加载 MAX_HOLDING_TIME 环境变量

        鉴于 设置了 MAX_HOLDING_TIME 环境变量
        当 调用 from_env() 方法
        则 使用环境变量值
        """
        os.environ['MAX_HOLDING_TIME'] = '600'
        try:
            config = SpreadArbConfig.from_env()
            assert config.max_holding_time == 600
        finally:
            os.environ.pop('MAX_HOLDING_TIME', None)

    def test_from_env_loads_unhedged_timeout(self):
        """
        T036 [US3]: 测试 from_env() 加载 UNHEDGED_TIMEOUT 环境变量

        鉴于 设置了 UNHEDGED_TIMEOUT 环境变量
        当 调用 from_env() 方法
        则 使用环境变量值
        """
        os.environ['UNHEDGED_TIMEOUT'] = '120'
        try:
            config = SpreadArbConfig.from_env()
            assert config.unhedged_position_timeout == 120
        finally:
            os.environ.pop('UNHEDGED_TIMEOUT', None)

    def test_from_env_multiple_variables(self):
        """
        测试同时加载多个环境变量
        """
        env_vars = {
            'MIN_SPREAD_RATE': '0.0006',
            'PROFIT_TARGET_RATE': '0.0008',
            'TIME_CLOSE_THRESHOLD': '90',
            'MAX_HOLDING_TIME': '400',
            'UNHEDGED_TIMEOUT': '45'
        }

        for key, value in env_vars.items():
            os.environ[key] = value

        try:
            config = SpreadArbConfig.from_env()
            assert config.min_spread_rate == Decimal('0.0006')
            assert config.profit_target_rate == Decimal('0.0008')
            assert config.time_close_threshold == 90
            assert config.max_holding_time == 400
            assert config.unhedged_position_timeout == 45
        finally:
            for key in env_vars:
                os.environ.pop(key, None)


class TestConfigCalculations:
    """测试配置计算属性"""

    def test_effective_min_spread_calculation(self):
        """
        测试 effective_min_spread 计算逻辑

        鉴于 配置对象存在
        当 访问 effective_min_spread 属性
        则 返回 min_spread_rate + latency_buffer
        """
        config = SpreadArbConfig(
            min_spread_rate=Decimal('0.0005'),
            latency_buffer=Decimal('0.0001')
        )

        assert config.effective_min_spread == Decimal('0.0006')

    def test_effective_min_spread_with_different_values(self):
        """
        测试不同配置值的 effective_min_spread 计算
        """
        test_cases = [
            (Decimal('0.001'), Decimal('0.0002'), Decimal('0.0012')),
            (Decimal('0.002'), Decimal('0.0005'), Decimal('0.0025')),
            (Decimal('0.0003'), Decimal('0.00005'), Decimal('0.00035')),
        ]

        for min_spread, latency, expected in test_cases:
            config = SpreadArbConfig(
                min_spread_rate=min_spread,
                latency_buffer=latency
            )
            assert config.effective_min_spread == expected
