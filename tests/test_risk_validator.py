"""
RiskValidator单元测试

测试011-async-ws-ioc-trading的风控验证器功能
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


class TestRiskValidatorBasics:
    """测试风控验证器基础功能"""

    def test_initialization(self, config, monitor):
        """测试初始化"""
        validator = RiskValidator(config, monitor)
        assert validator.config == config
        assert validator.monitor == monitor

    def test_initialization_with_logger(self, config, monitor):
        """测试带logger的初始化"""
        import logging
        logger = logging.getLogger('test')
        validator = RiskValidator(config, monitor, logger)
        assert validator.logger == logger


class TestValidateOpening:
    """测试开仓前综合验证"""

    def test_validate_opening_all_pass(self, validator):
        """测试所有验证通过"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0010'),  # 足够利润
            'expected_price': Decimal('3000'),
            'current_price': Decimal('3001.5'),
            'side': 'buy'
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,  # Extended数据新鲜
            current_time - 150   # Lighter数据新鲜
        )

        assert is_valid is True
        assert reason == ""

    def test_validate_opening_stale_data(self, validator):
        """测试数据过期拒绝"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0020'),
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,  # Extended数据新鲜
            current_time - 600   # Lighter数据过期（>500ms）
        )

        assert is_valid is False
        assert "数据过期" in reason
        assert "lighter" in reason.lower() or "600" in reason

    def test_validate_opening_slippage_rejection(self, validator):
        """测试滑点超限拒绝"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0020'),
            'expected_price': Decimal('3000'),
            'current_price': Decimal('3010'),  # 滑点0.33%，超过0.05%阈值
            'side': 'buy'
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        assert is_valid is False
        assert "滑点超限" in reason

    def test_validate_opening_profit_rejection(self, validator):
        """测试利润不足拒绝"""
        current_time = time.time() * 1000

        opportunity = {
            'spread_rate': Decimal('0.0004'),  # 0.04%，扣除成本后不足0.02%
        }

        is_valid, reason = validator.validate_opening(
            opportunity,
            current_time - 100,
            current_time - 150
        )

        assert is_valid is False
        assert "利润不足" in reason


class TestValidateDataFreshness:
    """测试数据新鲜度验证"""

    def test_validate_data_freshness_both_fresh(self, validator):
        """测试双边数据都新鲜"""
        current_time = time.time() * 1000
        ext_ts = current_time - 100
        lit_ts = current_time - 150

        both_fresh, results = validator.validate_data_freshness(ext_ts, lit_ts)

        assert both_fresh is True
        assert len(results) == 2
        assert all(r.is_fresh for r in results)

    def test_validate_data_freshness_one_stale(self, validator):
        """测试一边数据过期"""
        current_time = time.time() * 1000
        ext_ts = current_time - 100
        lit_ts = current_time - 600  # 过期

        both_fresh, results = validator.validate_data_freshness(ext_ts, lit_ts)

        assert both_fresh is False
        assert results[0].is_fresh is True
        assert results[1].is_fresh is False


class TestValidateSlippage:
    """测试滑点验证"""

    def test_validate_slippage_acceptable(self, validator):
        """测试滑点可接受"""
        expected = Decimal('3000')
        current = Decimal('3001.5')  # 0.05%滑点

        result = validator.validate_slippage(expected, current, 'buy')

        assert result.is_acceptable is True
        assert result.side == 'buy'

    def test_validate_slippage_unacceptable(self, validator):
        """测试滑点不可接受"""
        expected = Decimal('3000')
        current = Decimal('3010')  # 0.33%滑点

        result = validator.validate_slippage(expected, current, 'sell')

        assert result.is_acceptable is False


class TestValidateProfitability:
    """测试利润率验证"""

    def test_validate_profitability_profitable(self, validator):
        """测试利润率足够"""
        spread_rate = Decimal('0.0010')  # 0.10%

        result = validator.validate_profitability(spread_rate)

        assert result.is_profitable is True

    def test_validate_profitability_not_profitable(self, validator):
        """测试利润率不足"""
        spread_rate = Decimal('0.0004')  # 0.04%

        result = validator.validate_profitability(spread_rate)

        assert result.is_profitable is False
        assert result.decision == "拒绝开仓（利润不足）"


class TestCheckLegRisk:
    """测试单腿持仓风险检测"""

    def test_check_leg_risk_both_filled(self, validator):
        """测试双边成交"""
        has_risk, action = validator.check_leg_risk(True, True)

        assert has_risk is False
        assert action == "双边成交，无风险"

    def test_check_leg_risk_extended_only(self, validator):
        """测试只有Extended成交"""
        has_risk, action = validator.check_leg_risk(True, False)

        assert has_risk is True
        assert action == "紧急平仓Extended"

    def test_check_leg_risk_lighter_only(self, validator):
        """测试只有Lighter成交"""
        has_risk, action = validator.check_leg_risk(False, True)

        assert has_risk is True
        assert action == "紧急平仓Lighter"

    def test_check_leg_risk_both_failed(self, validator):
        """测试双边都失败"""
        has_risk, action = validator.check_leg_risk(False, False)

        assert has_risk is True
        assert action == "双边失败，无需平仓"


class TestDisabledChecks:
    """测试禁用检查时的行为"""

    def test_validate_opening_without_freshness_check(self, config, monitor):
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

    def test_validate_opening_without_profitability_check(self, config, monitor):
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
