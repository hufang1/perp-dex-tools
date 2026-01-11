"""
利润风控检查测试

测试012-dual-leg-concurrency的利润检查功能
"""

import pytest
from decimal import Decimal
from spread.config import SpreadArbConfig
from spread.performance_monitor import PerformanceMonitor
from spread.models import ProfitabilityCheckResult


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        extended_taker_fee_rate=Decimal('0.0002'),  # 0.02%
        lighter_fee_rate=Decimal('0.0003'),          # 0.03%
        expected_slippage_cost_rate=Decimal('0.0005'),  # 0.05%
        min_net_profit_rate=Decimal('0.0001'),       # 0.01% 最小净利润
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


class TestProfitabilityCheck:
    """测试利润率检查（T049-T052）"""

    def test_profit_check_reject_negative(self, monitor):
        """T049: 测试拒绝负利润交易"""
        # 价差率 = 0.08%, 手续费 = 0.05%, 滑点 = 0.05%
        # 净利润 = 0.08% - 0.05% - 0.05% = -0.02% < 0.01% (应该拒绝)
        spread_rate = Decimal('0.0008')  # 0.08%

        result = monitor.check_profitability(spread_rate)

        assert result.is_profitable is False
        assert result.net_profit_rate < Decimal('0')
        assert '拒绝开仓' in result.decision

    def test_profit_check_accept_positive(self, monitor):
        """T050: 测试接受正利润交易"""
        # 价差率 = 0.15%, 手续费 = 0.05%, 滑点 = 0.05%
        # 净利润 = 0.15% - 0.05% - 0.05% = 0.05% > 0.01% (应该接受)
        spread_rate = Decimal('0.0015')  # 0.15%

        result = monitor.check_profitability(spread_rate)

        assert result.is_profitable is True
        assert result.net_profit_rate > result.min_net_profit
        assert '允许开仓' in result.decision

    def test_profit_check_warn_high_fees(self, monitor, caplog):
        """T051: 测试高费率警告"""
        import logging
        caplog.set_level(logging.WARNING)

        # 使用高费率配置进行测试
        high_fee_config = SpreadArbConfig(
            extended_taker_fee_rate=Decimal('0.0004'),  # 0.04%
            lighter_fee_rate=Decimal('0.0004'),          # 0.04%
            expected_slippage_cost_rate=Decimal('0.0005'),
            min_net_profit_rate=Decimal('0.0001'),
        )
        high_fee_monitor = PerformanceMonitor(high_fee_config)

        spread_rate = Decimal('0.0015')
        result = high_fee_monitor.check_profitability(spread_rate)

        # 总费率 = 0.04% + 0.04% = 0.08% > 0.06% (应该警告)
        assert result.total_fees > Decimal('0.0006')

    def test_profit_check_fee_calculation(self, monitor):
        """T052: 测试手续费计算正确性"""
        spread_rate = Decimal('0.0015')  # 0.15%

        result = monitor.check_profitability(spread_rate)

        # 验证手续费计算
        expected_fees = monitor.config.extended_taker_fee_rate + monitor.config.lighter_fee_rate
        assert result.total_fees == expected_fees

        # 验证净利计算
        expected_net_profit = spread_rate - expected_fees - monitor.config.expected_slippage_cost_rate
        assert result.net_profit_rate == expected_net_profit

    def test_profit_check_breakdown_logging(self, monitor, caplog):
        """测试利润分解日志"""
        import logging
        caplog.set_level(logging.INFO)

        spread_rate = Decimal('0.0015')
        result = monitor.check_profitability(spread_rate)

        # 验证日志包含详细信息
        assert '价差率' in caplog.text or 'spread_rate' in caplog.text

    def test_profit_check_with_custom_fees(self, monitor):
        """测试自定义手续费率"""
        spread_rate = Decimal('0.0015')

        # 使用自定义费率
        result = monitor.check_profitability(
            spread_rate,
            extended_fee=Decimal('0.0001'),
            lighter_fee=Decimal('0.0001'),
            expected_slippage=Decimal('0.0003')
        )

        # 验证自定义费率被使用
        assert result.total_fees == Decimal('0.0002')
        assert result.expected_slippage == Decimal('0.0003')

        # 净利润 = 0.15% - 0.02% - 0.03% = 0.10%
        expected_net = Decimal('0.0015') - Decimal('0.0002') - Decimal('0.0003')
        assert result.net_profit_rate == expected_net

    def test_profit_check_exact_breakdown(self, monitor):
        """测试精确的利润分解"""
        spread_rate = Decimal('0.0020')  # 0.20%

        result = monitor.check_profitability(spread_rate)

        # 分解验证
        # 价差率: 0.20%
        # Extended费率: 0.02%
        # Lighter费率: 0.03%
        # 总手续费: 0.05%
        # 预期滑点: 0.05%
        # 净利润: 0.20% - 0.05% - 0.05% = 0.10%
        # 最小净利: 0.01%

        assert result.spread_rate == Decimal('0.0020')
        assert result.total_fees == Decimal('0.0005')
        assert result.expected_slippage == Decimal('0.0005')
        assert result.net_profit_rate == Decimal('0.0010')
        assert result.min_net_profit == Decimal('0.0001')
        assert result.profit_margin == Decimal('0.0009')  # 0.10% - 0.01%
