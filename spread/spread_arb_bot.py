"""
套利机器人主控制器：Lighter-Extended 单向价差收敛套利系统

负责：
1. 协调所有组件
2. 执行主交易循环
3. 处理订单簿更新
4. 状态管理和持久化
5. 信号处理（优雅关闭）
"""

import asyncio
import signal
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
import argparse
import os

from models import (
    BotState,
    BotConfig,
    Position,
    PositionState,
    BotStats,
    Trade,
    SpreadInfo,
    OpenPosition,
)
from order_book_manager import OrderBookManager
from spread_calculator import SpreadCalculator
from risk_manager import RiskManager
from trade_executor import TradeExecutor, ExecutionResult
from state_manager import StateManager
from exceptions import SpreadArbError, SingleSideExecutionError
from spread_monitor import SpreadMonitor
from arithmetic_open_strategy import ArithmeticOpenStrategy
from smart_close_strategy import SmartCloseStrategy
from position_balance_checker import PositionBalanceChecker

# 设置日志（仅输出错误）
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class SpreadArbBot:
    """
    套利机器人主控制器

    协调所有组件，执行价差套利策略
    """

    def __init__(self, config: BotConfig):
        """
        初始化机器人

        Args:
            config: 配置对象
        """
        self.config = config

        # 组件初始化（稍后在 start 方法中完成）
        self.order_book_manager: Optional[OrderBookManager] = None
        self.spread_monitor: Optional[SpreadMonitor] = None
        self.open_strategy: Optional[ArithmeticOpenStrategy] = None
        self.close_strategy: Optional[SmartCloseStrategy] = None
        self.balance_checker: Optional[PositionBalanceChecker] = None
        self.spread_calculator: Optional[SpreadCalculator] = None
        self.risk_manager: Optional[RiskManager] = None
        self.trade_executor: Optional[TradeExecutor] = None
        self.state_manager: Optional[StateManager] = None
        self.lighter_client = None
        self.extended_client = None

        # 运行状态
        self._running = False
        self._stop_event = asyncio.Event()

        # 统计信息
        self.start_time: Optional[datetime] = None

        # 订单簿同步任务
        self._orderbook_sync_task: Optional[asyncio.Task] = None

        # 开仓等待确认
        self._opening_wait_start_time: Optional[float] = None
        # 开仓失败冷却期（秒）
        self._open_cooldown: float = 10.0  # 增加到10秒
        self._last_open_fail_time: Optional[float] = None
        # 开仓成功冷却期（防止频繁开仓）
        self._last_open_success_time: Optional[float] = None
        self._open_success_cooldown: float = 3.0  # 成功后3秒冷却
        # 持仓日志输出间隔（秒）
        self._last_holding_log_time: float = 0
        self._holding_log_interval: float = 5.0  # 每5秒输出一次

        logger.debug("套利机器人初始化完成")
        logger.debug(f"配置: 交易对={config.symbol}, "
                   f"数量={config.target_quantity}, "
                   f"开仓阈值={config.min_spread_threshold:.2%}, "
                   f"最小利润={config.min_profit:.2%}")

    async def start(self) -> None:
        """启动机器人"""
        logger.debug("=" * 50)
        logger.info("启动机器人...")
        logger.debug("=" * 50)

        try:
            self.start_time = datetime.now()

            # 1. 初始化交易所客户端
            await self._init_clients()

            # 2. 初始化组件
            await self._init_components()

            # 3. 加载状态
            await self._load_state()

            # 4. 启动订单簿连接
            await self.order_book_manager.start()

            # 5. 启动价差监控器 (016-spread-optimize)
            await self.spread_monitor.start()

            # 6. 启动订单簿同步任务
            self._orderbook_sync_task = asyncio.create_task(self._sync_orderbooks_loop())

            # 7. 启动自动保存
            # await self.state_manager.start_auto_save()

            # 8. 设置信号处理
            self._setup_signal_handlers()

            # 9. 等待价差监控准备好
            logger.info("等待价差监控准备就绪...")
            import time as time_module
            wait_start = time_module.time()
            while True:
                spread_info = self.spread_monitor.get_current_spread()
                if spread_info is not None and spread_info.is_valid():
                    logger.info(f"价差监控就绪 (耗时{time_module.time() - wait_start:.1f}秒)")
                    break
                if time_module.time() - wait_start > 10:  # 最多等待10秒
                    logger.warning("价差监控等待超时，继续启动...")
                    break
                await asyncio.sleep(0.5)  # 每500ms检查一次

            # 10. 运行主交易循环
            self._running = True
            await self.run_trading_loop()

        except Exception as e:
            logger.error(f"启动失败: {e}", exc_info=True)
            await self.stop()
            raise

    async def stop(self) -> None:
        """停止机器人"""
        if not self._running:
            return

        logger.info("正在停止机器人...")
        self._running = False
        self._stop_event.set()

        try:
            # 停止订单簿同步任务（带超时）
            if self._orderbook_sync_task:
                self._orderbook_sync_task.cancel()
                try:
                    await asyncio.wait_for(self._orderbook_sync_task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                self._orderbook_sync_task = None

            # 停止自动保存（带超时）
            if self.state_manager:
                try:
                    await asyncio.wait_for(self.state_manager.stop_auto_save(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("停止自动保存超时")

            # 保存最终状态（带超时）
            if self.state_manager:
                try:
                    await asyncio.wait_for(self.state_manager.save_state(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("保存状态超时")

            # 停止订单簿连接（带超时）
            if self.order_book_manager:
                try:
                    await asyncio.wait_for(self.order_book_manager.stop(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("停止订单簿连接超时")

            # 停止价差监控器（带超时）
            if self.spread_monitor:
                try:
                    await asyncio.wait_for(self.spread_monitor.stop(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("停止价差监控器超时")

            # 打印统计信息
            self._print_stats()

            logger.info("机器人已停止")

        except Exception as e:
            logger.error(f"停止时出错: {e}", exc_info=True)

    async def run_trading_loop(self) -> None:
        """运行主交易循环"""
        logger.debug("主交易循环已启动")

        check_interval = 1.0  # 每秒检查一次

        while not self._stop_event.is_set():
            try:
                # 获取当前状态
                state = self.state_manager.get_state()

                if state == BotState.IDLE:
                    await self._process_idle_state()

                elif state == BotState.HOLDING:
                    await self._process_holding_state()

                elif state == BotState.OPENING:
                    await self._process_opening_state()

                elif state == BotState.OPENING_WAIT:
                    await self._process_opening_wait_state()

                elif state == BotState.CLOSING:
                    await self._process_closing_state()

                elif state == BotState.ERROR:
                    logger.error("处于错误状态，停止交易")
                    break

                # 等待下一次检查
                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                logger.info("交易循环被取消")
                break
            except Exception as e:
                logger.error(f"交易循环异常: {e}", exc_info=True)
                # 继续运行，不要因为单次错误而停止

    async def _process_idle_state(self) -> None:
        """处理 IDLE 状态：监控价差，寻找开仓机会"""
        if not self.order_book_manager.is_ready():
            logger.debug("订单簿未就绪，等待中...")
            return

        # 检查冷却期
        import time
        current_time = time.time()

        # 检查失败冷却期
        if self._last_open_fail_time is not None:
            elapsed = current_time - self._last_open_fail_time
            if elapsed < self._open_cooldown:
                logger.debug(f"失败冷却中，剩余{self._open_cooldown - elapsed:.1f}秒")
                return

        # 检查成功冷却期
        if self._last_open_success_time is not None:
            elapsed = current_time - self._last_open_success_time
            if elapsed < self._open_success_cooldown:
                logger.debug(f"成功冷却中，剩余{self._open_success_cooldown - elapsed:.1f}秒")
                return

        # 使用SpreadMonitor获取当前价差 (016-spread-optimize)
        spread_info = self.spread_monitor.get_current_spread()

        if spread_info is None or not spread_info.is_valid():
            return

        # 使用等差数列开仓策略判断 (016-spread-optimize)
        should_open, reason = self.open_strategy.should_open(spread_info)

        if should_open:
            logger.info(reason)

            # 风控验证
            validation = await self.risk_manager.validate_open_position(
                self.order_book_manager,
                self.config.target_quantity,
                spread_info
            )

            if not validation.is_valid:
                logger.warning(f"开仓风控失败: {validation.reason}")
                return

            # 切换到开仓状态
            self.state_manager.set_state(BotState.OPENING, f"价差{spread_info.spread_pct:.2%} > 阈值{self.config.min_spread_threshold:.2%}")
            await self.state_manager.save_state()
        else:
            # 输出不能开仓的原因，但限制频率（每5秒一次）
            if not hasattr(self, '_last_open_check_log_time'):
                self._last_open_check_log_time = 0
            current_time = time.time()
            if current_time - self._last_open_check_log_time >= 5.0:
                logger.info(reason)
                self._last_open_check_log_time = current_time

    async def _process_opening_state(self) -> None:
        """处理 OPENING 状态：执行开仓"""
        logger.info("执行开仓...")

        # 使用SpreadMonitor获取当前价差 (016-spread-optimize)
        spread_info = self.spread_monitor.get_current_spread()

        if spread_info is None or not spread_info.is_valid():
            logger.warning("无法获取价差信息，取消开仓")
            self.state_manager.set_state(BotState.IDLE, "无法获取价差信息")
            await self.state_manager.save_state()
            return

        # 执行开仓
        result = await self.trade_executor.execute_open_position(
            self.config.target_quantity,
            spread_info
        )

        # 检查是否完全失败（没有订单ID）
        if result.extended_order_id is None and result.lighter_order_id is None:
            # 完全失败，进入IDLE和冷却期
            logger.error(f"开仓完全失败: {result.error_message}")
            import time
            self._last_open_fail_time = time.time()
            logger.info(f"进入冷却期 ({self._open_cooldown}秒)")
            self.state_manager.set_state(BotState.IDLE, f"开仓失败: {result.error_message}")
            self._opening_wait_start_time = None
            await self.state_manager.save_state()
            return

        # 不管订单状态如何，只要有订单ID就进入OPENING_WAIT状态
        # 在OPENING_WAIT状态中通过实际仓位检查来判断是否真的开仓成功
        # 这样可以避免订单状态查询延迟导致的误判

        # 创建持仓记录（先创建，后续在OPENING_WAIT中验证）
        position = Position(
            state=PositionState.LONG,
            extended_entry_price=result.extended_price or spread_info.ext_ask,
            lighter_entry_price=result.lighter_price or spread_info.lig_bid,
            entry_spread=spread_info.spread_pct,
            entry_time=datetime.now(),
            extended_quantity=self.config.target_quantity,
            lighter_quantity=-self.config.target_quantity,
            extended_order_id=result.extended_order_id,
            lighter_order_id=result.lighter_order_id,
        )

        self.state_manager.update_position(position)

        # 更新缓存价差 (016-spread-optimize)
        self.open_strategy.update_cached_spread(spread_info.spread_pct)

        # 添加仓位到智能平仓系统 (016-spread-optimize)
        open_position = OpenPosition(
            position_id=str(uuid.uuid4()),
            open_time=datetime.now().timestamp(),
            ext_price=result.extended_price or spread_info.ext_ask,
            lig_price=result.lighter_price or spread_info.lig_bid,
            open_spread=spread_info.spread_pct,
            quantity=self.config.target_quantity,
            ext_order_id=result.extended_order_id,
            lig_order_id=result.lighter_order_id,
            is_active=True,
        )
        self.close_strategy.add_position(open_position)

        if result.success:
            logger.info(
                f"订单发送成功: Ext={result.extended_price} Lig={result.lighter_price} "
                f"价差={spread_info.spread_pct:.2%}"
            )
        else:
            logger.warning(
                f"订单发送超时/部分成功: Ext_filled={result.extended_filled} "
                f"Lig_filled={result.lighter_filled}，等待仓位确认..."
            )

        import time
        self._opening_wait_start_time = time.time()
        # 记录开仓成功时间，触发成功冷却期
        self._last_open_success_time = time.time()
        logger.info(f"等待仓位确认 (超时{self.config.open_wait_timeout}s)")
        self.state_manager.set_state(BotState.OPENING_WAIT, f"订单已发送: Ext={result.extended_order_id}, Lig={result.lighter_order_id}")
        await self.state_manager.save_state()

    async def _process_holding_state(self) -> None:
        """处理 HOLDING 状态：监控价差，寻找平仓机会和继续开仓机会"""
        position = self.state_manager.get_position()

        if position is None:
            logger.warning("持仓信息丢失，返回 IDLE 状态")
            self.state_manager.set_state(BotState.IDLE, "持仓信息丢失")
            await self.state_manager.save_state()
            return

        # 使用SpreadMonitor获取当前价差 (016-spread-optimize)
        spread_info = self.spread_monitor.get_current_spread()

        if spread_info is None or not spread_info.is_valid():
            return

        # 检查是否可以继续开仓（等差数列策略）
        should_open, reason = self.open_strategy.should_open(spread_info)

        if should_open:
            # 可以继续开仓！切换到开仓状态
            # 风控验证
            validation = await self.risk_manager.validate_open_position(
                self.order_book_manager,
                self.config.target_quantity,
                spread_info
            )

            if not validation.is_valid:
                print(f"⚠️ 继续开仓风控失败: {validation.reason}")
            else:
                # 风控通过，切换到开仓状态
                self.state_manager.set_state(BotState.OPENING, f"继续开仓: {reason}")
                await self.state_manager.save_state()
                return  # 直接返回，不再执行后续逻辑

        # 输出持仓状态日志（格式：icon 状态「持仓中」 实时价差 下次阈值 开仓/不开仓）
        # 限制频率：每5秒输出一次
        import time
        current_time = time.time()
        if current_time - self._last_holding_log_time >= self._holding_log_interval:
            current_spread = spread_info.spread_pct
            cached_spread = self.config.cached_open_spread
            spread_step = self.config.spread_step

            if cached_spread == 0:
                next_threshold = self.config.min_spread_threshold
                threshold_info = f"阈值{next_threshold:.2%}"
            else:
                next_threshold = cached_spread + spread_step
                threshold_info = f"缓存{cached_spread:.2%}+步进{spread_step:.2%}={next_threshold:.2%}"

            status_text = "开仓" if should_open else "不开仓"
            print(f"📊 状态「持仓中」 实时价差{current_spread:.2%} 下次{threshold_info} {status_text}")
            self._last_holding_log_time = current_time

        # 使用智能平仓策略判断 (016-spread-optimize)
        trigger = self.close_strategy.should_close(spread_info)

        if trigger.is_triggered:
            logger.info(trigger.format_log())

            # 切换到平仓状态
            self.state_manager.set_state(BotState.CLOSING, f"利润目标达成: {trigger.reason}")
            await self.state_manager.save_state()

    async def _process_closing_state(self) -> None:
        """处理 CLOSING 状态：执行平仓"""
        logger.info("执行平仓...")

        position = self.state_manager.get_position()
        if position is None:
            logger.warning("持仓信息丢失")
            self.state_manager.set_state(BotState.IDLE, "持仓信息丢失")
            await self.state_manager.save_state()
            return

        # 执行平仓
        result = await self.trade_executor.execute_close_position(
            position,
            abs(position.extended_quantity)
        )

        if result.success:
            # 平仓成功，计算利润
            entry_spread = position.entry_spread
            close_spread = await self._calculate_close_spread_from_result(result)
            profit = self._calculate_profit(position, result)

            # 更新统计
            stats = self.state_manager.get_stats()
            stats.total_trades += 1
            if profit > 0:
                stats.profitable_trades += 1
            stats.total_profit += profit
            stats.total_fees += self._calculate_fees(position)
            stats.last_trade_time = datetime.now()
            self.state_manager.update_stats(stats)

            # 清除持仓
            self.state_manager.update_position(None)
            self.state_manager.set_state(BotState.IDLE, f"平仓成功: 利润=${profit:.2f}, 价差收敛={entry_spread - close_spread:.2%}")
            await self.state_manager.save_state()

            # 平掉所有仓位记录 (016-spread-optimize)
            self.close_strategy.close_all()

            logger.info(
                f"平仓成功: 利润=${profit:.2f}, "
                f"价差收敛={entry_spread - close_spread:.2%}"
            )

        else:
            # 平仓失败
            logger.error(f"平仓失败: {result.error_message}")
            # 保持 HOLDING 状态，等待下一次机会
            self.state_manager.set_state(BotState.HOLDING, f"平仓失败: {result.error_message}")
            await self.state_manager.save_state()

    async def _process_opening_wait_state(self) -> None:
        """处理 OPENING_WAIT 状态：等待确认仓位"""
        import time

        current_time = time.time()
        if self._opening_wait_start_time is None:
            self._opening_wait_start_time = current_time

        elapsed = current_time - self._opening_wait_start_time
        timeout = self.config.open_wait_timeout

        if elapsed > timeout:
            logger.warning(f"等待超时({elapsed:.1f}s)，强平")
            await self._force_close_positions()
            # 强平后进入冷却期
            self._last_open_fail_time = time.time()
            logger.info(f"强平完成，进入冷却期 ({self._open_cooldown}秒)")
            self.state_manager.set_state(BotState.IDLE, f"等待超时({elapsed:.1f}s)，已强平")
            self._opening_wait_start_time = None
            await self.state_manager.save_state()
            return

        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()

            logger.debug(f"仓位检查 Ext={ext_position} Lig={lig_position} {elapsed:.1f}s")

            tolerance = Decimal("0.001")
            expected_qty = self.config.target_quantity

            ext_has_position = abs(ext_position - expected_qty) < tolerance
            lig_has_position = abs(lig_position - expected_qty) < tolerance

            if ext_has_position and lig_has_position:
                logger.info(f"仓位确认 Ext={ext_position} Lig={lig_position} {elapsed:.1f}s")
                self.state_manager.set_state(BotState.HOLDING, f"仓位确认成功 Ext={ext_position} Lig={lig_position}")
                self._opening_wait_start_time = None
                await self.state_manager.save_state()
            elif elapsed >= 2.0:
                # 检查仓位是否不一致（任何一边没有预期仓位）
                if not ext_has_position or not lig_has_position:
                    logger.warning(f"仓位不一致 Ext={ext_position} Lig={lig_position}，强平")
                    await self._force_close_positions()
                    # 强平后进入冷却期
                    self._last_open_fail_time = time.time()
                    logger.info(f"强平完成，进入冷却期 ({self._open_cooldown}秒)")
                    self.state_manager.set_state(BotState.IDLE, f"仓位不一致 Ext={ext_position} Lig={lig_position}，已强平")
                    self._opening_wait_start_time = None
                    await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"仓位检查失败: {e}")

    async def _force_close_positions(self) -> None:
        """强制平掉所有仓位"""
        logger.warning("执行强制平仓")

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # 获取当前仓位
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()

                tolerance = Decimal("0.001")
                ext_has_pos = abs(ext_position) >= tolerance
                lig_has_pos = abs(lig_position) >= tolerance

                if not ext_has_pos and not lig_has_pos:
                    logger.info(f"无仓位需要平仓 Ext={ext_position} Lig={lig_position}")
                    return

                logger.warning(f"强制平仓(尝试{attempt+1}/{max_retries}) Ext={ext_position} Lig={lig_position}")

                # 并发强平两边（提高效率）
                close_tasks = []

                if ext_has_pos:
                    side = "sell" if ext_position > 0 else "buy"
                    close_tasks.append(("extended", abs(ext_position), side))

                if lig_has_pos:
                    side = "sell" if lig_position > 0 else "buy"
                    close_tasks.append(("lighter", abs(lig_position), side))

                # 执行强平
                for exchange, qty, side in close_tasks:
                    success = await self.trade_executor.rollback_position(exchange, qty, side)
                    if not success:
                        logger.error(f"{exchange.capitalize()}强平失败")

                # 等待订单生效
                await asyncio.sleep(1.0)

                # 验证最终仓位
                final_ext = await self.extended_client.get_account_positions()
                final_lig = await self.lighter_client.get_account_positions()

                final_ext_has = abs(final_ext) >= tolerance
                final_lig_has = abs(final_lig) >= tolerance

                if not final_ext_has and not final_lig_has:
                    logger.info(f"强制平仓成功 Ext={final_ext} Lig={final_lig}")
                    return
                else:
                    logger.warning(f"平仓后仍有仓位 Ext={final_ext} Lig={final_lig}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

            except Exception as e:
                logger.error(f"强制平仓异常(尝试{attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)

        logger.error("强制平仓重试用尽，可能存在残余仓位")

    async def _handle_single_side_execution(self, result: ExecutionResult) -> None:
        """处理单边成交"""
        logger.error("检测到单边成交，执行紧急强平")

        import time
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # 获取当前仓位
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()

                logger.warning(f"当前仓位 Ext={ext_position} Lig={lig_position}")

                # 强平有仓位的一边
                if ext_position != 0:
                    side = "sell" if ext_position > 0 else "buy"
                    success = await self.trade_executor.rollback_position(
                        "extended", abs(ext_position), side
                    )
                    if not success:
                        logger.error(f"Extended强平失败(尝试{attempt+1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue

                if lig_position != 0:
                    side = "sell" if lig_position > 0 else "buy"
                    success = await self.trade_executor.rollback_position(
                        "lighter", abs(lig_position), side
                    )
                    if not success:
                        logger.error(f"Lighter强平失败(尝试{attempt+1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue

                # 验证最终仓位
                await asyncio.sleep(0.5)  # 等待订单生效
                final_ext = await self.extended_client.get_account_positions()
                final_lig = await self.lighter_client.get_account_positions()

                tolerance = Decimal("0.001")
                if abs(final_ext) < tolerance and abs(final_lig) < tolerance:
                    logger.info(f"强平成功 Ext={final_ext} Lig={final_lig}")
                    return
                else:
                    logger.warning(f"强平后仍有仓位 Ext={final_ext} Lig={final_lig}(尝试{attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

            except Exception as e:
                logger.error(f"强平异常(尝试{attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)

        logger.error("强平重试次数用尽，可能存在残余仓位")

    async def _check_and_clean_positions(self) -> None:
        """启动时检查并清理残留仓位"""
        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()

            tolerance = Decimal("0.001")
            has_ext = abs(ext_position) >= tolerance
            has_lig = abs(lig_position) >= tolerance

            if not has_ext and not has_lig:
                logger.info("启动仓位检查: 无残留仓位")
                return

            # 有残留仓位，需要清理
            logger.warning(f"启动仓位检查: 发现残留 Ext={ext_position} Lig={lig_position}")

            # 检查状态文件记录的持仓
            state = self.state_manager.get_state()
            position = self.state_manager.get_position()

            if state == BotState.HOLDING and position:
                # 状态文件显示有持仓，检查是否匹配
                logger.info(f"状态记录持仓: {position.extended_quantity}/{position.lighter_quantity}")
                # 不清理，让程序继续处理
                return

            # 状态显示无持仓但实际有仓位，需要清理
            logger.warning("状态显示无持仓但实际有仓位，执行清理")

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if abs(ext_position) >= tolerance:
                        side = "sell" if ext_position > 0 else "buy"
                        await self.trade_executor.rollback_position("extended", abs(ext_position), side)

                    if abs(lig_position) >= tolerance:
                        side = "sell" if lig_position > 0 else "buy"
                        await self.trade_executor.rollback_position("lighter", abs(lig_position), side)

                    await asyncio.sleep(0.5)
                    final_ext = await self.extended_client.get_account_positions()
                    final_lig = await self.lighter_client.get_account_positions()

                    if abs(final_ext) < tolerance and abs(final_lig) < tolerance:
                        logger.info(f"残留仓位清理成功 Ext={final_ext} Lig={final_lig}")
                        return
                    else:
                        logger.warning(f"残留仓位仍有 Ext={final_ext} Lig={final_lig}")
                        ext_position = final_ext
                        lig_position = final_lig

                except Exception as e:
                    logger.error(f"清理残留仓位异常(尝试{attempt+1}): {e}")

            logger.error("清理残留仓位失败，请手动检查")

        except Exception as e:
            logger.error(f"仓位检查失败: {e}")

    def get_stats(self) -> BotStats:
        """获取统计信息"""
        return self.state_manager.get_stats()

    def get_status(self) -> Dict:
        """
        获取机器人状态

        Returns:
            状态信息字典
        """
        position = self.state_manager.get_position()
        stats = self.state_manager.get_stats()

        return {
            "state": self.state_manager.get_state().value,
            "position": {
                "state": position.state.value if position else None,
                "entry_spread": float(position.entry_spread) if position else None,
                "entry_time": position.entry_time.isoformat() if position and position.entry_time else None,
            } if position else None,
            "stats": {
                "total_trades": stats.total_trades,
                "profitable_trades": stats.profitable_trades,
                "total_profit": float(stats.total_profit),
                "win_rate": stats.win_rate,
            },
            "uptime": str(datetime.now() - self.start_time) if self.start_time else None,
        }

    # ========================================================================
    # 私有方法：初始化
    # ========================================================================

    async def _init_clients(self) -> None:
        """初始化交易所客户端"""
        logger.debug("初始化交易所客户端...")

        # 添加项目根目录到 sys.path 以便导入 exchanges 模块
        import sys
        from pathlib import Path
        import requests
        project_root = Path(__file__).parent.parent.absolute()
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        # 导入交易所客户端
        from exchanges.lighter import LighterClient
        from exchanges.extended import ExtendedClient

        # 简单的 Config 类来包装字典（支持属性访问）
        class Config:
            def __init__(self, config_dict):
                for key, value in config_dict.items():
                    setattr(self, key, value)

        # 获取 Lighter market_id
        lighter_base_url = "https://mainnet.zklighter.elliot.ai"
        lighter_market_url = f"{lighter_base_url}/api/v1/orderBooks"
        try:
            response = requests.get(lighter_market_url, headers={"accept": "application/json"}, timeout=10)
            response.raise_for_status()
            data = response.json()
            lighter_market_id = None
            for market in data.get("order_books", []):
                if market["symbol"] == self.config.symbol:
                    lighter_market_id = market["market_id"]
                    break
            if lighter_market_id is None:
                raise ValueError(f"Lighter market {self.config.symbol} not found")
        except Exception as e:
            logger.error(f"Failed to get Lighter market_id: {e}")
            raise

        # 创建配置字典
        lighter_config_dict = {
            'ticker': self.config.symbol,
            'contract_id': lighter_market_id,  # 使用获取到的 market_id
            'quantity': self.config.target_quantity,
            'tick_size': Decimal('0.01'),  # 将在获取合约信息时更新
            'close_order_side': 'sell'
        }

        extended_config_dict = {
            'ticker': self.config.symbol,
            'contract_id': '',  # 将在获取合约信息时设置
            'quantity': self.config.target_quantity,
            'tick_size': Decimal('0.01'),  # 将在获取合约信息时更新
            'close_order_side': 'sell'
        }

        # 使用 Config 类包装
        lighter_config = Config(lighter_config_dict)
        extended_config = Config(extended_config_dict)

        self.lighter_client = LighterClient(lighter_config)
        self.extended_client = ExtendedClient(extended_config)

        # 连接到交易所并建立 WebSocket 连接
        logger.info("连接到 Lighter 交易所...")
        await self.lighter_client.connect()

        logger.info("连接到 Extended 交易所...")
        await self.extended_client.connect()

        # 获取合约属性（设置 contract_id, tick_size 等）
        logger.info("获取合约属性...")

        # Lighter: 获取合约属性
        lighter_contract_id, lighter_tick_size = await self.lighter_client.get_contract_attributes()
        lighter_config_dict['contract_id'] = lighter_contract_id
        lighter_config_dict['tick_size'] = lighter_tick_size
        logger.info(f"Lighter 合约属性: contract_id={lighter_contract_id}, tick_size={lighter_tick_size}")

        # Extended: 获取合约属性
        extended_contract_id, extended_tick_size = await self.extended_client.get_contract_attributes()
        extended_config_dict['contract_id'] = extended_contract_id
        extended_config_dict['tick_size'] = extended_tick_size
        logger.info(f"Extended 合约属性: contract_id={extended_contract_id}, tick_size={extended_tick_size}")

        # 更新配置
        lighter_config = Config(lighter_config_dict)
        extended_config = Config(extended_config_dict)
        self.lighter_client.config = lighter_config
        self.extended_client.config = extended_config

        # 等待 WebSocket 连接建立
        logger.info("等待订单簿数据...")
        # await asyncio.sleep(3)

        logger.debug("交易所客户端初始化完成")

    async def _init_components(self) -> None:
        """初始化组件"""
        logger.debug("初始化组件...")

        # 订单簿管理器
        self.order_book_manager = OrderBookManager(self.config.symbol)

        # 价差监控器 (016-spread-optimize)
        self.spread_monitor = SpreadMonitor(
            self.order_book_manager,
            open_threshold=self.config.min_spread_threshold,
            slippage_buffer=self.config.slippage_buffer
        )

        # 等差数列开仓策略 (016-spread-optimize)
        self.open_strategy = ArithmeticOpenStrategy(self.config)

        # 智能平仓系统 (016-spread-optimize)
        self.close_strategy = SmartCloseStrategy(self.config)

        # 价差计算器
        self.spread_calculator = SpreadCalculator(
            open_threshold=self.config.min_spread_threshold,
            slippage_buffer=self.config.slippage_buffer,
            min_profit=self.config.min_profit,
            max_spread=self.config.max_spread
        )

        # 风控管理器
        self.risk_manager = RiskManager(
            self.lighter_client,
            self.extended_client,
            self.config
        )

        # 交易执行器
        self.trade_executor = TradeExecutor(
            self.lighter_client,
            self.extended_client,
            self.risk_manager,
            timeout=self.config.single_side_timeout
        )

        # 仓位平衡检测器 (016-spread-optimize)
        self.balance_checker = PositionBalanceChecker(
            self.lighter_client,
            self.extended_client,
            self.trade_executor,
            buffer_seconds=self.config.balance_check_buffer
        )

        # 状态管理器
        state_file = Path("logs") / "spread_arb_state.json"
        self.state_manager = StateManager(state_file)

        logger.debug("组件初始化完成")

    async def _load_state(self) -> None:
        """加载状态"""
        logger.debug("加载状态...")

        state = await self.state_manager.load_state()
        logger.debug(f"当前状态: {state.value}")

        # 程序重启后，如果是OPENING或OPENING_WAIT状态，重置为IDLE
        # 因为之前的开仓流程已经失效，需要重新开始
        if state in [BotState.OPENING, BotState.OPENING_WAIT]:
            logger.info(f"检测到未完成的{state.value}状态，重置为IDLE")
            self.state_manager.set_state(BotState.IDLE, "程序重启，重置未完成的开仓状态")
            await self.state_manager.save_state()

        # 检查HOLDING/CLOSING状态但实际没有持仓的情况
        if state in [BotState.HOLDING, BotState.CLOSING]:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            has_position = abs(ext_position) >= tolerance or abs(lig_position) >= tolerance

            if not has_position:
                logger.info(f"检测到{state.value}状态但实际无持仓，重置为IDLE")
                self.state_manager.set_state(BotState.IDLE, "程序重启，检测到无实际持仓，重置状态")
                await self.state_manager.save_state()
                await self.state_manager.save_state()

        position = self.state_manager.get_position()
        if position:
            logger.debug(f"持仓: {position.state.value}, "
                       f"数量={abs(position.extended_quantity)}, "
                       f"开仓价差={position.entry_spread:.2%}")

        # 检查交易所实际仓位
        await self._check_and_clean_positions()

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        _shutting_down = [False]  # 使用列表避免 nonlocal

        def signal_handler(signum, frame):
            if _shutting_down[0]:
                # 已经在关闭中，强制退出
                logger.warning("强制退出")
                import sys
                sys.exit(1)

            logger.info(f"收到信号 {signum}，正在关闭...")
            _shutting_down[0] = True
            self._stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def _sync_orderbooks_loop(self) -> None:
        """
        订单簿同步循环

        定期从交易所客户端获取订单簿数据并更新到 OrderBookManager
        """
        from decimal import Decimal

        # 等待客户端被初始化
        while not self._stop_event.is_set():
            if self.extended_client is not None and self.lighter_client is not None:
                break
            await asyncio.sleep(0.5)

        while not self._stop_event.is_set():
            try:
                # 从 Extended 客户端获取订单簿
                if hasattr(self.extended_client, 'orderbook') and self.extended_client.orderbook:
                    orderbook = self.extended_client.orderbook
                    bids = {}
                    asks = {}

                    # 转换 bids {price: quantity}
                    if orderbook.get('bid'):
                        for item in orderbook['bid']:
                            bids[Decimal(str(item['p']))] = Decimal(str(item['q']))

                    # 转换 asks {price: quantity}
                    if orderbook.get('ask'):
                        for item in orderbook['ask']:
                            asks[Decimal(str(item['p']))] = Decimal(str(item['q']))

                    if bids and asks:
                        self.order_book_manager.update_extended_order_book(
                            bids=bids,
                            asks=asks,
                            sequence=0,
                            is_snapshot=True
                        )

                # 从 Lighter 客户端获取订单簿
                if hasattr(self.lighter_client, 'ws_manager') and self.lighter_client.ws_manager:
                    best_bid = self.lighter_client.ws_manager.best_bid
                    best_ask = self.lighter_client.ws_manager.best_ask

                    if best_bid and best_ask:
                        # Lighter 只返回最佳买卖价
                        best_bid_dec = Decimal(str(best_bid))
                        best_ask_dec = Decimal(str(best_ask))

                        bids = {best_bid_dec: Decimal("1.0")}  # 数量设为1.0表示有流动性
                        asks = {best_ask_dec: Decimal("1.0")}

                        self.order_book_manager.update_lighter_order_book(
                            bids=bids,
                            asks=asks,
                            sequence=0,
                            is_snapshot=True
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"订单簿同步异常: {e}")

            # 每100ms同步一次
            await asyncio.sleep(0.1)

    # ========================================================================
    # 私有方法：辅助
    # ========================================================================

    def _print_stats(self) -> None:
        """打印统计信息（精简单行格式）"""
        stats = self.get_stats()

        # 单行格式: 统计: 交易10次 | 胜率60% | 净利润$0.50 | 运行时间1:23:45
        stats_str = (f"统计: 交易{stats.total_trades}次 | "
                    f"胜率{stats.win_rate:.1%} | "
                    f"净利润${stats.net_profit:.2f}")

        if stats.start_time:
            uptime = datetime.now() - stats.start_time
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            stats_str += f" | 运行{hours}:{minutes:02d}:{seconds:02d}"

        logger.info(stats_str)

    async def _calculate_close_spread_from_result(self, result: ExecutionResult) -> Decimal:
        """从执行结果计算平仓价差"""
        # 简化处理
        return Decimal("0.001")

    def _calculate_profit(self, position: Position, result: ExecutionResult) -> Decimal:
        """计算利润"""
        # 简化计算
        return self.config.target_quantity * position.entry_spread * position.extended_entry_price * Decimal("0.5")

    def _calculate_fees(self, position: Position) -> Decimal:
        """计算手续费"""
        # Extended 0.025% 双向 = 0.05%
        return self.config.target_quantity * position.extended_entry_price * Decimal("0.0005")


# ========================================================================
# 命令行接口
# ============================================================================

def parse_arguments() -> BotConfig:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Lighter-Extended 单向价差收敛套利系统"
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default="BTC",
        help="交易对 (默认: BTC)"
    )

    parser.add_argument(
        "--size",
        type=Decimal,
        default=Decimal("0.01"),
        dest="target_quantity",
        help="交易数量 (默认: 0.01)"
    )

    parser.add_argument(
        "--spread-threshold",
        type=Decimal,
        default=Decimal("0.0002"),
        dest="min_spread_threshold",
        help="最小价差阈值 (默认: 0.002 = 0.02%%)"
    )

    parser.add_argument(
        "--slippage-buffer",
        type=Decimal,
        default=Decimal("0.0001"),
        help="滑点保护 (默认: 0.0005 = 0.01%%)"
    )

    parser.add_argument(
        "--min-profit",
        type=Decimal,
        default=Decimal("0.001"),
        help="最小利润 (默认: 0.001 = 0.1%%)"
    )

    parser.add_argument(
        "--max-spread",
        type=Decimal,
        default=Decimal("0.05"),
        help="极端价差阈值 (默认: 0.05 = 5%%)"
    )

    parser.add_argument(
        "--spread-step",
        type=Decimal,
        default=Decimal("0.00005"),
        dest="spread_step",
        help="价差步进值 (默认: 0.00005 = 0.005%%) (016-spread-optimize)"
    )

    parser.add_argument(
        "--balance-buffer",
        type=float,
        default=3.0,
        dest="balance_check_buffer",
        help="仓位平衡检测缓冲期（秒） (默认: 3.0) (016-spread-optimize)"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        dest="single_side_timeout",
        help="单边超时时间（秒） (默认: 3.0)"
    )

    parser.add_argument(
        "--open-wait-timeout",
        type=float,
        default=10.0,
        dest="open_wait_timeout",
        help="开仓等待确认超时时间（秒） (默认: 10.0)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行模式"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志模式"
    )

    args = parser.parse_args()

    return BotConfig(
        symbol=args.symbol,
        target_quantity=args.target_quantity,
        min_spread_threshold=args.min_spread_threshold,
        slippage_buffer=args.slippage_buffer,
        min_profit=args.min_profit,
        max_spread=args.max_spread,
        spread_step=args.spread_step,
        balance_check_buffer=args.balance_check_buffer,
        single_side_timeout=args.single_side_timeout,
        open_wait_timeout=args.open_wait_timeout,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


async def main():
    """主函数"""
    # 解析配置
    config = parse_arguments()

    # 验证配置
    if not config.validate():
        logger.error("配置参数无效")
        sys.exit(1)

    # 检查环境变量（使用专用验证模块）
    from env_validator import check_env_before_start

    if not check_env_before_start():
        sys.exit(1)

    # 创建并启动机器人
    bot = SpreadArbBot(config)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
    except Exception as e:
        logger.error(f"运行异常: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # 使用 try-except 防止 stop() 中的错误影响退出
        try:
            await asyncio.wait_for(bot.stop(), timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            logger.warning("停止超时，强制退出")


if __name__ == "__main__":
    asyncio.run(main())
