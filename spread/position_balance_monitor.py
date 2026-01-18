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
from typing import Optional, Dict, Any
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
        self._lighter_leverage = Decimal("10")  # Lighter默认10倍杠杆
        self._extended_leverage = Decimal("10")  # Extended默认10倍杠杆

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
            # 注意：这里使用SDK的账户API来获取余额信息
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

            # 提取可用余额（保证金）
            # 注意：根据SDK的实际字段名称调整
            available_balance = Decimal('0')
            if hasattr(account_info, 'collateral'):
                available_balance = Decimal(str(account_info.collateral))
            elif hasattr(account_info, 'balance'):
                available_balance = Decimal(str(account_info.balance))
            elif hasattr(account_info, 'total_collateral'):
                available_balance = Decimal(str(account_info.total_collateral))

            # 计算最大可开仓数量
            # 最大仓位 = 可用余额 * 杠杆 / 当前价格
            # 这里简化处理，假设1:1的保证金比例
            max_position = available_balance * self._lighter_leverage

            # 如果有当前持仓，计算已使用的保证金
            margin_used = Decimal('0')
            if hasattr(account_info, 'margin_used'):
                margin_used = Decimal(str(account_info.margin_used))

            return ExchangePositionBalance(
                exchange="lighter",
                current_position=current_position,
                available_balance=available_balance,
                max_position=max_position,
                leverage=self._lighter_leverage,
                margin_used=margin_used,
                timestamp=datetime.now().timestamp()
            )

        except Exception as e:
            logger.error(f"获取Lighter仓位余额失败: {e}")
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

            # 获取账户信息（包含保证金余额）
            # 注意：这里使用SDK的账户API来获取余额信息
            account_info = await self.extended_client.perpetual_trading_client.account.get_account()

            if not account_info or not hasattr(account_info, 'data'):
                logger.warning("无法获取Extended账户信息")
                return None

            data = account_info.data
            if not data:
                return None

            # 提取可用余额（保证金）
            # 注意：根据SDK的实际字段名称调整
            available_balance = Decimal('0')
            if hasattr(data, 'collateral'):
                available_balance = Decimal(str(data.collateral))
            elif hasattr(data, 'balance'):
                available_balance = Decimal(str(data.balance))
            elif hasattr(data, 'available_balance'):
                available_balance = Decimal(str(data.available_balance))
            elif hasattr(data, 'total_collateral'):
                available_balance = Decimal(str(data.total_collateral))

            # 计算最大可开仓数量
            # 最大仓位 = 可用余额 * 杠杆 / 当前价格
            # 这里简化处理，假设1:1的保证金比例
            max_position = available_balance * self._extended_leverage

            # 如果有当前持仓，计算已使用的保证金
            margin_used = Decimal('0')
            if hasattr(data, 'margin_used'):
                margin_used = Decimal(str(data.margin_used))

            return ExchangePositionBalance(
                exchange="extended",
                current_position=current_position,
                available_balance=available_balance,
                max_position=max_position,
                leverage=self._extended_leverage,
                margin_used=margin_used,
                timestamp=datetime.now().timestamp()
            )

        except Exception as e:
            logger.error(f"获取Extended仓位余额失败: {e}")
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
