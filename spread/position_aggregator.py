"""
持仓聚合器 - 将多个同向SpreadPair合并为统一持仓视图
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Dict, Optional
import time

from .spread_pair import SpreadPair


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
