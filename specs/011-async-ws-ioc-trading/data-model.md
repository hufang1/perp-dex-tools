# 数据模型：异步重构

**功能**: 011-async-ws-ioc-trading
**日期**: 2026-01-11

本文档定义异步重构功能的数据模型，包括实体、字段、验证规则和状态转换。

---

## 核心实体

### 1. OrderBookSnapshot（订单簿快照）

**用途**: 存储单个交易所在特定时刻的最优买卖盘数据

```python
@dataclass
class OrderBookSnapshot:
    """订单簿快照

    从WebSocket接收的订单簿数据快照，包含时间戳用于数据新鲜度检查。
    """
    exchange: str                              # 交易所标识: 'extended' or 'lighter'
    timestamp_ms: float                        # 数据生成时间戳（毫秒，交易所提供）
    bid_price: Decimal                         # 买一价
    ask_price: Decimal                         # 卖一价
    bid_qty: Decimal                           # 买一量
    ask_qty: Decimal                           # 卖一量
    local_update_time: float = field(default_factory=lambda: time.time() * 1000)  # 本地更新时间（毫秒）
    is_stale: bool = False                     # 数据过期标记

    def __post_init__(self):
        """验证数据"""
        if self.bid_price <= 0 or self.ask_price <= 0:
            raise ValueError("价格必须大于0")
        if self.bid_qty < 0 or self.ask_qty < 0:
            raise ValueError("数量不能为负")
        if self.bid_price >= self.ask_price:
            raise ValueError(f"买一价({self.bid_price})必须小于卖一价({self.ask_price})")

    @property
    def spread(self) -> Decimal:
        """价差 = ask_price - bid_price"""
        return self.ask_price - self.bid_price

    @property
    def mid_price(self) -> Decimal:
        """中间价 = (bid_price + ask_price) / 2"""
        return (self.bid_price + self.ask_price) / 2
```

**验证规则**:
- 价格必须大于0
- 数量必须非负
- 买一价必须小于卖一价
- 时间戳必须是正数

**状态转换**: 无（只读快照）

---

### 2. TimingRecord（时间戳记录）

**用途**: 记录关键时间点用于性能分析

```python
@dataclass
class TimingRecord:
    """时间戳记录

    用于记录交易流程中的关键时间点，分析性能瓶颈。
    """
    name: str                                  # 记录名称: 'signal', 'send_A', 'send_B', 'ack_A', 'ack_B'
    timestamp_ms: float                        # 时间戳（毫秒）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 附加元数据

    def __str__(self) -> str:
        return f"[{self.name}] {self.timestamp_ms:.2f}ms"

    def latency_to(self, other: 'TimingRecord') -> float:
        """计算到另一个记录的延迟（毫秒）"""
        return other.timestamp_ms - self.timestamp_ms
```

**验证规则**:
- 时间戳必须大于0
- name必须是预定义的值之一

**使用场景**:
```
signal_ts → calc_ts → send_A_ts ┐
                             ├→ 并发间隔
signal_ts → calc_ts → send_B_ts ┘
```

---

### 3. DataFreshnessResult（数据新鲜度检查结果）

**用途**: 数据时效性验证结果

```python
@dataclass
class DataFreshnessResult:
    """数据新鲜度检查结果

    检查订单簿数据是否在可接受的时间窗口内。
    """
    is_fresh: bool                              # 是否新鲜
    data_age_ms: float                         # 数据年龄（毫秒）
    threshold_ms: float                        # 阈值（毫秒）
    exchange: str                              # 交易所标识
    data_timestamp: float                      # 数据时间戳
    check_timestamp: float                     # 检查时间戳

    def __str__(self) -> str:
        status = "✅ 新鲜" if self.is_fresh else "❌ 过期"
        return (
            f"{status} | {self.exchange} | "
            f"数据年龄: {self.data_age_ms:.1f}ms | "
            f"阈值: {self.threshold_ms:.1f}ms"
        )

    @classmethod
    def fresh(cls, exchange: str, data_ts: float, threshold_ms: float = 500) -> 'DataFreshnessResult':
        """创建新鲜结果"""
        current_time = time.time() * 1000
        data_age = current_time - data_ts
        return cls(
            is_fresh=True,
            data_age_ms=data_age,
            threshold_ms=threshold_ms,
            exchange=exchange,
            data_timestamp=data_ts,
            check_timestamp=current_time
        )

    @classmethod
    def stale(cls, exchange: str, data_ts: float, threshold_ms: float = 500) -> 'DataFreshnessResult':
        """创建过期结果"""
        current_time = time.time() * 1000
        data_age = current_time - data_ts
        return cls(
            is_fresh=False,
            data_age_ms=data_age,
            threshold_ms=threshold_ms,
            exchange=exchange,
            data_timestamp=data_ts,
            check_timestamp=current_time
        )
```

**验证规则**:
- data_age_ms >= 0
- threshold_ms > 0

**决策逻辑**:
```
is_fresh = (data_age_ms <= threshold_ms)
```

---

### 4. SlippageCheckResult（滑点检查结果）

