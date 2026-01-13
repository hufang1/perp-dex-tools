"""
智能平仓系统模块

负责：
1. 管理多笔仓位（Portfolio）
2. 实时监控持仓，判断平仓条件
3. 计算加权平均开仓价差
4. 提供单行日志输出
"""

import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional

from models import (
    BotConfig,
    RealTimeSpreadInfo,
    Portfolio,
    OpenPosition,
    CloseTrigger,
)


logger = logging.getLogger(__name__)


class SmartCloseStrategy:
    """
    智能平仓策略

    平仓条件：开仓价差 >= 当前价差 + 盈利目标 + 手续费
    """

    def __init__(self, config: BotConfig):
        """
        初始化策略

        Args:
            config: 机器人配置对象
        """
        self.config = config
        self.portfolio: Portfolio = Portfolio()

    def add_position(self, position: OpenPosition) -> None:
        """
        添加仓位到组合

        Args:
            position: 开仓记录
        """
        self.portfolio.add_position(position)
        logger.info(f"添加仓位: {position.format_log()}")

    def should_close(self, spread_info: RealTimeSpreadInfo) -> CloseTrigger:
        """
        判断是否应该平仓

        Args:
            spread_info: 当前价差信息

        Returns:
            CloseTrigger对象，包含是否触发、原因等信息
        """
        if not spread_info or not spread_info.is_valid():
            return CloseTrigger(
                is_triggered=False,
                entry_spread=Decimal("0"),
                current_spread=Decimal("0"),
                profit_target=self.config.min_profit,
                fee_rate=self.config.total_fee_rate,
                expected_profit=Decimal("0"),
                trigger_time=datetime.now().timestamp(),
            )

        # 获取加权平均开仓价差
        entry_spread = self.portfolio.get_total_entry_spread()
        if entry_spread == 0:
            return CloseTrigger(
                is_triggered=False,
                entry_spread=Decimal("0"),
                current_spread=spread_info.spread_pct,
                profit_target=self.config.min_profit,
                fee_rate=self.config.total_fee_rate,
                expected_profit=Decimal("0"),
                trigger_time=datetime.now().timestamp(),
            )

        current_spread = spread_info.spread_pct
        profit_target = self.config.min_profit
        fee_rate = self.config.total_fee_rate

        # 计算预期利润
        expected_profit = entry_spread - current_spread - fee_rate

        # 判断是否触发平仓：开仓价差 >= 当前价差 + 盈利目标 + 手续费
        is_triggered = entry_spread >= current_spread + profit_target + fee_rate

        # 检查价差是否扩大（警告）
        if current_spread > entry_spread:
            logger.warning(
                f"价差扩大: 当前{current_spread:.2%} > 开仓{entry_spread:.2%}"
            )

        return CloseTrigger(
            is_triggered=is_triggered,
            entry_spread=entry_spread,
            current_spread=current_spread,
            profit_target=profit_target,
            fee_rate=fee_rate,
            expected_profit=expected_profit,
            trigger_time=datetime.now().timestamp(),
        )

    def monitor_position(self, spread_info: Optional[RealTimeSpreadInfo]) -> None:
        """
        监控持仓状态并输出日志

        Args:
            spread_info: 当前价差信息
        """
        if spread_info and spread_info.is_valid():
            trigger = self.should_close(spread_info)
            if not trigger.is_triggered:
                logger.info(trigger.format_log())

    def close_all(self) -> list[OpenPosition]:
        """
        平掉所有仓位

        Returns:
            已平仓的仓位列表
        """
        closed = self.portfolio.close_all()
        logger.info(f"平掉所有仓位: {len(closed)}笔")
        for pos in closed:
            logger.info(f"  {pos.format_log()}")
        return closed

    def get_portfolio(self) -> Portfolio:
        """获取当前仓位组合"""
        return self.portfolio

    def get_active_count(self) -> int:
        """获取活跃仓位数"""
        return len(self.portfolio.get_active_positions())

    def get_total_quantity(self) -> Decimal:
        """获取总持仓数量"""
        return self.portfolio.total_quantity

    def get_weighted_avg_spread(self) -> Decimal:
        """获取加权平均开仓价差"""
        return self.portfolio.get_total_entry_spread()

    def format_status(self) -> str:
        """
        格式化策略状态为单行日志

        Returns:
            状态字符串
        """
        return self.portfolio.format_log()
