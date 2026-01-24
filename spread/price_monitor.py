"""
实时价差和价格监控器模块

负责：
1. 监控Extended订单簿BBO价格（best bid/ask）
2. 监控Lighter订单簿BBO价格
3. 计算平仓口径价差（Lighter买价 - Extended卖价）
4. 检测价格偏离（价格位置优化）
5. 检测价差保护触发条件
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional, Callable, Dict, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PriceSnapshot:
    """
    价格快照数据类

    Attributes:
        timestamp: 快照时间戳
        ext_bid: Extended最佳买价
        ext_ask: Extended最佳卖价
        lig_bid: Lighter最佳买价
        lig_ask: Lighter最佳卖价
        spread_abs: 绝对价差
        spread_pct: 百分比价差
    """
    timestamp: datetime = field(default_factory=datetime.now)
    ext_bid: Decimal = field(default_factory=lambda: Decimal('0'))
    ext_ask: Decimal = field(default_factory=lambda: Decimal('0'))
    lig_bid: Decimal = field(default_factory=lambda: Decimal('0'))
    lig_ask: Decimal = field(default_factory=lambda: Decimal('0'))
    spread_abs: Decimal = field(default_factory=lambda: Decimal('0'))
    spread_pct: Decimal = field(default_factory=lambda: Decimal('0'))

    def is_valid(self) -> bool:
        """价格数据是否有效"""
        return (
            self.ext_bid > 0 and self.ext_ask > 0 and
            self.lig_bid > 0 and self.lig_ask > 0
        )


@dataclass
class SpreadConfig:
    """
    价差配置数据类

    Attributes:
        open_threshold: 开仓阈值（默认0.09%，使用开仓口径）
        close_threshold: 平仓利润阈值（默认0.06%）
        monitor_interval: 监控间隔（默认0.5秒）
        price_deviation_threshold: 价格偏离阈值（默认1 tick）
    """
    open_threshold: Decimal = field(default_factory=lambda: Decimal('0.0009'))  # 0.09%
    close_threshold: Decimal = field(default_factory=lambda: Decimal('0.0006'))  # 0.06%
    monitor_interval: float = 0.5  # seconds
    price_deviation_threshold: int = 1  # ticks


class PriceMonitor:
    """
    实时价差和价格监控器

    监控Extended和Lighter的订单簿价格，计算平仓口径价差，
    检测价格偏离和价差保护触发条件。

    使用方式：
    1. 创建监控器实例并设置配置
    2. 设置回调函数（价差保护、价格偏离）
    3. 调用start_monitoring()开始监控
    4. 通过update_ext_orderbook()和update_lig_orderbook()更新价格
    5. 调用stop_monitoring()停止监控

    Attributes:
        config: 价差配置
        current_snapshot: 当前价格快照
        on_spread_protection: 开仓价差保护触发回调
        on_price_deviation: 价格偏离回调
    """

    def __init__(self, config: Optional[SpreadConfig] = None):
        """
        初始化价格监控器

        Args:
            config: 价差配置，如果为None则使用默认配置
        """
        self.config = config or SpreadConfig()
        self.current_snapshot = PriceSnapshot()
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_check_time: float = 0

        # Callbacks
        self.on_spread_protection: Optional[Callable[[PriceSnapshot], None]] = None
        self.on_price_deviation: Optional[Callable[[str, Decimal, Decimal], None]] = None

        # Orderbook data caches
        self._ext_orderbook: Optional[Dict[str, Any]] = None
        self._lig_orderbook: Optional[Dict[str, Any]] = None
        self._tick_size: Decimal = Decimal('0.01')  # Default, will be updated

    def set_tick_size(self, tick_size: Decimal) -> None:
        """设置tick大小（用于价格偏离检测）"""
        self._tick_size = tick_size

    def set_config(self, config: SpreadConfig) -> None:
        """更新价差配置"""
        self.config = config

    async def update_ext_orderbook(self, orderbook: Dict[str, Any]) -> None:
        """
        更新Extended订单簿数据

        Args:
            orderbook: Extended订单簿数据字典
        """
        async with self._lock:
            self._ext_orderbook = orderbook
            await self._update_snapshot()

    async def update_lig_orderbook(self, orderbook: Dict[str, Any]) -> None:
        """
        更新Lighter订单簿数据

        Args:
            orderbook: Lighter订单簿数据字典
        """
        async with self._lock:
            self._lig_orderbook = orderbook
            await self._update_snapshot()

    async def _update_snapshot(self) -> None:
        """更新价格快照"""
        # Extract BBO prices from orderbooks
        ext_bid = Decimal('0')
        ext_ask = Decimal('0')
        lig_bid = Decimal('0')
        lig_ask = Decimal('0')

        if self._ext_orderbook:
            bids = self._ext_orderbook.get('bid', [])
            asks = self._ext_orderbook.get('ask', [])
            if bids and len(bids) > 0:
                ext_bid = Decimal(str(bids[0].get('p', '0')))
            if asks and len(asks) > 0:
                ext_ask = Decimal(str(asks[0].get('p', '0')))

        if self._lig_orderbook:
            bids = self._lig_orderbook.get('bids', {})
            asks = self._lig_orderbook.get('asks', {})
            if bids:
                # Lighter uses dict format: {price: quantity}
                best_bid_price = max(bids.keys(), key=lambda x: Decimal(x))
                lig_bid = Decimal(best_bid_price)  # 修复：应该是 lig_bid
            if asks:
                best_ask_price = min(asks.keys(), key=lambda x: Decimal(x))
                lig_ask = Decimal(best_ask_price)

        # 计算平仓口径价差: (lig_ask - ext_bid) / ext_bid
        spread_abs = Decimal('0')
        spread_pct = Decimal('0')
        if ext_bid > 0 and lig_ask > 0:
            spread_abs = lig_ask - ext_bid
            spread_pct = (spread_abs / ext_bid) if ext_bid > 0 else Decimal('0')

        # Update snapshot
        self.current_snapshot = PriceSnapshot(
            ext_bid=ext_bid,
            ext_ask=ext_ask,
            lig_bid=lig_bid,
            lig_ask=lig_ask,
            spread_abs=spread_abs,
            spread_pct=spread_pct
        )

    async def start_monitoring(self) -> None:
        """启动监控任务"""
        if self._monitoring:
            logger.warning("价格监控已在运行")
            return

        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"📊 价格监控已启动 | 间隔: {self.config.monitor_interval}秒")

    async def stop_monitoring(self) -> None:
        """停止监控任务"""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("📊 价格监控已停止")

    def is_monitoring(self) -> bool:
        """是否正在监控"""
        return self._monitoring

    async def _monitor_loop(self) -> None:
        """监控循环"""
        while self._monitoring:
            try:
                await self._check_conditions()
                await asyncio.sleep(self.config.monitor_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"价格监控循环错误: {e}")
                await asyncio.sleep(self.config.monitor_interval)

    async def _check_conditions(self) -> None:
        """检查价差保护和价格偏离条件"""
        async with self._lock:
            if not self.current_snapshot.is_valid():
                return

            current_time = asyncio.get_event_loop().time()
            self._last_check_time = current_time

            # Check spread protection
            await self._check_spread_protection()

    async def _check_spread_protection(self) -> None:
        """检查价差保护触发条件"""
        if not self.current_snapshot.is_valid():
            return

        # Check if open spread is below opening threshold
        open_spread = self._calculate_open_spread_pct()
        if open_spread is None:
            return
        if open_spread < self.config.open_threshold:
            logger.info(
                f"⚠️ 价差保护触发 | "
                f"开仓价差: {open_spread:.3%} < "
                f"开仓阈值: {self.config.open_threshold:.3%}"
            )
            if self.on_spread_protection:
                self.on_spread_protection(self.current_snapshot)

    def check_price_deviation(
        self,
        order_side: str,
        order_price: Decimal
    ) -> bool:
        """
        检查价格是否偏离最优位置

        Args:
            order_side: 订单方向 ('buy' or 'sell')
            order_price: 当前挂单价格

        Returns:
            True if price has deviated, False otherwise
        """
        if not self.current_snapshot.is_valid():
            return False

        deviation_threshold = self._tick_size * self.config.price_deviation_threshold

        if order_side.lower() == 'buy':
            # Buy order: should be at or near best bid
            best_bid = self.current_snapshot.ext_bid
            if best_bid > 0:
                deviation = abs(order_price - best_bid)
                if deviation > deviation_threshold:
                    logger.info(
                        f"⚠️ 买单价格偏离 | "
                        f"挂单价格: {order_price} | "
                        f"最佳买价: {best_bid} | "
                        f"偏离: {deviation}"
                    )
                    if self.on_price_deviation:
                        self.on_price_deviation(order_side, order_price, best_bid)
                    return True
        else:  # sell order
            # Sell order: should be at or near best ask
            best_ask = self.current_snapshot.ext_ask
            if best_ask > 0:
                deviation = abs(order_price - best_ask)
                if deviation > deviation_threshold:
                    logger.info(
                        f"⚠️ 卖单价格偏离 | "
                        f"挂单价格: {order_price} | "
                        f"最佳卖价: {best_ask} | "
                        f"偏离: {deviation}"
                    )
                    if self.on_price_deviation:
                        self.on_price_deviation(order_side, order_price, best_ask)
                    return True

        return False

    async def check_and_notify_price_deviation(
        self,
        order_side: str,
        order_price: Decimal,
        order_id: str
    ) -> bool:
        """
        检查价格偏离并通知（用于Maker订单动态重挂）

        Args:
            order_side: 订单方向 ('buy' or 'sell')
            order_price: 当前挂单价格
            order_id: 订单ID（用于日志）

        Returns:
            True if price has deviated beyond threshold, False otherwise
        """
        # 调试：检查快照是否有效
        order_id_str = str(order_id)
        # print(
        #     f"🔍 价格偏离检查入口 | "
        #     f"订单: {order_id_str[:8]} | "
        #     f"方向: {order_side} | "
        #     f"挂单价: {order_price:.2f} | "
        #     f"快照有效: {self.current_snapshot.is_valid()} | "
        #     f"ext_bid: {self.current_snapshot.ext_bid:.2f} | "
        #     f"ext_ask: {self.current_snapshot.ext_ask:.2f} | "
        #     f"tick_size: {self._tick_size}" 
        # )
  
        if not self.current_snapshot.is_valid():
            print(f"❌ 快照无效，跳过价格检查")
            return False

        deviation_threshold = self._tick_size * self.config.price_deviation_threshold

        if order_side.lower() == 'buy':
            # Buy order: should be at or near best bid
            best_bid = self.current_snapshot.ext_bid
            if best_bid > 0:
                deviation = abs(order_price - best_bid)

                if deviation > deviation_threshold:
                    print(
                        f"⚠️ 买单价格偏离！需要重挂 | "
                        f"订单: {order_id_str[:8]} | "
                        f"挂单: {order_price:.2f} | BBO: {best_bid:.2f} | "
                        f"偏离: {deviation:.2f} > 阈值: {deviation_threshold:.2f}"
                    )
                    logger.info(
                        f"⚠️ 买单价格偏离 | "
                        f"订单ID: {order_id} | "
                        f"挂单价格: {order_price} | "
                        f"最佳买价: {best_bid} | "
                        f"偏离: {deviation} | "
                        f"阈值: {deviation_threshold}"
                    )
                    if self.on_price_deviation:
                        self.on_price_deviation(order_side, order_price, best_bid)
                    return True
        else:  # sell order
            # Sell order: should be at or near best ask
            best_ask = self.current_snapshot.ext_ask
            if best_ask > 0:
                deviation = abs(order_price - best_ask)

                if deviation > deviation_threshold:
                    print(
                        f"⚠️ 卖单价格偏离！需要重挂 | "
                        f"订单: {order_id_str[:8]} | "
                        f"挂单: {order_price:.2f} | BBO: {best_ask:.2f} | "
                        f"偏离: {deviation:.2f} > 阈值: {deviation_threshold:.2f}"
                    )
                    logger.info(
                        f"⚠️ 卖单价格偏离 | "
                        f"订单ID: {order_id} | "
                        f"挂单价格: {order_price} | "
                        f"最佳卖价: {best_ask} | "
                        f"偏离: {deviation} | "
                        f"阈值: {deviation_threshold}"
                    )
                    if self.on_price_deviation:
                        self.on_price_deviation(order_side, order_price, best_ask)
                    return True

        return False

    def should_open_position(self) -> Tuple[bool, str]:
        """
        判断是否应该开仓（基于固定阈值策略）

        Returns:
            (should_open, reason): 是否应该开仓和原因说明
        """
        if not self.current_snapshot.is_valid():
            return False, "价格数据无效"

        open_spread = self._calculate_open_spread_pct()
        if open_spread is None:
            return False, "价格数据无效"
        if open_spread >= self.config.open_threshold:
            return True, (
                f"满足开仓条件: "
                f"开仓价差{open_spread:.3%} >= "
                f"阈值{self.config.open_threshold:.3%}"
            )
        else:
            return False, (
                f"不满足开仓条件: "
                f"开仓价差{open_spread:.3%} < "
                f"阈值{self.config.open_threshold:.3%}"
            )

    def should_close_position(self, open_spread: Decimal) -> Tuple[bool, str]:
        """
        判断是否应该平仓（基于固定阈值策略）

        Args:
            open_spread: 开仓时的价差

        Returns:
            (should_close, reason): 是否应该平仓和原因说明
        """
        if not self.current_snapshot.is_valid():
            return False, "价格数据无效"

        # 利润 = 开仓价差 - 当前平仓价差
        profit = open_spread - self.current_snapshot.spread_pct

        if profit > self.config.close_threshold:
            return True, (
                f"满足平仓条件: "
                f"利润{profit:.3%} > "
                f"阈值{self.config.close_threshold:.3%}"
            )
        else:
            return False, (
                f"不满足平仓条件: "
                f"利润{profit:.3%} <= "
                f"阈值{self.config.close_threshold:.3%}"
            )

    def get_current_prices(self) -> Optional[Tuple[Decimal, Decimal, Decimal, Decimal]]:
        """
        获取当前BBO价格

        Returns:
            (ext_bid, ext_ask, lig_bid, lig_ask) 或 None（如果数据无效）
        """
        if not self.current_snapshot.is_valid():
            return None
        return (
            self.current_snapshot.ext_bid,
            self.current_snapshot.ext_ask,
            self.current_snapshot.lig_bid,
            self.current_snapshot.lig_ask
        )

    def _calculate_open_spread_pct(self) -> Optional[Decimal]:
        """计算开仓口径价差: (lig_bid - ext_ask) / ext_ask"""
        if not self.current_snapshot.is_valid():
            return None
        if self.current_snapshot.ext_ask <= 0:
            return None
        return (self.current_snapshot.lig_bid - self.current_snapshot.ext_ask) / self.current_snapshot.ext_ask

    def get_current_spread(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        获取当前价差

        Returns:
            (spread_abs, spread_pct) 或 None（如果数据无效）
        """
        if not self.current_snapshot.is_valid():
            return None
        return (
            self.current_snapshot.spread_abs,
            self.current_snapshot.spread_pct
        )

    def get_status_summary(self) -> Dict[str, Any]:
        """
        获取监控状态摘要

        Returns:
            监控状态字典
        """
        return {
            'monitoring': self._monitoring,
            'monitor_interval': self.config.monitor_interval,
            'open_threshold': str(self.config.open_threshold),
            'close_threshold': str(self.config.close_threshold),
            'ext_bid': str(self.current_snapshot.ext_bid),
            'ext_ask': str(self.current_snapshot.ext_ask),
            'lig_bid': str(self.current_snapshot.lig_bid),
            'lig_ask': str(self.current_snapshot.lig_ask),
            'spread_abs': str(self.current_snapshot.spread_abs),
            'spread_pct': f"{self.current_snapshot.spread_pct:.3%}" if self.current_snapshot.is_valid() else "N/A",
            'last_check_time': self._last_check_time,
        }
