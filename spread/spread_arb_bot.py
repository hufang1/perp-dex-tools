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
from contextlib import asynccontextmanager
import uuid
import csv
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging
import argparse
import os
import math
from collections import deque

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
    RealTimeSpreadInfo,
)
from feishu_notifier import FeishuNotifier
from dashboard_ingestor import DashboardIngestor
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


class _DropNoisyLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "positions列表为空" in msg:
            return False
        return True


_noise_filter = _DropNoisyLogs()
logging.getLogger().addFilter(_noise_filter)
logging.getLogger("EXTENDED_ETH").addFilter(_noise_filter)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_noise_filter)
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

        # 防止Maker状态并发更新
        self._maker_state_lock = asyncio.Lock()
        self._maker_lock_wait_total = 0.0
        self._maker_lock_wait_max = 0.0
        self._maker_lock_acquire_count = 0

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
        self._maker_event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._maker_event_task: Optional[asyncio.Task] = None
        self._maker_event_latest: Dict[str, tuple] = {}
        self._maker_event_enqueued: set = set()
        self._last_open_capacity_log_time: float = 0.0
        self._last_open_capacity_reason: str = ""
        self._notifier: Optional[FeishuNotifier] = None
        self._dashboard_ingestor: Optional[DashboardIngestor] = None
        self._last_dashboard_sample_time: float = 0.0
        self._last_dashboard_position_time: float = 0.0
        self._last_close_context: Optional[Dict[str, object]] = None
        self._maker_close_fail_count: int = 0
        self._last_maker_order_id: Optional[str] = None
        self._last_maker_is_opening: Optional[bool] = None
        self._last_maker_context_id: Optional[str] = None
        self._last_maker_context_state: Optional[BotState] = None
        self._last_state_seen: Optional[BotState] = None
        self._alignment_check_in_progress: bool = False
        self._last_maker_recovery_check_time: float = 0.0
        self._run_ext_volume: Decimal = Decimal("0")  # USDT
        self._run_lig_volume: Decimal = Decimal("0")  # USDT
        self._run_total_volume: Decimal = Decimal("0")  # USDT
        self._run_ext_open_taker_volume: Decimal = Decimal("0")
        self._run_ext_open_maker_volume: Decimal = Decimal("0")
        self._run_lig_open_taker_volume: Decimal = Decimal("0")
        self._run_lig_open_maker_volume: Decimal = Decimal("0")
        self._run_profit: Decimal = Decimal("0")
        self._run_fees: Decimal = Decimal("0")
        self._last_trade_funds_delta: Decimal = Decimal("0")
        self._cum_trade_funds_delta: Decimal = Decimal("0")
        self._session_start_funds: Optional[Decimal] = None
        self._floating_base_funds: Optional[Decimal] = None
        self._boll_samples: deque = deque()
        self._boll_last_sample_time: float = 0.0
        self._boll_last_bands: Optional[tuple] = None
        self._last_boll_log_time: float = 0.0
        self._bandwidth_blocked: bool = False
        self._open_maker_confirm_start: Optional[float] = None

        logger.debug("套利机器人初始化完成")
        logger.debug(f"配置: 交易对={config.symbol}, "
                   f"数量={config.target_quantity}, "
                   f"开仓阈值={config.min_spread_threshold:.3%}, "
                   f"最小利润={config.min_profit:.3%}")
        # ========== 新增: 打印阶梯开仓配置用于调试 ==========
        print("🔧 [配置初始化] 开仓阈值参数:")
        print(f"   - open_maker_sigma = {config.open_maker_sigma}")
        print(f"   - open_taker_sigma = {config.open_taker_sigma}")
        print("🔧 [配置初始化] 平仓阈值参数:")
        print(f"   - limit_close_spread_a = {config.limit_close_spread_a} ({config.limit_close_spread_a:.3%})")
        print(f"   - market_close_spread_b = {config.market_close_spread_b} ({config.market_close_spread_b:.3%})")
        logger.info(
            f"开仓σ配置: maker={config.open_maker_sigma}, taker={config.open_taker_sigma} | "
            f"平仓A={config.limit_close_spread_a:.3%} B={config.market_close_spread_b:.3%}"
        )

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

            # 2.3 启动飞书通知器（不影响主循环）
            webhook = os.getenv("FEISHU_WEBHOOK_URL")
            self._notifier = FeishuNotifier(webhook)
            await self._notifier.start()
            self._notify(
                "🚀 套利程序启动",
                [
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"交易对: {self.config.symbol}",
                    f"数量: {self.config.target_quantity}",
                ],
            )

            # 2.4 启动Dashboard数据写入器（不影响主循环）
            self._dashboard_ingestor = DashboardIngestor(self.config.dashboard_ingest_url)
            await self._dashboard_ingestor.start()

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

            # 6.5 启动Maker事件处理任务（串行处理WS状态事件）
            self._maker_event_task = asyncio.create_task(self._maker_event_loop())

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

            # 停止Maker事件处理任务
            if self._maker_event_task:
                try:
                    await self._maker_event_queue.put(None)
                    await asyncio.wait_for(self._maker_event_task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    self._maker_event_task.cancel()
                self._maker_event_task = None

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

            # 停止飞书通知器（带超时）
            if self._notifier:
                try:
                    await asyncio.wait_for(self._notifier.stop(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("停止飞书通知器超时")

            # 停止Dashboard写入器（带超时）
            if self._dashboard_ingestor:
                try:
                    await asyncio.wait_for(self._dashboard_ingestor.stop(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("停止Dashboard写入器超时")

            self._notify(
                "🛑 套利程序停止",
                [
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"交易对: {self.config.symbol}",
                    f"统计: {self._format_stats_line()}",
                    f"本次总交易量(USDT): {self._run_total_volume:.2f}",
                    f"本次实际盈亏(USDT): {(self._run_profit - self._run_fees):.4f}",
                ],
            )

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
                if self._last_state_seen is not None and state != self._last_state_seen:
                    await self._handle_state_transition_alignment(self._last_state_seen, state)
                self._last_state_seen = state
                # 兜底：定期检查最近Maker订单是否已成交但未触发对冲
                await self._maybe_recover_maker_fill_out_of_band()

                if state == BotState.IDLE:
                    await self._process_idle_state()

                elif state == BotState.HOLDING:
                    await self._process_holding_state()

                elif state == BotState.OPENING:
                    await self._process_opening_state()

                elif state == BotState.OPENING_TAKER:
                    await self._process_opening_taker_state()

                elif state == BotState.OPENING_MAKER_WAIT:  # 新增 (017-ext-maker-mode)
                    await self._process_opening_maker_wait_state()

                elif state == BotState.OPENING_WAIT:
                    await self._process_opening_wait_state()

                elif state == BotState.CLOSING:
                    await self._process_closing_state()

                elif state == BotState.CLOSING_TAKER:  # 并发市价平仓
                    await self._process_closing_taker_state()

                elif state == BotState.CLOSING_MAKER_WAIT:  # 平仓挂单等待成交
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

    def _infer_alignment_mode(self, prev_state: BotState, next_state: BotState) -> Optional[str]:
        opening_states = {
            BotState.OPENING,
            BotState.OPENING_TAKER,
            BotState.OPENING_WAIT,
            BotState.OPENING_MAKER_WAIT,
        }
        closing_states = {
            BotState.CLOSING,
            BotState.CLOSING_TAKER,
            BotState.CLOSING_WAIT,
            BotState.CLOSING_MAKER_WAIT,
        }
        if prev_state in closing_states or next_state in closing_states:
            return "closing"
        if prev_state in opening_states or next_state in opening_states:
            return "opening"
        if prev_state == BotState.LIGHTER_HEDGING or next_state == BotState.LIGHTER_HEDGING:
            if hasattr(self, "_hedging_state") and getattr(self._hedging_state, "is_closing", False):
                return "closing"
            if self._last_maker_is_opening is not None:
                return "opening" if self._last_maker_is_opening else "closing"
        return None

    async def _handle_state_transition_alignment(self, prev_state: BotState, next_state: BotState) -> None:
        if self._alignment_check_in_progress:
            return
        mode = self._infer_alignment_mode(prev_state, next_state)
        if mode is None:
            return
        self._alignment_check_in_progress = True
        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            if abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                return

            ext_abs = abs(ext_position)
            lig_abs = abs(lig_position)
            diff = abs(ext_abs - lig_abs)
            if diff < tolerance:
                return

            if mode == "closing":
                # 仅在进入CLOSING_WAIT时做强一致性检查，避免对冲中误判
                if next_state != BotState.CLOSING_WAIT:
                    return
                logger.error(
                    f"⚠️ 平仓阶段仓位不一致: Ext={ext_position} Lig={lig_position}，触发强平"
                )
                self._notify(
                    "⚠️ 仓位不一致(平仓阶段)",
                    [
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        f"交易对: {self.config.symbol}",
                        f"阶段: 平仓",
                        f"Ext仓位: {ext_position}",
                        f"Lig仓位: {lig_position}",
                        "动作: 强制全平",
                    ],
                )
                await self._force_close_positions()
                self.state_manager.set_state(BotState.CLOSING_WAIT, "平仓阶段仓位不一致，强平后验证")
                await self.state_manager.save_state()
                return

            # 开仓阶段：仅在进入OPENING_WAIT时做单边回滚，避免对冲中误判
            if next_state != BotState.OPENING_WAIT:
                return

            pending_qty = None
            if hasattr(self, "_pending_open_position") and self._pending_open_position:
                pending_qty = self._pending_open_position.quantity
            if pending_qty is None:
                pending_qty = self.config.target_quantity

            reduce_qty = min(diff, pending_qty)
            if reduce_qty < tolerance:
                return

            if ext_abs > lig_abs:
                side = "sell" if ext_position > 0 else "buy"
                logger.warning(
                    f"⚠️ 开仓阶段仓位不一致: Ext={ext_position} Lig={lig_position}，"
                    f"仅回滚本次开仓量{reduce_qty}"
                )
                self._notify(
                    "⚠️ 仓位不一致(开仓阶段)",
                    [
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        f"交易对: {self.config.symbol}",
                        f"阶段: 开仓",
                        f"Ext仓位: {ext_position}",
                        f"Lig仓位: {lig_position}",
                        f"回滚数量: {reduce_qty}",
                        "动作: 回滚单边(本次开仓量)",
                    ],
                )
                await self.trade_executor.rollback_position("extended", reduce_qty, side)
            else:
                side = "sell" if lig_position > 0 else "buy"
                logger.warning(
                    f"⚠️ 开仓阶段仓位不一致: Ext={ext_position} Lig={lig_position}，"
                    f"仅回滚本次开仓量{reduce_qty}"
                )
                self._notify(
                    "⚠️ 仓位不一致(开仓阶段)",
                    [
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        f"交易对: {self.config.symbol}",
                        f"阶段: 开仓",
                        f"Ext仓位: {ext_position}",
                        f"Lig仓位: {lig_position}",
                        f"回滚数量: {reduce_qty}",
                        "动作: 回滚单边(本次开仓量)",
                    ],
                )
                await self.trade_executor.rollback_position("lighter", reduce_qty, side)
        except Exception as e:
            logger.warning(f"仓位对齐检查异常: {e}")
        finally:
            self._alignment_check_in_progress = False

    async def _enter_idle_state(self, reason: str, check_positions: bool = True) -> None:
        """
        进入 IDLE 状态的统一方法

        自动检查持仓情况，如果没有持仓则重置成功开仓次数。

        Args:
            reason: 进入 IDLE 状态的原因
            check_positions: 是否检查实际持仓（默认True）
        """
        old_count = self.config.successful_opening_count

        # 检查实际持仓（如果需要）
        should_reset = False
        if check_positions:
            try:
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()

                tolerance = Decimal("0.0001")
                has_positions = abs(ext_position) > tolerance or abs(lig_position) > tolerance

                if not has_positions:
                    should_reset = True
                    logger.info(f"确认无持仓，重置成功开仓次数: {old_count} -> 0")
                else:
                    logger.info(f"仍有持仓 Ext={ext_position} Lig={lig_position}，不重置开仓次数")
            except Exception as e:
                logger.warning(f"检查持仓失败，不重置开仓次数: {e}")
        else:
            # 不检查持仓，直接重置
            should_reset = True

        # 重置成功开仓次数（如果需要）
        if should_reset:
            await self.open_strategy.on_all_positions_closed()

        # 设置状态
        self.state_manager.set_state(BotState.IDLE, reason)
        await self.state_manager.save_state()

        logger.info(f"进入IDLE状态: {reason}")

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
                        # 有正常持仓，进入 HOLDING 状态（必要时重建Portfolio）
                        await self.close_strategy.ensure_portfolio_from_exchange(ext_position, lig_position, tolerance)
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

        await self._maybe_send_dashboard_snapshot(spread_info)

        self._update_bollinger(spread_info.spread_pct)
        if not await self._check_bandwidth_gate():
            should_open, reason, use_taker = False, "带宽过窄，停止开仓", False
        else:
            should_open, reason, use_taker = await self._should_open_bollinger(spread_info)
        thresholds = await self._get_open_sigma_thresholds()
        if thresholds:
            midline, maker_th, taker_th, _std = thresholds
            threshold_info = f"挂单阈值{maker_th:.3%} / 市价阈值{taker_th:.3%}(中轴{midline:.3%})"
        else:
            threshold_info = "布林带样本不足"

        # 输出空闲状态监控日志（每5秒一次）
        if not hasattr(self, '_last_idle_log_time'):
            self._last_idle_log_time = 0
        current_time = time.time()
        if current_time - self._last_idle_log_time >= 5.0:
            current_spread = spread_info.spread_pct
            status_text = "开仓" if should_open else "不开仓"
            bandwidth_text = ""
            bands = self._get_bollinger_bands()
            if bands:
                mid, upper, lower, _ = bands
                if mid > 0:
                    bandwidth_text = f" bw={(upper - lower) / mid:.3%}"
            print(f"📊 空闲 s={current_spread:.3%}{bandwidth_text} thr={threshold_info} {status_text}")
            self._last_idle_log_time = current_time

        # 记录实时价差到CSV（每10秒一次）
        if current_time - self._last_spread_log_time >= self._spread_log_interval:
            self._log_spread_to_csv(spread_info)
            self._last_spread_log_time = current_time

        # ========== 新增: 调试日志 ==========
        if should_open:
            print(f"🔍 [开仓触发] should_open=True, 准备执行开仓流程...")

        if await self._apply_spread_rules(
            BotState.IDLE,
            spread_info,
            rule_ids=["open"],
            should_open=should_open,
            use_taker=use_taker,
            reason=reason,
        ):
            return

        # 兜底：价差变化导致撤单后仍成交时，尝试补对冲
        await self._maybe_recover_maker_fill_out_of_band()

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
            await self._enter_idle_or_holding_after_open_failure("无法获取价差信息")
            return

        # ========== 新增 (017-ext-maker-mode): Maker模式分支 ==========
        if self.config.use_maker_mode:
            await self._process_opening_maker_mode(spread_info)
        else:
            await self._process_opening_taker_mode(spread_info)

    async def _process_opening_taker_state(self) -> None:
        """处理 OPENING_TAKER 状态：强制市价开仓"""
        logger.info("执行市价开仓...")
        import time
        self._last_open_time = time.time()
        spread_info = self.spread_monitor.get_current_spread()
        if spread_info is None or not spread_info.is_valid():
            logger.warning("无法获取价差信息，取消市价开仓")
            await self._enter_idle_or_holding_after_open_failure("无法获取价差信息")
            return
        await self._process_opening_taker_mode(spread_info)

    async def _process_opening_maker_mode(self, spread_info) -> None:
        """处理Maker模式开仓"""
        try:
            from uuid import uuid4
            pre_ext_pos = None
            pre_lig_pos = None
            try:
                pre_ext_pos = await self.extended_client.get_account_positions()
                pre_lig_pos = await self.lighter_client.get_account_positions()
            except Exception as e:
                logger.debug(f"获取下单前仓位失败(开仓): {e}")

            # 下Extended Maker订单
            result = await self.trade_executor.place_maker_open_order(
                self.config.target_quantity
            )

            if not result.success or result.extended_order_id is None:
                logger.error(f"Extended Maker开仓订单失败: {result.error_message}")
                await self._enter_idle_or_holding_after_open_failure("Maker订单失败")
                return

            # 初始化Maker等待状态
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()

            context_id = f"maker-{uuid4().hex}"
            self._maker_wait_state.current_order = MakerOrder(
                order_id=result.extended_order_id,
                price=result.extended_price,
                quantity=self.config.target_quantity,
                side='buy',
                is_opening=True,
                context_id=context_id
            )
            self._maker_wait_state.ext_position_before = pre_ext_pos
            self._maker_wait_state.lig_position_before = pre_lig_pos
            self._maker_wait_state.context_id = context_id
            self._last_maker_order_id = str(result.extended_order_id)
            self._last_maker_is_opening = True
            self._last_maker_context_id = context_id
            self._last_maker_context_state = BotState.OPENING_MAKER_WAIT
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
            await self._enter_idle_or_holding_after_open_failure(f"开仓异常: {e}")
            return

    async def _process_opening_taker_mode(self, spread_info) -> None:
        """处理Taker模式开仓（原有逻辑）"""
        # 执行开仓
        result = await self.trade_executor.execute_open_position(
            self.config.target_quantity,
            spread_info
        )
        if result.extended_price or result.lighter_price:
            logger.info(
                f"[taker价] Ext={result.extended_price or spread_info.ext_ask:.2f} "
                f"Lig={result.lighter_price or spread_info.lig_bid:.2f}"
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
            open_is_taker=True,
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
            # 可能是本地Portfolio丢失，但交易所仍有仓位
            try:
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()
                tolerance = Decimal("0.001")
                if abs(ext_position) >= tolerance and abs(lig_position) >= tolerance:
                    synced = await self.close_strategy.ensure_portfolio_from_exchange(
                        ext_position, lig_position, tolerance
                    )
                    if synced:
                        logger.info("已从交易所仓位恢复Portfolio，继续持仓逻辑")
                    else:
                        logger.warning("持仓信息丢失，返回 IDLE 状态")
                        self.state_manager.set_state(BotState.IDLE, "持仓信息丢失")
                        await self.state_manager.save_state()
                        return
                else:
                    logger.warning("持仓信息丢失，返回 IDLE 状态")
                    self.state_manager.set_state(BotState.IDLE, "持仓信息丢失")
                    await self.state_manager.save_state()
                    return
            except Exception as e:
                logger.warning(f"检查持仓失败: {e}")
                self.state_manager.set_state(BotState.IDLE, "持仓信息丢失")
                await self.state_manager.save_state()
                return
        else:
            # 本地有持仓，但交易所可能已平仓：同步校验
            try:
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()
                tolerance = Decimal("0.001")
                if abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                    logger.warning("检测到实际无仓位，清理本地持仓并回到IDLE")
                    self.close_strategy.close_all()
                    self._maker_close_fail_count = 0
                    self.state_manager.update_position(None)
                    self.state_manager.set_state(BotState.IDLE, "实际无仓位，清理本地持仓")
                    await self.state_manager.save_state()
                    return
            except Exception as e:
                logger.warning(f"同步仓位检查失败: {e}")

        # 使用SpreadMonitor获取当前价差 (016-spread-optimize)
        spread_info = self.spread_monitor.get_current_spread()

        if spread_info is None or not spread_info.is_valid():
            return
        close_spread_info = self._build_close_spread_info(spread_info)
        self._update_bollinger(spread_info.spread_pct)

        await self._maybe_send_dashboard_snapshot(spread_info)

        # 检查是否可以继续开仓（布林带策略 + 带宽过滤）
        if not await self._check_bandwidth_gate():
            should_open, reason, use_taker = False, "带宽过窄，停止开仓", False
        else:
            should_open, reason, use_taker = await self._should_open_bollinger(spread_info)

        await self._apply_spread_rules(
            BotState.HOLDING,
            spread_info,
            rule_ids=["open"],
            should_open=should_open,
            use_taker=use_taker,
            reason=reason,
        )

        # 兜底：若状态已切走但挂单未撤单且成交未被WS捕获，定期检查最后一笔Maker订单
        await self._maybe_recover_maker_fill_out_of_band()

        # 输出持仓状态日志（格式：icon 状态「持仓中」 实时价差，开仓阈值，平仓口径价差，平仓阈值，结果）
        # 限制频率：每5秒输出一次
        import time
        current_time = time.time()
        if current_time - self._last_holding_log_time >= self._holding_log_interval:
            current_spread = spread_info.spread_pct
            close_spread = close_spread_info.spread_pct if close_spread_info else Decimal("0")
            thresholds = await self._get_open_sigma_thresholds()
            open_taker = self.close_strategy.portfolio.has_open_taker()
            open_mode_label = "taker" if open_taker else "maker"
            if thresholds:
                midline, maker_th, taker_th, std = thresholds
                open_formula = f">=maker{maker_th:.3%}/taker{taker_th:.3%}"
            else:
                midline = Decimal("0")
                maker_th = taker_th = Decimal("0")
                std = Decimal("0")
                open_formula = "NA"

            # 计算平仓触发阈值（平仓价差口径）
            entry_spread = self.close_strategy.get_weighted_avg_spread()
            if entry_spread > 0:
                profit_spread = entry_spread - close_spread
                portfolio = self.close_strategy.get_portfolio()
                taker_qty = sum(p.quantity for p in portfolio.get_active_positions() if getattr(p, "open_is_taker", False)) if portfolio else Decimal("0")
                total_qty = portfolio.total_quantity if portfolio else Decimal("0")
                taker_ratio = (taker_qty / total_qty) if total_qty > 0 else Decimal("0")
                fee = Decimal("0.00025")
                limit_cost = taker_ratio * fee
                market_cost = (Decimal("1") + taker_ratio) * fee
                inventory_ratio = await self._get_inventory_ratio()
                limit_base = (
                    entry_spread - self.config.limit_close_spread_a - limit_cost
                    + (inventory_ratio * self.config.limit_close_spread_a)
                )
                hysteresis = std * self.config.close_limit_hysteresis_sigma
                limit_threshold = limit_base - hysteresis
                market_threshold = min(
                    midline,
                    entry_spread - self.config.market_close_spread_b - market_cost
                    + (inventory_ratio * self.config.market_close_spread_b),
                )
                if thresholds:
                    close_formula = (
                        f"close<=entry-A{self.config.limit_close_spread_a:.3%}-cost{limit_cost:.3%}+skew{(inventory_ratio*self.config.limit_close_spread_a):.3%}"
                        f"-hys{hysteresis:.3%}/"
                        f"<=min(mid{midline:.3%},entry-B{self.config.market_close_spread_b:.3%}-cost{market_cost:.3%}+skew{(inventory_ratio*self.config.market_close_spread_b):.3%})"
                    )
                else:
                    close_formula = "NA"
            else:
                profit_spread = Decimal("0")
                close_formula = ""

            # ========== 新增 (003-spreading-improvements): 判断结果（双模式平仓） ==========
            decision = await self._evaluate_close_decision(spread_info, close_spread_info)
            if decision["should_close"]:
                close_mode = "市价" if decision["use_market"] else "限价"
                result = f"平仓({close_mode})"
            elif should_open:
                if time.time() - self._last_open_capacity_log_time < 10.0 and self._last_open_capacity_reason:
                    result = "不开仓(余额不足)"
                else:
                    result = "开仓"
            else:
                result = "不开仓"

            position_spread_text = f"{entry_spread:.3%}" if entry_spread > 0 else "-"
            close_spread_text = f"{close_spread:.3%}" if entry_spread > 0 else "-"
            profit_text = f"{profit_spread:.3%}" if entry_spread > 0 else "-"
            bandwidth_text = ""
            bands = self._get_bollinger_bands()
            if bands:
                mid, upper, lower, _ = bands
                if mid > 0:
                    bandwidth_text = f" bw={(upper - lower) / mid:.3%}"
            print(
                f"📊 持仓 s={current_spread:.3%}{bandwidth_text} "
                f"open={open_formula}({open_mode_label}) "
                f"entry={position_spread_text} close={close_spread_text} pnl={profit_text} "
                f"rule:{close_formula} -> {result}"
            )
            self._last_holding_log_time = current_time

        # 记录实时价差到CSV（每10秒一次）
        if current_time - self._last_spread_log_time >= self._spread_log_interval:
            self._log_spread_to_csv(spread_info)
            self._last_spread_log_time = current_time

        # ========== 新增 (003-spreading-improvements): 使用双模式平仓策略 ==========
        if await self._apply_spread_rules(
            BotState.HOLDING,
            spread_info,
            rule_ids=["close"],
        ):
            return

    async def _process_closing_state(self) -> None:
        """
        处理 CLOSING 状态：判断并执行平仓

        根据当前价差判断使用挂单平仓还是市价平仓：
        - 市价平仓：切换到 CLOSING_TAKER 状态
        - 限价平仓：直接挂 Maker 单，进入 CLOSING_MAKER_WAIT 状态
        """
        logger.info("进入CLOSING状态，判断平仓模式...")

        # 获取当前价差信息
        spread_info = self.spread_monitor.get_current_spread()
        await self._apply_spread_rules(
            BotState.CLOSING,
            spread_info,
            rule_ids=["mode"],
        )

    async def _execute_maker_close(self) -> None:
        """
        执行限价平仓：挂 Extended Maker 平仓单

        挂单后直接进入 CLOSING_MAKER_WAIT 状态等待成交
        """
        logger.info("执行限价平仓，挂Ext Maker平仓单...")

        # 获取 Portfolio 持仓信息
        portfolio = self.close_strategy.get_portfolio()
        if portfolio is None or portfolio.total_quantity == 0:
            logger.warning("持仓信息丢失或无持仓")
            self.state_manager.set_state(BotState.IDLE, "持仓信息丢失或无持仓")
            await self.state_manager.save_state()
            return

        total_quantity = portfolio.total_quantity

        try:
            from uuid import uuid4
            pre_ext_pos = None
            pre_lig_pos = None
            try:
                pre_ext_pos = await self.extended_client.get_account_positions()
                pre_lig_pos = await self.lighter_client.get_account_positions()
            except Exception as e:
                logger.debug(f"获取下单前仓位失败(平仓): {e}")

            # 下 Extended Maker 平仓订单
            result = await self.trade_executor.place_maker_close_order(total_quantity)

            if not result.success or result.extended_order_id is None:
                logger.error(f"Extended Maker平仓订单失败: {result.error_message}")
                self._notify_close_failure(f"Maker平仓订单失败: {result.error_message}")
                self._maker_close_fail_count += 1
                if self._maker_close_fail_count >= self.config.maker_close_fail_threshold:
                    logger.warning(
                        f"Maker平仓失败达到阈值{self.config.maker_close_fail_threshold}，改用市价平仓"
                    )
                    await self._execute_market_close(total_quantity)
                else:
                    self.state_manager.set_state(BotState.HOLDING, "Maker平仓订单失败")
                    await self.state_manager.save_state()
                return

            # 成功挂单则清零失败计数
            self._maker_close_fail_count = 0

            # 初始化 Maker 等待状态
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()

            context_id = f"maker-{uuid4().hex}"
            self._maker_wait_state.current_order = MakerOrder(
                order_id=result.extended_order_id,
                price=result.extended_price,
                quantity=total_quantity,
                side='sell',  # 平仓卖出
                is_opening=False,  # 标记为平仓订单
                context_id=context_id
            )
            self._maker_wait_state.ext_position_before = pre_ext_pos
            self._maker_wait_state.lig_position_before = pre_lig_pos
            self._maker_wait_state.context_id = context_id
            self._last_maker_order_id = str(result.extended_order_id)
            self._last_maker_is_opening = False
            self._last_maker_context_id = context_id
            self._last_maker_context_state = BotState.CLOSING_MAKER_WAIT
            self._maker_wait_state.start_time = datetime.now()

            # 启动 WebSocket 订单监控
            self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

            logger.info(
                f"✅ Extended Maker平仓订单已挂出 | "
                f"order_id={result.extended_order_id} | "
                f"price={result.extended_price} | "
                f"quantity={total_quantity}"
            )
            print(f"💥 CLOSING -> Maker平仓单已挂出 -> CLOSING_MAKER_WAIT")

            # 进入 CLOSING_MAKER_WAIT 状态（WebSocket 回调会处理：成交 -> LIGHTER_HEDGING，取消 -> HOLDING）
            self.state_manager.set_state(
                BotState.CLOSING_MAKER_WAIT,
                f"Maker平仓订单已挂出: {result.extended_order_id}"
            )
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"限价平仓异常: {e}")
            self._notify_close_failure(f"限价平仓异常: {e}")
            self.state_manager.set_state(BotState.HOLDING, f"平仓异常: {e}")
            await self.state_manager.save_state()

    async def _process_closing_taker_state(self) -> None:
        """
        处理 CLOSING_TAKER 状态：并发市价平仓

        核心职责：
        1. Extended 和 Lighter 并发发送市价平仓单
        2. 快速成交，立即兑现利润
        3. 完成后切换到 CLOSING_WAIT 状态验证仓位
        """
        logger.info("进入CLOSING_TAKER状态，执行并发市价平仓...")

        # 获取 Portfolio 持仓信息
        portfolio = self.close_strategy.get_portfolio()
        if portfolio is None or portfolio.total_quantity == 0:
            logger.warning("持仓信息丢失或无持仓")
            self.state_manager.set_state(BotState.IDLE, "持仓信息丢失或无持仓")
            await self.state_manager.save_state()
            return

        total_quantity = portfolio.total_quantity
        entry_spread = portfolio.get_total_entry_spread()

        try:
            # 创建临时 Position 对象（execute_close_position 需要）
            temp_position = Position(
                state=PositionState.LONG,
                extended_entry_price=Decimal("0"),
                lighter_entry_price=Decimal("0"),
                entry_spread=entry_spread,
                entry_time=datetime.now(),
                extended_quantity=total_quantity,
                lighter_quantity=-total_quantity,
                extended_order_id="market_close",
                lighter_order_id="market_close"
            )

            # 并发市价平仓
            result = await self.trade_executor.execute_close_position(
                temp_position,
                total_quantity
            )

            if result.success:
                logger.info(
                    f"✅ 市价平仓订单已发送 | "
                    f"Ext={result.extended_order_id}, Lig={result.lighter_order_id} | "
                    f"耗时={result.execution_time:.3f}s"
                )
                print(f"💥 CLOSING -> CLOSING_TAKER -> CLOSING_WAIT | 市价平仓订单已发送")
            else:
                logger.error(f"市价平仓失败: {result.error_message}")
                self._notify_close_failure(f"市价平仓失败: {result.error_message}")
                # 即使失败也进入 CLOSING_WAIT 检查仓位（可能部分成交）
                logger.warning("市价平仓失败，进入CLOSING_WAIT检查仓位")

            # 进入 CLOSING_WAIT 状态验证仓位
            import time
            self._closing_wait_start_time = time.time()
            self.state_manager.set_state(BotState.CLOSING_WAIT, f"市价平仓订单已发送，等待确认")
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"CLOSING_TAKER状态异常: {e}")
            self._notify_close_failure(f"市价平仓异常: {e}")
            self.state_manager.set_state(BotState.HOLDING, f"市价平仓异常: {e}")
            await self.state_manager.save_state()

    # ========== 保留旧方法以兼容其他调用 ==========
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
            self._notify_close_failure(f"平仓订单发送失败: {result.error_message}")

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
                reason = "等待超时且API异常，已强平"
                self.state_manager.set_state(BotState.PAUSED, reason)
                self._notify_paused(reason)
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
                    self._notify_open_failure("两边都没有仓位", ext_position, lig_position)

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
                    ext_avg = lig_avg = None
                    for _ in range(3):
                        try:
                            ext_pos = await self.extended_client.get_detailed_position()
                            lig_pos = await self.lighter_client.get_detailed_position()
                            ext_avg = ext_pos.get('avg_price') if ext_pos else None
                            lig_avg = lig_pos.get('avg_price') if lig_pos else None
                        except Exception as e:
                            logger.debug(f"获取开仓均价失败，使用成交价: {e}")
                        if ext_avg and lig_avg:
                            break
                        await asyncio.sleep(0.5)

                    try:
                        snapshot = await self.position_balance_monitor.get_position_balance()
                        if snapshot and snapshot.extended and snapshot.lighter:
                            self._floating_base_funds = (
                                snapshot.extended.total_balance + snapshot.lighter.total_balance
                            )
                    except Exception:
                        pass

                    self._notify_open_success(ext_position, lig_position, ext_avg=ext_avg, lig_avg=lig_avg)
                    self.close_strategy.add_position(self._pending_open_position)

                    # 记录本次运行的交易量（USDT名义）
                    open_qty = self._pending_open_position.quantity
                    ext_notional = self._pending_open_position.ext_price * open_qty
                    lig_notional = self._pending_open_position.lig_price * open_qty
                    self._record_run_volume(ext_notional, lig_notional)
                    if self._pending_open_position.open_is_taker:
                        self._run_ext_open_taker_volume += ext_notional
                        self._run_lig_open_taker_volume += lig_notional
                    else:
                        self._run_ext_open_maker_volume += ext_notional
                        self._run_lig_open_maker_volume += lig_notional

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
                        reason = "回滚后强平失败，仍有残余仓位"
                        self.state_manager.set_state(BotState.PAUSED, reason)
                        self._notify_paused(reason)

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
            reason = f"仓位检查异常: {error_msg}"
            self.state_manager.set_state(BotState.PAUSED, reason)
            self._notify_paused(reason)
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
                self._maker_close_fail_count = 0

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

                # 记录本次运行的交易量与盈亏（USDT名义）
                ctx = self._last_close_context or {}
                ext_bid = ctx.get("ext_bid")
                lig_ask = ctx.get("lig_ask")
                if isinstance(ext_bid, Decimal) and isinstance(lig_ask, Decimal):
                    self._record_run_volume(ext_bid * total_quantity, lig_ask * total_quantity)
                self._run_profit += profit
                self._run_fees += fees

                await self._notify_close_success(profit)

                self.state_manager.set_state(BotState.IDLE, f"平仓成功: 利润=${profit:.2f}")
                await self.state_manager.save_state()

                logger.info(f"✅ 平仓确认成功，进入IDLE状态: 利润=${profit:.2f}")

            elif ext_closed or lig_closed:
                # 两边有差异，强平
                logger.error(f"⚠️ 平仓后仓位不一致！Ext={'已平' if ext_closed else f'有仓位{ext_position}'}, "
                          f"Lig={'已平' if lig_closed else f'有仓位{lig_position}'}")
                logger.error("立即强平所有仓位...")
                self._notify_close_failure("平仓后仓位不一致，触发强平")

                await self._force_close_positions()

                # 强平后等待生效
                await asyncio.sleep(0.5)
                ext_final = await self.extended_client.get_account_positions()
                lig_final = await self.lighter_client.get_account_positions()

                if abs(ext_final) >= tolerance or abs(lig_final) >= tolerance:
                    # 强平失败，进入风控模式
                    logger.error(f"强平失败 Ext={ext_final} Lig={lig_final}，进入风控模式")
                    self._paused_start_time = time.time()
                    self._last_api_check_time = time.time()
                    reason = "强平失败，仍有残余仓位"
                    self.state_manager.set_state(BotState.PAUSED, reason)
                    self._notify_paused(reason)
                    await self.state_manager.save_state()
                    return

                # 强平成功：发送平仓成功消息（以资金变化为准）
                await self._notify_close_success(Decimal("0"))

                # ========== 新增：强平成功后，根据当前价差决定下一步状态 ==========
                spread_info = self.spread_monitor.get_current_spread()

                if spread_info and spread_info.is_valid():
                    # 检查是否满足平仓条件（可能还有残余利润）
                    close_spread_info = self._build_close_spread_info(spread_info)
                    decision = await self._evaluate_close_decision(spread_info, close_spread_info)

                    if decision["should_close"]:
                        # 还有平仓机会，重新进入 CLOSING 状态
                        logger.info(f"强平完成，检测到平仓机会，重新进入CLOSING状态")
                        self.state_manager.set_state(BotState.CLOSING, f"强平完成，重新平仓")
                    elif self.close_strategy.get_total_quantity() > 0:
                        # 有持仓，进入 HOLDING 状态
                        logger.info(f"强平完成，仍有持仓，进入HOLDING状态")
                        self.state_manager.set_state(BotState.HOLDING, f"强平完成，继续监控")
                    else:
                        # 无持仓，进入 IDLE 状态
                        logger.info(f"强平完成，无持仓，进入IDLE状态")
                        await self._enter_idle_state("平仓后仓位不一致，已强制清理", check_positions=False)
                else:
                    # 无法获取价差，直接进入 IDLE
                    logger.info(f"强平完成，无法获取价差，进入IDLE状态")
                    await self._enter_idle_state("平仓后仓位不一致，已强制清理", check_positions=False)

            else:
                # 两边都有持仓，平仓失败
                logger.warning(f"⚠️ 平仓失败：两边都仍有仓位 Ext={ext_position} Lig={lig_position}")

                # 保持 HOLDING 状态，等待下一次机会
                self._notify_close_failure("平仓失败：两边仍有持仓")
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
            reason = f"仓位检查异常: {e}"
            self.state_manager.set_state(BotState.PAUSED, reason)
            self._notify_paused(reason)
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
                reason = f"API异常: {error_message}"
                self.state_manager.set_state(BotState.PAUSED, reason)
                self._notify_paused(reason)
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
        ext_min_qty = getattr(self.extended_client, "min_order_size", tolerance)
        lig_min_qty = getattr(self.lighter_client, "min_order_size", tolerance)

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

                if ext_extra >= ext_min_qty:
                    side = "sell"  # 多头平仓 = 卖出
                    close_tasks.append(("extended", ext_extra, side))
                    logger.info(f"回滚 Extended {ext_extra}")
                elif ext_extra >= tolerance:
                    logger.warning(f"Extended回滚数量低于最小下单量({ext_min_qty})，跳过: {ext_extra}")

                if lig_extra >= lig_min_qty:
                    side = "buy"  # 空头平仓 = 买入
                    close_tasks.append(("lighter", lig_extra, side))
                    logger.info(f"回滚 Lighter {lig_extra}")
                elif lig_extra >= tolerance:
                    logger.warning(f"Lighter回滚数量低于最小下单量({lig_min_qty})，跳过: {lig_extra}")

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
        print(f"   - opening_count = {self.config.successful_opening_count}")
        print(f"   - current_open_threshold = {self.config.current_open_threshold} ({self.config.current_open_threshold:.3%})")
        print(f"   - 计算公式: current = initial + (count * step) = {self.config.initial_open_spread} + ({self.config.successful_opening_count} * {self.config.spread_step}) = {self.config.current_open_threshold}")
        logger.info(f"[状态加载后] 阶梯开仓配置: initial={self.config.initial_open_spread:.3%}, step={self.config.spread_step:.3%}, count={self.config.successful_opening_count}, current_threshold={self.config.current_open_threshold:.3%}")

        # 不保留上次实际开仓价差，统一重置
        self.config.cached_open_spread = Decimal("0")

        # 程序重启后，如果是OPENING、OPENING_WAIT、OPENING_MAKER_WAIT、CLOSING、CLOSING_WAIT、CLOSING_MAKER_WAIT状态，重置为IDLE
        # 因为之前的交易流程已经失效，需要重新开始
        if state in [BotState.OPENING, BotState.OPENING_TAKER, BotState.OPENING_WAIT, BotState.OPENING_MAKER_WAIT,
                     BotState.CLOSING, BotState.CLOSING_WAIT, BotState.CLOSING_MAKER_WAIT]:
            logger.info(f"检测到未完成的{state.value}状态，重置为IDLE")
            await self._enter_idle_state("程序重启，重置未完成的交易状态", check_positions=True)

        # 检查HOLDING状态但实际没有持仓的情况
        if state == BotState.HOLDING:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            has_position = abs(ext_position) >= tolerance or abs(lig_position) >= tolerance

            if not has_position:
                logger.info(f"检测到{state.value}状态但实际无持仓，重置为IDLE")
                await self._enter_idle_state("程序重启，检测到无实际持仓，重置状态", check_positions=False)

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

        # 事件入队，串行处理，避免与主循环/重挂并发
        self._enqueue_maker_event("filled", order)

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

        # 事件入队，串行处理，避免与主循环/重挂并发
        self._enqueue_maker_event("partial", order)

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

        # 事件入队，串行处理，避免与主循环/重挂并发
        self._enqueue_maker_event("canceled", order)

    def _enqueue_maker_event(self, event_type: str, order: MakerOrder) -> None:
        """将Maker事件放入队列，交由事件循环串行处理"""
        if self._maker_event_queue is None:
            asyncio.create_task(self._handle_maker_order_event(event_type, order))
            return
        order_id = str(order.order_id)
        self._maker_event_latest[order_id] = (event_type, order)
        if order_id in self._maker_event_enqueued:
            return
        try:
            self._maker_event_queue.put_nowait(order_id)
            self._maker_event_enqueued.add(order_id)
        except asyncio.QueueFull:
            try:
                dropped = self._maker_event_queue.get_nowait()
                if dropped in self._maker_event_enqueued:
                    self._maker_event_enqueued.remove(dropped)
                self._maker_event_queue.put_nowait(order_id)
                self._maker_event_enqueued.add(order_id)
                logger.warning(
                    f"Maker事件队列已满，丢弃旧事件并替换 | dropped={dropped} new={order_id}"
                )
            except Exception:
                logger.error(f"Maker事件队列已满，丢弃事件: {event_type} | order_id={order_id}")

    async def _handle_maker_order_canceled(self, order: MakerOrder) -> None:
        """
        处理 Maker订单取消（异步任务）

        Args:
            order: 被取消的订单
        """
        try:
            async with self._maker_lock("ws_canceled"):
                # 检查当前状态，避免重复处理
                current_state = self.state_manager.get_state()

                # 只有在 OPENING_MAKER_WAIT 或 CLOSING_MAKER_WAIT 状态才处理
                if current_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                    logger.info(f"当前状态={current_state.value}，跳过WebSocket取消回调")
                    return

                # 确保是当前订单
                if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                    if self._maker_wait_state.current_order.order_id != order.order_id:
                        logger.info(f"订单取消非当前订单，跳过 | order_id={order.order_id}")
                        return

                # 停止监控
                self.maker_order_monitor.stop_monitoring()

                # 根据订单类型决定下一个状态
                if order.is_opening:
                    # ========== 修复：开仓订单取消，先检查是否有其他持仓 ==========
                    # 检查 Portfolio 中是否有其他持仓
                    portfolio = self.close_strategy.get_portfolio()
                    total_quantity = portfolio.total_quantity

                    if total_quantity > 0:
                        # 有其他持仓，进入 HOLDING 状态
                        logger.info(
                            f"开仓订单已取消，但有其他持仓 {total_quantity}，进入HOLDING状态"
                        )
                        handled = await self._safe_exit_maker_wait(
                            BotState.HOLDING,
                            f"开仓订单已取消，但有持仓({total_quantity})",
                            is_opening=True,
                        )
                        if handled:
                            return
                    else:
                        # 无持仓，进入 IDLE 状态
                        logger.info("开仓订单已取消，无持仓，进入IDLE状态")
                        handled = await self._safe_exit_maker_wait(
                            BotState.IDLE,
                            "开仓订单已取消（WebSocket）",
                            is_opening=True,
                        )
                        if handled:
                            return
                else:
                    # 平仓订单取消 -> 若实际已平仓，进入确认；否则回HOLDING
                    try:
                        ext_position = await self.extended_client.get_account_positions()
                        lig_position = await self.lighter_client.get_account_positions()
                        tolerance = Decimal("0.001")
                        ext_closed = abs(ext_position) < tolerance
                        lig_closed = abs(lig_position) < tolerance
                        if ext_closed and lig_closed:
                            import time
                            self._closing_wait_start_time = time.time()
                            self.state_manager.set_state(
                                BotState.CLOSING_WAIT,
                                "平仓订单取消后检测到无仓位，验证平仓",
                            )
                            await self.state_manager.save_state()
                            return
                    except Exception as e:
                        logger.warning(f"平仓取消后检查仓位失败: {e}")

                    handled = await self._safe_exit_maker_wait(
                        BotState.HOLDING,
                        "平仓订单已取消（WebSocket）",
                        is_opening=False,
                    )
                    if handled:
                        return

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
            async with self._maker_lock("ws_filled"):
                # 检查当前状态，避免重复处理
                current_state = self.state_manager.get_state()

                # 如果已经在处理中（LIGHTER_HEDGING, OPENING_WAIT, CLOSING_WAIT），跳过
                if current_state in [BotState.LIGHTER_HEDGING, BotState.OPENING_WAIT, BotState.CLOSING_WAIT]:
                    logger.info(f"订单成交已在处理中（状态={current_state.value}），跳过WebSocket回调")
                    return

                # 只有在 OPENING_MAKER_WAIT 或 CLOSING_MAKER_WAIT 状态才处理
                if current_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                    # 可能是价差切换/撤单后仍成交，尝试补对冲
                    await self._recover_maker_fill_out_of_band(order)
                    return

                # 确保是当前订单
                if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                    if self._maker_wait_state.context_id and order.context_id is None:
                        order.context_id = self._maker_wait_state.context_id
                    if (
                        self._maker_wait_state.current_order.order_id != order.order_id or
                        (
                            self._maker_wait_state.context_id and
                            order.context_id and
                            self._maker_wait_state.context_id != order.context_id
                        )
                    ):
                        logger.info(f"订单成交非当前订单，跳过 | order_id={order.order_id}")
                        return

                # 停止监控
                self.maker_order_monitor.stop_monitoring()

                # 额外保护：根据开/平仓场景判断是否需要对冲
                try:
                    ext_position = await self.extended_client.get_account_positions()
                    lig_position = await self.lighter_client.get_account_positions()
                    tolerance = Decimal("0.001")
                    is_opening = (current_state == BotState.OPENING_MAKER_WAIT)
                    if is_opening and abs(ext_position) < tolerance:
                        logger.warning(
                            f"Maker成交但Ext仓位≈0，跳过对冲 | order_id={order.order_id} ext_pos={ext_position}"
                        )
                        self.state_manager.set_state(BotState.OPENING_WAIT, "成交但Ext仓位为空，转入仓位确认")
                        await self.state_manager.save_state()
                        return
                    if (not is_opening) and abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                        logger.warning(
                            f"平仓成交但两边仓位≈0，跳过对冲 | order_id={order.order_id} "
                            f"ext_pos={ext_position} lig_pos={lig_position}"
                        )
                        self.state_manager.set_state(BotState.CLOSING_WAIT, "成交但两边仓位为空，转入仓位确认")
                        await self.state_manager.save_state()
                        return
                except Exception as e:
                    logger.debug(f"Maker成交后Ext仓位校验失败，继续对冲: {e}")

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

    async def _recover_maker_fill_out_of_band(self, order: MakerOrder) -> None:
        """成交晚到：不在Maker等待状态时，尝试检测单边并补对冲"""
        try:
            current_state = self.state_manager.get_state()
            if current_state in [BotState.PAUSED, BotState.OPENING_TAKER, BotState.CLOSING_TAKER]:
                logger.debug(f"补对冲跳过(非Maker状态): {current_state.value}")
                return

            if self._last_maker_is_opening is None:
                logger.debug("补对冲跳过: 无Maker上下文")
                return
            if not self._last_maker_context_id or not self._last_maker_context_state:
                logger.debug(
                    "补对冲跳过: Maker上下文不完整 | "
                    f"ctx={self._last_maker_context_id} state={self._last_maker_context_state}"
                )
                return
            if self._last_maker_context_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                logger.debug(
                    "补对冲跳过: 非Maker等待上下文 | "
                    f"state={self._last_maker_context_state.value}"
                )
                return
            if order.context_id is None:
                logger.debug("补对冲跳过: 订单缺少context_id")
                return
            if order.context_id != self._last_maker_context_id:
                logger.info(
                    "成交订单context不匹配，忽略 | "
                    f"order_id={order.order_id} ctx={order.context_id} last_ctx={self._last_maker_context_id}"
                )
                return

            if self._last_maker_order_id and str(order.order_id) != self._last_maker_order_id:
                logger.info(
                    f"成交订单非最近Maker订单，忽略 | order_id={order.order_id} last={self._last_maker_order_id}"
                )
                return

            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")

            if order.is_opening and abs(ext_position) < tolerance:
                logger.warning(
                    f"成交晚到(开仓)但Ext仓位≈0，跳过补对冲 | order_id={order.order_id} ext_pos={ext_position}"
                )
                return
            if (not order.is_opening) and abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                logger.warning(
                    f"成交晚到(平仓)但两边仓位≈0，跳过补对冲 | order_id={order.order_id} "
                    f"ext_pos={ext_position} lig_pos={lig_position}"
                )
                return

            imbalance = ext_position + lig_position  # lig为负时应接近0
            if abs(imbalance) < tolerance:
                logger.info("成交晚到但仓位已平衡，跳过补对冲")
                return

            hedge_qty = abs(imbalance)
            if hedge_qty <= 0:
                return

            # 创建MakerWaitState以携带is_opening给对冲逻辑
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()
            self._maker_wait_state.current_order = MakerOrder(
                order_id=order.order_id,
                price=order.avg_fill_price,
                quantity=hedge_qty,
                side=order.side,
                is_opening=order.is_opening,
                context_id=order.context_id,
            )
            self._maker_wait_state.context_id = order.context_id

            if not hasattr(self, '_hedging_state'):
                from models import HedgingState
                self._hedging_state = HedgingState()
            self._hedging_state.ext_filled_quantity = hedge_qty
            self._hedging_state.ext_filled_price = order.avg_fill_price
            self._hedging_state.start_time = datetime.now()

            if order.is_opening:
                self.state_manager.set_state(BotState.LIGHTER_HEDGING, "成交晚到，补Lighter开仓对冲")
            else:
                self._hedging_state.is_closing = True
                self.state_manager.set_state(BotState.LIGHTER_HEDGING, "成交晚到，补Lighter平仓对冲")
            await self.state_manager.save_state()

            logger.warning(
                f"成交晚到触发补对冲 | order_id={order.order_id} | "
                f"ext={ext_position} lig={lig_position} hedge={hedge_qty}"
            )
        except Exception as e:
            logger.error(f"成交晚到补对冲失败: {e}", exc_info=True)

    async def _maybe_recover_maker_fill_out_of_band(self) -> None:
        """兜底轮询：检查最近一笔Maker订单是否已成交但未触发对冲"""
        now = time.time()
        if now - self._last_maker_recovery_check_time < 3.0:
            return
        self._last_maker_recovery_check_time = now

        if not self._last_maker_order_id:
            return
        if self._last_maker_is_opening is None:
            return
        if not self._last_maker_context_id or not self._last_maker_context_state:
            return
        if self._last_maker_context_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
            return

        # 若仍在Maker等待状态，交给主流程处理
        current_state = self.state_manager.get_state()
        if current_state in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT, BotState.LIGHTER_HEDGING]:
            return
        if current_state in [BotState.PAUSED, BotState.OPENING_TAKER, BotState.CLOSING_TAKER]:
            return

        try:
            order_info = await self.trade_executor.get_extended_order_info(self._last_maker_order_id)
            if not order_info:
                return
            status = str(order_info.get("status", "")).upper()
            raw_filled = order_info.get("filled_size", "0")
            filled_qty = Decimal(str(raw_filled)) if raw_filled is not None else Decimal("0")
            if status not in ["FILLED", "PARTIALLY_FILLED"] or filled_qty <= 0:
                return

            # 额外保险：仅在仓位不平衡时才触发对冲，避免误判
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            imbalance = ext_position + lig_position
            if abs(imbalance) < tolerance:
                return

            avg_price = order_info.get("avg_price") or order_info.get("avg_fill_price") or order_info.get("price")
            avg_price = Decimal(str(avg_price)) if avg_price is not None else Decimal("0")

            order = MakerOrder(
                order_id=self._last_maker_order_id,
                price=avg_price,
                quantity=filled_qty,
                side="sell",
                is_opening=bool(self._last_maker_is_opening),
                filled_quantity=filled_qty,
                avg_fill_price=avg_price,
                context_id=self._last_maker_context_id,
            )
            logger.warning(
                f"兜底成交检测触发补对冲 | state={current_state.value} "
                f"order_id={self._last_maker_order_id} filled={filled_qty}"
            )
            await self._recover_maker_fill_out_of_band(order)
        except Exception as e:
            logger.debug(f"兜底检查最近Maker订单失败: {e}")

    async def _handle_maker_order_partially_filled(self, order: MakerOrder) -> None:
        """
        处理 Maker订单部分成交（异步任务）

        Args:
            order: 部分成交的订单
        """
        try:
            async with self._maker_lock("ws_partial"):
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

                # 确保是当前订单
                if hasattr(self, '_maker_wait_state') and self._maker_wait_state.current_order:
                    if self._maker_wait_state.context_id and order.context_id is None:
                        order.context_id = self._maker_wait_state.context_id
                    if (
                        self._maker_wait_state.current_order.order_id != order.order_id or
                        (
                            self._maker_wait_state.context_id and
                            order.context_id and
                            self._maker_wait_state.context_id != order.context_id
                        )
                    ):
                        logger.info(f"订单部分成交非当前订单，跳过 | order_id={order.order_id}")
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

    async def _handle_maker_order_event(self, event_type: str, order: MakerOrder) -> None:
        if event_type == "filled":
            await self._handle_maker_order_filled(order)
        elif event_type == "partial":
            await self._handle_maker_order_partially_filled(order)
        elif event_type == "canceled":
            await self._handle_maker_order_canceled(order)
        else:
            logger.warning(f"未知Maker事件类型: {event_type}")

    async def _maker_event_loop(self) -> None:
        """串行处理Maker订单事件，避免与主循环/重挂并发"""
        try:
            while not self._stop_event.is_set():
                order_id = await self._maker_event_queue.get()
                if order_id is None:
                    break
                if order_id in self._maker_event_enqueued:
                    self._maker_event_enqueued.remove(order_id)
                event = self._maker_event_latest.pop(order_id, None)
                if not event:
                    continue
                event_type, order = event
                await self._handle_maker_order_event(event_type, order)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Maker事件处理异常: {e}", exc_info=True)

    # ========================================================================
    # 私有方法：辅助
    # ========================================================================

    def _print_stats(self) -> None:
        """打印统计信息（精简单行格式）"""
        stats = self.get_stats()

        stats_str = self._format_stats_line()

        if stats.start_time:
            uptime = datetime.now() - stats.start_time
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            stats_str += f" | 运行{hours}:{minutes:02d}:{seconds:02d}"

        logger.info(stats_str)
        if self._maker_lock_acquire_count > 0:
            avg_wait = self._maker_lock_wait_total / self._maker_lock_acquire_count
            logger.info(
                f"Maker锁统计: count={self._maker_lock_acquire_count} "
                f"avg_wait={avg_wait:.4f}s max_wait={self._maker_lock_wait_max:.4f}s"
            )

    def _format_stats_line(self) -> str:
        """返回统计信息单行（用于日志/推送）"""
        stats = self.get_stats()
        return (
            f"交易{stats.total_trades}次 | "
            f"胜率{stats.win_rate:.1%} | "
            f"净利润${stats.net_profit:.2f}"
        )

    @asynccontextmanager
    async def _maker_lock(self, label: str):
        start = time.time()
        await self._maker_state_lock.acquire()
        wait = time.time() - start
        self._maker_lock_acquire_count += 1
        self._maker_lock_wait_total += wait
        if wait > self._maker_lock_wait_max:
            self._maker_lock_wait_max = wait
        if wait > 0.05:
            logger.warning(f"Maker锁等待较长 | {label} | wait={wait:.3f}s")
        try:
            yield
        finally:
            self._maker_state_lock.release()

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

        # 初始化实时价差CSV文件（若表头不一致则新建文件）
        spread_header = [
            'timestamp', 'state', 'ext_bid', 'ext_ask',
            'lig_bid', 'lig_ask', 'spread_abs', 'spread_pct',
            'position_spread', 'portfolio_qty', 'total_entry_spread'
        ]
        if self._spread_csv_path.exists():
            try:
                with open(self._spread_csv_path, 'r', newline='') as f:
                    reader = csv.reader(f)
                    first_row = next(reader, [])
                if first_row and first_row != spread_header:
                    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
                    self._spread_csv_path = self._csv_log_dir / f"spread_data_{date_str}_{suffix}.csv"
            except Exception as e:
                logger.warning(f"读取价差CSV表头失败，重建新文件: {e}")
                suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._spread_csv_path = self._csv_log_dir / f"spread_data_{date_str}_{suffix}.csv"

        if not self._spread_csv_path.exists():
            with open(self._spread_csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(spread_header)

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

    def _build_close_spread_info(self, spread_info: RealTimeSpreadInfo) -> Optional[RealTimeSpreadInfo]:
        """构造平仓口径价差（Ext卖出 + Lighter买入）"""
        if not spread_info:
            return None
        ext_bid = spread_info.ext_bid
        ext_ask = spread_info.ext_ask
        lig_bid = spread_info.lig_bid
        lig_ask = spread_info.lig_ask
        spread_abs = lig_ask - ext_bid
        spread_pct = spread_abs / ext_bid if ext_bid > 0 else Decimal("0")
        return RealTimeSpreadInfo(
            ext_bid=ext_bid,
            ext_ask=ext_ask,
            lig_bid=lig_bid,
            lig_ask=lig_ask,
            spread_abs=spread_abs,
            spread_pct=spread_pct,
            timestamp=spread_info.timestamp,
        )

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
                str(portfolio.get_weighted_avg_spread() if portfolio else 0),
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
            if not await self._safe_exit_maker_wait(BotState.IDLE, "Maker等待状态异常", is_opening=True):
                await self.state_manager.save_state()
            return

        # 获取当前订单ID
        order_id = self._maker_wait_state.current_order.order_id

        try:
            # ========== 监控日志：实时价差和订单簿BBO ==========
            spread_info = self.spread_monitor.get_current_spread()
            if spread_info and spread_info.is_valid():
                self._update_bollinger(spread_info.spread_pct)
                # 获取Extended订单簿BBO价格
                ext_bid, ext_ask = await self.extended_client.fetch_bbo_prices(
                    self.extended_client.config.contract_id
                )

                # 获取当前仓位价差（使用close_strategy的portfolio获取加权平均）
                position_spread = self.close_strategy.get_weighted_avg_spread()

                # 计算平仓阈值（平仓价差口径）
                open_taker = self.close_strategy.portfolio.has_open_taker()
                open_mode_label = "有市价开仓" if open_taker else "全挂单开仓"
                if position_spread > 0:
                    position_spread_str = f"{position_spread:.3%}"
                    close_spread_info = self._build_close_spread_info(spread_info)
                    if close_spread_info:
                        profit_spread = position_spread - close_spread_info.spread_pct
                        profit_str = f"利润{profit_spread:.3%}"
                    else:
                        profit_str = "利润无"
                    bands = self._get_bollinger_bands()
                    portfolio = self.close_strategy.get_portfolio()
                    taker_qty = sum(p.quantity for p in portfolio.get_active_positions() if getattr(p, "open_is_taker", False)) if portfolio else Decimal("0")
                    total_qty = portfolio.total_quantity if portfolio else Decimal("0")
                    taker_ratio = (taker_qty / total_qty) if total_qty > 0 else Decimal("0")
                    fee = Decimal("0.00025")
                    limit_cost = taker_ratio * fee
                    market_cost = (Decimal("1") + taker_ratio) * fee
                    if bands:
                        midline, _upper, _lower, _std = bands
                        close_threshold_str = (
                            f"{profit_str} | 平仓价差≤开仓均价差-A{self.config.limit_close_spread_a:.3%}-cost{limit_cost:.3%} "
                            f"| 市价平仓≤min(中轴{midline:.3%}, 开仓均价差-B{self.config.market_close_spread_b:.3%}-cost{market_cost:.3%})"
                        )
                    else:
                        close_threshold_str = f"{profit_str} | 布林带样本不足"
                else:
                    position_spread_str = "无"
                    close_threshold_str = "无仓位"

                # 输出监控日志（每秒一次）
                print(
                    f"📊 开仓挂单 s={spread_info.spread_pct:.3%} "
                    f"bid={ext_bid:.2f} mode={open_mode_label} "
                    f"entry={position_spread_str} {close_threshold_str}"
                )

            # ========== 订单成交/取消由 WebSocket 处理，主循环不再检测 ==========
            # WebSocket 回调会处理：
            # - FILLED: 完全成交 -> LIGHTER_HEDGING
            # - PARTIALLY_FILLED: 部分成交 -> LIGHTER_HEDGING
            # - CANCELED: 订单取消 -> IDLE

            # ========== 主循环只处理：价差保护 + 平仓检查 + 价格偏离 ==========

            if await self._apply_spread_rules(
                BotState.OPENING_MAKER_WAIT,
                spread_info,
                rule_ids=["protect", "close_preempt", "open_escalate"],
            ):
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
            if not await self._safe_exit_maker_wait(BotState.IDLE, f"异常: {e}", is_opening=True):
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
        time_module = __import__('time')

        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            logger.warning("Maker等待状态未初始化，返回HOLDING")
            if not await self._safe_exit_maker_wait(BotState.HOLDING, "Maker等待状态异常", is_opening=False):
                await self.state_manager.save_state()
            return

        try:
            # ========== 订单成交/取消由 WebSocket 处理，主循环不再检测 ==========
            # WebSocket 回调会处理：
            # - FILLED: 完全成交 -> LIGHTER_HEDGING
            # - PARTIALLY_FILLED: 部分成交 -> LIGHTER_HEDGING
            # - CANCELED: 订单取消 -> HOLDING

            # ========== 主循环只处理：价差检查 + 价格偏离 ==========

            spread_info = self.spread_monitor.get_current_spread()
            if await self._apply_spread_rules(
                BotState.CLOSING_MAKER_WAIT,
                spread_info,
                rule_ids=["close_cancel", "close_escalate"],
            ):
                return

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
                current_time = time_module.time()
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
            if not await self._safe_exit_maker_wait(BotState.HOLDING, f"异常: {e}", is_opening=False):
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

            # 额外保护：根据实盘仓位限制对冲数量，避免Ext未成交/延迟导致Lig单边
            try:
                ext_position = lig_position = None
                for attempt in range(2):
                    ext_position = await self.extended_client.get_account_positions()
                    lig_position = await self.lighter_client.get_account_positions()
                    if abs(ext_position) > Decimal("0") or abs(lig_position) > Decimal("0"):
                        break
                    await asyncio.sleep(0.2)
                tolerance = Decimal("0.001")
                max_ext = abs(ext_position) if ext_position is not None else Decimal("0")
                max_lig = abs(lig_position) if lig_position is not None else Decimal("0")
                if is_opening:
                    # 开仓对冲：仅以Ext实际仓位为上限（Lig尚未对冲时为0）
                    capped_qty = min(ext_filled_qty, max_ext)
                else:
                    # 平仓：以lig现有仓位为上限，避免过度对冲
                    capped_qty = min(ext_filled_qty, max_lig)
                if capped_qty < tolerance:
                    logger.warning(
                        f"对冲跳过 | ext_pos={ext_position} lig_pos={lig_position} ext_filled={ext_filled_qty}"
                    )
                    self._notify_fill_verify_failed(
                        is_opening=is_opening,
                        expected_qty=ext_filled_qty,
                        source="lighter_hedge_guard"
                    )
                    self._hedging_state.ext_filled_quantity = Decimal('0')
                    self.state_manager.set_state(
                        BotState.OPENING_WAIT if is_opening else BotState.CLOSING_WAIT,
                        "对冲数量不足，进入仓位确认"
                    )
                    await self.state_manager.save_state()
                    return
                if capped_qty != ext_filled_qty:
                    logger.info(
                        f"对冲数量调整 | ext_filled={ext_filled_qty} -> capped={capped_qty} "
                        f"(ext_pos={ext_position}, lig_pos={lig_position})"
                    )
                    ext_filled_qty = capped_qty
                    self._hedging_state.ext_filled_quantity = capped_qty
            except Exception as e:
                logger.debug(f"对冲仓位校验失败，继续原数量: {e}")

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
            # 使用订单簿计算VWAP作为对冲价格（A方案）
            lig_vwap = None
            try:
                lig_vwap = await self.order_book_manager.calculate_vwap(
                    "lighter",
                    ext_filled_qty,
                    "buy" if hedge_side == "buy" else "sell"
                )
                if lig_vwap and lig_vwap > 0:
                    slip = self.config.lighter_hedge_slippage_bps
                    if hedge_side == "buy":
                        lig_vwap = lig_vwap * (Decimal("1") + slip)
                    else:
                        lig_vwap = lig_vwap * (Decimal("1") - slip)
                    logger.info(f"Lighter对冲VWAP(含滑点): {lig_vwap} | slip={slip}")
                else:
                    logger.info("Lighter对冲VWAP为空或无效，准备使用BBO")
            except Exception as e:
                logger.warning(f"计算Lighter VWAP失败，使用BBO: {e}")

            if not lig_vwap or lig_vwap <= 0:
                try:
                    lig_bid, lig_ask = await self.lighter_client.fetch_bbo_prices(
                        self.lighter_client.config.contract_id
                    )
                    slip = self.config.lighter_hedge_slippage_bps
                    if hedge_side == "buy":
                        lig_vwap = lig_ask * (Decimal("1") + slip)
                    else:
                        lig_vwap = lig_bid * (Decimal("1") - slip)
                    logger.info(f"Lighter对冲BBO(含滑点): {lig_vwap} | slip={slip}")
                except Exception as e:
                    logger.warning(f"获取Lighter BBO失败，使用默认价格: {e}")
                    lig_vwap = None

            result = await self.trade_executor.execute_lighter_hedge(
                quantity=ext_filled_qty,
                side=hedge_side,
                ext_filled_price=ext_filled_price,
                price_override=lig_vwap,
                reduce_only=not is_opening,
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
                                open_is_taker=False,
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
                                open_is_taker=False,
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

    def _get_spread_rule_table(self) -> Dict[BotState, list]:
        if not hasattr(self, "_spread_rule_table"):
            self._spread_rule_table = {
                BotState.IDLE: [("open", self._handle_idle_spread_transition)],
                BotState.HOLDING: [
                    ("open", self._handle_holding_open_transition),
                    ("close", self._handle_holding_close_transition),
                ],
                BotState.CLOSING: [("mode", self._handle_closing_spread_transition)],
                BotState.OPENING_MAKER_WAIT: [
                    ("protect", self._handle_opening_maker_wait_spread_protect),
                    ("close_preempt", self._handle_opening_maker_wait_spread_close_preempt),
                    ("open_escalate", self._handle_opening_maker_wait_spread_escalate),
                ],
                BotState.CLOSING_MAKER_WAIT: [
                    ("close_cancel", self._handle_closing_maker_wait_spread_transition),
                    ("close_escalate", self._handle_closing_maker_wait_spread_escalate),
                ],
            }
        return self._spread_rule_table

    async def _apply_spread_rules(self, state: BotState, spread_info, rule_ids: Optional[list] = None, **context) -> bool:
        """根据状态执行价差规则表，返回是否已处理并触发状态转换"""
        handlers = self._get_spread_rule_table().get(state, [])
        for rule_id, handler in handlers:
            if rule_ids is not None and rule_id not in rule_ids:
                continue
            result = await handler(spread_info, **context)
            if result:
                return True
        return False

    def _log_spread_rule(self, level: str, state: BotState, action: str, message: str, also_print: bool = False) -> None:
        prefix = f"[SPREAD][{state.value}][{action}] "
        log_func = getattr(logger, level, logger.info)
        log_func(prefix + message)
        if also_print:
            print(prefix + message)

    def _update_bollinger(self, spread_pct: Decimal) -> None:
        now = time.time()
        if now - self._boll_last_sample_time < self.config.boll_sample_interval:
            return
        self._boll_last_sample_time = now
        self._boll_samples.append((now, spread_pct))
        window_seconds = self.config.boll_window_minutes * 60
        while self._boll_samples and now - self._boll_samples[0][0] > window_seconds:
            self._boll_samples.popleft()

        if len(self._boll_samples) < self.config.boll_min_samples:
            self._boll_last_bands = None
            return

        values = [s for _, s in self._boll_samples]
        mean = sum(values) / Decimal(len(values))
        mean_f = float(mean)
        var = sum((float(v) - mean_f) ** 2 for v in values) / max(len(values), 1)
        std = Decimal(str(math.sqrt(var)))
        upper = mean + (self.config.boll_k * std)
        lower = mean - (self.config.boll_k * std)
        self._boll_last_bands = (mean, upper, lower, std)

        # 低频日志，避免刷屏
        if now - self._last_boll_log_time >= 30.0:
            logger.info(
                f"[BOLL] mid={mean:.3%} upper={upper:.3%} lower={lower:.3%} "
                f"std={std:.4%} n={len(self._boll_samples)}"
            )
            self._last_boll_log_time = now

    def _get_bollinger_bands(self) -> Optional[tuple]:
        return self._boll_last_bands

    async def _get_inventory_ratio(self) -> Decimal:
        """库存倾斜比例：已用资金 / 总资金（0~1）"""
        try:
            snapshot = await self.position_balance_monitor.get_position_balance()
            if not snapshot or not snapshot.extended or not snapshot.lighter:
                return Decimal("0")
            used = snapshot.extended.margin_used + snapshot.lighter.margin_used
            total = snapshot.extended.total_balance + snapshot.lighter.total_balance
            if total <= 0:
                return Decimal("0")
            ratio = used / total
            if ratio < 0:
                return Decimal("0")
            return ratio if ratio <= 1 else Decimal("1")
        except Exception:
            return Decimal("0")

    async def _get_open_sigma_thresholds(self) -> Optional[tuple]:
        """
        返回 (midline, maker_threshold, taker_threshold, std)
        """
        bands = self._get_bollinger_bands()
        if not bands:
            return None
        mean, _upper, _lower, std = bands
        ratio = await self._get_inventory_ratio()
        penalty = ratio * self.config.open_sigma_penalty
        maker_sigma = self.config.open_maker_sigma + penalty
        taker_sigma = self.config.open_taker_sigma + penalty
        maker_threshold = mean + (maker_sigma * std)
        taker_threshold = mean + (taker_sigma * std)
        return mean, maker_threshold, taker_threshold, std

    async def _check_bandwidth_gate(self) -> bool:
        """
        布林带带宽过滤：带宽过窄则暂停开仓
        """
        bands = self._get_bollinger_bands()
        if not bands:
            return True
        mid, upper, lower, _ = bands
        if mid <= 0:
            return True
        bandwidth = (upper - lower) / mid
        if bandwidth < self.config.boll_bandwidth_min:
            if not self._bandwidth_blocked:
                self._bandwidth_blocked = True
                self._notify_bandwidth_blocked(bandwidth)
            return False
        if self._bandwidth_blocked:
            self._bandwidth_blocked = False
            self._notify_bandwidth_recovered(bandwidth)
        return True

    async def _should_open_bollinger(self, spread_info) -> tuple[bool, str, bool]:
        if not self.config.use_bollinger:
            should_open, reason = self.open_strategy.should_open(spread_info)
            return should_open, reason, not self.config.use_maker_mode
        thresholds = await self._get_open_sigma_thresholds()
        if not thresholds:
            return False, "布林带样本不足", False
        mean, maker_threshold, taker_threshold, _std = thresholds
        bands = self._get_bollinger_bands()
        if bands:
            mid, upper, lower, _ = bands
            if mid > 0:
                bandwidth = (upper - lower) / mid
                if bandwidth < self.config.boll_bandwidth_min:
                    return False, f"布林带宽度{bandwidth:.3%} < {self.config.boll_bandwidth_min:.3%}，不开仓", False
        current_spread = spread_info.spread_pct
        if current_spread >= taker_threshold:
            # 市价开仓不需要确认窗
            self._open_maker_confirm_start = None
            reason = (
                f"开仓: 价差{current_spread:.3%} >= 市价阈值{taker_threshold:.3%}"
                f"（中轴{mean:.3%}, {self.config.open_taker_sigma}σ）"
            )
            self._notify_open_trigger(spread_info, mean, taker_threshold, reason)
            return True, reason, True
        if current_spread >= maker_threshold:
            confirm_secs = self.config.open_maker_confirm_seconds
            now = time.time()
            if confirm_secs > 0:
                if self._open_maker_confirm_start is None:
                    self._open_maker_confirm_start = now
                    return False, f"挂单确认中({confirm_secs:.1f}s)", False
                if now - self._open_maker_confirm_start < confirm_secs:
                    return False, f"挂单确认中({confirm_secs:.1f}s)", False
            self._open_maker_confirm_start = None
            reason = (
                f"开仓: 价差{current_spread:.3%} >= 挂单阈值{maker_threshold:.3%}"
                f"（中轴{mean:.3%}, {self.config.open_maker_sigma}σ）"
            )
            self._notify_open_trigger(spread_info, mean, maker_threshold, reason)
            return True, reason, False
        # 未达挂单阈值，重置确认窗口
        self._open_maker_confirm_start = None
        reason = (
            f"价差{current_spread:.3%}未达挂单阈值{maker_threshold:.3%}"
            f"（中轴{mean:.3%}）"
        )
        return False, reason, False

    async def _try_switch_on_insufficient(self, spread_info, balance_reason: str) -> bool:
        """
        资金不足时的腾笼换鸟逻辑：
        1) 持仓时间 >= switch_min_hold_minutes
        2) 当前实时价差 > 持仓价差 + switch_cost_bps
        触发后直接市价平仓释放资金
        """
        portfolio = self.close_strategy.get_portfolio()
        if not portfolio or portfolio.total_quantity <= 0:
            return False
        if not portfolio.first_open_time:
            return False

        hold_minutes = (time.time() - portfolio.first_open_time) / 60.0
        if hold_minutes < self.config.switch_min_hold_minutes:
            return False

        entry_spread = portfolio.get_total_entry_spread()
        if entry_spread <= 0:
            return False

        switch_threshold = entry_spread + self.config.switch_cost_bps
        if spread_info.spread_pct <= switch_threshold:
            return False

        close_spread_info = self._build_close_spread_info(spread_info)
        if close_spread_info:
            decision = {
                "use_market": True,
                "close_spread": close_spread_info.spread_pct,
                "profit_spread": entry_spread - close_spread_info.spread_pct,
            }
            self._set_close_context(decision, close_spread_info)

        self._log_spread_rule(
            "warning",
            BotState.HOLDING,
            "switch_close",
            f"腾笼换鸟触发 | 余额不足 | 持仓{hold_minutes:.1f}m | "
            f"当前价差{spread_info.spread_pct:.3%} > "
            f"持仓价差{entry_spread:.3%}+成本{self.config.switch_cost_bps:.3%}",
            also_print=True,
        )
        self._notify(
            "🔄 腾笼换鸟触发",
            [
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"交易对: {self.config.symbol}",
                f"持仓时长: {hold_minutes:.1f}m",
                f"当前价差: {spread_info.spread_pct:.3%}",
                f"持仓价差: {entry_spread:.3%}",
                f"换仓成本: {self.config.switch_cost_bps:.3%}",
                f"原因: 余额不足 | {balance_reason}",
            ],
        )
        self.state_manager.set_state(BotState.CLOSING_TAKER, f"腾笼换鸟: {balance_reason}")
        await self.state_manager.save_state()
        return True

    async def _evaluate_close_decision(self, spread_info, close_spread_info) -> Dict[str, object]:
        decision = {
            "should_close": False,
            "use_market": False,
            "profit_spread": Decimal("0"),
            "total_spread": Decimal("0"),
            "close_spread": Decimal("0"),
            "open_spread": Decimal("0"),
            "midline": Decimal("0"),
            "lower": Decimal("0"),
            "market_threshold": Decimal("0"),
            "limit_threshold": Decimal("0"),
            "limit_exit_threshold": Decimal("0"),
            "limit_cost": Decimal("0"),
            "market_cost": Decimal("0"),
            "taker_ratio": Decimal("0"),
            "close_reason": "",
        }
        if not spread_info or not close_spread_info:
            return decision
        bands = self._get_bollinger_bands()
        if not bands:
            return decision
        mean, _upper, lower, std = bands
        portfolio = self.close_strategy.get_portfolio()
        total_spread = await self.close_strategy.get_total_position_spread()
        if total_spread <= 0 or not portfolio:
            return decision
        profit_spread = total_spread - close_spread_info.spread_pct
        active_positions = portfolio.get_active_positions()
        taker_qty = sum(p.quantity for p in active_positions if getattr(p, "open_is_taker", False))
        total_qty = portfolio.total_quantity
        taker_ratio = (taker_qty / total_qty) if total_qty > 0 else Decimal("0")
        inventory_ratio = await self._get_inventory_ratio()
        fee = Decimal("0.00025")
        limit_cost = taker_ratio * fee
        market_cost = (Decimal("1") + taker_ratio) * fee
        base_limit_threshold = (
            total_spread
            - self.config.limit_close_spread_a
            - limit_cost
            + (inventory_ratio * self.config.limit_close_spread_a)
        )
        hysteresis = std * self.config.close_limit_hysteresis_sigma
        limit_threshold = base_limit_threshold - hysteresis
        limit_exit_threshold = base_limit_threshold
        market_raw = (
            total_spread
            - self.config.market_close_spread_b
            - market_cost
            + (inventory_ratio * self.config.market_close_spread_b)
        )
        market_threshold = min(mean, market_raw)
        decision.update(
            {
                "total_spread": total_spread,
                "profit_spread": profit_spread,
                "close_spread": close_spread_info.spread_pct,
                "open_spread": spread_info.spread_pct,
                "midline": mean,
                "lower": lower,
                "limit_threshold": limit_threshold,
                "limit_exit_threshold": limit_exit_threshold,
                "market_threshold": market_threshold,
                "limit_cost": limit_cost,
                "market_cost": market_cost,
                "taker_ratio": taker_ratio,
            }
        )
        if close_spread_info.spread_pct <= market_threshold:
            decision["should_close"] = True
            decision["use_market"] = True
            decision["close_reason"] = "market_profit"
            return decision
        if close_spread_info.spread_pct <= limit_threshold:
            decision["should_close"] = True
            decision["use_market"] = False
            decision["close_reason"] = "limit_min"
            return decision
        return decision

    def _notify(self, title: str, lines: List[str]) -> None:
        if self._notifier:
            self._notifier.enqueue(title, lines)

    def _set_close_context(self, decision: Dict[str, object], close_spread_info: Optional[RealTimeSpreadInfo]) -> None:
        if not close_spread_info:
            return
        use_market = bool(decision.get("use_market", False))
        self._last_close_context = {
            "mode": "市价" if use_market else "挂单",
            "close_spread": decision.get("close_spread", Decimal("0")),
            "profit_spread": decision.get("profit_spread", Decimal("0")),
            "ext_bid": close_spread_info.ext_bid,
            "lig_ask": close_spread_info.lig_ask,
            "entry_spread": self.close_strategy.get_weighted_avg_spread(),
        }

    def _notify_open_success(self, ext_pos: Decimal, lig_pos: Decimal, ext_avg=None, lig_avg=None) -> None:
        if not hasattr(self, "_pending_open_position") or not self._pending_open_position:
            return
        pos = self._pending_open_position
        ext_price = Decimal(str(ext_avg)) if ext_avg else pos.ext_price
        lig_price = Decimal(str(lig_avg)) if lig_avg else pos.lig_price
        if ext_price > 0:
            real_open_spread = (lig_price - ext_price) / ext_price
        else:
            real_open_spread = pos.open_spread

        current_qty = self.close_strategy.get_total_quantity()
        current_avg = self.close_strategy.get_weighted_avg_spread()
        total_qty = current_qty + pos.quantity
        if total_qty > 0:
            avg_entry_spread = (current_avg * current_qty + real_open_spread * pos.quantity) / total_qty
        else:
            avg_entry_spread = real_open_spread
        mode = "市价" if pos.open_is_taker else "挂单"
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            "方向: Ext买 / Lig卖",
            f"开仓价差率: {real_open_spread:.3%}",
            f"当前仓位平均开仓价差: {avg_entry_spread:.3%}",
            f"Ext开仓均价: {ext_price:.2f}",
            f"Lig开仓均价: {lig_price:.2f}",
            f"Ext仓位: {ext_pos}",
            f"Lig仓位: {lig_pos}",
        ]
        self._notify(f"✅ 开仓成功（{mode}）", lines)

    def _notify_open_failure(self, reason: str, ext_pos: Optional[Decimal] = None, lig_pos: Optional[Decimal] = None) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"原因: {reason}",
        ]
        if ext_pos is not None and lig_pos is not None:
            lines.append(f"仓位: Ext={ext_pos} Lig={lig_pos}")
        self._notify("❌ 开仓失败", lines)

    def _notify_open_escalate(self, spread: Decimal, threshold: Decimal) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"触发价差: {spread:.3%}",
            f"市价阈值: {threshold:.3%}",
            "动作: 撤单并切换市价开仓",
        ]
        self._notify("⚠️ 开仓挂单升级市价", lines)

    def _notify_fill_verify_failed(self, is_opening: bool, expected_qty: Decimal, source: str) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"阶段: {'开仓' if is_opening else '平仓'}",
            f"来源: {source}",
            f"预期成交量: {expected_qty}",
            "说明: Ext成交校验未通过，已阻止对冲",
        ]
        self._notify("⚠️ 成交校验失败", lines)

    def _notify_paused(self, reason: str) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"原因: {reason}",
        ]
        self._notify("🛡️ 进入风控暂停", lines)

    def _notify_open_trigger(self, spread_info, midline: Decimal, upper: Decimal, reason: str) -> None:
        if not self.config.notify_open_trigger:
            return
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"实时价差: {spread_info.spread_pct:.3%}",
            f"中轴: {midline:.3%}",
            f"阈值: {upper:.3%}",
            f"原因: {reason}",
        ]
        self._notify("📈 开仓触发信号", lines)

    async def _notify_close_success(self, profit: Decimal) -> None:
        ctx = self._last_close_context or {}
        mode = ctx.get("mode", "未知")
        close_spread = ctx.get("close_spread", Decimal("0"))
        ext_bid = ctx.get("ext_bid", Decimal("0"))
        lig_ask = ctx.get("lig_ask", Decimal("0"))
        entry_spread = ctx.get("entry_spread", self.close_strategy.get_weighted_avg_spread())

        ideal_rate = entry_spread - close_spread
        fee_rate = Decimal("0.000225")
        actual_rate = ideal_rate
        if self.close_strategy.portfolio.has_open_taker():
            actual_rate -= fee_rate
        if mode == "市价":
            actual_rate -= fee_rate

        total_funds_after = Decimal("0")
        ext_funds_after = Decimal("0")
        lig_funds_after = Decimal("0")
        try:
            snapshot = await self.position_balance_monitor.get_position_balance()
            if snapshot and snapshot.extended and snapshot.lighter:
                ext_funds_after = snapshot.extended.total_balance
                lig_funds_after = snapshot.lighter.total_balance
                total_funds_after = ext_funds_after + lig_funds_after
        except Exception:
            pass

        total_funds_before = ctx.get("funds_before", Decimal("0"))
        ext_funds_before = ctx.get("ext_funds_before", Decimal("0"))
        lig_funds_before = ctx.get("lig_funds_before", Decimal("0"))
        funds_delta = total_funds_after - total_funds_before if total_funds_before else profit
        ext_delta = ext_funds_after - ext_funds_before if ext_funds_before else Decimal("0")
        lig_delta = lig_funds_after - lig_funds_before if lig_funds_before else Decimal("0")

        if total_funds_before:
            self._last_trade_funds_delta = funds_delta
            self._cum_trade_funds_delta += funds_delta

        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"方式: {mode}",
            "方向: Ext卖 / Lig买",
            f"平仓价差率: {close_spread:.3%}",
            f"平均开仓价差: {entry_spread:.3%}",
            f"理想收益率: {ideal_rate:.3%}",
            f"实际收益率: {actual_rate:.3%}",
            f"Ext平仓价: {ext_bid:.2f}",
            f"Lig平仓价: {lig_ask:.2f}",
            f"两边总资金(平仓后): {total_funds_after:.2f}",
            f"Ext实际收益: {ext_delta:.2f}",
            f"Lig实际收益: {lig_delta:.2f}",
            f"收益(资金变化): {funds_delta:.2f}",
        ]
        self._notify("✅ 平仓成功", lines)


    def _notify_close_failure(self, reason: str) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"原因: {reason}",
        ]
        self._notify("❌ 平仓失败", lines)

    def _notify_close_escalate(self, spread: Decimal, threshold: Decimal) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"平仓价差: {spread:.3%}",
            f"市价阈值: {threshold:.3%}",
            "动作: 撤单并切换市价平仓",
        ]
        self._notify("⚠️ 平仓挂单升级市价", lines)

    def _notify_bandwidth_blocked(self, bandwidth: Decimal) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"带宽: {bandwidth:.3%}",
            f"阈值: {self.config.boll_bandwidth_min:.3%}",
            "动作: 停止开仓，仅允许平仓",
        ]
        self._notify("🛑 窄幅震荡，停止开仓", lines)

    def _notify_bandwidth_recovered(self, bandwidth: Decimal) -> None:
        lines = [
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"交易对: {self.config.symbol}",
            f"带宽: {bandwidth:.3%}",
            f"阈值: {self.config.boll_bandwidth_min:.3%}",
            "动作: 恢复开仓",
        ]
        self._notify("✅ 带宽恢复，允许开仓", lines)

    def _get_open_order_notional(self, spread_info) -> Decimal:
        """获取开仓名义金额（USDT）"""
        return self.config.target_quantity * spread_info.ext_ask

    def _record_run_volume(self, ext_notional: Decimal, lig_notional: Decimal) -> None:
        if ext_notional is None or lig_notional is None:
            return
        if ext_notional <= 0 and lig_notional <= 0:
            return
        self._run_ext_volume += max(Decimal("0"), ext_notional)
        self._run_lig_volume += max(Decimal("0"), lig_notional)
        self._run_total_volume = self._run_ext_volume + self._run_lig_volume

    async def _capture_close_funds_before(self) -> None:
        if not self._last_close_context:
            self._last_close_context = {}
        if self._last_close_context.get("funds_before"):
            return
        try:
            snapshot = await self.position_balance_monitor.get_position_balance()
            if snapshot and snapshot.extended and snapshot.lighter:
                ext_before = snapshot.extended.total_balance
                lig_before = snapshot.lighter.total_balance
                total_funds = ext_before + lig_before
                self._last_close_context["funds_before"] = total_funds
                self._last_close_context["ext_funds_before"] = ext_before
                self._last_close_context["lig_funds_before"] = lig_before
        except Exception:
            pass

    async def _maybe_send_dashboard_snapshot(self, spread_info) -> None:
        """按采样频率写入Dashboard数据（非阻塞）"""
        if not self._dashboard_ingestor or not self._dashboard_ingestor.enabled:
            return
        if not spread_info or not spread_info.is_valid():
            return
        now = time.time()
        if now - self._last_dashboard_sample_time < self.config.dashboard_sample_interval:
            return
        self._last_dashboard_sample_time = now

        bands = self._get_bollinger_bands()
        if bands:
            midline, upper, lower, _std = bands
        else:
            midline = upper = lower = Decimal("0")

        open_thresholds = await self._get_open_sigma_thresholds()
        if open_thresholds:
            _mid, maker_th, taker_th, std = open_thresholds
            open_maker_exit = maker_th - (self.config.open_maker_hysteresis_sigma * std)
        else:
            maker_th = taker_th = open_maker_exit = Decimal("0")

        close_spread_info = self._build_close_spread_info(spread_info)
        close_spread = close_spread_info.spread_pct if close_spread_info else Decimal("0")
        market_threshold = Decimal("0")
        limit_threshold = Decimal("0")
        limit_exit_threshold = Decimal("0")
        try:
            decision = await self._evaluate_close_decision(spread_info, close_spread_info)
            market_threshold = decision.get("market_threshold", Decimal("0")) or Decimal("0")
            limit_threshold = decision.get("limit_threshold", Decimal("0")) or Decimal("0")
            limit_exit_threshold = decision.get("limit_exit_threshold", Decimal("0")) or Decimal("0")
        except Exception:
            market_threshold = Decimal("0")
            limit_threshold = Decimal("0")
            limit_exit_threshold = Decimal("0")

        ext_qty = lig_qty = ext_avail = lig_avail = Decimal("0")
        ext_total = lig_total = Decimal("0")
        include_position = now - self._last_dashboard_position_time >= self.config.dashboard_position_interval
        try:
            if include_position:
                snapshot = await self.position_balance_monitor.get_position_balance()
                if snapshot.extended:
                    ext_qty = snapshot.extended.current_position
                    ext_avail = snapshot.extended.available_balance
                    ext_total = snapshot.extended.total_balance
                if snapshot.lighter:
                    lig_qty = snapshot.lighter.current_position
                    lig_avail = snapshot.lighter.available_balance
                    lig_total = snapshot.lighter.total_balance
        except Exception as e:
            logger.debug(f"Dashboard仓位快照获取失败: {e}")

        payload = {
            "symbol": self.config.symbol,
            "spread": {
                "open": float(spread_info.spread_pct),
                "close": float(close_spread),
                "mid": float(midline),
                "upper": float(upper),
                "lower": float(lower),
                "openMaker": float(maker_th),
                "openTaker": float(taker_th),
                "openMakerExit": float(open_maker_exit),
                "closeMarket": float(market_threshold),
                "closeLimit": float(limit_threshold),
                "closeLimitExit": float(limit_exit_threshold),
                "extBid": float(spread_info.ext_bid),
                "extAsk": float(spread_info.ext_ask),
                "ligBid": float(spread_info.lig_bid),
                "ligAsk": float(spread_info.lig_ask),
            },
        }
        if include_position:
            payload["position"] = {
                "extQty": float(ext_qty),
                "ligQty": float(lig_qty),
                "extAvailUsd": float(ext_avail),
                "ligAvailUsd": float(lig_avail),
                "extTotalUsd": float(ext_total),
                "ligTotalUsd": float(lig_total),
                "extVolume": float(self._run_ext_volume),
                "ligVolume": float(self._run_lig_volume),
                "totalVolume": float(self._run_total_volume),
                "extOpenTakerVolume": float(self._run_ext_open_taker_volume),
                "extOpenMakerVolume": float(self._run_ext_open_maker_volume),
                "ligOpenTakerVolume": float(self._run_lig_open_taker_volume),
                "ligOpenMakerVolume": float(self._run_lig_open_maker_volume),
            }
            total_funds = ext_total + lig_total
            if total_funds > 0:
                if self._session_start_funds is None:
                    self._session_start_funds = total_funds
            # 记录当前利润（价差口径），并带上累计收益（USDT）
            try:
                entry_spread = self.close_strategy.get_weighted_avg_spread()
                profit_spread = entry_spread - close_spread
                # 实际收益率 = 理想收益率 - 市价手续费（仅Ext市价开/平仓时扣）
                fee_rate = Decimal("0.000225")
                actual_profit = profit_spread
                if hasattr(self.close_strategy, "portfolio") and self.close_strategy.portfolio.has_open_taker():
                    actual_profit -= fee_rate
                if self.state_manager.get_state() == BotState.CLOSING_TAKER:
                    actual_profit -= fee_rate
                stats = self.state_manager.get_stats()
                floating_delta = Decimal("0")
                floating_cum = Decimal("0")
                if self._floating_base_funds is not None and total_funds > 0:
                    floating_delta = total_funds - self._floating_base_funds
                if self._session_start_funds is not None and total_funds > 0:
                    floating_cum = total_funds - self._session_start_funds
                payload["pnl"] = {
                    "entry_spread": float(entry_spread),
                    "close_spread": float(close_spread),
                    "ideal_rate": float(profit_spread),
                    "actual_rate": float(actual_profit),
                    "profit": float(profit_spread),
                    "cumulative": float(stats.total_profit if stats else Decimal("0")),
                    "funds_delta": float(floating_delta),
                    "funds_cumulative": float(floating_cum),
                }
            except Exception as e:
                logger.debug(f"Dashboard利润计算失败: {e}")
            self._last_dashboard_position_time = now
        self._dashboard_ingestor.enqueue(payload)

    async def _enter_idle_or_holding_after_open_failure(self, reason: str) -> None:
        """开仓失败后，根据实际仓位决定进入IDLE或HOLDING"""
        try:
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            has_position = abs(ext_position) >= tolerance or abs(lig_position) >= tolerance

            if has_position:
                state_reason = f"{reason} | 检测到仓位 Ext={ext_position}, Lig={lig_position}"
                self._notify_open_failure(reason, ext_position, lig_position)
                self.state_manager.set_state(BotState.HOLDING, state_reason)
            else:
                self._notify_open_failure(reason, ext_position, lig_position)
                self.state_manager.set_state(BotState.IDLE, reason)
        except Exception as e:
            logger.warning(f"开仓失败后检查仓位异常: {e}")
            self._notify_open_failure(reason)
            self.state_manager.set_state(BotState.IDLE, reason)

        await self.state_manager.save_state()

    async def _handle_idle_spread_transition(self, spread_info, should_open: bool = False, reason: str = "", use_taker: bool = False, **_) -> bool:
        """IDLE状态：处理价差触发的开仓转换"""
        if not should_open:
            return False

        # 风控验证
        self._log_spread_rule("info", BotState.IDLE, "open_check", "开始风控验证", also_print=True)
        validation = await self.risk_manager.validate_open_position(
            self.order_book_manager,
            self.config.target_quantity,
            spread_info
        )

        if not validation.is_valid:
            self._log_spread_rule(
                "warning",
                BotState.IDLE,
                "open_risk_fail",
                f"风控验证失败: {validation.reason}",
                also_print=True,
            )
            return True

        self._log_spread_rule("info", BotState.IDLE, "open_check", "风控通过，开始余额检测", also_print=True)

        # ========== 新增: 固定名义金额仓位检测 ==========
        order_notional = self._get_open_order_notional(spread_info)
        balance_result = await self.funds_checker.check_open_capacity(
            order_notional_usd=order_notional,
            ext_price=spread_info.ext_ask,
            lig_price=spread_info.lig_bid
        )

        if not balance_result.is_sufficient:
            self._log_spread_rule(
                "warning",
                BotState.IDLE,
                "open_capacity_fail",
                f"仓位检测失败: {balance_result.format_log()}",
                also_print=True,
            )
            return True

        self._log_spread_rule("info", BotState.IDLE, "open_ready", "余额通过，切换到OPENING", also_print=True)

        reason_text = reason or f"价差{spread_info.spread_pct:.3%} 触发开仓"
        open_label = "有市价开仓" if use_taker else "全挂单开仓"
        self.state_manager.set_state(
            BotState.OPENING_TAKER if use_taker else BotState.OPENING,
            reason_text + f" | {open_label}",
        )
        await self.state_manager.save_state()
        return True

    async def _handle_holding_open_transition(self, spread_info, should_open: bool = False, reason: str = "", use_taker: bool = False, **_) -> bool:
        """HOLDING状态：处理价差触发的继续开仓转换"""
        if not should_open:
            return False

        # 可以继续开仓！切换到开仓状态
        # 风控验证
        validation = await self.risk_manager.validate_open_position(
            self.order_book_manager,
            self.config.target_quantity,
            spread_info
        )

        if not validation.is_valid:
            self._log_spread_rule(
                "warning",
                BotState.HOLDING,
                "open_risk_fail",
                f"继续开仓风控失败: {validation.reason}",
                also_print=True,
            )
            return True

        # 风控通过，先做仓位检测
        order_notional = self._get_open_order_notional(spread_info)
        balance_result = await self.funds_checker.check_open_capacity(
            order_notional_usd=order_notional,
            ext_price=spread_info.ext_ask,
            lig_price=spread_info.lig_bid
        )

        if not balance_result.is_sufficient:
            now = time.time()
            self._last_open_capacity_reason = balance_result.format_log()
            if await self._try_switch_on_insufficient(spread_info, self._last_open_capacity_reason):
                return True
            if now - self._last_open_capacity_log_time >= 5.0:
                self._log_spread_rule(
                    "warning",
                    BotState.HOLDING,
                    "open_capacity_fail",
                    f"仓位检测失败: {balance_result.format_log()}",
                    also_print=True,
                )
                self._last_open_capacity_log_time = now
            return True

        # 风控通过，等待一段时间确保前一次开仓的订单查询已完成
        # 防止 Extended API 限流（两次开仓太近会导致订单查询冲突）
        current_time = time.time()

        # 检查距离上次开仓的时间
        if hasattr(self, '_last_open_time') and self._last_open_time is not None:
            elapsed_since_last_open = current_time - self._last_open_time
            min_interval = 5.0  # 最小间隔 5 秒

            if elapsed_since_last_open < min_interval:
                wait_time = min_interval - elapsed_since_last_open
                self._log_spread_rule(
                    "info",
                    BotState.HOLDING,
                    "open_delay",
                    f"等待 {wait_time:.1f} 秒后继续开仓（避免 API 限流）",
                )
                await asyncio.sleep(wait_time)

        # 检查是否已有持仓（继续开仓 vs 首次开仓）
        has_existing_position = self.close_strategy.get_total_quantity() > 0

        if has_existing_position:
            # 已有持仓，这是继续开仓（加仓）
            # 切换到 OPENING 状态（输出状态转换日志）
            open_label = "有市价开仓" if use_taker else "全挂单开仓"
            self.state_manager.set_state(
                BotState.OPENING_TAKER if use_taker else BotState.OPENING,
                f"继续开仓（加仓）: {reason} | {open_label}",
            )
            self._last_open_time = current_time  # 记录开仓时间
            await self.state_manager.save_state()
            # 加仓逻辑会在 OPENING 状态中处理
        else:
            # 首次开仓，正常走 OPENING 流程
            open_label = "有市价开仓" if use_taker else "全挂单开仓"
            self.state_manager.set_state(
                BotState.OPENING_TAKER if use_taker else BotState.OPENING,
                f"首次开仓: {reason} | {open_label}",
            )
            self._last_open_time = current_time  # 记录开仓时间
            await self.state_manager.save_state()

        return True

    async def _handle_holding_close_transition(self, spread_info, **_) -> bool:
        """HOLDING状态：处理价差触发的平仓转换"""
        close_spread_info = self._build_close_spread_info(spread_info)
        decision = await self._evaluate_close_decision(spread_info, close_spread_info)

        if not decision["should_close"]:
            return False

        # 根据利润水平选择平仓模式
        total_quantity = self.close_strategy.get_total_quantity()
        self._set_close_context(decision, close_spread_info)
        await self._capture_close_funds_before()

        if decision["use_market"]:
            # 市价平仓：立即执行
            await self._execute_market_close(total_quantity)
            reason_text = "市价平仓触发"
            self._log_spread_rule(
                "info",
                BotState.HOLDING,
                "close_market",
                f"{reason_text} | 开仓{decision['total_spread']:.3%} | "
                f"平仓价差{decision['close_spread']:.3%} <= 市价阈值{decision['market_threshold']:.3%}",
            )
        else:
            # 限价平仓：挂单等待成交
            await self._execute_limit_close(total_quantity)
            self._log_spread_rule(
                "info",
                BotState.HOLDING,
                "close_limit",
                f"开仓{decision['total_spread']:.3%} | "
                f"平仓价差{decision['close_spread']:.3%} <= 限价阈值{decision['limit_threshold']:.3%}",
            )

        await self.state_manager.save_state()
        return True

    async def _handle_closing_spread_transition(self, spread_info, **_) -> bool:
        """CLOSING状态：根据价差决定市价/限价平仓"""
        if not spread_info:
            self._log_spread_rule(
                "warning",
                BotState.CLOSING,
                "close_default",
                "无法获取有效价差信息，使用默认模式（挂单平仓）",
            )
            # 默认使用挂单平仓，直接执行挂单
            await self._execute_maker_close()
            return True

        if spread_info.is_valid():
            self._update_bollinger(spread_info.spread_pct)

        # 使用布林带+利润判断平仓模式
        close_spread_info = self._build_close_spread_info(spread_info)
        decision = await self._evaluate_close_decision(spread_info, close_spread_info)

        if not decision["should_close"]:
            self._log_spread_rule(
                "warning",
                BotState.CLOSING,
                "close_default",
                "进入CLOSING状态但不满足平仓条件，使用默认模式（挂单平仓）",
            )
            # 默认使用挂单平仓，直接执行挂单
            await self._execute_maker_close()
            return True

        # 根据决策执行平仓
        self._set_close_context(decision, close_spread_info)
        await self._capture_close_funds_before()
        close_mode = "市价" if decision["use_market"] else "限价挂单"
        self._log_spread_rule(
            "info",
            BotState.CLOSING,
            "close_mode",
            f"{close_mode} | 持仓价差={decision['total_spread']:.3%} | "
            f"利润={decision['profit_spread']:.3%} | "
            f"{'市价阈值(平仓价差)' if decision['use_market'] else '限价阈值(平仓价差)'}="
            f"{(decision['market_threshold'] if decision['use_market'] else decision['limit_threshold']):.3%}",
        )

        if decision["use_market"]:
            # 市价平仓：切换到 CLOSING_TAKER 状态
            reason_text = "市价平仓触发"
            self.state_manager.set_state(
                BotState.CLOSING_TAKER,
                f"市价平仓 | {reason_text} | 平仓价差≤市价阈值{decision['market_threshold']:.3%}"
            )
            await self.state_manager.save_state()
        else:
            # 限价挂单平仓：直接执行挂单
            await self._execute_maker_close()
        return True

    async def _handle_opening_maker_wait_spread_protect(self, spread_info, **_) -> bool:
        """OPENING_MAKER_WAIT状态：价差保护"""
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            return False
        if self.state_manager.get_state() != BotState.OPENING_MAKER_WAIT:
            return False

        order_id = self._maker_wait_state.current_order.order_id

        # 检查价差保护（布林带上轨）
        if spread_info and spread_info.is_valid():
            thresholds = await self._get_open_sigma_thresholds()
            if not thresholds:
                return False
            midline, maker_threshold, _taker_threshold, std = thresholds
            cancel_threshold = maker_threshold - (self.config.open_maker_hysteresis_sigma * std)
            if spread_info.spread_pct < cancel_threshold:
                async with self._maker_lock("open_protect"):
                    # 价差不满足条件，取消订单
                    spread_value = spread_info.spread_pct
                    self._log_spread_rule(
                        "warning",
                        BotState.OPENING_MAKER_WAIT,
                        "open_protect",
                        f"实时价差{spread_value:.3%} < 撤销阈值{cancel_threshold:.3%}(中轴{midline:.3%})",
                    )

                    # 先检查是否已成交/部分成交
                    if await self._handle_maker_fill_before_state_change(
                        is_opening=True,
                        reason="价差保护触发时检测到成交，进入对冲",
                    ):
                        return True

                    await self.trade_executor.cancel_extended_maker_order(order_id)

                    # 撤单后再次检查是否成交
                    if await self._handle_maker_fill_before_state_change(
                        is_opening=True,
                        reason="撤单后检测到成交，进入对冲",
                    ):
                        return True

                    # 先检查实际仓位（订单可能已成交但API返回有延迟）
                    ext_position = await self.extended_client.get_account_positions()
                    lig_position = await self.lighter_client.get_account_positions()
                    tolerance = Decimal("0.001")
                    has_position = abs(ext_position) >= tolerance or abs(lig_position) >= tolerance

                    if has_position:
                        # 有仓位，进入 HOLDING 状态
                        reason = f"价差保护触发但检测到仓位，进入持仓（Ext={ext_position}, Lig={lig_position}）"
                        if await self._safe_exit_maker_wait(BotState.HOLDING, reason, is_opening=True):
                            return True
                        self._log_spread_rule(
                            "info",
                            BotState.OPENING_MAKER_WAIT,
                            "open_protect_hold",
                            f"价差保护触发但有仓位 -> 进入HOLDING | Ext={ext_position} Lig={lig_position}",
                        )
                    else:
                        # 无仓位，进入 IDLE 状态
                        reason = f"价差保护触发，取消挂单（实时价差{spread_value:.3%} < 撤销阈值{cancel_threshold:.3%}）"
                        if await self._safe_exit_maker_wait(BotState.IDLE, reason, is_opening=True):
                            return True

                    self._maker_wait_state.reset()
                    await self.state_manager.save_state()
                    return True

        return False

    async def _handle_opening_maker_wait_spread_close_preempt(self, spread_info, **_) -> bool:
        """OPENING_MAKER_WAIT状态：平仓信号处理"""
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            return False
        if self.state_manager.get_state() != BotState.OPENING_MAKER_WAIT:
            return False

        order_id = self._maker_wait_state.current_order.order_id

        # 在开仓等待过程中，如果已有持仓（加仓情况）且满足平仓条件，应该优先平仓
        total_quantity = self.close_strategy.get_total_quantity()
        if total_quantity > 0 and spread_info:
            if spread_info.is_valid():
                self._update_bollinger(spread_info.spread_pct)
            close_spread_info = self._build_close_spread_info(spread_info)
            decision = await self._evaluate_close_decision(spread_info, close_spread_info)
            if decision["should_close"]:
                async with self._maker_lock("open_close_preempt"):
                    self._set_close_context(decision, close_spread_info)
                    await self._capture_close_funds_before()
                    # 需要平仓，取消开仓挂单
                    close_mode = "市价" if decision["use_market"] else "限价"
                    now = time.time()
                    if not hasattr(self, "_last_close_preempt_log_time"):
                        self._last_close_preempt_log_time = 0.0
                    if now - self._last_close_preempt_log_time >= 5.0:
                        self._log_spread_rule(
                            "warning",
                            BotState.OPENING_MAKER_WAIT,
                            "close_preempt",
                            f"{close_mode}平仓 | 平仓价差{decision['close_spread']:.3%} | "
                            f"阈值={(decision['market_threshold'] if decision['use_market'] else decision['limit_threshold']):.3%}",
                            also_print=True,
                        )
                        self._last_close_preempt_log_time = now

                    # 先检查是否已成交/部分成交
                    if await self._handle_maker_fill_before_state_change(
                        is_opening=True,
                        reason="开仓挂单遇到平仓信号时已成交，进入对冲",
                    ):
                        return True

                    # 取消开仓挂单
                    await self.trade_executor.cancel_extended_maker_order(order_id)

                    # 撤单后再次检查是否成交
                    if await self._handle_maker_fill_before_state_change(
                        is_opening=True,
                        reason="撤单后检测到成交，进入对冲",
                    ):
                        return True

                    if decision["use_market"]:
                        # 市价平仓：立即执行
                        await self._execute_market_close(total_quantity)
                        self._log_spread_rule(
                            "info",
                            BotState.OPENING_MAKER_WAIT,
                            "close_preempt_market",
                            f"开仓挂单已取消，执行市价平仓 | 数量={total_quantity}",
                        )
                    else:
                        # 限价平仓：进入 CLOSING 状态
                        reason = (
                            f"开仓过程中检测到平仓信号 | "
                            f"平仓价差≤限价阈值{decision['limit_threshold']:.3%}"
                        )
                        if await self._safe_exit_maker_wait(BotState.CLOSING, reason, is_opening=True):
                            return True
                        self._log_spread_rule(
                            "info",
                            BotState.OPENING_MAKER_WAIT,
                            "close_preempt_limit",
                            f"开仓挂单已取消，进入限价平仓状态 | 原因={reason}",
                        )

                    # 重置等待状态并保存
                    self._maker_wait_state.reset()
                    await self.state_manager.save_state()
                    return True

        return False

    async def _handle_opening_maker_wait_spread_escalate(self, spread_info, **_) -> bool:
        """OPENING_MAKER_WAIT状态：达到市价阈值则撤单并改为市价开仓"""
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            return False
        if self.state_manager.get_state() != BotState.OPENING_MAKER_WAIT:
            return False
        if not spread_info or not spread_info.is_valid():
            return False

        thresholds = await self._get_open_sigma_thresholds()
        if not thresholds:
            return False
        _mid, _maker_th, taker_th, _std = thresholds
        if spread_info.spread_pct < taker_th:
            return False

        order_id = self._maker_wait_state.current_order.order_id
        async with self._maker_lock("open_escalate"):
            self._log_spread_rule(
                "warning",
                BotState.OPENING_MAKER_WAIT,
                "open_escalate",
                f"价差{spread_info.spread_pct:.3%} >= 市价阈值{taker_th:.3%}，撤单改市价开仓",
            )
            self._notify_open_escalate(spread_info.spread_pct, taker_th)

            # 先检查是否已成交/部分成交
            if await self._handle_maker_fill_before_state_change(
                is_opening=True,
                reason="市价阈值触发前检测到成交，进入对冲",
            ):
                return True

            await self.trade_executor.cancel_extended_maker_order(order_id)

            # 撤单后再次检查是否成交
            if await self._handle_maker_fill_before_state_change(
                is_opening=True,
                reason="撤单后检测到成交，进入对冲",
            ):
                return True

            if await self._safe_exit_maker_wait(BotState.OPENING_TAKER, "市价阈值触发，切市价开仓", is_opening=True):
                return True
            self._maker_wait_state.reset()
            await self.state_manager.save_state()
            return True

    async def _handle_closing_maker_wait_spread_transition(self, spread_info, **_) -> bool:
        """CLOSING_MAKER_WAIT状态：价差不满足则撤单回HOLDING"""
        time_module = __import__('time')
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            return False

        if not spread_info:
            return False

        if spread_info.is_valid():
            self._update_bollinger(spread_info.spread_pct)
        close_spread_info = self._build_close_spread_info(spread_info)
        decision = await self._evaluate_close_decision(spread_info, close_spread_info)
        if decision["should_close"]:
            return False

        async with self._maker_lock("close_cancel"):
            now = time_module.time()
            if not hasattr(self, "_last_close_cancel_log_time"):
                self._last_close_cancel_log_time = 0.0
            order_id = self._maker_wait_state.current_order.order_id
            if now - self._last_close_cancel_log_time >= 5.0:
                exit_threshold = decision.get("limit_exit_threshold", decision["limit_threshold"])
                self._log_spread_rule(
                    "warning",
                    BotState.CLOSING_MAKER_WAIT,
                    "close_cancel",
                    f"平仓价差{decision['close_spread']:.3%} > "
                    f"限价离场阈值{exit_threshold:.3%} 且 > 市价阈值{decision['market_threshold']:.3%}",
                )
                self._last_close_cancel_log_time = now

            # 先检查是否已成交/部分成交
            if await self._handle_maker_fill_before_state_change(
                is_opening=False,
                reason="平仓条件失效时检测到成交，进入对冲",
            ):
                return True

            await self.trade_executor.cancel_extended_maker_order(order_id)

            # 撤单后再次检查是否成交
            if await self._handle_maker_fill_before_state_change(
                is_opening=False,
                reason="撤单后检测到成交，进入对冲",
            ):
                return True

            # 撤单后检查实际仓位，如果已平仓则进入确认流程
            try:
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()
                tolerance = Decimal("0.001")
                ext_closed = abs(ext_position) < tolerance
                lig_closed = abs(lig_position) < tolerance
                if ext_closed and lig_closed:
                    self._closing_wait_start_time = time_module.time()
                    self.state_manager.set_state(
                        BotState.CLOSING_WAIT,
                        "撤单后检测到无仓位，验证平仓",
                    )
                    await self.state_manager.save_state()
                    return True
            except Exception as e:
                logger.warning(f"撤单后检查仓位失败: {e}")

            exit_threshold = decision.get("limit_exit_threshold", decision["limit_threshold"])
            reason = (
                f"平仓条件失效，取消挂单（平仓价差{decision['close_spread']:.3%} > "
                f"限价离场阈值{exit_threshold:.3%}）"
            )
            if await self._safe_exit_maker_wait(BotState.HOLDING, reason, is_opening=False):
                return True
            self._maker_wait_state.reset()
            await self.state_manager.save_state()
            return True

    async def _handle_hedging_failure(self, is_opening: bool, ext_filled_qty: Decimal) -> None:
        """
        处理Lighter对冲失败

        根据Edge Case决策：
        - 只强制平仓本次新开仓的Extended仓位
        - 保留原有持仓不动
        - 如果强制平仓失败，进入PAUSED状态
        """
        try:
            # 先检查实际仓位，若已平衡则直接恢复
            try:
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()
                tolerance = Decimal("0.001")
                if abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                    logger.warning("对冲失败但实际无仓位，进入平仓确认")
                    self.close_strategy.close_all()
                    self._maker_close_fail_count = 0
                    self.state_manager.update_position(None)
                    if not is_opening:
                        self._closing_wait_start_time = time.time()
                        self.state_manager.set_state(BotState.CLOSING_WAIT, "对冲失败但实际无仓位，验证平仓")
                    else:
                        self.state_manager.set_state(BotState.IDLE, "对冲失败但实际无仓位")
                    await self.state_manager.save_state()
                    return
            except Exception as e:
                logger.warning(f"对冲失败后仓位检查异常: {e}")

            # 如果是平仓对冲失败且Ext已平，则尝试补Lighter减仓
            if not is_opening:
                try:
                    ext_position = await self.extended_client.get_account_positions()
                    lig_position = await self.lighter_client.get_account_positions()
                    tolerance = Decimal("0.001")
                    if abs(ext_position) < tolerance and abs(lig_position) >= tolerance:
                        side = "buy" if lig_position < 0 else "sell"
                        qty = abs(lig_position)
                        logger.warning(
                            f"平仓对冲失败，检测到Lighter残仓 {lig_position}，尝试补单减仓"
                        )
                        success = False
                        for attempt in range(1, 4):
                            try:
                                await self.trade_executor._place_lighter_order_taker(
                                    side=side,
                                    quantity=qty,
                                    price=None,
                                    reduce_only=True,
                                )
                                logger.info(f"Lighter补单减仓成功 | attempt={attempt} qty={qty}")
                                success = True
                                break
                            except Exception as e:
                                logger.warning(f"Lighter补单减仓失败 | attempt={attempt} err={e}")
                                await asyncio.sleep(0.5)
                        if not success:
                            logger.error("Lighter补单减仓重试失败，进入风控暂停")
                            reason = f"Lighter补单减仓失败: qty={qty}"
                            self.state_manager.set_state(BotState.PAUSED, reason)
                            self._notify_paused(reason)
                            await self.state_manager.save_state()
                            return
                        self.state_manager.set_state(BotState.CLOSING_WAIT, "补Lighter减仓后验证平仓")
                        self._closing_wait_start_time = time.time()
                        await self.state_manager.save_state()
                        return
                except Exception as e:
                    logger.warning(f"补Lighter减仓失败: {e}")

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
            reason = f"Lighter对冲失败，需要人工处理: ext_filled_qty={ext_filled_qty}"
            self.state_manager.set_state(BotState.PAUSED, reason)
            self._notify_paused(reason)
            await self.state_manager.save_state()

        except Exception as e:
            logger.error(f"强制平仓异常: {e}")
            reason = f"强制平仓异常: {e}"
            self.state_manager.set_state(BotState.PAUSED, reason)
            self._notify_paused(reason)
            await self.state_manager.save_state()

    async def _get_maker_order_fill_info(self, order_id: str) -> tuple[Decimal, str, Decimal]:
        """
        获取Maker订单成交信息

        Returns:
            filled_qty, status, avg_price
        """
        filled_qty = Decimal("0")
        avg_price = Decimal("0")
        status = "UNKNOWN"

        try:
            order_info = await self.trade_executor.get_extended_order_info(order_id)
            if order_info:
                status = str(order_info.get("status", status)).upper()
                raw_filled = order_info.get("filled_size", "0")
                if isinstance(raw_filled, str):
                    filled_qty = Decimal(raw_filled)
                elif isinstance(raw_filled, (int, float)):
                    filled_qty = Decimal(str(raw_filled))
                else:
                    filled_qty = Decimal(raw_filled) if raw_filled else Decimal("0")

                raw_avg = order_info.get("avg_price") or order_info.get("avg_fill_price")
                if raw_avg is not None:
                    avg_price = Decimal(str(raw_avg))
        except Exception as e:
            logger.warning(f"获取订单成交信息失败 | {order_id} | {e}")

        return filled_qty, status, avg_price

    async def _handle_maker_fill_before_state_change(self, is_opening: bool, reason: str) -> bool:
        """
        在状态切换前检测挂单是否已成交/部分成交，避免单边风险
        """
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            return False

        order = self._maker_wait_state.current_order
        filled_qty, status, avg_price = await self._get_maker_order_fill_info(order.order_id)

        if filled_qty <= 0 and status not in ["FILLED", "PARTIALLY_FILLED"]:
            return False

        if filled_qty <= 0:
            filled_qty = order.filled_quantity or Decimal("0")
        if filled_qty <= 0:
            return False

        if avg_price <= 0:
            avg_price = order.avg_fill_price or order.price

        # 更新 MakerWaitState 中的订单状态
        order.status = "FILLED" if status == "FILLED" else "PARTIALLY_FILLED"
        order.filled_quantity = filled_qty
        order.avg_fill_price = avg_price

        # 进入 LIGHTER_HEDGING 状态前做仓位变化确认
        try:
            if not await self._confirm_ext_position_change(is_opening, filled_qty):
                logger.warning("成交校验失败，跳过对冲进入原状态切换")
                return False
        except Exception as e:
            logger.debug(f"成交校验异常，继续原逻辑: {e}")

        # 进入 LIGHTER_HEDGING 状态对冲
        if not hasattr(self, '_hedging_state'):
            from models import HedgingState
            self._hedging_state = HedgingState()
        self._hedging_state.ext_filled_quantity = filled_qty
        self._hedging_state.ext_filled_price = avg_price
        self._hedging_state.start_time = datetime.now()

        if is_opening:
            self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"{reason}（Ext成交{filled_qty}）")
        else:
            self._hedging_state.is_closing = True
            self.state_manager.set_state(BotState.LIGHTER_HEDGING, f"{reason}（Ext成交{filled_qty}）")

        await self.state_manager.save_state()
        return True

    async def _handle_closing_maker_wait_spread_escalate(self, spread_info, **_) -> bool:
        """CLOSING_MAKER_WAIT状态：达到市价阈值则撤单并改市价平仓"""
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state.current_order is None:
            return False
        if not spread_info or not spread_info.is_valid():
            return False

        close_spread_info = self._build_close_spread_info(spread_info)
        decision = await self._evaluate_close_decision(spread_info, close_spread_info)
        if not decision["should_close"] or not decision["use_market"]:
            return False

        order_id = self._maker_wait_state.current_order.order_id
        async with self._maker_lock("close_escalate"):
            self._log_spread_rule(
                "warning",
                BotState.CLOSING_MAKER_WAIT,
                "close_escalate",
                f"平仓价差{decision['close_spread']:.3%} <= 市价阈值{decision['market_threshold']:.3%}，撤单改市价平仓",
            )
            self._notify_close_escalate(decision["close_spread"], decision["market_threshold"])

            # 先检查是否已成交/部分成交
            if await self._handle_maker_fill_before_state_change(
                is_opening=False,
                reason="市价平仓阈值触发前检测到成交，进入对冲",
            ):
                return True

            await self.trade_executor.cancel_extended_maker_order(order_id)

            # 撤单后再次检查是否成交
            if await self._handle_maker_fill_before_state_change(
                is_opening=False,
                reason="撤单后检测到成交，进入对冲",
            ):
                return True

            total_quantity = self.close_strategy.get_total_quantity()
            await self._execute_market_close(total_quantity)
            self._log_spread_rule(
                "info",
                BotState.CLOSING_MAKER_WAIT,
                "close_escalate_market",
                f"挂单已取消，执行市价平仓 | 数量={total_quantity}",
            )

            self._maker_wait_state.reset()
            await self.state_manager.save_state()
            return True

    async def _safe_exit_maker_wait(self, next_state: BotState, reason: str, is_opening: bool) -> bool:
        """
        在离开Maker等待状态前做成交检查，避免错过已成交订单
        """
        return await self._transition_state(
            next_state=next_state,
            reason=reason,
            guard=lambda: self._handle_maker_fill_before_state_change(
                is_opening=is_opening,
                reason="状态切换前检测到成交，进入对冲",
            ),
        )

    async def _transition_state(
        self,
        next_state: BotState,
        reason: str,
        guard=None,
    ) -> bool:
        """
        统一状态切换入口（可选守卫）

        Returns:
            True if guard handled transition (skip set_state), False otherwise.
        """
        if guard is not None:
            try:
                handled = await guard()
                if handled:
                    return True
            except Exception as e:
                logger.warning(f"状态切换守卫异常: {e}")
        self.state_manager.set_state(next_state, reason)
        return False

    async def _confirm_ext_position_change(self, is_opening: bool, expected_qty: Decimal) -> bool:
        """
        通过Ext仓位变化确认成交真实性，避免误判成交触发对冲
        """
        if not hasattr(self, '_maker_wait_state') or self._maker_wait_state is None:
            return True

        before = self._maker_wait_state.ext_position_before
        if before is None:
            return True

        try:
            current = await self.extended_client.get_account_positions()
        except Exception as e:
            logger.debug(f"成交校验读取Ext仓位失败: {e}")
            return True

        delta = (abs(current) - abs(before)) if is_opening else (abs(before) - abs(current))
        threshold = max(Decimal("0.001"), expected_qty * Decimal("0.2"))

        logger.info(
            f"成交校验 | is_opening={is_opening} | before={before} | current={current} | "
            f"delta={delta} | expected={expected_qty} | threshold={threshold}"
        )

        return delta >= threshold

    async def _reposition_maker_order(self, is_opening: bool) -> None:
        """
        重新挂单（取消旧订单 + 挂出新订单）

        Args:
            is_opening: True=开仓重挂, False=平仓重挂
        """
        async with self._maker_lock("reposition"):
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
                elif old_order.filled_quantity:
                    # REST查不到订单时，回退到本地WS记录
                    filled_qty = old_order.filled_quantity

                print(
                    f"🔄 订单状态查询 | "
                    f"原订单数量: {old_order.quantity} | "
                    f"已成交数量: {filled_qty} | "
                    f"剩余数量: {old_order.quantity - filled_qty}"
                )

                # 2. 取消旧订单并验证取消成功 (003-spreading-improvements: 使用带验证的取消方法)
                try:
                    await self.trade_executor.cancel_maker_order_with_verification(
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

                    # 成交校验：确认Ext仓位变化
                    try:
                        if not await self._confirm_ext_position_change(is_opening, old_order.quantity):
                            logger.warning("成交校验失败，取消进入对冲，返回持仓状态")
                            self.state_manager.set_state(BotState.HOLDING, "成交校验失败，返回持仓")
                            await self.state_manager.save_state()
                            return
                    except Exception as e:
                        logger.debug(f"成交校验异常，继续原逻辑: {e}")

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

                # 4. 重新挂单前确认状态仍然有效
                current_state = self.state_manager.get_state()
                if current_state not in [BotState.OPENING_MAKER_WAIT, BotState.CLOSING_MAKER_WAIT]:
                    logger.warning(f"状态已变更({current_state.value})，取消重挂")
                    return
                if not self._maker_wait_state.current_order or self._maker_wait_state.current_order.order_id != old_order.order_id:
                    logger.warning("当前订单已变更，取消重挂")
                    return

                # 5. 重新挂单（使用剩余数量）
                if is_opening:
                    result = await self.trade_executor.place_maker_open_order(remaining_qty)
                else:
                    result = await self.trade_executor.place_maker_close_order(remaining_qty)

                if result.success:
                    # 6. 更新状态
                    context_id = old_order.context_id or (
                        self._maker_wait_state.context_id if hasattr(self, '_maker_wait_state') else None
                    )
                    new_order = MakerOrder(
                        order_id=result.extended_order_id,
                        price=result.extended_price,
                        quantity=remaining_qty,
                        side=old_order.side,
                        is_opening=is_opening,
                        context_id=context_id
                    )
                    self._maker_wait_state.current_order = new_order
                    self._maker_wait_state.reposition_count += 1
                    self._last_maker_order_id = str(result.extended_order_id)
                    self._last_maker_is_opening = is_opening
                    if context_id:
                        self._last_maker_context_id = context_id
                        self._maker_wait_state.context_id = context_id

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
            # 如果交易所已无仓位，直接回到IDLE
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            if abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                logger.warning("市价平仓前检测到无仓位，跳过下单并回到IDLE")
                self.close_strategy.close_all()
                self._maker_close_fail_count = 0
                self.state_manager.update_position(None)
                self.state_manager.set_state(BotState.IDLE, "无仓位，跳过市价平仓")
                await self.state_manager.save_state()
                return
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

                # 进入CLOSING_WAIT状态，由仓位确认统一收尾/推送
                import time
                self._closing_wait_start_time = time.time()
                self.state_manager.set_state(BotState.CLOSING_WAIT, "市价平仓完成，等待确认")
                await self.state_manager.save_state()
            else:
                logger.error(f"市价平仓失败: {result.error_message}")
                # 市价平仓失败，回到HOLDING状态
                # 追加实盘仓位确认，避免状态查询超时导致的误判
                await asyncio.sleep(1.0)
                ext_position = await self.extended_client.get_account_positions()
                lig_position = await self.lighter_client.get_account_positions()
                tolerance = Decimal("0.001")
                if abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                    logger.info("市价平仓确认：实盘已无仓位，按成功处理")
                    self.close_strategy.close_all()
                    self._maker_close_fail_count = 0
                    self.state_manager.update_position(None)
                    import time
                    self._closing_wait_start_time = time.time()
                    self.state_manager.set_state(BotState.CLOSING_WAIT, "市价平仓完成(仓位确认)")
                    await self.state_manager.save_state()
                else:
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
            from uuid import uuid4
            # 如果交易所已无仓位，直接回到IDLE
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            if abs(ext_position) < tolerance and abs(lig_position) < tolerance:
                logger.warning("限价平仓前检测到无仓位，跳过下单并回到IDLE")
                self.close_strategy.close_all()
                self._maker_close_fail_count = 0
                self.state_manager.update_position(None)
                self.state_manager.set_state(BotState.IDLE, "无仓位，跳过限价平仓")
                await self.state_manager.save_state()
                return

            effective_qty = min(total_quantity, abs(ext_position))
            if effective_qty < tolerance:
                logger.warning(
                    f"限价平仓前检测到Ext仓位不足，跳过Maker | ext={ext_position}, lig={lig_position}"
                )
                if abs(lig_position) >= tolerance:
                    side = "sell" if lig_position > 0 else "buy"
                    await self.trade_executor.rollback_position("lighter", abs(lig_position), side)
                self.state_manager.set_state(BotState.CLOSING_WAIT, "Ext仓位不足，等待仓位确认")
                await self.state_manager.save_state()
                return

            # 使用Maker模式平仓（017-ext-maker-mode已经支持）
            result = await self.trade_executor.place_maker_close_order(effective_qty)

            if not result.success or result.extended_order_id is None:
                logger.error(f"Extended Maker平仓订单失败: {result.error_message}")
                self._maker_close_fail_count += 1
                if self._maker_close_fail_count >= self.config.maker_close_fail_threshold:
                    logger.warning(
                        f"Maker平仓失败达到阈值{self.config.maker_close_fail_threshold}，改用市价平仓"
                    )
                    await self._execute_market_close(total_quantity)
                else:
                    self.state_manager.set_state(BotState.HOLDING, "Maker平仓订单失败")
                    await self.state_manager.save_state()
                return

            # 成功挂单则清零失败计数
            self._maker_close_fail_count = 0

            # 初始化Maker等待状态
            from models import MakerWaitState
            if not hasattr(self, '_maker_wait_state'):
                self._maker_wait_state = MakerWaitState()

            # 创建MakerOrder对象
            context_id = f"maker-{uuid4().hex}"
            close_order = MakerOrder(
                order_id=result.extended_order_id,
                price=result.extended_price,
                quantity=effective_qty,
                side='sell',  # 平仓时卖出
                is_opening=False,  # 标记为平仓订单
                context_id=context_id
            )
            self._last_maker_order_id = str(result.extended_order_id)
            self._last_maker_is_opening = False
            self._last_maker_context_id = context_id
            self._last_maker_context_state = BotState.CLOSING_MAKER_WAIT

            self._maker_wait_state.current_order = close_order
            self._maker_wait_state.context_id = context_id

            logger.info(
                f"✅ Extended Maker平仓订单已挂出 | "
                f"order_id={close_order.order_id} | "
                f"price={close_order.price} | "
                f"quantity={close_order.quantity}"
            )

            # 启动 WebSocket 订单监控
            self.maker_order_monitor.start_monitoring(close_order)

            # 进入 CLOSING_MAKER_WAIT 状态等待成交
            # WebSocket 回调会处理：成交 -> LIGHTER_HEDGING，取消 -> HOLDING
            self.state_manager.set_state(
                BotState.CLOSING_MAKER_WAIT,
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
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Lighter-Extended 单向价差收敛套利系统"
    )

    def env_default(name: str, cast, fallback):
        val = os.getenv(name)
        if val is None or str(val).strip() == "":
            return fallback
        try:
            return cast(val)
        except Exception:
            return fallback

    def env_bool(name: str, fallback: bool) -> bool:
        val = os.getenv(name)
        if val is None:
            return fallback
        return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}

    parser.add_argument(
        "--symbol",
        type=str,
        default=os.getenv("SYMBOL", "BTC"),
        help="交易对 (默认: BTC)"
    )

    parser.add_argument(
        "--size",
        type=Decimal,
        default=Decimal(str(env_default("TARGET_QUANTITY", Decimal, Decimal("0.01")))),
        dest="target_quantity",
        help="交易数量 (默认: 0.01)"
    )


    parser.add_argument(
        "--spread-threshold",
        type=Decimal,
        default=Decimal(str(env_default("MIN_SPREAD_THRESHOLD", Decimal, Decimal("0.0004")))),
        dest="min_spread_threshold",
        help="最小价差阈值 (默认: 0.002 = 0.04%%)"
    )

    parser.add_argument(
        "--slippage-buffer",
        type=Decimal,
        default=Decimal(str(env_default("SLIPPAGE_BUFFER", Decimal, Decimal("0.0001")))),
        help="滑点保护 (默认: 0.0005 = 0.01%%)"
    )

    parser.add_argument(
        "--min-profit",
        type=Decimal,
        default=Decimal(str(env_default("MIN_PROFIT", Decimal, Decimal("0")))),
        help="最小利润 (默认: 0 = 0%%)"
    )

    parser.add_argument(
        "--max-spread",
        type=Decimal,
        default=Decimal(str(env_default("MAX_SPREAD", Decimal, Decimal("0.05")))),
        help="极端价差阈值 (默认: 0.05 = 5%%)"
    )

    parser.add_argument(
        "--spread-step",
        type=Decimal,
        default=env_default("SPREAD_STEP", Decimal, None),
        dest="spread_step",
        help="价差步长值 (默认: 0.00002 = 0.002%%) (003-spreading-improvements)"
    )

    parser.add_argument(
        "--initial-open-spread",
        type=Decimal,
        default=env_default("INITIAL_OPEN_SPREAD", Decimal, None),
        dest="initial_open_spread",
        help="初始开仓价差阈值 (默认: 0.0006 = 0.06%%) (003-spreading-improvements)"
    )

    parser.add_argument(
        "--balance-buffer",
        type=float,
        default=env_default("BALANCE_CHECK_BUFFER", float, 3.0),
        dest="balance_check_buffer",
        help="仓位平衡检测缓冲期（秒） (默认: 3.0) (016-spread-optimize)"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=env_default("SINGLE_SIDE_TIMEOUT", float, 3.0),
        dest="single_side_timeout",
        help="单边超时时间（秒） (默认: 3.0)"
    )

    parser.add_argument(
        "--open-wait-timeout",
        type=float,
        default=env_default("OPEN_WAIT_TIMEOUT", float, 10.0),
        dest="open_wait_timeout",
        help="开仓等待确认超时时间（秒） (默认: 10.0)"
    )

    parser.add_argument(
        "--lighter-hedge-slippage",
        type=Decimal,
        default=env_default("LIGHTER_HEDGE_SLIPPAGE_BPS", Decimal, None),
        dest="lighter_hedge_slippage_bps",
        help="Lighter对冲VWAP滑点缓冲 (默认: 0.0002 = 0.02%)"
    )
    parser.add_argument(
        "--use-bollinger",
        action="store_true",
        dest="use_bollinger",
        help="启用布林带动态阈值"
    )
    parser.add_argument(
        "--boll-window-minutes",
        type=int,
        default=env_default("BOLL_WINDOW_MINUTES", int, None),
        dest="boll_window_minutes",
        help="布林带统计窗口（分钟）"
    )
    parser.add_argument(
        "--boll-k",
        type=Decimal,
        default=env_default("BOLL_K", Decimal, None),
        dest="boll_k",
        help="布林带标准差倍数（默认: 2）"
    )
    parser.add_argument(
        "--open-taker-sigma",
        type=Decimal,
        default=env_default("OPEN_TAKER_SIGMA", Decimal, None),
        dest="open_taker_sigma",
        help="市价开仓触发Sigma倍数（默认: 2.5）"
    )
    parser.add_argument(
        "--open-maker-sigma",
        type=Decimal,
        default=env_default("OPEN_MAKER_SIGMA", Decimal, None),
        dest="open_maker_sigma",
        help="挂单开仓触发Sigma倍数（默认: 1.75）"
    )
    parser.add_argument(
        "--open-sigma-penalty",
        type=Decimal,
        default=env_default("OPEN_SIGMA_PENALTY", Decimal, None),
        dest="open_sigma_penalty",
        help="库存倾斜惩罚系数（默认: 0.5）"
    )
    parser.add_argument(
        "--close-limit-hysteresis-sigma",
        type=Decimal,
        default=env_default("CLOSE_LIMIT_HYSTERESIS_SIGMA", Decimal, None),
        dest="close_limit_hysteresis_sigma",
        help="挂单平仓触发阈值Sigma（默认: 0.1）"
    )
    parser.add_argument(
        "--limit-close-a",
        type=Decimal,
        default=env_default("LIMIT_CLOSE_A", Decimal, None),
        dest="limit_close_spread_a",
        help="挂单平仓收益阈值A（默认: 0.00005 = 0.005%）"
    )
    parser.add_argument(
        "--market-close-b",
        type=Decimal,
        default=env_default("MARKET_CLOSE_B", Decimal, None),
        dest="market_close_spread_b",
        help="市价平仓收益阈值B（默认: 0.0001 = 0.01%）"
    )
    parser.add_argument(
        "--boll-sample-interval",
        type=float,
        default=env_default("BOLL_SAMPLE_INTERVAL", float, None),
        dest="boll_sample_interval",
        help="布林带采样间隔（秒）"
    )
    parser.add_argument(
        "--boll-min-samples",
        type=int,
        default=env_default("BOLL_MIN_SAMPLES", int, None),
        dest="boll_min_samples",
        help="布林带最小样本数"
    )
    parser.add_argument(
        "--boll-bandwidth-min",
        type=Decimal,
        default=env_default("BOLL_BANDWIDTH_MIN", Decimal, None),
        dest="boll_bandwidth_min",
        help="布林带宽度阈值（(upper-lower)/midline，默认: 0.001 = 0.1%）"
    )
    parser.add_argument(
        "--switch-cost-bps",
        type=Decimal,
        default=env_default("SWITCH_COST_BPS", Decimal, None),
        dest="switch_cost_bps",
        help="腾笼换鸟换仓成本（默认: 0.000225 = 0.0225%%）"
    )
    parser.add_argument(
        "--switch-min-hold-minutes",
        type=int,
        default=env_default("SWITCH_MIN_HOLD_MINUTES", int, None),
        dest="switch_min_hold_minutes",
        help="腾笼换鸟最小持仓时间（分钟）"
    )
    parser.add_argument(
        "--dashboard-ingest-url",
        type=str,
        default=env_default("DASHBOARD_INGEST_URL", str, None),
        dest="dashboard_ingest_url",
        help="Dashboard写入URL（例如: http://localhost:3000/api/ingest）"
    )
    parser.add_argument(
        "--dashboard-sample-interval",
        type=float,
        default=env_default("DASHBOARD_SAMPLE_INTERVAL", float, None),
        dest="dashboard_sample_interval",
        help="Dashboard采样间隔（秒）"
    )
    parser.add_argument(
        "--dashboard-position-interval",
        type=float,
        default=env_default("DASHBOARD_POSITION_INTERVAL", float, None),
        dest="dashboard_position_interval",
        help="Dashboard仓位/余额采样间隔（秒）"
    )
    parser.add_argument(
        "--maker-close-fail-threshold",
        type=int,
        default=env_default("MAKER_CLOSE_FAIL_THRESHOLD", int, None),
        dest="maker_close_fail_threshold",
        help="Maker平仓失败阈值，超过后自动改用市价平仓"
    )
    parser.add_argument(
        "--close-market-on-lower",
        action="store_true",
        dest="close_market_on_lower",
        help="价差触达下轨时使用市价平仓"
    )
    parser.add_argument(
        "--no-close-market-on-lower",
        action="store_true",
        dest="no_close_market_on_lower",
        help="价差触达下轨时不使用市价平仓"
    )
    parser.add_argument(
        "--notify-open-trigger",
        action="store_true",
        dest="notify_open_trigger",
        help="推送开仓触发信号"
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
    if args.lighter_hedge_slippage_bps is not None:
        config_kwargs['lighter_hedge_slippage_bps'] = args.lighter_hedge_slippage_bps
    if args.use_bollinger or env_bool("USE_BOLLINGER", False):
        config_kwargs['use_bollinger'] = True
    if args.boll_window_minutes is not None:
        config_kwargs['boll_window_minutes'] = args.boll_window_minutes
    if args.boll_k is not None:
        config_kwargs['boll_k'] = args.boll_k
    if args.open_taker_sigma is not None:
        config_kwargs['open_taker_sigma'] = args.open_taker_sigma
    if args.open_maker_sigma is not None:
        config_kwargs['open_maker_sigma'] = args.open_maker_sigma
    if args.open_sigma_penalty is not None:
        config_kwargs['open_sigma_penalty'] = args.open_sigma_penalty
    if args.close_limit_hysteresis_sigma is not None:
        config_kwargs['close_limit_hysteresis_sigma'] = args.close_limit_hysteresis_sigma
    if args.boll_sample_interval is not None:
        config_kwargs['boll_sample_interval'] = args.boll_sample_interval
    if args.boll_min_samples is not None:
        config_kwargs['boll_min_samples'] = args.boll_min_samples
    if args.boll_bandwidth_min is not None:
        config_kwargs['boll_bandwidth_min'] = args.boll_bandwidth_min
    if args.limit_close_spread_a is not None:
        config_kwargs['limit_close_spread_a'] = args.limit_close_spread_a
    if args.market_close_spread_b is not None:
        config_kwargs['market_close_spread_b'] = args.market_close_spread_b
    if args.switch_cost_bps is not None:
        config_kwargs['switch_cost_bps'] = args.switch_cost_bps
    if args.switch_min_hold_minutes is not None:
        config_kwargs['switch_min_hold_minutes'] = args.switch_min_hold_minutes
    if args.dashboard_ingest_url is not None:
        config_kwargs['dashboard_ingest_url'] = args.dashboard_ingest_url
    if args.dashboard_sample_interval is not None:
        config_kwargs['dashboard_sample_interval'] = args.dashboard_sample_interval
    if args.dashboard_position_interval is not None:
        config_kwargs['dashboard_position_interval'] = args.dashboard_position_interval
    if args.maker_close_fail_threshold is not None:
        config_kwargs['maker_close_fail_threshold'] = args.maker_close_fail_threshold
    if args.close_market_on_lower:
        config_kwargs['close_market_on_lower'] = True
    if args.no_close_market_on_lower:
        config_kwargs['close_market_on_lower'] = False
    if args.notify_open_trigger or env_bool("NOTIFY_OPEN_TRIGGER", False):
        config_kwargs['notify_open_trigger'] = True

    if 'close_market_on_lower' not in config_kwargs:
        config_kwargs['close_market_on_lower'] = env_bool("CLOSE_MARKET_ON_LOWER", False)
    if 'dashboard_ingest_url' not in config_kwargs:
        config_kwargs['dashboard_ingest_url'] = os.getenv("DASHBOARD_INGEST_URL", "")
    if 'dashboard_sample_interval' not in config_kwargs:
        config_kwargs['dashboard_sample_interval'] = env_default("DASHBOARD_SAMPLE_INTERVAL", float, None) or 1.0
    if 'dashboard_position_interval' not in config_kwargs:
        config_kwargs['dashboard_position_interval'] = env_default("DASHBOARD_POSITION_INTERVAL", float, None) or 1.0
    if 'maker_close_fail_threshold' not in config_kwargs:
        config_kwargs['maker_close_fail_threshold'] = env_default("MAKER_CLOSE_FAIL_THRESHOLD", int, None) or 3

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
