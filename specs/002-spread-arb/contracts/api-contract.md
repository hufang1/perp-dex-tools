# API 契约：Lighter-Extended 单向价差收敛套利系统

**功能**: 002-spread-arb | **日期**: 2026-01-12

## 概述

本文档定义了套利机器人内部组件之间的接口契约。这是一个独立运行的 Python 应用程序，不提供外部 HTTP API，而是通过内部组件接口进行通信。

## 组件接口

### 1. OrderBookManager（订单簿管理器）

```python
class OrderBookManager:
    """管理两个交易所的订单簿数据"""

    async def get_order_book(self, exchange: str) -> OrderBook:
        """
        获取指定交易所的订单簿

        Args:
            exchange: "lighter" 或 "extended"

        Returns:
            OrderBook 对象

        Raises:
            ValueError: 交易所名称无效
            OrderBookNotReadyError: 订单簿数据未就绪
        """
        pass

    async def calculate_vwap(
        self,
        exchange: str,
        quantity: Decimal,
        side: str
    ) -> Decimal:
        """
        计算指定交易所的 VWAP

        Args:
            exchange: "lighter" 或 "extended"
            quantity: 目标交易数量
            side: "buy" 或 "sell"

        Returns:
            VWAP 价格

        Raises:
            InsufficientDepthError: 订单簿深度不足
        """
        pass

    def is_ready(self) -> bool:
        """
        检查订单簿是否就绪

        Returns:
            两个交易所的订单簿都已加载且有效
        """
        pass

    async def start(self) -> None:
        """启动 WebSocket 连接"""
        pass

    async def stop(self) -> None:
        """停止 WebSocket 连接"""
        pass
```

**事件回调**:

```python
class OrderBookUpdateHandler(Protocol):
    async def on_orderbook_update(self, exchange: str) -> None:
        """订单簿更新时调用"""
        pass
```

---

### 2. SpreadCalculator（价差计算器）

```python
class SpreadCalculator:
    """计算两个交易所之间的价差"""

    def __init__(
        self,
        open_threshold: Decimal = Decimal("0.002"),
        slippage_buffer: Decimal = Decimal("0.0005"),
        min_profit: Decimal = Decimal("0.001"),
        max_spread: Decimal = Decimal("0.05")
    ):
        """
        初始化价差计算器

        Args:
            open_threshold: 开仓阈值（默认 0.2%）
            slippage_buffer: 滑点保护（默认 0.05%）
            min_profit: 最小利润（默认 0.1%）
            max_spread: 极端价差阈值（默认 5%）
        """
        pass

    async def calculate_open_spread(
        self,
        order_book_manager: OrderBookManager,
        quantity: Decimal
    ) -> Optional[SpreadInfo]:
        """
        计算开仓价差

        Args:
            order_book_manager: 订单簿管理器
            quantity: 目标交易数量

        Returns:
            SpreadInfo 对象，如果价差无效返回 None

        SpreadInfo:
            value: Decimal  # 价差值（百分比）
            extended_vwap: Decimal  # Extended VWAP
            lighter_vwap: Decimal  # Lighter VWAP
            is_valid: bool  # 是否有效
        """
        pass

    async def calculate_close_spread(
        self,
        order_book_manager: OrderBookManager,
        quantity: Decimal
    ) -> Optional[SpreadInfo]:
        """
        计算平仓价差

        Args:
            order_book_manager: 订单簿管理器
            quantity: 目标交易数量

        Returns:
            SpreadInfo 对象，如果价差无效返回 None
        """
        pass

    def should_open(self, spread: Decimal) -> bool:
        """
        判断是否应该开仓

        Args:
            spread: 当前价差

        Returns:
            是否满足开仓条件
        """
        pass

    def should_close(
        self,
        open_spread: Decimal,
        close_spread: Decimal
    ) -> bool:
        """
        判断是否应该平仓

        Args:
            open_spread: 开仓价差
            close_spread: 当前平仓价差

        Returns:
            是否满足平仓条件（开仓价差 - 平仓价差 > 手续费 + 最小利润）
        """
        pass
```

---

### 3. RiskManager（风控管理器）

