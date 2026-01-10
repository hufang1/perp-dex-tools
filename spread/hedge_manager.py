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
        3. 最多重试 3 次（但防止重复下单）

        修复：防止重试时重复下单导致仓位不对等

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
        # 记录第一次尝试的订单ID，防止重复下单
        first_order_id = None
        first_order_result = None

        for attempt in range(self.max_retries):
            try:
                self.logger.info(
                    f"[Lighter] 对冲 {side.upper()}: "
                    f"{quantity:.4f} @ ~{expected_price:.2f} "
                    f"(尝试 {attempt + 1}/{self.max_retries})"
                )

                # 检查Lighter订单簿深度
                orderbook = await self.lighter_client.get_orderbook()
                if orderbook:
                    book_side = 'asks' if side == 'buy' else 'bids'
                    depth = orderbook.get(book_side, {})

                    # 计算深度价值
                    total_depth_value = Decimal('0')
                    for price, size in depth.items():
                        total_depth_value += price * size

                    # 检查深度是否足够
                    if total_depth_value < self.config.min_lighter_depth_usdt:
                        error_msg = (
                            f"Lighter深度不足: {book_side}深度=${total_depth_value:.2f} "
                            f"< 最小要求${self.config.min_lighter_depth_usdt:.2f}"
                        )
                        self.logger.error(f"❌ {error_msg}")
                        return {
                            'success': False,
                            'error': error_msg,
                            'filled_quantity': Decimal('0'),
                            'filled_price': Decimal('0'),
                            'slippage': Decimal('0')
                        }

                    self.logger.info(f"✅ Lighter深度检查通过: {book_side}=${total_depth_value:.2f}")

                # 🔴 关键修复：如果不是第一次尝试，先检查是否已有订单在处理中
                if attempt > 0 and first_order_id is not None:
                    self.logger.warning(
                        f"⚠️ 重试对冲 (第{attempt + 1}次)，检查第一次下单的订单: {first_order_id}"
                    )

                    # 尝试获取第一次下单的订单信息
                    order_info = await self.lighter_client.get_order_info(first_order_id)

                    if order_info is not None:
                        self.logger.info(
                            f"✅ 找到第一次下单的订单信息: "
                            f"status={order_info.status}, "
                            f"filled_size={order_info.filled_size}"
                        )

                        # 如果订单已成交，直接返回
                        if order_info.status == 'FILLED':
                            self.logger.info(f"✅ 第一次下单已成交，无需重复下单")

                            # 计算滑点
                            filled_price = order_info.price
                            if side == 'buy':
                                slippage = (filled_price - expected_price) / expected_price
                            else:
                                slippage = (expected_price - filled_price) / expected_price

                            return {
                                'success': True,
                                'order_id': first_order_id,
                                'filled_price': filled_price,
                                'filled_quantity': order_info.filled_size,
                                'slippage': slippage
                            }
                        # 如果订单还在处理中，继续等待
                        elif order_info.status in ['OPEN', 'PENDING']:
                            self.logger.info(f"⏳ 第一次下单还在处理中，继续等待...")
                            # 继续循环，不重新下单
                            await asyncio.sleep(1)
                            continue
                    else:
                        self.logger.warning(f"⚠️ 无法获取第一次下单的订单信息")

                # 如果是第一次尝试，或者之前的订单失败了，则下单
                if attempt == 0 or first_order_result is None:
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

                    # 记录第一次下单的订单ID
                    if first_order_id is None:
                        first_order_id = order_result.order_id
                        first_order_result = order_result
                        self.logger.info(f"📝 记录第一次下单ID: {first_order_id}")

                # 等待WebSocket订单更新 (最多等待5秒)
                # current_order 由WebSocket回调设置，需要等待足够时间
                max_wait_time = 5  # 秒
                check_interval = 0.1  # 秒
                total_waited = 0

                while total_waited < max_wait_time:
                    await asyncio.sleep(check_interval)
                    total_waited += check_interval

                    # 检查current_order是否已被WebSocket更新
                    if self.lighter_client.current_order is not None:
                        # 验证订单ID匹配
                        if self.lighter_client.current_order.order_id == order_result.order_id:
                            break
                        # 或者验证client_order_id匹配
                        if (hasattr(self.lighter_client, 'current_order_client_id') and
                            self.lighter_client.current_order_client_id is not None):
                            # client_order_index匹配（存储在order_result中可能是不同的格式）
                            pass

                # 获取订单信息
                order_info = await self.lighter_client.get_order_info(
                    order_result.order_id
                )

                if order_info is None:
                    self.logger.error(
                        f"❌ 订单信息为None. current_order状态: {self.lighter_client.current_order is not None}, "
                        f"client_order_id: {getattr(self.lighter_client, 'current_order_client_id', 'N/A')}"
                    )
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
                # 增强错误日志记录,包含更多上下文信息
                error_type = type(e).__name__
                error_msg = str(e)

                # 提取关键错误信息
                if "连接" in error_msg or "connection" in error_msg.lower():
                    error_category = "连接错误"
                elif "流动性" in error_msg or "liquidity" in error_msg.lower():
                    error_category = "流动性不足"
                elif "超时" in error_msg or "timeout" in error_msg.lower():
                    error_category = "请求超时"
                else:
                    error_category = "未知错误"

                self.logger.error(
                    f"❌ 对冲尝试 {attempt + 1}/{self.max_retries} 失败 "
                    f"({error_category}): {error_msg}"
                )
                self.logger.debug(
                    f"对冲失败详情 - Side: {side}, Quantity: {quantity}, "
                    f"Expected Price: {expected_price}, Error Type: {error_type}"
                )

                if attempt < self.max_retries - 1:
                    self.logger.info(f"等待 {self.retry_delay} 秒后重试...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    self.logger.error(
                        f"❌ 对冲失败,已达最大重试次数 ({self.max_retries}). "
                        f"最终错误: {error_category} - {error_msg}"
                    )
                    return {
                        'success': False,
                        'filled_quantity': Decimal('0'),
                        'error': f"{error_category}: {error_msg}"
                    }
        
        # 不应该到达这里
        return {
            'success': False,
            'filled_quantity': Decimal('0'),
            'error': '未知错误'
        }
