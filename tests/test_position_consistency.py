"""
仓位一致性验证单元测试

测试开仓后的仓位一致性验证功能
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from spread.models import PositionConsistencyCheck
from spread.spread_pair import SpreadPair


class TestPositionConsistencyCheck:
    """测试仓位一致性检查数据模型（001-fix-order-type - User Story 2）"""

    def test_position_consistency_check_creation(self):
        """
        测试：PositionConsistencyCheck对象创建

        场景：
        1. 创建仓位一致性检查对象
        2. 验证所有字段正确设置
        3. 验证字符串表示格式正确
        """
        check = PositionConsistencyCheck(
            is_consistent=True,
            extended_quantity=Decimal('0.01'),
            lighter_quantity=Decimal('0.01'),
            difference=Decimal('0'),
            difference_rate=0.0,
            threshold_exceeded=False
        )

        assert check.is_consistent is True
        assert check.extended_quantity == Decimal('0.01')
        assert check.lighter_quantity == Decimal('0.01')
        assert check.difference == Decimal('0')
        assert check.difference_rate == 0.0
        assert check.threshold_exceeded is False

        # 验证字符串表示
        str_repr = str(check)
        assert '✅ 一致' in str_repr
        assert '0.0100' in str_repr

    def test_position_inconsistency_detection(self):
        """
        测试：检测仓位不一致

        场景：
        1. Extended仓位0.01，Lighter仓位0.005
        2. 验证差异计算正确
        3. 验证不一致标记正确
        """
        check = PositionConsistencyCheck(
            is_consistent=False,
            extended_quantity=Decimal('0.01'),
            lighter_quantity=Decimal('0.005'),
            difference=Decimal('0.005'),
            difference_rate=0.5,  # 50%差异率
            threshold_exceeded=True
        )

        assert check.is_consistent is False
        assert check.difference == Decimal('0.005')
        assert check.difference_rate == 0.5
        assert check.threshold_exceeded is True

        # 验证字符串表示
        str_repr = str(check)
        assert '⚠️ 不一致' in str_repr

    def test_threshold_calculation(self):
        """
        测试：阈值计算逻辑

        场景：
        1. 绝对差异0.001 ETH（阈值边界）
        2. 差异率10%（阈值边界）
        3. 验证阈值判断逻辑
        """
        # 刚好在阈值上的情况
        check_at_threshold = PositionConsistencyCheck(
            is_consistent=True,
            extended_quantity=Decimal('0.01'),
            lighter_quantity=Decimal('0.009'),
            difference=Decimal('0.001'),
            difference_rate=0.1,  # 10%
            threshold_exceeded=False  # 刚好在阈值，不算超过
        )

        assert check_at_threshold.difference == Decimal('0.001')
        assert check_at_threshold.difference_rate == 0.1

        # 超过阈值的情况
        check_exceed = PositionConsistencyCheck(
            is_consistent=False,
            extended_quantity=Decimal('0.01'),
            lighter_quantity=Decimal('0.008'),
            difference=Decimal('0.002'),
            difference_rate=0.2,  # 20%
            threshold_exceeded=True
        )

        assert check_exceed.difference == Decimal('0.002')
        assert check_exceed.threshold_exceeded is True


class TestPositionConsistencyValidation:
    """测试仓位一致性验证逻辑"""

    def test_validate_after_hedge_success(self):
        """
        测试：对冲成功后验证仓位一致性

        场景：
        1. Extended成交0.01 ETH
        2. Lighter对冲成交0.01 ETH
        3. 验证仓位一致
        """
        extended_qty = Decimal('0.01')
        lighter_qty = Decimal('0.01')

        # 计算差异
        diff_qty = abs(extended_qty - lighter_qty)
        assert diff_qty == Decimal('0')

        # 计算差异率
        total_exposure = abs(extended_qty) + abs(lighter_qty)
        diff_rate = float(diff_qty / total_exposure) if total_exposure > 0 else 0.0

        assert diff_rate == 0.0

        # 检查阈值
        threshold = Decimal('0.001')
        rate_threshold = 0.1

        is_consistent = diff_qty <= threshold and diff_rate <= rate_threshold
        assert is_consistent is True

    def test_validate_detects_imbalance(self):
        """
        测试：检测到仓位失衡

        场景：
        1. Extended成交0.01 ETH
        2. Lighter仅成交0.009 ETH
        3. 检测到10%失衡（在阈值边界）
        """
        extended_qty = Decimal('0.01')
        lighter_qty = Decimal('0.009')

        # 计算差异
        diff_qty = abs(extended_qty - lighter_qty)
        assert diff_qty == Decimal('0.001')

        # 计算差异率
        total_exposure = abs(extended_qty) + abs(lighter_qty)
        diff_rate = float(diff_qty / total_exposure)
        expected_rate = 0.001 / 0.019  # ~5.26%

        assert abs(diff_rate - expected_rate) < 0.01

        # 检查阈值
        threshold = Decimal('0.001')
        rate_threshold = 0.1

        threshold_exceeded = diff_qty > threshold or diff_rate > rate_threshold
        # 差异数量刚好等于阈值，差异率小于阈值
        assert threshold_exceeded is False

    def test_severe_imbalance_detection(self):
        """
        测试：检测到严重仓位失衡

        场景：
        1. Extended成交0.21 ETH
        2. Lighter仅成交0.02 ETH
        3. 检测到严重失衡（>80%）
        """
        extended_qty = Decimal('0.21')
        lighter_qty = Decimal('0.02')

        # 计算差异
        diff_qty = abs(extended_qty - lighter_qty)
        assert diff_qty == Decimal('0.19')

        # 计算差异率
        total_exposure = abs(extended_qty) + abs(lighter_qty)
        diff_rate = float(diff_qty / total_exposure)
        expected_rate = 0.19 / 0.23  # ~82.6%

        assert abs(diff_rate - expected_rate) < 0.01

        # 检查阈值
        threshold = Decimal('0.001')
        rate_threshold = 0.1

        threshold_exceeded = diff_qty > threshold or diff_rate > rate_threshold
        assert threshold_exceeded is True


class TestPositionConsistencyLogging:
    """测试仓位一致性日志记录"""

    def test_consistent_logging_format(self):
        """
        测试：仓位一致时的日志格式

        场景：
        1. 仓位完全一致
        2. 验证日志格式包含必要信息
        """
        check = PositionConsistencyCheck(
            is_consistent=True,
            extended_quantity=Decimal('0.01'),
            lighter_quantity=Decimal('0.01'),
            difference=Decimal('0'),
            difference_rate=0.0,
            threshold_exceeded=False
        )

        log_str = str(check)
        assert '✅ 一致' in log_str
        assert '0.0100' in log_str
        assert '0.00%' in log_str

    def test_inconsistent_logging_format(self):
        """
        测试：仓位不一致时的日志格式

        场景：
        1. 仓位不一致
        2. 验证日志格式包含警告信息
        """
        check = PositionConsistencyCheck(
            is_consistent=False,
            extended_quantity=Decimal('0.21'),
            lighter_quantity=Decimal('0.02'),
            difference=Decimal('0.19'),
            difference_rate=0.826,
            threshold_exceeded=True
        )

        log_str = str(check)
        assert '⚠️ 不一致' in log_str
        assert '0.1900' in log_str
        assert '82.60%' in log_str


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
