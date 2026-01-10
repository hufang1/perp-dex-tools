"""
价差套利配置类
"""

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SpreadArbConfig:
    """价差套利配置"""

    # ==================== 基础配置 ====================
    ticker: str = 'ETH'                                    # 交易对符号
    order_quantity_usdt: Decimal = Decimal('35')          # 单次下单金额 (USDT)

    # ==================== 价差配置 ====================
    min_spread_rate: Decimal = Decimal('0.0010')           # 最小价差率 (0.10%) - 修复: 确保正期望收益
    latency_buffer: Decimal = Decimal('0.0001')            # 延迟缓冲 (0.01%)
    
    # ==================== 持仓管理 ====================
    max_open_pairs: int = 3                                # 最大同时持有套利对数量
    max_total_position_usdt: Decimal = Decimal('25')      # 最大总持仓价值 (USDT)
    
    # ==================== 平仓策略 ====================
    enable_time_close: bool = True                         # 启用时间止盈
    max_holding_time: int = 70                            # 最大持仓时间 (秒, 1分钟)
    time_close_threshold: int = 60                         # 时间平仓阈值 (秒, 1分钟) - 新增

    enable_profit_target: bool = True                      # 启用盈利目标
    profit_target_rate: Decimal = Decimal('0.0005')        # 目标盈利率 (0.05%)

    enable_stop_loss: bool = True                          # 启用止损
    stop_loss_usdt: Decimal = Decimal('5')                 # 止损金额 ($5)

    # ==================== 新增：时间止盈配置 ====================
    time_close_profit_threshold: Decimal = Decimal('0.0001')  # 时间止盈最小利润率 (0.01%)
    allow_negative_close: bool = False                     # 是否允许负利润平仓 (False=必须利润>0)

    # ==================== 008-fix-spread-close: 价差收敛和平仓优先级配置 ====================
    # 价差收敛判断阈值
    spread_convergence_threshold: Decimal = Decimal('0.001')   # 价差收敛阈值 (0.1%)
    # 启用新的5级优先级平仓系统
    close_priority_enabled: bool = True                       # 启用优先级平仓（True=使用P1-P5系统）
    # 平仓利润率配置
    min_close_profit_rate: Decimal = Decimal('0.0005')         # 最小平仓利润率 (0.05%) - P1触发条件
    max_close_loss_rate: Decimal = Decimal('0.01')             # 最大平仓亏损率 (1%) - P4触发条件
    delay_close_threshold: Decimal = Decimal('0.01')           # 延迟平仓阈值 (1%) - P5触发条件
    # T028: 价差扩大延迟平仓配置
    enable_delay_on_divergence: bool = False                  # 价差扩大时是否延迟平仓（默认False=立即平仓）
    
    # ==================== 风险控制 ====================
    max_lighter_depth_ratio: Decimal = Decimal('0.5')      # Lighter 深度使用比例 (50%)
    min_lighter_depth_usdt: Decimal = Decimal('200')       # Lighter 最小深度 (USDT)
    check_depth_layers: int = 3                            # 检查深度层数
    slippage_tolerance: Decimal = Decimal('0.001')         # 最大可接受滑点 (0.1%)

    # ==================== 未对冲持仓保护 ====================
    max_unhedged_positions: int = 0                        # 最大允许未对冲持仓数量 (0=严格禁止, >0=容忍数量)
    auto_close_unhedged: bool = False                      # 自动平仓未对冲持仓 (谨慎使用!)
    unhedged_position_timeout: int = 60                    # 未对冲持仓超时自动处理 (秒, 默认60秒)

    # ==================== 对冲失败监控 ====================
    hedge_failure_threshold: Decimal = Decimal('0.3')      # 对冲失败率阈值 (30% 触发警告)
    hedge_failure_window: int = 10                         # 对冲失败率统计窗口 (最近N次尝试)

    # ==================== 持仓对账 ====================
    enable_reconciliation: bool = True                     # 启用持仓对账
    reconciliation_interval: int = 60                      # 对账间隔 (秒, 默认1分钟)
    
    # ==================== 超时配置 ====================
    extended_fill_timeout: int = 10                        # Extended 成交超时 (秒)
    lighter_hedge_timeout: int = 3                         # Lighter 对冲超时 (秒)
    
    # ==================== 断路器 ====================
    max_consecutive_failures: int = 3                      # 最大连续失败次数
    cooldown_period: int = 60                              # 冷却期 (秒)
    
    # ==================== 优先级 ====================
    prioritize_closing: bool = True                        # 优先平仓而非开仓
    
    # ==================== 手续费配置 ====================
    extended_maker_fee_rate: Decimal = Decimal('0')    # Extended maker手续费率 (0.01%) - 假设值
    extended_taker_fee_rate: Decimal = Decimal('0.000225')   # Extended taker手续费率 (0.0225%)
    lighter_fee_rate: Decimal = Decimal('0.0')             # Lighter手续费率 (0%)

    # ==================== Maker/Taker策略配置 ====================
    maker_timeout_seconds: int = 5                         # Maker单超时时间 (秒)
    maker_timeout_action: str = "convert_to_taker"          # 超时后动作: "convert_to_taker" 或 "cancel"
    use_maker_orders: bool = True                            # 是否使用maker单 (True=使用maker节省手续费)
    maker_price_tick: Decimal = Decimal('0.01')             # Maker价格精度 (美元) - Extended价格最小单位
    min_profit_threshold: Decimal = Decimal('0.0002')       # 最小盈利阈值 (0.02%) - Maker转换条件

    # ==================== 其他 ====================
    enable_partial_fill: bool = True                       # 允许部分成交
    log_level: str = "INFO"                                # 日志级别
    env_file: str = ".env"                                 # 环境变量文件路径

    # ==================== 价差记录器配置 ====================
    enable_spread_recorder: bool = True                    # 启用价差记录器
    spread_recorder_interval: int = 5                      # 采样间隔（秒）
    spread_recorder_output_dir: str = "data"               # CSV输出目录路径
    spread_recorder_buffer_size: int = 100                 # 缓冲区大小（记录数）
    spread_recorder_log_level: str = "INFO"                # 日志级别
    spread_recorder_flush_interval: int = 60               # 缓冲刷新间隔（秒）

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

        # 新增: 验证平仓策略参数
        if self.profit_target_rate <= 0:
            raise ValueError("profit_target_rate 必须大于 0")

        if self.time_close_threshold <= 0:
            raise ValueError("time_close_threshold 必须大于 0")

        if self.max_holding_time <= self.time_close_threshold:
            raise ValueError("max_holding_time 必须大于 time_close_threshold")

        # 验证手续费率
        if self.extended_maker_fee_rate < 0:
            raise ValueError("extended_maker_fee_rate 不能为负数")

        if self.extended_taker_fee_rate < 0:
            raise ValueError("extended_taker_fee_rate 不能为负数")

        if self.lighter_fee_rate < 0:
            raise ValueError("lighter_fee_rate 不能为负数")

        # 验证maker/taker策略配置
        if self.maker_timeout_seconds <= 0:
            raise ValueError("maker_timeout_seconds 必须大于 0")

        if self.maker_timeout_action not in ["convert_to_taker", "cancel"]:
            raise ValueError("maker_timeout_action 必须是 'convert_to_taker' 或 'cancel'")

        # 009-fix-spread-loss-fees: 验证maker价格精度
        if self.maker_price_tick <= 0:
            raise ValueError("maker_price_tick 必须大于 0")

        # 009-fix-spread-loss-fees: 验证最小盈利阈值
        if self.min_profit_threshold < 0:
            raise ValueError("min_profit_threshold 不能为负数")

        # 验证价差记录器配置
        if self.spread_recorder_interval <= 0:
            raise ValueError("spread_recorder_interval 必须大于 0")

        if self.spread_recorder_buffer_size <= 0:
            raise ValueError("spread_recorder_buffer_size 必须大于 0")

        if self.spread_recorder_flush_interval <= 0:
            raise ValueError("spread_recorder_flush_interval 必须大于 0")

        if self.spread_recorder_log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            raise ValueError("spread_recorder_log_level 必须是 DEBUG/INFO/WARNING/ERROR 之一")

    @property
    def effective_min_spread(self) -> Decimal:
        """计算有效最小价差 (考虑延迟缓冲)"""
        return self.min_spread_rate + self.latency_buffer

    @classmethod
    def from_env(cls) -> 'SpreadArbConfig':
        """从环境变量加载配置

        支持的环境变量:
        - MIN_SPREAD_RATE: 最小价差率 (默认 0.0005)
        - PROFIT_TARGET_RATE: 盈利目标 (默认 0.0005)
        - TIME_CLOSE_THRESHOLD: 时间平仓阈值秒数 (默认 60)
        - MAX_HOLDING_TIME: 最大持仓时间秒数 (默认 300)
        - UNHEDGED_TIMEOUT: 未对冲持仓超时秒数 (默认 60)
        """
        return cls(
            # 基础配置
            ticker=os.getenv('TICKER', 'ETH'),
            order_quantity_usdt=Decimal(os.getenv('ORDER_QUANTITY_USDT', '35')),

            # 价差配置
            min_spread_rate=Decimal(os.getenv('MIN_SPREAD_RATE', '0.0005')),
            latency_buffer=Decimal(os.getenv('LATENCY_BUFFER', '0.0001')),

            # 持仓管理
            max_open_pairs=int(os.getenv('MAX_OPEN_PAIRS', '3')),
            max_total_position_usdt=Decimal(os.getenv('MAX_TOTAL_POSITION_USDT', '25')),

            # 平仓策略
            enable_time_close=os.getenv('ENABLE_TIME_CLOSE', 'True').lower() == 'true',
            max_holding_time=int(os.getenv('MAX_HOLDING_TIME', '300')),
            time_close_threshold=int(os.getenv('TIME_CLOSE_THRESHOLD', '60')),
            enable_profit_target=os.getenv('ENABLE_PROFIT_TARGET', 'True').lower() == 'true',
            profit_target_rate=Decimal(os.getenv('PROFIT_TARGET_RATE', '0.0005')),
            enable_stop_loss=os.getenv('ENABLE_STOP_LOSS', 'True').lower() == 'true',
            stop_loss_usdt=Decimal(os.getenv('STOP_LOSS_USDT', '5')),
            time_close_profit_threshold=Decimal(os.getenv('TIME_CLOSE_PROFIT_THRESHOLD', '0.0001')),
            allow_negative_close=os.getenv('ALLOW_NEGATIVE_CLOSE', 'False').lower() == 'true',

            # 风险控制
            max_lighter_depth_ratio=Decimal(os.getenv('MAX_LIGHTER_DEPTH_RATIO', '0.5')),
            min_lighter_depth_usdt=Decimal(os.getenv('MIN_LIGHTER_DEPTH_USDT', '200')),
            check_depth_layers=int(os.getenv('CHECK_DEPTH_LAYERS', '3')),
            slippage_tolerance=Decimal(os.getenv('SLIPPAGE_TOLERANCE', '0.001')),

            # 未对冲持仓保护
            max_unhedged_positions=int(os.getenv('MAX_UNHEDGED_POSITIONS', '0')),
            auto_close_unhedged=os.getenv('AUTO_CLOSE_UNHEDGED', 'False').lower() == 'true',
            unhedged_position_timeout=int(os.getenv('UNHEDGED_TIMEOUT', '60')),

            # 对冲失败监控
            hedge_failure_threshold=Decimal(os.getenv('HEDGE_FAILURE_THRESHOLD', '0.3')),
            hedge_failure_window=int(os.getenv('HEDGE_FAILURE_WINDOW', '10')),

            # 持仓对账
            enable_reconciliation=os.getenv('ENABLE_RECONCILIATION', 'True').lower() == 'true',
            reconciliation_interval=int(os.getenv('RECONCILIATION_INTERVAL', '60')),

            # 超时配置
            extended_fill_timeout=int(os.getenv('EXTENDED_FILL_TIMEOUT', '10')),
            lighter_hedge_timeout=int(os.getenv('LIGHTER_HEDGE_TIMEOUT', '3')),

            # 断路器
            max_consecutive_failures=int(os.getenv('MAX_CONSECUTIVE_FAILURES', '3')),
            cooldown_period=int(os.getenv('COOLDOWN_PERIOD', '60')),

            # 优先级
            prioritize_closing=os.getenv('PRIORITIZE_CLOSING', 'True').lower() == 'true',

            # 其他
            enable_partial_fill=os.getenv('ENABLE_PARTIAL_FILL', 'True').lower() == 'true',
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            env_file=os.getenv('ENV_FILE', '.env')
        )


# Default configuration instance
config = SpreadArbConfig()
