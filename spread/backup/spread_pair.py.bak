"""
套利对 - 表示一个 Extended + Lighter 的套利持仓
"""

import time
from decimal import Decimal
from typing import Optional, Dict, Any


class SpreadPair:
    """套利对 - 记录一个完整的套利持仓"""
    
    def __init__(
        self,
        pair_id: int,
        extended_side: str,       # 'buy' or 'sell'
        extended_price: Decimal,
        extended_quantity: Decimal,
        lighter_price: Decimal,
        lighter_quantity: Decimal,
        extended_order_id: Optional[str] = None,
        lighter_order_id: Optional[str] = None
    ):
        """
        初始化套利对

        Args:
            pair_id: 套利对 ID
            extended_side: Extended 方向 ('buy' 或 'sell')
            extended_price: Extended 成交价格
            extended_quantity: Extended 成交数量
            lighter_price: Lighter 成交价格
            lighter_quantity: Lighter 成交数量 (应该与 extended_quantity 相同)
            extended_order_id: Extended 开仓订单 ID
            lighter_order_id: Lighter 开仓订单 ID
        """
        self.pair_id = pair_id
        self.extended_side = extended_side
        self.extended_price = extended_price
        self.extended_quantity = extended_quantity
        self.lighter_price = lighter_price
        self.lighter_quantity = lighter_quantity

        # 开仓订单ID
        self.open_extended_order_id = extended_order_id
        self.open_lighter_order_id = lighter_order_id

        # 兼容旧代码 (保留现有属性)
        self.extended_order_id = extended_order_id
        self.lighter_order_id = lighter_order_id

        # 平仓订单ID (新增)
        self.close_extended_order_id: Optional[str] = None
        self.close_lighter_order_id: Optional[str] = None

        # 时间戳
        self.open_time = time.time()
        self.close_time: Optional[float] = None

        # 订单类型 (新增)
        self.open_order_type: str = "MAKER"  # "MAKER" 或 "TAKER"
        self.close_order_type: str = "MAKER"  # "MAKER" 或 "TAKER"
        self.maker_wait_duration_ms: int = 0  # maker单等待时长（毫秒）

        # 手续费类型 (新增)
        self.open_extended_fee_type: str = "MAKER"  # "MAKER" 或 "TAKER"
        self.close_extended_fee_type: str = "MAKER"  # "MAKER" 或 "TAKER"

        # 状态
        self.is_closed = False
        self.is_closing = False  # 是否正在平仓中（防止重复平仓）

        # 平仓信息
        self.close_extended_price: Optional[Decimal] = None
        self.close_lighter_price: Optional[Decimal] = None
        self.realized_pnl: Optional[Decimal] = None
    
    @property
    def lighter_side(self) -> str:
        """Lighter 方向 (与 Extended 相反)"""
        return 'sell' if self.extended_side == 'buy' else 'buy'
    
    @property
    def holding_time(self) -> float:
        """持仓时间 (秒)"""
        if self.is_closed:
            return self.close_time - self.open_time
        return time.time() - self.open_time
    
    @property
    def open_spread(self) -> Decimal:
        """开仓时的价差"""
        if self.extended_side == 'buy':
            # Extended 买入, Lighter 卖出
            return self.lighter_price - self.extended_price
        else:
            # Extended 卖出, Lighter 买入
            return self.extended_price - self.lighter_price
    
    @property
    def open_spread_rate(self) -> Decimal:
        """开仓时的价差率"""
        if self.extended_side == 'buy':
            return self.open_spread / self.extended_price
        else:
            return self.open_spread / self.lighter_price
    
    def should_close(self, opportunity: Dict[str, Any]) -> bool:
        """
        判断是否应该平仓此套利对
        
        Args:
            opportunity: 新的套利机会
                {
                    'side': 'buy' or 'sell',  # Extended 方向
                    'extended_price': Decimal,
                    'lighter_price': Decimal,
                    ...
                }
        
        Returns:
            True 如果新机会是反方向 (可以用来平仓)
        """
        # 检查方向是否相反
        return opportunity['side'] != self.extended_side
    
    def calculate_unrealized_pnl(
        self,
        current_extended_price: Decimal,
        current_lighter_price: Decimal
    ) -> Decimal:
        """
        计算未实现盈亏 (浮动盈亏)
        
        Args:
            current_extended_price: 当前 Extended 价格 (用于平仓的价格)
            current_lighter_price: 当前 Lighter 价格 (用于平仓的价格)
        
        Returns:
            未实现盈亏 (USDT)
        """
        if self.extended_side == 'buy':
            # 开仓: Extended 买 @ extended_price, Lighter 卖 @ lighter_price
            # 平仓: Extended 卖 @ current_extended_price, Lighter 买 @ current_lighter_price
            extended_pnl = (current_extended_price - self.extended_price) * self.extended_quantity
            lighter_pnl = (self.lighter_price - current_lighter_price) * self.lighter_quantity
        else:
            # 开仓: Extended 卖 @ extended_price, Lighter 买 @ lighter_price
            # 平仓: Extended 买 @ current_extended_price, Lighter 卖 @ current_lighter_price
            extended_pnl = (self.extended_price - current_extended_price) * self.extended_quantity
            lighter_pnl = (current_lighter_price - self.lighter_price) * self.lighter_quantity
        
        return extended_pnl + lighter_pnl

    def calculate_realized_pnl(
        self,
        extended_close_price: Optional[Decimal],
        lighter_close_price: Optional[Decimal]
    ) -> Optional[Decimal]:
        """
        计算使用对手价立即平仓的理论收益

        Args:
            extended_close_price: Extended平仓价格
                - 做多持仓: 使用bid价格（卖出）
                - 做空持仓: 使用ask价格（买入平仓）
            lighter_close_price: Lighter平仓价格
                - 做多持仓时Lighter为做空: 使用ask价格（买入平仓）
                - 做空持仓时Lighter为做多: 使用bid价格（卖出）

        Returns:
            已实现盈亏 (Decimal) 或 None (当价格为None时)
            - 正数: 盈利
            - 负数: 亏损
            - 零: 不盈不亏
            - None: 价格缺失无法计算

        Calculation:
            Extended盈亏 + Lighter盈亏

        做多示例:
            Extended买入 @ $3000, 当前bid $3005 → 盈 $5
            Lighter卖出 @ $2980, 当前ask $3010 → 亏 $20
            已实现收益 = $5 - $20 = -$15

        做空示例:
            Extended卖出 @ $3000, 当前ask $2995 → 盈 $5
            Lighter买入 @ $2980, 当前bid $2975 → 盈 $5
            已实现收益 = $5 + $5 = $10
        """
        # 价格为None时无法计算
        if extended_close_price is None or lighter_close_price is None:
            return None

        # 验证价格和数量有效性
        if extended_close_price <= 0 or lighter_close_price <= 0:
            return None
        if self.extended_quantity <= 0 or self.lighter_quantity <= 0:
            return None

        try:
            if self.extended_side == 'buy':
                # 做多: Extended买入，现在用bid卖出
                extended_pnl = (extended_close_price - self.extended_price) * self.extended_quantity
                # 做多时Lighter为做空，现在用ask买入平仓
                lighter_pnl = (self.lighter_price - lighter_close_price) * self.lighter_quantity
            else:
                # 做空: Extended卖出，现在用ask买入平仓
                extended_pnl = (self.extended_price - extended_close_price) * self.extended_quantity
                # 做空时Lighter为做多，现在用bid卖出
                lighter_pnl = (lighter_close_price - self.lighter_price) * self.lighter_quantity

            return extended_pnl + lighter_pnl
        except Exception:
            # 计算异常时返回None
            return None

    def close(
        self,
        close_extended_price: Decimal,
        close_lighter_price: Decimal
    ) -> Decimal:
        """
        标记套利对为已平仓并计算实现盈亏
        
        Args:
            close_extended_price: Extended 平仓价格
            close_lighter_price: Lighter 平仓价格
        
        Returns:
            实现盈亏 (USDT)
        """
        self.is_closed = True
        self.close_time = time.time()
        self.close_extended_price = close_extended_price
        self.close_lighter_price = close_lighter_price
        
        # 计算实现盈亏
        self.realized_pnl = self.calculate_unrealized_pnl(
            close_extended_price,
            close_lighter_price
        )
        
        return self.realized_pnl

    def calculate_opening_fees(
        self,
        extended_fee_rate: Decimal,
        lighter_fee_rate: Decimal
    ) -> Decimal:
        """
        计算开仓手续费

        Args:
            extended_fee_rate: Extended手续费率
            lighter_fee_rate: Lighter手续费率

        Returns:
            总开仓手续费
        """
        # Extended开仓手续费
        extended_fee = self.extended_quantity * self.extended_price * extended_fee_rate

        # Lighter开仓手续费
        lighter_fee = self.lighter_quantity * self.lighter_price * lighter_fee_rate

        return extended_fee + lighter_fee

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典 (用于日志记录)"""
        return {
            'pair_id': self.pair_id,
            'extended_side': self.extended_side,
            'extended_price': float(self.extended_price),
            'extended_quantity': float(self.extended_quantity),
            'lighter_price': float(self.lighter_price),
            'lighter_quantity': float(self.lighter_quantity),
            'open_spread': float(self.open_spread),
            'open_spread_rate': float(self.open_spread_rate),
            'open_time': self.open_time,
            'close_time': self.close_time,
            'holding_time': self.holding_time,
            'is_closed': self.is_closed,
            'close_extended_price': float(self.close_extended_price) if self.close_extended_price else None,
            'close_lighter_price': float(self.close_lighter_price) if self.close_lighter_price else None,
            'realized_pnl': float(self.realized_pnl) if self.realized_pnl else None,
            # 新增订单ID字段
            'open_extended_order_id': self.open_extended_order_id,
            'open_lighter_order_id': self.open_lighter_order_id,
            'close_extended_order_id': self.close_extended_order_id,
            'close_lighter_order_id': self.close_lighter_order_id
        }
    
    def __repr__(self) -> str:
        """字符串表示"""
        status = "已平仓" if self.is_closed else "持仓中"
        return (
            f"SpreadPair(#{self.pair_id}, {self.extended_side.upper()}, "
            f"{self.extended_quantity} @ E:{self.extended_price}/L:{self.lighter_price}, "
            f"{status}, 持仓{self.holding_time:.0f}秒)"
        )
