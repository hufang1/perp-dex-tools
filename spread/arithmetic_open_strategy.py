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

from models import (
    BotConfig,
    RealTimeSpreadInfo,
    OpenStrategyState,
    TieredOpeningState,
)


logger = logging.getLogger(__name__)


class ArithmeticOpenStrategy:
    """
    等差数列开仓策略

    首次开仓：价差 >= min_threshold
    后续开仓：价差 >= cached_open_spread + spread_step
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

        (003-spreading-improvements: 修改为使用阶梯价差阈值)

        阶梯式价差阈值策略：
        - 第1次开仓：initial_open_spread (如 0.5%)
        - 第2次开仓：initial_open_spread + spread_step (如 0.6%)
        - 第N次开仓：initial_open_spread + (N-1) * spread_step

        Args:
            spread_info: 当前价差信息

        Returns:
            (should_open, reason): 是否应该开仓和原因说明
        """
        if not spread_info or not spread_info.is_valid():
            return False, "价差数据无效"

        current_spread = spread_info.spread_pct

        # ========== 新增 (003-spreading-improvements): 使用阶梯开仓阈值 ==========
        current_threshold = self.config.current_open_threshold

        if current_spread >= current_threshold:
            self._state = OpenStrategyState.READY
            reason = (
                f"开仓: 价差{current_spread:.3%} >= 阈值{current_threshold:.3%} "
                f"(初始={self.config.initial_open_spread:.3%}, "
                f"次数={self.config.opening_count}, "
                f"步长={self.config.spread_step:.3%})"
            )
            return True, reason
        else:
            self._state = OpenStrategyState.WAITING
            reason = (
                f"价差{current_spread:.3%}未达到阶梯阈值{current_threshold:.3%} "
                f"(初始={self.config.initial_open_spread:.3%}, "
                f"次数={self.config.opening_count}, "
                f"步长={self.config.spread_step:.3%})"
            )
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
            logger.info(f"上次开仓价差更新: {old_spread:.3%} -> {new_spread:.3%}")
        else:
            logger.info(f"上次开仓价差保持: {old_spread:.3%} (新价差{new_spread:.3%} <= 上次价差，未更新)")

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
        # ========== 新增 (003-spreading-improvements): 使用阶梯开仓状态 ==========
        tier_state = self.get_current_tier_state()
        return tier_state.format_log()

    # ========== 新增方法 (003-spreading-improvements): 阶梯开仓回调 ==========

    async def on_position_opened(self, actual_spread: Decimal) -> None:
        """
        开仓成功回调 (003-spreading-improvements)

        在开仓成功后调用，增加开仓次数并更新策略状态。

        Args:
            actual_spread: 实际开仓价差
        """
        old_count = self.config.opening_count
        self.config.opening_count += 1

        logger.info(
            f"开仓成功 | 开仓次数: {old_count} -> {self.config.opening_count} | "
            f"下次阈值: {self.config.current_open_threshold:.3%} | "
            f"实际价差: {actual_spread:.3%}"
        )

        # 记录开仓历史
        tier_state = self.get_current_tier_state()
        tier_state.record_opening(actual_spread)

    async def on_all_positions_closed(self) -> None:
        """
        所有仓位平仓回调 (003-spreading-improvements)

        在所有仓位平仓后调用，重置开仓次数。
        """
        old_count = self.config.opening_count
        self.config.opening_count = 0

        logger.info(
            f"所有仓位已平仓 | 重置开仓次数: {old_count} -> 0 | "
            f"下次阈值恢复为: {self.config.current_open_threshold:.3%}"
        )

        # 重置阶梯状态
        tier_state = self.get_current_tier_state()
        tier_state.reset()

    def get_current_tier_state(self) -> TieredOpeningState:
        """
        获取当前阶梯开仓状态 (003-spreading-improvements)

        Returns:
            TieredOpeningState: 当前阶梯开仓状态快照
        """
        return TieredOpeningState(
            current_count=self.config.opening_count,
            current_threshold=self.config.current_open_threshold,
            next_threshold=self.config.initial_open_spread + (
                (self.config.opening_count + 1) * self.config.spread_step
            ),
            initial_spread=self.config.initial_open_spread,
            step_size=self.config.spread_step,
        )
