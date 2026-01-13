"""
仓位平衡检测与保护模块

负责：
1. 开仓后验证两边仓位数量是否相等
2. 缓冲期内持续监控仓位状态
3. 检测到不平衡时立即执行紧急平仓
4. 处理一侧交易所失败的情况
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime

from models import BalanceCheckResult


logger = logging.getLogger(__name__)


class PositionBalanceChecker:
    """
    仓位平衡检测器

    开仓后验证两边仓位，不平衡时立即平仓保护
    """

    def __init__(self, lighter_client, extended_client, trade_executor, buffer_seconds: float = 3.0):
        """
        初始化检测器

        Args:
            lighter_client: Lighter交易所客户端
            extended_client: Extended交易所客户端
            trade_executor: 交易执行器
            buffer_seconds: 缓冲期时长（秒）
        """
        self.lighter_client = lighter_client
        self.extended_client = extended_client
        self.trade_executor = trade_executor
        self.buffer_seconds = buffer_seconds
        self._monitor_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start_monitoring(self, expected_quantity: Decimal) -> BalanceCheckResult:
        """
        启动缓冲期监控

        Args:
            expected_quantity: 预期的持仓数量（两边应该相等）

        Returns:
            最终的平衡检查结果
        """
        self._stop_event.clear()
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(expected_quantity)
        )

        try:
            result = await self._monitor_task
            return result
        except asyncio.CancelledError:
            # 监控被取消（紧急平仓）
            return BalanceCheckResult(
                is_balanced=False,
                ext_quantity=Decimal("0"),
                lig_quantity=Decimal("0"),
                check_time=datetime.now().timestamp(),
            )

    async def _monitor_loop(self, expected_quantity: Decimal) -> BalanceCheckResult:
        """
        监控循环

        Args:
            expected_quantity: 预期的持仓数量

        Returns:
            最终的平衡检查结果
        """
        start_time = asyncio.get_event_loop().time()
        check_interval = 0.5  # 每0.5秒检查一次

        while not self._stop_event.is_set():
            try:
                # 执行平衡检查
                result = await self.verify_balance(expected_quantity)

                if result.is_balanced:
                    # 平衡，检查是否超过缓冲期
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= self.buffer_seconds:
                        logger.info(result.format_log())
                        return result
                else:
                    # 不平衡，立即触发紧急平仓
                    logger.error(result.format_log())
                    await self._emergency_close()
                    return result

                # 等待下一次检查
                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"仓位平衡检查异常: {e}")
                await asyncio.sleep(check_interval)

        # 如果循环结束（未触发平仓或超时），执行最后一次检查
        return await self.verify_balance(expected_quantity)

    async def verify_balance(self, expected_quantity: Decimal) -> BalanceCheckResult:
        """
        验证仓位平衡

        Args:
            expected_quantity: 预期的持仓数量

        Returns:
            平衡检查结果
        """
        try:
            # 查询两个交易所的仓位
            ext_qty = await self._query_extended_position()
            lig_qty = await self._query_lighter_position()

            # 检查是否平衡（允许小的精度误差）
            tolerance = Decimal("0.0001")
            is_balanced = abs(ext_qty - lig_qty) <= tolerance

            # 计算差异
            quantity_diff = abs(ext_qty - lig_qty)
            diff_percentage = quantity_diff / expected_quantity if expected_quantity > 0 else Decimal("0")

            return BalanceCheckResult(
                is_balanced=is_balanced,
                ext_quantity=ext_qty,
                lig_quantity=lig_qty,
                check_time=datetime.now().timestamp(),
                quantity_diff=quantity_diff,
                diff_percentage=diff_percentage,
            )

        except Exception as e:
            logger.error(f"查询仓位失败: {e}")
            # 查询失败视为不平衡，需要紧急平仓
            return BalanceCheckResult(
                is_balanced=False,
                ext_quantity=Decimal("0"),
                lig_quantity=Decimal("0"),
                check_time=datetime.now().timestamp(),
            )

    async def _query_extended_position(self) -> Decimal:
        """
        查询Extended仓位

        Returns:
            持仓数量（查询失败返回0）
        """
        try:
            # TODO: 调用extended_client的持仓查询接口
            # 这里需要根据实际的API实现
            # position = await self.extended_client.get_position()
            # return Decimal(str(position.get('quantity', 0)))

            # 临时实现：返回0表示未实现
            logger.warning("Extended仓位查询未实现，临时返回0")
            return Decimal("0")

        except Exception as e:
            logger.error(f"查询Extended仓位异常: {e}")
            return Decimal("0")

    async def _query_lighter_position(self) -> Decimal:
        """
        查询Lighter仓位

        Returns:
            持仓数量（查询失败返回0）
        """
        try:
            # TODO: 调用lighter_client的持仓查询接口
            # 这里需要根据实际的API实现
            # position = await self.lighter_client.get_position()
            # return Decimal(str(position.get('quantity', 0)))

            # 临时实现：返回0表示未实现
            logger.warning("Lighter仓位查询未实现，临时返回0")
            return Decimal("0")

        except Exception as e:
            logger.error(f"查询Lighter仓位异常: {e}")
            return Decimal("0")

    async def _emergency_close(self) -> None:
        """
        紧急平仓

        检测到不平衡时立即平掉所有仓位
        """
        logger.error("执行紧急平仓...")
        try:
            # TODO: 调用trade_executor执行紧急平仓
            # 需要实现一个平掉两边所有仓位的逻辑
            logger.warning("紧急平仓功能需要根据实际API实现")
        except Exception as e:
            logger.error(f"紧急平仓失败: {e}")

    def stop_monitoring(self) -> None:
        """停止监控"""
        self._stop_event.set()
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
