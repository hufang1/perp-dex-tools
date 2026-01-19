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
    CloseModeDecision,  # 新增 (003-spreading-improvements)
)


logger = logging.getLogger(__name__)


class SmartCloseStrategy:
    """
    智能平仓策略

    平仓条件：开仓价差 >= 当前价差 + 盈利目标 + 手续费
    """

    def __init__(self, config: BotConfig, extended_client=None, lighter_client=None):
        """
        初始化策略

        Args:
            config: 机器人配置对象
            extended_client: Extended交易所客户端（可选，用于获取持仓信息）
            lighter_client: Lighter交易所客户端（可选，用于获取持仓信息）
        """
        self.config = config
        self.portfolio: Portfolio = Portfolio()
        self._last_log_time: float = 0
        self._log_interval: float = 5.0  # 每5秒输出一次日志

        # 新增 (003-spreading-improvements): 交易所客户端引用
        self.extended_client = extended_client
        self.lighter_client = lighter_client

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
                f"价差扩大: 当前{current_spread:.3%} > 开仓{entry_spread:.3%}"
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
                # 限制日志输出频率：每5秒一次
                import time
                current_time = time.time()
                if current_time - self._last_log_time >= self._log_interval:
                    logger.info(trigger.format_log())
                    self._last_log_time = current_time

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

    # ========== 新增方法 (003-spreading-improvements): 双模式平仓 ==========

    async def should_close(self, spread_info: RealTimeSpreadInfo) -> CloseModeDecision:
        """
        判断是否应该平仓（修改：返回三元组）

        (003-spreading-improvements: 修改为支持双模式平仓)
        根据利润水平选择市价平仓或限价平仓：
        - 利润大（价差收缩到市价阈值）：市价平仓，快速兑现
        - 利润小（价差收缩到限价阈值）：限价平仓，降低成本

        Args:
            spread_info: 当前价差信息

        Returns:
            CloseModeDecision: 包含是否平仓、原因、使用哪种模式
        """
        if not spread_info or not spread_info.is_valid():
            return CloseModeDecision(
                should_close=False,
                use_market=False,
                total_position_spread=Decimal("0"),
                current_spread=Decimal("0"),
                market_threshold=Decimal("0"),
                limit_threshold=Decimal("0"),
            )

        # 获取总开仓仓位的价差
        total_spread = await self.get_total_position_spread()
        if total_spread == 0:
            return CloseModeDecision(
                should_close=False,
                use_market=False,
                total_position_spread=Decimal("0"),
                current_spread=spread_info.spread_pct,
                market_threshold=Decimal("0"),
                limit_threshold=Decimal("0"),
            )

        current_spread = spread_info.spread_pct

        # 计算阈值（003-spreading-improvements: 使用新的配置参数）
        # 市价平仓阈值：当前价差 < 总开仓 - 市价阈值B
        market_threshold = total_spread - self.config.market_close_spread_b
        # 限价平仓阈值：当前价差 < 总开仓 - 限价阈值A
        limit_threshold = total_spread - self.config.limit_close_spread_a

        # 判断平仓模式
        if current_spread < market_threshold:
            # 市价平仓：利润大，立即兑现
            reason = (
                f"市价平仓 | 利润大 | "
                f"价差{current_spread:.3%} < 市价阈值{market_threshold:.3%}"
            )
            return CloseModeDecision(
                should_close=True,
                use_market=True,
                total_position_spread=total_spread,
                current_spread=current_spread,
                market_threshold=market_threshold,
                limit_threshold=limit_threshold,
                expected_profit_market=total_spread - current_spread,
            )
        elif current_spread < limit_threshold:
            # 限价平仓：利润小，使用限价单降低成本
            reason = (
                f"限价平仓 | 利润小 | "
                f"价差{current_spread:.3%} < 限价阈值{limit_threshold:.3%}"
            )
            return CloseModeDecision(
                should_close=True,
                use_market=False,
                total_position_spread=total_spread,
                current_spread=current_spread,
                market_threshold=market_threshold,
                limit_threshold=limit_threshold,
                expected_profit_limit=total_spread - current_spread,
            )
        else:
            # 不满足平仓条件
            return CloseModeDecision(
                should_close=False,
                use_market=False,
                total_position_spread=total_spread,
                current_spread=current_spread,
                market_threshold=market_threshold,
                limit_threshold=limit_threshold,
            )

    async def get_total_position_spread(self) -> Decimal:
        """
        获取总开仓仓位的价差（新增 003-spreading-improvements）

        优先从交易所API获取两个总仓位的平均开仓成本。
        如果API失败，使用Portfolio的加权平均作为降级策略。

        Returns:
            总开仓仓位的平均价差（lig_avg - ext_avg） / ext_avg
        """
        try:
            # 方案A：从交易所获取
            ext_avg, lig_avg = await self._fetch_exchange_avg_prices()
            if ext_avg > 0 and lig_avg > 0:
                total_spread = (lig_avg - ext_avg) / ext_avg
                logger.debug(f"从交易所获取平均价差: {total_spread:.3%}")
                return total_spread
        except Exception as e:
            logger.warning(f"从交易所获取平均价格失败: {e}，使用本地记录")

        # 方案B：使用本地记录的加权平均
        total_spread = self.portfolio.weighted_avg_entry_spread
        logger.debug(f"使用本地平均价差: {total_spread:.3%}")
        return total_spread

    async def _fetch_exchange_avg_prices(self) -> tuple[Decimal, Decimal]:
        """
        从交易所获取平均开仓价格（新增 003-spreading-improvements）

        并发查询两个交易所的持仓信息，获取平均开仓价格。

        Returns:
            (ext_avg_price, lig_avg_price): 两个交易所的平均开仓价格

        Raises:
            Exception: API调用失败时抛出
        """
        import asyncio

        # 检查客户端是否可用
        if not self.extended_client or not self.lighter_client:
            logger.warning("交易所客户端未注入，使用本地加权平均")
            return (Decimal("0"), Decimal("0"))

        try:
            # 并发查询两个交易所的持仓
            ext_pos_result, lig_pos_result = await asyncio.gather(
                self.extended_client.get_account_positions(),
                self.lighter_client.get_account_positions(),
                return_exceptions=True
            )

            # 处理Extended结果
            ext_avg_price = Decimal("0")
            if isinstance(ext_pos_result, Exception):
                logger.warning(f"获取Extended持仓失败: {ext_pos_result}")
            elif isinstance(ext_pos_result, dict) and 'avg_entry_price' in ext_pos_result:
                ext_avg_price = Decimal(str(ext_pos_result['avg_entry_price']))
            else:
                logger.warning(f"Extended持仓数据格式异常: {ext_pos_result}")

            # 处理Lighter结果
            lig_avg_price = Decimal("0")
            if isinstance(lig_pos_result, Exception):
                logger.warning(f"获取Lighter持仓失败: {lig_pos_result}")
            elif isinstance(lig_pos_result, dict) and 'avg_entry_price' in lig_pos_result:
                lig_avg_price = Decimal(str(lig_pos_result['avg_entry_price']))
            else:
                logger.warning(f"Lighter持仓数据格式异常: {lig_pos_result}")

            logger.debug(
                f"交易所平均价格: Ext={ext_avg_price:.2f}, Lig={lig_avg_price:.2f}"
            )

            return ext_avg_price, lig_avg_price

        except Exception as e:
            logger.error(f"查询交易所持仓异常: {e}")
            raise
