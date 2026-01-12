# 数据模型：Lighter-Extended 单向价差收敛套利系统

**功能**: 002-spread-arb | **日期**: 2026-01-12

## 实体关系图

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   SpreadArbBot  │───────│ OrderBookManager│───────│   OrderBook     │
│   (主控制器)     │ 1   2 │   (订单簿管理)   │ 2   1 │   (订单簿数据)   │
└─────────────────┘       └─────────────────┘       └─────────────────┘
        │                                                     │
        │                                                     │
        ▼                                                     ▼
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ StateManager    │       │ SpreadCalculator│       │ RiskManager     │
│ (状态管理)       │       │ (价差计算)       │       │ (风控管理)       │
└─────────────────┘       └─────────────────┘       └─────────────────┘
```

## 核心实体

### 1. SpreadArbBot（套利机器人）

**描述**: 主控制器，协调所有组件执行套利策略

**状态**:
```python
class SpreadArbBot:
    state: BotState  # IDLE, OPENING, HOLDING, CLOSING, ERROR
    position: Position  # 当前持仓信息
    config: BotConfig  # 配置参数
    stats: BotStats  # 统计信息
```

**状态转换**:
```
IDLE → OPENING → HOLDING → CLOSING → IDLE
  ↓         ↓         ↓         ↓
ERROR ← ERROR ← ERROR ← ERROR
```

**验证规则**:
- 只能在 IDLE 状态下开仓
- 只能在 HOLDING 状态下平仓
- ERROR 状态需要手动干预

---

### 2. OrderBook（订单簿）

**描述**: 单个交易所的订单簿数据

**字段**:
```python
class OrderBook:
    exchange: str  # "lighter" 或 "extended"
    symbol: str  # 交易对，如 "BTC-USD"
    bids: Dict[Decimal, Decimal]  # 价格 -> 数量
    asks: Dict[Decimal, Decimal]  # 价格 -> 数量
    last_update: datetime  # 最后更新时间
    sequence: int  # 序列号，用于验证数据完整性
    is_valid: bool  # 数据是否有效
```

**验证规则**:
- 所有价格必须 > 0
- 所有数量必须 >= 0
- 最佳买价必须 < 最佳卖价
- 序列号必须递增

**方法**:
- `calculate_vwap(quantity: Decimal, side: str) -> Decimal`: 计算 VWAP
- `get_best_bid() -> Tuple[Decimal, Decimal]`: 返回最佳买价和数量
- `get_best_ask() -> Tuple[Decimal, Decimal]`: 返回最佳卖价和数量
- `check_depth(quantity: Decimal) -> bool`: 检查深度是否足够

---

### 3. OrderBookManager（订单簿管理器）

**描述**: 管理两个交易所的订单簿，处理 WebSocket 更新

**字段**:
```python
class OrderBookManager:
    lighter_order_book: OrderBook
    extended_order_book: OrderBook
    lighter_ws: LighterWebSocketClient
    extended_ws: ExtendedWebSocketClient
```

**验证规则**:
- 订单簿数据更新时必须验证序列号
- 检测到序列号缺失时重新获取快照
- 订单簿不一致时标记为无效

---

### 4. SpreadCalculator（价差计算器）

**描述**: 计算两个交易所之间的价差

**字段**:
```python
class SpreadCalculator:
    open_threshold: Decimal  # 开仓阈值，默认 0.002 (0.2%)
    close_threshold: Decimal  # 平仓阈值，动态计算
    slippage_buffer: Decimal  # 滑点保护，默认 0.0005 (0.05%)
    min_profit: Decimal  # 最小利润，默认 0.001 (0.1%)
    max_spread: Decimal  # 极端价差阈值，默认 0.05 (5%)
