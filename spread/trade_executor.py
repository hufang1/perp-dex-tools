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

from models import SpreadInfo, Position, Trade, PositionState, CancelOrderResult
from exceptions import (
    ExecutionTimeoutError,
    SingleSideExecutionError,
    RiskValidationFailedError,
    OrderCancellationError,
)
from price_snapshot import PriceSnapshot


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

        # logger.info(f"交易执行器初始化: 超时={timeout}秒")

    async def execute_open_position(
        self,
        quantity: Decimal,
        spread
    ) -> ExecutionResult:
        """
        执行开仓（001-fix-spread-price优化：统一价格获取+滑点保护）

        开仓方向（Taker模式，即时成交）：
        - Extended: 买入（使用 ask 价格 + 0.2%滑点保护）
        - Lighter: 卖出（使用 bid 价格 + 0.2%滑点保护）

        价格同步机制：
        1. 在execute_open_position层面统一并发获取两个交易所BBO价格
        2. 记录时间戳并计算time_delta（目标<10ms）
        3. 创建PriceSnapshot并验证有效性
        4. 计算带0.2%滑点保护的taker价格
        5. 验证价格一致性（ext买入 < lig卖出）

        Args:
            quantity: 交易数量
            spread: 价差信息（仅用于日志记录，实际价格重新获取）

        Returns:
            ExecutionResult 对象
        """
        start_time = time.time()

        try:
            # Step 1: 并发获取两个交易所的BBO价格
            ext_bbo_future = self.extended_client.fetch_bbo_prices(
                self.extended_client.config.contract_id
            )
            lig_bbo_future = self.lighter_client.fetch_bbo_prices(
                self.lighter_client.config.contract_id
            )

            # 获取Ext价格并记录时间戳
            ext_fetch_time = time.time()
            ext_bid, ext_ask = await ext_bbo_future

            # 获取Lig价格并记录时间戳
            lig_fetch_time = time.time()
            lig_bid, lig_ask = await lig_bbo_future

            # 计算时间差
            time_delta = abs(lig_fetch_time - ext_fetch_time)

            # Step 2: 创建价格快照
            price_snapshot = PriceSnapshot(
                ext_bid=ext_bid,
                ext_ask=ext_ask,
                ext_timestamp=ext_fetch_time,
                lig_bid=lig_bid,
                lig_ask=lig_ask,
                lig_timestamp=lig_fetch_time,
                time_delta=time_delta
            )

            # Step 3: 验证价格快照
            if not price_snapshot.is_valid():
                logger.warning(
                    f"价格快照无效: time_delta={time_delta*1000:.1f}ms (阈值<10ms), "
                    f"跳过此次开仓"
                )
                return ExecutionResult(
                    success=False,
                    error_message=f"价格快照无效: time_delta={time_delta*1000:.1f}ms",
                    execution_time=time.time() - start_time
                )

            # Step 4: 计算taker价格（0.2%滑点）
            ext_price, lig_price = price_snapshot.calculate_taker_prices()

            # Step 5: 验证价格一致性
            # if not price_snapshot.validate_price_consistency():
            #     logger.error(
            #         f"价差异常: ext买入={ext_price:.2f} >= lig卖出={lig_price:.2f}, "
            #         f"跳过此次开仓（套利无盈利空间）"
            #     )
            #     return ExecutionResult(
            #         success=False,
            #         error_message=f"价差异常: ext={ext_price:.2f} >= lig={lig_price:.2f}",
            #         execution_time=time.time() - start_time
            #     )

            # Step 6: 记录价格同步日志
            spread_pct = (ext_price / lig_price - 1) * 100 if lig_price > 0 else 0
            logger.info(
                f"[价格同步] "
                f"ext_bid={ext_bid:.2f}, ext_ask={ext_ask:.2f}, "
                f"lig_bid={lig_bid:.2f}, lig_ask={lig_ask:.2f}, "
                f"time_delta={time_delta*1000:.1f}ms, "
                f"ext_price={ext_price:.2f}, lig_price={lig_price:.2f}, "
                f"spread={spread_pct:.2f}%"
            )

            # Step 7: 并发发送订单（使用计算好的价格）
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
                    f"[开仓成功] "
                    f"ext_order_id={extended_result['order_id']}, "
                    f"lig_order_id={lighter_result['order_id']}, "
                    f"ext_price={extended_result.get('price'):.2f}, "
                    f"lig_price={lighter_result.get('price'):.2f}, "
                    f"耗时={execution_time:.3f}s"
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
                logger.error(
                    f"单边成交: Extended={execution_status['extended_filled']}, "
                    f"Lighter={execution_status['lighter_filled']}"
                )
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
        # logger.info(f"平仓[Taker]: 数量={quantity}")

        try:
            # 以交易所真实仓位为上限，避免 reduce-only 超量
            ext_position = await self.extended_client.get_account_positions()
            lig_position = await self.lighter_client.get_account_positions()
            tolerance = Decimal("0.001")
            ext_qty = min(abs(ext_position), quantity)
            lig_qty = min(abs(lig_position), quantity)

            if ext_qty < tolerance and lig_qty < tolerance:
                return ExecutionResult(
                    success=True,
                    execution_time=time.time() - start_time,
                    extended_filled=True,
                    lighter_filled=True
                )

            tasks = []
            if ext_qty >= tolerance:
                tasks.append(self._place_extended_order_taker("sell", ext_qty, None, reduce_only=True))
            else:
                tasks.append(None)
            if lig_qty >= tolerance:
                tasks.append(self._place_lighter_order_taker("buy", lig_qty, None, reduce_only=True))
            else:
                tasks.append(None)

            results = await asyncio.gather(
                *(t for t in tasks if t is not None),
                return_exceptions=True
            )

            extended_result = None
            lighter_result = None
            idx = 0
            if tasks[0] is not None:
                extended_result = results[idx]
                idx += 1
            if tasks[1] is not None:
                lighter_result = results[idx]

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
                extended_result["order_id"] if isinstance(extended_result, dict) else None,
                lighter_result["order_id"] if isinstance(lighter_result, dict) else None,
                self.timeout
            )

            execution_time = time.time() - start_time

            # 处理执行结果
            if execution_status["both_filled"]:
                # logger.info(
                #     f"平仓成功[Taker]: Ext={extended_result['order_id']}, "
                #     f"Lig={lighter_result['order_id']}, "
                #     f"耗时={execution_time:.3f}秒"
                # )
                return ExecutionResult(
                    success=True,
                    extended_order_id=extended_result["order_id"] if isinstance(extended_result, dict) else None,
                    lighter_order_id=lighter_result["order_id"] if isinstance(lighter_result, dict) else None,
                    extended_price=extended_result.get("price") if isinstance(extended_result, dict) else None,
                    lighter_price=lighter_result.get("price") if isinstance(lighter_result, dict) else None,
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
        extended_order_id: Optional[str],
        lighter_order_id: Optional[str],
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

        Raises:
            Exception: 订单查询连续失败时抛出异常
        """
        # 若两边都没有订单，直接返回完成
        if extended_order_id is None and lighter_order_id is None:
            return {
                "both_filled": True,
                "extended_filled": True,
                "lighter_filled": True,
                "timeout": False
            }

        start_time = time.time()
        check_interval = 0.1  # 100ms 检查一次

        extended_filled = extended_order_id is None
        lighter_filled = lighter_order_id is None
        # 连续失败计数
        extended_fail_count = 0
        lighter_fail_count = 0
        max_fail_count = 10  # 连续10次失败则抛出异常

        while time.time() - start_time < timeout:
            # 检查订单状态（分别检查，一边失败不影响另一边）
            # Extended
            if extended_order_id is not None:
                try:
                    extended_status = await self._check_order_status(
                        "extended", extended_order_id,
                        allow_retries=False  # 不允许重试，失败就抛出异常
                    )
                    extended_fail_count = 0  # 成功则重置计数
                except Exception as e:
                    extended_fail_count += 1
                    logger.warning(f"Extended订单查询失败 ({extended_fail_count}/{max_fail_count}): {e}")
                    extended_status = {"filled": False}
                    if extended_fail_count >= max_fail_count:
                        logger.warning(f"Extended订单查询连续失败{max_fail_count}次，转入仓位确认")
                        return {
                            "both_filled": False,
                            "extended_filled": extended_filled,
                            "lighter_filled": lighter_filled,
                            "timeout": True
                        }
                extended_filled = extended_status.get("filled", False)

            # Lighter
            if lighter_order_id is not None:
                try:
                    lighter_status = await self._check_order_status(
                        "lighter", lighter_order_id,
                        allow_retries=False
                    )
                    lighter_fail_count = 0
                except Exception as e:
                    lighter_fail_count += 1
                    logger.warning(f"Lighter订单查询失败 ({lighter_fail_count}/{max_fail_count}): {e}")
                    lighter_status = {"filled": False}
                    if lighter_fail_count >= max_fail_count:
                        logger.warning(f"Lighter订单查询连续失败{max_fail_count}次，转入仓位确认")
                        return {
                            "both_filled": False,
                            "extended_filled": extended_filled,
                            "lighter_filled": lighter_filled,
                            "timeout": True
                        }
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
        # logger.warning(f"强平[Taker]: {exchange} {side} {quantity}")

        try:
            order_id = None
            if exchange == "extended":
                if side == "sell":
                    result = await self._place_extended_order_taker("sell", quantity, None, reduce_only=True)
                else:
                    result = await self._place_extended_order_taker("buy", quantity, None, reduce_only=True)
            else:  # lighter
                if side == "sell":
                    result = await self._place_lighter_order_taker("sell", quantity, None, reduce_only=True)
                else:
                    result = await self._place_lighter_order_taker("buy", quantity, None, reduce_only=True)

            if isinstance(result, Exception):
                logger.error(f"强平下单失败: {result}")
                return False

            order_id = result.get('order_id')

            # 等待强平订单成交（最多3秒）
            if order_id:
                try:
                    execution_status = await self.wait_for_execution(
                        order_id if exchange == "extended" else None,
                        order_id if exchange == "lighter" else None,
                        timeout=3.0
                    )

                    if execution_status["both_filled"] or execution_status[f"{exchange}_filled"]:
                        # logger.info(f"强平成交: {order_id}")
                        return True
                    else:
                        # 订单超时，但可能已经成交（API查询有延迟）
                        # 等待1秒后通过实际仓位判断
                        await asyncio.sleep(1.0)
                except Exception as e:
                    # wait_for_execution 抛出异常（通常是API异常）
                    # 订单可能已经成交，等待2秒后通过实际仓位判断
                    logger.warning(f"强平订单状态查询异常: {e}，等待2秒后检查实际仓位")
                    await asyncio.sleep(2.0)

            # 通过实际仓位判断是否强平成功
            client = self.extended_client if exchange == "extended" else self.lighter_client
            actual_position = await client.get_account_positions()
            tolerance = Decimal("0.001")

            # 强平成功：仓位接近0或已反向（如果原有多头，强平后应为空头或0）
            if abs(actual_position) < tolerance:
                logger.info(f"{exchange}强平成功（仓位确认）: {actual_position}")
                return True
            else:
                # 仍有仓位，强平失败
                logger.error(f"{exchange}强平失败（仍有仓位）: {actual_position}")
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
        price: Optional[Decimal],
        reduce_only: bool = False
    ) -> Dict[str, Any]:
        """
        下 Extended Taker 订单 (001-fix-spread-price优化：加入0.05%滑点保护)

        Taker模式：使用对手价确保即时成交
        - 买入：使用ask价格 + 0.05%滑点保护 (ask * 1.0005)
        - 卖出：使用bid价格 - 0.05%滑点保护 (bid * 0.9995)

        注意：滑点从0.2%降低到0.05%，避免吃掉小价差的利润空间

        Args:
            side: "buy" 或 "sell"
            quantity: 数量
            price: 价格（None表示自动计算带滑点保护的价格，或指定具体价格）

        Returns:
            订单结果字典
        """
        try:
            contract_id = self.extended_client.config.contract_id

            # Taker模式：获取对手价并加入0.2%滑点保护确保即时成交
            if price is None:
                best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
                if side == "buy":
                    # 买入使用ask价格 + 0.05%滑点保护
                    price = best_ask * Decimal('1.0002')
                else:
                    # 卖出使用bid价格 - 0.05%滑点保护
                    price = best_bid * Decimal('0.9998')

            # 调用 Extended 客户端的 taker 订单方法
            # 使用 place_open_order 但不使用 post_only，且价格跨越价差
            result = await self.extended_client.place_taker_order(
                contract_id=contract_id,
                quantity=quantity,
                side=side,
                price=price,
                reduce_only=reduce_only
            )
            logger.info(f"Ext Taker订单: {side} {quantity} @ {price:.2f}")

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
        price: Optional[Decimal],
        reduce_only: bool = False
    ) -> Dict[str, Any]:
        """
        下 Lighter Taker 订单 (016-spread-optimize)

        Taker模式：跨越价差确保即时成交
        - 买入：ask * 1.002（高于ask 0.2%）
        - 卖出：bid * 0.998（低于bid 0.2%）

        Args:
            side: "buy" 或 "sell"
            quantity: 数量
            price: 价格（None表示自动计算跨越价差的价格）

        Returns:
            订单结果字典
        """
        try:
            contract_id = self.lighter_client.config.contract_id

            # Taker模式：计算跨越价差的价格
            if price is None:
                best_bid, best_ask = await self.lighter_client.fetch_bbo_prices(contract_id)

                if side == "buy":
                    # 买入用ask * 1.002，确保跨越价差
                    price = best_ask * Decimal('1.002')
                else:
                    # 卖出用bid * 0.998，确保跨越价差
                    price = best_bid * Decimal('0.998')

            # 调用 Lighter 客户端下taker订单（使用IOC立即成交或取消）
            result = await self.lighter_client.place_limit_order(
                contract_id=contract_id,
                quantity=quantity,
                price=price,
                side=side,
                time_in_force=0,  # 0=IOC (Immediate or Cancel): taker模式
                reduce_only=reduce_only,
            )
            logger.info(f"Lig Taker订单: {side} {quantity} @ {price}")

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
        order_id: str,
        allow_retries: bool = True
    ) -> Dict[str, Any]:
        """
        检查订单状态

        Args:
            exchange: "extended" 或 "lighter"
            order_id: 订单 ID
            allow_retries: 是否允许重试（首次查询允许重试，连续失败则抛出异常）

        Returns:
            订单状态字典

        Raises:
            Exception: 订单查询连续失败时抛出异常
        """
        # 检查订单ID是否有效
        if order_id is None or order_id == "None":
            error_msg = f"{exchange}订单ID无效: {order_id}"
            if not allow_retries:
                raise Exception(error_msg)
            logger.warning(error_msg)
            return {"filled": False}

        try:
            if exchange == "extended":
                order_info = await self.extended_client.get_order_info(order_id)
            else:
                order_info = await self.lighter_client.get_order_info(order_id)

            if order_info is None:
                error_msg = f"{exchange}订单查询失败: order_id={order_id}"
                if not allow_retries:
                    raise Exception(error_msg)
                logger.warning(error_msg)
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
            error_msg = f"{exchange}订单查询异常: {e}"
            if not allow_retries:
                raise Exception(error_msg)
            logger.error(error_msg)
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
            # logger.info("已取消未成交订单")
        except Exception as e:
            logger.error(f"取消订单失败: {e}")

    # ========== 新增方法 (017-ext-maker-mode) ==========

    async def place_maker_open_order(
        self,
        quantity: Decimal
    ) -> ExecutionResult:
        """
        下Extended Maker开仓订单（串行执行：Extended先成交，然后Lighter对冲）

        Maker模式特点：
        - Extended使用Maker挂单（post_only）获得~0%手续费
        - 挂单价格位于BBO（最佳买价/卖价）
        - 需要等待订单成交（通过WebSocket监控）

        Args:
            quantity: 交易数量

        Returns:
            ExecutionResult 包含订单ID和价格
        """
        start_time = time.time()
        try:
            # 使用Extended客户端的place_maker_order方法
            order_result = await self.extended_client.place_maker_order(
                contract_id=self.extended_client.config.contract_id,
                quantity=quantity,
                direction='buy'  # 开仓时Extended买入
            )

            if not order_result.success:
                return ExecutionResult(
                    success=False,
                    error_message=order_result.error_message,
                    execution_time=time.time() - start_time
                )

            logger.info(
                f"✅ Extended Maker开仓订单已挂出 | "
                f"order_id={order_result.order_id} | "
                f"price={order_result.price} | "
                f"quantity={order_result.size} | "
                f"status={order_result.status}"
            )

            return ExecutionResult(
                success=True,
                extended_order_id=order_result.order_id,
                extended_price=order_result.price,
                execution_time=time.time() - start_time,
                extended_filled=False  # Maker订单需要等待成交
            )

        except Exception as e:
            logger.error(f"Extended Maker开仓订单失败: {e}")
            return ExecutionResult(
                success=False,
                error_message=str(e),
                execution_time=time.time() - start_time
            )

    async def place_maker_close_order(
        self,
        quantity: Decimal
    ) -> ExecutionResult:
        """
        下Extended Maker平仓订单（串行执行：Extended先成交，然后Lighter对冲）

        Maker模式特点：
        - Extended使用Maker挂单（post_only）获得~0%手续费
        - 挂单价格位于BBO（最佳买价/卖价）
        - 需要等待订单成交（通过WebSocket监控）

        Args:
            quantity: 交易数量

        Returns:
            ExecutionResult 包含订单ID和价格
        """
        start_time = time.time()
        try:
            # 使用Extended客户端的place_maker_order方法
            order_result = await self.extended_client.place_maker_order(
                contract_id=self.extended_client.config.contract_id,
                quantity=quantity,
                direction='sell',  # 平仓时Extended卖出
                reduce_only=True,
            )

            if not order_result.success:
                return ExecutionResult(
                    success=False,
                    error_message=order_result.error_message,
                    execution_time=time.time() - start_time
                )

            logger.info(
                f"✅ Extended Maker平仓订单已挂出 | "
                f"order_id={order_result.order_id} | "
                f"price={order_result.price} | "
                f"quantity={order_result.size} | "
                f"status={order_result.status}"
            )

            return ExecutionResult(
                success=True,
                extended_order_id=order_result.order_id,
                extended_price=order_result.price,
                execution_time=time.time() - start_time,
                extended_filled=False  # Maker订单需要等待成交
            )

        except Exception as e:
            logger.error(f"Extended Maker平仓订单失败: {e}")
            return ExecutionResult(
                success=False,
                error_message=str(e),
                execution_time=time.time() - start_time
            )

    async def execute_lighter_hedge(
        self,
        quantity: Decimal,
        side: str,  # 'buy' or 'sell'
        ext_filled_price: Decimal,
        price_override: Optional[Decimal] = None,
        reduce_only: bool = False
    ) -> ExecutionResult:
        """
        在Lighter执行对冲订单（Taker模式，即时成交）

        在Extended Maker订单成交后，立即在Lighter执行对冲。

        Args:
            quantity: 对冲数量
            side: 对冲方向（开仓时sell，平仓时buy）
            ext_filled_price: Extended成交价格（用于日志）

        Returns:
            ExecutionResult 包含订单ID和价格
        """
        start_time = time.time()
        try:
            if price_override is not None:
                lig_price = price_override
            else:
                # 获取Lighter BBO价格
                lig_bid, lig_ask = await self.lighter_client.fetch_bbo_prices(
                    self.lighter_client.config.contract_id
                )

                # 根据方向选择价格
                if side.lower() == 'buy':
                    lig_price = lig_ask  # 买入使用ask价格
                else:
                    lig_price = lig_bid  # 卖出使用bid价格

            # 下Lighter Taker订单
            lighter_result = await self._place_lighter_order_taker(side, quantity, lig_price, reduce_only=reduce_only)

            if isinstance(lighter_result, Exception):
                return ExecutionResult(
                    success=False,
                    error_message=f"Lighter对冲订单失败: {lighter_result}",
                    execution_time=time.time() - start_time
                )

            # ========== 修改：只查询Lighter订单状态，不再查询Extended ==========
            # 等待Lighter订单成交（使用较短超时时间）
            lighter_success = await self._wait_for_lighter_order(lighter_result["order_id"], 3.0)

            execution_time = time.time() - start_time

            if lighter_success:
                logger.info(
                    f"✅ Lighter对冲成功 | "
                    f"order_id={lighter_result['order_id']} | "
                    f"side={side} | "
                    f"price={lighter_result.get('price')} | "
                    f"quantity={quantity} | "
                    f"ext_filled_price={ext_filled_price} | "
                    f"耗时={execution_time:.3f}s"
                )
                return ExecutionResult(
                    success=True,
                    lighter_order_id=lighter_result["order_id"],
                    lighter_price=lighter_result.get("price"),
                    execution_time=execution_time,
                    lighter_filled=True
                )
            else:
                logger.error(f"❌ Lighter对冲失败: 未完全成交或超时")
                return ExecutionResult(
                    success=False,
                    lighter_order_id=lighter_result["order_id"],
                    lighter_price=lighter_result.get("price"),
                    error_message="Lighter对冲订单未完全成交或超时",
                    execution_time=execution_time,
                    lighter_filled=False
                )

        except Exception as e:
            logger.error(f"Lighter对冲异常: {e}")
            return ExecutionResult(
                success=False,
                error_message=str(e),
                execution_time=time.time() - start_time
            )

    async def _wait_for_lighter_order(self, lighter_order_id: str, timeout: float = 6.0) -> bool:
        """
        等待Lighter订单成交（专用于Maker模式对冲）

        注意：Lighter的IOC订单会立即成交或取消，无法通过订单查询API获取状态。
        我们通过查询账户持仓来验证对冲是否成功。

        Args:
            lighter_order_id: Lighter订单ID（仅用于日志记录）
            timeout: 超时时间（秒）

        Returns:
            True if 对冲成功，False otherwise
        """
        import time
        start_time = time.time()

        end_time = start_time + timeout
        await asyncio.sleep(0.5)

        while time.time() < end_time:
            try:
                lighter_position = await self.lighter_client.get_account_positions()
                if lighter_position > 0:
                    logger.info(
                        f"✅ Lighter对冲验证成功 | "
                        f"order_id={lighter_order_id} | "
                        f"持仓={lighter_position}"
                    )
                    return True
            except Exception as e:
                logger.error(f"查询Lighter持仓失败: {e}")
                logger.warning("⚠️ 无法验证Lighter对冲，稍后重试")
            await asyncio.sleep(0.5)

        logger.warning(
            f"⚠️ Lighter对冲超时 | "
            f"order_id={lighter_order_id} | "
            f"timeout={timeout}s"
        )
        return False

    # ========== 新增方法 (003-spreading-improvements): 取消订单验证 ==========

    async def cancel_maker_order_with_verification(
        self,
        order_id: str,
        exchange: str,
        max_retries: int = 5,
        retry_interval: float = 2.0,
        verify_timeout: float = 5.0
    ) -> CancelOrderResult:
        """
        取消Maker订单并验证取消成功（防止重复挂单）

        在修改挂单价格时，必须先取消旧订单并验证取消成功后才能创建新订单。
        使用REST API轮询验证取消状态，确保订单真正被取消。

        Args:
            order_id: 订单ID
            exchange: 交易所 ("extended" 或 "lighter")
            max_retries: 最大重试次数（默认5次）
            retry_interval: 重试间隔（秒，默认2秒）
            verify_timeout: 验证超时时间（秒，默认5秒）

        Returns:
            CancelOrderResult 取消操作结果

        Raises:
            OrderCancellationError: 取消失败时抛出
        """
        start_time = time.time()
        attempts = 0
        final_status = None
        error_message = None

        logger.info(
            f"开始取消订单 | ID={order_id[:12]}... | "
            f"exchange={exchange} | max_retries={max_retries}"
        )

        while attempts < max_retries:
            attempts += 1
            attempt_start = time.time()

            try:
                # Step 1: 调用交易所API取消订单
                cancel_success = False
                if exchange == "extended":
                    result = await self.extended_client.cancel_order(order_id)
                    cancel_success = result.success if hasattr(result, 'success') else result
                elif exchange == "lighter":
                    result = await self.lighter_client.cancel_order(order_id)
                    cancel_success = result.success if hasattr(result, 'success') else result
                else:
                    error_message = f"不支持的交易所: {exchange}"
                    logger.error(error_message)
                    break

                # 如果取消API调用失败
                if not cancel_success:
                    logger.warning(
                        f"取消API调用失败 | 尝试={attempts}/{max_retries} | "
                        f"ID={order_id[:12]}..."
                    )
                    await asyncio.sleep(retry_interval)
                    continue

                # Step 2: 验证订单已真正取消（通过REST API轮询）
                is_canceled = await self._verify_order_cancellation(
                    order_id=order_id,
                    exchange=exchange,
                    timeout=verify_timeout
                )

                attempt_time = time.time() - attempt_start

                if is_canceled:
                    total_time = time.time() - start_time
                    logger.info(
                        f"订单取消成功 | ID={order_id[:12]}... | "
                        f"尝试={attempts}次 | 耗时={total_time:.1f}秒"
                    )
                    return CancelOrderResult(
                        order_id=order_id,
                        canceled=True,
                        attempts=attempts,
                        total_time=total_time,
                        final_status="CANCELED",
                        error_message=None
                    )
                else:
                    logger.warning(
                        f"取消验证失败 | 尝试={attempts}/{max_retries} | "
                        f"ID={order_id[:12]}... | 耗时={attempt_time:.1f}秒"
                    )
                    # 继续重试
                    await asyncio.sleep(retry_interval)

            except asyncio.TimeoutError:
                logger.warning(
                    f"取消验证超时 | 尝试={attempts}/{max_retries} | "
                    f"timeout={verify_timeout}秒"
                )
                await asyncio.sleep(retry_interval)
            except Exception as e:
                logger.error(
                    f"取消订单异常 | 尝试={attempts}/{max_retries} | "
                    f"ID={order_id[:12]}... | 错误={e}"
                )
                await asyncio.sleep(retry_interval)

        # 所有重试都失败
        total_time = time.time() - start_time

        # 尝试获取最终状态
        try:
            final_status = await self._get_order_status_for_verification(order_id, exchange)
        except Exception:
            final_status = "UNKNOWN"

        raise OrderCancellationError(
            order_id=order_id,
            attempts=attempts,
            final_status=final_status,
            error_message=error_message or "超过最大重试次数"
        )

    async def _verify_order_cancellation(
        self,
        order_id: str,
        exchange: str,
        timeout: float = 5.0
    ) -> bool:
        """
        验证订单已取消（私有方法）

        通过REST API轮询查询订单状态，确认订单已被取消或成交。

        Args:
            order_id: 订单ID
            exchange: 交易所 ("extended" 或 "lighter")
            timeout: 验证超时时间（秒）

        Returns:
            True if 订单已取消/成交（不再活跃），False if 订单仍然开放
        """
        start_time = time.time()
        check_interval = 0.5  # 每500ms检查一次

        while time.time() - start_time < timeout:
            try:
                status = await self._get_order_status_for_verification(order_id, exchange)

                # 检查订单状态
                if status in ["CANCELED", "FILLED", "EXPIRED", "REJECTED"]:
                    logger.debug(
                        f"订单确认{status} | ID={order_id[:12]}... | "
                        f"耗时={time.time() - start_time:.1f}秒"
                    )
                    return True
                elif status == "OPEN":
                    # 订单仍然开放，继续等待
                    logger.debug(
                        f"订单仍开放 | ID={order_id[:12]}... | "
                        f"elapsed={time.time() - start_time:.1f}秒"
                    )
                    await asyncio.sleep(check_interval)
                elif status == "PARTIALLY_FILLED":
                    # 部分成交，视为仍然活跃
                    logger.debug(
                        f"订单部分成交 | ID={order_id[:12]}... | "
                        f"elapsed={time.time() - start_time:.1f}秒"
                    )
                    await asyncio.sleep(check_interval)
                else:
                    # 未知状态
                    logger.warning(
                        f"订单状态未知 | ID={order_id[:12]}... | status={status}"
                    )
                    await asyncio.sleep(check_interval)

            except Exception as e:
                logger.error(f"验证取消状态异常: {e}")
                await asyncio.sleep(check_interval)

        # 超时：无法确认订单已取消
        logger.warning(
            f"验证取消超时 | ID={order_id[:12]}... | timeout={timeout}秒"
        )
        return False

    async def _get_order_status_for_verification(
        self,
        order_id: str,
        exchange: str
    ) -> str:
        """
        获取订单状态用于取消验证（私有方法）

        Args:
            order_id: 订单ID
            exchange: 交易所 ("extended" 或 "lighter")

        Returns:
            订单状态字符串: "OPEN", "CANCELED", "FILLED", "PARTIALLY_FILLED", etc.

        Raises:
            Exception: 查询失败时抛出
        """
        try:
            if exchange == "extended":
                order_info = await self.extended_client.get_order_info(order_id)
            elif exchange == "lighter":
                order_info = await self.lighter_client.get_order_info(order_id)
            else:
                raise ValueError(f"不支持的交易所: {exchange}")

            if order_info is None:
                raise Exception(f"订单查询返回None: {order_id}")

            # 返回订单状态
            return order_info.status

        except Exception as e:
            logger.error(f"获取订单状态失败 | ID={order_id[:12]}... | exchange={exchange} | 错误={e}")
            raise

    async def cancel_extended_maker_order(
        self,
        order_id: str
    ) -> bool:
        """
        取消Extended Maker订单

        Args:
            order_id: Extended订单ID

        Returns:
            True if successful, False otherwise
        """
        try:
            result = await self.extended_client.cancel_order(order_id)
            if result.success:
                logger.info(f"✅ Extended Maker订单已取消: order_id={order_id}")
                return True
            else:
                logger.warning(f"⚠️ Extended Maker订单取消失败: {result.error_message}")
                return False
        except Exception as e:
            logger.error(f"❌ Extended Maker订单取消异常: {e}")
            return False

    async def get_extended_order_info(
        self,
        order_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        查询Extended订单信息

        Args:
            order_id: Extended订单ID

        Returns:
            订单信息字典或None
        """
        try:
            order_info = await self.extended_client.get_order_info(order_id)
            if order_info:
                return {
                    'order_id': order_info.order_id,
                    'status': order_info.status,
                    'filled_size': order_info.filled_size,
                    'price': order_info.price,
                    'side': order_info.side
                }
            return None
        except Exception as e:
            logger.error(f"查询Extended订单失败: {e}")
            return None
