"""
交易执行器：执行开仓和平仓订单

负责：
1. 并发发送订单到两个交易所
2. 监控订单执行状态
3. 处理超时和单边成交
4. 强平（rollback）操作
"""

import asyncio
import time
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from models import SpreadInfo, Position, Trade, PositionState
from exceptions import (
    ExecutionTimeoutError,
    SingleSideExecutionError,
    RiskValidationFailedError,
)


logger = logging.getLogger(__name__)


class ExecutionResult:
    """订单执行结果"""

    def __init__(
        self,
        success: bool = False,
        extended_order_id: Optional[str] = None,
        lighter_order_id: Optional[str] = None,
        extended_price: Optional[Decimal] = None,
        lighter_price: Optional[Decimal] = None,
        error_message: Optional[str] = None,
        execution_time: float = 0.0,
        extended_filled: bool = False,
        lighter_filled: bool = False
    ):
        self.success = success
        self.extended_order_id = extended_order_id
        self.lighter_order_id = lighter_order_id
        self.extended_price = extended_price
        self.lighter_price = lighter_price
        self.error_message = error_message
        self.execution_time = execution_time
        self.extended_filled = extended_filled
        self.lighter_filled = lighter_filled


class TradeExecutor:
    """
    执行交易订单

    负责在两个交易所之间并发执行套利交易
    """

    def __init__(
        self,
        lighter_client,
        extended_client,
        risk_manager,
        timeout: float = 3.0
    ):
        """
        初始化交易执行器

        Args:
            lighter_client: Lighter 交易所客户端
            extended_client: Extended 交易所客户端
            risk_manager: 风控管理器
            timeout: 单边超时时间（秒）
        """
        self.lighter_client = lighter_client
        self.extended_client = extended_client
        self.risk_manager = risk_manager
        self.timeout = timeout

        logger.info(f"交易执行器初始化: 超时={timeout}秒")

    async def execute_open_position(
        self,
        quantity: Decimal,
        spread
    ) -> ExecutionResult:
        """
        执行开仓（并发发送订单）- Taker模式 (016-spread-optimize)

        开仓方向（Taker模式，即时成交）：
        - Extended: 买入（使用 ask 价格）
        - Lighter: 卖出（使用 bid 价格）

        Args:
            quantity: 交易数量
            spread: 价差信息（RealTimeSpreadInfo或SpreadInfo）

        Returns:
            ExecutionResult 对象
        """
        start_time = time.time()
        logger.info(f"开仓[Taker]: 数量={quantity}")

        try:
            # Taker模式价格计算 (016-spread-optimize)
            # 买入用ask，卖出用bid
            if hasattr(spread, 'ext_ask'):
                # RealTimeSpreadInfo
                ext_price = spread.ext_ask
                lig_price = spread.lig_bid
            else:
                # SpreadInfo（向后兼容）
                ext_price = getattr(spread, 'extended_ask_vwap', None)
                lig_price = getattr(spread, 'lighter_bid_vwap', None)

            # 并发发送两个订单（Taker模式）
            results = await asyncio.gather(
                self._place_extended_order_taker("buy", quantity, ext_price),
                self._place_lighter_order_taker("sell", quantity, lig_price),
                return_exceptions=True
            )

            extended_result = results[0]
            lighter_result = results[1]

            # 检查是否有错误
            if isinstance(extended_result, Exception):
                return ExecutionResult(
                    error_message=f"Extended 订单失败: {extended_result}",
                    execution_time=time.time() - start_time
                )

            if isinstance(lighter_result, Exception):
                return ExecutionResult(
                    error_message=f"Lighter 订单失败: {lighter_result}",
                    execution_time=time.time() - start_time
                )

            # 等待订单成交
            execution_status = await self.wait_for_execution(
                extended_result["order_id"],
                lighter_result["order_id"],
                self.timeout
            )

            execution_time = time.time() - start_time

            # 处理执行结果
            if execution_status["both_filled"]:
                logger.info(
                    f"开仓成功[Taker]: Ext={extended_result['order_id']}, "
                    f"Lig={lighter_result['order_id']}, "
                    f"耗时={execution_time:.3f}秒"
                )
                return ExecutionResult(
                    success=True,
                    extended_order_id=extended_result["order_id"],
                    lighter_order_id=lighter_result["order_id"],
                    extended_price=extended_result.get("price"),
                    lighter_price=lighter_result.get("price"),
                    execution_time=execution_time,
                    extended_filled=True,
                    lighter_filled=True
                )
            elif execution_status["timeout"]:
                logger.warning("订单状态查询超时（不取消订单，通过实际仓位确认）")
                # 不取消订单！订单可能已经成交，但状态查询有延迟
                # 让OPENING_WAIT状态通过查询实际仓位来判断
                return ExecutionResult(
                    success=False,
                    extended_order_id=extended_result["order_id"],
                    lighter_order_id=lighter_result["order_id"],
                    extended_price=extended_result.get("price"),
                    lighter_price=lighter_result.get("price"),
                    error_message="订单状态查询超时",
                    execution_time=execution_time,
                    extended_filled=execution_status["extended_filled"],
                    lighter_filled=execution_status["lighter_filled"]
                )
            else:
                # 单边成交（这种情况现在不应该发生，因为我们修改了wait_for_execution）
                logger.error(
                    f"单边成交: Extended={execution_status['extended_filled']}, "
                    f"Lighter={execution_status['lighter_filled']}"
                )
                # 也返回order_id，让上层逻辑进入OPENING_WAIT状态检查实际仓位
                return ExecutionResult(
                    success=False,
                    extended_order_id=extended_result["order_id"],
                    lighter_order_id=lighter_result["order_id"],
                    extended_price=extended_result.get("price"),
                    lighter_price=lighter_result.get("price"),
                    error_message="单边成交",
                    execution_time=execution_time,
                    extended_filled=execution_status["extended_filled"],
                    lighter_filled=execution_status["lighter_filled"]
                )

        except Exception as e:
            logger.error(f"执行开仓失败: {e}")
            return ExecutionResult(
                error_message=str(e),
                execution_time=time.time() - start_time
            )

    async def execute_close_position(
        self,
        position: Position,
        quantity: Decimal
    ) -> ExecutionResult:
        """
        执行平仓（并发发送订单）- Taker模式 (016-spread-optimize)

        平仓方向（Taker模式，即时成交）：
        - Extended: 卖出（使用 bid 价格）
        - Lighter: 买入（使用 ask 价格）

        Args:
            position: 当前持仓
            quantity: 交易数量

        Returns:
            ExecutionResult 对象
        """
        start_time = time.time()
        logger.info(f"平仓[Taker]: 数量={quantity}")

        try:
            # Taker模式：使用市价单确保即时成交 (016-spread-optimize)
            results = await asyncio.gather(
                self._place_extended_order_taker("sell", quantity, None),
                self._place_lighter_order_taker("buy", quantity, None),
                return_exceptions=True
            )

            extended_result = results[0]
            lighter_result = results[1]

            # 检查是否有错误
            if isinstance(extended_result, Exception):
                return ExecutionResult(
                    error_message=f"Extended 订单失败: {extended_result}",
                    execution_time=time.time() - start_time
                )

            if isinstance(lighter_result, Exception):
                return ExecutionResult(
                    error_message=f"Lighter 订单失败: {lighter_result}",
                    execution_time=time.time() - start_time
                )

            # 等待订单成交
            execution_status = await self.wait_for_execution(
                extended_result["order_id"],
                lighter_result["order_id"],
                self.timeout
            )

            execution_time = time.time() - start_time

            # 处理执行结果
            if execution_status["both_filled"]:
                logger.info(
                    f"平仓成功[Taker]: Ext={extended_result['order_id']}, "
                    f"Lig={lighter_result['order_id']}, "
                    f"耗时={execution_time:.3f}秒"
                )
                return ExecutionResult(
                    success=True,
                    extended_order_id=extended_result["order_id"],
                    lighter_order_id=lighter_result["order_id"],
                    extended_price=extended_result.get("price"),
                    lighter_price=lighter_result.get("price"),
                    execution_time=execution_time,
                    extended_filled=True,
                    lighter_filled=True
                )
            else:
                logger.error(f"平仓失败或超时")
                return ExecutionResult(
                    error_message="平仓失败或超时",
                    execution_time=execution_time,
                    extended_filled=execution_status["extended_filled"],
                    lighter_filled=execution_status["lighter_filled"]
                )

        except Exception as e:
            logger.error(f"执行平仓失败: {e}")
            return ExecutionResult(
                error_message=str(e),
                execution_time=time.time() - start_time
            )

    async def wait_for_execution(
        self,
        extended_order_id: str,
        lighter_order_id: str,
        timeout: float = 3.0
    ) -> Dict[str, Any]:
        """
        等待订单执行

        重要变更：不再立即判定单边成交，而是等待到超时
        让系统进入OPENING_WAIT状态通过实际仓位检查来判断

        Args:
            extended_order_id: Extended 订单 ID
            lighter_order_id: Lighter 订单 ID
            timeout: 超时时间（秒）

        Returns:
            执行状态字典
        """
        start_time = time.time()
        check_interval = 0.1  # 100ms 检查一次

        extended_filled = False
        lighter_filled = False

        while time.time() - start_time < timeout:
            # 检查订单状态
            extended_status = await self._check_order_status(
                "extended", extended_order_id
            )
            lighter_status = await self._check_order_status(
                "lighter", lighter_order_id
            )

            extended_filled = extended_status.get("filled", False)
            lighter_filled = lighter_status.get("filled", False)

            if extended_filled and lighter_filled:
                # 两边都已成交，成功返回
                return {
                    "both_filled": True,
                    "extended_filled": True,
                    "lighter_filled": True,
                    "timeout": False
                }

            # 不再立即判定单边成交，继续等待
            # 即使检测到单边成交，也等待到超时
            # 这样可以让后续的OPENING_WAIT状态通过实际仓位来验证

            await asyncio.sleep(check_interval)

        # 超时：返回当前状态，让上层逻辑处理
        # 不管是单边成交还是都没成交，都进入OPENING_WAIT状态
        return {
            "both_filled": False,
            "extended_filled": extended_filled,
            "lighter_filled": lighter_filled,
            "timeout": True
        }

    async def rollback_position(
        self,
        exchange: str,
        quantity: Decimal,
        side: str
    ) -> bool:
        """
        强平（单边成交时使用）- Taker模式 (016-spread-optimize)

        Args:
            exchange: 需要强平的交易所
            quantity: 数量
            side: 强平方向（与原订单相反）

        Returns:
            是否成功
        """
        logger.warning(f"强平[Taker]: {exchange} {side} {quantity}")

        try:
            order_id = None
            if exchange == "extended":
                if side == "sell":
                    result = await self._place_extended_order_taker("sell", quantity, None)
                else:
                    result = await self._place_extended_order_taker("buy", quantity, None)
            else:  # lighter
                if side == "sell":
                    result = await self._place_lighter_order_taker("sell", quantity, None)
                else:
                    result = await self._place_lighter_order_taker("buy", quantity, None)

            if isinstance(result, Exception):
                logger.error(f"强平下单失败: {result}")
                return False

            order_id = result.get('order_id')

            # 等待强平订单成交（最多3秒）
            if order_id:
                execution_status = await self.wait_for_execution(
                    order_id if exchange == "extended" else None,
                    order_id if exchange == "lighter" else None,
                    timeout=3.0
                )

                if execution_status["both_filled"] or execution_status[f"{exchange}_filled"]:
                    logger.info(f"强平成交: {order_id}")
                    return True
                else:
                    logger.error(f"强平未成交/超时: {order_id}")
                    return False

            return False

        except Exception as e:
            logger.error(f"强平异常: {e}")
            return False

    # ========================================================================
    # 私有方法
    # ========================================================================

    async def _place_extended_order(
        self,
        side: str,
        quantity: Decimal,
        price: Optional[Decimal]
    ) -> Dict[str, Any]:
        """
        下 Extended 订单

        Args:
            side: "buy" 或 "sell"
            quantity: 数量
            price: 价格（None 表示市价单）

        Returns:
            订单结果字典
        """
        try:
            # 调用 Extended 客户端
            # 注意：这里需要根据实际的 Extended API 实现
            if price is None:
                # 市价单
                result = await self.extended_client.place_market_order(
                    side=side,
                    amount=quantity
                )
            else:
                # 限价单
                result = await self.extended_client.place_limit_order(
                    side=side,
                    amount=quantity,
                    price=price
                )

            return {
                "order_id": result.get("order_id"),
                "price": result.get("price")
            }

        except Exception as e:
            logger.error(f"Extended 订单失败: {e}")
            raise

    async def _place_lighter_order(
        self,
        side: str,
        quantity: Decimal,
        price: Optional[Decimal]
    ) -> Dict[str, Any]:
        """
        下 Lighter 订单

        Args:
            side: "buy" 或 "sell"
            quantity: 数量
            price: 价格（None 表示市价单）

        Returns:
            订单结果字典
        """
        try:
            # 调用 Lighter 客户端
            # 注意：这里需要根据实际的 Lighter API 实现
            if price is None:
                # 市价单
                result = await self.lighter_client.place_market_order(
                    side=side,
                    amount=quantity
                )
            else:
                # 限价单
                result = await self.lighter_client.place_limit_order(
                    side=side,
                    amount=quantity,
                    price=price
                )

            return {
                "order_id": result.get("order_id"),
                "price": result.get("price")
            }

        except Exception as e:
            logger.error(f"Lighter 订单失败: {e}")
            raise

    async def _place_extended_order_taker(
        self,
        side: str,
        quantity: Decimal,
        price: Optional[Decimal]
    ) -> Dict[str, Any]:
        """
        下 Extended Taker 订单 (016-spread-optimize)

        Taker模式：使用对手价确保即时成交
        - 买入：使用ask价格（或更高）
        - 卖出：使用bid价格（或更低）

        Args:
            side: "buy" 或 "sell"
            quantity: 数量
            price: 价格（None表示自动获取对手价，或指定具体价格）

        Returns:
            订单结果字典
        """
        try:
            contract_id = self.extended_client.config.contract_id

            # Taker模式：获取对手价确保即时成交
            if price is None:
                best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
                if side == "buy":
                    # 买入使用ask价格确保成交
                    price = best_ask
                else:
                    # 卖出使用bid价格确保成交
                    price = best_bid

            # 调用 Extended 客户端的 taker 订单方法
            # 使用 place_open_order 但不使用 post_only，且价格跨越价差
            result = await self.extended_client.place_taker_order(
                contract_id=contract_id,
                quantity=quantity,
                side=side,
                price=price
            )
            logger.debug(f"Ext Taker订单: {side} {quantity} @ {price}")

            if result.success:
                return {
                    "order_id": result.order_id,
                    "price": result.price if result.price else price
                }
            else:
                raise Exception(result.error_message)

        except Exception as e:
            logger.error(f"Extended Taker订单失败: {e}")
            raise

    async def _place_lighter_order_taker(
        self,
        side: str,
        quantity: Decimal,
        price: Optional[Decimal]
    ) -> Dict[str, Any]:
        """
        下 Lighter Taker 订单 (016-spread-optimize)

        Taker模式：使用对手价确保即时成交，设置post_only=False
        - 买入：使用ask价格
        - 卖出：使用bid价格

        Args:
            side: "buy" 或 "sell"
            quantity: 数量
            price: 价格（None表示自动使用对手价）

        Returns:
            订单结果字典
        """
        try:
            contract_id = self.lighter_client.config.contract_id

            # Taker模式：使用对手价
            if price is None:
                best_bid, best_ask = await self.lighter_client.fetch_bbo_prices(contract_id)
                if side == "buy":
                    # 买入用ask价格
                    price = best_ask
                else:
                    # 卖出用bid价格
                    price = best_bid

            # 调用 Lighter 客户端下taker订单（使用IOC立即成交或取消）
            result = await self.lighter_client.place_limit_order(
                contract_id=contract_id,
                quantity=quantity,
                price=price,
                side=side,
                time_in_force=0  # 0=IOC (Immediate or Cancel): taker模式
            )
            logger.debug(f"Lig Taker订单: {side} {quantity} @ {price}")

            if result.success:
                return {
                    "order_id": result.order_id,
                    "price": result.price if result.price else price
                }
            else:
                raise Exception(result.error_message)

        except Exception as e:
            logger.error(f"Lighter Taker订单失败: {e}")
            raise

    async def _check_order_status(
        self,
        exchange: str,
        order_id: str
    ) -> Dict[str, Any]:
        """
        检查订单状态

        Args:
            exchange: "extended" 或 "lighter"
            order_id: 订单 ID

        Returns:
            订单状态字典
        """
        try:
            if exchange == "extended":
                order_info = await self.extended_client.get_order_info(order_id)
            else:
                order_info = await self.lighter_client.get_order_info(order_id)

            if order_info is None:
                return {"filled": False}

            # OrderInfo has status and filled_size attributes
            is_filled = order_info.status in ['FILLED', 'PARTIALLY_FILLED']
            filled_price = order_info.price if is_filled else None
            filled_quantity = order_info.filled_size if is_filled else Decimal('0')

            return {
                "filled": is_filled and order_info.filled_size > 0,
                "price": filled_price,
                "quantity": filled_quantity,
                "status": order_info.status,
                "filled_size": order_info.filled_size
            }

        except Exception as e:
            logger.error(f"检查订单状态失败 ({exchange}): {e}")
            return {"filled": False}

    async def _cancel_orders(
        self,
        extended_order_id: str,
        lighter_order_id: str
    ) -> None:
        """
        取消订单

        Args:
            extended_order_id: Extended 订单 ID
            lighter_order_id: Lighter 订单 ID
        """
        try:
            await asyncio.gather(
                self.extended_client.cancel_order(extended_order_id),
                self.lighter_client.cancel_order(lighter_order_id),
                return_exceptions=True
            )
            logger.info("已取消未成交订单")
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
