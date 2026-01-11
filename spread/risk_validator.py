"""
风控验证模块

本模块实现011-async-ws-ioc-trading的风控验证功能，包括:
- 开仓前综合验证
- 数据新鲜度验证
- 滑点验证
- 利润率验证
- 单腿持仓风险检测
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from spread.config import SpreadArbConfig
from spread.models import (
    DataFreshnessResult,
    ProfitabilityCheckResult,
    SlippageCheckResult,
)
from spread.performance_monitor import PerformanceMonitor


class RiskValidator:
    """
    风控验证器

    负责在开仓前进行所有必要的数据和风控检查。
    """

    def __init__(
        self,
        config: SpreadArbConfig,
        monitor: PerformanceMonitor,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """初始化风控验证器

        Args:
            config: SpreadArbConfig配置对象
            monitor: PerformanceMonitor实例
            logger: 日志记录器（可选）
        """
        self.config = config
        self.monitor = monitor
        self.logger = logger or logging.getLogger(__name__)

    # ========================================================================
    # 开仓前验证
    # ========================================================================

    def validate_opening(
        self,
        opportunity: Dict[str, Any],
        extended_ts: float,
        lighter_ts: float
    ) -> Tuple[bool, str]:
        """综合验证开仓条件

        Args:
            opportunity: 套利机会字典
            extended_ts: Extended数据时间戳
            lighter_ts: Lighter数据时间戳

        Returns:
            (是否有效, 原因)

        Example:
            is_valid, reason = validator.validate_opening(opportunity, ext_ts, lit_ts)
            # (True, "") 或 (False, "数据过期: Extended数据年龄623ms")
        """
        # 1. 数据新鲜度验证
        if self.config.enable_data_freshness_check:
            both_fresh, freshness_results = self.validate_data_freshness(extended_ts, lighter_ts)
            if not both_fresh:
                stale_info = ", ".join([
                    f"{r.exchange}: {r.data_age_ms:.0f}ms"
                    for r in freshness_results
                    if not r.is_fresh
                ])
                return False, f"数据过期: {stale_info}"

        # 2. 滑点验证
        if 'expected_price' in opportunity and 'current_price' in opportunity:
            slippage_result = self.validate_slippage(
                opportunity['expected_price'],
                opportunity['current_price'],
                opportunity.get('side', 'buy')
            )
            if not slippage_result.is_acceptable:
                return False, f"滑点超限: {slippage_result.slippage_rate:.4%}"

        # 3. 利润率验证
        if self.config.enable_profitability_check and 'spread_rate' in opportunity:
            profit_result = self.validate_profitability(opportunity['spread_rate'])
            if not profit_result.is_profitable:
                return False, f"利润不足: {profit_result.net_profit_rate:.4%}"

        return True, ""

    # ========================================================================
    # 数据新鲜度验证
    # ========================================================================

    def validate_data_freshness(
        self,
        extended_ts: float,
        lighter_ts: float
    ) -> Tuple[bool, List[DataFreshnessResult]]:
        """验证数据新鲜度

        Args:
            extended_ts: Extended数据时间戳
            lighter_ts: Lighter数据时间戳

        Returns:
            (都新鲜, [extended_result, lighter_result])
        """
        return self.monitor.check_both_data_freshness(extended_ts, lighter_ts)

    # ========================================================================
    # 滑点验证
    # ========================================================================

    def validate_slippage(
        self,
        expected_price: Decimal,
        current_price: Decimal,
        side: str
    ) -> SlippageCheckResult:
        """验证滑点

        参数和返回值同monitor.check_slippage()
        """
        return self.monitor.check_slippage(expected_price, current_price, side)

    # ========================================================================
    # 利润率验证
    # ========================================================================

    def validate_profitability(
        self,
        spread_rate: Decimal
    ) -> ProfitabilityCheckResult:
        """验证利润率

        参数和返回值同monitor.check_profitability()
        """
        return self.monitor.check_profitability(spread_rate)

    # ========================================================================
    # 单腿持仓检测
    # ========================================================================

    def check_leg_risk(
        self,
        extended_filled: bool,
        lighter_filled: bool
    ) -> Tuple[bool, str]:
        """检测单腿持仓风险

        Args:
            extended_filled: Extended是否成交
            lighter_filled: Lighter是否成交

        Returns:
            (有风险, 动作)

        Example:
            has_risk, action = check_leg_risk(True, False)
            # (True, "紧急平仓Extended")
        """
        if extended_filled and not lighter_filled:
            return True, "紧急平仓Extended"
        elif not extended_filled and lighter_filled:
            return True, "紧急平仓Lighter"
        elif not extended_filled and not lighter_filled:
            return True, "双边失败，无需平仓"
        else:
            return False, "双边成交，无风险"
