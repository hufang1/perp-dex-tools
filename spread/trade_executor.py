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
        spread: SpreadInfo
    ) -> ExecutionResult:
        """
        执行开仓（并发发送订单）

        开仓方向：
        - Extended: 买入（使用 spread.extended_ask_vwap）
        - Lighter: 卖出（使用 spread.lighter_bid_vwap）

        Args:
            quantity: 交易数量
            spread: 价差信息

        Returns:
            ExecutionResult 对象
        """
        start_time = time.time()
        logger.info(f"开始执行开仓: 数量={quantity}")

        try:
            # 并发发送两个订单
            results = await asyncio.gather(
                self._place_extended_order("buy", quantity, spread.extended_ask_vwap),
                self._place_lighter_order("sell", quantity, spread.lighter_bid_vwap),
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
                    f"开仓成功: Extended={extended_result['order_id']}, "
                    f"Lighter={lighter_result['order_id']}, "
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
                logger.error("开仓超时")
                # 尝试取消订单
                await self._cancel_orders(
                    extended_result["order_id"],
                    lighter_result["order_id"]
                )
                return ExecutionResult(
                    error_message="订单执行超时",
                    execution_time=execution_time,
                    extended_filled=execution_status["extended_filled"],
                    lighter_filled=execution_status["lighter_filled"]
                )
            else:
                # 单边成交
                logger.error(
                    f"单边成交: Extended={execution_status['extended_filled']}, "
                    f"Lighter={execution_status['lighter_filled']}"
                )
                return ExecutionResult(
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
        执行平仓（并发发送订单）

        平仓方向：
        - Extended: 卖出
        - Lighter: 买入

        Args:
            position: 当前持仓
            quantity: 交易数量

        Returns:
            ExecutionResult 对象
        """
        start_time = time.time()
        logger.info(f"开始执行平仓: 数量={quantity}")

        try:
            # 并发发送两个订单
            # 注意：平仓时需要获取当前市场价格
            # 这里简化处理，实际应该从订单簿获取 VWAP

            results = await asyncio.gather(
                self._place_extended_order("sell", quantity, None),  # 市价单
                self._place_lighter_order("buy", quantity, None),   # 市价单
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
                    f"平仓成功: Extended={extended_result['order_id']}, "
                    f"Lighter={lighter_result['order_id']}, "
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
                return {
                    "both_filled": True,
                    "extended_filled": True,
                    "lighter_filled": True,
                    "timeout": False
                }

            # 检查单边成交（异常情况）
            if extended_filled != lighter_filled:
                # 等待一小段时间确认
                await asyncio.sleep(0.2)

                # 重新检查
                extended_status = await self._check_order_status(
                    "extended", extended_order_id
                )
                lighter_status = await self._check_order_status(
                    "lighter", lighter_order_id
                )

                extended_filled = extended_status.get("filled", False)
                lighter_filled = lighter_status.get("filled", False)

                if extended_filled != lighter_filled:
                    return {
                        "both_filled": False,
                        "extended_filled": extended_filled,
                        "lighter_filled": lighter_filled,
                        "timeout": False
                    }

            await asyncio.sleep(check_interval)

        # 超时
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
        强平（单边成交时使用）

        Args:
            exchange: 需要强平的交易所
            quantity: 数量
            side: 强平方向（与原订单相反）

        Returns:
            是否成功
        """
        logger.warning(f"执行强平: {exchange} {side} {quantity}")

        try:
            if exchange == "extended":
                if side == "buy":
                    result = await self._place_extended_order("sell", quantity, None)
                else:
                    result = await self._place_extended_order("buy", quantity, None)
            else:  # lighter
                if side == "buy":
                    result = await self._place_lighter_order("sell", quantity, None)
                else:
                    result = await self._place_lighter_order("buy", quantity, None)

            if isinstance(result, Exception):
                logger.error(f"强平失败: {result}")
                return False

            logger.info(f"强平成功: {result.get('order_id')}")
            return True

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
                status = await self.extended_client.get_order_status(order_id)
            else:
                status = await self.lighter_client.get_order_status(order_id)

            return {
                "filled": status.get("filled", False),
                "price": status.get("filled_price"),
                "quantity": status.get("filled_quantity")
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
