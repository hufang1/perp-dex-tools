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
        order_id = order_data.get('id')
        if order_id != self._order.order_id:
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
    is_opening: bool = True
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
        is_opening=is_opening
    )
