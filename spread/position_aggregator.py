"""
持仓聚合器 - 将多个同向SpreadPair合并为统一持仓视图
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
import time

from .spread_pair import SpreadPair
from .models import PositionConsistencyCheck


# T058: PositionSummary数据类
@dataclass
class PositionSummary:
    """仓位汇总 - 两个交易所的仓位总览"""
    extended_total_qty: Decimal  # Extended总仓位数量（正数=多头，负数=空头）
    lighter_total_qty: Decimal   # Lighter总仓位数量（正数=多头，负数=空头）
    diff_qty: Decimal            # 差异数量（使用相减：|extended - lighter|）
    timestamp: float             # 计算时间戳


# T059: BalanceResult数据类
@dataclass
class BalanceResult:
    """仓位平衡结果 - 扩展的仓位平衡分析"""
    summary: PositionSummary     # 仓位汇总
    diff_rate: Decimal           # 差异率（diff_qty / avg_total_qty）
    is_imbalanced: bool          # 是否失衡
    warning_level: str           # 警告级别: 'OK', 'WARN', 'CRITICAL'
    timestamp: float             # 计算时间戳


@dataclass
class UnifiedPosition:
    """统一持仓 - 聚合同方向的多个SpreadPair"""

    # 基本信息
    direction: str  # 'long' 或 'short'
    pair_ids: List[int]  # 包含的套利对ID列表

    # 仓位信息
    total_quantity: Decimal  # 总数量
    extended_avg_price: Decimal  # Extended平均开仓价格（加权平均）
    lighter_avg_price: Decimal  # Lighter平均开仓价格（加权平均）

    # 时间信息
    earliest_open_time: float  # 最早开仓时间
    latest_open_time: float  # 最晚开仓时间

    # 手续费
    total_opening_fees: Decimal  # 总开仓手续费

    def calculate_holding_time_range(self) -> tuple:
        """返回持仓时间范围 (最早, 最晚, 单位: 秒)"""
        now = time.time()
        earliest_holding = now - self.latest_open_time
        latest_holding = now - self.earliest_open_time
        return (earliest_holding, latest_holding)

    def calculate_average_holding_time(self) -> float:
        """返回平均持仓时间 (秒)"""
        now = time.time()
        total_holding = sum([now - self.latest_open_time, now - self.earliest_open_time])
        return total_holding / 2


class PositionAggregator:
    """持仓聚合器 - 将多个SpreadPair按方向聚合"""

    def __init__(self, extended_fee_rate: Decimal = Decimal('0.000225'),
                 lighter_fee_rate: Decimal = Decimal('0.0')):
        """
        初始化持仓聚合器

        Args:
            extended_fee_rate: Extended手续费率
            lighter_fee_rate: Lighter手续费率
        """
        self.extended_fee_rate = extended_fee_rate
        self.lighter_fee_rate = lighter_fee_rate

    def aggregate_positions(self, pairs: List[SpreadPair]) -> Dict[str, UnifiedPosition]:
        """
        聚合同方向的持仓

        Args:
            pairs: SpreadPair列表

        Returns:
            按方向分组的统一持仓字典
            - 'long': UnifiedPosition (如果有做多持仓)
            - 'short': UnifiedPosition (如果有做空持仓)
        """
        if not pairs:
            return {}

        # 按方向分组
        long_pairs = []
        short_pairs = []

        for pair in pairs:
            if pair.extended_side == 'buy':
                long_pairs.append(pair)
            else:
                short_pairs.append(pair)

        result = {}

        # 聚合做多持仓
        if long_pairs:
            result['long'] = self._aggregate_same_direction_pairs(long_pairs, 'long')

        # 聚合做空持仓
        if short_pairs:
            result['short'] = self._aggregate_same_direction_pairs(short_pairs, 'short')

        return result

    def _aggregate_same_direction_pairs(self, pairs: List[SpreadPair], direction: str) -> UnifiedPosition:
        """
        聚合同方向的pairs

        Args:
            pairs: 同方向的SpreadPair列表
            direction: 方向 ('long' 或 'short')

        Returns:
            UnifiedPosition对象
        """
        if not pairs:
            raise ValueError("pairs列表不能为空")

        # 计算总数量
        total_quantity = sum(pair.extended_quantity for pair in pairs)

        # 计算加权平均价格
        extended_total_value = sum(pair.extended_quantity * pair.extended_price for pair in pairs)
        lighter_total_value = sum(pair.lighter_quantity * pair.lighter_price for pair in pairs)

        extended_avg_price = extended_total_value / total_quantity
        lighter_avg_price = lighter_total_value / total_quantity

        # 计算时间范围
        open_times = [pair.open_time for pair in pairs]
        earliest_open_time = min(open_times)
        latest_open_time = max(open_times)

        # 计算总开仓手续费
        total_opening_fees = self._calculate_total_opening_fees(pairs)

        # 收集pair_id
        pair_ids = [pair.pair_id for pair in pairs]

        return UnifiedPosition(
            direction=direction,
            pair_ids=pair_ids,
            total_quantity=total_quantity,
            extended_avg_price=extended_avg_price,
            lighter_avg_price=lighter_avg_price,
            earliest_open_time=earliest_open_time,
            latest_open_time=latest_open_time,
            total_opening_fees=total_opening_fees
        )

    def _calculate_total_opening_fees(self, pairs: List[SpreadPair]) -> Decimal:
        """
        计算总开仓手续费

        Args:
            pairs: SpreadPair列表

        Returns:
            总开仓手续费
        """
        total_fees = Decimal('0')

        for pair in pairs:
            # Extended开仓手续费
            extended_fee = pair.extended_quantity * pair.extended_price * self.extended_fee_rate
            total_fees += extended_fee

            # Lighter开仓手续费
            lighter_fee = pair.lighter_quantity * pair.lighter_price * self.lighter_fee_rate
            total_fees += lighter_fee

        return total_fees

    # ==================== T060-T061: 仓位平衡计算方法 ====================

    def calculate_balance(self, pairs: List[SpreadPair]) -> BalanceResult:
        """
        T060: 计算仓位平衡状态（使用相减而非绝对值相加）

        修复前: diff_qty = abs(extended_total) + abs(lighter_total)  # 错误！
        修复后: diff_qty = abs(extended_total - lighter_total)     # 正确

        Args:
            pairs: SpreadPair列表

        Returns:
            BalanceResult: 仓位平衡结果
        """
        # 计算各交易所总仓位（考虑方向）
        extended_total = Decimal('0')
        lighter_total = Decimal('0')

        for pair in pairs:
            # 做多：Extended为正，Lighter为负（对冲）
            # 做空：Extended为负，Lighter为正（对冲）
            if pair.extended_side == 'buy':
                # 做多价差：Extended多头，Lighter空头
                extended_total += pair.extended_quantity
                lighter_total -= pair.lighter_quantity
            else:
                # 做空价差：Extended空头，Lighter多头
                extended_total -= pair.extended_quantity
                lighter_total += pair.lighter_quantity

        # 修复：使用相减计算差异数量
        diff_qty = abs(extended_total + lighter_total)

        # 创建仓位汇总
        summary = PositionSummary(
            extended_total_qty=extended_total,
            lighter_total_qty=lighter_total,
            diff_qty=diff_qty,
            timestamp=time.time()
        )

        # 计算差异率
        avg_total_qty = (abs(extended_total) + abs(lighter_total)) / 2
        if avg_total_qty > 0:
            diff_rate = diff_qty / avg_total_qty
        else:
            diff_rate = Decimal('0')

        # 判断失衡级别
        warning_level = self.determine_imbalance_level(diff_rate)
        is_imbalanced = warning_level != 'OK'

        return BalanceResult(
            summary=summary,
            diff_rate=diff_rate,
            is_imbalanced=is_imbalanced,
            warning_level=warning_level,
            timestamp=time.time()
        )

    def determine_imbalance_level(self, diff_rate: Decimal) -> str:
        """
        T061: 判断仓位失衡级别

        Args:
            diff_rate: 差异率（0-1之间）

        Returns:
            'OK': 平衡（diff_rate < 0.01, 即1%）
            'WARN': 失衡（0.01 <= diff_rate < 0.05, 即1%-5%）
            'CRITICAL': 严重失衡（diff_rate >= 0.05, 即5%以上）
        """
        if diff_rate < Decimal('0.01'):
            return 'OK'
        elif diff_rate < Decimal('0.05'):
            return 'WARN'
        else:
            return 'CRITICAL'

    # ========================================================================
    # 001-fix-order-type: 单个套利对仓位一致性检查
    # ========================================================================

    def get_position_balance_for_pair(
        self,
        pair: SpreadPair,
        threshold: Decimal = Decimal('0.001'),
        rate_threshold: float = 0.1
    ) -> PositionConsistencyCheck:
        """
        001-fix-order-type: 获取单个套利对的仓位一致性检查结果

        验证开仓后Extended和Lighter仓位数量是否一致。

        Args:
            pair: 套利对对象
            threshold: 差异数量阈值（默认0.001 ETH）
            rate_threshold: 差异率阈值（默认10%）

        Returns:
            PositionConsistencyCheck: 一致性检查结果
        """
        # 获取仓位数量
        extended_qty = pair.extended_quantity
        lighter_qty = pair.lighter_quantity

        # 计算差异数量（绝对值）
        difference = abs(extended_qty - lighter_qty)

        # 计算差异率
        total_exposure = (abs(extended_qty) + abs(lighter_qty)) / 2
        if total_exposure > 0:
            difference_rate = float(difference / total_exposure)
        else:
            difference_rate = 0.0

        # 检查是否超过阈值
        threshold_exceeded = (
            difference > threshold or
            difference_rate > rate_threshold
        )

        # 判断是否一致
        is_consistent = not threshold_exceeded

        return PositionConsistencyCheck(
            is_consistent=is_consistent,
            extended_quantity=extended_qty,
            lighter_quantity=lighter_qty,
            difference=difference,
            difference_rate=difference_rate,
            threshold_exceeded=threshold_exceeded
        )
