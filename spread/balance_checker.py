"""
余额检测器模块 (003-spreading-improvements: User Story 4)

负责：
1. 查询两个交易所的可用余额
2. 计算开仓所需金额
3. 比较并返回检测结果

注意：此模块与 position_balance_checker.py 不同
- position_balance_checker.py: 开仓后检查两边仓位是否平衡
- balance_checker.py: 开仓前检查可用余额是否充足
"""

import logging
from decimal import Decimal
from typing import Optional

from models import BotConfig, BalanceAvailabilityResult


logger = logging.getLogger(__name__)


class BalanceAvailabilityChecker:
    """
    可用余额检测器

    在开仓前检查两个交易所的可用余额是否足够支持目标仓位，
    防止单边持仓风险。

    注意：这是开仓前的余额检测，与 PositionBalanceChecker 不同
    - PositionBalanceChecker: 开仓后检查两边仓位是否平衡
    - BalanceAvailabilityChecker: 开仓前检查可用余额是否充足

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
                leverage = getattr(self.config, 'leverage', Decimal("1"))
                # 计算最大可开仓位
                max_position = ext_available * leverage / ext_price
                logger.warning(
                    f"Extended余额不足: 可用{ext_available:.2f} < 需要{ext_required:.2f} USDT | 最大可开{max_position:.3f}"
                )
                return BalanceAvailabilityResult(
                    is_sufficient=False,
                    ext_available=ext_available,
                    ext_required=ext_required,
                    lig_available=lig_available,
                    lig_required=lig_required,
                    check_time=check_time,
                    failure_reason=f"Extended余额不足(最大{max_position:.3f})",
                    shortage_amount=shortage,
                    max_position=max_position
                )

            # 检查Lighter余额
            if lig_available < lig_required:
                shortage = lig_required - lig_available
                leverage = getattr(self.config, 'leverage', Decimal("1"))
                # 计算最大可开仓位
                max_position = lig_available * leverage / lig_price
                logger.warning(
                    f"Lighter余额不足: 可用{lig_available:.4f} < 需要{lig_required:.4f} 代币 | 最大可开{max_position:.3f}"
                )
                return BalanceAvailabilityResult(
                    is_sufficient=False,
                    ext_available=ext_available,
                    ext_required=ext_required,
                    lig_available=lig_available,
                    lig_required=lig_required,
                    check_time=check_time,
                    failure_reason=f"Lighter余额不足(最大{max_position:.3f})",
                    shortage_amount=shortage,
                    max_position=max_position
                )

            # 两个交易所余额都充足
            leverage = getattr(self.config, 'leverage', Decimal("1"))
            max_position_ext = ext_available * leverage / ext_price
            max_position_lig = lig_available * leverage / lig_price
            max_position = min(max_position_ext, max_position_lig)
            logger.info(
                f"余额充足 | Ext:{ext_available:.1f}/{ext_required:.1f} Lig:{lig_available:.2f}/{lig_required:.2f} 最大可开{max_position:.3f}"
            )
            return BalanceAvailabilityResult(
                is_sufficient=True,
                ext_available=ext_available,
                ext_required=ext_required,
                lig_available=lig_available,
                lig_required=lig_required,
                check_time=check_time,
                max_position=max_position
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
                failure_reason=f"余额检测异常: {str(e)}",
                max_position=Decimal("0")
            )

    async def check_open_capacity(
        self,
        order_notional_usd: Decimal,
        ext_price: Decimal,
        lig_price: Optional[Decimal] = None
    ) -> BalanceAvailabilityResult:
        """
        使用固定名义金额检查开仓可用仓位

        规则：
        - 可用余额 * 杠杆 >= order_notional_usd 则满足

        Args:
            order_notional_usd: 固定开仓名义金额（USDT）
            ext_price: Extended价格（用于计算最大可开数量）
            lig_price: Lighter价格（可选，默认使用ext_price）
        """
        import time

        check_time = time.time()

        if lig_price is None:
            lig_price = ext_price

        try:
            import asyncio

            ext_balance, lig_balance = await asyncio.gather(
                self._get_extended_balance(),
                self._get_lighter_balance(),
                return_exceptions=True
            )

            ext_available = ext_balance if isinstance(ext_balance, Decimal) else Decimal("0")
            lig_available = lig_balance if isinstance(lig_balance, Decimal) else Decimal("0")

            leverage = getattr(self.config, 'leverage', Decimal("1"))
            if leverage <= 0:
                leverage = Decimal("1")

            safety_buffer = getattr(self.config, "balance_safety_buffer", Decimal("0"))
            if safety_buffer < 0:
                safety_buffer = Decimal("0")

            required_notional = order_notional_usd * (Decimal("1") + safety_buffer)
            ext_capacity = ext_available * leverage
            lig_capacity = lig_available * leverage
            required_margin = required_notional / leverage

            logger.info(
                f"仓位检测 | 名义={order_notional_usd:.2f} | "
                f"缓冲={safety_buffer:.2%} | 杠杆={leverage}x | Ext可用={ext_available:.2f} "
                f"Lig可用={lig_available:.2f} | "
                f"Ext名义={ext_capacity:.2f} Lig名义={lig_capacity:.2f}"
            )

            if ext_capacity < required_notional:
                shortage = required_notional - ext_capacity
                max_position = ext_capacity / ext_price if ext_price > 0 else Decimal("0")
                logger.warning(
                    f"Extended仓位不足: 可用{ext_available:.2f} * {leverage}x < {required_notional:.2f} USDT"
                )
                return BalanceAvailabilityResult(
                    is_sufficient=False,
                    ext_available=ext_available,
                    ext_required=required_margin,
                    lig_available=lig_available,
                    lig_required=required_margin,
                    check_time=check_time,
                    failure_reason=f"Extended仓位不足(最大名义{ext_capacity:.2f})",
                    shortage_amount=shortage,
                    max_position=max_position
                )

            if lig_capacity < required_notional:
                shortage = required_notional - lig_capacity
                max_position = lig_capacity / lig_price if lig_price > 0 else Decimal("0")
                logger.warning(
                    f"Lighter仓位不足: 可用{lig_available:.2f} * {leverage}x < {required_notional:.2f} USDT"
                )
                return BalanceAvailabilityResult(
                    is_sufficient=False,
                    ext_available=ext_available,
                    ext_required=required_margin,
                    lig_available=lig_available,
                    lig_required=required_margin,
                    check_time=check_time,
                    failure_reason=f"Lighter仓位不足(最大名义{lig_capacity:.2f})",
                    shortage_amount=shortage,
                    max_position=max_position
                )

            max_position_ext = ext_capacity / ext_price if ext_price > 0 else Decimal("0")
            max_position_lig = lig_capacity / lig_price if lig_price > 0 else Decimal("0")
            max_position = min(max_position_ext, max_position_lig)

            logger.info(
                f"仓位充足 | Ext:{ext_available:.1f} Lig:{lig_available:.2f} "
                f"名义阈值{order_notional_usd:.2f} 最大可开{max_position:.3f}"
            )
            return BalanceAvailabilityResult(
                is_sufficient=True,
                ext_available=ext_available,
                ext_required=required_margin,
                lig_available=lig_available,
                lig_required=required_margin,
                check_time=check_time,
                max_position=max_position
            )

        except Exception as e:
            logger.error(f"仓位检测异常: {e}")
            return BalanceAvailabilityResult(
                is_sufficient=False,
                ext_available=Decimal("0"),
                ext_required=Decimal("0"),
                lig_available=Decimal("0"),
                lig_required=Decimal("0"),
                check_time=check_time,
                failure_reason=f"仓位检测异常: {str(e)}",
                max_position=Decimal("0")
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

            # ========== 使用正确的API方法 ==========
            # 参考 position_balance_monitor.py 的实现
            account = self.extended_client.perpetual_trading_client.account
            if hasattr(account, 'get_balance') and callable(getattr(account, 'get_balance')):
                result = await account.get_balance()

                if result and hasattr(result, 'data') and result.data:
                    balance_model = result.data
                    # 优先使用 available_for_trade（可用于交易的余额）
                    if hasattr(balance_model, 'available_for_trade'):
                        available = Decimal(str(balance_model.available_for_trade))
                        logger.debug(f"Extended可用余额: {available}")
                        return available
                    elif hasattr(balance_model, 'balance'):
                        available = Decimal(str(balance_model.balance))
                        logger.debug(f"Extended余额: {available}")
                        return available

            logger.warning("无法获取Extended余额信息")
            return Decimal("0")

        except Exception as e:
            logger.error(f"获取Extended余额失败: {e}")
            return Decimal("0")

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

            # ========== 使用正确的API方法 ==========
            # 参考 position_balance_monitor.py 的实现
            from lighter import AccountApi
            account_api = AccountApi(self.lighter_client.api_client)
            account_data = await account_api.account(
                by="index",
                value=str(self.lighter_client.account_index)
            )

            if not account_data or not account_data.accounts:
                logger.warning("无法获取Lighter账户信息")
                return Decimal("0")

            account_info = account_data.accounts[0]

            # 获取总资产价值作为总保证金
            total_balance = Decimal('0')
            if hasattr(account_info, 'total_asset_value'):
                total_balance = Decimal(str(account_info.total_asset_value))

            # 计算已使用的保证金（优先allocated_margin，否则用仓位*价格/杠杆估算）
            margin_used = Decimal('0')
            fallback_used = Decimal('0')
            bbo_price = None
            if hasattr(account_info, 'positions'):
                for pos in account_info.positions:
                    pos_value = getattr(pos, 'position', '0')
                    if str(pos_value) == '0':
                        continue

                    alloc = None
                    if hasattr(pos, 'allocated_margin'):
                        try:
                            alloc = Decimal(str(pos.allocated_margin))
                        except (ValueError, TypeError):
                            alloc = None
                    if alloc is not None and alloc > 0:
                        margin_used += alloc
                        continue

                    # allocated_margin不可用时，估算保证金
                    price = None
                    for attr in ("mark_price", "avg_price", "entry_price", "price", "index_price"):
                        if hasattr(pos, attr):
                            raw = getattr(pos, attr)
                            if raw is not None:
                                try:
                                    price = Decimal(str(raw))
                                    break
                                except (ValueError, TypeError):
                                    continue
                    if price is None or price <= 0:
                        try:
                            market_id = getattr(pos, "market_id", None)
                            if market_id is None or market_id == self.lighter_client.config.contract_id:
                                if bbo_price is None:
                                    lig_bid, lig_ask = await self.lighter_client.fetch_bbo_prices(
                                        self.lighter_client.config.contract_id
                                    )
                                    bbo_price = (lig_bid + lig_ask) / Decimal("2")
                                price = bbo_price
                        except Exception:
                            price = None
                    if price is None or price <= 0:
                        continue

                    try:
                        qty = abs(Decimal(str(pos_value)))
                    except (ValueError, TypeError):
                        continue

                    lev = getattr(self.config, 'leverage', Decimal("1"))
                    if lev <= 0:
                        lev = Decimal("1")
                    fallback_used += (qty * price) / lev

            if margin_used == 0 and fallback_used > 0:
                margin_used = fallback_used
                logger.debug(f"Lighter保证金使用估算: {margin_used}")

            # 可用保证金 = 总资产价值 - 已分配保证金
            available_balance = total_balance - margin_used
            if available_balance < 0:
                available_balance = Decimal('0')

            logger.debug(f"Lighter可用余额: total={total_balance}, margin_used={margin_used}, available={available_balance}")
            return available_balance

        except Exception as e:
            logger.error(f"获取Lighter余额失败: {e}")
            return Decimal("0")

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
