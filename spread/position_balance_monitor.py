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

            # 尝试方法1：使用REST API获取账户余额
            available_balance = Decimal('0')
            balance_found = False

            try:
                # Extended REST API endpoint for account info
                url = "https://api.starknet.extended.exchange/api/v1/perp/account"
                headers = {"X-Api-Key": self.extended_client.api_key}

                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            print(f"[DEBUG] Extended REST API响应: {data}")

                            if data.get("status") == "OK" and data.get("data"):
                                account_data = data["data"]

                                # 尝试不同的字段名称
                                for field in ['collateral', 'balance', 'availableBalance',
                                              'available_balance', 'free_balance', 'total_balance',
                                              'margin_balance', 'accountBalance', 'account_balance',
                                              'collateralBalance', 'collateral_balance']:
                                    if field in account_data and account_data[field] is not None:
                                        try:
                                            available_balance = Decimal(str(account_data[field]))
                                            balance_found = True
                                            print(f"[INFO] Extended从REST API获取余额字段: {field} = {available_balance}")
                                            break
                                        except (ValueError, TypeError):
                                            continue

                                # 如果还没找到，打印所有字段
                                if not balance_found:
                                    print(f"[WARNING] Extended REST API返回的字段: {list(account_data.keys())}")
            except Exception as e:
                print(f"[DEBUG] Extended REST API请求失败: {e}")

            # 尝试方法2：使用SDK的collateral相关方法（如果存在）
            if not balance_found:
                try:
                    account = self.extended_client.perpetual_trading_client.account
                    # 尝试调用可能的方法
                    for method_name in ['get_collateral', 'get_balance', 'get_collateral_balance',
                                       'get_account_balance', 'fetch_balance']:
                        if hasattr(account, method_name):
                            method = getattr(account, method_name)
                            if callable(method):
                                result = await method()
                                print(f"[DEBUG] Extended调用方法 {method_name} 结果: {result}")
                                if result is not None:
                                    try:
                                        if hasattr(result, 'data'):
                                            available_balance = Decimal(str(result.data))
                                        else:
                                            available_balance = Decimal(str(result))
                                        balance_found = True
                                        print(f"[INFO] Extended从方法{method_name}获取余额: {available_balance}")
                                        break
                                    except (ValueError, TypeError):
                                        continue
                except Exception as e:
                    print(f"[DEBUG] Extended SDK方法调用失败: {e}")

            # 计算最大可开仓数量
            # 最大仓位 = 可用余额 * 杠杆
            max_position = available_balance * self._extended_leverage

            return ExchangePositionBalance(
                exchange="extended",
                current_position=current_position,
                available_balance=available_balance,
                max_position=max_position,
                leverage=self._extended_leverage,
                margin_used=Decimal('0'),
                timestamp=datetime.now().timestamp()
            )

        except Exception as e:
            print(f"[ERROR] 获取Extended仓位余额失败: {e}")
            import traceback
            traceback.print_exc()
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
