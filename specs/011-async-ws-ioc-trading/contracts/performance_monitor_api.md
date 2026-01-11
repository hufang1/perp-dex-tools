# API合约：性能监控与调试输出

**功能**: 011-async-ws-ioc-trading
**日期**: 2026-01-11

本文档定义异步重构功能的API合约，包括接口、参数、返回值和异常处理。

---

## 1. PerformanceMonitor API

性能监控器负责记录时间戳、检查数据新鲜度、验证滑点和利润率，并输出结构化调试信息。

### 1.1 初始化

```python
def __init__(self, config: SpreadArbConfig, logger: Optional[logging.Logger] = None) -> None:
    """初始化性能监控器

    Args:
        config: SpreadArbConfig配置对象
        logger: 日志记录器（可选，默认创建新logger）
    """
```

### 1.2 时间戳记录

```python
def record_timestamp(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    """记录时间戳

    Args:
        name: 记录名称，建议值: 'signal', 'calc', 'send_A', 'send_B', 'ack_A', 'ack_B'
        metadata: 附加元数据，例如 {'log': True} 强制输出日志

    Example:
        monitor.record_timestamp('signal', {'opportunity': spread_rate})
    """
```

```python
def get_latency(self, start_name: str, end_name: str) -> Optional[float]:
    """计算两个时间戳之间的延迟

    Args:
        start_name: 起始记录名称
        end_name: 结束记录名称

    Returns:
        延迟（毫秒），如果找不到记录返回None

    Example:
        latency = monitor.get_latency('signal', 'send_A')
        # 返回: 8.45 (毫秒)
    """
```

### 1.3 延迟监控

```python
def record_tick_to_trade_latency(self, signal_ts: float, send_ts: float) -> None:
    """记录行情到交易的延迟

    Args:
        signal_ts: 信号触发时间戳（毫秒）
        send_ts: 订单发送时间戳（毫秒）

    副作用:
        - 更新统计数据
        - 如果延迟超过max_tick_to_trade_latency_ms，输出警告
        - 如果config.log_all_timestamps=True，输出INFO日志

    Example:
        monitor.record_tick_to_trade_latency(1704960123456.78, 1704960123465.23)
        # 输出: ⏱️ [行情→交易延迟] 8.45ms | 信号: 1704960123456.78ms | 发送: 1704960123465.23ms
    """
```

```python
def record_execution_latency(self, send_ts: float, ack_ts: float) -> None:
    """记录执行延迟（发送到ACK）

    Args:
        send_ts: 发送时间戳（毫秒）
        ack_ts: ACK时间戳（毫秒）

    副作用:
        - 更新统计数据
        - 如果延迟超过max_execution_latency_ms，输出警告
    """
```

```python
def record_concurrent_send_gap(self, first_send_ts: float, second_send_ts: float) -> None:
    """记录并发发送时间差

    Args:
        first_send_ts: 第一个订单发送时间戳（毫秒）
        second_send_ts: 第二个订单发送时间戳（毫秒）

    副作用:
        - 计算间隔并记录到stats
        - 输出INFO日志，带✅或❌标记

    Example:
        monitor.record_concurrent_send_gap(1704960123465.23, 1704960123468.44)
        # 输出: 🔄 [并发发送] Extended→Lighter间隔: 3.21ms ✅ | 阈值: 5ms
    """
```

### 1.4 数据新鲜度检查

```python
def check_data_freshness(
    self,
    exchange: str,
    data_timestamp: float,
    current_time: Optional[float] = None
) -> DataFreshnessResult:
    """检查数据新鲜度

    Args:
        exchange: 交易所名称 ('extended' 或 'lighter')
        data_timestamp: 数据时间戳（毫秒）
        current_time: 当前时间戳（毫秒），默认为系统时间

    Returns:
        DataFreshnessResult: 检查结果

    Raises:
        ValueError: exchange不是'extended'或'lighter'

    副作用:
        - 更新stale_data_count统计
        - 如果数据过期，输出ERROR日志

    Example:
        result = monitor.check_data_freshness('extended', 1704960123411.23)
        # 返回: DataFreshnessResult(is_fresh=True, data_age_ms=45.2, ...)
    """
```

