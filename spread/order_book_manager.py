"""
订单簿管理器：管理两个交易所的订单簿数据

负责：
1. 接收和处理 WebSocket 订单簿更新
2. 计算 VWAP（成交量加权平均价）
3. 验证订单簿数据完整性（序列号检查）
4. 检测数据缺失并重新获取快照
"""

import asyncio
from decimal import Decimal
from typing import Dict, Optional, Callable
from datetime import datetime
import logging

from models import OrderBook, BotState
from exceptions import (
    OrderBookNotReadyError,
    InsufficientDepthError,
    WebSocketConnectionError,
    OrderBookSequenceError,
)
from utils import (
    calculate_vwap,
    validate_order_book_integrity,
    depth_is_sufficient,
)


logger = logging.getLogger(__name__)


class OrderBookManager:
    """
    管理两个交易所（Lighter 和 Extended）的订单簿

    功能：
    - 维护两个交易所的订单簿状态
    - 通过 WebSocket 接收实时更新
    - 计算 VWAP
    - 验证数据完整性
    """

    def __init__(self, symbol: str):
        """
        初始化订单簿管理器

        Args:
            symbol: 交易对符号，如 "BTC"
        """
        self.symbol = symbol

        # 订单簿数据
        self.lighter_order_book: Optional[OrderBook] = None
        self.extended_order_book: Optional[OrderBook] = None

        # 序列号跟踪
        self.lighter_last_sequence: int = 0
        self.extended_last_sequence: int = 0

        # WebSocket 连接状态
        self.lighter_connected: bool = False
        self.extended_connected: bool = False

        # 更新回调函数
        self._update_handlers: list[Callable] = []

        # 重连配置
        self._reconnect_delay_base: float = 1.0
        self._reconnect_delay_max: float = 60.0
        self._running: bool = False

    def get_order_book(self, exchange: str) -> OrderBook:
        """
        获取指定交易所的订单簿

        Args:
            exchange: "lighter" 或 "extended"

        Returns:
            OrderBook 对象

        Raises:
            ValueError: 交易所名称无效
            OrderBookNotReadyError: 订单簿数据未就绪
        """
        if exchange not in ["lighter", "extended"]:
            raise ValueError(f"无效的交易所名称: {exchange}")

        if exchange == "lighter":
            if self.lighter_order_book is None or not self.lighter_order_book.is_valid:
                raise OrderBookNotReadyError("Lighter 订单簿未就绪")
            return self.lighter_order_book
        else:
            if self.extended_order_book is None or not self.extended_order_book.is_valid:
                raise OrderBookNotReadyError("Extended 订单簿未就绪")
            return self.extended_order_book

    async def calculate_vwap(
        self,
        exchange: str,
        quantity: Decimal,
        side: str
    ) -> Decimal:
        """
        计算指定交易所的 VWAP

        Args:
            exchange: "lighter" 或 "extended"
            quantity: 目标交易数量
            side: "buy" 或 "sell"

        Returns:
            VWAP 价格

        Raises:
            InsufficientDepthError: 订单簿深度不足
        """
        order_book = self.get_order_book(exchange)

        # 根据买卖方向选择订单簿侧
        if side == "buy":
            order_book_side = order_book.asks
        elif side == "sell":
            order_book_side = order_book.bids
        else:
            raise ValueError(f"无效的交易方向: {side}")

        # 检查深度是否足够
        if not depth_is_sufficient(order_book_side, quantity, side):
            total_available = sum(order_book_side.values())
            raise InsufficientDepthError(
                exchange,
                float(quantity),
                float(total_available)
            )

        # 计算 VWAP
        vwap = calculate_vwap(order_book_side, quantity, side)
        if vwap is None:
            raise InsufficientDepthError(
                exchange,
                float(quantity),
                float(sum(order_book_side.values()))
            )

        return vwap

    def is_ready(self) -> bool:
        """
        检查订单簿是否就绪

        Returns:
            两个交易所的订单簿都已加载且有效
        """
        return (
            self.lighter_order_book is not None
            and self.lighter_order_book.is_valid
            and self.extended_order_book is not None
            and self.extended_order_book.is_valid
        )

    async def start(self) -> None:
        """
        启动 WebSocket 连接

        注意：此方法是框架方法，实际的 WebSocket 连接
        应在子类或外部组件中实现，通过调用更新方法来更新订单簿。
        """
        self._running = True
        logger.info(f"订单簿管理器已启动，交易对: {self.symbol}")

    async def stop(self) -> None:
        """停止 WebSocket 连接"""
        self._running = False
        self.lighter_connected = False
        self.extended_connected = False
        logger.info("订单簿管理器已停止")

    def register_update_handler(self, handler: Callable) -> None:
        """
        注册订单簿更新回调函数

        Args:
            handler: 回调函数，签名为 async def handler(exchange: str)
        """
        self._update_handlers.append(handler)

    async def _notify_update_handlers(self, exchange: str) -> None:
        """通知所有更新处理器"""
        for handler in self._update_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(exchange)
                else:
                    handler(exchange)
            except Exception as e:
                logger.error(f"更新处理器错误 ({exchange}): {e}")

    def update_lighter_order_book(
        self,
        bids: Dict[Decimal, Decimal],
        asks: Dict[Decimal, Decimal],
        sequence: int,
        is_snapshot: bool = False
    ) -> None:
        """
        更新 Lighter 订单簿

        Args:
            bids: 买单 {价格: 数量}
            asks: 卖单 {价格: 数量}
            sequence: 序列号
            is_snapshot: 是否为快照（完整替换）
        """
        try:
            # 验证序列号
            if not is_snapshot:
                is_valid, error_msg = validate_order_book_integrity(
                    sequence,
                    self.lighter_last_sequence,
                    "lighter"
                )
                if not is_valid:
                    logger.warning(f"Lighter 订单簿序列号错误: {error_msg}")
                    # 标记需要重新获取快照
                    self._request_snapshot("lighter")
                    return

            # 更新或创建订单簿
            if is_snapshot or self.lighter_order_book is None:
                self.lighter_order_book = OrderBook(
                    exchange="lighter",
                    symbol=self.symbol,
                    bids=bids.copy(),
                    asks=asks.copy(),
                    last_update=datetime.now(),
                    sequence=sequence,
                    is_valid=True
                )
            else:
                # 增量更新
                if self.lighter_order_book:
                    self.lighter_order_book.bids.update(bids)
                    self.lighter_order_book.asks.update(asks)
                    # 移除数量为 0 的层级
                    self.lighter_order_book.bids = {
                        p: q for p, q in self.lighter_order_book.bids.items() if q > 0
                    }
                    self.lighter_order_book.asks = {
                        p: q for p, q in self.lighter_order_book.asks.items() if q > 0
                    }
                    self.lighter_order_book.last_update = datetime.now()
                    self.lighter_order_book.sequence = sequence

            self.lighter_last_sequence = sequence
            self.lighter_connected = True

            # 验证订单簿
            if self.lighter_order_book and not self.lighter_order_book.validate():
                logger.warning("Lighter 订单簿验证失败")
                self.lighter_order_book.is_valid = False

            logger.debug(f"Lighter 订单簿已更新，序列号: {sequence}")

        except Exception as e:
            logger.error(f"更新 Lighter 订单簿失败: {e}")

    def update_extended_order_book(
        self,
        bids: Dict[Decimal, Decimal],
        asks: Dict[Decimal, Decimal],
        sequence: int,
        is_snapshot: bool = False
    ) -> None:
        """
        更新 Extended 订单簿

        Args:
            bids: 买单 {价格: 数量}
            asks: 卖单 {价格: 数量}
            sequence: 序列号
            is_snapshot: 是否为快照（完整替换）
        """
        try:
            # 验证序列号
            if not is_snapshot:
                is_valid, error_msg = validate_order_book_integrity(
                    sequence,
                    self.extended_last_sequence,
                    "extended"
                )
                if not is_valid:
                    logger.warning(f"Extended 订单簿序列号错误: {error_msg}")
                    # 标记需要重新获取快照
                    self._request_snapshot("extended")
                    return

            # 更新或创建订单簿
            if is_snapshot or self.extended_order_book is None:
                self.extended_order_book = OrderBook(
                    exchange="extended",
                    symbol=self.symbol,
                    bids=bids.copy(),
                    asks=asks.copy(),
                    last_update=datetime.now(),
                    sequence=sequence,
                    is_valid=True
                )
            else:
                # 增量更新
                if self.extended_order_book:
                    self.extended_order_book.bids.update(bids)
                    self.extended_order_book.asks.update(asks)
                    # 移除数量为 0 的层级
                    self.extended_order_book.bids = {
                        p: q for p, q in self.extended_order_book.bids.items() if q > 0
                    }
                    self.extended_order_book.asks = {
                        p: q for p, q in self.extended_order_book.asks.items() if q > 0
                    }
                    self.extended_order_book.last_update = datetime.now()
                    self.extended_order_book.sequence = sequence

            self.extended_last_sequence = sequence
            self.extended_connected = True

            # 验证订单簿
            if self.extended_order_book and not self.extended_order_book.validate():
                logger.warning("Extended 订单簿验证失败")
                self.extended_order_book.is_valid = False

            logger.debug(f"Extended 订单簿已更新，序列号: {sequence}")

        except Exception as e:
            logger.error(f"更新 Extended 订单簿失败: {e}")

    def _request_snapshot(self, exchange: str) -> None:
        """
        请求重新获取快照

        当检测到序列号缺失时调用

        Args:
            exchange: "lighter" 或 "extended"
        """
        logger.warning(f"请求 {exchange} 订单簿快照")
        # 标记订单簿无效
        if exchange == "lighter" and self.lighter_order_book:
            self.lighter_order_book.is_valid = False
        elif exchange == "extended" and self.extended_order_book:
            self.extended_order_book.is_valid = False

        # TODO: 触发快照重新获取逻辑
        # 这需要与具体的 WebSocket 客户端实现配合

    def get_status(self) -> Dict:
        """
        获取订单簿管理器状态

        Returns:
            状态信息字典
        """
        return {
            "symbol": self.symbol,
            "lighter_connected": self.lighter_connected,
            "extended_connected": self.extended_connected,
            "lighter_sequence": self.lighter_last_sequence,
            "extended_sequence": self.extended_last_sequence,
            "is_ready": self.is_ready(),
            "lighter_valid": (
                self.lighter_order_book.is_valid
                if self.lighter_order_book else False
            ),
            "extended_valid": (
                self.extended_order_book.is_valid
                if self.extended_order_book else False
            ),
        }
