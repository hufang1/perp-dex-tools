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

        # 订单状态缓存机制（修复竞态条件bug）
        self._pending_updates: Dict[str, list] = {}  # 待应用的订单更新缓存
        self._update_lock = asyncio.Lock()  # 保护缓存和订单状态的并发锁
        self._cache_ttl: int = 300  # 缓存TTL（5分钟）
        self._max_cache_size: int = 100  # 最大缓存订单数
        self._max_updates_per_order: int = 10  # 每订单最大更新数
        self._cache_hits: int = 0  # 缓存命中次数
        self._cache_misses: int = 0  # 缓存未命中次数

        # T044-T049: Maker订单统计和跟踪
        self.maker_attempts: int = 0  # Maker订单尝试次数
        self.maker_rejections: int = 0  # Maker订单被拒绝次数
        self.maker_successes: int = 0  # Maker订单成功次数
        self.maker_converts: int = 0  # Maker转Taker次数
    
    async def place_spread_maker_order(
        self,
        side: str,
        price: Decimal,
        quantity: Decimal,
        post_only: bool = False
    ) -> Dict[str, Any]:
        """
        在 Extended 下价差 Maker 单

        Args:
            side: 'buy' or 'sell'
            price: 挂单价格
            quantity: 下单数量 (币数)
            post_only: 是否使用post_only (True=maker单, False=taker单)

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
            f"[Extended] 下 {side.upper()} {'Maker' if post_only else 'Taker'} 单: "
            f"{quantity:.4f} @ {price:.2f}"
        )

        # T044: 记录maker订单尝试
        if post_only:
            self.record_maker_attempt()

        # 重置状态
        self.current_order_status = None
        self.filled_quantity = Decimal('0')
        self.filled_price = Decimal('0')

        try:
            # 使用 Extended 客户端下单
            order_result = await self.extended_client.place_open_order(
                contract_id=self.extended_client.contract_id,
                quantity=quantity,
                direction=side,
                post_only=post_only
            )
            
            if not order_result.success:
                self.logger.error(f"下单失败: {order_result.error_message}")
                return {
                    'success': False,
                    'error': order_result.error_message
                }
            
            self.current_order_id = order_result.order_id

            # 【竞态条件修复】设置current_order_id后立即检查并应用缓存更新
            await self._apply_pending_updates(order_result.order_id)

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

        # 【竞态条件修复】在循环开始前检查是否有缓存的更新
        await self._apply_pending_updates(order_id)
        
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

    async def maker_timeout_wait(
        self,
        order_id: str,
        timeout: int
    ) -> Dict[str, Any]:
        """
        等待maker订单成交或超时

        Args:
            order_id: 订单ID
            timeout: 超时时间（秒）

        Returns:
            {
                'status': 'FILLED' | 'TIMEOUT',
                'filled_quantity': Decimal,
                'filled_price': Decimal,
                'remaining': Decimal
            }
        """
        start_time = time.time()
        check_interval = 0.5  # 检查间隔 500ms

        self.logger.info(f"等待Maker订单成交: {order_id} (超时 {timeout}秒)")

        while time.time() - start_time < timeout:
            # 检查订单状态
            if self.current_order_status == 'FILLED':
                self.logger.info(
                    f"✅ Maker订单完全成交: {self.filled_quantity:.4f} @ {self.filled_price:.2f}"
                )
                return {
                    'status': 'FILLED',
                    'filled_quantity': self.filled_quantity,
                    'filled_price': self.filled_price,
                    'remaining': Decimal('0')
                }

            if self.current_order_status in ['CANCELLED', 'CANCELED']:
                self.logger.warning(f"❌ Maker订单已取消")
                return {
                    'status': 'CANCELLED',
                    'filled_quantity': self.filled_quantity,
                    'filled_price': self.filled_price if self.filled_price > 0 else Decimal('0'),
                    'remaining': self.config.order_quantity_usdt - self.filled_quantity
                }

            await asyncio.sleep(check_interval)

        # 超时
        self.logger.warning(
            f"⏰ Maker订单等待超时: 已成交 {self.filled_quantity:.4f}"
        )
        return {
            'status': 'TIMEOUT',
            'filled_quantity': self.filled_quantity,
            'filled_price': self.filled_price if self.filled_price > 0 else Decimal('0'),
            'remaining': self.config.order_quantity_usdt - self.filled_quantity
        }

    async def convert_to_taker(
        self,
        side: str,
        quantity: Decimal,
        original_order_id: str
    ) -> Dict[str, Any]:
        """
        将maker订单转换为taker订单

        Args:
            side: 'buy' or 'sell'
            quantity: 下单数量
            original_order_id: 原始maker订单ID（用于取消）

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
        # T044: 记录maker转taker
        self.record_maker_convert()

        # T049: 更新日志显示maker订单实际状态
        self.logger.info(
            f"🔄 [Maker转Taker] {side.upper()} {quantity:.4f} "
            f"(原订单: {original_order_id[:8]}...)"
        )

        # 1. 取消原始maker订单
        cancel_result = await self.cancel_order(original_order_id)
        if not cancel_result:
            self.logger.warning(f"[Maker转Taker] 取消原订单失败，继续下taker单")

        # 2. 下taker订单（post_only=False）
        try:
            order_result = await self.extended_client.place_open_order(
                contract_id=self.extended_client.contract_id,
                quantity=quantity,
                direction=side,
                post_only=False  # taker订单
            )

            if not order_result.success:
                self.logger.error(f"[Maker转Taker] Taker订单下单失败: {order_result.error_message}")
                return {
                    'success': False,
                    'error': order_result.error_message
                }

            self.current_order_id = order_result.order_id

            # 应用可能存在的缓存更新
            await self._apply_pending_updates(order_result.order_id)

            # T049: 更新日志显示maker订单实际状态
            self.logger.info(
                f"✅ [Maker转Taker] Taker订单已提交: {order_result.order_id[:8]}... "
                f"@ {order_result.price:.2f} (原maker订单已取消)"
            )

            return {
                'success': True,
                'order_id': order_result.order_id,
                'price': order_result.price,
                'quantity': quantity,
                'side': side
            }

        except Exception as e:
            self.logger.error(f"[Maker转Taker] 异常: {e}")
            return {
                'success': False,
                'error': str(e)
            }

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
                    'order_type': str,  # 'OPEN' or 'CLOSE'
                    ...
                }
        """
        order_id = order_data.get('order_id')

        # 006-fix-lighter-close: 移除CLOSE订单忽略逻辑
        # CLOSE订单现在与OPEN订单同样处理，以便平仓流程能正确识别成交状态
        # 原代码假设CLOSE订单不应影响开仓流程，但这是错误的：
        # - 每次下单前状态都会重置（place_spread_maker_order第78-80行）
        # - 订单ID匹配机制确保只有当前订单的更新才会被应用
        # - 开仓和平仓是串行执行的，不会同时进行

        # 【竞态条件修复】检查current_order_id是否已设置
        if self.current_order_id is None:
            # 订单ID尚未设置，缓存这个更新
            self.logger.info(
                f"⚡ 检测到竞态条件: 缓存订单更新, order_id={order_id}, "
                f"current_order_id=None"
            )
            self._add_pending_update(order_id, order_data)
            return

        # 检查是否是当前订单
        if order_id != self.current_order_id:
            # 不是当前订单，也尝试缓存（可能是其他订单的更新）
            self.logger.debug(
                f"[DEBUG] 订单ID不匹配: 缓存更新, "
                f"收到order_id={order_id}, "
                f"当前current_order_id={self.current_order_id}"
            )
            self._add_pending_update(order_id, order_data)
            return

        # 是当前订单，直接应用更新
        self.current_order_status = order_data.get('status')

        filled_size = Decimal(str(order_data.get('filled_size', 0)))
        if filled_size > 0:
            self.filled_quantity = filled_size
            self.filled_price = Decimal(str(order_data.get('price', 0)))

        # 006-fix-lighter-close: 增强日志，区分OPEN/CLOSE订单
        order_type = order_data.get('order_type', 'UNKNOWN')
        self.logger.info(
            f"✅ 订单状态更新 [{order_type}]: {order_id} -> {self.current_order_status} "
            f"已成交: {self.filled_quantity:.4f} @ {self.filled_price:.2f}"
        )

    def _add_pending_update(self, order_id: str, order_data: Dict[str, Any]) -> None:
        """
        添加订单更新到缓存

        Args:
            order_id: 订单ID
            order_data: 订单数据
        """
        # 创建缓存条目
        cache_entry = {
            "order_data": order_data,
            "timestamp": time.time()
        }

        # 初始化该订单的缓存列表（如果不存在）
        if order_id not in self._pending_updates:
            self._pending_updates[order_id] = []

        # 限制每个订单的缓存更新数量
        if len(self._pending_updates[order_id]) >= self._max_updates_per_order:
            # 删除最旧的更新
            self._pending_updates[order_id].pop(0)
            self.logger.debug(
                f"[DEBUG] 缓存限制: 删除最旧的更新, order_id={order_id}, "
                f"当前数量={len(self._pending_updates[order_id])}"
            )

        # 添加新更新
        self._pending_updates[order_id].append(cache_entry)
        self.logger.debug(
            f"[DEBUG] 缓存订单更新: order_id={order_id}, "
            f"timestamp={cache_entry['timestamp']:.3f}, "
            f"status={order_data.get('status')}"
        )

    async def _apply_pending_updates(self, order_id: str) -> None:
        """
        应用指定订单的缓存更新

        Args:
            order_id: 订单ID
        """
        # T009: 添加详细日志 - 缓存检查开始
        self.logger.info(f"🔍 检查缓存: order_id={order_id}")

        async with self._update_lock:
            # 检查是否有该订单的缓存
            if order_id not in self._pending_updates:
                # T009: 添加详细日志 - 未找到缓存
                self.logger.info(f"❌ 无缓存更新: order_id={order_id}")
                self._cache_misses += 1
                return

            # 获取并删除缓存
            updates = self._pending_updates.pop(order_id)
            # T009: 添加详细日志 - 找到缓存
            self.logger.info(f"✅ 找到缓存: order_id={order_id}, 数量={len(updates)}")

            # 按时间戳升序排序
            updates.sort(key=lambda x: x['timestamp'])

            # 依次应用每个更新
            for update in updates:
                order_data = update['order_data']
                status = order_data.get('status')

                # 更新订单状态
                self.current_order_status = status

                # 更新成交数量和价格
                filled_size = Decimal(str(order_data.get('filled_size', 0)))
                if filled_size > 0:
                    self.filled_quantity = filled_size
                    self.filled_price = Decimal(str(order_data.get('price', 0)))

                self.logger.info(
                    f"✅ 应用缓存的订单更新: order_id={order_id}, "
                    f"status={status}, "
                    f"filled_size={self.filled_quantity:.4f}, "
                    f"price={self.filled_price:.2f}"
                )

            # 更新统计
            self._cache_hits += 1
            self.logger.info(
                f"📊 缓存统计: 命中率={self._get_cache_hit_rate():.1%}, "
                f"命中={self._cache_hits}, 未命中={self._cache_misses}"
            )

    async def _cleanup_cache(self) -> None:
        """
        清理过期和超限的缓存
        """
        async with self._update_lock:
            now = time.time()
            orders_to_remove = []

            # 1. 清理超过TTL的缓存
            for order_id, updates in self._pending_updates.items():
                if updates and now - updates[0]['timestamp'] > self._cache_ttl:
                    orders_to_remove.append(order_id)
                    self.logger.warning(
                        f"⚠️ TTL过期: 清理缓存, order_id={order_id}, "
                        f"年龄={now - updates[0]['timestamp']:.1f}秒"
                    )

            # 2. 清理已完成订单的缓存
            for order_id, updates in self._pending_updates.items():
                if updates:
                    latest_status = updates[-1]['order_data'].get('status')
                    if latest_status in ['FILLED', 'CANCELLED', 'CANCELED']:
                        if order_id not in orders_to_remove:
                            orders_to_remove.append(order_id)
                            self.logger.debug(
                                f"[DEBUG] 订单完成: 清理缓存, order_id={order_id}, "
                                f"status={latest_status}"
                            )

            # 3. 清理超过最大限制的缓存（最旧的）
            if len(self._pending_updates) > self._max_cache_size:
                # 按最早的时间戳排序
                sorted_orders = sorted(
                    self._pending_updates.items(),
                    key=lambda x: x[1][0]['timestamp'] if x[1] else 0
                )
                excess = len(self._pending_updates) - self._max_cache_size
                for order_id, _ in sorted_orders[:excess]:
                    if order_id not in orders_to_remove:
                        orders_to_remove.append(order_id)

            # 执行清理
            for order_id in orders_to_remove:
                if order_id in self._pending_updates:
                    del self._pending_updates[order_id]

            if orders_to_remove:
                self.logger.warning(
                    f"⚠️ 清理缓存: 清理了{len(orders_to_remove)}个订单, "
                    f"剩余{len(self._pending_updates)}个"
                )

    def _get_cache_hit_rate(self) -> float:
        """
        计算缓存命中率

        Returns:
            命中率（0-1之间）
        """
        total = self._cache_hits + self._cache_misses
        if total == 0:
            return 0.0
        return self._cache_hits / total

    # ==================== T044-T049: Maker订单统计和跟踪方法 ====================

    def record_maker_attempt(self) -> None:
        """
        T044: 记录一次maker订单尝试
        """
        self.maker_attempts += 1
        self.logger.debug(f"[Maker统计] 记录尝试，总次数: {self.maker_attempts}")

    def record_maker_rejection(self) -> None:
        """
        T045: 记录一次maker订单被拒绝
        """
        self.maker_rejections += 1
        self.logger.debug(f"[Maker统计] 记录拒绝，总拒绝: {self.maker_rejections}")

    def record_maker_success(self) -> None:
        """
        记录一次maker订单成功成交
        """
        self.maker_successes += 1
        self.logger.debug(f"[Maker统计] 记录成功，总成功: {self.maker_successes}")

    def record_maker_convert(self) -> None:
        """
        记录一次maker转taker操作
        """
        self.maker_converts += 1
        self.logger.debug(f"[Maker统计] 记录转换，总转换: {self.maker_converts}")

    def get_maker_success_rate(self) -> float:
        """
        T046: 获取maker订单成功率

        Returns:
            float: 成功率（0-1之间），如果没有尝试则返回0
        """
        if self.maker_attempts == 0:
            return 0.0
        return self.maker_successes / self.maker_attempts

    def get_maker_rejection_rate(self) -> float:
        """
        获取maker订单拒绝率

        Returns:
            float: 拒绝率（0-1之间），如果没有尝试则返回0
        """
        if self.maker_attempts == 0:
            return 0.0
        return self.maker_rejections / self.maker_attempts

    def should_adjust_price_tick(self) -> bool:
        """
        T047: 判断是否需要调整price_tick

        如果maker拒绝率过高（>50%），可能需要调整price_tick

        Returns:
            bool: True=需要调整, False=不需要调整
        """
        rejection_rate = self.get_maker_rejection_rate()
        if self.maker_attempts >= 10 and rejection_rate > 0.5:
            self.logger.warning(
                f"[Maker统计] 拒绝率过高: {rejection_rate:.2%}，建议调整price_tick"
            )
            return True
        return False

    def get_maker_stats(self) -> Dict[str, Any]:
        """
        获取maker订单统计信息

        Returns:
            Dict: 包含所有maker统计的字典
        """
        return {
            'attempts': self.maker_attempts,
            'rejections': self.maker_rejections,
            'successes': self.maker_successes,
            'converts': self.maker_converts,
            'success_rate': self.get_maker_success_rate(),
            'rejection_rate': self.get_maker_rejection_rate(),
            'should_adjust_tick': self.should_adjust_price_tick()
        }
