"""
WebSocket连接管理模块

本模块实现011-async-ws-ioc-trading的WebSocket连接管理功能，包括:
- 连接管理（Extended和Lighter）
- 订单簿频道订阅
- 本地订单簿缓存
- 心跳保活机制
- 断线检测和自动重连
"""

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from spread.config import SpreadArbConfig


class WebSocketManager:
    """
    WebSocket连接管理器

    负责与交易所建立WebSocket连接、订阅频道、接收推送并维护本地订单簿缓存。
    """

    def __init__(self, config: SpreadArbConfig, logger: Optional[logging.Logger] = None) -> None:
        """初始化WebSocket管理器

        Args:
            config: SpreadArbConfig配置对象
            logger: 日志记录器（可选）
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # WebSocket连接
        self.ws_extended: Optional[Any] = None  # Extended WebSocket连接
        self.ws_lighter: Optional[Any] = None   # Lighter WebSocket连接

        # 连接状态
        self._connected_extended = False
        self._connected_lighter = False
        self._running = False

        # 本地订单簿缓存
        self.orderbooks: Dict[str, Dict[str, Any]] = {
            'extended': {'bid': None, 'ask': None, 'bid_qty': None, 'ask_qty': None, 'timestamp': None},
            'lighter': {'bid': None, 'ask': None, 'bid_qty': None, 'ask_qty': None, 'timestamp': None}
        }

        # 订单簿回调
        self.orderbook_callback: Optional[Callable[[str, Dict], None]] = None

        # 心跳任务
        self._heartbeat_tasks: List[asyncio.Task] = []

        # 重连任务
        self._reconnect_tasks: List[asyncio.Task] = []

        # WebSocket URL配置
        self.ws_urls = {
            'extended': 'wss://api.starknet.extended.exchange/stream.extended.exchange',  # 修复: 从SDK获取正确URL
            'lighter': 'wss://mainnet.zklighter.elliot.ai/stream'
        }

        # 订阅的交易对
        self._symbol: Optional[str] = None



    async def connect_extended(self) -> None:
        """连接到Extended交易所WebSocket

        Raises:
            ConnectionError: 连接失败

        副作用:
            - 设置self.ws_extended连接对象
            - 启动心跳任务
            - 输出INFO日志
        """
        url = self.ws_urls['extended']
        self.logger.info(f"正在连接Extended WebSocket: {url}")

        try:
            # 导入websockets
            import websockets

            # 准备认证头

            self.ws_extended = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            )

            self._connected_extended = True
            self.logger.info(f"✅ Extended WebSocket连接成功")

            # 启动心跳任务
            self._heartbeat_tasks.append(
                asyncio.create_task(self._maintain_connection('extended'))
            )

            # 启动消息处理
            asyncio.create_task(self._handle_extended_messages())

        except Exception as e:
            self._connected_extended = False
            self.logger.error(f"❌ Extended WebSocket连接失败: {e}")
            raise ConnectionError(f"Extended连接失败: {e}")

    async def connect_lighter(self) -> None:
        """连接到Lighter交易所WebSocket

        Raises:
            ConnectionError: 连接失败
        """
        url = self.ws_urls['lighter']
        self.logger.info(f"正在连接Lighter WebSocket: {url}")

        try:
            # 导入websockets
            import websockets

            self.ws_lighter = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10
            )

            self._connected_lighter = True
            self.logger.info(f"✅ Lighter WebSocket连接成功")

            # 启动心跳任务
            self._heartbeat_tasks.append(
                asyncio.create_task(self._maintain_connection('lighter'))
            )

            # 启动消息处理
            asyncio.create_task(self._handle_lighter_messages())

        except Exception as e:
            self._connected_lighter = False
            self.logger.error(f"❌ Lighter WebSocket连接失败: {e}")
            raise ConnectionError(f"Lighter连接失败: {e}")

    async def connect_all(self) -> None:
        """连接所有交易所WebSocket

        副作用:
            - 并发调用connect_extended()和connect_lighter()
        """
        self._running = True

        try:
            await asyncio.gather(
                self.connect_extended(),
                self.connect_lighter()
            )
            self.logger.info("✅ 所有WebSocket连接已建立")
        except Exception as e:
            self.logger.error(f"❌ WebSocket连接失败: {e}")
            raise

    async def disconnect_all(self) -> None:
        """断开所有WebSocket连接

        副作用:
            - 取消心跳任务
            - 关闭所有连接
        """
        self._running = False

        # 取消所有任务
        for task in self._heartbeat_tasks + self._reconnect_tasks:
            if not task.done():
                task.cancel()

        # 关闭连接
        if self.ws_extended:
            await self.ws_extended.close()
            self._connected_extended = False
            self.logger.info("Extended WebSocket已断开")

        if self.ws_lighter:
            await self.ws_lighter.close()
            self._connected_lighter = False
            self.logger.info("Lighter WebSocket已断开")

    def is_connected(self, exchange: str) -> bool:
        """检查连接状态

        Args:
            exchange: 'extended' 或 'lighter'

        Returns:
            是否已连接
        """
        if exchange == 'extended':
            return self._connected_extended and self.ws_extended is not None
        elif exchange == 'lighter':
            return self._connected_lighter and self.ws_lighter is not None
        return False

    # ========================================================================
    # 订阅管理
    # ========================================================================

    async def subscribe_orderbook(self, exchange: str, symbol: str) -> None:
        """订阅订单簿频道

        Args:
            exchange: 'extended' 或 'lighter'
            symbol: 交易对，如 'ETH-USD'

        副作用:
            - 发送订阅消息
            - 设置消息回调处理器
        """
        self._symbol = symbol

        if exchange == 'extended':
            await self._subscribe_extended_orderbook(symbol)
        elif exchange == 'lighter':
            await self._subscribe_lighter_orderbook(symbol)
        else:
            raise ValueError(f"无效的exchange: {exchange}")

    async def _subscribe_extended_orderbook(self, symbol: str) -> None:
        """订阅Extended订单簿频道"""
        if not self.is_connected('extended'):
            self.logger.warning("Extended未连接，无法订阅订单簿")
            return

        # Extended订阅消息格式（根据实际API调整）
        subscribe_msg = {
            "type": "subscribe",
            "channel": "bookTicker",
            "symbol": symbol
        }

        try:
            await self.ws_extended.send(json.dumps(subscribe_msg))
            self.logger.info(f"✅ 已订阅Extended订单簿: {symbol}")
        except Exception as e:
            self.logger.error(f"❌ Extended订阅失败: {e}")

    async def _subscribe_lighter_orderbook(self, symbol: str) -> None:
        """订阅Lighter订单簿频道"""
        if not self.is_connected('lighter'):
            self.logger.warning("Lighter未连接，无法订阅订单簿")
            return

        # Lighter订阅消息格式（根据实际API调整）
        subscribe_msg = {
            "type": "subscribe",
            "channel": "bookTicker",
            "symbol": symbol,
            "market_index": self.config.contract_id
        }

        try:
            await self.ws_lighter.send(json.dumps(subscribe_msg))
            self.logger.info(f"✅ 已订阅Lighter订单簿: {symbol}")
        except Exception as e:
            self.logger.error(f"❌ Lighter订阅失败: {e}")

    def unsubscribe_all(self) -> None:
        """取消所有订阅"""
        # 实现取消订阅逻辑
        self.logger.info("已取消所有订阅")

    # ========================================================================
    # 数据获取
    # ========================================================================

    def get_orderbook(self, exchange: str) -> Optional[Dict[str, Any]]:
        """获取本地缓存的订单簿

        Args:
            exchange: 'extended' 或 'lighter'

        Returns:
            订单簿字典 {'bid': Decimal, 'ask': Decimal, 'timestamp': float}
            如果未连接返回None
        """
        if exchange not in ('extended', 'lighter'):
            return None

        return self.orderbooks.get(exchange)

    def get_orderbook_timestamp(self, exchange: str) -> Optional[float]:
        """获取订单簿时间戳

        Args:
            exchange: 'extended' 或 'lighter'

        Returns:
            时间戳（毫秒），如果未连接返回None
        """
        if exchange not in ('extended', 'lighter'):
            return None

        return self.orderbooks.get(exchange, {}).get('timestamp')

    # ========================================================================
    # 回调设置
    # ========================================================================

    def set_orderbook_callback(self, callback: Callable[[str, Dict], None]) -> None:
        """设置订单簿更新回调

        Args:
            callback: 回调函数，签名为 callback(exchange: str, orderbook: Dict)

        Example:
            def on_orderbook_update(exchange, orderbook):
                print(f"{exchange}: bid={orderbook['bid']}, ask={orderbook['ask']}")

            ws_manager.set_orderbook_callback(on_orderbook_update)
        """
        self.orderbook_callback = callback

    # ========================================================================
    # 消息处理
    # ========================================================================

    async def _handle_extended_messages(self) -> None:
        """处理Extended WebSocket消息"""
        try:
            async for raw in self.ws_extended:
                try:
                    msg = json.loads(raw)

                    # 处理ping消息
                    if msg.get("type") == "PING" or raw == "ping":
                        await self.ws_extended.send("pong")
                        continue

                    # 处理订单簿更新
                    if msg.get("channel") == "bookTicker" or msg.get("type") == "bookTicker":
                        self._process_extended_orderbook(msg)

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    self.logger.error(f"处理Extended消息错误: {e}")

        except Exception as e:
            self.logger.error(f"Extended消息处理循环异常: {e}")
            self._connected_extended = False
            # 触发重连
            if self._running:
                asyncio.create_task(self._auto_reconnect('extended'))

    async def _handle_lighter_messages(self) -> None:
        """处理Lighter WebSocket消息"""
        try:
            async for raw in self.ws_lighter:
                try:
                    msg = json.loads(raw)

                    # 处理ping消息
                    if msg.get("type") == "PING" or raw == "ping":
                        await self.ws_lighter.send("pong")
                        continue

                    # 处理订单簿更新
                    if msg.get("channel") == "bookTicker" or msg.get("type") == "bookTicker":
                        self._process_lighter_orderbook(msg)

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    self.logger.error(f"处理Lighter消息错误: {e}")

        except Exception as e:
            self.logger.error(f"Lighter消息处理循环异常: {e}")
            self._connected_lighter = False
            # 触发重连
            if self._running:
                asyncio.create_task(self._auto_reconnect('lighter'))

    def _process_extended_orderbook(self, msg: Dict[str, Any]) -> None:
        """处理Extended订单簿数据"""
        try:
            # 解析价格（根据实际API格式调整）
            bid_price = Decimal(str(msg.get('b', msg.get('bidPrice', 0))))
            ask_price = Decimal(str(msg.get('a', msg.get('askPrice', 0))))
            bid_qty = Decimal(str(msg.get('B', msg.get('bidQty', 0))))
            ask_qty = Decimal(str(msg.get('A', msg.get('askQty', 0))))

            # 获取时间戳（交易所提供或本地时间）
            timestamp = msg.get('E', msg.get('time', time.time() * 1000))
            if isinstance(timestamp, (int, float)):
                timestamp = float(timestamp)
            else:
                timestamp = time.time() * 1000

            # 更新本地缓存
            self.orderbooks['extended'] = {
                'bid': bid_price,
                'ask': ask_price,
                'bid_qty': bid_qty,
                'ask_qty': ask_qty,
                'timestamp': timestamp
            }

            # 触发回调
            if self.orderbook_callback:
                self.orderbook_callback('extended', self.orderbooks['extended'])

            # 调试日志
            if self.config.log_all_timestamps:
                self.logger.debug(f"Extended订单簿更新: bid={bid_price}, ask={ask_price}")

        except Exception as e:
            self.logger.error(f"处理Extended订单簿数据错误: {e}")

    def _process_lighter_orderbook(self, msg: Dict[str, Any]) -> None:
        """处理Lighter订单簿数据"""
        try:
            # 解析价格（根据实际API格式调整）
            bid_price = Decimal(str(msg.get('b', msg.get('bidPrice', 0))))
            ask_price = Decimal(str(msg.get('a', msg.get('askPrice', 0))))
            bid_qty = Decimal(str(msg.get('B', msg.get('bidQty', 0))))
            ask_qty = Decimal(str(msg.get('A', msg.get('askQty', 0))))

            # 获取时间戳
            timestamp = msg.get('E', msg.get('time', time.time() * 1000))
            if isinstance(timestamp, (int, float)):
                timestamp = float(timestamp)
            else:
                timestamp = time.time() * 1000

            # 更新本地缓存
            self.orderbooks['lighter'] = {
                'bid': bid_price,
                'ask': ask_price,
                'bid_qty': bid_qty,
                'ask_qty': ask_qty,
                'timestamp': timestamp
            }

            # 触发回调
            if self.orderbook_callback:
                self.orderbook_callback('lighter', self.orderbooks['lighter'])

            # 调试日志
            if self.config.log_all_timestamps:
                self.logger.debug(f"Lighter订单簿更新: bid={bid_price}, ask={ask_price}")

        except Exception as e:
            self.logger.error(f"处理Lighter订单簿数据错误: {e}")

    # ========================================================================
    # 心跳保活
    # ========================================================================

    async def _maintain_connection(self, exchange: str) -> None:
        """保持WebSocket连接活跃

        Args:
            exchange: 'extended' 或 'lighter'
        """
        interval = 30  # 30秒心跳间隔

        while self._running and self.is_connected(exchange):
            try:
                ws = self.ws_extended if exchange == 'extended' else self.ws_lighter

                # 发送应用层心跳
                ping_msg = {"type": "ping", "ts": time.time()}
                await ws.send(json.dumps(ping_msg))

                await asyncio.sleep(interval)

            except Exception as e:
                self.logger.warning(f"{exchange}心跳失败: {e}")
                if exchange == 'extended':
                    self._connected_extended = False
                else:
                    self._connected_lighter = False
                break

    # ========================================================================
    # 断线重连
    # ========================================================================

    async def _auto_reconnect(self, exchange: str) -> None:
        """自动重连逻辑

        Args:
            exchange: 'extended' 或 'lighter'
        """
        retry_delay = 1  # 初始1秒
        max_delay = 60   # 最大60秒

        while self._running:
            try:
                self.logger.info(f"正在重连{exchange}... ({retry_delay}秒后)")

                await asyncio.sleep(retry_delay)

                if exchange == 'extended':
                    await self.connect_extended()
                    # 重新订阅
                    if self._symbol:
                        await self._subscribe_extended_orderbook(self._symbol)
                else:
                    await self.connect_lighter()
                    # 重新订阅
                    if self._symbol:
                        await self._subscribe_lighter_orderbook(self._symbol)

                # 重连成功，重置延迟
                retry_delay = 1
                self.logger.info(f"✅ {exchange}重连成功")
                break

            except Exception as e:
                self.logger.warning(f"❌ {exchange}重连失败，{retry_delay}秒后重试: {e}")
                retry_delay = min(retry_delay * 2, max_delay)