```python
def check_both_data_freshness(
    self,
    extended_ts: float,
    lighter_ts: float,
    current_time: Optional[float] = None
) -> tuple[bool, List[DataFreshnessResult]]:
    """检查两个交易所的数据新鲜度

    Args:
        extended_ts: Extended数据时间戳（毫秒）
        lighter_ts: Lighter数据时间戳（毫秒）
        current_time: 当前时间戳（毫秒），默认为系统时间

    Returns:
        (是否都新鲜, [extended_result, lighter_result])

    副作用:
        - 如果任一数据过期，输出WARNING日志
    """
```

### 1.5 滑点检查

```python
def check_slippage(
    self,
    expected_price: Decimal,
    current_price: Decimal,
    side: str,
    threshold: Optional[Decimal] = None
) -> SlippageCheckResult:
    """检查滑点是否可接受

    Args:
        expected_price: 预期成交价
        current_price: 当前盘口价
        side: 方向 ('buy' 或 'sell')
        threshold: 滑点阈值，默认从config读取ioc_slippage_tolerance_rate

    Returns:
        SlippageCheckResult: 检查结果

    Raises:
        ValueError: side不是'buy'或'sell'

    副作用:
        - 如果滑点超限，输出ERROR日志
        - 如果滑点超过max_slippage_warning_rate，输出红色高亮警告

    Example:
        result = monitor.check_slippage(
            expected_price=Decimal('3000.00'),
            current_price=Decimal('3001.50'),
            side='buy'
        )
        # 返回: SlippageCheckResult(is_acceptable=True, slippage_rate=Decimal('0.0005'), ...)
    """
```

### 1.6 利润率检查

```python
def check_profitability(
    self,
    spread_rate: Decimal,
    extended_fee: Optional[Decimal] = None,
    lighter_fee: Optional[Decimal] = None,
    expected_slippage: Optional[Decimal] = None
) -> ProfitabilityCheckResult:
    """检查利润率是否足够

    Args:
        spread_rate: 价差率
        extended_fee: Extended手续费率，默认从config读取
        lighter_fee: Lighter手续费率，默认从config读取
        expected_slippage: 预期滑点成本，默认从config读取

    Returns:
        ProfitabilityCheckResult: 检查结果

    副作用:
        - 如果利润不足，更新profitability_rejections统计
        - 如果双边费率之和>0.06%，输出WARNING
        - 输出INFO或WARNING日志

    Example:
        result = monitor.check_profitability(Decimal('0.0010'))
        # 返回: ProfitabilityCheckResult(is_profitable=True, net_profit_rate=Decimal('0.0005'), ...)
    """
```

### 1.7 决策记录

```python
def log_opening_decision(
    self,
    opportunity: Dict[str, Any],
    data_freshness: List[DataFreshnessResult],
    slippage_check: Optional[SlippageCheckResult] = None,
    profitability_check: Optional[ProfitabilityCheckResult] = None,
    final_decision: str = "PENDING"
) -> None:
    """记录开仓决策过程

    Args:
        opportunity: 套利机会字典，包含:
            - 'type': str (如 '做多价差')
            - 'side': str ('buy' or 'sell')
            - 'spread_rate': Decimal
            - 'extended_price': Decimal
            - 'lighter_price': Decimal
        data_freshness: 数据新鲜度检查结果列表
        slippage_check: 滑点检查结果（可选）
        profitability_check: 利润率检查结果（可选）
        final_decision: 最终决策 ('允许开仓', '拒绝开仓')

    副作用:
        - 输出格式化决策日志到INFO级别

    Example:
        monitor.log_opening_decision(
            opportunity={
                'type': '做多价差',
                'side': 'buy',
                'spread_rate': Decimal('0.0010'),
                'extended_price': Decimal('3000.00'),
                'lighter_price': Decimal('3003.00')
            },
            data_freshness=[ext_result, lit_result],
            slippage_check=slippage_result,
            profitability_check=profit_result,
            final_decision='允许开仓'
        )
    """
```

### 1.8 统计导出

```python
def get_stats_summary(self) -> Dict[str, Any]:
    """获取统计摘要

    Returns:
        包含以下字段的字典:
        - 'total_checks': int
        - 'stale_data_count': int
        - 'stale_data_rate': float
        - 'slippage_rejections': int
        - 'profitability_rejections': int
        - 'avg_tick_to_trade_latency_ms': float
        - 'max_tick_to_trade_latency_ms': float
        - 'avg_execution_latency_ms': float
        - 'max_execution_latency_ms': float
        - 'concurrent_order_send_gap_ms': float
    """
```

```python
def log_stats_summary(self) -> None:
    """记录统计摘要到日志

    副作用:
        - 输出格式化统计报告到INFO级别
    """
```