```python
class RiskManager:
    """风险控制和异常处理"""

    async def validate_open_position(
        self,
        order_book_manager: OrderBookManager,
        quantity: Decimal,
        spread: SpreadInfo
    ) -> ValidationResult:
        """
        验证开仓条件

        Args:
            order_book_manager: 订单簿管理器
            quantity: 目标交易数量
            spread: 价差信息

        Returns:
            ValidationResult:
                is_valid: bool
                reason: Optional[str]  # 拒绝原因
        """
        pass

    async def validate_close_position(
        self,
        position: Position,
        quantity: Decimal,
        spread: SpreadInfo
    ) -> ValidationResult:
        """
        验证平仓条件

        Args:
            position: 当前持仓
            quantity: 目标交易数量
            spread: 价差信息

        Returns:
            ValidationResult
        """
        pass

    async def check_balance(
        self,
        exchange: str,
        quantity: Decimal,
        price: Decimal
    ) -> bool:
        """
        检查余额是否充足

        Args:
            exchange: "lighter" 或 "extended"
            quantity: 交易数量
            price: 交易价格

        Returns:
            余额是否充足
        """
        pass

    def is_spread_reasonable(self, spread: Decimal) -> bool:
        """
        检查价差是否合理（不是极端价差）

        Args:
            spread: 价差值

        Returns:
            价差是否合理（<= 5%）
        """
        pass

    async def emergency_close(
        self,
        exchange_client,
        position: Position
    ) -> bool:
        """
        紧急平仓

        Args:
            exchange_client: 交易所客户端
            position: 持仓信息

        Returns:
            是否成功
        """
        pass
```

---

### 4. StateManager（状态管理器）

```python
class StateManager:
    """管理系统状态和持久化"""

    def __init__(self, state_file: Path):
        """
        初始化状态管理器

        Args:
            state_file: 状态文件路径
        """
        pass

    async def load_state(self) -> BotState:
        """
        加载状态

        Returns:
            当前机器人状态

        Raises:
            StateLoadError: 状态加载失败
        """
        pass

    async def save_state(
        self,
        state: BotState,
        position: Optional[Position],
        stats: BotStats
    ) -> None:
        """
        保存状态

        Args:
            state: 机器人状态
            position: 持仓信息
            stats: 统计信息
        """
        pass

    async def clear_state(self) -> None:
        """清除状态文件"""
        pass

    def get_position(self) -> Optional[Position]:
        """获取当前持仓"""
        pass

    def update_position(self, position: Position) -> None:
        """更新持仓信息"""
        pass

    def get_state(self) -> BotState:
        """获取机器人状态"""
        pass

    def set_state(self, state: BotState) -> None:
        """设置机器人状态"""
        pass
```

---

### 5. TradeExecutor（交易执行器）

```python
class TradeExecutor:
    """执行交易订单"""

    def __init__(
        self,
        lighter_client: LighterClient,
        extended_client: ExtendedClient,
        risk_manager: RiskManager
    ):
        """
        初始化交易执行器

        Args:
            lighter_client: Lighter 客户端
            extended_client: Extended 客户端
            risk_manager: 风控管理器
        """
        pass

    async def execute_open_position(
        self,
        quantity: Decimal,
        spread: SpreadInfo
    ) -> ExecutionResult:
        """
        执行开仓（并发发送订单）

        Args:
            quantity: 交易数量
            spread: 价差信息

        Returns:
            ExecutionResult:
                success: bool
                extended_order_id: Optional[str]
                lighter_order_id: Optional[str]
                extended_price: Optional[Decimal]
                lighter_price: Optional[Decimal]
                error_message: Optional[str]
                execution_time: float  # 执行时间（秒）
        """
        pass

    async def execute_close_position(
        self,
        position: Position,
        quantity: Decimal
    ) -> ExecutionResult:
        """
        执行平仓（并发发送订单）

        Args:
            position: 当前持仓
            quantity: 交易数量

        Returns:
            ExecutionResult
        """
        pass

    async def wait_for_execution(
        self,
        extended_order_id: str,
        lighter_order_id: str,
        timeout: float = 3.0
    ) -> ExecutionStatus:
        """
        等待订单执行

        Args:
            extended_order_id: Extended 订单 ID
            lighter_order_id: Lighter 订单 ID
            timeout: 超时时间（秒）

        Returns:
            ExecutionStatus:
                both_filled: bool  # 两边都成交
                extended_filled: bool
                lighter_filled: bool
                timeout: bool
        """
        pass

    async def rollback_position(
        self,
        exchange: str,
        quantity: Decimal
    ) -> bool:
        """
        强平（单边成交时使用）

        Args:
            exchange: 需要强平的交易所
            quantity: 数量

        Returns:
            是否成功
        """
        pass
```

