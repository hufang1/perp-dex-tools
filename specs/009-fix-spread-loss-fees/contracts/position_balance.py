"""
Contract: Position Balance Calculator

This contract defines the interface for calculating position balance
between Extended and Lighter exchanges.

Purpose: Correct calculation of hedged position balance.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, NamedTuple, Literal


class PositionSummary(NamedTuple):
    """单个交易所的仓位汇总"""
    long_qty: Decimal      # 多头仓位
    short_qty: Decimal     # 空头仓位
    net_qty: Decimal       # 净仓位 (long - short)
    total_exposure: Decimal  # 总敞口 (|long| + |short|)


class BalanceResult(NamedTuple):
    """仓位平衡结果"""
    extended_summary: PositionSummary    # Extended仓位汇总
    lighter_summary: PositionSummary     # Lighter仓位汇总
    net_position: Decimal                # 净仓位 (extended - lighter)
    abs_net_position: Decimal            |None = None  # 净仓位绝对值
    diff_rate: Decimal                   # 差异率
    is_balanced: bool                    # 是否平衡
    imbalance_level: Literal['NONE', 'LOW', 'MEDIUM', 'HIGH']  # 不平衡级别


class IPositionBalanceCalculator(ABC):
    """仓位平衡计算器接口"""

    @abstractmethod
    def calculate_balance(
        self,
        extended_long_qty: Decimal,
        extended_short_qty: Decimal,
        lighter_long_qty: Decimal,
        lighter_short_qty: Decimal
    ) -> BalanceResult:
        """
        计算仓位平衡

        算法（修复版）:
            extended_net = extended_long - extended_short
            lighter_net = lighter_long - lighter_short
            net_position = extended_net - lighter_net  # 使用相减！
            total_exposure = |extended_net| + |lighter_net|

            if total_exposure > 0:
                diff_rate = |net_position| / total_exposure
            else:
                diff_rate = 0

        Args:
            extended_long_qty: Extended多头仓位
            extended_short_qty: Extended空头仓位
            lighter_long_qty: Lighter多头仓位
            lighter_short_qty: Lighter空头仓位

        Returns:
            BalanceResult: 仓位平衡结果
        """
        pass

    @abstractmethod
    def determine_imbalance_level(
        self,
        diff_rate: Decimal
    ) -> Literal['NONE', 'LOW', 'MEDIUM', 'HIGH']:
        """
        确定不平衡级别

        阈值:
            NONE:   diff_rate < 1%
            LOW:    1% <= diff_rate < 5%
            MEDIUM: 5% <= diff_rate < 10%
            HIGH:   diff_rate >= 10%

        Args:
            diff_rate: 差异率

        Returns:
            不平衡级别
        """
        pass

    @abstractmethod
    def should_trigger_alert(self, balance: BalanceResult) -> tuple[bool, str]:
        """
        判断是否应该触发警报

        触发条件:
            1. 不平衡级别 >= MEDIUM
            2. 净仓位 > 某个阈值
            3. 对冲失败率过高

        Args:
            balance: 仓位平衡结果

        Returns:
            tuple[bool, str]: (是否触发, 警报消息)
        """
        pass


class PositionReconciliation(ABC):
    """仓位对账接口"""

    @abstractmethod
    def reconcile_positions(
        self,
        reported_extended_qty: Decimal,
        reported_lighter_qty: Decimal,
        calculated_extended_qty: Decimal,
        calculated_lighter_qty: Decimal
    ) -> tuple[bool, str]:
        """
        对账交易所报告的仓位和本地计算的仓位

        Args:
            reported_extended_qty: Extended报告的仓位
            reported_lighter_qty: Lighter报告的仓位
            calculated_extended_qty: 本地计算的Extended仓位
            calculated_lighter_qty: 本地计算的Lighter仓位

        Returns:
            tuple[bool, str]: (是否匹配, 差异说明)
        """
        pass

    @abstractmethod
    def detect_unhedged_position(
        self,
        balance: BalanceResult
    ) -> tuple[bool, Decimal, Literal['extended', 'lighter']]:
        """
        检测未对冲仓位

        Args:
            balance: 仓位平衡结果

        Returns:
            tuple[bool, Decimal, Literal['extended', 'lighter']]:
                (是否有未对冲, 未对冲数量, 哪个交易所多余)
        """
        pass