---

## 2. WebSocketManager API

WebSocket连接管理器负责与交易所建立WebSocket连接、订阅频道、接收推送并维护本地订单簿缓存。

### 2.1 初始化

```python
def __init__(self, config: SpreadArbConfig, logger: Optional[logging.Logger] = None) -> None:
    """初始化WebSocket管理器

    Args:
        config: SpreadArbConfig配置对象
        logger: 日志记录器（可选）
    """
```

### 2.2 连接管理

```python
async def connect_extended(self) -> None:
    """连接到Extended交易所WebSocket

    Raises:
        ConnectionError: 连接失败

    副作用:
        - 设置self.ws_extended连接对象
        - 启动心跳任务
        - 输出INFO日志
    """
```

```python
async def connect_lighter(self) -> None:
    """连接到Lighter交易所WebSocket

    Raises:
        ConnectionError: 连接失败
    """
```

```python
async def connect_all(self) -> None:
    """连接所有交易所WebSocket

    副作用:
        - 并发调用connect_extended()和connect_lighter()
    """
```

```python
async def disconnect_all(self) -> None:
    """断开所有WebSocket连接

    副作用:
        - 取消心跳任务
        - 关闭所有连接
    """
```

```python
def is_connected(self, exchange: str) -> bool:
    """检查连接状态

    Args:
        exchange: 'extended' 或 'lighter'

    Returns:
        是否已连接
    """
```

### 2.3 订阅管理

```python
async def subscribe_orderbook(self, exchange: str, symbol: str) -> None:
    """订阅订单簿频道

    Args:
        exchange: 'extended' 或 'lighter'
        symbol: 交易对，如 'ETH-USD'

    副作用:
        - 发送订阅消息
        - 设置消息回调处理器
    """
```

```python
def unsubscribe_all(self) -> None:
    """取消所有订阅"""
```

### 2.4 数据获取

```python
def get_orderbook(self, exchange: str) -> Optional[Dict[str, Decimal]]:
    """获取本地缓存的订单簿

    Args:
        exchange: 'extended' 或 'lighter'

    Returns:
        订单簿字典 {'bid': Decimal, 'ask': Decimal, 'timestamp': float}
        如果未连接返回None
    """
```

```python
def get_orderbook_timestamp(self, exchange: str) -> Optional[float]:
    """获取订单簿时间戳

    Args:
        exchange: 'extended' 或 'lighter'

    Returns:
        时间戳（毫秒），如果未连接返回None
    """
```

### 2.5 回调设置

```python
def set_orderbook_callback(self, callback: Callable[[str, Dict], None]) -> None:
    """设置订单簿更新回调

    Args:
        callback: 回调函数，签名为 callback(exchange: str, orderbook: Dict)

    Example:
        def on_orderbook_update(exchange, orderbook):
            print(f"{exchange}: bid={orderbook['bid']}, ask={orderbook['ask']}")

        ws_manager.set_orderbook_callback(on_orderbook_update)
    """
```

---

## 3. ConcurrentExecutor API

并发执行器负责同时向两个交易所发送订单，并记录发送时间差。

### 3.1 并发下单

```python
async def execute_concurrent_orders(
    self,
    extended_order: Dict[str, Any],
    lighter_order: Dict[str, Any],
    timeout_ms: int = 500
) -> tuple[Dict, Dict, float]:
    """并发执行两个交易所的下单

    Args:
        extended_order: Extended订单字典
        lighter_order: Lighter订单字典
        timeout_ms: 超时时间（毫秒）

    Returns:
        (extended_result, lighter_result, send_gap_ms)
        - result: {'success': bool, 'order_id': str, 'error': str}
        - send_gap_ms: 发送时间差（毫秒）

    Raises:
        TimeoutError: 两个订单都超时

    副作用:
        - 记录send_A_ts和send_B_ts
        - 调用monitor.record_concurrent_send_gap()
    """
```

### 3.2 并发平仓

```python
async def execute_concurrent_close(
    self,
    extended_order: Dict[str, Any],
    lighter_order: Dict[str, Any],
    timeout_ms: int = 500
) -> tuple[Dict, Dict, float]:
    """并发执行平仓

    参数和返回值同execute_concurrent_orders
    """
```

### 3.3 紧急平仓

