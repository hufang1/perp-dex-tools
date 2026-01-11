"""
仓位平衡计算修复测试

测试PositionBalance的修复后计算逻辑：
- 使用绝对值计算总暴露度
- 使用绝对值计算实际差异
- 正确的差异率计算
"""

import time
from decimal import Decimal

import pytest

from spread.models import PositionBalance


class TestPositionBalanceFix:
    """测试仓位平衡计算修复"""

    def test_fully_hedged_position(self):
        """测试完全对冲仓位 - 应该显示0%差异率"""
        balance = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.01'),
            lighter_total_qty=Decimal('-0.01'),  # 对冲仓位（空头）
            diff_qty=Decimal('0.02')
        )

        # 完全对冲应该显示0%差异率
        assert balance.diff_rate == Decimal('0'), f"期望0%, 实际{balance.diff_rate}"
        assert balance.warning_level == 'OK'
        assert not balance.is_imbalanced

    def test_imbalanced_position_82_percent(self):
        """测试82.6%失衡仓位（Extended 0.21, Lighter 0.02）"""
        balance = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.21'),
            lighter_total_qty=Decimal('0.02'),
            diff_qty=Decimal('0.19')
        )

        # 期望: 0.19 / 0.23 = 82.6%
        expected_rate = Decimal('0.19') / Decimal('0.23')
        assert balance.diff_rate == expected_rate, f"期望{expected_rate}, 实际{balance.diff_rate}"
        assert balance.diff_rate > Decimal('0.8'), "差异率应该大于80%"
        assert balance.diff_rate < Decimal('0.9'), "差异率应该小于90%"
        assert balance.warning_level == 'CRITICAL'
        assert balance.is_imbalanced

    def test_critical_imbalance(self):
        """测试严重失衡触发CRITICAL级别"""
        balance = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.10'),
            lighter_total_qty=Decimal('0.01'),  # 90%失衡
            diff_qty=Decimal('0.09')
        )

        # 总暴露度: 0.11, 差异: 0.09, 失衡率: 81.8%
        assert balance.diff_rate > Decimal('0.5'), "应该超过50%阈值"
        assert balance.warning_level == 'CRITICAL'
        assert balance.is_imbalanced

    def test_warning_level_determination(self):
        """测试警告级别判断"""
        # 测试OK级别（<10%）
        balance_ok = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.10'),
            lighter_total_qty=Decimal('0.095'),
            diff_qty=Decimal('0.005')
        )
        assert balance_ok.warning_level == 'OK'
        assert not balance_ok.is_imbalanced

        # 测试WARN级别（10%-50%）
        balance_warn = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.10'),
            lighter_total_qty=Decimal('0.07'),
            diff_qty=Decimal('0.03')
        )
        assert balance_warn.warning_level == 'WARN'
        assert balance_warn.is_imbalanced

        # 测试CRITICAL级别（>=50%）
        balance_critical = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.10'),
            lighter_total_qty=Decimal('0.02'),  # 修改：使差异率达到50%以上
            diff_qty=Decimal('0.08')
        )
        # 总暴露度: 0.12, 差异: 0.08, 失衡率: 66.7%
        assert balance_critical.warning_level == 'CRITICAL'
        assert balance_critical.is_imbalanced

    def test_edge_cases(self):
        """测试边界情况"""
        # 零仓位
        balance_zero = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0'),
            lighter_total_qty=Decimal('0'),
            diff_qty=Decimal('0')
        )
        assert balance_zero.diff_rate == Decimal('0')
        assert balance_zero.warning_level == 'OK'

        # 单边仓位（Extended有仓位，Lighter为0）
        balance_single = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.10'),
            lighter_total_qty=Decimal('0'),
            diff_qty=Decimal('0.10')
        )
        assert balance_single.diff_rate == Decimal('1'), "100%失衡"
        assert balance_single.warning_level == 'CRITICAL'

        # 完全对称对冲
        balance_symmetric = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('0.05'),
            lighter_total_qty=Decimal('-0.05'),
            diff_qty=Decimal('0.10')
        )
        assert balance_symmetric.diff_rate == Decimal('0')
        assert balance_symmetric.warning_level == 'OK'

    def test_negative_positions(self):
        """测试负数仓位（空头仓位）"""
        # Extended空头，Lighter多头（对冲）
        balance = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('-0.08'),
            lighter_total_qty=Decimal('0.08'),
            diff_qty=Decimal('0.16')
        )
        # 使用绝对值计算，应该是对冲的
        assert balance.diff_rate == Decimal('0')
        assert balance.warning_level == 'OK'

    def test_imbalanced_negative_positions(self):
        """测试负数仓位的失衡情况"""
        # Extended空头-0.10，Lighter多头0.02（严重失衡）
        balance = PositionBalance(
            timestamp=time.time(),
            extended_total_qty=Decimal('-0.10'),
            lighter_total_qty=Decimal('0.02'),
            diff_qty=Decimal('0.12')
        )
        # 总暴露度: 0.12, 差异: 0.08, 失衡率: 66.7%
        assert balance.diff_rate > Decimal('0.5')
        assert balance.warning_level == 'CRITICAL'
