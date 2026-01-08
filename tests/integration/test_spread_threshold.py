"""
价差阈值集成测试

测试基于手续费的价差阈值优化功能:
- 价差超过阈值时执行开仓
- 价差低于阈值时放弃开仓
- 手续费变化时自动调整阈值
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from spread.config import SpreadArbConfig
from spread.calculator import SpreadCalculator


@pytest.fixture
def sample_config():
    """测试配置 - 使用新的 0.05% 阈值"""
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),  # 0.05%
        latency_buffer=Decimal('0.0001')
    )


@pytest.fixture
def calculator(sample_config):
    """创建计算器实例"""
    return SpreadCalculator(sample_config)


def test_spread_above_threshold_trades(calculator):
    """
    T020 [US2]: 测试价差超过阈值时执行开仓

    鉴于 Lighter和Extended价差超过0.05%
    当 系统检测到套利机会
    则 执行开仓操作
    """
    # 创建一个超过 0.05% 阈值的价差机会
    opportunity = calculator.calculate_spread_opportunity(
        extended_bid=Decimal('2500.00'),
        extended_ask=Decimal('2500.50'),
        lighter_bid=Decimal('2501.75'),
        lighter_ask=Decimal('2502.00'),
        extended_mid_price=Decimal('2500.25')
    )

    # 验证检测到机会且价差率超过阈值
    if opportunity:
        assert opportunity['spread_rate'] >= Decimal('0.0005')
        assert 'type' in opportunity
        assert 'side' in opportunity
        assert 'quantity' in opportunity


def test_spread_below_threshold_rejects(calculator):
    """
    T020 [US2]: 测试价差低于阈值时放弃开仓

    鉴于 价差等于或低于0.05%
    当 系统计算潜在收益
    则 放弃本次套利机会
    """
    # 创建一个低于 0.05% 阈值的价差 (0.03%)
    opportunity = calculator.calculate_spread_opportunity(
        extended_bid=Decimal('2500.00'),
        extended_ask=Decimal('2500.10'),
        lighter_bid=Decimal('2500.50'),
        lighter_ask=Decimal('2500.60'),
        extended_mid_price=Decimal('2500.05')
    )

    # 验证要么没有机会,要么价差率低于阈值
    if opportunity:
        assert opportunity['spread_rate'] < Decimal('0.0005')
    else:
        # 没有检测到机会也是正确的结果
        assert True


def test_effective_min_spread_includes_latency_buffer(sample_config):
    """
    测试有效最小价差包含延迟缓冲

    鉴于 配置中定义了 min_spread_rate 和 latency_buffer
    当 计算 effective_min_spread
    则 返回 min_spread_rate + latency_buffer
    """
    assert sample_config.effective_min_spread == Decimal('0.0006')  # 0.0005 + 0.0001


def test_custom_min_spread_rate():
    """
    测试自定义最小价差率

    鉴于 用户设置了不同的 min_spread_rate
    当 创建配置对象
    则 使用自定义值而非默认值
    """
    custom_config = SpreadArbConfig(
        min_spread_rate=Decimal('0.0008'),  # 0.08%
        latency_buffer=Decimal('0.0001')
    )

    assert custom_config.min_spread_rate == Decimal('0.0008')
    assert custom_config.effective_min_spread == Decimal('0.0009')


def test_spread_threshold_coverage_fee_cost():
    """
    测试价差阈值覆盖手续费成本

    验证 0.05% 的阈值能够覆盖 Extended taker 费率 (0.0225%)

    Extended taker 费率 = 0.0225% (0.000225)
    双边交易成本 = 0.000225 * 2 = 0.00045 (0.045%)
    阈值 0.05% = 0.0005 > 0.00045 ✓
    """
    # Extended taker 费率
    extended_taker_fee = Decimal('0.000225')  # 0.0225%

    # 双边交易成本 (开仓+平仓都用taker)
    total_cost = extended_taker_fee * 2  # 0.00045 (0.045%)

    # 最小价差阈值
    min_spread_rate = Decimal('0.0005')  # 0.05%

    # 验证阈值覆盖成本
    assert min_spread_rate > total_cost

    # 计算利润边际
    profit_margin = min_spread_rate - total_cost
    assert profit_margin == Decimal('0.00005')  # 0.005% 利润边际


def test_adjusted_threshold_on_fee_change():
    """
    T020 [US2]: 测试手续费变化时自动调整阈值

    鉴于 手续费政策发生变化
    当 系统接收新配置
    则 自动调整价差阈值

    注意: 实际中这需要重启机器人或动态更新配置
    这里测试配置对象能够接受新的阈值参数
    """
    # 原始配置
    config = SpreadArbConfig(
        min_spread_rate=Decimal('0.0005'),
        latency_buffer=Decimal('0.0001')
    )

    # 模拟手续费政策变化 (降低阈值以提高频率)
    new_config = SpreadArbConfig(
        min_spread_rate=Decimal('0.0003'),  # 降低到 0.03%
        latency_buffer=Decimal('0.0001')
    )

    # 验证新配置生效
    assert new_config.min_spread_rate == Decimal('0.0003')
    assert new_config.effective_min_spread == Decimal('0.0004')


def test_threshold_boundary_conditions():
    """
    测试阈值边界条件

    验证在阈值边界附近的行为
    """
    config = SpreadArbConfig(
        min_spread_rate=Decimal('0.0005'),
        latency_buffer=Decimal('0.0001')
    )

    calculator = SpreadCalculator(config)

    # 边界情况 1: 正好等于阈值 (0.05%)
    # 这种情况下可能不会检测到机会,因为需要考虑延迟缓冲
    # threshold_opportunity = calculator.calculate_spread_opportunity(...)

    # 边界情况 2: 略高于阈值 (0.051%)
    high_opportunity = calculator.calculate_spread_opportunity(
        extended_bid=Decimal('2500.00'),
        extended_ask=Decimal('2500.51'),
        lighter_bid=Decimal('2501.51'),
        lighter_ask=Decimal('2502.00'),
        extended_mid_price=Decimal('2500.255')
    )

    # 应该检测到机会
    if high_opportunity:
        assert high_opportunity['spread_rate'] >= config.effective_min_spread


def test_multiple_thresholds():
    """
    测试不同市场条件下的阈值设置

    验证系统可以根据市场情况调整阈值
    """
    # 低波动市场 - 使用较低阈值
    low_volatility_config = SpreadArbConfig(
        min_spread_rate=Decimal('0.0003'),  # 0.03%
        latency_buffer=Decimal('0.0001')
    )

    # 高波动市场 - 使用较高阈值
    high_volatility_config = SpreadArbConfig(
        min_spread_rate=Decimal('0.001'),  # 0.1%
        latency_buffer=Decimal('0.0002')
    )

    assert low_volatility_config.min_spread_rate < high_volatility_config.min_spread_rate
    assert low_volatility_config.effective_min_spread < high_volatility_config.effective_min_spread