```python
async def emergency_close_position(
    self,
    exchange: str,
    side: str,
    quantity: Decimal,
    timeout_ms: int = 1000
) -> Dict:
    """紧急平仓（单腿）

    Args:
        exchange: 'extended' 或 'lighter'
        side: 'buy' 或 'sell'
        quantity: 数量
        timeout_ms: 超时时间（毫秒）

    Returns:
        {'success': bool, 'order_id': str, 'filled_qty': Decimal, 'error': str}

    Note:
        紧急平仓使用市价单或大滑点限价单，确保必须成交
    """
```

---

## 4. IocOrderManager API

IOC订单管理器负责创建IOC订单、计算激进限价价格、处理部分成交。

### 4.1 创建IOC订单

```python
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
```

### 4.2 计算IOC价格

```python
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
        # 返回: Decimal('3001.50')
    """
```

### 4.3 处理部分成交

```python
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
```

---

## 5. RiskValidator API

风控验证器负责在开仓前进行所有必要的数据和风控检查。

### 5.1 开仓前验证

```python
def validate_opening(
    self,
    opportunity: Dict[str, Any],
    extended_ts: float,
    lighter_ts: float
) -> tuple[bool, str]:
    """综合验证开仓条件

    Args:
        opportunity: 套利机会字典
        extended_ts: Extended数据时间戳
        lighter_ts: Lighter数据时间戳

    Returns:
        (是否有效, 原因)

    Example:
        is_valid, reason = validator.validate_opening(opportunity, ext_ts, lit_ts)
        # (True, "") 或 (False, "数据过期: Extended数据年龄623ms")
    """
```

### 5.2 数据新鲜度验证

```python
def validate_data_freshness(
    self,
    extended_ts: float,
    lighter_ts: float
) -> tuple[bool, List[DataFreshnessResult]]:
    """验证数据新鲜度

    Args:
        extended_ts: Extended数据时间戳
        lighter_ts: Lighter数据时间戳

    Returns:
        (都新鲜, [extended_result, lighter_result])
    """
```

### 5.3 滑点验证

```python
def validate_slippage(
    self,
    expected_price: Decimal,
    current_price: Decimal,
    side: str
) -> SlippageCheckResult:
    """验证滑点

    参数和返回值同monitor.check_slippage()
    """
```

### 5.4 利润率验证

```python
def validate_profitability(
    self,
    spread_rate: Decimal
) -> ProfitabilityCheckResult:
    """验证利润率

    参数和返回值同monitor.check_profitability()
    """
```

### 5.5 单腿持仓检测

```python
def check_leg_risk(
    self,
    extended_filled: bool,
    lighter_filled: bool
) -> tuple[bool, str]:
    """检测单腿持仓风险

    Args:
        extended_filled: Extended是否成交
        lighter_filled: Lighter是否成交

    Returns:
        (有风险, 动作)

    Example:
        has_risk, action = check_leg_risk(True, False)
        # (True, "紧急平仓Extended")
    """
```

---

## 输出格式规范

### 控制台输出

```
⏱️ [行情→交易延迟] 8.45ms | 信号: 1704960123456.78ms | 发送: 1704960123465.23ms
⏱️ [执行延迟] 245.67ms | 发送: 1704960123465.23ms | ACK: 1704960123710.90ms
🔄 [并发发送] Extended→Lighter间隔: 3.21ms ✅ | 阈值: 5ms
📡 [数据新鲜度] ✅ 新鲜 | extended | 数据年龄: 45.2ms | 阈值: 500ms
📊 [滑点检查] ✅ 可接受 | buy | 预期价: $3000.00 | 当前价: $3001.50 | 滑点: 0.05%
💰 [利润检查] ✅ 可交易 | 价差率: 0.10% | 净利: 0.05%
```

### CSV导出

**operations_YYYY_MM_DD.csv**:
```csv
timestamp,operation_type,exchange,signal_ts,data_ts_A,data_ts_B,send_A_ts,send_B_ts,ack_A_ts,ack_B_ts,spread_rate,slippage_rate,profit_rate,decision,status,send_gap_ms
1704960123,OPEN,BOTH,1704960123456.78,1704960123411.23,1704960123404.56,1704960123465.23,1704960123468.44,1704960123710.90,1704960123715.33,0.001000,0.000500,0.000500,ALLOWED,SUCCESS,3.21
```

**performance_YYYY_MM_DD.csv**:
```csv
timestamp,tick_to_trade_latency_ms,execution_latency_ms,concurrent_gap_ms,data_age_A_ms,data_age_B_ms,slippage_rate,decision
1704960123,8.45,245.67,3.21,45.55,52.22,0.000500,ALLOWED
```
