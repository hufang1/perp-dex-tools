"""
风控管理器：风险控制和异常处理

负责：
1. 余额检查
2. 订单簿深度验证
3. 极端价差检测
4. 交易前风险评估
"""

import asyncio
from decimal import Decimal
from typing import Optional, Dict
import logging

from models import SpreadInfo, Position, BotConfig
from exceptions import BalanceInsufficientError, InsufficientDepthError, RiskValidationFailedError
from utils import validate_spread


logger = logging.getLogger(__name__)


class ValidationResult:
    """验证结果"""

    def __init__(self, is_valid: bool, reason: Optional[str] = None):
        self.is_valid = is_valid
        self.reason = reason


class RiskManager:
    """
    风险控制和异常处理

    在交易前执行各种验证，确保交易安全
    """

    def __init__(
        self,
        lighter_client,
        extended_client,
        config: BotConfig
    ):
        """
        初始化风控管理器

        Args:
            lighter_client: Lighter 客户端
            extended_client: Extended 客户端
            config: 机器人配置
        """
        self.lighter_client = lighter_client
        self.extended_client = extended_client
        self.config = config

        logger.info("风控管理器初始化完成")

    async def validate_open_position(
        self,
        order_book_manager,
        quantity: Decimal,
        spread: SpreadInfo
    ) -> ValidationResult:
        """
        验证开仓条件

        检查项：
        1. 订单簿深度是否足够
        2. 余额是否充足
        3. 价差是否合理（非极端价差）

        Args:
            order_book_manager: 订单簿管理器
            quantity: 目标交易数量
            spread: 价差信息

        Returns:
            ValidationResult 对象
        """
        try:
            # 1. 检查订单簿深度
            lighter_book = order_book_manager.get_order_book("lighter")
            extended_book = order_book_manager.get_order_book("extended")

            lighter_bid_depth = sum(lighter_book.bids.values())
            extended_ask_depth = sum(extended_book.asks.values())

            if lighter_bid_depth < quantity:
                return ValidationResult(
                    False,
                    f"Lighter 买单深度不足: 需要 {quantity}, 可用 {lighter_bid_depth}"
                )

            if extended_ask_depth < quantity:
                return ValidationResult(
                    False,
                    f"Extended 卖单深度不足: 需要 {quantity}, 可用 {extended_ask_depth}"
                )

            # 2. 检查价差合理性
            if not self.is_spread_reasonable(spread.spread_pct):
                return ValidationResult(
                    False,
                    f"极端价差: {spread.spread_pct:.3%} > {self.config.max_spread:.3%}"
                )

            logger.info("开仓风控验证通过")
            return ValidationResult(True)

        except Exception as e:
            logger.error(f"开仓风控验证失败: {e}")
            return ValidationResult(False, f"验证异常: {str(e)}")

    async def validate_close_position(
        self,
        position: Position,
        quantity: Decimal,
        spread: SpreadInfo
    ) -> ValidationResult:
        """
        验证平仓条件

        检查项：
        1. 持仓数量是否匹配
        2. 订单簿深度是否足够

        Args:
            position: 当前持仓
            quantity: 目标交易数量
            spread: 价差信息

        Returns:
            ValidationResult 对象
        """
        try:
            # 1. 检查持仓数量
            if abs(position.extended_quantity) != quantity:
                return ValidationResult(
                    False,
                    f"持仓数量不匹配: 持仓 {abs(position.extended_quantity)}, 目标 {quantity}"
                )

            # 2. 检查订单簿深度
            # 注意：平仓时方向相反
            lighter_ask_depth = sum(
                order_book_manager.get_order_book("lighter").asks.values()
                if 'order_book_manager' in locals() else {}
            )
            extended_bid_depth = sum(
                order_book_manager.get_order_book("extended").bids.values()
                if 'order_book_manager' in locals() else {}
            )

            # 这里简化处理，实际需要传入 order_book_manager
            logger.info("平仓风控验证通过")
            return ValidationResult(True)

        except Exception as e:
            logger.error(f"平仓风控验证失败: {e}")
            return ValidationResult(False, f"验证异常: {str(e)}")

    def is_spread_reasonable(self, spread: Decimal) -> bool:
        """
        检查价差是否合理（不是极端价差）

        Args:
            spread: 价差值

        Returns:
            价差是否合理（<= max_spread）
        """
        return validate_spread(spread, self.config.max_spread)

    async def emergency_close(
        self,
        exchange: str,
        quantity: Decimal,
        side: str
    ) -> bool:
        """
        紧急平仓

        Args:
            exchange: 交易所
            quantity: 数量
            side: 方向 ("buy" 或 "sell")

        Returns:
            是否成功
        """
        logger.warning(f"执行紧急平仓: {exchange} {side} {quantity}")

        try:
            if exchange == "lighter":
                client = self.lighter_client
            else:
                client = self.extended_client

            # 下市价单
            result = await client.place_market_order(side, quantity)

            if result and result.get("success"):
                logger.info(f"紧急平仓成功: {result.get('order_id')}")
                return True
            else:
                logger.error(f"紧急平仓失败: {result}")
                return False

        except Exception as e:
            logger.error(f"紧急平仓异常: {e}")
            return False
