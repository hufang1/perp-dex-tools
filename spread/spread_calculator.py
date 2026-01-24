"""
价差计算器：计算两个交易所之间的价差

负责：
1. 计算开仓价差（Extended Ask VWAP vs Lighter Bid VWAP）
2. 计算平仓价差（Lighter Ask VWAP vs Extended Bid VWAP）
3. 判断是否满足开仓/平仓条件（平仓使用利润口径）
4. 检测极端价差
"""

import asyncio
from decimal import Decimal
from typing import Optional
from datetime import datetime
import logging

from models import SpreadInfo, Position, PositionState
from exceptions import InsufficientDepthError, ExtremeSpreadError
from utils import calculate_spread_percentage, validate_spread


logger = logging.getLogger(__name__)


class SpreadCalculator:
    """
    计算两个交易所之间的价差

    套利策略：
    - 开仓：Extended 买入（Ask）+ Lighter 卖出（Bid）
      价差 = (Lighter_Bid_VWAP - Extended_Ask_VWAP) / Extended_Ask_VWAP

    - 平仓：Extended 卖出（Bid）+ Lighter 买入（Ask）
      价差 = (Lighter_Ask_VWAP - Extended_Bid_VWAP) / Extended_Bid_VWAP
    """

    def __init__(
        self,
        open_threshold: Decimal = Decimal("0.0002"),
        slippage_buffer: Decimal = Decimal("0.0005"),
        min_profit: Decimal = Decimal("0.0001"),
        max_spread: Decimal = Decimal("0.05")
    ):
        """
        初始化价差计算器

        Args:
            open_threshold: 开仓阈值（默认 0.2%）
            slippage_buffer: 滑点保护（默认 0.05%）
        min_profit: 最小利润阈值（默认 0.1%）
            max_spread: 极端价差阈值（默认 5%）
        """
        self.open_threshold = open_threshold
        self.slippage_buffer = slippage_buffer
        self.min_profit = min_profit
        self.max_spread = max_spread

        logger.info(
            f"价差计算器初始化: 开仓阈值={open_threshold:.3%}, "
            f"滑点保护={slippage_buffer:.3%}, "
            f"最小利润={min_profit:.3%}, "
            f"最大价差={max_spread:.3%}"
        )

    async def calculate_open_spread(
        self,
        order_book_manager,
        quantity: Decimal
    ) -> Optional[SpreadInfo]:
        """
        计算开仓价差

        开仓方向：Extended 买入 + Lighter 卖出
        价差公式：(Lighter_Bid_VWAP - Extended_Ask_VWAP) / Extended_Ask_VWAP

        Args:
            order_book_manager: 订单簿管理器
            quantity: 目标交易数量

        Returns:
            SpreadInfo 对象，如果价差无效返回 None
        """
        try:
            # 并发计算两个 VWAP
            lighter_bid_vwap, extended_ask_vwap = await asyncio.gather(
                order_book_manager.calculate_vwap("lighter", quantity, "sell"),
                order_book_manager.calculate_vwap("extended", quantity, "buy"),
                return_exceptions=True
            )

            # 检查是否有错误
            if isinstance(lighter_bid_vwap, Exception):
                logger.error(f"计算 Lighter Bid VWAP 失败: {lighter_bid_vwap}")
                return None

            if isinstance(extended_ask_vwap, Exception):
                logger.error(f"计算 Extended Ask VWAP 失败: {extended_ask_vwap}")
                return None

            # 计算价差
            spread = calculate_spread_percentage(lighter_bid_vwap, extended_ask_vwap)

            if spread is None:
                logger.warning("无法计算价差")
                return None

            # 检查价差是否为正（有利可图）
            if spread <= 0:
                logger.debug(f"价差为负或零: {spread:.4%}")
                return None

            # 检查是否为极端价差
            if not self.is_spread_reasonable(spread):
                logger.warning(
                    f"检测到极端价差: {spread:.3%}，跳过此次机会"
                )
                return None

            spread_info = SpreadInfo(
                open_spread=spread,
                lighter_bid_vwap=lighter_bid_vwap,
                extended_ask_vwap=extended_ask_vwap,
                timestamp=datetime.now(),
                is_reasonable=True
            )

            logger.info(
                f"开仓价差: {spread:.3%} "
                f"(Lighter Bid: {lighter_bid_vwap}, "
                f"Extended Ask: {extended_ask_vwap})"
            )

            return spread_info

        except InsufficientDepthError as e:
            logger.warning(f"订单簿深度不足: {e}")
            return None
        except Exception as e:
            logger.error(f"计算开仓价差失败: {e}")
            return None

    async def calculate_close_spread(
        self,
        order_book_manager,
        quantity: Decimal
    ) -> Optional[SpreadInfo]:
        """
        计算平仓价差

        平仓方向：Extended 卖出 + Lighter 买入
        价差公式：(Lighter_Ask_VWAP - Extended_Bid_VWAP) / Extended_Bid_VWAP

        Args:
            order_book_manager: 订单簿管理器
            quantity: 目标交易数量

        Returns:
            SpreadInfo 对象，如果价差无效返回 None
        """
        try:
            # 并发计算两个 VWAP
            lighter_ask_vwap, extended_bid_vwap = await asyncio.gather(
                order_book_manager.calculate_vwap("lighter", quantity, "buy"),
                order_book_manager.calculate_vwap("extended", quantity, "sell"),
                return_exceptions=True
            )

            # 检查是否有错误
            if isinstance(lighter_ask_vwap, Exception):
                logger.error(f"计算 Lighter Ask VWAP 失败: {lighter_ask_vwap}")
                return None

            if isinstance(extended_bid_vwap, Exception):
                logger.error(f"计算 Extended Bid VWAP 失败: {extended_bid_vwap}")
                return None

            # 计算价差
            spread = calculate_spread_percentage(lighter_ask_vwap, extended_bid_vwap)

            if spread is None:
                logger.warning("无法计算平仓价差")
                return None

            spread_info = SpreadInfo(
                close_spread=spread,
                lighter_ask_vwap=lighter_ask_vwap,
                extended_bid_vwap=extended_bid_vwap,
                timestamp=datetime.now(),
                is_reasonable=True
            )

            logger.debug(
                f"平仓价差: {spread:.3%} "
                f"(Lighter Ask: {lighter_ask_vwap}, "
                f"Extended Bid: {extended_bid_vwap})"
            )

            return spread_info

        except InsufficientDepthError as e:
            logger.warning(f"订单簿深度不足: {e}")
            return None
        except Exception as e:
            logger.error(f"计算平仓价差失败: {e}")
            return None

    def should_open(self, spread: Decimal) -> bool:
        """
        判断是否应该开仓

        条件：价差 >= 开仓阈值 + 滑点保护

        Args:
            spread: 当前价差

        Returns:
            是否满足开仓条件
        """
        required_spread = self.open_threshold + self.slippage_buffer
        should = spread >= required_spread

        if should:
            logger.info(
                f"价差 {spread:.3%} 满足开仓条件 "
                f"(阈值: {self.open_threshold:.3%} + 滑点: {self.slippage_buffer:.3%})"
            )
        else:
            logger.debug(
                f"价差 {spread:.3%} 不满足开仓条件 "
                f"(需要: {required_spread:.3%})"
            )

        return should

    def should_close(
        self,
        open_spread: Decimal,
        close_spread: Decimal,
        position: Position
    ) -> bool:
        """
        判断是否应该平仓

        条件：利润 = 开仓价差 - 平仓价差 >= 最小利润
        即：利润达到目标

        Args:
            open_spread: 开仓价差
            close_spread: 当前平仓价差
            position: 当前持仓

        Returns:
            是否满足平仓条件
        """
        # 计算价差收敛幅度
        spread_convergence = open_spread - close_spread

        # 检查是否达到最小利润
        should = spread_convergence >= self.min_profit

        if should:
            logger.info(
                f"价差收敛 {spread_convergence:.3%} "
                f"(开仓: {open_spread:.3%} -> 平仓: {close_spread:.3%}) "
                f"满足平仓条件 (最小利润: {self.min_profit:.3%})"
            )
        else:
            logger.debug(
                f"价差收敛 {spread_convergence:.3%} 不满足平仓条件 "
                f"(需要: {self.min_profit:.3%})"
            )

        return should

    def is_spread_reasonable(self, spread: Decimal) -> bool:
        """
        检查价差是否合理（不是极端价差）

        Args:
            spread: 价差值

        Returns:
            价差是否合理（<= max_spread）
        """
        reasonable = validate_spread(spread, self.max_spread)

        if not reasonable:
            logger.warning(
                f"极端价差检测: {spread:.3%} > {self.max_spread:.3%}"
            )

        return reasonable

    def calculate_profit_potential(
        self,
        open_spread: Decimal,
        quantity: Decimal,
        entry_price: Decimal
    ) -> Decimal:
        """
        计算潜在利润

        Args:
            open_spread: 开仓价差
            quantity: 交易数量
            entry_price: 入场价格

        Returns:
            预期利润（扣除手续费）
        """
        # 简化计算：价差 * 价格 * 数量
        # 实际利润取决于平仓价差
        gross_profit = open_spread * entry_price * quantity

        # 扣除手续费（Lighter 0% + Extended 0.025% * 2）
        # 一开一平，Extended 双向手续费
        fees = entry_price * quantity * Decimal("0.0005")  # 0.05%

        net_profit = gross_profit - fees

        logger.debug(
            f"利润估算: 毛利={gross_profit:.2f}, 手续费={fees:.2f}, "
            f"净利={net_profit:.2f}"
        )

        return net_profit
