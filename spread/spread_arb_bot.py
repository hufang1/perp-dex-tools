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
import csv
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
    Portfolio,
)
from order_book_manager import OrderBookManager
from spread_calculator import SpreadCalculator
from risk_manager import RiskManager
from trade_executor import TradeExecutor, ExecutionResult
from state_manager import StateManager
from exceptions import SpreadArbError, SingleSideExecutionError
from spread_monitor import SpreadMonitor
from price_monitor import PriceMonitor
from arithmetic_open_strategy import ArithmeticOpenStrategy
from smart_close_strategy import SmartCloseStrategy
from position_balance_checker import PositionBalanceChecker
from maker_order_monitor import MakerOrderMonitor
from models import MakerOrder
from position_balance_monitor import PositionBalanceMonitor

# 设置日志（输出 INFO 及以上级别）
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
        self.price_monitor: Optional[PriceMonitor] = None
        self.open_strategy: Optional[ArithmeticOpenStrategy] = None
        self.close_strategy: Optional[SmartCloseStrategy] = None
        self.balance_checker: Optional[PositionBalanceChecker] = None
        self.spread_calculator: Optional[SpreadCalculator] = None
        self.risk_manager: Optional[RiskManager] = None
        self.trade_executor: Optional[TradeExecutor] = None
        self.state_manager: Optional[StateManager] = None
        self.lighter_client = None
        self.extended_client = None
        self.maker_order_monitor: Optional[MakerOrderMonitor] = None

        # 运行状态
        self._running = False
        self._stop_event = asyncio.Event()

        # 统计信息
        self.start_time: Optional[datetime] = None

        # 订单簿同步任务
        self._orderbook_sync_task: Optional[asyncio.Task] = None

        # 开仓等待确认
        self._opening_wait_start_time: Optional[float] = None
        # 待确认的仓位（仓位确认成功后才添加到智能平仓系统）
        self._pending_open_position = None
        # 开仓失败冷却期（秒）
        self._open_cooldown: float = 10.0  # 增加到10秒
        self._last_open_fail_time: Optional[float] = None
        # 开仓成功冷却期（防止频繁开仓）
        self._last_open_success_time: Optional[float] = None
        self._open_success_cooldown: float = 3.0  # 成功后3秒冷却
        # 最后开仓时间（用于防止连续开仓导致 API 限流）
        self._last_open_time: Optional[float] = None

        # 平仓等待确认
        self._closing_wait_start_time: Optional[float] = None
        # 平仓等待超时时间（秒）
        self._close_wait_timeout: float = 10.0
        # 持仓日志输出间隔（秒）
        self._last_holding_log_time: float = 0
        self._holding_log_interval: float = 5.0  # 每5秒输出一次
        # API错误计数和风控模式
        self._api_error_count: int = 0
        self._paused_start_time: Optional[float] = None
        self._last_api_check_time: Optional[float] = None

        # CSV埋点日志
        self._csv_log_dir = Path("logs/trades")
        self._csv_log_dir.mkdir(parents=True, exist_ok=True)
        self._init_csv_loggers()
        self._api_error_count: int = 0

        # 实时价差CSV记录
        self._last_spread_log_time: float = 0
        self._spread_log_interval: float = 10.0  # 每10秒记录一次实时价差
        self._api_error_threshold: int = 3  # 连续3次错误进入风控模式
        self._paused_start_time: Optional[float] = None
        self._paused_check_interval: float = 10.0  # 每10秒检查API是否恢复
        self._last_api_check_time: float = 0

        logger.debug("套利机器人初始化完成")
        logger.debug(f"配置: 交易对={config.symbol}, "
                   f"数量={config.target_quantity}, "
                   f"开仓阈值={config.min_spread_threshold:.3%}, "
                   f"最小利润={config.min_profit:.3%}")
        # ========== 新增: 打印阶梯开仓配置用于调试 ==========
        print(f"🔧 [配置初始化] 阶梯开仓参数:")
        print(f"   - initial_open_spread = {config.initial_open_spread} ({config.initial_open_spread:.3%})")
        print(f"   - spread_step = {config.spread_step} ({config.spread_step:.3%})")
        print(f"   - opening_count = {config.opening_count}")
        print(f"   - current_open_threshold = {config.current_open_threshold} ({config.current_open_threshold:.3%})")
        logger.info(f"阶梯开仓配置: initial={config.initial_open_spread:.3%}, step={config.spread_step:.3%}, count={config.opening_count}, current_threshold={config.current_open_threshold:.3%}")

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

            # 2.5 设置 Extended 订单更新处理（WebSocket 订单监控）
            self.extended_client.setup_order_update_handler(self._handle_extended_order_update)
            logger.info("Extended 订单更新处理已设置")

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

                elif state == BotState.OPENING_MAKER_WAIT:  # 新增 (017-ext-maker-mode)
                    await self._process_opening_maker_wait_state()

                elif state == BotState.OPENING_WAIT:
                    await self._process_opening_wait_state()

                elif state == BotState.CLOSING:
                    await self._process_closing_state()

                elif state == BotState.CLOSING_MAKER_WAIT:  # 新增 (017-ext-maker-mode)
                    await self._process_closing_maker_wait_state()

                elif state == BotState.LIGHTER_HEDGING:  # 新增 (017-ext-maker-mode)
                    await self._process_lighter_hedging_state()

                elif state == BotState.CLOSING_WAIT:
                    await self._process_closing_wait_state()

                elif state == BotState.PAUSED:
                    await self._process_paused_state()

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

        # 检查是否有仓位需要处理（回滚后的仓位恢复）
        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")

            # 检查是否有仓位
            has_position = abs(ext_position) >= tolerance or abs(lig_position) >= tolerance

            if has_position:
                # 有仓位：检查是否平衡（两边相等）
                position_diff = abs(ext_position - lig_position)

                if position_diff < tolerance:
                    # 两边仓位相等，说明是正常持仓
                    if abs(ext_position) >= tolerance:
                        # 有正常持仓，进入 HOLDING 状态
                        logger.info(f"检测到正常持仓 Ext={ext_position} Lig={lig_position}，进入持仓状态")
                        self.state_manager.set_state(BotState.HOLDING, "回滚后恢复持仓状态")
                        await self.state_manager.save_state()
                        return
                    else:
                        # 没有实际持仓，保持 IDLE 状态
                        logger.info(f"无实际持仓 Ext={ext_position} Lig={lig_position}，保持空闲状态")
                        return
                else:
                    # 两边仓位不相等，说明是异常（残留），需要强制清理
                    logger.error(f"发现异常仓位（不平衡） Ext={ext_position} Lig={lig_position}，强制清理中...")
                    await self._force_close_positions()
                    # 清理后返回，等待下一个循环
                    return
        except Exception as e:
            logger.warning(f"检查仓位失败: {e}")
            # 如果检查失败，不阻止开仓（避免卡死）

        # 使用SpreadMonitor获取当前价差 (016-spread-optimize)
        spread_info = self.spread_monitor.get_current_spread()

        if spread_info is None or not spread_info.is_valid():
            return

        # ========== 新增 (017-ext-maker-mode): Maker模式使用固定阈值 ==========
        if self.config.use_maker_mode:
            # Maker模式：使用阶梯开仓阈值 (003-spreading-improvements: 改为使用阶梯阈值)
            should_open, reason = self.open_strategy.should_open(spread_info)
            current_threshold = self.config.current_open_threshold
            threshold_info = f"开仓阈值{current_threshold:.3%}(阶梯:次{self.config.opening_count},初{self.config.initial_open_spread:.3%},步{self.config.spread_step:.3%})"
        else:
            # Taker模式：使用阶梯开仓策略 (003-spreading-improvements)
            should_open, reason = self.open_strategy.should_open(spread_info)
            # 使用新的 current_open_threshold 显示当前阶梯阈值
            current_threshold = self.config.current_open_threshold
            threshold_info = f"开仓阈值{current_threshold:.3%}(阶梯:次{self.config.opening_count},初{self.config.initial_open_spread:.3%},步{self.config.spread_step:.3%})"

        # 输出空闲状态监控日志（每5秒一次）
        if not hasattr(self, '_last_idle_log_time'):
            self._last_idle_log_time = 0
        current_time = time.time()
        if current_time - self._last_idle_log_time >= 5.0:
            current_spread = spread_info.spread_pct
            status_text = "开仓" if should_open else "不开仓"
            # ========== 新增: 添加计算公式的调试信息 ==========
            calc_formula = f"{self.config.initial_open_spread:.3%}+({self.config.opening_count}*{self.config.spread_step:.3%})={self.config.current_open_threshold:.3%}"
            print(f"📊 状态「空闲」 实时价差{current_spread:.3%} 下次{threshold_info} 计算:{calc_formula} {status_text}")
            self._last_idle_log_time = current_time

        # 记录实时价差到CSV（每10秒一次）
        if current_time - self._last_spread_log_time >= self._spread_log_interval:
            self._log_spread_to_csv(spread_info)
            self._last_spread_log_time = current_time

        # ========== 新增: 调试日志 ==========
        if should_open:
            print(f"🔍 [开仓触发] should_open=True, 准备执行开仓流程...")

        if should_open:
            # 风控验证
            print(f"🔍 [开仓触发] 开始风控验证...")
            validation = await self.risk_manager.validate_open_position(
                self.order_book_manager,
                self.config.target_quantity,
                spread_info
            )

            if not validation.is_valid:
                print(f"🔍 [开仓触发] 风控验证失败: {validation.reason}")
                logger.warning(f"开仓风控失败: {validation.reason}")
                return

            print(f"🔍 [开仓触发] 风控验证通过，开始余额检测...")

            # ========== 新增 (003-spreading-improvements): 余额检测 ==========
            balance_result = await self.funds_checker.check_before_opening(
                target_quantity=self.config.target_quantity,
                ext_price=spread_info.ext_ask,  # Extended买入价格
                lig_price=spread_info.lig_bid   # Lighter卖出价格
            )

            if not balance_result.is_sufficient:
                print(f"🔍 [开仓触发] 余额检测失败: {balance_result.format_log()}")
                logger.warning(f"余额不足，跳过本次开仓: {balance_result.format_log()}")
                return

            print(f"🔍 [开仓触发] 余额检测通过，准备切换到OPENING状态...")

            # 切换到开仓状态
            # ========== 修改 (003-spreading-improvements): 统一使用阶梯开仓阈值 ==========
            current_threshold = self.config.current_open_threshold
            self.state_manager.set_state(
                BotState.OPENING,
                f"价差{spread_info.spread_pct:.3%} >= 阶梯开仓阈值{current_threshold:.3%}(次{self.config.opening_count})"
            )
            await self.state_manager.save_state()

    async def _process_opening_state(self) -> None:
        """处理 OPENING 状态：执行开仓"""
        logger.info("执行开仓...")

        # 记录开仓时间（用于防止连续开仓导致 API 限流）
        import time
        self._last_open_time = time.time()

        # 使用SpreadMonitor获取当前价差 (016-spread-optimize)
        spread_info = self.spread_monitor.get_current_spread()

        if spread_info is None or not spread_info.is_valid():
            logger.warning("无法获取价差信息，取消开仓")
            self.state_manager.set_state(BotState.IDLE, "无法获取价差信息")
            await self.state_manager.save_state()
            return

        # ========== 新增 (017-ext-maker-mode): Maker模式分支 ==========
        if self.config.use_maker_mode:
            await self._process_opening_maker_mode(spread_info)
        else:
            await self._process_opening_taker_mode(spread_info)

    async def _process_opening_maker_mode(self, spread_info) -> None:
        """处理Maker模式开仓"""
        try:
            # 下Extended Maker订单
            result = await self.trade_executor.place_maker_open_order(
                self.config.target_quantity
            )

            if not result.success or result.extended_order_id is None:
                logger.error(f"Extended Maker开仓订单失败: {result.error_message}")
                self.state_manager.set_state(BotState.IDLE, "Maker订单失败")
                await self.state_manager.save_state()
                return

            # 初始化Maker等待状态
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()

            self._maker_wait_state.current_order = MakerOrder(
                order_id=result.extended_order_id,
                price=result.extended_price,
                quantity=self.config.target_quantity,
                side='buy',
                is_opening=True
            )
            self._maker_wait_state.start_time = datetime.now()

            # 启动 WebSocket 订单监控
            self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

            logger.info(
                f"✅ Extended Maker开仓订单已挂出 | "
                f"order_id={result.extended_order_id} | "
                f"price={result.extended_price} | "
                f"quantity={self.config.target_quantity}"
            )

            # 进入OPENING_MAKER_WAIT状态
            self.state_manager.set_state(
                BotState.OPENING_MAKER_WAIT,
                f"Maker订单已挂出: {result.extended_order_id}"
            )
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"Maker模式开仓异常: {e}")
            self.state_manager.set_state(BotState.IDLE, f"开仓异常: {e}")
            await self.state_manager.save_state()

    async def _process_opening_taker_mode(self, spread_info) -> None:
        """处理Taker模式开仓（原有逻辑）"""
        # 执行开仓
        result = await self.trade_executor.execute_open_position(
            self.config.target_quantity,
            spread_info
        )

        # 不管订单状态如何，都进入 OPENING_WAIT 状态检查实际仓位
        # 即使订单返回失败，也可能有部分成交（或者订单还在处理中）
        # 通过实际仓位检查来判断是否真的开仓成功，避免遗漏单边成交

        # 检查是否完全失败（两边都没有订单ID）
        if result.extended_order_id is None and result.lighter_order_id is None:
            logger.error(f"订单发送完全失败: {result.error_message}，仍需检查仓位以防部分成交")
        else:
            logger.info(f"订单已发送: Ext={result.extended_order_id}, Lig={result.lighter_order_id}")

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

        # 注意：不在这里更新 cached_open_spread！
        # 需要等到仓位确认成功后再更新（在 OPENING_WAIT 状态中）
        # 如果仓位确认失败并回滚，cached_open_spread 保持不变

        # 注意：不在这里添加仓位到智能平仓系统！
        # 需要等到仓位确认成功后再添加（在 OPENING_WAIT 状态中）
        # 预创建 OpenPosition 对象，等待确认后添加
        self._pending_open_position = OpenPosition(
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

        # 输出订单状态信息
        if result.success:
            logger.info(
                f"订单发送成功: Ext={result.extended_price} Lig={result.lighter_price} "
                f"价差={spread_info.spread_pct:.3%}"
            )
        elif result.extended_order_id or result.lighter_order_id:
            # 有订单ID但订单状态不是成功
            logger.warning(
                f"订单发送超时/部分成功: Ext_filled={result.extended_filled} "
                f"Lig_filled={result.lighter_filled}，等待仓位确认..."
            )
        else:
            # 完全失败（没有订单ID）
            logger.error(
                f"订单发送失败: {result.error_message}，仍需检查仓位以防部分成交"
            )

        # 进入 OPENING_WAIT 状态验证仓位（不管订单状态如何）
        import time
        self._opening_wait_start_time = time.time()
        self._last_open_success_time = time.time()
        logger.info(f"等待仓位确认 (超时{self.config.open_wait_timeout}s)")
        self.state_manager.set_state(BotState.OPENING_WAIT, f"订单已发送: Ext={result.extended_order_id}, Lig={result.lighter_order_id}")
        await self.state_manager.save_state()

    async def _process_holding_state(self) -> None:
        """处理 HOLDING 状态：监控价差，寻找平仓机会和继续开仓机会"""
        # 使用 Portfolio 检查持仓（替代旧的 Position 对象）
        total_quantity = self.close_strategy.get_total_quantity()

        if total_quantity <= 0:
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
                # 风控通过，等待一段时间确保前一次开仓的订单查询已完成
                # 防止 Extended API 限流（两次开仓太近会导致订单查询冲突）
                import time
                current_time = time.time()

                # 检查距离上次开仓的时间
                if hasattr(self, '_last_open_time') and self._last_open_time is not None:
                    elapsed_since_last_open = current_time - self._last_open_time
                    min_interval = 5.0  # 最小间隔 5 秒

                    if elapsed_since_last_open < min_interval:
                        wait_time = min_interval - elapsed_since_last_open
                        logger.info(f"等待 {wait_time:.1f} 秒后继续开仓（避免 API 限流）")
                        await asyncio.sleep(wait_time)

                # 检查是否已有持仓（继续开仓 vs 首次开仓）
                has_existing_position = self.close_strategy.get_total_quantity() > 0

                if has_existing_position:
                    # 已有持仓，这是继续开仓（加仓）
                    # 切换到 OPENING 状态（输出状态转换日志）
                    self.state_manager.set_state(BotState.OPENING, f"继续开仓（加仓）: {reason}")
                    self._last_open_time = current_time  # 记录开仓时间
                    await self.state_manager.save_state()
                    # 加仓逻辑会在 OPENING 状态中处理
                else:
                    # 首次开仓，正常走 OPENING 流程
                    self.state_manager.set_state(BotState.OPENING, f"首次开仓: {reason}")
                    self._last_open_time = current_time  # 记录开仓时间
                    await self.state_manager.save_state()

                return  # 直接返回，不再执行后续逻辑

        # 输出持仓状态日志（格式：icon 状态「持仓中」 实时价差，下一次开仓价差，平仓需要价差，结果）
        # 限制频率：每5秒输出一次
        import time
        current_time = time.time()
        if current_time - self._last_holding_log_time >= self._holding_log_interval:
            current_spread = spread_info.spread_pct
            cached_spread = self.config.cached_open_spread
            spread_step = self.config.spread_step

            # 计算下一次开仓价差
            if cached_spread == 0:
                next_open_threshold = self.config.min_spread_threshold
                open_formula = f">={next_open_threshold:.3%}"
            else:
                next_open_threshold = cached_spread + spread_step
                open_formula = f">=(上次开仓{cached_spread:.3%}+步长{spread_step:.3%}={next_open_threshold:.3%})"

            # 计算平仓价差（从 close_strategy 的 portfolio 获取加权平均开仓价差，与实际平仓判断保持一致）
            entry_spread = self.close_strategy.get_weighted_avg_spread()
            if entry_spread > 0:
                close_threshold = entry_spread - self.config.min_profit - self.config.total_fee_rate
                close_formula = f"<=(开仓{entry_spread:.3%}-利润{self.config.min_profit:.3%}-手续费{self.config.total_fee_rate:.3%}={close_threshold:.3%})"
            else:
                close_formula = ""

            # ========== 新增 (003-spreading-improvements): 判断结果（双模式平仓） ==========
            decision = await self.close_strategy.should_close(spread_info)
            if decision.should_close:
                close_mode = "市价" if decision.use_market else "限价"
                result = f"平仓({close_mode})"
            elif should_open:
                result = "开仓"
            else:
                result = "不开仓不平仓"

            # 组合日志，用括号组织逻辑
            if close_formula:
                print(f"📊 状态「持仓中」 实时价差{current_spread:.3%}（下一次开仓需价差{open_formula}，平仓需价差{close_formula}），结果：{result}")
            else:
                print(f"📊 状态「持仓中」 实时价差{current_spread:.3%}（下一次开仓需价差{open_formula}），结果：{result}")
            self._last_holding_log_time = current_time

        # 记录实时价差到CSV（每10秒一次）
        if current_time - self._last_spread_log_time >= self._spread_log_interval:
            self._log_spread_to_csv(spread_info)
            self._last_spread_log_time = current_time

        # ========== 新增 (003-spreading-improvements): 使用双模式平仓策略 ==========
        decision = await self.close_strategy.should_close(spread_info)

        if decision.should_close:
            # 根据利润水平选择平仓模式
            total_quantity = self.close_strategy.get_total_quantity()

            if decision.use_market:
                # 市价平仓：立即执行
                await self._execute_market_close(total_quantity)
                logger.info(
                    f"市价平仓触发 | 开仓{decision.total_position_spread:.3%} | "
                    f"当前{decision.current_spread:.3%} < 市价阈值{decision.market_threshold:.3%} | "
                    f"预期利润{decision.expected_profit_market:.3%}"
                )
            else:
                # 限价平仓：挂单等待成交
                await self._execute_limit_close(total_quantity)
                logger.info(
                    f"限价平仓触发 | 开仓{decision.total_position_spread:.3%} | "
                    f"当前{decision.current_spread:.3%} < 限价阈值{decision.limit_threshold:.3%} | "
                    f"预期利润{decision.expected_profit_limit:.3%}"
                )

            await self.state_manager.save_state()

    async def _process_closing_state(self) -> None:
        """处理 CLOSING 状态：执行平仓"""
        logger.info("执行平仓...")

        # 获取 Portfolio（多笔仓位）
        portfolio = self.close_strategy.get_portfolio()
        if portfolio is None or portfolio.total_quantity == 0:
            logger.warning("持仓信息丢失或无持仓")
            self.state_manager.set_state(BotState.IDLE, "持仓信息丢失或无持仓")
            await self.state_manager.save_state()
            return

        # 获取总持仓数量和开仓价差（用于后续记录）
        total_quantity = portfolio.total_quantity
        entry_spread = portfolio.get_total_entry_spread()
        first_open_time = portfolio.first_open_time

        logger.info(f"平仓总数量: {total_quantity} ETH, 加权开仓价差: {entry_spread:.3%}")

        # ========== 新增 (017-ext-maker-mode): Maker模式分支 ==========
        if self.config.use_maker_mode:
            await self._process_closing_maker_mode(total_quantity)
        else:
            await self._process_closing_taker_mode(total_quantity, entry_spread)

    async def _process_closing_maker_mode(self, total_quantity: Decimal) -> None:
        """处理Maker模式平仓"""
        try:
            # 下Extended Maker平仓订单
            result = await self.trade_executor.place_maker_close_order(
                total_quantity
            )

            if not result.success or result.extended_order_id is None:
                logger.error(f"Extended Maker平仓订单失败: {result.error_message}")
                self.state_manager.set_state(BotState.HOLDING, "Maker平仓订单失败")
                await self.state_manager.save_state()
                return

            # 初始化Maker等待状态
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()

            self._maker_wait_state.current_order = MakerOrder(
                order_id=result.extended_order_id,
                price=result.extended_price,
                quantity=total_quantity,
                side='sell',
                is_opening=False  # 平仓订单
            )
            self._maker_wait_state.start_time = datetime.now()

            # 启动 WebSocket 订单监控
            self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

            logger.info(
                f"✅ Extended Maker平仓订单已挂出 | "
                f"order_id={result.extended_order_id} | "
                f"price={result.extended_price} | "
                f"quantity={total_quantity}"
            )

            # 进入CLOSING_MAKER_WAIT状态
            self.state_manager.set_state(
                BotState.CLOSING_MAKER_WAIT,
                f"Maker平仓订单已挂出: {result.extended_order_id}"
            )
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"Maker模式平仓异常: {e}")
            self.state_manager.set_state(BotState.HOLDING, f"平仓异常: {e}")
            await self.state_manager.save_state()

    async def _process_closing_taker_mode(self, total_quantity: Decimal, entry_spread: Decimal) -> None:
        """处理Taker模式平仓（原有逻辑）"""
        # 创建一个临时 Position 对象用于 execute_close_position
        # 因为 execute_close_position 需要 Position 参数
        temp_position = Position(
            state=PositionState.LONG,
            extended_entry_price=Decimal("0"),  # 平仓时不需要
            lighter_entry_price=Decimal("0"),  # 平仓时不需要
            entry_spread=entry_spread,
            entry_time=datetime.now(),
            extended_quantity=total_quantity,
            lighter_quantity=-total_quantity,
            extended_order_id="close",
            lighter_order_id="close"
        )

        # 执行平仓
        result = await self.trade_executor.execute_close_position(
            temp_position,
            total_quantity
        )

        # 不管订单状态如何，都进入 CLOSING_WAIT 状态检查实际仓位
        if result.success or result.extended_order_id or result.lighter_order_id:
            logger.info(f"平仓订单已发送: Ext={result.extended_order_id}, Lig={result.lighter_order_id}")
        else:
            logger.error(f"平仓订单发送失败: {result.error_message}")

        # 进入 CLOSING_WAIT 状态验证仓位（不管订单状态如何）
        import time
        self._closing_wait_start_time = time.time()
        self.state_manager.set_state(BotState.CLOSING_WAIT, f"平仓订单已发送，等待确认")
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
            # 检查是否有API错误记录，如果有则进入风控模式而不是IDLE
            if self._api_error_count > 0:
                print(f"🛡️ 等待超时且API异常，进入风控暂停模式")
                self.state_manager.set_state(BotState.PAUSED, f"等待超时且API异常，已强平")
            else:
                self.state_manager.set_state(BotState.IDLE, f"等待超时({elapsed:.1f}s)，已强平")
            self._opening_wait_start_time = None
            await self.state_manager.save_state()
            return

        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()

            # 注意：Extended 返回绝对值（正数），Lighter 返回原始值（空头为负数）
            # 详细日志：显示类型和精确值
            logger.info(f"仓位检查 Ext={ext_position} (type:{type(ext_position).__name__}, repr:{repr(ext_position)}) "
                       f"Lig={lig_position} (type:{type(lig_position).__name__}, repr:{repr(lig_position)}) ({elapsed:.1f}s)")

            tolerance = Decimal("0.001")

            # 正确的逻辑：比较 Extended 和 Lighter 的仓位是否相等
            # 只要两边的仓位一致（ext ≈ lig），就说明套利成功
            ext_lig_diff = abs(ext_position - lig_position)
            positions_match = ext_lig_diff < tolerance

            # 检查是否两边都没有开仓
            both_zero = ext_position < tolerance and lig_position < tolerance

            logger.info(f"仓位验证: Ext={ext_position} Lig={lig_position} diff={ext_lig_diff} {('✓' if positions_match else '✗')}")

            if positions_match:
                if both_zero:
                    # 两边都没有开仓
                    logger.warning(f"开仓失败：两边都没有仓位")

                    # CSV埋点：开仓失败（两边都没开）
                    if hasattr(self, '_pending_open_position') and self._pending_open_position:
                        self._log_open_to_csv(
                            status='开仓失败_两边无仓位',
                            ext_pos=ext_position,
                            lig_pos=lig_position,
                            position_diff=ext_lig_diff,
                            target_qty=self.config.target_quantity,
                            elapsed=elapsed,
                            open_spread=self._pending_open_position.open_spread,
                            ext_order_id=self._pending_open_position.ext_order_id,
                            lig_order_id=self._pending_open_position.lig_order_id
                        )

                    # 进入冷却期
                    self._last_open_fail_time = time.time()
                    logger.info(f"进入冷却期 ({self._open_cooldown}秒)")
                    self.state_manager.set_state(BotState.IDLE, f"开仓失败：两边都没有仓位")
                    self._opening_wait_start_time = None

                    # 清除待确认的仓位
                    if hasattr(self, '_pending_open_position'):
                        self._pending_open_position = None

                    await self.state_manager.save_state()
                    return
                logger.info(f"仓位确认成功 Ext={ext_position} Lig={lig_position} {elapsed:.1f}s")
                self.state_manager.set_state(BotState.HOLDING, f"仓位确认成功 Ext={ext_position} Lig={lig_position}")
                self._opening_wait_start_time = None

                # 仓位确认成功后，添加到智能平仓系统
                if hasattr(self, '_pending_open_position') and self._pending_open_position:
                    self.close_strategy.add_position(self._pending_open_position)

                    # 更新上次开仓价差（只在仓位确认成功后才更新）
                    logger.info(f"准备更新开仓价差: 当前={self.config.cached_open_spread:.3%}, 新值={self._pending_open_position.open_spread:.3%}")
                    self.open_strategy.update_cached_spread(self._pending_open_position.open_spread)
                    logger.info(f"更新后开仓价差: {self.config.cached_open_spread:.3%}")

                    # ========== 新增 (003-spreading-improvements): 阶梯开仓回调 ==========
                    # 调用开仓成功回调，增加开仓次数
                    await self.open_strategy.on_position_opened(self._pending_open_position.open_spread)

                    # CSV埋点：开仓成功
                    self._log_open_to_csv(
                        status='开仓成功',
                        ext_pos=ext_position,
                        lig_pos=lig_position,
                        position_diff=ext_lig_diff,
                        target_qty=self.config.target_quantity,
                        elapsed=elapsed,
                        open_spread=self._pending_open_position.open_spread,
                        ext_order_id=self._pending_open_position.ext_order_id,
                        lig_order_id=self._pending_open_position.lig_order_id
                    )

                    self._pending_open_position = None

                await self.state_manager.save_state()
            elif elapsed >= 2.0 and not positions_match:
                # 等待2秒后，如果仓位仍不一致，只平掉本次开仓的数量（不平全仓）
                logger.warning(f"仓位验证失败 (elapsed={elapsed:.1f}s >= 2.0s): Ext={ext_position} Lig={lig_position} diff={ext_lig_diff}")

                # 判断哪边多了仓位，只平掉多出来的部分（本次开仓数量）
                portfolio = self.close_strategy.get_portfolio()

                # CSV埋点：仓位不对等
                if hasattr(self, '_pending_open_position') and self._pending_open_position:
                    self._log_open_to_csv(
                        status='仓位不对等',
                        ext_pos=ext_position,
                        lig_pos=lig_position,
                        position_diff=ext_lig_diff,
                        target_qty=self.config.target_quantity,
                        elapsed=elapsed,
                        open_spread=self._pending_open_position.open_spread,
                        ext_order_id=self._pending_open_position.ext_order_id,
                        lig_order_id=self._pending_open_position.lig_order_id
                    )
                current_qty = portfolio.total_quantity if portfolio else Decimal("0")

                # 只平掉两边比之前持仓多的部分
                await self._rollback_partial_positions(current_qty, ext_position, lig_position)

                # 回滚后检查实际仓位，决定下一步状态
                await asyncio.sleep(0.5)  # 等待回平订单生效
                ext_position_after = await self.extended_client.get_account_positions()
                lig_position_after = await self.lighter_client.get_account_positions()
                tolerance = Decimal("0.001")

                ext_has_pos = abs(ext_position_after) >= tolerance
                lig_has_pos = abs(lig_position_after) >= tolerance
                both_zero = not ext_has_pos and not lig_has_pos
                both_match = abs(ext_position_after - lig_position_after) < tolerance

                # 强平后进入冷却期
                self._last_open_fail_time = time.time()

                # 清除待确认的仓位
                if hasattr(self, '_pending_open_position'):
                    self._pending_open_position = None

                if both_zero:
                    # 两边都平了，进入 IDLE
                    logger.info(f"回滚后无仓位 Ext={ext_position_after} Lig={lig_position_after}，进入空闲状态")
                    logger.info(f"回滚完成，进入冷却期 ({self._open_cooldown}秒)")
                    self.state_manager.set_state(BotState.IDLE, "仓位回滚完成，无持仓")
                    self._opening_wait_start_time = None
                elif both_match:
                    # 两边都有持仓且相等，进入 HOLDING
                    logger.info(f"回滚后仍有持仓 Ext={ext_position_after} Lig={lig_position_after}，进入持仓状态")
                    self.state_manager.set_state(BotState.HOLDING, f"回滚后恢复持仓状态")
                    self._opening_wait_start_time = None
                else:
                    # 仓位仍不一致，强制全平
                    logger.error(f"回滚后仓位仍不一致 Ext={ext_position_after} Lig={lig_position_after}，强制全平")
                    await self._force_close_positions()

                    # 等待强制平仓生效
                    await asyncio.sleep(0.5)
                    ext_final = await self.extended_client.get_account_positions()
                    lig_final = await self.lighter_client.get_account_positions()

                    if abs(ext_final) < tolerance and abs(lig_final) < tolerance:
                        logger.info("强制平仓完成，进入空闲状态")
                        self.state_manager.set_state(BotState.IDLE, "回滚后强制清理完成")
                    else:
                        # 强平失败，进入风控模式
                        logger.error(f"强制平仓失败 Ext={ext_final} Lig={lig_final}，进入风控模式")
                        print(f"🛡️ 强平失败，进入风控暂停模式")
                        import time
                        self._paused_start_time = time.time()
                        self._last_api_check_time = time.time()
                        self.state_manager.set_state(BotState.PAUSED, f"回滚后强平失败，仍有残余仓位")

                    self._opening_wait_start_time = None

                await self.state_manager.save_state()
            else:
                # 继续等待
                logger.debug(f"继续等待仓位确认 (elapsed={elapsed:.1f}s < 2.0s)")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"仓位检查失败: {error_msg}")
            # 检测是否是API错误
            self._handle_api_error(error_msg)
            # 如果进入风控模式，直接返回
            if self.state_manager.get_state() == BotState.PAUSED:
                return
            # 其他异常也要暂停，避免死循环
            print(f"🛡️ 仓位检查异常，进入风控暂停模式: {error_msg}")
            import time
            self._paused_start_time = time.time()
            self._last_api_check_time = time.time()
            self.state_manager.set_state(BotState.PAUSED, f"仓位检查异常: {error_msg}")
            await self.state_manager.save_state()
            return

    async def _process_closing_wait_state(self) -> None:
        """处理 CLOSING_WAIT 状态：等待确认平仓结果"""
        import time

        current_time = time.time()
        if self._closing_wait_start_time is None:
            self._closing_wait_start_time = current_time

        elapsed = current_time - self._closing_wait_start_time

        # 等待 3 秒后检查仓位
        if elapsed < 3.0:
            return

        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")

            logger.info(f"平仓后仓位检查 ({elapsed:.1f}s): Ext={ext_position} Lig={lig_position}")

            # 检查两边仓位情况
            ext_closed = ext_position < tolerance
            lig_closed = lig_position < tolerance

            if ext_closed and lig_closed:
                # 两边都平了，平仓成功
                portfolio = self.close_strategy.get_portfolio()
                total_quantity = portfolio.total_quantity if portfolio else Decimal("0")
                entry_spread = portfolio.get_total_entry_spread() if portfolio else Decimal("0")
                first_open_time = portfolio.first_open_time if portfolio else None

                # 计算利润（简化计算）
                if portfolio:
                    # 简化计算：使用加权平均开仓价差
                    avg_price = Decimal("3000")  # 估算价格
                    profit = total_quantity * (entry_spread - self.config.total_fee_rate) * avg_price
                else:
                    profit = Decimal("0")
                close_spread = Decimal("0.001")

                # 更新统计
                stats = self.state_manager.get_stats()
                stats.total_trades += 1
                if profit > 0:
                    stats.profitable_trades += 1
                stats.total_profit += profit
                stats.total_fees += self._calculate_fees_for_portfolio(portfolio) if portfolio else Decimal("0")
                stats.last_trade_time = datetime.now()
                self.state_manager.update_stats(stats)

                # 清除所有持仓记录
                self.close_strategy.close_all()

                # ========== 新增 (003-spreading-improvements): 阶梯开仓重置回调 ==========
                # 调用所有仓位平仓回调，重置开仓次数
                await self.open_strategy.on_all_positions_closed()

                # 清除旧的 Position（向后兼容）
                old_position = self.state_manager.get_position()
                if old_position:
                    self.state_manager.update_position(None)

                # 计算持仓时长
                elapsed_time = time.time() - first_open_time if first_open_time else 0.0

                # CSV埋点：平仓成功
                fees = self._calculate_fees_for_portfolio(portfolio) if portfolio else Decimal("0")
                self._log_close_to_csv(
                    entry_spread=entry_spread,
                    close_spread=close_spread,
                    total_qty=total_quantity,
                    profit=profit,
                    fees=fees,
                    elapsed=elapsed_time,
                    status='平仓成功'
                )

                self.state_manager.set_state(BotState.IDLE, f"平仓成功: 利润=${profit:.2f}")
                await self.state_manager.save_state()

                logger.info(f"✅ 平仓确认成功，进入IDLE状态: 利润=${profit:.2f}")

            elif ext_closed or lig_closed:
                # 两边有差异，强平
                logger.error(f"⚠️ 平仓后仓位不一致！Ext={'已平' if ext_closed else f'有仓位{ext_position}'}, "
                          f"Lig={'已平' if lig_closed else f'有仓位{lig_position}'}")
                logger.error("立即强平所有仓位...")

                await self._force_close_positions()

                # 强平后进入 IDLE 状态
                logger.info("✅ 强平完成，进入IDLE状态")
                self.state_manager.set_state(BotState.IDLE, "平仓后仓位不一致，已强制清理")
                await self.state_manager.save_state()

            else:
                # 两边都有持仓，平仓失败
                logger.warning(f"⚠️ 平仓失败：两边都仍有仓位 Ext={ext_position} Lig={lig_position}")

                # 保持 HOLDING 状态，等待下一次机会
                self.state_manager.set_state(BotState.HOLDING, "平仓失败，仍有持仓")
                await self.state_manager.save_state()

            # 清除平仓等待时间
            self._closing_wait_start_time = None

        except Exception as e:
            logger.error(f"平仓后仓位检查失败: {e}", exc_info=True)
            # 检测是否是API错误
            self._handle_api_error(str(e))
            # 如果进入风控模式，直接返回
            if self.state_manager.get_state() == BotState.PAUSED:
                return
            # 其他异常也要暂停
            print(f"🛡️ 仓位检查异常，进入风控暂停模式: {e}")
            self._paused_start_time = time.time()
            self._last_api_check_time = time.time()
            self.state_manager.set_state(BotState.PAUSED, f"仓位检查异常: {e}")
            await self.state_manager.save_state()
            return

    async def _process_paused_state(self) -> None:
        """处理 PAUSED 状态：风控暂停模式，定期检测API是否恢复"""
        import time
        current_time = time.time()

        # 定期检测API是否恢复
        if current_time - self._last_api_check_time >= self._paused_check_interval:
            self._last_api_check_time = current_time

            # 尝试调用API检测是否恢复
            api_recovered = await self._check_api_recovery()

            if api_recovered:
                # API已恢复，退出风控模式
                print(f"✅ API已恢复，退出风控模式")
                self._api_error_count = 0
                self._paused_start_time = None

                # 检查是否有持仓，决定返回哪个状态（使用 Portfolio 替代旧的 Position）
                total_quantity = self.close_strategy.get_total_quantity()
                if total_quantity > 0:
                    # 有持仓，返回持仓状态
                    self.state_manager.set_state(BotState.HOLDING, "API恢复，继续监控持仓")
                else:
                    # 无持仓，返回空闲状态
                    self.state_manager.set_state(BotState.IDLE, "API恢复，等待交易机会")
                await self.state_manager.save_state()
            else:
                # API未恢复
                if self._paused_start_time:
                    paused_duration = current_time - self._paused_start_time
                    print(f"⚠️ API异常中，已暂停{paused_duration:.0f}秒，继续等待...")
                else:
                    print(f"⚠️ API异常，进入风控暂停模式，等待恢复...")

    async def _check_api_recovery(self) -> bool:
        """
        检测API是否已恢复

        Returns:
            True表示API已恢复，False表示仍然异常
        """
        try:
            # 简单检测：尝试获取订单簿数据
            spread_info = self.spread_monitor.get_current_spread()
            if spread_info and spread_info.is_valid():
                return True
            return False
        except Exception as e:
            logger.debug(f"API检测失败: {e}")
            return False

    def _handle_api_error(self, error_message: str) -> None:
        """
        处理API错误，决定是否进入风控模式

        Args:
            error_message: 错误信息
        """
        # 检测是否是API错误（HTTP 400, 500, 超时等）
        api_error_keywords = ["HTTP 400", "HTTP 500", "timeout", "connection", "500", "502", "503", "504"]
        is_api_error = any(keyword in error_message.lower() for keyword in api_error_keywords)

        if is_api_error:
            self._api_error_count += 1
            logger.warning(f"API错误计数: {self._api_error_count}/{self._api_error_threshold} - {error_message}")

            # 达到阈值，进入风控模式
            if self._api_error_count >= self._api_error_threshold:
                import time
                self._paused_start_time = time.time()
                self._last_api_check_time = time.time()
                self._api_error_count = 0  # 重置计数

                print(f"🛡️ API连续异常{self._api_error_threshold}次，进入风控暂停模式")
                self.state_manager.set_state(BotState.PAUSED, f"API异常: {error_message}")
                # 注意：这里不保存状态，避免重启后还是PAUSED状态
        else:
            # 非API错误，重置计数
            self._api_error_count = 0

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
                    # 注意：Lighter 在套利策略中是空头（卖出开仓）
                    # get_account_positions() 返回绝对值，但实际仓位是负数
                    # 所以强平时应该买入平仓
                    side = "buy"  # 空头强平 = 买入
                    close_tasks.append(("lighter", lig_position, side))  # lig_position 已经是绝对值

                # 并发执行强平（两边互不影响，避免一边API失败导致另一边无法强平）
                rollback_results = await asyncio.gather(
                    *[self.trade_executor.rollback_position(exchange, qty, side)
                      for exchange, qty, side in close_tasks],
                    return_exceptions=True
                )

                for i, result in enumerate(rollback_results):
                    exchange = close_tasks[i][0]
                    if isinstance(result, Exception):
                        logger.error(f"{exchange.capitalize()}强平异常: {result}")
                    elif not result:
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

    async def _rollback_partial_positions(self, before_qty: Decimal, ext_current: Decimal, lig_current: Decimal) -> None:
        """
        只回滚多出来的仓位，使两边相等（不平全仓）

        策略：取两边较小的仓位作为基准，回滚多出来的部分

        Args:
            before_qty: 开仓前的持仓量（记录值，仅供参考）
            ext_current: Extended当前仓位
            lig_current: Lighter当前仓位
        """
        tolerance = Decimal("0.001")

        # 策略：取两边较小的仓位作为基准
        base_qty = min(ext_current, lig_current)

        # 计算两边比基准多出的部分
        ext_extra = max(Decimal("0"), ext_current - base_qty)
        lig_extra = max(Decimal("0"), lig_current - base_qty)

        print(f"🔧 回滚计算:")
        print(f"   Extended当前: {ext_current}")
        print(f"   Lighter当前: {lig_current}")
        print(f"   基准仓位(取较小): {base_qty}")
        print(f"   Extended需平: {ext_extra}")
        print(f"   Lighter需平: {lig_extra}")

        # 检查是否需要回滚
        if ext_extra < tolerance and lig_extra < tolerance:
            logger.info("两边仓位已相等，无需回滚")
            return

        logger.info(f"回滚多出的仓位: Ext平{ext_extra}, Lig平{lig_extra}")

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # 并发回滚两边多出来的仓位
                close_tasks = []

                if ext_extra >= tolerance:
                    side = "sell"  # 多头平仓 = 卖出
                    close_tasks.append(("extended", ext_extra, side))
                    logger.info(f"回滚 Extended {ext_extra}")

                if lig_extra >= tolerance:
                    side = "buy"  # 空头平仓 = 买入
                    close_tasks.append(("lighter", lig_extra, side))
                    logger.info(f"回滚 Lighter {lig_extra}")

                if not close_tasks:
                    logger.info("回滚完成")
                    return

                # 并发执行回滚
                rollback_results = await asyncio.gather(
                    *[self.trade_executor.rollback_position(exchange, qty, side)
                      for exchange, qty, side in close_tasks],
                    return_exceptions=True
                )

                for i, result in enumerate(rollback_results):
                    exchange = close_tasks[i][0]
                    if isinstance(result, Exception):
                        logger.error(f"{exchange.capitalize()}回滚异常: {result}")
                    elif not result:
                        logger.error(f"{exchange.capitalize()}回滚失败")

                # 等待订单生效
                await asyncio.sleep(1.0)

                # 验证回滚结果：两边是否相等
                final_ext = await self.extended_client.get_account_positions()
                final_lig = await self.lighter_client.get_account_positions()

                final_diff = abs(final_ext - final_lig)

                if final_diff < tolerance:
                    logger.info(f"回滚成功 Ext={final_ext} Lig={final_lig}")
                    return
                else:
                    logger.warning(f"回滚后仍不平衡 Ext={final_ext} Lig={final_lig} (diff={final_diff})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

            except Exception as e:
                logger.error(f"回滚异常(尝试{attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)

        logger.warning("回滚重试用尽，可能存在残余仓位")

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

                # 并发强平有仓位的一边（两边互不影响，避免一边API失败导致另一边无法强平）
                rollback_tasks = []
                if ext_position != 0:
                    side = "sell" if ext_position > 0 else "buy"
                    rollback_tasks.append(("extended", abs(ext_position), side))

                if lig_position != 0:
                    # 注意：Lighter 在套利策略中是空头（卖出开仓）
                    # get_account_positions() 返回绝对值，但实际仓位是负数
                    # 所以强平时应该买入平仓
                    side = "buy"  # 空头强平 = 买入
                    rollback_tasks.append(("lighter", lig_position, side))  # lig_position 已经是绝对值

                # 并发执行强平
                if rollback_tasks:
                    rollback_results = await asyncio.gather(
                        *[self.trade_executor.rollback_position(exchange, qty, side)
                          for exchange, qty, side in rollback_tasks],
                        return_exceptions=True
                    )

                    for i, result in enumerate(rollback_results):
                        exchange = rollback_tasks[i][0]
                        if isinstance(result, Exception):
                            logger.error(f"{exchange.capitalize()}强平异常(尝试{attempt+1}/{max_retries}): {result}")
                        elif not result:
                            logger.error(f"{exchange.capitalize()}强平失败(尝试{attempt+1}/{max_retries})")

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
                    # 并发清理残留仓位（两边互不影响，避免一边API失败导致另一边无法清理）
                    cleanup_tasks = []
                    if abs(ext_position) >= tolerance:
                        side = "sell" if ext_position > 0 else "buy"
                        cleanup_tasks.append(("extended", abs(ext_position), side))

                    if abs(lig_position) >= tolerance:
                        # 注意：Lighter 在套利策略中是空头（卖出开仓）
                        # get_account_positions() 返回绝对值，但实际仓位是负数
                        # 所以强平时应该买入平仓
                        side = "buy"  # 空头强平 = 买入
                        cleanup_tasks.append(("lighter", lig_position, side))  # lig_position 已经是绝对值

                    # 并发执行清理
                    if cleanup_tasks:
                        await asyncio.gather(
                            *[self.trade_executor.rollback_position(exchange, qty, side)
                              for exchange, qty, side in cleanup_tasks],
                            return_exceptions=True
                        )

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

        # 设置 Extended 订单更新处理（WebSocket 订单监控）
        # 注意：这里需要在 maker_order_monitor 初始化之后设置，暂时先设置占位
        # 实际设置会在 _init_components 之后进行

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

        # 价格监控器 (017-ext-maker-mode)
        # ========== 修改 (003-spreading-improvements): 使用阶梯开仓阈值 ==========
        from price_monitor import SpreadConfig as PriceSpreadConfig
        price_config = PriceSpreadConfig(
            open_threshold=self.config.current_open_threshold,  # 使用阶梯开仓阈值
            close_threshold=self.config.fixed_close_threshold,
            monitor_interval=self.config.price_monitor_interval,
            price_deviation_threshold=1  # 1 tick
        )
        self.price_monitor = PriceMonitor(config=price_config)
        # 设置tick size（用于价格偏离检测）
        self.price_monitor.set_tick_size(Decimal('0.1'))  # ETH的tick size通常是1

        # 等差数列开仓策略 (016-spread-optimize)
        self.open_strategy = ArithmeticOpenStrategy(self.config)

        # 智能平仓系统 (016-spread-optimize)
        # 新增 (003-spreading-improvements): 传入交易所客户端用于获取持仓信息
        self.close_strategy = SmartCloseStrategy(
            self.config,
            extended_client=self.extended_client,
            lighter_client=self.lighter_client
        )

        # ========== 新增 (003-spreading-improvements): 余额检测器 ==========
        # 注意：这是开仓前的余额检测，与 PositionBalanceChecker 不同
        from balance_checker import BalanceAvailabilityChecker
        self.funds_checker = BalanceAvailabilityChecker(
            lighter_client=self.lighter_client,
            extended_client=self.extended_client,
            config=self.config
        )

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
        # 设置config引用，用于状态转换时重置策略状态
        self.state_manager.set_config(self.config)

        # Extended Maker订单监控器
        self.maker_order_monitor = MakerOrderMonitor()
        # 设置订单成交回调
        self.maker_order_monitor.on_order_filled = self._on_maker_order_filled
        self.maker_order_monitor.on_order_partially_filled = self._on_maker_order_partially_filled
        self.maker_order_monitor.on_order_canceled = self._on_maker_order_canceled

        # 仓位余额监控器（用于风控）
        self.position_balance_monitor = PositionBalanceMonitor(
            self.lighter_client,
            self.extended_client,
            self.config
        )

        logger.debug("组件初始化完成")

    async def _load_state(self) -> None:
        """加载状态"""
        logger.debug("加载状态...")

        state = await self.state_manager.load_state()
        logger.debug(f"当前状态: {state.value}")

        # ========== 新增: 打印状态加载后的阶梯开仓配置用于调试 ==========
        print(f"🔧 [状态加载后] 阶梯开仓参数:")
        print(f"   - initial_open_spread = {self.config.initial_open_spread} ({self.config.initial_open_spread:.3%})")
        print(f"   - spread_step = {self.config.spread_step} ({self.config.spread_step:.3%})")
        print(f"   - opening_count = {self.config.opening_count}")
        print(f"   - current_open_threshold = {self.config.current_open_threshold} ({self.config.current_open_threshold:.3%})")
        print(f"   - 计算公式: current = initial + (count * step) = {self.config.initial_open_spread} + ({self.config.opening_count} * {self.config.spread_step}) = {self.config.current_open_threshold}")
        logger.info(f"[状态加载后] 阶梯开仓配置: initial={self.config.initial_open_spread:.3%}, step={self.config.spread_step:.3%}, count={self.config.opening_count}, current_threshold={self.config.current_open_threshold:.3%}")

        # 程序重启后，如果是OPENING、OPENING_WAIT、OPENING_MAKER_WAIT、CLOSING、CLOSING_WAIT、CLOSING_MAKER_WAIT状态，重置为IDLE
        # 因为之前的交易流程已经失效，需要重新开始
        if state in [BotState.OPENING, BotState.OPENING_WAIT, BotState.OPENING_MAKER_WAIT,
                     BotState.CLOSING, BotState.CLOSING_WAIT, BotState.CLOSING_MAKER_WAIT]:
            logger.info(f"检测到未完成的{state.value}状态，重置为IDLE")
            self.state_manager.set_state(BotState.IDLE, "程序重启，重置未完成的交易状态")
            await self.state_manager.save_state()

        # 检查HOLDING状态但实际没有持仓的情况
        if state == BotState.HOLDING:
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
                       f"开仓价差={position.entry_spread:.3%}")

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
                        # 同时更新 PriceMonitor
                        if self.price_monitor:
                            await self.price_monitor.update_ext_orderbook(orderbook)

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
                        # 同时更新 PriceMonitor
                        if self.price_monitor:
                            lighter_orderbook = {
                                'bids': {str(best_bid_dec): "1.0"},
                                'asks': {str(best_ask_dec): "1.0"}
                            }
                            await self.price_monitor.update_lig_orderbook(lighter_orderbook)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"订单簿同步异常: {e}")

            # 每100ms同步一次
            await asyncio.sleep(0.1)

    # ========================================================================
    # 私有方法：订单处理（WebSocket 订单监控）
    # ========================================================================

    def _handle_extended_order_update(self, order_data: Dict) -> None:
        """
        处理 Extended WebSocket 订单更新（同步函数，由 WebSocket 回调调用）

        Args:
            order_data: 订单数据字典，包含：
                - order_id: 订单ID
                - status: 订单状态
                - side: 订单方向
                - size: 订单数量
                - price: 订单价格
                - filled_size: 成交数量
        """
        try:
            # 转换为 MakerOrderMonitor 需要的格式
            # 确保 order_id 是字符串类型（Extended SDK 可能返回整数）
            order_id = order_data.get('order_id')
            monitor_order_data = {
                'id': str(order_id) if order_id is not None else None,  # 转换为字符串
                'status': order_data.get('status'),
                'side': order_data.get('side'),
                'qty': order_data.get('size'),
                'price': order_data.get('price'),
                'filledQty': order_data.get('filled_size', '0')
            }

            # 使用 create_task 异步处理，避免阻塞 WebSocket 回调
            asyncio.create_task(self.maker_order_monitor.handle_order_update(monitor_order_data))

        except Exception as e:
            logger.error(f"处理订单更新异常: {e}")

    def _on_maker_order_filled(self, order: MakerOrder) -> None:
        """
        Maker订单完全成交回调（WebSocket 实时触发）

        Args:
            order: 成交的订单
        """
        print(
            f"✅ [WebSocket] Maker订单完全成交 | "
            f"订单: {str(order.order_id)[:8]} | "
            f"数量: {order.filled_quantity} | "
            f"价格: {order.avg_fill_price:.2f}"
        )
        logger.info(
            f"✅ [WebSocket] Maker订单完全成交 | "
            f"订单: {order.order_id} | "
            f"数量: {order.filled_quantity} | "
            f"价格: {order.avg_fill_price} | "
            f"开仓: {order.is_opening}"
        )

        # 使用 create_task 确保回调不会阻塞 WebSocket 处理
        asyncio.create_task(self._handle_maker_order_filled(order))

    def _on_maker_order_partially_filled(self, order: MakerOrder) -> None:
        """
        Maker订单部分成交回调（WebSocket 实时触发）

        Args:
            order: 部分成交的订单
        """
        print(
            f"✅ [WebSocket] Maker订单部分成交 | "
            f"订单: {str(order.order_id)[:8]} | "
            f"成交: {order.filled_quantity}/{order.quantity}"
        )
        logger.info(
            f"✅ [WebSocket] Maker订单部分成交 | "
            f"订单: {order.order_id} | "
            f"成交: {order.filled_quantity}/{order.quantity} | "
            f"均价: {order.avg_fill_price}"
        )

        # 使用 create_task 确保回调不会阻塞 WebSocket 处理
        asyncio.create_task(self._handle_maker_order_partially_filled(order))

    def _on_maker_order_canceled(self, order: MakerOrder) -> None:
        """
        Maker订单取消回调（WebSocket 实时触发）

        Args:
            order: 被取消的订单
        """
        print(
            f"❌ [WebSocket] Maker订单已取消 | "
            f"订单: {str(order.order_id)[:8]} | "
            f"成交: {order.filled_quantity}/{order.quantity}"
        )
        logger.info(
            f"❌ [WebSocket] Maker订单已取消 | "
            f"订单: {order.order_id} | "
            f"成交: {order.filled_quantity}/{order.quantity}"
        )

        # 使用 create_task 异步处理状态转换
        asyncio.create_task(self._handle_maker_order_canceled(order))

    async def _handle_maker_order_canceled(self, order: MakerOrder) -> None:
        """
        处理 Maker订单取消（异步任务）

        Args:
            order: 被取消的订单
        """
        try:
            # 检查当前状态，避免重复处理
            current_state = self.state_manager.get_state()

            # 只有在 OPENING_MAKER_WAIT 或 CLOSING_MAKER_WAIT 状态才处理
            if current_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                logger.info(f"当前状态={current_state.value}，跳过WebSocket取消回调")
                return

            # 停止监控
            self.maker_order_monitor.stop_monitoring()

            # 根据订单类型决定下一个状态
            if order.is_opening:
                # 开仓订单取消 -> IDLE
                self.state_manager.set_state(BotState.IDLE, "开仓订单已取消（WebSocket）")
            else:
                # 平仓订单取消 -> HOLDING
                self.state_manager.set_state(BotState.HOLDING, "平仓订单已取消（WebSocket）")

            # 重置等待状态
            if hasattr(self, '_maker_wait_state'):
                self._maker_wait_state.reset()

            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"处理订单取消异常: {e}", exc_info=True)

    async def _handle_maker_order_filled(self, order: MakerOrder) -> None:
        """
        处理 Maker订单完全成交（异步任务）

        Args:
            order: 成交的订单
        """
        try:
            # 检查当前状态，避免重复处理
            current_state = self.state_manager.get_state()

            # 如果已经在处理中（LIGHTER_HEDGING, OPENING_WAIT, CLOSING_WAIT），跳过
            if current_state in [BotState.LIGHTER_HEDGING, BotState.OPENING_WAIT, BotState.CLOSING_WAIT]:
                logger.info(f"订单成交已在处理中（状态={current_state.value}），跳过WebSocket回调")
                return

            # 只有在 OPENING_MAKER_WAIT 或 CLOSING_MAKER_WAIT 状态才处理
            if current_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                logger.info(f"当前状态={current_state.value}，跳过WebSocket成交回调")
                return

            # 停止监控
            self.maker_order_monitor.stop_monitoring()

            # 更新 MakerWaitState 中的订单状态
            if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                if self._maker_wait_state.current_order.order_id == order.order_id:
                    self._maker_wait_state.current_order.status = 'FILLED'
                    self._maker_wait_state.current_order.filled_quantity = order.filled_quantity
                    self._maker_wait_state.current_order.avg_fill_price = order.avg_fill_price

            # 进入 LIGHTER_HEDGING 状态对冲
            if not hasattr(self, '_hedging_state'):
                from models import HedgingState
                self._hedging_state = HedgingState()
            self._hedging_state.ext_filled_quantity = order.filled_quantity
            self._hedging_state.ext_filled_price = order.avg_fill_price
            self._hedging_state.start_time = datetime.now()

            is_opening = (current_state == BotState.OPENING_MAKER_WAIT)
            if is_opening:
                self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"Extended完全成交（WebSocket），开始Lighter对冲")
            else:
                self._hedging_state.is_closing = True
                self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"Extended平仓完全成交（WebSocket），开始Lighter对冲")
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"处理订单成交异常: {e}", exc_info=True)

    async def _handle_maker_order_partially_filled(self, order: MakerOrder) -> None:
        """
        处理 Maker订单部分成交（异步任务）

        Args:
            order: 部分成交的订单
        """
        try:
            # 检查当前状态，避免重复处理
            current_state = self.state_manager.get_state()

            # 如果已经在处理中，跳过
            if current_state in [BotState.LIGHTER_HEDGING, BotState.OPENING_WAIT, BotState.CLOSING_WAIT]:
                logger.info(f"订单部分成交已在处理中（状态={current_state.value}），跳过WebSocket回调")
                return

            # 只有在 OPENING_MAKER_WAIT 或 CLOSING_MAKER_WAIT 状态才处理
            if current_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                logger.info(f"当前状态={current_state.value}，跳过WebSocket部分成交回调")
                return

            # 更新 MakerWaitState 中的订单状态
            if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                if self._maker_wait_state.current_order.order_id == order.order_id:
                    self._maker_wait_state.current_order.status = 'PARTIALLY_FILLED'
                    self._maker_wait_state.current_order.filled_quantity = order.filled_quantity
                    self._maker_wait_state.current_order.avg_fill_price = order.avg_fill_price

            # 进入 LIGHTER_HEDGING 状态对冲已成交部分
            if not hasattr(self, '_hedging_state'):
                from models import HedgingState
                self._hedging_state = HedgingState()
            self._hedging_state.ext_filled_quantity = order.filled_quantity
            self._hedging_state.ext_filled_price = order.avg_fill_price
            self._hedging_state.start_time = datetime.now()

            is_opening = (current_state == BotState.OPENING_MAKER_WAIT)
            if is_opening:
                self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"Extended部分成交{order.filled_quantity}（WebSocket），开始Lighter对冲")
            else:
                self._hedging_state.is_closing = True
                self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"Extended平仓部分成交{order.filled_quantity}（WebSocket），开始Lighter对冲")
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"处理部分成交异常: {e}", exc_info=True)

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
        """计算利润（旧版，单笔仓位）"""
        # 简化计算
        return self.config.target_quantity * position.entry_spread * position.extended_entry_price * Decimal("0.5")

    def _calculate_profit_for_portfolio(self, portfolio: Portfolio, result: ExecutionResult) -> Decimal:
        """计算 Portfolio 利润（新版，多笔仓位）"""
        # 简化计算：使用加权平均开仓价差
        entry_spread = portfolio.get_total_entry_spread()
        total_quantity = portfolio.total_quantity

        # 获取平仓价格
        if result.extended_price and result.lighter_price:
            avg_close_price = (result.extended_price + result.lighter_price) / 2
        else:
            # 如果没有平仓价格，使用开仓价格的估算
            avg_close_price = Decimal("3000")  # 临时默认值

        # 利润 = 数量 * (开仓价差 - 手续费) * 价格
        # 开仓价差就是利润率
        profit = total_quantity * (entry_spread - self.config.total_fee_rate) * avg_close_price
        return profit

    def _calculate_fees(self, position: Position) -> Decimal:
        """计算手续费（旧版，单笔仓位）"""
        # Extended 0.025% 双向 = 0.05%
        return self.config.target_quantity * position.extended_entry_price * Decimal("0.0005")

    def _calculate_fees_for_portfolio(self, portfolio: Portfolio) -> Decimal:
        """计算 Portfolio 手续费（新版，多笔仓位）"""
        # 简化计算：使用总数量和平均价格
        total_quantity = portfolio.total_quantity
        # 使用估算价格
        avg_price = Decimal("3000")
        return total_quantity * avg_price * self.config.total_fee_rate

    def _init_csv_loggers(self) -> None:
        """初始化CSV日志记录器"""
        date_str = datetime.now().strftime("%Y%m%d")
        self._open_csv_path = self._csv_log_dir / f"open_trades_{date_str}.csv"
        self._close_csv_path = self._csv_log_dir / f"close_trades_{date_str}.csv"
        self._spread_csv_path = self._csv_log_dir / f"spread_data_{date_str}.csv"

        # 初始化开仓CSV文件
        if not self._open_csv_path.exists():
            with open(self._open_csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'status', 'ext_position', 'lig_position',
                    'position_diff', 'target_qty', 'elapsed_time',
                    'open_spread', 'ext_order_id', 'lig_order_id'
                ])

        # 初始化平仓CSV文件
        if not self._close_csv_path.exists():
            with open(self._close_csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'entry_spread', 'close_spread',
                    'total_quantity', 'profit', 'fees',
                    'profit_pct', 'elapsed_time', 'status'
                ])

        # 初始化实时价差CSV文件
        if not self._spread_csv_path.exists():
            with open(self._spread_csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'state', 'ext_bid', 'ext_ask',
                    'lig_bid', 'lig_ask', 'spread_abs', 'spread_pct',
                    'cached_open_spread', 'portfolio_qty', 'total_entry_spread'
                ])

        logger.info(f"CSV日志文件: 开仓={self._open_csv_path}, 平仓={self._close_csv_path}, 价差={self._spread_csv_path}")

    def _log_open_to_csv(self, status: str, ext_pos: Decimal, lig_pos: Decimal,
                         position_diff: Decimal, target_qty: Decimal,
                         elapsed: float, open_spread: Decimal,
                         ext_order_id: str, lig_order_id: str) -> None:
        """记录开仓结果到CSV（异步执行，不阻塞主程序）"""
        asyncio.create_task(self._log_open_to_csv_async(
            status, ext_pos, lig_pos, position_diff, target_qty,
            elapsed, open_spread, ext_order_id, lig_order_id
        ))

    async def _log_open_to_csv_async(self, status: str, ext_pos: Decimal, lig_pos: Decimal,
                                     position_diff: Decimal, target_qty: Decimal,
                                     elapsed: float, open_spread: Decimal,
                                     ext_order_id: str, lig_order_id: str) -> None:
        """异步记录开仓结果到CSV"""
        try:
            await asyncio.to_thread(self._write_open_to_csv_file,
                datetime.now().isoformat(),
                status,
                str(ext_pos),
                str(lig_pos),
                str(position_diff),
                str(target_qty),
                f"{elapsed:.2f}",
                str(open_spread),
                ext_order_id or '',
                lig_order_id or ''
            )
        except Exception as e:
            logger.warning(f"写入开仓CSV失败: {e}")

    def _write_open_to_csv_file(self, *args) -> None:
        """同步写入开仓CSV文件（在线程池中执行）"""
        try:
            with open(self._open_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(args)
        except Exception as e:
            logger.warning(f"写入开仓CSV文件失败: {e}")

    def _log_close_to_csv(self, entry_spread: Decimal, close_spread: Decimal,
                          total_qty: Decimal, profit: Decimal, fees: Decimal,
                          elapsed: float, status: str) -> None:
        """记录平仓结果到CSV（异步执行，不阻塞主程序）"""
        asyncio.create_task(self._log_close_to_csv_async(
            entry_spread, close_spread, total_qty, profit, fees, elapsed, status
        ))

    async def _log_close_to_csv_async(self, entry_spread: Decimal, close_spread: Decimal,
                                     total_qty: Decimal, profit: Decimal, fees: Decimal,
                                     elapsed: float, status: str) -> None:
        """异步记录平仓结果到CSV"""
        try:
            # 计算利润百分比
            if total_qty > 0 and entry_spread > 0:
                profit_pct = (profit / (total_qty * entry_spread * Decimal("3000"))) * 100
            else:
                profit_pct = Decimal("0")

            await asyncio.to_thread(self._write_close_to_csv_file,
                datetime.now().isoformat(),
                str(entry_spread),
                str(close_spread),
                str(total_qty),
                str(profit),
                str(fees),
                f"{profit_pct:.2f}%",
                f"{elapsed:.2f}",
                status
            )
        except Exception as e:
            logger.warning(f"写入平仓CSV失败: {e}")

    def _write_close_to_csv_file(self, *args) -> None:
        """同步写入平仓CSV文件（在线程池中执行）"""
        try:
            with open(self._close_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(args)
        except Exception as e:
            logger.warning(f"写入平仓CSV文件失败: {e}")

    def _log_spread_to_csv(self, spread_info) -> None:
        """记录实时价差到CSV（异步执行，不阻塞主程序）"""
        # 在后台线程中执行CSV写入，避免阻塞主循环
        asyncio.create_task(self._log_spread_to_csv_async(spread_info))

    async def _log_spread_to_csv_async(self, spread_info) -> None:
        """异步记录实时价差到CSV"""
        try:
            portfolio = self.close_strategy.get_portfolio()
            state = self.state_manager.get_state().value

            # 使用 asyncio.to_thread 在后台线程中执行同步IO操作
            await asyncio.to_thread(self._write_spread_to_csv_file,
                datetime.now().isoformat(),
                state,
                str(spread_info.ext_bid),
                str(spread_info.ext_ask),
                str(spread_info.lig_bid),
                str(spread_info.lig_ask),
                str(spread_info.spread_abs),
                str(spread_info.spread_pct),
                str(self.config.cached_open_spread),
                str(portfolio.total_quantity if portfolio else 0),
                str(portfolio.get_total_entry_spread() if portfolio else 0)
            )
        except Exception as e:
            logger.warning(f"写入价差CSV失败: {e}")

    def _write_spread_to_csv_file(self, *args) -> None:
        """同步写入CSV文件（在线程池中执行）"""
        try:
            with open(self._spread_csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(args)
        except Exception as e:
            logger.warning(f"写入价差CSV文件失败: {e}")

    # ========== 新增方法 (017-ext-maker-mode) ==========

    async def _process_opening_maker_wait_state(self) -> None:
        """
        处理 OPENING_MAKER_WAIT 状态：等待Extended Maker订单成交

        核心职责：
        1. 监控价差保护（实时价差 < 0.09%时取消挂单）
        2. 监控价格位置优化（挂单价格偏离时重新挂单）
        3. 监控订单成交状态（WebSocket更新）
        4. 部分成交时进入LIGHTER_HEDGING对冲已成交部分
        5. 完全成交时进入LIGHTER_HEDGING对冲全部
        """
        from models import MakerWaitState, HedgingState

        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            logger.warning("Maker等待状态未初始化，返回IDLE")
            self.state_manager.set_state(BotState.IDLE, "Maker等待状态异常")
            await self.state_manager.save_state()
            return

        # 获取当前订单ID
        order_id = self._maker_wait_state.current_order.order_id

        try:
            # ========== 监控日志：实时价差和订单簿BBO ==========
            spread_info = self.spread_monitor.get_current_spread()
            if spread_info and spread_info.is_valid():
                # 获取Extended订单簿BBO价格
                ext_bid, ext_ask = await self.extended_client.fetch_bbo_prices(
                    self.extended_client.config.contract_id
                )

                # 获取仓位余额信息（用于风控显示）
                balance_log = ""
                try:
                    balance_snapshot = await self.position_balance_monitor.get_position_balance()
                    if balance_snapshot.is_valid():
                        balance_log = f" | {balance_snapshot.format_compact_log()}"
                except Exception as e:
                    logger.debug(f"获取仓位余额失败: {e}")

                # 输出监控日志（每秒一次）
                print(
                    f"📊 状态「开仓挂单等待成交」 | "
                    f"实时价差{spread_info.spread_pct:.3%} | "
                    f"ext_bid={ext_bid:.2f} ext_ask={ext_ask:.2f}"
                    f"{balance_log}"
                )

            # ========== 订单成交/取消由 WebSocket 处理，主循环不再检测 ==========
            # WebSocket 回调会处理：
            # - FILLED: 完全成交 -> LIGHTER_HEDGING
            # - PARTIALLY_FILLED: 部分成交 -> LIGHTER_HEDGING
            # - CANCELED: 订单取消 -> IDLE

            # ========== 主循环只处理：价差保护 + 价格偏离 ==========

            # 检查价差保护 (003-spreading-improvements: 使用阶梯开仓阈值)
            if spread_info and spread_info.is_valid():
                current_threshold = self.config.current_open_threshold
                if spread_info.spread_pct < current_threshold:
                    # 价差不满足条件，取消订单
                    spread_value = spread_info.spread_pct
                    logger.warning(
                        f"⚠️ 价差保护触发 | "
                        f"实时价差{spread_value:.3%} < 阶梯开仓阈值{current_threshold:.3%}(次{self.config.opening_count})"
                    )
                    await self.trade_executor.cancel_extended_maker_order(order_id)

                    # 先检查实际仓位（订单可能已成交但API返回有延迟）
                    ext_position = await self.extended_client.get_account_positions()
                    lig_position = await self.lighter_client.get_account_positions()
                    tolerance = Decimal("0.001")
                    has_position = abs(ext_position) >= tolerance or abs(lig_position) >= tolerance

                    if has_position:
                        # 有仓位，进入 HOLDING 状态
                        reason = f"价差保护触发但检测到仓位，进入持仓（Ext={ext_position}, Lig={lig_position}）"
                        self.state_manager.set_state(BotState.HOLDING, reason)
                        logger.info(f"💥 价差保护触发但有仓位 -> 进入HOLDING | Ext={ext_position} Lig={lig_position}")
                    else:
                        # 无仓位，进入 IDLE 状态
                        reason = f"价差保护触发，取消挂单（实时价差{spread_value:.3%} < 开仓阈值{threshold_value:.3%}）"
                        self.state_manager.set_state(BotState.IDLE, reason)

                    self._maker_wait_state.reset()
                    await self.state_manager.save_state()
                    return

            # 检查价格偏离（只对未成交的订单进行）
            price_deviated = await self.price_monitor.check_and_notify_price_deviation(
                order_side=self._maker_wait_state.current_order.side,
                order_price=self._maker_wait_state.current_order.price,
                order_id=order_id
            )

            if price_deviated:
                # ========== 新增：检查是否正在重挂中（防止并发） ==========
                if self._maker_wait_state.is_repositioning:
                    logger.debug("正在重挂中，跳过本次价格偏离检测")
                    return

                # 检查冷却时间
                current_time = time.time()
                cooldown_remaining = self.config.reposition_cooldown - (current_time - self._maker_wait_state.last_reposition_time)
                if cooldown_remaining > 0:
                    print(f"⏳ 重挂冷却中，剩余 {cooldown_remaining:.1f} 秒")
                    logger.debug(f"重挂冷却中，跳过本次检测")
                    return

                print(f"🚀 开始重挂订单...")

                # 取消旧订单并重新挂单
                await self._reposition_maker_order(is_opening=True)
                self._maker_wait_state.last_reposition_time = current_time
                return
            else:
                # 价格未偏离，无需重挂
                pass

            # 检查超时
            elapsed = (datetime.now() - self._maker_wait_state.start_time).total_seconds()
            if elapsed > self.config.maker_order_timeout:
                logger.info(
                    f"⏱️ Maker订单等待超时 ({elapsed:.1f}s)，继续等待（根据Edge Case决策B）"
                )
                # 继续等待，不取消订单

        except Exception as e:
            logger.error(f"OPENING_MAKER_WAIT状态处理异常: {e}")
            # 出错时取消订单并返回IDLE
            if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                await self.trade_executor.cancel_extended_maker_order(
                    self._maker_wait_state.current_order.order_id
                )
            self.state_manager.set_state(BotState.IDLE, f"异常: {e}")
            await self.state_manager.save_state()

    async def _process_closing_maker_wait_state(self) -> None:
        """
        处理 CLOSING_MAKER_WAIT 状态：等待Extended Maker平仓订单成交

        核心职责：
        1. 监控平仓条件（不满足时取消挂单回到HOLDING）
        2. 监控价格位置优化（挂单价格偏离时重新挂单）
        3. 监控订单成交状态（WebSocket更新）
        4. 部分成交时进入LIGHTER_HEDGING对冲已成交部分
        5. 完全成交时进入LIGHTER_HEDGING对冲全部
        """
        from models import MakerWaitState, HedgingState

        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            logger.warning("Maker等待状态未初始化，返回HOLDING")
            self.state_manager.set_state(BotState.HOLDING, "Maker等待状态异常")
            await self.state_manager.save_state()
            return

        try:
            # ========== 订单成交/取消由 WebSocket 处理，主循环不再检测 ==========
            # WebSocket 回调会处理：
            # - FILLED: 完全成交 -> LIGHTER_HEDGING
            # - PARTIALLY_FILLED: 部分成交 -> LIGHTER_HEDGING
            # - CANCELED: 订单取消 -> HOLDING

            # ========== 主循环只处理：价格偏离 ==========

            # 检查价格偏离
            order_id = self._maker_wait_state.current_order.order_id
            price_deviated = await self.price_monitor.check_and_notify_price_deviation(
                order_side=self._maker_wait_state.current_order.side,
                order_price=self._maker_wait_state.current_order.price,
                order_id=order_id
            )

            if price_deviated:
                # ========== 新增：检查是否正在重挂中（防止并发） ==========
                if self._maker_wait_state.is_repositioning:
                    logger.debug("正在重挂中，跳过本次价格偏离检测")
                    return

                # 检查冷却时间
                current_time = time.time()
                if current_time - self._maker_wait_state.last_reposition_time < self.config.reposition_cooldown:
                    logger.debug(f"重挂冷却中，跳过本次检测")
                    return

                # 取消旧订单并重新挂单
                await self._reposition_maker_order(is_opening=False)
                self._maker_wait_state.last_reposition_time = current_time
                return

        except Exception as e:
            logger.error(f"CLOSING_MAKER_WAIT状态处理异常: {e}")
            # 出错时返回HOLDING状态
            self.state_manager.set_state(BotState.HOLDING, f"异常: {e}")
            await self.state_manager.save_state()

    async def _process_lighter_hedging_state(self) -> None:
        """
        处理 LIGHTER_HEDGING 状态：在Lighter执行对冲订单

        核心职责：
        1. 在Lighter执行对冲订单（Taker模式，即时成交）
        2. 对冲数量与Extended成交数量一致
        3. 对冲成功后进入OPENING_WAIT或CLOSING_WAIT验证仓位
        4. 对冲失败时触发强制平仓逻辑
        """
        from models import HedgingState, MakerWaitState

        if not hasattr(self, '_hedging_state') or self._hedging_state.ext_filled_quantity == 0:
            logger.warning("对冲状态未初始化或无成交数量")
            # 判断是从开仓还是平仓进入的
            if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                if self._maker_wait_state.current_order.is_opening:
                    self.state_manager.set_state(BotState.OPENING_WAIT, "对冲状态异常，验证仓位")
                else:
                    self.state_manager.set_state(BotState.CLOSING_WAIT, "对冲状态异常，验证仓位")
            else:
                self.state_manager.set_state(BotState.IDLE, "对冲状态异常")
            await self.state_manager.save_state()
            return

        try:
            ext_filled_qty = self._hedging_state.ext_filled_quantity
            ext_filled_price = self._hedging_state.ext_filled_price

            # 判断对冲方向（开仓时Lighter卖出，平仓时Lighter买入）
            is_opening = True  # 默认是开仓对冲
            if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                is_opening = self._maker_wait_state.current_order.is_opening

            hedge_side = 'sell' if is_opening else 'buy'

            logger.info(
                f"🔄 执行Lighter对冲 | "
                f"side={hedge_side} | "
                f"quantity={ext_filled_qty} | "
                f"ext_price={ext_filled_price}"
            )

            # ========== 风控检查：Lighter价格是否不利 ==========
            if is_opening:
                # 开仓场景：Extended买入，Lighter卖出
                # 检查：Lighter卖出价应该 > Extended买入价（才能盈利）
                # 如果 Lighter卖出价 <= Extended买入价，跳过Lighter开仓

                # 获取当前Lighter的卖出价
                if hasattr(self.lighter_client, 'ws_manager') and self.lighter_client.ws_manager:
                    lighter_ask = self.lighter_client.ws_manager.best_ask
                    if lighter_ask:
                        lighter_ask_dec = Decimal(str(lighter_ask))

                        # 计算价差率（百分比）
                        spread_abs = lighter_ask_dec - ext_filled_price
                        spread_ratio = (spread_abs / ext_filled_price * 100) if ext_filled_price > 0 else Decimal("0")

                        print(
                            f"🔍 风控检查 | "
                            f"Ext买入价: {ext_filled_price:.2f} | "
                            f"Lig卖出价: {lighter_ask_dec:.2f} | "
                            f"价差: {spread_abs:.2f} ({spread_ratio:+.4f}%)"
                        )

                        if lighter_ask_dec <= ext_filled_price:
                            # Lighter价格不利，跳过开仓
                            print(
                                f"⚠️ 风控触发：Lig卖出价({lighter_ask_dec:.2f}) <= Ext买入价({ext_filled_price:.2f})，"
                                f"跳过Lighter开仓，直接进入验证阶段"
                            )
                            logger.warning(
                                f"⚠️ 风控触发：Lig卖出价({lighter_ask_dec:.2f}) <= Ext买入价({ext_filled_price:.2f})，"
                                f"跳过Lighter开仓，直接进入验证阶段"
                            )

                            # 直接进入OPENING_WAIT状态
                            import time
                            self._opening_wait_start_time = time.time()
                            self.state_manager.set_state(
                                BotState.OPENING_WAIT,
                                f"风控触发跳过Lighter开仓，验证仓位（可能不平衡）"
                            )
                            # 重置对冲状态，避免重复处理
                            if hasattr(self, '_hedging_state'):
                                self._hedging_state.ext_filled_quantity = Decimal('0')
                            await self.state_manager.save_state()
                            return

            # 执行Lighter对冲
            result = await self.trade_executor.execute_lighter_hedge(
                quantity=ext_filled_qty,
                side=hedge_side,
                ext_filled_price=ext_filled_price
            )

            if result.success and result.lighter_filled:
                # 对冲成功
                logger.info(
                    f"✅ Lighter对冲成功 | "
                    f"order_id={result.lighter_order_id} | "
                    f"quantity={ext_filled_qty}"
                )

                # 记录本次成交
                if hasattr(self, '_maker_wait_state'):
                    self._maker_wait_state.add_fill_record(
                        self._hedging_state.lighter_order_id or "unknown",
                        ext_filled_qty
                    )

                # 判断是否还有剩余数量需要继续等待
                if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                    remaining = self._maker_wait_state.current_order.remaining_quantity
                    if remaining > 0:
                        # 还有剩余数量，回到MAKER_WAIT状态继续等待
                        if is_opening:
                            self.state_manager.set_state(
                                BotState.OPENING_MAKER_WAIT,
                                f"对冲{ext_filled_qty}完成，剩余{remaining}继续等待"
                            )
                        else:
                            self.state_manager.set_state(
                                BotState.CLOSING_MAKER_WAIT,
                                f"对冲{ext_filled_qty}完成，剩余{remaining}继续等待"
                            )
                    else:
                        # ========== 修复：使用交易所API获取真实平均价格 ==========
                        if is_opening:
                            # 尝试从交易所API获取真实的平均开仓价格
                            try:
                                logger.info(
                                    f"[_create_pending_position] 尝试从交易所获取真实价格..."
                                )

                                ext_pos = await self.extended_client.get_detailed_position()
                                lig_pos = await self.lighter_client.get_detailed_position()

                                logger.info(
                                    f"[_create_pending_position] API返回 | "
                                    f"ext_pos={ext_pos} | "
                                    f"lig_pos={lig_pos}"
                                )

                                # 使用交易所返回的真实平均价格，如果有的话
                                ext_avg_price = ext_pos.get('avg_price', Decimal('0'))
                                lig_avg_price = lig_pos.get('avg_price', Decimal('0'))

                                logger.info(
                                    f"[_create_pending_position] 提取的价格 | "
                                    f"ext_avg_price={ext_avg_price:.2f} | "
                                    f"lig_avg_price={lig_avg_price:.2f}"
                                )

                                # 如果API返回了有效价格，使用真实价格；否则使用成交价格
                                if ext_avg_price > 0:
                                    actual_ext_price = ext_avg_price
                                    logger.info(f"[_create_pending_position] 使用Ext真实价格: {actual_ext_price:.2f}")
                                else:
                                    actual_ext_price = ext_filled_price
                                    logger.warning(
                                        f"[_create_pending_position] Ext API未返回有效价格，使用成交价格: {actual_ext_price:.2f}"
                                    )

                                if lig_avg_price > 0:
                                    actual_lig_price = lig_avg_price
                                    logger.info(f"[_create_pending_position] 使用Lig真实价格: {actual_lig_price:.2f}")
                                else:
                                    actual_lig_price = result.lighter_price or ext_filled_price
                                    logger.warning(
                                        f"[_create_pending_position] Lig API未返回有效价格，使用成交价格: {actual_lig_price:.2f}"
                                    )

                                # 计算真实价差
                                if actual_ext_price > 0:
                                    actual_spread = (actual_lig_price - actual_ext_price) / actual_ext_price
                                else:
                                    actual_spread = Decimal('0')

                                logger.info(
                                    f"[_create_pending_position] 最终价格 | "
                                    f"ext={actual_ext_price:.2f} | "
                                    f"lig={actual_lig_price:.2f} | "
                                    f"spread={actual_spread:.3%} | "
                                    f"成交价: ext={ext_filled_price:.2f}, lig={result.lighter_price or 0:.2f}"
                                )

                            except Exception as e:
                                logger.error(
                                    f"[_create_pending_position] 获取交易所真实价格失败: {e} | "
                                    f"使用成交价格作为备选 | ext={ext_filled_price:.2f}, lig={result.lighter_price or 0:.2f}"
                                )
                                actual_ext_price = ext_filled_price
                                actual_lig_price = result.lighter_price or ext_filled_price
                                actual_spread = Decimal('0')

                            # 创建 _pending_open_position（用于后续添加到 Portfolio）
                            self._pending_open_position = OpenPosition(
                                position_id=str(uuid.uuid4()),
                                open_time=datetime.now().timestamp(),
                                ext_price=actual_ext_price,
                                lig_price=actual_lig_price,
                                open_spread=actual_spread,
                                quantity=ext_filled_qty,
                                ext_order_id=self._maker_wait_state.current_order.order_id,
                                lig_order_id=result.lighter_order_id,
                                is_active=True,
                            )
                            logger.info(
                                f"[_create_pending_position] 创建待确认仓位 | Maker模式 | "
                                f"ext_price={actual_ext_price:.2f} | "
                                f"lig_price={actual_lig_price:.2f} | "
                                f"open_spread={actual_spread:.3%} | "
                                f"quantity={ext_filled_qty}"
                            )

                            import time
                            self._opening_wait_start_time = time.time()
                            self.state_manager.set_state(BotState.OPENING_WAIT, "对冲完成，验证仓位")
                        else:
                            self.state_manager.set_state(BotState.CLOSING_WAIT, "对冲完成，验证仓位")
                else:
                    # 没有maker_wait_state，直接进入验证
                    if is_opening:
                        # ========== 修复：Maker 模式下创建 _pending_open_position ==========
                        spread_info = self.spread_monitor.get_current_spread()
                        if spread_info and spread_info.is_valid():
                            self._pending_open_position = OpenPosition(
                                position_id=str(uuid.uuid4()),
                                open_time=datetime.now().timestamp(),
                                ext_price=ext_filled_price,
                                lig_price=result.lighter_price or Decimal('0'),
                                open_spread=spread_info.spread_pct,
                                quantity=ext_filled_qty,
                                ext_order_id="maker_open",
                                lig_order_id=result.lighter_order_id,
                                is_active=True,
                            )
                        import time
                        self._opening_wait_start_time = time.time()
                        self.state_manager.set_state(BotState.OPENING_WAIT, "对冲完成，验证仓位")
                    else:
                        self.state_manager.set_state(BotState.CLOSING_WAIT, "对冲完成，验证仓位")

                # 重置对冲状态，避免重复处理
                self._hedging_state.ext_filled_quantity = Decimal('0')
                await self.state_manager.save_state()
                return

            else:
                # 对冲失败
                logger.error(
                    f"❌ Lighter对冲失败 | "
                    f"error={result.error_message} | "
                    f"ext_filled_qty={ext_filled_qty}"
                )

                # 根据Edge Case决策：只强制平仓本次新开仓的Extended仓位
                # 保留原有持仓不动
                await self._handle_hedging_failure(is_opening, ext_filled_qty)

        except Exception as e:
            logger.error(f"LIGHTER_HEDGING状态处理异常: {e}")
            # 异常时也触发失败处理
            await self._handle_hedging_failure(True, 0)

    async def _handle_hedging_failure(self, is_opening: bool, ext_filled_qty: Decimal) -> None:
        """
        处理Lighter对冲失败

        根据Edge Case决策：
        - 只强制平仓本次新开仓的Extended仓位
        - 保留原有持仓不动
        - 如果强制平仓失败，进入PAUSED状态
        """
        try:
            logger.warning(
                f"🔄 开始强制平仓Extended仓位 | "
                f"is_opening={is_opening} | "
                f"ext_filled_qty={ext_filled_qty}"
            )

            # TODO: 实现强制平仓逻辑
            # 这里需要调用Extended的平仓方法，只平仓ext_filled_qty的数量
            # 如果平仓成功：
            #   - 如果is_opening=True：进入IDLE状态（无持仓）
            #   - 如果is_opening=False：检查是否还有持仓，有则HOLDING，无则IDLE
            # 如果平仓失败：
            #   - 进入PAUSED状态

            # 暂时实现：进入PAUSED状态
            self.state_manager.set_state(
                BotState.PAUSED,
                f"Lighter对冲失败，需要人工处理: ext_filled_qty={ext_filled_qty}"
            )
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"强制平仓异常: {e}")
            self.state_manager.set_state(BotState.PAUSED, f"强制平仓异常: {e}")
            await self.state_manager.save_state()

    async def _reposition_maker_order(self, is_opening: bool) -> None:
        """
        重新挂单（取消旧订单 + 挂出新订单）

        Args:
            is_opening: True=开仓重挂, False=平仓重挂
        """
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            logger.warning("无活跃订单可重挂")
            return

        # ========== 防止并发重挂 ==========
        if self._maker_wait_state.is_repositioning:
            logger.warning("正在重挂中，跳过本次调用")
            return

        # 设置重挂标志
        self._maker_wait_state.is_repositioning = True

        old_order = self._maker_wait_state.current_order

        try:
            # 1. 在取消订单之前，先获取订单状态（包括已成交数量）
            order_info = await self.trade_executor.get_extended_order_info(old_order.order_id)

            filled_qty = Decimal('0')
            if order_info and 'filled_size' in order_info:
                # 确保 filled_size 是 Decimal 类型
                filled_size = order_info['filled_size']
                if isinstance(filled_size, str):
                    filled_qty = Decimal(filled_size)
                elif isinstance(filled_size, (int, float)):
                    filled_qty = Decimal(str(filled_size))
                else:
                    filled_qty = Decimal(filled_size) if filled_size else Decimal('0')

            print(
                f"🔄 订单状态查询 | "
                f"原订单数量: {old_order.quantity} | "
                f"已成交数量: {filled_qty} | "
                f"剩余数量: {old_order.quantity - filled_qty}"
            )

            # 2. 取消旧订单并验证取消成功 (003-spreading-improvements: 使用带验证的取消方法)
            try:
                cancel_result = await self.trade_executor.cancel_maker_order_with_verification(
                    order_id=old_order.order_id,
                    exchange="extended",
                    max_retries=5,
                    retry_interval=2.0,
                    verify_timeout=5.0
                )
            except Exception as cancel_error:
                logger.error(f"取消订单验证失败: {old_order.order_id} | 错误: {cancel_error}")
                # 取消失败，停止重挂流程
                return

            # 3. 计算剩余数量（使用原订单数量和已成交数量）
            remaining_qty = old_order.quantity - filled_qty

            print(
                f"🔄 准备重挂订单 | "
                f"原订单数量: {old_order.quantity} | "
                f"已成交数量: {filled_qty} | "
                f"剩余数量: {remaining_qty} | "
                f"剩余数量类型: {type(remaining_qty).__name__}"
            )

            if remaining_qty <= 0:
                print(f"✅ 订单已完全成交，无需重挂")
                logger.info(f"订单已完全成交，无需重挂")

                # ========== 修复：订单已完全成交，需要切换到 LIGHTER_HEDGING 状态 ==========
                # 停止监控当前订单
                self.maker_order_monitor.stop_monitoring()

                # 更新 MakerWaitState 中的订单状态
                if self._maker_wait_state.current_order:
                    self._maker_wait_state.current_order.status = 'FILLED'
                    self._maker_wait_state.current_order.filled_quantity = old_order.quantity
                    self._maker_wait_state.current_order.avg_fill_price = old_order.price

                # 进入 LIGHTER_HEDGING 状态对冲
                if not hasattr(self, '_hedging_state'):
                    from models import HedgingState
                    self._hedging_state = HedgingState()
                self._hedging_state.ext_filled_quantity = old_order.quantity
                self._hedging_state.ext_filled_price = old_order.price
                self._hedging_state.start_time = datetime.now()

                is_opening = (self.state_manager.get_state() == BotState.OPENING_MAKER_WAIT)
                if is_opening:
                    self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"Extended完全成交（价格偏离检测），开始Lighter对冲")
                else:
                    self._hedging_state.is_closing = True
                    self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"Extended平仓完全成交（价格偏离检测），开始Lighter对冲")
                await self.state_manager.save_state()

                logger.info(f"✅ 已切换到 LIGHTER_HEDGING 状态进行对冲")
                return

            # 4. 重新挂单（使用剩余数量）
            if is_opening:
                result = await self.trade_executor.place_maker_open_order(remaining_qty)
            else:
                result = await self.trade_executor.place_maker_close_order(remaining_qty)

            if result.success:
                # 5. 更新状态
                new_order = MakerOrder(
                    order_id=result.extended_order_id,
                    price=result.extended_price,
                    quantity=remaining_qty,
                    side=old_order.side,
                    is_opening=is_opening
                )
                self._maker_wait_state.current_order = new_order
                self._maker_wait_state.reposition_count += 1

                # 重新启动 WebSocket 订单监控（监控新订单）
                self.maker_order_monitor.start_monitoring(new_order)

                print(
                    f"✅ 订单重挂成功 | "
                    f"旧订单: {old_order.order_id} @ {old_order.price:.2f} | "
                    f"新订单: {new_order.order_id} @ {new_order.price:.2f} | "
                    f"数量: {remaining_qty} | "
                    f"重挂次数: {self._maker_wait_state.reposition_count}"
                )
                logger.info(
                    f"🔄 订单重挂成功 | "
                    f"旧订单: {old_order.order_id} @ {old_order.price:.2f} | "
                    f"新订单: {new_order.order_id} @ {new_order.price:.2f} | "
                    f"数量: {remaining_qty} | "
                    f"重挂次数: {self._maker_wait_state.reposition_count}"
                )
            else:
                print(f"❌ 重新挂单失败: {result.error_message}")
                logger.error(f"重新挂单失败: {result.error_message}")

        except Exception as e:
            print(f"❌ 重挂订单异常: {e}")
            logger.error(f"重挂订单异常: {e}")

        finally:
            # ========== 清除重挂标志（无论成功或失败） ==========
            self._maker_wait_state.is_repositioning = False


    # ========== 新增方法 (003-spreading-improvements): 双模式平仓 ==========

    async def _execute_market_close(self, total_quantity: Decimal) -> None:
        """
        执行市价平仓（立即执行）(003-spreading-improvements)

        市价平仓特点：
        - 并发发送Extended和Lighter市价平仓单
        - 快速成交，立即兑现利润
        - 适用场景：利润大，需要快速锁定收益

        Args:
            total_quantity: 平仓数量
        """
        logger.info(f"执行市价平仓: 数量={total_quantity}")

        try:
            # 创建临时Position对象（execute_close_position需要）
            temp_position = Position(
                state=PositionState.LONG,
                extended_entry_price=Decimal("0"),
                lighter_entry_price=Decimal("0"),
                entry_spread=Decimal("0"),  # 市价平仓不需要计算价差
                entry_time=datetime.now(),
                extended_quantity=total_quantity,
                lighter_quantity=-total_quantity,
                extended_order_id="market_close",
                lighter_order_id="market_close"
            )

            # 使用trade_executor的taker模式平仓（016-spread-optimize已经支持）
            result = await self.trade_executor.execute_close_position(
                temp_position,
                total_quantity
            )

            if result.success:
                logger.info(
                    f"✅ 市价平仓成功 | "
                    f"Ext={result.extended_order_id}, Lig={result.lighter_order_id} | "
                    f"耗时={result.execution_time:.3f}s"
                )

                # 进入IDLE状态
                self.state_manager.set_state(BotState.IDLE, "市价平仓完成")
                await self.state_manager.save_state()
            else:
                logger.error(f"市价平仓失败: {result.error_message}")
                # 市价平仓失败，回到HOLDING状态
                self.state_manager.set_state(BotState.HOLDING, "市价平仓失败")
                await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"市价平仓异常: {e}")
            self.state_manager.set_state(BotState.ERROR, f"市价平仓异常: {e}")
            await self.state_manager.save_state()

    async def _execute_limit_close(self, total_quantity: Decimal) -> None:
        """
        执行限价平仓（等待成交）(003-spreading-improvements)

        限价平仓特点：
        - Extended使用Maker挂单模式（低手续费）
        - 等待订单成交
        - 适用场景：利润小，使用限价单降低成本

        Args:
            total_quantity: 平仓数量
        """
        logger.info(f"执行限价平仓: 数量={total_quantity}")

        try:
            # 使用Maker模式平仓（017-ext-maker-mode已经支持）
            result = await self.trade_executor.place_maker_close_order(total_quantity)

            if not result.success or result.extended_order_id is None:
                logger.error(f"Extended Maker平仓订单失败: {result.error_message}")
                self.state_manager.set_state(BotState.HOLDING, "Maker平仓订单失败")
                await self.state_manager.save_state()
                return

            # 初始化Maker等待状态
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()

            # 创建MakerOrder对象
            close_order = MakerOrder(
                order_id=result.extended_order_id,
                price=result.extended_price,
                quantity=total_quantity,
                side='sell',  # 平仓时卖出
                is_opening=False  # 标记为平仓订单
            )

            self._maker_wait_state.current_order = close_order

            logger.info(
                f"✅ Extended Maker平仓订单已挂出 | "
                f"order_id={close_order.order_id} | "
                f"price={close_order.price} | "
                f"quantity={close_order.quantity}"
            )

            # 进入CLOSING_LIMIT状态（003-spreading-improvements: 新状态）
            self.state_manager.set_state(
                BotState.CLOSING_LIMIT,
                f"Maker平仓订单已挂出: {result.extended_order_id}"
            )
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"限价平仓异常: {e}")
            self.state_manager.set_state(BotState.HOLDING, f"限价平仓异常: {e}")
            await self.state_manager.save_state()


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
        default=Decimal("0.0004"),
        dest="min_spread_threshold",
        help="最小价差阈值 (默认: 0.002 = 0.04%%)"
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
        default=Decimal("0"),
        help="最小利润 (默认: 0 = 0%%)"
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
        default=None,  # 使用 models.py 中的默认值
        dest="spread_step",
        help="价差步长值 (默认: 0.00002 = 0.002%%) (003-spreading-improvements)"
    )

    parser.add_argument(
        "--initial-open-spread",
        type=Decimal,
        default=None,  # 使用 models.py 中的默认值
        dest="initial_open_spread",
        help="初始开仓价差阈值 (默认: 0.0006 = 0.06%%) (003-spreading-improvements)"
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

    # ========== 修改 (003-spreading-improvements): 只传递非None的参数，保留dataclass默认值 ==========
    config_kwargs = {
        'symbol': args.symbol,
        'target_quantity': args.target_quantity,
        'min_spread_threshold': args.min_spread_threshold,
        'slippage_buffer': args.slippage_buffer,
        'min_profit': args.min_profit,
        'max_spread': args.max_spread,
        'balance_check_buffer': args.balance_check_buffer,
        'single_side_timeout': args.single_side_timeout,
        'open_wait_timeout': args.open_wait_timeout,
        'dry_run': args.dry_run,
        'verbose': args.verbose,
    }

    # 只传递非None的参数，保留dataclass默认值
    if args.spread_step is not None:
        config_kwargs['spread_step'] = args.spread_step
    if args.initial_open_spread is not None:
        config_kwargs['initial_open_spread'] = args.initial_open_spread

    return BotConfig(**config_kwargs)


async def main():
    """主函数"""
    # 解析配置
    config = parse_arguments()

    # ========== 新增: 打印命令行参数解析后的配置用于调试 ==========
    print(f"🔧 [命令行参数解析] 阶梯开仓参数:")
    print(f"   - initial_open_spread = {config.initial_open_spread} ({config.initial_open_spread:.3%})")
    print(f"   - spread_step = {config.spread_step} ({config.spread_step:.3%})")
    print(f"   - opening_count = {config.opening_count}")
    print(f"   - current_open_threshold = {config.current_open_threshold} ({config.current_open_threshold:.3%})")
    print(f"   - 计算公式: current = initial + (count * step) = {config.initial_open_spread} + ({config.opening_count} * {config.spread_step}) = {config.current_open_threshold}")

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
