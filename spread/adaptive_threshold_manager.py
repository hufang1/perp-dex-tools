"""
动态阈值管理模块

本模块根据对冲成功率动态调整开仓阈值，包括:
- 在高成功率时使用降低阈值（增加交易频率）
- 在低成功率时使用安全阈值（保护资金）
- 根据仓位失衡率动态调整
"""

import logging
from decimal import Decimal

from .config import SpreadArbConfig
from .safety_monitor import SafetyMonitor


class AdaptiveThresholdManager:
    """动态阈值管理器 - 根据对冲成功率动态调整开仓阈值"""

    def __init__(self, config: SpreadArbConfig, safety_monitor: SafetyMonitor):
        """
        初始化动态阈值管理器

        Args:
            config: 配置对象
            safety_monitor: 安全监控器
        """
        self.config = config
        self.safety_monitor = safety_monitor
        self.logger = logging.getLogger("AdaptiveThresholdManager")

    def get_effective_min_spread_rate(self) -> Decimal:
        """
        获取当前有效的最小价差率

        根据对冲成功率动态调整：
        - 成功率>90%: 使用reduced_min_spread_rate (0.06%)
        - 成功率>80%: 使用中间值
        - 成功率<80%: 使用adaptive_min_spread_rate_safe (0.15%)
        - 未启用动态阈值: 使用config.min_spread_rate

        Returns:
            当前有效的最小价差率
        """
        # 如果未启用动态阈值，返回基础配置
        if not self.config.adaptive_threshold_enabled:
            return self.config.min_spread_rate

        # 获取当前对冲成功率
        hedge_failure_rate = self.safety_monitor.get_hedge_failure_rate()
        hedge_success_rate = Decimal('1') - hedge_failure_rate

        # 根据成功率选择阈值
        if hedge_success_rate >= self.config.adaptive_min_hedge_success_rate:
            # 高成功率：使用降低阈值
            return self.config.reduced_min_spread_rate
        elif hedge_success_rate >= Decimal('0.8'):
            # 中等成功率：使用中间值
            safe_threshold = self.config.adaptive_min_spread_rate_safe
            reduced_threshold = self.config.reduced_min_spread_rate
            # 线性插值
            mid_threshold = (safe_threshold + reduced_threshold) / Decimal('2')
            return mid_threshold
        else:
            # 低成功率：使用安全阈值
            return self.config.adaptive_min_spread_rate_safe

    def should_enable_reduced_thresholds(self) -> bool:
        """
        检查是否应该启用降低阈值

        条件：
        1. 对冲成功率>90%
        2. 仓位失衡率<20%

        Returns:
            True表示对冲成功率足够高，可以使用降低阈值
        """
        # 获取对冲成功率
        hedge_failure_rate = self.safety_monitor.get_hedge_failure_rate()
        hedge_success_rate = Decimal('1') - hedge_failure_rate

        # 获取仓位失衡率
        imbalance_rate = self.safety_monitor.get_position_imbalance_rate()

        # 检查条件
        success_ok = hedge_success_rate >= self.config.adaptive_min_hedge_success_rate
        imbalance_ok = imbalance_rate < Decimal('0.2')

        return success_ok and imbalance_ok

    async def update_thresholds(self) -> None:
        """
        定期更新阈值

        每adaptive_adjustment_interval秒调用一次
        """
        if not self.config.adaptive_threshold_enabled:
            return

        current_threshold = self.get_effective_min_spread_rate()
        should_enable_reduced = self.should_enable_reduced_thresholds()

        self.logger.info(
            f"动态阈值更新: 当前阈值={current_threshold:.4%}, "
            f"对冲成功率={1 - self.safety_monitor.get_hedge_failure_rate():.2%}, "
            f"仓位失衡率={self.safety_monitor.get_position_imbalance_rate():.2%}, "
            f"启用降低阈值={should_enable_reduced}"
        )