**用途**: 滑点阈值验证结果

```python
@dataclass
class SlippageCheckResult:
    """滑点检查结果

    检查预期价格与当前价格的偏差是否在可接受范围内。
    """
    is_acceptable: bool                        # 是否可接受
    expected_price: Decimal                    # 预期成交价
    current_price: Decimal                     # 当前盘口价
    slippage_rate: Decimal                     # 滑点率（绝对值）
    threshold_rate: Decimal                    # 阈值
    side: str                                  # 方向: 'buy' or 'sell'

    def __str__(self) -> str:
        status = "✅ 可接受" if self.is_acceptable else "❌ 超阈值"
        return (
            f"{status} | {self.side} | "
            f"预期价: ${self.expected_price:.4f} | "
            f"当前价: ${self.current_price:.4f} | "
            f"滑点: {self.slippage_rate:.4%} | "
            f"阈值: {self.threshold_rate:.4%}"
        )

    @property
    def slippage_amount(self) -> Decimal:
        """滑点金额（绝对值）"""
        return abs(self.current_price - self.expected_price)
```

**验证规则**:
- 价格必须大于0
- slippage_rate >= 0
- threshold_rate > 0
- side必须是'buy'或'sell'

**计算逻辑**:
```python
# 买入：当前价越高越不利
if side == 'buy':
    slippage_rate = (current_price - expected_price) / expected_price
else:  # 卖出：当前价越低越不利
    slippage_rate = (expected_price - current_price) / expected_price

is_acceptable = (slippage_rate <= threshold_rate)
```

---

### 5. ProfitabilityCheckResult（利润率检查结果）

**用途**: 利润率验证结果

```python
@dataclass
class ProfitabilityCheckResult:
    """利润率检查结果

    检查扣除成本后的净利润是否满足要求。
    """
    is_profitable: bool                        # 是否可交易
    spread_rate: Decimal                       # 原始价差率
    total_fees: Decimal                        # 双边手续费总和
    expected_slippage: Decimal                 # 预期滑点成本
    min_net_profit: Decimal                    # 最低净利要求
    net_profit_rate: Decimal                   # 净利润率
    decision: str                              # 决策描述

    def __str__(self) -> str:
        status = "✅ 可交易" if self.is_profitable else "❌ 不足利润"
        return (
            f"{status} | "
            f"价差率: {self.spread_rate:.4%} | "
            f"手续费: {self.total_fees:.4%} | "
            f"预期滑点: {self.expected_slippage:.4%} | "
            f"最小净利: {self.min_net_profit:.4%} | "
            f"净利: {self.net_profit_rate:.4%} | "
            f"决策: {self.decision}"
        )

    @property
    def profit_margin(self) -> Decimal:
        """利润边际 = net_profit_rate - min_net_profit"""
        return self.net_profit_rate - self.min_net_profit
```

**验证规则**:
- 所有费率必须非负
- spread_rate >= 0

**计算逻辑**:
```python
net_profit_rate = spread_rate - total_fees - expected_slippage
is_profitable = (net_profit_rate >= min_net_profit)
```

**决策**:
```python
if is_profitable:
    decision = "允许开仓"
else:
    decision = "拒绝开仓（利润不足）"
```

---

### 6. TradeOperationRecord（交易操作记录）

**用途**: 完整记录一次交易操作的所有时间戳和结果

