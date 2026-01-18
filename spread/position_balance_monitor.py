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

            # 打印调试信息
            logger.debug(f"Lighter account_info类型: {type(account_info)}")

            # 提取可用余额（保证金）
            # 尝试多种可能的字段名称
            available_balance = Decimal('0')
            balance_found = False

            # 优先级顺序：尝试不同的字段名称
            field_candidates = [
                'collateral', 'total_collateral', 'collateral_balance',
                'balance', 'available_balance', 'free_balance',
                'margin_balance', 'account_balance', 'total_balance',
                'withdrawable', 'available', 'free',
                'equity', 'total_equity'
            ]

            # 尝试从account_info获取
            for field in field_candidates:
                if hasattr(account_info, field):
                    value = getattr(account_info, field)
                    if value is not None:
                        try:
                            available_balance = Decimal(str(value))
                            balance_found = True
                            logger.info(f"Lighter余额字段: {field} = {available_balance}")
                            break
                        except (ValueError, TypeError):
                            continue

            # 如果直接字段都没找到，尝试遍历所有属性
            if not balance_found:
                for attr_name in dir(account_info):
                    if not attr_name.startswith('_'):
                        attr_value = getattr(account_info, attr_name, None)
                        if attr_value is not None and not callable(attr_value):
                            # 尝试判断是否是余额相关的字段
                            attr_lower = attr_name.lower()
                            if any(keyword in attr_lower for keyword in ['balance', 'collateral', 'margin', 'equity', 'available', 'free']):
                                try:
                                    if isinstance(attr_value, (int, float, str)):
                                        potential_balance = Decimal(str(attr_value))
                                        if potential_balance > 0:  # 只有大于0的才可能是余额
                                            available_balance = potential_balance
                                            balance_found = True
                                            logger.info(f"Lighter通过遍历找到余额字段: {attr_name} = {available_balance}")
                                            break
                                except (ValueError, TypeError):
                                    continue

            if not balance_found:
                logger.warning(f"无法找到Lighter余额字段")
                logger.warning(f"account_info的属性列表: {[attr for attr in dir(account_info) if not attr.startswith('_')]}")

            # 计算最大可开仓数量
            # 最大仓位 = 可用余额 * 杠杆
            max_position = available_balance * self._lighter_leverage

            # 如果有当前持仓，计算已使用的保证金
            margin_used = Decimal('0')
            if hasattr(account_info, 'margin_used'):
                margin_used = Decimal(str(account_info.margin_used))
            elif hasattr(account_info, 'used_margin'):
                margin_used = Decimal(str(account_info.used_margin))

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

            # 获取账户信息（包含保证金余额）
            # 注意：这里使用SDK的账户API来获取余额信息
            account_info = await self.extended_client.perpetual_trading_client.account.get_account()

            if not account_info:
                print(f"[DEBUG] Extended账户信息为空，account_info类型: {type(account_info)}")
                return None

            # 打印调试信息
            print(f"[DEBUG] Extended account_info类型: {type(account_info)}")
            print(f"[DEBUG] Extended account_info属性: {dir(account_info)}")

            # 尝试获取data属性
            data = None
            if hasattr(account_info, 'data'):
                data = account_info.data
                print(f"[DEBUG] Extended data类型: {type(data)}")
                print(f"[DEBUG] Extended data值: {data}")
                if data:
                    print(f"[DEBUG] Extended data属性: {dir(data)}")
                    print(f"[DEBUG] Extended data.__dict__: {data.__dict__ if hasattr(data, '__dict__') else 'N/A'}")

            # 提取可用余额（保证金）
            # 尝试多种可能的字段名称
            available_balance = Decimal('0')
            balance_found = False

            # 优先级顺序：尝试不同的字段名称
            field_candidates = [
                'collateral', 'total_collateral', 'collateral_balance',
                'balance', 'available_balance', 'free_balance',
                'margin_balance', 'account_balance', 'total_balance',
                'withdrawable', 'available', 'free'
            ]

            # 尝试从data对象获取
            if data:
                for field in field_candidates:
                    if hasattr(data, field):
                        value = getattr(data, field)
                        if value is not None:
                            try:
                                available_balance = Decimal(str(value))
                                balance_found = True
                                print(f"[INFO] Extended余额字段: {field} = {available_balance}")
                                break
                            except (ValueError, TypeError):
                                continue

                # 如果直接字段都没找到，尝试遍历所有属性
                if not balance_found:
                    for attr_name in dir(data):
                        if not attr_name.startswith('_'):
                            attr_value = getattr(data, attr_name, None)
                            if attr_value is not None and not callable(attr_value):
                                # 尝试判断是否是余额相关的字段
                                attr_lower = attr_name.lower()
                                if any(keyword in attr_lower for keyword in ['balance', 'collateral', 'margin', 'equity', 'available', 'free']):
                                    try:
                                        # 跳过已经是 Decimal 的值
                                        if isinstance(attr_value, (int, float, str)):
                                            potential_balance = Decimal(str(attr_value))
                                            if potential_balance > 0:  # 只有大于0的才可能是余额
                                                available_balance = potential_balance
                                                balance_found = True
                                                print(f"[INFO] Extended通过遍历找到余额字段: {attr_name} = {available_balance}")
                                                break
                                    except (ValueError, TypeError):
                                        continue

            # 尝试从account_info直接获取
            if not balance_found:
                for field in field_candidates:
                    if hasattr(account_info, field):
                        value = getattr(account_info, field)
                        if value is not None:
                            try:
                                available_balance = Decimal(str(value))
                                balance_found = True
                                print(f"[INFO] Extended从account_info获取余额字段: {field} = {available_balance}")
                                break
                            except (ValueError, TypeError):
                                continue

            if not balance_found:
                print(f"[WARNING] 无法找到Extended余额字段，data类型: {type(data)}")
                print(f"[WARNING] data的属性列表: {[attr for attr in dir(data) if not attr.startswith('_')] if data else 'None'}")

            # 计算最大可开仓数量
            # 最大仓位 = 可用余额 * 杠杆
            max_position = available_balance * self._extended_leverage

            # 如果有当前持仓，计算已使用的保证金
            margin_used = Decimal('0')
            if data:
                if hasattr(data, 'margin_used'):
                    margin_used = Decimal(str(data.margin_used))
                elif hasattr(data, 'used_margin'):
                    margin_used = Decimal(str(data.used_margin))

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
