"""
余额检测器模块 (003-spreading-improvements: User Story 4)

负责：
1. 查询两个交易所的可用余额
2. 计算开仓所需金额
3. 比较并返回检测结果
"""

import logging
from decimal import Decimal
from typing import Optional

from models import BotConfig, BalanceAvailabilityResult


logger = logging.getLogger(__name__)


class BalanceChecker:
    """
    可用余额检测器

    在开仓前检查两个交易所的可用余额是否足够支持目标仓位，
    防止单边持仓风险。

    职责：
    1. 查询Extended的可用USDT余额
    2. 查询Lighter的可用代币余额
    3. 计算开仓所需金额（考虑杠杆）
    4. 比较并返回检测结果
    """

    def __init__(
        self,
        lighter_client,
        extended_client,
        config: BotConfig
    ):
        """
        初始化余额检测器

        Args:
            lighter_client: Lighter交易所客户端
            extended_client: Extended交易所客户端
            config: 机器人配置
        """
        self.lighter_client = lighter_client
        self.extended_client = extended_client
        self.config = config

    async def check_before_opening(
        self,
        target_quantity: Decimal,
        ext_price: Decimal,
        lig_price: Optional[Decimal] = None
    ) -> BalanceAvailabilityResult:
        """
        开仓前检查两个交易所的可用余额

        Args:
            target_quantity: 目标开仓数量
            ext_price: Extended开仓价格
            lig_price: Lighter开仓价格（可选，默认使用ext_price）

        Returns:
            BalanceAvailabilityResult: 检测结果

        异常处理：
            - API调用失败时返回 is_sufficient=False
            - 不抛出异常，确保调用方可以优雅降级
        """
        import time

        check_time = time.time()

        # 默认使用相同价格
        if lig_price is None:
            lig_price = ext_price

        try:
            # 并发查询两个交易所的余额
            import asyncio

            ext_balance, lig_balance = await asyncio.gather(
                self._get_extended_balance(),
                self._get_lighter_balance(),
                return_exceptions=True
            )

            # 处理查询结果
            ext_available = ext_balance if isinstance(ext_balance, Decimal) else Decimal("0")
            lig_available = lig_balance if isinstance(lig_balance, Decimal) else Decimal("0")

            # 计算所需金额
            ext_required = self._calculate_required_amount(target_quantity, ext_price)
            lig_required = self._calculate_required_amount(target_quantity, lig_price)

            # 检查Extended余额
            if ext_available < ext_required:
                shortage = ext_required - ext_available
                logger.warning(
                    f"Extended余额不足: 可用{ext_available:.2f} < 需要{ext_required:.2f} USDT"
                )
                return BalanceAvailabilityResult(
                    is_sufficient=False,
                    ext_available=ext_available,
                    ext_required=ext_required,
                    lig_available=lig_available,
                    lig_required=lig_required,
                    check_time=check_time,
                    failure_reason="Extended USDT余额不足",
                    shortage_amount=shortage
                )

            # 检查Lighter余额
            if lig_available < lig_required:
                shortage = lig_required - lig_available
                logger.warning(
                    f"Lighter余额不足: 可用{lig_available:.4f} < 需要{lig_required:.4f} 代币"
                )
                return BalanceAvailabilityResult(
                    is_sufficient=False,
                    ext_available=ext_available,
                    ext_required=ext_required,
                    lig_available=lig_available,
                    lig_required=lig_required,
                    check_time=check_time,
                    failure_reason="Lighter代币余额不足",
                    shortage_amount=shortage
                )

            # 两个交易所余额都充足
            logger.info(
                f"余额检测通过 | Ext: {ext_available:.2f}/{ext_required:.2f} USDT | "
                f"Lig: {lig_available:.4f}/{lig_required:.4f} 代币"
            )
            return BalanceAvailabilityResult(
                is_sufficient=True,
                ext_available=ext_available,
                ext_required=ext_required,
                lig_available=lig_available,
                lig_required=lig_required,
                check_time=check_time
            )

        except Exception as e:
            logger.error(f"余额检测异常: {e}")
            return BalanceAvailabilityResult(
                is_sufficient=False,
                ext_available=Decimal("0"),
                ext_required=Decimal("0"),
                lig_available=Decimal("0"),
                lig_required=Decimal("0"),
                check_time=check_time,
                failure_reason=f"余额检测异常: {str(e)}"
            )

    async def _get_extended_balance(self) -> Decimal:
        """
        获取Extended可用USDT余额

        Returns:
            可用USDT余额

        Raises:
            ExchangeAPIError: API调用失败
        """
        try:
            if self.extended_client is None:
                logger.warning("Extended客户端未初始化")
                return Decimal("0")

            # 调用交易所API获取余额
            balance_info = await self.extended_client.get_account_balance()

            # 解析余额数据（根据实际API响应格式调整）
            if isinstance(balance_info, dict):
                available = balance_info.get('available', balance_info.get('available_balance', '0'))
                return Decimal(str(available))

            logger.warning(f"Extended余额数据格式异常: {type(balance_info)}")
            return Decimal("0")

        except Exception as e:
            logger.error(f"获取Extended余额失败: {e}")
            raise

    async def _get_lighter_balance(self, symbol: str = "ETH") -> Decimal:
        """
        获取Lighter可用代币余额

        Args:
            symbol: 交易对符号（如 "ETH"）

        Returns:
            可用代币余额

        Raises:
            ExchangeAPIError: API调用失败
        """
        try:
            if self.lighter_client is None:
                logger.warning("Lighter客户端未初始化")
                return Decimal("0")

            # 调用交易所API获取余额
            balance_info = await self.lighter_client.get_account_balance()

            # 解析余额数据（根据实际API响应格式调整）
            if isinstance(balance_info, dict):
                # 尝试获取指定代币的余额
                if 'balances' in balance_info:
                    for bal in balance_info['balances']:
                        if bal.get('asset') == symbol:
                            return Decimal(str(bal.get('available', '0')))
                # 或者直接返回总余额
                available = balance_info.get('available', balance_info.get('available_balance', '0'))
                return Decimal(str(available))

            logger.warning(f"Lighter余额数据格式异常: {type(balance_info)}")
            return Decimal("0")

        except Exception as e:
            logger.error(f"获取Lighter余额失败: {e}")
            raise

    def _calculate_required_amount(
        self,
        quantity: Decimal,
        price: Decimal
    ) -> Decimal:
        """
        计算所需金额（考虑杠杆）

        Args:
            quantity: 数量
            price: 价格

        Returns:
            所需金额（保证金）
        """
        # 计算名义价值
        notional_value = quantity * price

        # 考虑杠杆（如果配置了杠杆）
        leverage = getattr(self.config, 'leverage', Decimal("1"))
        if leverage > 1:
            required_margin = notional_value / leverage
        else:
            required_margin = notional_value

        # 添加安全缓冲（10%）
        safety_buffer = required_margin * Decimal("0.1")
        total_required = required_margin + safety_buffer

        logger.debug(
            f"计算所需金额: 数量={quantity:.4f}, 价格={price:.2f}, "
            f"名义价值={notional_value:.2f}, 杠杆={leverage}x, "
            f"保证金={required_margin:.2f}, 缓冲={safety_buffer:.2f}, "
            f"总计={total_required:.2f}"
        )

        return total_required
