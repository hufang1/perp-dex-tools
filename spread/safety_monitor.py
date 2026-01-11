"""
安全监控模块

本模块实现价差套利系统的安全监控和熔断机制，包括:
- 对冲失败率监控
- 仓位失衡率计算
- 多级熔断器逻辑
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Tuple, Optional, List, Dict

from .config import SpreadArbConfig
from .models import SafetyState, HedgeFailureTracking


class SafetyError(Exception):
    """安全检查失败的基类异常"""
    pass


class CircuitBreakerError(SafetyError):
    """熔断器触发时的异常"""
    pass


class SafetyMonitor:
    """安全监控器 - 实时监控系统安全状态，触发熔断机制"""

    def __init__(self, config: SpreadArbConfig, logger: logging.Logger):
        """
        初始化安全监控器

        Args:
            config: 配置对象
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger
        self.state = SafetyState()
        self.failure_tracking: List[HedgeFailureTracking] = []
        self._lock = asyncio.Lock()

    async def record_hedge_attempt(self, success: bool, failure_reason: Optional[str] = None) -> None:
        """
        记录对冲尝试结果

        Args:
            success: 对冲是否成功
            failure_reason: 失败原因（如果失败）

        Raises:
            ValueError: 如果failure_reason在success=True时提供
        """
        if success and failure_reason:
            raise ValueError("成功时不应提供failure_reason")

        async with self._lock:
            # 更新统计
            self.state.total_hedge_attempts += 1
            if not success:
                self.state.total_hedge_failures += 1

            # 更新滑动窗口（最多保留配置的窗口大小）
            self.state.recent_hedge_attempts.append(success)
            if len(self.state.recent_hedge_attempts) > self.config.hedge_failure_window:
                self.state.recent_hedge_attempts.pop(0)

            # 重新计算失败率
            self.state.hedge_failure_rate = self._calculate_failure_rate()

            # 如果失败，记录详细跟踪信息
            if not success and failure_reason:
                self._log_failure(failure_reason)

            # 检查熔断条件
            await self._check_circuit_conditions()

    def get_hedge_failure_rate(self) -> Decimal:
        """
        获取当前对冲失败率

        Returns:
            对冲失败率（0-1之间的Decimal）
        """
        return self.state.hedge_failure_rate

    def check_circuit_breaker(self) -> Tuple[int, str]:
        """
        检查是否应该触发熔断

        Returns:
            (熔断级别, 原因)
            级别: 0=正常, 1=警告, 2=禁止开仓, 3=完全暂停
        """
        failure_rate = self.state.hedge_failure_rate
        imbalance_rate = self.state.position_imbalance_rate

        # 级别3（完全暂停）: 失败率>50% 或 失衡率>50%
        if failure_rate > Decimal('0.5') or imbalance_rate > Decimal('0.5'):
            return 3, f"严重告警: 对冲失败率={failure_rate:.2%}, 仓位失衡率={imbalance_rate:.2%}"

        # 级别2（禁止开仓）: 失败率>30%
        if failure_rate > self.config.safety_hedge_failure_threshold:
            return 2, f"对冲失败率过高: {failure_rate:.2%} > {self.config.safety_hedge_failure_threshold:.2%}"

        # 级别1（警告）: 失败率>20%
        if failure_rate > Decimal('0.2'):
            return 1, f"对冲失败率警告: {failure_rate:.2%}"

        # 级别0（正常）
        return 0, "系统正常"

    def should_pause_opening(self) -> bool:
        """
        检查是否应该暂停开仓

        Returns:
            True表示应该暂停开仓
        """
        # 如果系统已暂停
        if self.state.is_paused:
            return True

        # 检查熔断级别
        level, _ = self.check_circuit_breaker()
        return level >= 2

    def should_force_close(self) -> bool:
        """
        检查是否应该强制平仓

        Returns:
            True表示应该强制平仓所有持仓
        """
        level, _ = self.check_circuit_breaker()
        return level >= 3

    def update_position_imbalance(self, extended_qty: Decimal, lighter_qty: Decimal) -> None:
        """
        更新仓位失衡率

        Args:
            extended_qty: Extended总仓位（带符号）
            lighter_qty: Lighter总仓位（带符号）
        """
        # 使用绝对值计算总暴露度
        total_exposure = abs(extended_qty) + abs(lighter_qty)

        # 使用绝对值计算实际差异
        diff_qty = abs(abs(extended_qty) - abs(lighter_qty))

        # 计算差异率
        if total_exposure > 0:
            imbalance_rate = diff_qty / total_exposure
        else:
            imbalance_rate = Decimal('0')

        # 更新状态
        self.state.position_imbalance_rate = imbalance_rate
        self.state.last_imbalance_check = time.time()

        # 记录日志
        if imbalance_rate > self.config.safety_position_imbalance_threshold:
            self.logger.warning(
                f"仓位失衡率过高: {imbalance_rate:.2%} "
                f"(Extended: {extended_qty}, Lighter: {lighter_qty})"
            )

    def get_position_imbalance_rate(self) -> Decimal:
        """
        获取当前仓位失衡率

        Returns:
            仓位失衡率（0-1之间的Decimal）
        """
        return self.state.position_imbalance_rate

    def get_safety_state(self) -> SafetyState:
        """
        获取当前安全状态快照

        Returns:
            SafetyState对象
        """
        return self.state

    def reset_circuit_breaker(self) -> None:
        """
        手动重置熔断器

        用于用户确认问题解决后恢复交易
        """
        self.state.is_paused = False
        self.state.pause_reason = ""
        self.state.pause_since = None
        self.state.circuit_breaker_level = 0

        self.logger.info("熔断器已手动重置，系统恢复正常")

    def _calculate_failure_rate(self) -> Decimal:
        """从滑动窗口计算失败率"""
        if not self.state.recent_hedge_attempts:
            return Decimal('0')

        failures = sum(1 for attempt in self.state.recent_hedge_attempts if not attempt)
        return Decimal(str(failures)) / Decimal(str(len(self.state.recent_hedge_attempts)))

    async def _check_circuit_conditions(self) -> None:
        """检查熔断条件并更新状态"""
        level, reason = self.check_circuit_breaker()

        # 更新熔断级别
        if level > self.state.circuit_breaker_level:
            self.state.circuit_breaker_level = level
            self.logger.warning(f"熔断器级别提升到 {level}: {reason}")

        # 如果达到完全暂停级别
        if level >= 3 and not self.state.is_paused:
            self.state.is_paused = True
            self.state.pause_reason = reason
            self.state.pause_since = time.time()
            self.logger.error(f"系统进入完全暂停状态: {reason}")

    def _log_failure(self, reason: str) -> None:
        """记录失败详情"""
        self.logger.warning(f"对冲失败: {reason}, 当前失败率: {self.state.hedge_failure_rate:.2%}")
