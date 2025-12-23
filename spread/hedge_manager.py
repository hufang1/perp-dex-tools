"""
对冲管理器 - 负责 Lighter 端的对冲操作
"""

import logging
import asyncio
from decimal import Decimal
from typing import Dict, Any

from .config import SpreadArbConfig


class HedgeManager:
    """Lighter 对冲管理器"""
    
    def __init__(
        self,
        config: SpreadArbConfig,
        lighter_client  # LighterClient 实例
    ):
        """
        初始化对冲管理器
        
        Args:
            config: 配置对象
            lighter_client: Lighter 客户端实例
        """
        self.config = config
        self.lighter_client = lighter_client
        self.logger = logging.getLogger("HedgeManager")
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 1  # 秒
    
    async def execute_hedge(
        self,
        side: str,           # 'buy' or 'sell'
        quantity: Decimal,   # 对冲数量 (币数)
        expected_price: Decimal  # 预期成交价格
    ) -> Dict[str, Any]:
        """
        执行 Lighter 对冲
        
        策略:
        1. 使用市价单快速成交
        2. 检查滑点是否在容忍范围内
        3. 最多重试 3 次
        
        Args:
            side: 'buy' 或 'sell'
            quantity: 对冲数量
            expected_price: 预期成交价格 (用于计算滑点)
        
        Returns:
            {
                'success': bool,
                'order_id': str,
                'filled_price': Decimal,
                'filled_quantity': Decimal,
                'slippage': Decimal,  # 滑点率
                'error': str (如果失败)
            }
        """
        for attempt in range(self.max_retries):
            try:
                self.logger.info(
                    f"[Lighter] 对冲 {side.upper()}: "
                    f"{quantity:.4f} @ ~{expected_price:.2f} "
                    f"(尝试 {attempt + 1}/{self.max_retries})"
                )
                
                # 下市价单 (使用 Lighter 客户端的限价单功能)
                # 设置一个极端价格确保成交
                if side == 'buy':
                    # 买单: 价格设置为预期价格的 1.01 倍
                    limit_price = expected_price * Decimal('1.01')
                else:
                    # 卖单: 价格设置为预期价格的 0.99 倍
                    limit_price = expected_price * Decimal('0.99')
                
                # 下单
                order_result = await self.lighter_client.place_limit_order(
                    contract_id=self.lighter_client.contract_id,
                    quantity=quantity,
                    price=limit_price,
                    side=side
                )
                
                if not order_result.success:
                    raise Exception(f"下单失败: {order_result.error_message}")
                
                # 等待成交确认
                await asyncio.sleep(0.5)
                
                # 获取订单信息
                order_info = await self.lighter_client.get_order_info(
                    order_result.order_id
                )
                
                if order_info is None:
                    raise Exception("无法获取订单信息")
                
                if order_info.status != 'FILLED':
                    raise Exception(f"订单未成交: {order_info.status}")
                
                filled_price = order_info.price
                filled_quantity = order_info.filled_size
                
                # 计算滑点
                if side == 'buy':
                    slippage = (filled_price - expected_price) / expected_price
                else:
                    slippage = (expected_price - filled_price) / expected_price
                
                # 记录滑点
                if slippage > self.config.slippage_tolerance:
                    self.logger.warning(
                        f"⚠️ 滑点较大: {slippage:.4%} > {self.config.slippage_tolerance:.4%}"
                    )
                else:
                    self.logger.info(f"✅ 滑点: {slippage:.4%}")
                
                self.logger.info(
                    f"✅ Lighter 对冲完成: {filled_quantity:.4f} @ {filled_price:.2f}"
                )
                
                return {
                    'success': True,
                    'order_id': order_result.order_id,
                    'filled_price': filled_price,
                    'filled_quantity': filled_quantity,
                    'slippage': slippage
                }
                
            except Exception as e:
                self.logger.error(f"对冲尝试 {attempt + 1} 失败: {e}")
                
                if attempt < self.max_retries - 1:
                    self.logger.info(f"等待 {self.retry_delay} 秒后重试...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    self.logger.error("❌ 对冲失败,已达最大重试次数")
                    return {
                        'success': False,
                        'filled_quantity': Decimal('0'),
                        'error': str(e)
                    }
        
        # 不应该到达这里
        return {
            'success': False,
            'filled_quantity': Decimal('0'),
            'error': '未知错误'
        }
