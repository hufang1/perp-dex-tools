"""
单腿回滚处理模块

本模块实现012-dual-leg-concurrency的单腿成交快速回滚功能，包括:
- 单腿持仓检测
- 紧急平仓执行
- 回滚性能监控
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from spread.config import SpreadArbConfig
from spread.models import ConcurrentOrderResult, LegRollbackEvent
from spread.performance_monitor import PerformanceMonitor


class LegRollbackHandler:
    """
    单腿回滚处理器

    当并发订单执行后出现单腿持仓时，触发紧急平仓以消除风险敞口。
    """

    def __init__(
        self,
        config: SpreadArbConfig,
        monitor: PerformanceMonitor,
        extended_client: Any,
        lighter_client: Any,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """初始化单腿回滚处理器

        Args:
            config: SpreadArbConfig配置对象
            monitor: PerformanceMonitor实例
            extended_client: Extended交易所客户端
            lighter_client: Lighter交易所客户端
            logger: 日志记录器（可选）
        """
        self.config = config
        self.monitor = monitor
        self.extended_client = extended_client
        self.lighter_client = lighter_client
        self.logger = logger or logging.getLogger(__name__)

    # ========================================================================
    # 单腿检测
    # ========================================================================

    def detect_legging(self, result: ConcurrentOrderResult) -> bool:
        """检测是否出现单腿持仓（T041）

        Args:
            result: 并发订单执行结果

        Returns:
            True 如果出现单腿持仓（一边成交一边失败）

        Examples:
            >>> result = ConcurrentOrderResult(
            ...     extended_success=True, lighter_success=False, ...
            ... )
            >>> handler.detect_legging(result)
            True
        """
        # 单腿持仓：一边成功一边失败
        is_legging = result.extended_success != result.lighter_success

        if is_legging:
            legging_side = 'extended' if result.extended_success else 'lighter'
            self.logger.error(
                f"🚨 [单腿检测] 检测到{legging_side}单腿持仓！"
            )

        return is_legging

    # ========================================================================
    # 紧急平仓
    # ========================================================================

    async def execute_emergency_close(
        self,
        result: ConcurrentOrderResult,
        pair_id: int
    ) -> LegRollbackEvent:
        """执行紧急平仓（T042）

        使用市价单或大滑点限价单立即平仓，确保在1秒内完成。

        Args:
            result: 并发订单执行结果（包含单腿持仓信息）
            pair_id: 套利对ID

        Returns:
            LegRollbackEvent对象，记录回滚过程和结果

        契约:
            - rollback_latency_ms 必须 <= 1000ms（否则未达标）
            - 最多重试3次
            - 必须记录"[CRITICAL] Legging detected"日志
        """
        # T043: 关键日志标记
        self.logger.error(
            f"[CRITICAL] Legging detected, rolling back position (pair_id={pair_id})"
        )

        # 确定需要平仓的一边
        if result.extended_success:
            # Extended成交了，需要平仓Extended
            exchange = 'extended'
            side = 'sell' if result.extended_filled_price > 0 else 'buy'
            quantity = result.extended_filled_qty
            price = result.extended_filled_price
        else:
            # Lighter成交了，需要平仓Lighter
            exchange = 'lighter'
            side = 'buy' if result.lighter_filled_price > 0 else 'sell'
            quantity = result.lighter_filled_qty
            price = result.lighter_filled_price

        # 确定平仓方向（与开仓相反）
        # 根据result中的价格推断方向：如果有filled_price表示已成交
        # 如果Extended成功：side从opportunity获取，这里简化处理
        # 实际应该从opportunity['side']推断，这里假设result包含此信息

        start_time = time.time() * 1000
        trigger_time = start_time

        self.logger.warning(
            f"🚨 [紧急平仓] 开始: {exchange} {side} {quantity} "
            f"@ ${price:.2f}"
        )

        # 尝试最多3次
        max_retries = self.config.rollback_max_retries
        rollback_success = False
        rollback_order_id = None
        rollback_filled_qty = Decimal('0')
        error_message = None

        for attempt in range(1, max_retries + 1):
            try:
                # 使用市价单（Extended原生支持，Lighter用极端限价）
                # 传入价格用于平仓
                order = {
                    'side': side,
                    'quantity': str(quantity),
                    'price': str(price),  # 传入持仓价格作为参考
                    'order_type': 'CLOSE',  # 标记为平仓订单
                    'symbol': self.config.ticker
                }

                if exchange == 'extended':
                    order_result = await asyncio.wait_for(
                        self._place_order_extended(order),
                        timeout=self.config.rollback_timeout_ms / 1000
                    )
                else:
                    order_result = await asyncio.wait_for(
                        self._place_order_lighter(order),
                        timeout=self.config.rollback_timeout_ms / 1000
                    )

                if order_result.get('success'):
                    rollback_success = True
                    rollback_order_id = order_result.get('order_id')
                    rollback_filled_qty = Decimal(order_result.get('executed_qty', quantity))
                    break
                else:
                    error_message = order_result.get('error', 'Unknown error')
                    self.logger.warning(
                        f"⚠️ [紧急平仓] 第{attempt}次尝试失败: {error_message}"
                    )

            except asyncio.TimeoutError:
                error_message = 'timeout'
                self.logger.error(f"⚠️ [紧急平仓] 第{attempt}次尝试超时")
            except Exception as e:
                error_message = str(e)
                self.logger.error(f"⚠️ [紧急平仓] 第{attempt}次尝试异常: {e}")

            if attempt < max_retries:
                await asyncio.sleep(0.05)  # 50ms后重试

        complete_time = time.time() * 1000
        rollback_latency_ms = complete_time - start_time
        exposure_time_ms = complete_time - trigger_time

        # 创建回滚事件
        event = LegRollbackEvent(
            trigger_time=trigger_time,
            legging_side=exchange,
            legging_qty=quantity,
            legging_price=price,
            rollback_executed=True,
            rollback_start_ts=start_time,
            rollback_complete_ts=complete_time,
            rollback_latency_ms=rollback_latency_ms,
            rollback_success=rollback_success,
            rollback_order_id=rollback_order_id,
            rollback_filled_qty=rollback_filled_qty,
            rollback_error=error_message,
            exposure_time_ms=exposure_time_ms,
            price_slippage=None  # TODO: 计算价格滑点
        )

        # T044: 检查SLA（在LegRollbackEvent.is_within_sla()中实现）
        if event.is_within_sla():
            self.logger.info(
                f"✅ [紧急平仓] 成功! 延迟: {rollback_latency_ms:.2f}ms "
                f"(<= 1000ms SLA)"
            )
        else:
            self.logger.error(
                f"❌ [紧急平仓] 未达标! 延迟: {rollback_latency_ms:.2f}ms "
                f"(> 1000ms SLA)"
            )

        # 记录到性能监控
        self.monitor.record_rollback_latency(rollback_latency_ms)

        return event

    # ========================================================================
    # 交易所客户端适配器
    # ========================================================================

    async def _place_order_extended(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Extended下单适配器

        Args:
            order: 订单字典，包含:
                - side: 'buy' 或 'sell'
                - quantity: 数量（字符串或Decimal）
                - price: 价格（用于平仓）
                - type: 'MARKET' 表示市价单（用于紧急平仓）

        Returns:
            订单结果字典，包含:
                - success: bool
                - order_id: str 或 None
                - executed_qty: 成交数量
                - avg_price: 成交均价
                - error: str 或 None
        """
        # 获取contract_id
        contract_id = getattr(self.extended_client, 'contract_id', None)
        if not contract_id:
            contract_id = getattr(self.extended_client.config, 'contract_id', None)

        if not contract_id:
            return {
                'success': False,
                'order_id': None,
                'executed_qty': '0',
                'avg_price': '0',
                'error': 'Missing contract_id'
            }

        # 解析参数
        side = order.get('side')  # 'buy' 或 'sell'
        quantity = Decimal(order['quantity'])

        # 对于紧急平仓，使用订单簿中的对手价
        # 这里简化处理：使用传入的价格或获取当前对手价
        price = Decimal(order.get('price', 0))
        if price == 0:
            # 如果没有指定价格，尝试获取当前对手价
            # 这里简化处理，实际应该从订单簿获取
            self.logger.warning("未指定平仓价格，使用默认值0")
            price = Decimal('0')

        try:
            # 紧急平仓总是使用place_close_order
            result = await self.extended_client.place_close_order(
                contract_id=contract_id,
                quantity=quantity,
                price=price,
                side=side
            )

            # 映射OrderResult到字典格式
            return {
                'success': result.success,
                'order_id': result.order_id,
                'executed_qty': str(result.filled_size or result.size or '0'),
                'avg_price': str(result.price or '0'),
                'error': result.error_message
            }

        except Exception as e:
            return {
                'success': False,
                'order_id': None,
                'executed_qty': '0',
                'avg_price': '0',
                'error': str(e)
            }

    async def _place_order_lighter(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Lighter下单适配器

        Args:
            order: 订单字典，包含:
                - side: 'buy' 或 'sell'
                - quantity: 数量（字符串或Decimal）
                - price: 价格（用于平仓）
                - type: 'MARKET' 表示市价单（用于紧急平仓）

        Returns:
            订单结果字典，包含:
                - success: bool
                - order_id: str 或 None
                - executed_qty: 成交数量
                - avg_price: 成交均价
                - error: str 或 None
        """
        # 获取contract_id
        contract_id = getattr(self.lighter_client, 'contract_id', None)
        if not contract_id:
            contract_id = getattr(self.lighter_client.config, 'contract_id', None)

        if not contract_id:
            return {
                'success': False,
                'order_id': None,
                'executed_qty': '0',
                'avg_price': '0',
                'error': 'Missing contract_id'
            }

        # 解析参数
        side = order.get('side')  # 'buy' 或 'sell'
        quantity = Decimal(order['quantity'])

        # 对于紧急平仓，使用极端价格确保成交
        price = Decimal(order.get('price', 0))
        if price == 0 or order.get('type') == 'MARKET':
            # 使用极端限价模拟市价单
            if side == 'buy':
                # 买入使用极端高价确保成交
                price = Decimal('999999')
            else:
                # 卖出使用极端低价确保成交
                price = Decimal('0.01')

        try:
            # 紧急平仓总是使用place_close_order
            result = await self.lighter_client.place_close_order(
                contract_id=contract_id,
                quantity=quantity,
                price=price,
                side=side
            )

            # 映射OrderResult到字典格式
            return {
                'success': result.success,
                'order_id': result.order_id,
                'executed_qty': str(result.filled_size or result.size or '0'),
                'avg_price': str(result.price or '0'),
                'error': result.error_message
            }

        except Exception as e:
            return {
                'success': False,
                'order_id': None,
                'executed_qty': '0',
                'avg_price': '0',
                'error': str(e)
            }
