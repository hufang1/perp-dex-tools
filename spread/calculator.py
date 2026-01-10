"""
价差计算器 - 计算套利机会和深度分析
"""

import logging
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple

from .config import SpreadArbConfig


class SpreadCalculator:
    """价差计算与套利机会识别"""
    
    def __init__(self, config: SpreadArbConfig):
        """
        初始化价差计算器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = logging.getLogger("SpreadCalculator")
    
    def calculate_spread_opportunity_mid(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal,
        min_spread_rate: Optional[Decimal] = None
    ) -> Optional[Dict[str, Any]]:
        """
        使用中间价计算价差机会（修复后的方法）

        算法:
        1. 计算中间价: extended_mid = (bid + ask) / 2
        2. 计算价差: spread = extended_mid - lighter_mid
        3. 判断方向: spread > 0 → short_spread, spread < 0 → long_spread
        4. 验证价差率是否超过阈值

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价
            min_spread_rate: 最小价差率阈值（默认使用config.min_spread_rate）

        Returns:
            {
                'spread_mid': Decimal,           # 中间价差
                'spread_rate': Decimal,          # 价差率
                'direction': str,                # 'long_spread' | 'short_spread'
                'extended_side': str,            # 'buy' | 'sell'
                'extended_price': Decimal,       # Extended挂单价格
                'lighter_price': Decimal,        # Lighter对冲价格
                'expected_profit_rate': Decimal  # 预期利润率
            }
            或 None (如果没有机会)
        """
        if min_spread_rate is None:
            min_spread_rate = self.config.min_spread_rate

        # 1. 计算中间价
        extended_mid = (extended_bid + extended_ask) / Decimal('2')
        lighter_mid = (lighter_bid + lighter_ask) / Decimal('2')

        # 2. 计算价差: spread = extended_mid - lighter_mid
        spread = extended_mid - lighter_mid
        spread_abs = abs(spread)

        # 计算价差率 (相对于lighter中间价)
        if lighter_mid > 0:
            spread_rate = spread_abs / lighter_mid
        else:
            self.logger.warning("Lighter中间价 <= 0，无法计算价差率")
            return None

        # 扣除延迟缓冲
        expected_profit_rate = spread_rate - self.config.latency_buffer

        self.logger.debug(
            f"[价差检查(中间价)] Extended_mid={extended_mid:.2f}, Lighter_mid={lighter_mid:.2f}, "
            f"Spread={spread:.2f} ({spread_rate:.4%}), 预期利润={expected_profit_rate:.4%}, "
            f"阈值={min_spread_rate:.4%}"
        )

        # 3. 验证价差率是否超过阈值
        if expected_profit_rate < min_spread_rate:
            return None

        # 4. 根据价差符号决定方向
        if spread > 0:
            # Extended贵于Lighter → 做空价差
            direction = 'short_spread'
            extended_side = 'sell'  # 卖出Extended
            extended_price = extended_ask  # 在卖一挂单
            lighter_price = lighter_bid   # Lighter用买一对冲
        elif spread < 0:
            # Extended便宜于Lighter → 做多价差
            direction = 'long_spread'
            extended_side = 'buy'   # 买入Extended
            extended_price = extended_bid  # 在买一挂单
            lighter_price = lighter_ask    # Lighter用卖一对冲
        else:
            # spread = 0，无套利机会
            return None

        # 计算下单数量
        quantity = self.config.order_quantity_usdt / extended_mid

        return {
            'spread_mid': spread,
            'spread_rate': spread_rate,
            'direction': direction,
            'side': extended_side,            # 向后兼容: bot.py中使用opportunity['side']
            'extended_side': extended_side,
            'extended_price': extended_price,
            'lighter_price': lighter_price,
            'expected_profit_rate': expected_profit_rate,
            'quantity': quantity
        }

    def calculate_spread_opportunity(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal,
        extended_mid_price: Optional[Decimal] = None
    ) -> Optional[Dict[str, Any]]:
        """
        计算价差机会（已修复：使用中间价计算）

        本方法现在调用calculate_spread_opportunity_mid来确保：
        - 使用中间价计算价差（spread = extended_mid - lighter_mid）
        - 根据价差符号决定正确的套利方向

        Args:
            extended_bid: Extended 最佳买价
            extended_ask: Extended 最佳卖价
            lighter_bid: Lighter 最佳买价
            lighter_ask: Lighter 最佳卖价
            extended_mid_price: Extended 中间价 (用于计算数量，已弃用参数)

        Returns:
            套利机会字典，如果没有机会则返回 None
        """
        # 调用新的中间价计算方法
        return self.calculate_spread_opportunity_mid(
            extended_bid=extended_bid,
            extended_ask=extended_ask,
            lighter_bid=lighter_bid,
            lighter_ask=lighter_ask
        )
    
    def calculate_max_safe_quantity(
        self,
        lighter_orderbook: Dict[str, Dict[Decimal, Decimal]],
        side: str,
        target_quantity: Decimal
    ) -> Tuple[bool, Decimal, Decimal]:
        """
        计算在 Lighter 的最大安全下单量
        
        Args:
            lighter_orderbook: Lighter 订单簿 {'bids': {price: size}, 'asks': {price: size}}
            side: 'buy' 或 'sell' (Lighter 对冲方向)
            target_quantity: 目标下单量 (币数)
        
        Returns:
            (is_sufficient, safe_quantity, avg_price)
            - is_sufficient: 深度是否充足
            - safe_quantity: 安全下单量
            - avg_price: 预期平均成交价格
        """
        # 确定要检查的订单簿方向
        book_side = 'asks' if side == 'buy' else 'bids'
        
        # 获取订单簿
        book = lighter_orderbook.get(book_side, {})
        
        if not book:
            self.logger.warning(f"Lighter {book_side} 订单簿为空")
            return False, Decimal('0'), Decimal('0')
        
        # 按价格排序 (买单降序，卖单升序)
        sorted_levels = sorted(
            book.items(),
            key=lambda x: x[0],
            reverse=(book_side == 'bids')
        )[:self.config.check_depth_layers]
        
        # 累积深度和价值
        cumulative_qty = Decimal('0')
        cumulative_value = Decimal('0')
        
        for price, size in sorted_levels:
            cumulative_qty += size
            cumulative_value += price * size
        
        if cumulative_qty == 0:
            return False, Decimal('0'), Decimal('0')
        
        # 计算平均价格
        avg_price = cumulative_value / cumulative_qty
        
        # 应用深度比例限制
        max_safe_quantity = cumulative_qty * self.config.max_lighter_depth_ratio
        
        # 检查深度是否充足
        is_sufficient = max_safe_quantity >= target_quantity
        
        # 返回实际安全数量
        safe_quantity = min(max_safe_quantity, target_quantity)
        
        self.logger.debug(
            f"Lighter {side} 深度检查: "
            f"累积深度={cumulative_qty:.4f}, "
            f"安全数量={safe_quantity:.4f}, "
            f"平均价={avg_price:.2f}"
        )
        
        return is_sufficient, safe_quantity, avg_price
    
    def check_lighter_depth_value(
        self,
        lighter_orderbook: Dict[str, Dict[Decimal, Decimal]],
        side: str
    ) -> Decimal:
        """
        检查 Lighter 深度的 USDT 价值
        
        Args:
            lighter_orderbook: Lighter 订单簿
            side: 'buy' 或 'sell'
        
        Returns:
            深度的 USDT 价值
        """
        book_side = 'asks' if side == 'buy' else 'bids'
        book = lighter_orderbook.get(book_side, {})
        
        if not book:
            return Decimal('0')
        
        # 获取前 N 档
        sorted_levels = sorted(
            book.items(),
            key=lambda x: x[0],
            reverse=(book_side == 'bids')
        )[:self.config.check_depth_layers]
        
        # 计算总价值
        total_value = sum(price * size for price, size in sorted_levels)
        
        return total_value
