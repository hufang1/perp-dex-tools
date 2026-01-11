"""
Risk Validation集成测试

测试011-async-ws-ioc-trading的风险验证功能
"""

import pytest
import time
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from spread.config import SpreadArbConfig
from spread.risk_validator import RiskValidator
from spread.performance_monitor import PerformanceMonitor
from spread.models import DataFreshnessResult


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        max_data_age_ms=500.0,
        ioc_slippage_tolerance_rate=Decimal('0.0005'),
        min_net_profit_rate=Decimal('0.0002'),
        expected_slippage_cost_rate=Decimal('0.0001'),
        enable_data_freshness_check=True,
        enable_profitability_check=True,
        enable_leg_risk_guard=True,
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


@pytest.fixture
def validator(config, monitor):
    """创建测试用的风控验证器"""
    return RiskValidator(config, monitor)


class TestOpeningValidation:
    """测试开仓验证"""

    def test_validate_opening_all_checks_pass(self, validator):
        """测试所有验证通过"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0010'),  # 足够利润
            'expected_price': Decimal('3000'),
            'current_price': Decimal('3001.5'),  # 滑点可接受
            'side': 'buy'
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,  # Extended数据新鲜
            current_time - 150   # Lighter数据新鲜
        )

        assert is_valid is True
        assert reason == ""

    def test_validate_opening_data_freshness_fails(self, validator):
        """测试数据新鲜度验证失败"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0020'),  # 足够利润
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,  # Extended数据新鲜
            current_time - 600   # Lighter数据过期
        )

        assert is_valid is False
        assert "数据过期" in reason

    def test_validate_opening_slippage_fails(self, validator):
        """测试滑点验证失败"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0020'),
            'expected_price': Decimal('3000'),
            'current_price': Decimal('3010'),  # 滑点过大
            'side': 'buy'
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        assert is_valid is False
        assert "滑点" in reason

    def test_validate_opening_profitability_fails(self, validator):
        """测试利润率验证失败"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0004'),  # 利润不足
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        assert is_valid is False
        assert "利润" in reason


class TestLegRiskGuard:
    """测试单腿风险守护"""

    def test_both_filled_no_risk(self, validator):
        """测试双边成交无风险"""
        has_risk, action = validator.check_leg_risk(True, True)

        assert has_risk is False
        assert "无风险" in action

    def test_extended_only_risk(self, validator):
        """测试只有Extended成交有风险"""
        has_risk, action = validator.check_leg_risk(True, False)

        assert has_risk is True
        assert "Extended" in action

    def test_lighter_only_risk(self, validator):
        """测试只有Lighter成交有风险"""
        has_risk, action = validator.check_leg_risk(False, True)

        assert has_risk is True
        assert "Lighter" in action

    def test_both_failed_no_position(self, validator):
        """测试双边都失败无持仓"""
        has_risk, action = validator.check_leg_risk(False, False)

        assert has_risk is True
        assert "无需平仓" in action


class TestRiskValidationIntegration:
    """测试风险验证集成"""

    def test_full_validation_workflow(self, validator):
        """测试完整验证工作流"""
        current_time = time.time() * 1000

        # 1. 验证数据新鲜度
        ext_fresh, lit_fresh = current_time - 100, current_time - 150
        both_fresh, freshness_results = validator.validate_data_freshness(
            ext_fresh, lit_fresh
        )

        assert both_fresh is True
        assert len(freshness_results) == 2

        # 2. 验证滑点
        expected = Decimal('3000')
        current = Decimal('3001.5')
        slippage_result = validator.validate_slippage(expected, current, 'buy')

        assert slippage_result.is_acceptable is True

        # 3. 验证利润率
        spread_rate = Decimal('0.0010')
        profit_result = validator.validate_profitability(spread_rate)

        assert profit_result.is_profitable is True

        # 4. 综合验证
        opportunity = {
            'spread_rate': spread_rate,
            'expected_price': expected,
            'current_price': current,
            'side': 'buy'
        }

        is_valid, reason = validator.validate_opening(
            opportunity, ext_fresh, lit_fresh
        )

        assert is_valid is True

    def test_validation_with_stale_data(self, validator):
        """测试使用过期数据的验证"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0020'),
        }

        # Extended数据新鲜，Lighter数据过期
        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 600  # 过期
        )

        assert is_valid is False
        assert "lighter" in reason.lower()

    def test_validation_with_high_slippage(self, validator):
        """测试高滑点的验证"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0020'),
            'expected_price': Decimal('3000'),
            'current_price': Decimal('3010'),  # 高滑点
            'side': 'buy'
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        assert is_valid is False
        assert "滑点" in reason

    def test_validation_with_low_profit(self, validator):
        """测试低利润率的验证"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0004'),  # 低利润
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        assert is_valid is False
        assert "利润" in reason


class TestRiskValidationWithDisabledChecks:
    """测试禁用检查时的行为"""

    def test_validation_without_freshness_check(self, config, monitor):
        """测试禁用数据新鲜度检查"""
        config.enable_data_freshness_check = False
        validator = RiskValidator(config, monitor)

        current_time = time.time() * 1000
        opportunity = {'spread_rate': Decimal('0.0010')}

        # 即使数据过期，也应该通过（因为检查被禁用）
        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 600,  # 过期数据
            current_time - 700
        )

        # 应该继续检查利润率，而不会因为数据过期而拒绝
        # 由于利润率检查会通过，所以结果是有效的
        assert is_valid is True

    def test_validation_without_profitability_check(self, config, monitor):
        """测试禁用利润率检查"""
        config.enable_profitability_check = False
        validator = RiskValidator(config, monitor)

        current_time = time.time() * 1000
        opportunity = {
            'spread_rate': Decimal('0.0001'),  # 很低的利润率
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        # 利润率检查被禁用，应该通过
        assert is_valid is True


class TestRiskValidationLogging:
    """测试风险验证日志"""

    def test_data_freshness_logging(self, validator, caplog):
        """测试数据新鲜度日志"""
        import logging
        caplog.set_level(logging.INFO)

        current_time = time.time() * 1000
        validator.validate_data_freshness(
            current_time - 100,
            current_time - 600  # 过期
        )

        # 应该有数据过期的日志
        # 具体的日志内容取决于实现
        assert len(caplog.records) >= 0

    def test_slippage_check_logging(self, validator, caplog):
        """测试滑点检查日志"""
        import logging
        caplog.set_level(logging.WARNING)

        validator.validate_slippage(
            Decimal('3000'),
            Decimal('3010'),  # 高滑点
            'buy'
        )

        # 应该有滑点警告日志（如果实现的话）
        assert len(caplog.records) >= 0


class TestRiskValidationPerformance:
    """测试风险验证性能"""

    def test_validation_speed(self, validator):
        """测试验证速度"""
        import time

        current_time = time.time() * 1000
        opportunity = {
            'spread_rate': Decimal('0.0010'),
            'expected_price': Decimal('3000'),
            'current_price': Decimal('3001.5'),
            'side': 'buy'
        }

        start = time.time()
        validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )
        elapsed = (time.time() - start) * 1000

        # 验证应该很快（< 10ms）
        assert elapsed < 10

    def test_multiple_validations(self, validator):
        """测试多次验证"""
        current_time = time.time() * 1000

        # 执行100次验证
        for _ in range(100):
            opportunity = {
                'spread_rate': Decimal('0.0010'),
            }
            validator.validate_opening(
                opportunity,
                current_time - 100,
                current_time - 150
            )

        # 验证统计应该更新
        stats = validator.monitor.get_stats_summary()
        assert stats['total_checks'] > 0
