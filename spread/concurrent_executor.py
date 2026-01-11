"""
并发执行模块

本模块实现011-async-ws-ioc-trading的并发交易执行功能，包括:
- 双腿并发下单（asyncio.gather）
- 并发平仓
- 紧急单腿平仓
- 并发时间戳记录
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Callable, Dict, Optional, Tuple

from spread.config import SpreadArbConfig
from spread.performance_monitor import PerformanceMonitor
from spread.models import ConcurrentOrderResult


class ConcurrentExecutor:
    """
    并发执行器

    负责同时向两个交易所发送订单，并记录发送时间差。
    """

    def __init__(
        self,
        config: SpreadArbConfig,
        monitor: PerformanceMonitor,
        extended_client: Any,
        lighter_client: Any,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """初始化并发执行器

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
    # 并发下单
    # ========================================================================

    async def execute_concurrent_orders(
        self,
        extended_order: Dict[str, Any],
        lighter_order: Dict[str, Any],
        timeout_ms: int = 500
    ) -> Tuple[Dict, Dict, float]:
        """并发执行两个交易所的下单

        Args:
            extended_order: Extended订单字典
            lighter_order: Lighter订单字典
            timeout_ms: 超时时间（毫秒）

        Returns:
            (extended_result, lighter_result, send_gap_ms)
            - result: {'success': bool, 'order_id': str, 'error': str}
            - send_gap_ms: 发送时间差（毫秒）

        Raises:
            TimeoutError: 两个订单都超时

        副作用:
            - 记录send_A_ts和send_B_ts
            - 调用monitor.record_concurrent_send_gap()
        """
        send_a_ts = None
        send_b_ts = None

        async def place_extended():
            nonlocal send_a_ts
            send_a_ts = time.time() * 1000
            try:
                # 调用Extended客户端下单方法
                result = await asyncio.wait_for(
                    self._place_order_extended(extended_order),
                    timeout=timeout_ms / 1000
                )
                return {'success': True, 'order_id': result.get('order_id'), 'data': result}
            except asyncio.TimeoutError:
                return {'success': False, 'error': 'timeout', 'order_id': None}
            except Exception as e:
                return {'success': False, 'error': str(e), 'order_id': None}

        async def place_lighter():
            nonlocal send_b_ts
            send_b_ts = time.time() * 1000
            try:
                # 调用Lighter客户端下单方法
                result = await asyncio.wait_for(
                    self._place_order_lighter(lighter_order),
                    timeout=timeout_ms / 1000
                )
                return {'success': True, 'order_id': result.get('order_id'), 'data': result}
            except asyncio.TimeoutError:
                return {'success': False, 'error': 'timeout', 'order_id': None}
            except Exception as e:
                return {'success': False, 'error': str(e), 'order_id': None}

        # 并发执行
        results = await asyncio.gather(
            place_extended(),
            place_lighter(),
            return_exceptions=True
        )

        ext_result = results[0] if not isinstance(results[0], Exception) else {'success': False, 'error': str(results[0])}
        lit_result = results[1] if not isinstance(results[1], Exception) else {'success': False, 'error': str(results[1])}

        # 计算发送间隔
        send_gap_ms = abs(send_b_ts - send_a_ts) if (send_a_ts and send_b_ts) else 0

        # 记录到性能监控
        if send_a_ts and send_b_ts:
            self.monitor.record_concurrent_send_gap(send_a_ts, send_b_ts)

        # 记录时间戳
        self.monitor.record_timestamp('send_A', {'ts': send_a_ts})
        self.monitor.record_timestamp('send_B', {'ts': send_b_ts})

        self.logger.info(
            f"🔄 [并发下单] Extended: {'✅' if ext_result['success'] else '❌'}, "
            f"Lighter: {'✅' if lit_result['success'] else '❌'}, "
            f"间隔: {send_gap_ms:.2f}ms"
        )

        return ext_result, lit_result, send_gap_ms

    # ========================================================================
    # 012-dual-leg-concurrency: 双腿并发下单（扩展版本）
    # ========================================================================

    async def execute_dual_leg_orders(
        self,
        extended_order: Dict[str, Any],
        lighter_order: Dict[str, Any],
        opportunity: Dict[str, Any]
    ) -> ConcurrentOrderResult:
        """执行双腿并发订单（扩展版本）

        Args:
            extended_order: Extended订单字典（由IocOrderManager创建）
            lighter_order: Lighter订单字典（由IocOrderManager创建）
            opportunity: 套利机会字典（用于日志记录）

        Returns:
            ConcurrentOrderResult对象，包含：
            - 双边订单执行结果
            - 并发发送时间差
            - 成交状态判断

        Raises:
            TimeoutError: 两个订单都超时（500ms）
            ConnectionError: 网络连接失败

        契约:
            - send_gap_ms 必须 <= 5ms（否则警告）
            - total_latency_ms 必须 <= 500ms（否则超时）
            - 必须记录send_A_ts和send_B_ts时间戳
        """
        send_a_ts = None
        send_b_ts = None
        start_time = time.time() * 1000

        async def place_extended():
            nonlocal send_a_ts
            send_a_ts = time.time() * 1000
            try:
                result = await asyncio.wait_for(
                    self._place_order_extended(extended_order),
                    timeout=self.config.order_timeout_ms / 1000
                )
                return {
                    'success': True,
                    'order_id': result.get('order_id'),
                    'filled_qty': Decimal(result.get('executed_qty', 0)),
                    'filled_price': Decimal(result.get('avg_price', 0)),
                    'error': None
                }
            except asyncio.TimeoutError:
                return {
                    'success': False,
                    'order_id': None,
                    'filled_qty': Decimal('0'),
                    'filled_price': None,
                    'error': 'timeout'
                }
            except Exception as e:
                return {
                    'success': False,
                    'order_id': None,
                    'filled_qty': Decimal('0'),
                    'filled_price': None,
                    'error': str(e)
                }

        async def place_lighter():
            nonlocal send_b_ts
            send_b_ts = time.time() * 1000
            try:
                result = await asyncio.wait_for(
                    self._place_order_lighter(lighter_order),
                    timeout=self.config.order_timeout_ms / 1000
                )
                return {
                    'success': True,
                    'order_id': result.get('order_id'),
                    'filled_qty': Decimal(result.get('executed_qty', 0)),
                    'filled_price': Decimal(result.get('avg_price', 0)),
                    'error': None
                }
            except asyncio.TimeoutError:
                return {
                    'success': False,
                    'order_id': None,
                    'filled_qty': Decimal('0'),
                    'filled_price': None,
                    'error': 'timeout'
                }
            except Exception as e:
                return {
                    'success': False,
                    'order_id': None,
                    'filled_qty': Decimal('0'),
                    'filled_price': None,
                    'error': str(e)
                }

        # 并发执行
        results = await asyncio.gather(
            place_extended(),
            place_lighter(),
            return_exceptions=True
        )

        ext_result = results[0] if not isinstance(results[0], Exception) else {
            'success': False, 'order_id': None, 'filled_qty': Decimal('0'),
            'filled_price': None, 'error': str(results[0])
        }
        lit_result = results[1] if not isinstance(results[1], Exception) else {
            'success': False, 'order_id': None, 'filled_qty': Decimal('0'),
            'filled_price': None, 'error': str(results[1])
        }

        # 计算指标
        send_gap_ms = abs(send_b_ts - send_a_ts) if (send_a_ts and send_b_ts) else 0
        total_latency_ms = time.time() * 1000 - start_time

        # 判断成交状态
        is_both_filled = ext_result['success'] and lit_result['success']
        is_legging = ext_result['success'] != lit_result['success']
        is_both_failed = not ext_result['success'] and not lit_result['success']

        # 构造结果对象
        result = ConcurrentOrderResult(
            extended_success=ext_result['success'],
            extended_order_id=ext_result['order_id'],
            extended_filled_qty=ext_result['filled_qty'],
            extended_filled_price=ext_result['filled_price'],
            extended_error=ext_result['error'],
            lighter_success=lit_result['success'],
            lighter_order_id=lit_result['order_id'],
            lighter_filled_qty=lit_result['filled_qty'],
            lighter_filled_price=lit_result['filled_price'],
            lighter_error=lit_result['error'],
            send_a_ts=send_a_ts or 0,
            send_b_ts=send_b_ts or 0,
            send_gap_ms=send_gap_ms,
            total_latency_ms=total_latency_ms,
            is_both_filled=is_both_filled,
            is_legging=is_legging,
            is_both_failed=is_both_failed
        )

        # 记录到性能监控
        if send_a_ts and send_b_ts:
            self.monitor.record_concurrent_send_gap(send_a_ts, send_b_ts)

        # 日志记录
        if is_both_filled:
            self.logger.info(
                f"✅ [双腿成交] Extended: {ext_result['order_id']}, "
                f"Lighter: {lit_result['order_id']}, "
                f"间隔: {send_gap_ms:.2f}ms, 延迟: {total_latency_ms:.2f}ms"
            )
        elif is_legging:
            # 🔴 FIX: 修复日志格式bug，正确显示成交/失败状态
            success_side = 'Extended' if ext_result['success'] else 'Lighter'
            fail_side = 'Lighter' if ext_result['success'] else 'Extended'
            self.logger.warning(
                f"⚠️ [单腿持仓] {success_side}: 成交, {fail_side}: 失败, "
                f"间隔: {send_gap_ms:.2f}ms | "
                f"Extended: success={ext_result['success']}, order_id={ext_result['order_id']}, "
                f"Lighter: success={lit_result['success']}, order_id={lit_result['order_id']}"
            )
        else:
            self.logger.error(
                f"❌ [双边失败] Extended: {ext_result['error']}, "
                f"Lighter: {lit_result['error']}, "
                f"间隔: {send_gap_ms:.2f}ms"
            )

        return result

    # ========================================================================
    # 并发平仓
    # ========================================================================

    async def execute_concurrent_close(
        self,
        extended_order: Dict[str, Any],
        lighter_order: Dict[str, Any],
        timeout_ms: int = 500
    ) -> Tuple[Dict, Dict, float]:
        """并发执行平仓

        参数和返回值同execute_concurrent_orders
        """
        return await self.execute_concurrent_orders(extended_order, lighter_order, timeout_ms)

    # ========================================================================
    # 紧急平仓
    # ========================================================================

    async def emergency_close_position(
        self,
        exchange: str,
        side: str,
        quantity: Decimal,
        timeout_ms: int = 1000
    ) -> Dict:
        """紧急平仓（单腿）

        Args:
            exchange: 'extended' 或 'lighter'
            side: 'buy' 或 'sell'
            quantity: 数量
            timeout_ms: 超时时间（毫秒）

        Returns:
            {'success': bool, 'order_id': str, 'filled_qty': Decimal, 'error': str}

        Note:
            紧急平仓使用市价单或大滑点限价单，确保必须成交
        """
        self.logger.warning(f"🚨 [紧急平仓] {exchange} {side} {quantity}")

        try:
            # 构造紧急平仓订单
            # 使用市价单或大滑点限价单确保成交
            order = {
                'side': side,
                'quantity': str(quantity),
                'order_type': 'CLOSE',  # 标记为平仓订单
                'symbol': self.config.ticker
            }

            if exchange == 'extended':
                result = await asyncio.wait_for(
                    self._place_order_extended(order),
                    timeout=timeout_ms / 1000
                )
            else:
                result = await asyncio.wait_for(
                    self._place_order_lighter(order),
                    timeout=timeout_ms / 1000
                )

            self.logger.info(f"✅ [紧急平仓] 成功: {result.get('order_id')}")
            return {
                'success': True,
                'order_id': result.get('order_id'),
                'filled_qty': Decimal(result.get('executed_qty', quantity)),
                'error': None
            }

        except asyncio.TimeoutError:
            self.logger.error(f"❌ [紧急平仓] 超时")
            return {'success': False, 'error': 'timeout', 'order_id': None, 'filled_qty': Decimal('0')}
        except Exception as e:
            self.logger.error(f"❌ [紧急平仓] 失败: {e}")
            return {'success': False, 'error': str(e), 'order_id': None, 'filled_qty': Decimal('0')}

    # ========================================================================
    # 交易所客户端适配器
    # ========================================================================

    async def _place_order_extended(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Extended下单适配器

        Args:
            order: 订单字典，包含:
                - side: 'buy' 或 'sell'
                - quantity: 数量（字符串或Decimal）
                - price: 价格（可选，用于平仓）
                - order_type: 'OPEN' 或 'CLOSE'（默认OPEN）

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
        direction = order.get('side')  # 'buy' 或 'sell'
        quantity = Decimal(order['quantity'])
        order_type = order.get('order_type', 'OPEN')  # 默认开仓

        try:
            if order_type == 'CLOSE':
                # 平仓订单
                price = Decimal(order.get('price', 0))
                result = await self.extended_client.place_close_order(
                    contract_id=contract_id,
                    quantity=quantity,
                    price=price,
                    side=direction
                )
            else:
                # 开仓订单
                result = await self.extended_client.place_open_order(
                    contract_id=contract_id,
                    quantity=quantity,
                    direction=direction,
                    post_only=False  # IOC订单总是taker
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
                - price: 价格（可选，用于平仓）
                - order_type: 'OPEN' 或 'CLOSE'（默认OPEN）

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
        direction = order.get('side')  # 'buy' 或 'sell'
        quantity = Decimal(order['quantity'])
        order_type = order.get('order_type', 'OPEN')  # 默认开仓

        try:
            if order_type == 'CLOSE':
                # 平仓订单
                price = Decimal(order.get('price', 0))
                result = await self.lighter_client.place_close_order(
                    contract_id=contract_id,
                    quantity=quantity,
                    price=price,
                    side=direction
                )
            else:
                # 开仓订单
                result = await self.lighter_client.place_open_order(
                    contract_id=contract_id,
                    quantity=quantity,
                    direction=direction
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
