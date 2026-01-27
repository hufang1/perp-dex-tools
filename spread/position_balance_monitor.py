"""
仓位余额监控模块

用于查询和监控 Lighter 和 Extended 两个交易所的：
1. 当前持仓数量
2. 可用余额（保证金）
3. 最大可开仓数量
4. 剩余可用仓位

主要用于风控，确保在开仓前有足够的可用余额。
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime

from models import PositionBalanceSnapshot, ExchangePositionBalance

logger = logging.getLogger(__name__)


class PositionBalanceMonitor:
    """
    仓位余额监控器

    负责查询和缓存两个交易所的仓位余额信息
    """

    def __init__(self, lighter_client, extended_client, config):
        """
        初始化仓位余额监控器

        Args:
            lighter_client: Lighter交易所客户端
            extended_client: Extended交易所客户端
            config: 机器人配置对象
        """
        self.lighter_client = lighter_client
        self.extended_client = extended_client
        self.config = config

        # 缓存快照
        self._cached_snapshot: Optional[PositionBalanceSnapshot] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 5.0  # 缓存有效期5秒

        # 配置参数（默认值，可根据实际情况调整）
        self._lighter_leverage = Decimal("20")  # Lighter默认10倍杠杆
        self._extended_leverage = Decimal("20")  # Extended默认10倍杠杆

    async def get_position_balance(self, force_refresh: bool = False) -> PositionBalanceSnapshot:
        """
        获取仓位余额快照

        Args:
            force_refresh: 是否强制刷新（忽略缓存）

        Returns:
            PositionBalanceSnapshot: 仓位余额快照
        """
        current_time = datetime.now().timestamp()

        # 检查缓存
        if (not force_refresh and
            self._cached_snapshot is not None and
            current_time - self._cache_time < self._cache_ttl):
            return self._cached_snapshot

        # 并发查询两个交易所的仓位余额
        try:
            lighter_balance, extended_balance = await asyncio.gather(
                self._get_lighter_balance(),
                self._get_extended_balance(),
                return_exceptions=True
            )

            # 处理异常结果
            if isinstance(lighter_balance, Exception):
                logger.warning(f"获取Lighter余额失败: {lighter_balance}")
                lighter_balance = None
            if isinstance(extended_balance, Exception):
                logger.warning(f"获取Extended余额失败: {extended_balance}")
                extended_balance = None

            # 创建快照
            snapshot = PositionBalanceSnapshot(
                lighter=lighter_balance,
                extended=extended_balance,
                timestamp=current_time
            )

            # 更新缓存
            self._cached_snapshot = snapshot
            self._cache_time = current_time

            return snapshot

        except Exception as e:
            logger.error(f"获取仓位余额失败: {e}")
            # 返回旧的缓存（如果有）
            if self._cached_snapshot is not None:
                return self._cached_snapshot
            # 返回空快照
            return PositionBalanceSnapshot()

    async def _get_lighter_balance(self) -> Optional[ExchangePositionBalance]:
        """
        获取Lighter交易所的仓位余额

        Returns:
            ExchangePositionBalance: Lighter仓位余额，查询失败返回None
        """
        try:
            # 获取当前持仓
            current_position = await self.lighter_client.get_account_positions()

            # 获取账户信息（包含保证金余额）
            from lighter import AccountApi
            account_api = AccountApi(self.lighter_client.api_client)
            account_data = await account_api.account(
                by="index",
                value=str(self.lighter_client.account_index)
            )

            if not account_data or not account_data.accounts:
                logger.warning("无法获取Lighter账户信息")
                return None

            account_info = account_data.accounts[0]

            # 从数据结构看，Lighter返回的数据包含：
            # - total_asset_value: 总资产价值（保证金）
            # - positions: 持仓列表，每个持仓有 allocated_margin（已分配保证金）
            # - additional_properties.assets: 资产列表（LIT、USDC等）

            # 获取总资产价值作为总保证金
            total_balance = Decimal('0')
            if hasattr(account_info, 'total_asset_value'):
                total_balance = Decimal(str(account_info.total_asset_value))

            # 计算已使用的保证金（优先allocated_margin，否则估算）
            margin_used = Decimal('0')
            fallback_used = Decimal('0')
            allocated_details = []
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
                        symbol = getattr(pos, 'symbol', '?')
                        allocated_details.append(f"{symbol}:{alloc}")
                        continue

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

                    lev = self._lighter_leverage if self._lighter_leverage > 0 else Decimal("1")
                    fallback_used += (qty * price) / lev

            if margin_used == 0 and fallback_used > 0:
                margin_used = fallback_used
                allocated_details.append(f"estimated:{margin_used}")

            # 打印调试信息
            # debug日志已移除，避免刷屏

            # 可用保证金 = 总资产价值 - 已分配保证金
            available_balance = total_balance - margin_used
            if available_balance < 0:
                available_balance = Decimal('0')

            # 最大可开仓数量 = 可用保证金 * 杠杆
            max_position = available_balance * self._lighter_leverage

            return ExchangePositionBalance(
                exchange="lighter",
                current_position=current_position,
                available_balance=available_balance,
                total_balance=total_balance,
                max_position=max_position,
                leverage=self._lighter_leverage,
                margin_used=margin_used,
                timestamp=datetime.now().timestamp()
            )

        except Exception as e:
            logger.error(f"获取Lighter仓位余额失败: {e}", exc_info=True)
            return None

    async def _get_extended_balance(self) -> Optional[ExchangePositionBalance]:
        """
        获取Extended交易所的仓位余额

        Returns:
            ExchangePositionBalance: Extended仓位余额，查询失败返回None
        """
        try:
            # 获取当前持仓
            current_position = await self.extended_client.get_account_positions()

            available_balance = Decimal('0')
            total_balance = Decimal('0')
            balance_found = False

            # 使用SDK的get_balance方法
            account = self.extended_client.perpetual_trading_client.account
            if hasattr(account, 'get_balance') and callable(getattr(account, 'get_balance')):
                result = await account.get_balance()

                if result and hasattr(result, 'data') and result.data:
                    balance_model = result.data
                    # 使用 available_for_trade（可用于交易的余额）
                    if hasattr(balance_model, 'available_for_trade'):
                        available_balance = balance_model.available_for_trade
                        balance_found = True
                    elif hasattr(balance_model, 'balance'):
                        available_balance = balance_model.balance
                        balance_found = True
                    if hasattr(balance_model, 'balance'):
                        total_balance = balance_model.balance
                    elif hasattr(balance_model, 'available_for_trade'):
                        total_balance = balance_model.available_for_trade

            if not balance_found:
                logger.warning("无法获取Extended余额信息")
            if total_balance == 0 and available_balance > 0:
                total_balance = available_balance

            # 最大可开仓数量 = 可用余额 * 杠杆
            max_position = available_balance * self._extended_leverage

            return ExchangePositionBalance(
                exchange="extended",
                current_position=current_position,
                available_balance=available_balance,
                total_balance=total_balance,
                max_position=max_position,
                leverage=self._extended_leverage,
                margin_used=Decimal('0'),
                timestamp=datetime.now().timestamp()
            )

        except Exception as e:
            logger.error(f"获取Extended仓位余额失败: {e}", exc_info=True)
            return None

    async def can_open_position(self, quantity: Decimal) -> tuple[bool, str]:
        """
        检查是否有足够的余额开仓

        Args:
            quantity: 要开仓的数量

        Returns:
            (can_open, reason): 是否可以开仓及原因说明
        """
        snapshot = await self.get_position_balance()

        if not snapshot.is_valid():
            return False, "无法获取仓位余额信息"

        # 检查Lighter
        if snapshot.lighter.remaining_capacity < quantity:
            return (
                False,
                f"Lighter余额不足: 剩余={snapshot.lighter.remaining_capacity:.4f}, 需要={quantity:.4f}"
            )

        # 检查Extended
        if snapshot.extended.remaining_capacity < quantity:
            return (
                False,
                f"Extended余额不足: 剩余={snapshot.extended.remaining_capacity:.4f}, 需要={quantity:.4f}"
            )

        return True, "余额充足"

    def format_status_log(self) -> str:
        """
        格式化状态日志（紧凑格式）

        Returns:
            格式化的状态日志字符串
        """
        if self._cached_snapshot is None:
            return "Lig: - | Ext: -"

        return self._cached_snapshot.format_compact_log()