---

### 6. SpreadArbBot（主控制器）

```python
class SpreadArbBot:
    """套利机器人主控制器"""

    def __init__(self, config: BotConfig):
        """
        初始化机器人

        Args:
            config: 配置对象
        """
        pass

    async def start(self) -> None:
        """启动机器人"""
        pass

    async def stop(self) -> None:
        """停止机器人"""
        pass

    async def run_trading_loop(self) -> None:
        """运行主交易循环"""
        pass

    def get_stats(self) -> BotStats:
        """获取统计信息"""
        pass

    def get_status(self) -> BotStatus:
        """
        获取机器人状态

        Returns:
            BotStatus:
                state: BotState
                position: Optional[Position]
                current_spread: Optional[Decimal]
                uptime: timedelta
                last_trade_time: Optional[datetime]
        """
        pass
```

---

## 数据结构

### OrderBook（订单簿）

```python
@dataclass
class OrderBook:
    exchange: str
    symbol: str
    bids: Dict[Decimal, Decimal]  # 价格 -> 数量
    asks: Dict[Decimal, Decimal]
    last_update: datetime
    sequence: int
    is_valid: bool
```

### SpreadInfo（价差信息）

```python
@dataclass
class SpreadInfo:
    value: Decimal  # 价差值（百分比）
    extended_vwap: Decimal
    lighter_vwap: Decimal
    is_valid: bool
    timestamp: datetime
```

### Position（持仓）

```python
@dataclass
class Position:
    state: PositionState
    extended_entry_price: Decimal
    lighter_entry_price: Decimal
    entry_spread: Decimal
    entry_time: datetime
    extended_quantity: Decimal
    lighter_quantity: Decimal
    extended_order_id: Optional[str]
    lighter_order_id: Optional[str]
```

### BotStats（统计信息）

```python
@dataclass
class BotStats:
    total_trades: int
    profitable_trades: int
    total_profit: Decimal
    total_fees: Decimal
    start_time: Optional[datetime]
    last_trade_time: Optional[datetime]
```

### BotConfig（配置）

```python
@dataclass
class BotConfig:
    symbol: str
    target_quantity: Decimal
    min_spread_threshold: Decimal
    slippage_buffer: Decimal
    min_profit: Decimal
    max_spread: Decimal
    single_side_timeout: float
    lighter_account_index: int
    lighter_api_key_index: int
```

---

## 错误类型

```python
class SpreadArbError(Exception):
    """基础错误类"""
    pass

class OrderBookNotReadyError(SpreadArbError):
    """订单簿未就绪"""
    pass

class InsufficientDepthError(SpreadArbError):
    """订单簿深度不足"""
    pass

class RiskValidationFailedError(SpreadArbError):
    """风控验证失败"""
    pass

class ExecutionTimeoutError(SpreadArbError):
    """执行超时"""
    pass

class StateLoadError(SpreadArbError):
    """状态加载失败"""
    pass

class BalanceInsufficientError(SpreadArbError):
    """余额不足"""
    pass
```

---

## 事件类型

```python
@dataclass
class OrderBookUpdateEvent:
    exchange: str
    timestamp: datetime

@dataclass
class SpreadUpdateEvent:
    open_spread: Optional[Decimal]
    close_spread: Optional[Decimal]
    timestamp: datetime

@dataclass
class PositionOpenedEvent:
    position: Position
    execution_time: float

@dataclass
class PositionClosedEvent:
    position: Position
    profit: Decimal
    execution_time: float

@dataclass
class RiskEvent:
    level: str  # "WARNING", "ERROR", "CRITICAL"
    message: str
    timestamp: datetime
```
