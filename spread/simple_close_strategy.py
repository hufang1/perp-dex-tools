"""
极简平仓策略模块

本模块实现012-dual-leg-concurrency的极简平仓逻辑，包括:
- 基于净价差的止盈止损判断
- 并发平仓执行
- 移除复杂的P1-P5优先级系统
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Dict, TYPE_CHECKING, Optional

from spread.config import SpreadArbConfig
from spread.models import SimpleCloseDecision, ConcurrentOrderResult
from spread.concurrent_executor import ConcurrentExecutor
from spread.ioc_order_manager import IocOrderManager

if TYPE_CHECKING:
    from spread.spread_pair import SpreadPair


class SimpleCloseStrategy:
    """
    极简平仓策略

    只监控当前净价差，基于止盈和止损阈值决定是否平仓。
    不考虑持仓时间等复杂因素。
    """

    def __init__(
        self,
        config: SpreadArbConfig,
        concurrent_executor: ConcurrentExecutor,
        ioc_order_manager: IocOrderManager,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """初始化极简平仓策略

        Args:
            config: SpreadArbConfig配置对象
            concurrent_executor: ConcurrentExecutor实例（用于并发平仓）
            ioc_order_manager: IocOrderManager实例（用于创建IOC平仓订单）
            logger: 日志记录器（可选）
        """
        self.config = config
        self.concurrent_executor = concurrent_executor
        self.ioc_order_manager = ioc_order_manager
        self.logger = logger or logging.getLogger(__name__)

    # ========================================================================
    # T071: 平仓决策判断
    # ========================================================================

    def should_close(
        self,
        pair: 'SpreadPair',
        current_extended_bid: Decimal,
        current_extended_ask: Decimal,
        current_lighter_bid: Decimal,
        current_lighter_ask: Decimal
    ) -> SimpleCloseDecision:
        """判断是否应该平仓（T071）

        Args:
            pair: 套利对
            current_extended_bid: 当前Extended买一价
            current_extended_ask: 当前Extended卖一价
            current_lighter_bid: 当前Lighter买一价
            current_lighter_ask: 当前Lighter卖一价

        Returns:
            SimpleCloseDecision对象

        算法:
            - 计算当前中间价差
            - 止盈: current_spread <= open_spread - target_profit
            - 止损: current_spread >= open_spread + stop_loss
        """
        # 计算当前中间价差
        current_extended_mid = (current_extended_bid + current_extended_ask) / Decimal('2')
        current_lighter_mid = (current_lighter_bid + current_lighter_ask) / Decimal('2')
        current_spread = current_extended_mid - current_lighter_mid

        # 计算当前价差率（相对于持有价格）
        if pair.extended_side == 'buy':
            # 做多价差
            current_spread_rate = current_spread / current_lighter_mid
        else:
            # 做空价差
            current_spread_rate = current_spread / current_extended_mid

        # T072: 使用SimpleCloseDecision.calculate_decision()
        decision = SimpleCloseDecision(
            open_spread_rate=pair.open_spread_rate,
            current_spread_rate=current_spread_rate,
            target_profit_rate=self.config.simple_close_target_profit_rate,
            stop_loss_rate=self.config.simple_close_stop_loss_rate,
            should_close=False,
            close_reason='hold'
        )

        decision.calculate_decision()

        return decision

    # ========================================================================
    # T073: 并发平仓执行
    # ========================================================================

    async def execute_close(
        self,
        pair: 'SpreadPair',
        extended_orderbook: Dict[str, Decimal],
        lighter_orderbook: Dict[str, Decimal]
    ) -> ConcurrentOrderResult:
        """执行并发平仓（T073）

        使用IOC订单进行并发平仓，确保快速成交。

        Args:
            pair: 套利对
            extended_orderbook: Extended订单簿 {'bid': Decimal, 'ask': Decimal}
            lighter_orderbook: Lighter订单簿 {'bid': Decimal, 'ask': Decimal}

        Returns:
            ConcurrentOrderResult对象

        算法:
            - 创建IOC平仓订单（方向与开仓相反）
            - 使用ConcurrentExecutor并发执行
        """
        # 构造平仓机会字典
        close_side = 'sell' if pair.extended_side == 'buy' else 'buy'

        opportunity = {
            'side': close_side,
            'quantity': pair.extended_quantity
        }

        # T018: 创建双腿IOC平仓订单
        extended_order, lighter_order = self.ioc_order_manager.create_dual_leg_orders(
            opportunity=opportunity,
            extended_orderbook=extended_orderbook,
            lighter_orderbook=lighter_orderbook
        )

        self.logger.info(
            f"📝 [并发平仓] pair_id={pair.pair_id}, "
            f"side={close_side}, quantity={pair.extended_quantity}"
        )

        # T019: 并发执行平仓订单
        result = await self.concurrent_executor.execute_dual_leg_orders(
            extended_order=extended_order,
            lighter_order=lighter_order,
            opportunity=opportunity
        )

        # 记录结果
        if result.is_both_filled:
            self.logger.info(
                f"✅ [并发平仓成功] pair_id={pair.pair_id}, "
                f"Extended: {result.extended_order_id}, "
                f"Lighter: {result.lighter_order_id}, "
                f"间隔: {result.send_gap_ms:.2f}ms"
            )
        elif result.is_legging:
            self.logger.error(
                f"⚠️ [并发平仓单腿] pair_id={pair.pair_id}, "
                f"需要后续处理"
            )
        else:
            self.logger.error(
                f"❌ [并发平仓失败] pair_id={pair.pair_id}, "
                f"Extended: {result.extended_error}, "
                f"Lighter: {result.lighter_error}"
            )

        return result

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def log_decision(self, decision: SimpleCloseDecision, pair_id: int) -> None:
        """记录平仓决策日志

        Args:
            decision: SimpleCloseDecision对象
            pair_id: 套利对ID
        """
        if decision.should_close:
            if decision.close_reason == 'take_profit':
                self.logger.info(
                    f"🎯 [止盈] pair_id={pair_id}, "
                    f"开仓价差: {decision.open_spread_rate:.4%}, "
                    f"当前价差: {decision.current_spread_rate:.4%}, "
                    f"价差变化: {decision.spread_delta:.4%}"
                )
            else:  # stop_loss
                self.logger.warning(
                    f"🛑 [止损] pair_id={pair_id}, "
                    f"开仓价差: {decision.open_spread_rate:.4%}, "
                    f"当前价差: {decision.current_spread_rate:.4%}, "
                    f"价差变化: {decision.spread_delta:.4%}"
                )
        else:
            self.logger.debug(
                f"⏳ [持有] pair_id={pair_id}, "
                f"开仓价差: {decision.open_spread_rate:.4%}, "
                f"当前价差: {decision.current_spread_rate:.4%}"
            )
