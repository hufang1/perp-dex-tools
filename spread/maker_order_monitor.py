"""
Extended Maker订单监控器模块

负责：
1. 监听Extended WebSocket订单状态更新
2. 处理订单状态变化（NEW, PARTIALLY_FILLED, FILLED, CANCELED）
3. 跟踪订单成交数量和均价
4. 提供订单事件回调接口
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional, Callable, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from models import MakerOrder

from models import BotState

logger = logging.getLogger(__name__)


class MakerOrderMonitor:
    """
    Extended Maker订单监控器

    监听Extended WebSocket订单状态更新并跟踪订单状态。

    使用方式：
    1. 创建监控器实例并设置回调函数
    2. 在订单创建后调用start_monitoring()开始监控
    3. WebSocket更新会触发相应回调函数
    4. 调用stop_monitoring()停止监控

    Attributes:
        order: 当前监控的Maker订单
        on_order_filled: 订单成交回调
        on_order_partially_filled: 订单部分成交回调
        on_order_canceled: 订单取消回调
        on_cancellation_initiated: 取消订单发起回调 (003-spreading-improvements)
        on_cancellation_verified: 取消订单验证成功回调 (003-spreading-improvements)
        on_cancellation_failed: 取消订单失败回调 (003-spreading-improvements)
    """

    def __init__(self):
        """初始化Maker订单监控器"""
        self._order: Optional['MakerOrder'] = None
        self._monitoring = False
        self._lock = asyncio.Lock()

        # Callbacks
        self.on_order_filled: Optional[Callable[['MakerOrder'], None]] = None
        self.on_order_partially_filled: Optional[Callable[['MakerOrder'], None]] = None
        self.on_order_canceled: Optional[Callable[['MakerOrder'], None]] = None

        # ========== 新增回调 (003-spreading-improvements): 取消订单监控 ==========
        self.on_cancellation_initiated: Optional[Callable[[str, str], None]] = None
        self.on_cancellation_verified: Optional[Callable[[str, int, float], None]] = None
        self.on_cancellation_failed: Optional[Callable[[str, str, str], None]] = None

        # 取消状态跟踪
        self._cancellation_in_progress = False
        self._cancellation_start_time: Optional[datetime] = None

    def start_monitoring(self, order: 'MakerOrder') -> None:
        """
        开始监控订单

        Args:
            order: 要监控的Maker订单
        """
        self._order = order
        self._monitoring = True
        logger.info(
            f"📊 开始监控Maker订单: {order.order_id} | "
            f"{order.side.upper()} {order.quantity} @ {order.price}"
        )

    def stop_monitoring(self) -> None:
        """停止监控订单"""
        if self._monitoring and self._order:
            logger.info(
                f"📊 停止监控Maker订单: {self._order.order_id} | "
                f"状态: {self._order.status} | "
                f"成交: {self._order.filled_quantity}/{self._order.quantity}"
            )
        self._monitoring = False
        self._order = None

    def is_monitoring(self) -> bool:
        """是否正在监控"""
        return self._monitoring and self._order is not None

    # ========== 新增方法 (003-spreading-improvements): 取消订单监控支持 ==========

    def notify_cancellation_initiated(self, order_id: str, exchange: str) -> None:
        """
        通知取消订单已发起

        当开始取消订单时调用，用于通知监控系统取消操作已开始。

        Args:
            order_id: 要取消的订单ID
            exchange: 交易所名称
        """
        self._cancellation_in_progress = True
        self._cancellation_start_time = datetime.now()

        logger.info(
            f"🔕 取消订单已发起 | ID={order_id[:12]}... | exchange={exchange}"
        )

        if self.on_cancellation_initiated:
            self.on_cancellation_initiated(order_id, exchange)

    def notify_cancellation_verified(
        self,
        order_id: str,
        attempts: int,
        total_time: float
    ) -> None:
        """
        通知取消订单验证成功

        当订单取消验证成功时调用。

        Args:
            order_id: 已取消的订单ID
            attempts: 尝试次数
            total_time: 总耗时（秒）
        """
        self._cancellation_in_progress = False

        logger.info(
            f"✅ 取消订单验证成功 | ID={order_id[:12]}... | "
            f"尝试={attempts}次 | 耗时={total_time:.1f}秒"
        )

        if self.on_cancellation_verified:
            self.on_cancellation_verified(order_id, attempts, total_time)

    def notify_cancellation_failed(
        self,
        order_id: str,
        final_status: str,
        error_message: str
    ) -> None:
        """
        通知取消订单失败

        当订单取消失败时调用。

        Args:
            order_id: 订单ID
            final_status: 最终状态
            error_message: 错误信息
        """
        self._cancellation_in_progress = False

        logger.error(
            f"❌ 取消订单失败 | ID={order_id[:12]}... | "
            f"状态={final_status} | 错误={error_message}"
        )

        if self.on_cancellation_failed:
            self.on_cancellation_failed(order_id, final_status, error_message)

    def is_cancellation_in_progress(self) -> bool:
        """
        是否正在进行取消操作

        Returns:
            True if 取消操作正在进行
        """
        return self._cancellation_in_progress

    def get_cancellation_duration(self) -> Optional[float]:
        """
        获取取消操作持续时间（秒）

        Returns:
            取消操作持续时间，如果没有取消操作则返回None
        """
        if self._cancellation_start_time is None:
            return None
        return (datetime.now() - self._cancellation_start_time).total_seconds()

    # ========== 原有方法 ==========

    def get_order(self) -> Optional['MakerOrder']:
        """获取当前监控的订单"""
        return self._order

    async def handle_order_update(self, order_data: Dict[str, Any]) -> None:
        """
        处理WebSocket订单更新

        Args:
            order_data: WebSocket订单数据字典
        """
        if not self._monitoring or not self._order:
            return

        # Check if this update is for our monitored order
        # 确保 order_id 是字符串类型进行比较（Extended SDK 可能返回整数）
        order_id = order_data.get('id')
        if str(order_id) != str(self._order.order_id):
            # 订单 ID 不匹配，跳过此更新
            logger.debug(
                f"订单 ID 不匹配 | 收到: {order_id} ({type(order_id).__name__}) | "
                f"监控中: {self._order.order_id} ({type(self._order.order_id).__name__})"
            )
            return

        async with self._lock:
            # Store old status for comparison
            old_status = self._order.status
            old_filled = self._order.filled_quantity

            # Update order from WebSocket data
            self._order.update_from_websocket(order_data)

            # Log state changes
            new_status = self._order.status
            new_filled = self._order.filled_quantity

            # Status changed
            if new_status != old_status:
                logger.info(
                    f"📊 Maker订单状态变化: {self._order.order_id} | "
                    f"{old_status} -> {new_status}"
                )

            # Filled quantity changed
            if new_filled != old_filled:
                logger.info(
                    f"✅ Maker订单成交更新: {self._order.order_id} | "
                    f"成交数量: {old_filled} -> {new_filled} | "
                    f"成交均价: {self._order.avg_fill_price}"
                )

            # Trigger callbacks based on order state
            await self._trigger_callbacks(old_status, old_filled)

    async def _trigger_callbacks(self, old_status: str, old_filled: Decimal) -> None:
        """
        触发相应的回调函数

        Args:
            old_status: 旧状态
            old_filled: 旧成交数量
        """
        if not self._order:
            return

        # Fully filled callback
        if self._order.is_fully_filled and old_status != 'FILLED':
            logger.info(
                f"✅ Maker订单完全成交: {self._order.order_id} | "
                f"成交数量: {self._order.filled_quantity} | "
                f"成交均价: {self._order.avg_fill_price}"
            )
            if self.on_order_filled:
                self.on_order_filled(self._order)

        # Partially filled callback
        elif self._order.is_partially_filled:
            new_fill = self._order.filled_quantity - old_filled
            if new_fill > 0:
                logger.info(
                    f"✅ Maker订单部分成交: {self._order.order_id} | "
                    f"新增成交: {new_fill} | "
                    f"累计成交: {self._order.filled_quantity}/{self._order.quantity} | "
                    f"成交均价: {self._order.avg_fill_price}"
                )
                if self.on_order_partially_filled:
                    self.on_order_partially_filled(self._order)

        # Canceled callback
        elif self._order.is_canceled and old_status not in ['CANCELED', 'CANCELLED']:
            logger.info(
                f"❌ Maker订单已取消: {self._order.order_id} | "
                f"成交数量: {self._order.filled_quantity}/{self._order.quantity} | "
                f"剩余数量: {self._order.remaining_quantity}"
            )
            if self.on_order_canceled:
                self.on_order_canceled(self._order)

    def get_status_summary(self) -> Optional[Dict[str, Any]]:
        """
        获取订单状态摘要

        Returns:
            订单状态摘要字典，如果没有监控订单则返回None
        """
        if not self._order:
            return None

        return {
            'order_id': self._order.order_id,
            'side': self._order.side,
            'price': str(self._order.price),
            'quantity': str(self._order.quantity),
            'status': self._order.status,
            'filled_quantity': str(self._order.filled_quantity),
            'remaining_quantity': str(self._order.remaining_quantity),
            'avg_fill_price': str(self._order.avg_fill_price),
            'is_opening': self._order.is_opening,
            'created_at': self._order.created_at.isoformat(),
            'updated_at': self._order.updated_at.isoformat(),
        }


# Convenience function for creating MakerOrder from order result
def create_maker_order_from_result(
    order_id: str,
    price: Decimal,
    quantity: Decimal,
    side: str,
    is_opening: bool = True,
    context_id: Optional[str] = None
) -> 'MakerOrder':
    """
    从订单结果创建MakerOrder对象

    Args:
        order_id: 订单ID
        price: 订单价格
        quantity: 订单数量
        side: 订单方向 (buy/sell)
        is_opening: 是否为开仓订单

    Returns:
        MakerOrder对象
    """
    from models import MakerOrder
    return MakerOrder(
        order_id=order_id,
        price=price,
        quantity=quantity,
        side=side.lower(),
        is_opening=is_opening,
        context_id=context_id
    )
