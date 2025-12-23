"""
价差套利配置类
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SpreadArbConfig:
    """价差套利配置"""
    
    # ==================== 基础配置 ====================
    ticker: str = 'ETH'                                    # 交易对符号
    order_quantity_usdt: Decimal = Decimal('5')          # 单次下单金额 (USDT)
    
    # ==================== 价差配置 ====================
    min_spread_rate: Decimal = Decimal('0.0005')           # 最小价差率 (0.05%)
    latency_buffer: Decimal = Decimal('0.0001')            # 延迟缓冲 (0.01%)
    
    # ==================== 持仓管理 ====================
    max_open_pairs: int = 3                                # 最大同时持有套利对数量
    max_total_position_usdt: Decimal = Decimal('25')      # 最大总持仓价值 (USDT)
    
    # ==================== 平仓策略 ====================
    enable_time_close: bool = True                         # 启用时间止盈
    max_holding_time: int = 1800                           # 最大持仓时间 (秒, 30分钟)
    
    enable_profit_target: bool = True                      # 启用盈利目标
    profit_target_rate: Decimal = Decimal('0.002')         # 目标盈利率 (0.2%)
    
    enable_stop_loss: bool = True                          # 启用止损
    stop_loss_usdt: Decimal = Decimal('5')                 # 止损金额 ($5)
    
    # ==================== 风险控制 ====================
    max_lighter_depth_ratio: Decimal = Decimal('0.5')      # Lighter 深度使用比例 (50%)
    min_lighter_depth_usdt: Decimal = Decimal('200')       # Lighter 最小深度 (USDT)
    check_depth_layers: int = 3                            # 检查深度层数
    slippage_tolerance: Decimal = Decimal('0.001')         # 最大可接受滑点 (0.1%)
    
    # ==================== 超时配置 ====================
    extended_fill_timeout: int = 10                        # Extended 成交超时 (秒)
    lighter_hedge_timeout: int = 3                         # Lighter 对冲超时 (秒)
    
    # ==================== 断路器 ====================
    max_consecutive_failures: int = 3                      # 最大连续失败次数
    cooldown_period: int = 60                              # 冷却期 (秒)
    
    # ==================== 优先级 ====================
    prioritize_closing: bool = True                        # 优先平仓而非开仓
    
    # ==================== 其他 ====================
    enable_partial_fill: bool = True                       # 允许部分成交
    log_level: str = "INFO"                                # 日志级别
    
    def __post_init__(self):
        """验证配置"""
        # 验证价差率
        if self.min_spread_rate <= 0:
            raise ValueError("min_spread_rate 必须大于 0")
        
        if self.min_spread_rate <= self.latency_buffer:
            raise ValueError("min_spread_rate 必须大于 latency_buffer")
        
        # 验证持仓限制
        if self.max_open_pairs <= 0:
            raise ValueError("max_open_pairs 必须大于 0")
        
        if self.order_quantity_usdt <= 0:
            raise ValueError("order_quantity_usdt 必须大于 0")
        
        # 验证深度比例
        if not (0 < self.max_lighter_depth_ratio <= 1):
            raise ValueError("max_lighter_depth_ratio 必须在 (0, 1] 范围内")
    
    @property
    def effective_min_spread(self) -> Decimal:
        """计算有效最小价差 (考虑延迟缓冲)"""
        return self.min_spread_rate + self.latency_buffer