```

**方法**:
- `calculate_open_spread() -> Optional[Decimal]`: 计算开仓价差
- `calculate_close_spread() -> Optional[Decimal]`: 计算平仓价差
- `should_open(position_size: Decimal) -> bool`: 判断是否应该开仓
- `should_close(open_spread: Decimal, position_size: Decimal) -> bool`: 判断是否应该平仓

**价差计算公式**:
```
开仓价差 = (Lighter_Bid_VWAP - Extended_Ask_VWAP) / Extended_Ask_VWAP
平仓价差 = (Lighter_Ask_VWAP - Extended_Bid_VWAP) / Extended_Bid_VWAP
```

**验证规则**:
- 价差必须在 [0, max_spread] 范围内
- VWAP 计算前必须验证订单簿深度
- 极端价差（> max_spread）返回 None

---

### 5. Position（持仓）

**描述**: 当前套利持仓信息

**字段**:
```python
@dataclass
class Position:
    state: PositionState  # NONE, LONG, SHORT
    extended_entry_price: Decimal  # Extended 开仓价格
    lighter_entry_price: Decimal  # Lighter 开仓价格
    entry_spread: Decimal  # 开仓价差
    entry_time: datetime  # 开仓时间
    extended_quantity: Decimal  # Extended 持仓数量
    lighter_quantity: Decimal  # Lighter 持仓数量
    extended_order_id: Optional[str]  # Extended 订单 ID
    lighter_order_id: Optional[str]  # Lighter 订单 ID
```

**验证规则**:
- LONG 状态时：extended_quantity > 0, lighter_quantity < 0
- SHORT 状态时：extended_quantity < 0, lighter_quantity > 0
- 数量必须匹配（绝对值相等）

---

### 6. StateManager（状态管理器）

**描述**: 管理系统状态，支持持久化和恢复

**字段**:
```python
class StateManager:
    current_state: BotState
    position: Optional[Position]
    state_file: Path  # 状态文件路径
    last_save_time: datetime
```

**方法**:
- `save_state()`: 保存当前状态到文件
- `load_state() -> BotState`: 从文件加载状态
- `clear_state()`: 清除状态文件

**状态文件格式** (JSON):
```json
{
  "state": "IDLE",
  "position": null,
  "stats": {
    "total_trades": 0,
    "total_profit": 0,
    "start_time": "2026-01-12T00:00:00Z"
  }
}
```

---

### 7. RiskManager（风控管理器）

**描述**: 风险控制和异常处理

**字段**:
```python
class RiskManager:
    max_single_side_timeout: float = 3.0  # 单边成交超时（秒）
    max_price_deviation: Decimal = Decimal("0.005")  # 0.5%
    required_liquidity_ratio: Decimal = Decimal("1.5")  # 1.5倍
    emergency_shutdown: bool = False
```

**检查项**:
- `check_balance_sufficient(quantity: Decimal, price: Decimal) -> bool`: 检查余额是否充足
- `check_depth_sufficient(order_book: OrderBook, quantity: Decimal) -> bool`: 检查深度是否足够
- `check_spread_reasonable(spread: Decimal) -> bool`: 检查价差是否合理
- `check_execution_timeout(start_time: float) -> bool`: 检查是否超时

**风控动作**:
- `emergency_close_position()`: 紧急平仓
- `reject_trade(reason: str)`: 拒绝交易
- `pause_trading(reason: str)`: 暂停交易

---

### 8. Trade（交易记录）

**描述**: 单笔交易记录

**字段**:
```python
@dataclass
class Trade:
    trade_id: str  # 唯一交易 ID
    timestamp: datetime  # 交易时间
    exchange: str  # "lighter" 或 "extended"
    side: str  # "buy" 或 "sell"
    price: Decimal  # 成交价格
    quantity: Decimal  # 成交数量
    order_type: str  # "OPEN" 或 "CLOSE"
    spread: Optional[Decimal]  # 当时价差
    profit: Optional[Decimal]  # 利润（仅平仓时）
