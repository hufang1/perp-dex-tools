"""
订单管理器 - 负责 Extended 端的订单操作
"""

import logging
import time
import asyncio
from decimal import Decimal
from typing import Dict, Any, Optional

from .config import SpreadArbConfig


class SpreadOrderManager:
    """Extended 订单管理器"""
    
    def __init__(
        self,
        config: SpreadArbConfig,
        extended_client,  # ExtendedClient 实例
    ):
        """
        初始化订单管理器
        
        Args:
            config: 配置对象
            extended_client: Extended 客户端实例
        """
        self.config = config
        self.extended_client = extended_client
        self.logger = logging.getLogger("OrderManager")
        
        # 当前订单状态跟踪
        self.current_order_id: Optional[str] = None
        self.current_order_status: Optional[str] = None
        self.filled_quantity: Decimal = Decimal('0')
        self.filled_price: Decimal = Decimal('0')
    
    async def place_spread_maker_order(
        self,
        side: str,
        price: Decimal,
        quantity: Decimal
    ) -> Dict[str, Any]:
        """
        在 Extended 下价差 Maker 单
        
        Args:
            side: 'buy' or 'sell'
            price: 挂单价格
            quantity: 下单数量 (币数)
        
        Returns:
            {
                'success': bool,
                'order_id': str,
                'price': Decimal,
                'quantity': Decimal,
                'side': str,
                'error': str (如果失败)
            }
        """
        self.logger.info(
            f"[Extended] 下 {side.upper()} Maker 单: "
            f"{quantity:.4f} @ {price:.2f}"
        )
        
        # 重置状态
        self.current_order_status = None
        self.filled_quantity = Decimal('0')
        self.filled_price = Decimal('0')
        
        try:
            # 使用 Extended 客户端下单
            order_result = await self.extended_client.place_open_order(
                contract_id=self.extended_client.contract_id,
                quantity=quantity,
                direction=side
            )
            
            if not order_result.success:
                self.logger.error(f"下单失败: {order_result.error_message}")
                return {
                    'success': False,
                    'error': order_result.error_message
                }
            
            self.current_order_id = order_result.order_id
            
            self.logger.info(
                f"✅ 订单已提交: {order_result.order_id} "
                f"@ {order_result.price:.2f}"
            )
            
            return {
                'success': True,
                'order_id': order_result.order_id,
                'price': order_result.price,
                'quantity': quantity,
                'side': side
            }
            
        except Exception as e:
            self.logger.error(f"下单异常: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def wait_for_fill(
        self,
        order_id: str,
        timeout: int,
        allow_partial: bool = True
    ) -> Dict[str, Any]:
        """
        等待订单成交
        
        Args:
            order_id: 订单 ID
            timeout: 超时时间 (秒)
            allow_partial: 是否允许部分成交
        
        Returns:
            {
                'status': 'FILLED' | 'PARTIAL' | 'TIMEOUT' | 'CANCELLED',
                'filled_quantity': Decimal,
                'filled_price': Decimal,
                'remaining': Decimal
            }
        """
        start_time = time.time()
        check_interval = 0.5  # 检查间隔 500ms
        
        self.logger.info(f"等待订单成交: {order_id} (超时 {timeout}秒)")
        
        while time.time() - start_time < timeout:
            # 检查订单状态 (通过 WebSocket 回调更新)
            if self.current_order_status == 'FILLED':
                self.logger.info(
                    f"✅ 订单完全成交: {self.filled_quantity:.4f} @ {self.filled_price:.2f}"
                )
                return {
                    'status': 'FILLED',
                    'filled_quantity': self.filled_quantity,
                    'filled_price': self.filled_price,
                    'remaining': Decimal('0')
                }
            
            if self.current_order_status == 'PARTIALLY_FILLED' and allow_partial:
                # 部分成交且允许部分成交
                if self.filled_quantity > 0:
                    self.logger.info(
                        f"⚡ 订单部分成交: {self.filled_quantity:.4f} @ {self.filled_price:.2f}"
                    )
                    return {
                        'status': 'PARTIAL',
                        'filled_quantity': self.filled_quantity,
                        'filled_price': self.filled_price,
                        'remaining': self.config.order_quantity_usdt - self.filled_quantity
                    }
            
            if self.current_order_status in ['CANCELLED', 'CANCELED']:
                self.logger.warning(f"❌ 订单已取消")
                return {
                    'status': 'CANCELLED',
                    'filled_quantity': self.filled_quantity,
                    'filled_price': self.filled_price if self.filled_price > 0 else Decimal('0'),
                    'remaining': self.config.order_quantity_usdt - self.filled_quantity
                }
            
            await asyncio.sleep(check_interval)
        
        # 超时
        self.logger.warning(
            f"⏰ 订单等待超时: 已成交 {self.filled_quantity:.4f}"
        )
        return {
            'status': 'TIMEOUT',
            'filled_quantity': self.filled_quantity,
            'filled_price': self.filled_price if self.filled_price > 0 else Decimal('0'),
            'remaining': self.config.order_quantity_usdt - self.filled_quantity
        }
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        取消订单
        
        Args:
            order_id: 订单 ID
        
        Returns:
            是否成功取消
        """
        try:
            self.logger.info(f"取消订单: {order_id}")
            
            result = await self.extended_client.cancel_order(order_id)
            
            if result.success:
                self.logger.info(f"✅ 订单已取消: {order_id}")
                return True
            else:
                self.logger.error(f"取消订单失败: {result.error_message}")
                return False
                
        except Exception as e:
            self.logger.error(f"取消订单异常: {e}")
            return False
    
    def update_order_status(self, order_data: Dict[str, Any]):
        """
        更新订单状态 (由 WebSocket 回调调用)
        
        Args:
            order_data: 订单数据
                {
                    'order_id': str,
                    'status': str,
                    'filled_size': Decimal,
                    'price': Decimal,
                    ...
                }
        """
        order_id = order_data.get('order_id')
        
        # 只处理当前订单
        if order_id != self.current_order_id:
            return
        
        self.current_order_status = order_data.get('status')
        
        filled_size = Decimal(str(order_data.get('filled_size', 0)))
        if filled_size > 0:
            self.filled_quantity = filled_size
            self.filled_price = Decimal(str(order_data.get('price', 0)))
        
        self.logger.debug(
            f"订单状态更新: {order_id} -> {self.current_order_status} "
            f"已成交: {self.filled_quantity:.4f}"
        )
