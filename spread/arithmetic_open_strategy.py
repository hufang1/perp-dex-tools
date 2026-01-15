"""
等差数列开仓策略模块

负责：
1. 判断是否满足开仓条件（首次和后续开仓）
2. 管理上次开仓价差（cached_open_spread）
3. 提供单行日志输出
"""

import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime

from models import BotConfig, RealTimeSpreadInfo, OpenStrategyState


logger = logging.getLogger(__name__)


class ArithmeticOpenStrategy:
    """
    等差数列开仓策略

    首次开仓：价差 > min_threshold
    后续开仓：价差 > cached_open_spread + spread_step
    价差缩小时不降低上次开仓价差
    """

    def __init__(self, config: BotConfig):
        """
        初始化策略

        Args:
            config: 机器人配置对象
        """
        self.config = config
        self._state = OpenStrategyState.WAITING
        self._last_check_time: float = 0

    def should_open(self, spread_info: RealTimeSpreadInfo) -> tuple[bool, str]:
        """
        判断是否应该开仓

        Args:
            spread_info: 当前价差信息

        Returns:
            (should_open, reason): 是否应该开仓和原因说明
        """
        if not spread_info or not spread_info.is_valid():
            return False, "价差数据无效"

        current_spread = spread_info.spread_pct
        min_threshold = self.config.min_spread_threshold
        cached_spread = self.config.cached_open_spread
        spread_step = self.config.spread_step

        # 首次开仓：上次开仓价差为0时，使用最小阈值
        if cached_spread == 0:
            if current_spread > min_threshold:
                self._state = OpenStrategyState.READY
                reason = f"开仓: 价差{current_spread:.2%} > 阈值{min_threshold:.2%}"
                return True, reason
            else:
                self._state = OpenStrategyState.WAITING
                reason = f"价差{current_spread:.2%}未达到开仓阈值{min_threshold:.2%}"
                return False, reason

        # 后续开仓：价差必须大于上次开仓价差+步长
        threshold = cached_spread + spread_step
        if current_spread > threshold:
            self._state = OpenStrategyState.READY
            reason = f"开仓: 价差{current_spread:.2%} > 阈值{threshold:.2%} (上次开仓{cached_spread:.2%} + 步长{spread_step:.3%})"
            return True, reason
        else:
            self._state = OpenStrategyState.WAITING
            if current_spread > cached_spread:
                reason = f"价差{current_spread:.2%}未达到开仓条件{threshold:.2%}"
            else:
                reason = f"价差{current_spread:.2%} < 上次开仓{cached_spread:.2%}，等待价差扩大"
            return False, reason

    def update_cached_spread(self, new_spread: Decimal) -> None:
        """
        更新上次开仓价差

        价差缩小时不降低上次开仓价差（只增不减）

        Args:
            new_spread: 新的价差值
        """
        old_spread = self.config.cached_open_spread

        # 只增不减原则
        if new_spread > old_spread:
            self.config.cached_open_spread = new_spread
            logger.info(f"上次开仓价差更新: {old_spread:.2%} -> {new_spread:.2%}")
        else:
            logger.debug(f"上次开仓价差保持: {old_spread:.2%} (新价差{new_spread:.2%}未超过)")

    def get_state(self) -> OpenStrategyState:
        """获取当前策略状态"""
        return self._state

    def get_cached_spread(self) -> Decimal:
        """获取当前上次开仓价差"""
        return self.config.cached_open_spread

    def get_next_threshold(self) -> Decimal:
        """获取下次开仓阈值"""
        cached = self.config.cached_open_spread
        if cached == 0:
            return self.config.min_spread_threshold
        return cached + self.config.spread_step

    def format_status(self) -> str:
        """
        格式化策略状态为单行日志

        Returns:
            状态字符串
        """
        cached = self.config.cached_open_spread
        step = self.config.spread_step
        threshold = self.get_next_threshold()

        if cached == 0:
            return f"策略: 首次开仓 | 阈值{threshold:.2%}"
        else:
            return f"策略: 上次开仓{cached:.2%} | 步长{step:.2%} | 阈值{threshold:.2%}"