```python
@dataclass
class TradeOperationRecord:
    """交易操作记录

    记录开仓/平仓的完整时间戳链和结果，用于性能分析和复盘。
    """
    timestamp: float                           # 记录时间戳
    operation_type: str                        # 操作类型: 'OPEN', 'CLOSE', 'EMERGENCY_CLOSE'
    exchange: str                              # 交易所: 'BOTH', 'EXTENDED', 'LIGHTER'

    # 时间戳链（全部可选）
    signal_ts: Optional[float] = None          # 策略信号触发时间
    data_ts_A: Optional[float] = None          # Extended数据时间
    data_ts_B: Optional[float] = None          # Lighter数据时间
    calc_ts: Optional[float] = None            # 计算完成时间
    send_A_ts: Optional[float] = None          # Extended发送时间
    send_B_ts: Optional[float] = None          # Lighter发送时间
    ack_A_ts: Optional[float] = None           # Extended ACK时间
    ack_B_ts: Optional[float] = None           # Lighter ACK时间

    # 交易数据
    spread_rate: Optional[Decimal] = None      # 价差率
    slippage_rate: Optional[Decimal] = None    # 实际滑点率
    profit_rate: Optional[Decimal] = None      # 利润率

    # 结果
    decision: str = "PENDING"                  # 决策: 'ALLOWED', 'REJECTED', ...
    status: str = "PENDING"                    # 状态: 'SUCCESS', 'FAILED', 'PARTIAL'
    reason: Optional[str] = None               # 失败原因

    # 并发指标
    send_gap_ms: Optional[float] = None        # 并发发送间隔

    def __post_init__(self):
        """设置默认timestamp"""
        if self.timestamp == 0:
            self.timestamp = time.time()

    @property
    def tick_to_trade_latency_ms(self) -> Optional[float]:
        """行情→交易延迟"""
        if self.signal_ts and self.send_A_ts:
            return self.send_A_ts - self.signal_ts
        return None

    @property
    def execution_latency_ms(self) -> Optional[float]:
        """执行延迟"""
        if self.send_A_ts and self.ack_A_ts:
            return self.ack_A_ts - self.send_A_ts
        return None

    @property
    def data_freshness_A_ms(self) -> Optional[float]:
        """Extended数据年龄"""
        if self.data_ts_A and self.signal_ts:
            return self.signal_ts - self.data_ts_A
        return None

    @property
    def data_freshness_B_ms(self) -> Optional[float]:
        """Lighter数据年龄"""
        if self.data_ts_B and self.signal_ts:
            return self.signal_ts - self.data_ts_B
        return None

    def to_csv_row(self) -> Dict[str, str]:
        """转换为CSV行"""
        return {
            'timestamp': str(int(self.timestamp)),
            'operation_type': self.operation_type,
            'exchange': self.exchange,
            'signal_ts': f"{self.signal_ts:.2f}" if self.signal_ts else '',
            'data_ts_A': f"{self.data_ts_A:.2f}" if self.data_ts_A else '',
            'data_ts_B': f"{self.data_ts_B:.2f}" if self.data_ts_B else '',
            'send_A_ts': f"{self.send_A_ts:.2f}" if self.send_A_ts else '',
            'send_B_ts': f"{self.send_B_ts:.2f}" if self.send_B_ts else '',
            'ack_A_ts': f"{self.ack_A_ts:.2f}" if self.ack_A_ts else '',
            'ack_B_ts': f"{self.ack_B_ts:.2f}" if self.ack_B_ts else '',
            'spread_rate': f"{self.spread_rate:.6f}" if self.spread_rate is not None else '',
            'slippage_rate': f"{self.slippage_rate:.6f}" if self.slippage_rate is not None else '',
            'profit_rate': f"{self.profit_rate:.6f}" if self.profit_rate is not None else '',
            'decision': self.decision,
            'status': self.status,
            'send_gap_ms': f"{self.send_gap_ms:.2f}" if self.send_gap_ms is not None else ''
        }
```

---

## 实体关系

```
OrderBookSnapshot (交易所数据)
        ↓
    [计算价差]
        ↓
SpreadOpportunity (套利机会)
        ↓
    [风控验证]
        ↓
DataFreshnessResult ──┐
SlippageCheckResult ───┤→ 决策
ProfitabilityCheckResult─┘
        ↓
    [执行交易]
        ↓
TradeOperationRecord (完整记录)
```

---

## 数据流

### 开仓流程数据流

```
1. WebSocket推送 → OrderBookSnapshot
2. 计算价差 → SpreadOpportunity
3. 数据新鲜度检查 → DataFreshnessResult
4. 滑点检查 → SlippageCheckResult
5. 利润率检查 → ProfitabilityCheckResult
6. 决策记录 → TradeOperationRecord (部分字段)
7. 并发下单 → 记录send_A_ts, send_B_ts
8. 收到ACK → 记录ack_A_ts, ack_B_ts
9. 更新TradeOperationRecord → 写入CSV
```

---

## CSV导出格式

### operations_YYYY_MM_DD.csv

```csv
timestamp,operation_type,exchange,signal_ts,data_ts_A,data_ts_B,send_A_ts,send_B_ts,ack_A_ts,ack_B_ts,spread_rate,slippage_rate,profit_rate,decision,status,send_gap_ms
1704960123,OPEN,BOTH,1704960123456.78,1704960123411.23,1704960123404.56,1704960123465.23,1704960123468.44,1704960123710.90,1704960123715.33,0.001000,0.000500,0.000500,ALLOWED,SUCCESS,3.21
1704960189,CLOSE,BOTH,1704960189123.45,1704960189100.00,1704960189095.00,1704960189130.12,1704960189132.67,1704960189380.00,1704960189385.00,0.000200,0.000300,0.000150,ALLOWED,SUCCESS,2.55
```

### performance_YYYY_MM_DD.csv

```csv
timestamp,tick_to_trade_latency_ms,execution_latency_ms,concurrent_gap_ms,data_age_A_ms,data_age_B_ms,slippage_rate,decision
1704960123,8.45,245.67,3.21,45.55,52.22,0.000500,ALLOWED
1704960189,6.78,249.88,2.55,23.45,28.45,0.000300,ALLOWED
```

---

## 配置参数映射

数据模型中使用的阈值来自`SpreadArbConfig`：

| 模型字段 | 配置参数 | 默认值 |
|----------|----------|--------|
| threshold_ms | max_data_age_ms | 500ms |
| threshold_rate | ioc_slippage_tolerance_rate | 0.05% |
| min_net_profit | min_net_profit_rate | 0.02% |
| expected_slippage | expected_slippage_cost_rate | 0.01% |
| total_fees | extended_taker_fee + lighter_fee | 0.04% |
