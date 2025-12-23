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
    
    def calculate_spread_opportunity(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal,
        extended_mid_price: Optional[Decimal] = None
    ) -> Optional[Dict[str, Any]]:
        """
        计算价差机会
        
        Args:
            extended_bid: Extended 最佳买价
            extended_ask: Extended 最佳卖价
            lighter_bid: Lighter 最佳买价
            lighter_ask: Lighter 最佳卖价
            extended_mid_price: Extended 中间价 (用于计算数量)
        
        Returns:
            套利机会字典，如果没有机会则返回 None
            {
                'type': 'buy_extended_sell_lighter' | 'sell_extended_buy_lighter',
                'side': 'buy' | 'sell',              # Extended 方向
                'spread': Decimal,                    # 绝对价差
                'spread_rate': Decimal,               # 价差率
                'expected_profit_rate': Decimal,      # 预期利润率 (扣除延迟缓冲)
                'extended_price': Decimal,            # Extended 挂单价格
                'lighter_price': Decimal,             # Lighter 预期成交价格
                'quantity': Decimal                   # 建议下单量 (币数)
            }
        """
        opportunities = []
        
        # 计算中间价 (用于 USDT 转币数量)
        if extended_mid_price is None:
            extended_mid_price = (extended_bid + extended_ask) / Decimal('2')
        
        # 机会 1: Extended 买入 + Lighter 卖出
        # Extended 挂买单在 best bid, Lighter 卖出在 best bid
        if lighter_bid > extended_bid:
            spread = lighter_bid - extended_bid
            spread_rate = spread / extended_bid
            
            # 扣除延迟缓冲后的预期利润率
            expected_profit_rate = spread_rate - self.config.latency_buffer
            
            if expected_profit_rate >= self.config.min_spread_rate:
                # 计算下单数量 (USDT 转币数量)
                quantity = self.config.order_quantity_usdt / extended_mid_price
                
                opportunities.append({
                    'type': 'buy_extended_sell_lighter',
                    'side': 'buy',
                    'spread': spread,
                    'spread_rate': spread_rate,
                    'expected_profit_rate': expected_profit_rate,
                    'extended_price': extended_bid,   # 在买一挂单
                    'lighter_price': lighter_bid,     # 预期卖给 Lighter 买一
                    'quantity': quantity
                })
        
        # 机会 2: Extended 卖出 + Lighter 买入
        # Extended 挂卖单在 best ask, Lighter 买入在 best ask
        if extended_ask > lighter_ask:
            spread = extended_ask - lighter_ask
            spread_rate = spread / lighter_ask
            
            # 扣除延迟缓冲后的预期利润率
            expected_profit_rate = spread_rate - self.config.latency_buffer
            
            if expected_profit_rate >= self.config.min_spread_rate:
                # 计算下单数量
                quantity = self.config.order_quantity_usdt / extended_mid_price
                
                opportunities.append({
                    'type': 'sell_extended_buy_lighter',
                    'side': 'sell',
                    'spread': spread,
                    'spread_rate': spread_rate,
                    'expected_profit_rate': expected_profit_rate,
                    'extended_price': extended_ask,   # 在卖一挂单
                    'lighter_price': lighter_ask,     # 预期买在 Lighter 卖一
                    'quantity': quantity
                })
        
        # 返回最优机会 (按预期利润率排序)
        if opportunities:
            best = max(opportunities, key=lambda x: x['expected_profit_rate'])
            
            self.logger.debug(
                f"发现套利机会: {best['type']} "
                f"价差率={best['spread_rate']:.4%} "
                f"预期利润={best['expected_profit_rate']:.4%}"
            )
            
            return best
        
        return None
    
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
