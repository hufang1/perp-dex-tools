"""
实时价差监控模块

负责：
1. 订阅order_book_manager的价格更新
2. 计算两个交易所的价差
3. 输出单行精简日志
4. 提供get_current_spread()方法供其他组件使用
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime

from models import RealTimeSpreadInfo, OrderBook


logger = logging.getLogger(__name__)


class SpreadMonitor:
    """
    实时价差监控器

    订阅订单簿更新，计算并存储当前价差信息
    """

    def __init__(self, order_book_manager, open_threshold: Decimal = Decimal("0.002"), slippage_buffer: Decimal = Decimal("0.0005")):
        """
        初始化价差监控器

        Args:
            order_book_manager: 订单簿管理器实例
            open_threshold: 开仓阈值（默认 0.20%）
            slippage_buffer: 滑点保护（默认 0.05%）
        """
        self.order_book_manager = order_book_manager
        self.open_threshold = open_threshold
        self.slippage_buffer = slippage_buffer
        self._current_spread: Optional[RealTimeSpreadInfo] = None
        self._last_log_time: float = 0
        self._log_interval: float = 5.0  # 每5秒输出一次日志
        self._running: bool = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动价差监控"""
        if self._running:
            logger.warning("价差监控已在运行")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("价差监控已启动")

    async def stop(self) -> None:
        """停止价差监控"""
        if not self._running:
            return

        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        logger.info("价差监控已停止")

    async def _monitor_loop(self) -> None:
        """监控循环：定期计算价差"""
        while self._running:
            try:
                # 计算价差
                spread_info = self._calculate_spread()

                if spread_info:
                    # 只在价差有效时更新 current_spread
                    if spread_info.is_valid():
                        self._current_spread = spread_info

                    # 限制日志输出频率（每5秒一次）
                    current_time = asyncio.get_event_loop().time()
                    if current_time - self._last_log_time >= self._log_interval:
                        # 使用配置的开仓阈值和滑点保护
                        logger.info(spread_info.format_log(self.open_threshold, self.slippage_buffer))
                        self._last_log_time = current_time

                # 等待下一次检查
                await asyncio.sleep(0.1)  # 100ms更新频率

            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _calculate_spread(self) -> Optional[RealTimeSpreadInfo]:
        """
        计算价差

        Returns:
            RealTimeSpreadInfo对象，如果数据无效则返回None
        """
        try:
            # 获取两个交易所的订单簿
            ext_orderbook = self.order_book_manager.get_order_book("extended")
            lig_orderbook = self.order_book_manager.get_order_book("lighter")

            if ext_orderbook is None or lig_orderbook is None:
                return None

            # 获取最佳买卖价
            ext_best_bid = ext_orderbook.get_best_bid()
            ext_best_ask = ext_orderbook.get_best_ask()
            lig_best_bid = lig_orderbook.get_best_bid()
            lig_best_ask = lig_orderbook.get_best_ask()

            if ext_best_bid is None or ext_best_ask is None:
                return None
            if lig_best_bid is None or lig_best_ask is None:
                return None

            # 提取价格
            ext_bid = ext_best_bid[0]
            ext_ask = ext_best_ask[0]
            lig_bid = lig_best_bid[0]
            lig_ask = lig_best_ask[0]

            # 验证价格有效性
            if ext_bid <= 0 or ext_ask <= 0 or lig_bid <= 0 or lig_ask <= 0:
                return None
            if ext_bid >= ext_ask or lig_bid >= lig_ask:
                return None

            # 计算价差（与开仓策略对齐）
            # 开仓：Extended 买入 + Lighter 卖出
            # 价差 = (Lighter_Bid - Extended_Ask) / Extended_Ask
            spread_abs = lig_bid - ext_ask

            # 计算百分比价差（相对于 Extended Ask 价格）
            spread_pct = spread_abs / ext_ask if ext_ask > 0 else Decimal("0")

            # 创建价差信息对象
            spread_info = RealTimeSpreadInfo(
                ext_bid=ext_bid,
                ext_ask=ext_ask,
                lig_bid=lig_bid,
                lig_ask=lig_ask,
                spread_abs=spread_abs,
                spread_pct=spread_pct,
                timestamp=datetime.now().timestamp(),
            )

            return spread_info

        except Exception:
            return None

    def get_current_spread(self) -> Optional[RealTimeSpreadInfo]:
        """
        获取当前价差

        Returns:
            当前价差信息，如果没有可用数据则返回None
        """
        return self._current_spread

    def is_valid_spread(self, spread: Optional[RealTimeSpreadInfo]) -> bool:
        """
        验证价差数据是否有效

        Args:
            spread: 价差信息对象

        Returns:
            True如果价差数据有效，否则False
        """
        if spread is None:
            return False
        return spread.is_valid()