```

**CSV 输出格式**:
```csv
trade_id,timestamp,exchange,side,price,quantity,order_type,spread,profit
```

---

### 9. BotStats（统计信息）

**描述**: 机器人运行统计

**字段**:
```python
@dataclass
class BotStats:
    total_trades: int = 0  # 总交易次数
    profitable_trades: int = 0  # 盈利交易次数
    total_profit: Decimal = Decimal("0")  # 累计利润
    total_fees: Decimal = Decimal("0")  # 累计手续费
    start_time: datetime = None  # 启动时间
    last_trade_time: datetime = None  # 最后交易时间
```

**计算指标**:
- `win_rate: float = profitable_trades / total_trades`
- `avg_profit: Decimal = total_profit / total_trades`
- `uptime: timedelta = now() - start_time`

---

### 10. BotConfig（配置）

**描述**: 机器人配置参数

**字段**:
```python
@dataclass
class BotConfig:
    # 交易参数
    symbol: str = "BTC"  # 交易对
    target_quantity: Decimal = Decimal("0.01")  # 目标交易数量
    min_spread_threshold: Decimal = Decimal("0.002")  # 最小价差阈值 0.2%

    # 风控参数
    slippage_buffer: Decimal = Decimal("0.0005")  # 滑点保护 0.05%
    min_profit: Decimal = Decimal("0.001")  # 最小利润 0.1%
    max_spread: Decimal = Decimal("0.05")  # 极端价差阈值 5%
    single_side_timeout: float = 3.0  # 单边超时 3 秒

    # 交易所配置
    lighter_account_index: int = 0
    lighter_api_key_index: int = 0
    extended_vault: str = ""  # 从环境变量读取
```

**配置来源**:
- 命令行参数（优先级最高）
- 环境变量
- 默认值

---

## 数据流

### 开仓流程数据流

```
1. WebSocket 更新订单簿
   ↓
2. OrderBookManager 更新 OrderBook
   ↓
3. SpreadCalculator 计算价差
   ↓
4. 价差 > 阈值？
   ↓ Yes
5. RiskManager 验证（余额、深度、价差合理性）
   ↓
6. 并发发送订单：
   - Extended 买入
   - Lighter 卖出
   ↓
7. 监控订单成交
   ↓
8. 更新 Position 状态
   ↓
9. 保存 State
```

### 平仓流程数据流

```
1. 持仓中，持续监控价差
   ↓
2. SpreadCalculator 计算平仓价差
   ↓
3. 价差收敛（开仓价差 - 平仓价差 > 利润阈值）？
   ↓ Yes
4. RiskManager 验证
   ↓
5. 并发发送订单：
   - Extended 卖出
   - Lighter 买入
   ↓
6. 监控订单成交
   ↓
7. 计算 Profit
   ↓
8. 更新 Stats
   ↓
9. 清除 Position，保存 State
```

---

## 持久化

### 状态持久化

**文件**: `logs/spread_arb_state.json`

**触发条件**:
- 状态变更（IDLE ↔ HOLDING）
- 每 60 秒定期保存
- 程序退出时

### 交易日志持久化

**文件**: `logs/spread_arb_trades.csv`

**触发条件**:
- 每笔交易成交后立即追加

### 日志文件

**文件**: `logs/spread_arb_YYYYMMDD.log`

**内容**:
- 结构化日志（JSON 格式）
- 按日期轮转

---

## 数据验证

### 输入验证

| 数据类型 | 验证规则 | 错误处理 |
|---------|---------|---------|
| 价格 | > 0 | 拒绝交易 |
| 数量 | > 0 | 拒绝交易 |
| 价差 | 0 <= spread <= max_spread | 视为无效数据 |
| 序列号 | 严格递增 | 重新获取快照 |
| 订单 ID | 非空字符串 | 记录错误 |

### 状态一致性检查

- 持仓数量必须匹配（Extended 和 Lighter 绝对值相等）
- 余额检查：实际余额 >= 持仓价值 + 保留缓冲
- 订单状态：WebSocket 状态与本地状态必须一致
