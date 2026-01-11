"""
IOC订单管理模块

本模块实现011-async-ws-ioc-trading的IOC订单功能，包括:
- IOC订单创建
- 激进限价定价
- 部分成交处理
"""

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from spread.config import SpreadArbConfig


class IocOrderManager:
    """
    IOC订单管理器

    负责创建IOC订单、计算激进限价价格、处理部分成交。
    """

    def __init__(
        self,
        config: SpreadArbConfig,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """初始化IOC订单管理器

        Args:
            config: SpreadArbConfig配置对象
            logger: 日志记录器（可选）
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

    # ========================================================================
    # IOC订单创建
    # ========================================================================

    def create_ioc_order(
        self,
        exchange: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        slippage_tolerance: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """创建IOC订单

        Args:
            exchange: 'extended' 或 'lighter'
            side: 'buy' 或 'sell'
            price: 基础价格（bid或ask）
            quantity: 数量
            slippage_tolerance: 滑点容忍度，默认从config读取

        Returns:
            订单字典，包含:
            - 'symbol': str
            - 'side': str
            - 'type': 'LIMIT'
            - 'price': str
            - 'quantity': str
            - 'timeInForce': 'IOC'
            - 'postOnly': False
        """
        if slippage_tolerance is None:
            slippage_tolerance = self.config.ioc_slippage_tolerance_rate

        # 计算IOC价格（激进限价）
        ioc_price = self.calculate_ioc_price(price, side, slippage_tolerance)

        # 构造订单
        order = {
            'symbol': self.config.ticker,
            'side': side,
            'type': 'LIMIT',
            'price': str(ioc_price),
            'quantity': str(quantity),
        }

        # 根据交易所设置不同字段
        if exchange == 'extended':
            order['timeInForce'] = 'IOC'
            order['postOnly'] = False
        elif exchange == 'lighter':
            # Lighter可能使用下划线命名
            order['time_in_force'] = 'IOC'
            order['post_only'] = False
        else:
            raise ValueError(f"无效的exchange: {exchange}")

        self.logger.info(
            f"📝 [IOC订单] {exchange} {side} 价格={ioc_price} "
            f"(基础价={price}, 滑点容忍={slippage_tolerance:.4%})"
        )

        return order

    # ========================================================================
    # IOC价格计算
    # ========================================================================

    def calculate_ioc_price(
        self,
        base_price: Decimal,
        side: str,
        slippage_tolerance: Decimal
    ) -> Decimal:
        """计算IOC订单价格（激进限价）

        Args:
            base_price: 基础价格（买一bid或卖一ask）
            side: 'buy' 或 'sell'
            slippage_tolerance: 滑点容忍度

        Returns:
            激进限价

        Example:
            price = calculate_ioc_price(Decimal('3000'), 'buy', Decimal('0.0005'))
            # 返回: Decimal('3001.5')
        """
        if side == 'buy':
            # 买入：价格高于ask确保成交
            return base_price * (Decimal('1') + slippage_tolerance)
        else:
            # 卖出：价格低于bid确保成交
            return base_price * (Decimal('1') - slippage_tolerance)

    # ========================================================================
    # 部分成交处理
    # ========================================================================

    def handle_partial_fill(
        self,
        order_result: Dict,
        expected_quantity: Decimal
    ) -> Dict[str, Any]:
        """处理IOC订单结果（可能部分成交）

        Args:
            order_result: 交易所返回的订单结果
            expected_quantity: 预期数量

        Returns:
            {
                'success': bool,
                'filled_qty': Decimal,
                'avg_price': Decimal,
                'is_partial': bool,
                'unfilled_qty': Decimal
            }
        """
        status = order_result.get('status', '')

        if status == 'filled':
            # 完全成交
            return {
                'success': True,
                'filled_qty': Decimal(order_result.get('executed_qty', expected_quantity)),
                'avg_price': Decimal(order_result.get('avg_price', 0)),
                'is_partial': False,
                'unfilled_qty': Decimal('0')
            }

        elif status == 'partially_filled':
            # 部分成交（IOC未成交部分自动撤销）
            filled_qty = Decimal(order_result.get('executed_qty', 0))
            return {
                'success': True,
                'filled_qty': filled_qty,
                'avg_price': Decimal(order_result.get('avg_price', 0)),
                'is_partial': True,
                'unfilled_qty': expected_quantity - filled_qty
            }

        else:
            # 完全未成交
            return {
                'success': False,
                'filled_qty': Decimal('0'),
                'avg_price': Decimal('0'),
                'is_partial': False,
                'unfilled_qty': expected_quantity
            }

    def log_partial_fill_warning(self, result: Dict[str, Any], exchange: str) -> None:
        """记录部分成交警告

        Args:
            result: handle_partial_fill返回的结果
            exchange: 交易所名称
        """
        if result.get('is_partial'):
            self.logger.warning(
                f"⚠️ [部分成交] {exchange} "
                f"成交: {result['filled_qty']}, "
                f"未成交: {result['unfilled_qty']}, "
                f"均价: ${result['avg_price']}"
            )

    # ========================================================================
    # 012-dual-leg-concurrency: 双腿并发订单创建
    # ========================================================================

    def create_dual_leg_orders(
        self,
        opportunity: Dict[str, Any],
        extended_orderbook: Dict,
        lighter_orderbook: Dict
    ) -> tuple[Dict, Dict]:
        """创建双腿IOC订单

        Args:
            opportunity: 套利机会字典
                - 'side': 'buy' or 'sell' (Extended方向)
                - 'quantity': Decimal (下单数量)
            extended_orderbook: Extended订单簿
                - 'bid': Decimal
                - 'ask': Decimal
            lighter_orderbook: Lighter订单簿
                - 'bid': Decimal
                - 'ask': Decimal

        Returns:
            (extended_order, lighter_order) 订单字典元组

        Note:
            - Extended订单使用timeInForce参数
            - Lighter订单使用time_in_force参数（下划线）
            - 买入价 = ask * (1 + SLIPPAGE_TOLERANCE)
            - 卖出价 = bid * (1 - SLIPPAGE_TOLERANCE)
        """
        side = opportunity['side']
        quantity = opportunity.get('quantity', Decimal('0.01'))

        # Extended订单
        if side == 'buy':
            extended_price = extended_orderbook['ask']  # 买入用ask
        else:
            extended_price = extended_orderbook['bid']  # 卖出用bid

        extended_order = self.create_ioc_order(
            exchange='extended',
            side=side,
            price=extended_price,
            quantity=quantity
        )

        # Lighter订单（方向相反）
        lighter_side = 'sell' if side == 'buy' else 'buy'
        if lighter_side == 'buy':
            lighter_price = lighter_orderbook['ask']  # 买入用ask
        else:
            lighter_price = lighter_orderbook['bid']  # 卖出用bid

        lighter_order = self.create_ioc_order(
            exchange='lighter',
            side=lighter_side,
            price=lighter_price,
            quantity=quantity
        )

        self.logger.info(
            f"📝 [双腿订单创建] "
            f"Extended: {side} @ {extended_price}, "
            f"Lighter: {lighter_side} @ {lighter_price}"
        )

        return extended_order, lighter_order

    def log_no_fill_warning(self, exchange: str, expected_qty: Decimal) -> None:
        """记录完全未成交警告

        Args:
            exchange: 交易所名称
            expected_qty: 预期数量
        """
        self.logger.error(
            f"🚨 [完全未成交] {exchange} "
            f"预期数量: {expected_qty}, "
            f"实际成交: 0"
        )
