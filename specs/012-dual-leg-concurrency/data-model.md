# 数据模型设计：双腿并发交易重构

**分支**: `012-dual-leg-concurrency` | **日期**: 2026-01-11

## 概述

本文档定义双腿并发交易功能涉及的数据模型，包括新增实体和扩展现有实体。

## 新增实体

### 1. ConcurrentOrderResult（并发订单执行结果）

**描述**: 记录双腿并发订单的执行结果

```python
@dataclass
class ConcurrentOrderResult:
    """并发订单执行结果

    记录使用asyncio.gather同时发送两个订单的执行结果。
    """
    # Extended订单结果
    extended_success: bool
    extended_order_id: Optional[str]
    extended_filled_qty: Decimal
    extended_filled_price: Optional[Decimal]
    extended_error: Optional[str]

    # Lighter订单结果
    lighter_success: bool
    lighter_order_id: Optional[str]
    lighter_filled_qty: Decimal
    lighter_filled_price: Optional[Decimal]
    lighter_error: Optional[str]

    # 并发执行指标
    send_a_ts: float           # Extended发送时间戳（毫秒）
    send_b_ts: float           # Lighter发送时间戳（毫秒）
    send_gap_ms: float         # 发送时间差（毫秒）
    total_latency_ms: float    # 总执行时间（毫秒）

    # 成交状态
    is_both_filled: bool       # 双边都成交
    is_legging: bool           # 单腿持仓
    is_both_failed: bool       # 双边失败

    def get_filled_ratio(self) -> tuple[Decimal, Decimal]:
        """获取成交比例

        Returns:
            (extended_ratio, lighter_ratio) 成交比例（0-1）
        """
        # TODO: 实现成交比例计算
        pass
```

**状态转换**:

```
[发送中] → [部分成交/完全成交/失败]
     ↓
[单腿持仓检测] → [双边成交/单腿/双边失败]
```

### 2. LegRollbackEvent（单腿回滚事件）

**描述**: 记录单腿持仓检测和回滚操作的详细信息

```python
@dataclass
class LegRollbackEvent:
    """单腿回滚事件

    当一边订单成交而另一边失败时触发。
    """
    # 触发条件
    trigger_time: float           # 触发时间戳（毫秒）
    legging_side: str             # 'extended' 或 'lighter'（成交的一边）
    legging_qty: Decimal          # 成交数量
    legging_price: Decimal        # 成交价格

    # 回滚操作
    rollback_executed: bool       # 是否执行回滚
    rollback_start_ts: float      # 回滚开始时间戳
    rollback_complete_ts: float   # 回滚完成时间戳
    rollback_latency_ms: float    # 回滚耗时（毫秒）

    # 回滚结果
    rollback_success: bool        # 回滚是否成功
    rollback_order_id: Optional[str]  # 回滚订单ID
    rollback_filled_qty: Decimal  # 回滚成交数量
    rollback_error: Optional[str] # 回滚错误信息

    # 风险敞口
    exposure_time_ms: float       # 风险敞口时间（毫秒）
    price_slippage: Optional[Decimal]  # 价格滑点（如果亏损）

    def is_within_sla(self) -> bool:
        """检查回滚是否在SLA内（1秒）"""
        return self.rollback_latency_ms <= 1000
```

**验证规则**:
- `rollback_latency_ms` 必须 <= 1000ms
- `rollback_filled_qty` 应该等于 `legging_qty`
- `exposure_time_ms` 应该最小化

### 3. SimpleCloseDecision（极简平仓决策）

**描述**: 基于净价差的简化平仓决策

```python
@dataclass
class SimpleCloseDecision:
    """极简平仓决策

    只监控当前净价差，不考虑持仓时间等复杂因素。
    """
    # 决策输入
    open_spread_rate: Decimal     # 开仓时价差率
    current_spread_rate: Decimal   # 当前价差率
    target_profit_rate: Decimal    # 目标利润率
    stop_loss_rate: Decimal        # 止损阈值

    # 决策输出
    should_close: bool             # 是否应该平仓
    close_reason: str              # 平仓原因 ('take_profit' 或 'stop_loss')
    spread_delta: Decimal          # 价差变化（当前-开仓）

    # 盈亏估算
    unrealized_pnl: Optional[Decimal]  # 未实现盈亏（USD）

    def calculate_decision(self) -> None:
        """计算平仓决策

        止盈: current_spread <= open_spread - target_profit
        止损: current_spread >= open_spread + stop_loss
        """
        self.spread_delta = self.current_spread_rate - self.open_spread_rate

        if self.current_spread_rate <= (self.open_spread_rate - self.target_profit_rate):
            self.should_close = True
            self.close_reason = 'take_profit'
        elif self.current_spread_rate >= (self.open_spread_rate + self.stop_loss_rate):
            self.should_close = True
            self.close_reason = 'stop_loss'
        else:
            self.should_close = False
            self.close_reason = 'hold'
```

**状态转换**:

```
[持仓中]
     ↓
[价差监控]
     ↓
[价差回归?] → 是 → [止盈平仓]
[价差扩大?] → 是 → [止损平仓]
[都否] → [继续持有]
```

## 扩展现有实体

### 4. 扩展SpreadPair（套利对）

**现有实体**: `spread/spread_pair.py`

**新增字段**:

```python
@dataclass
class SpreadPair:
    # ... 现有字段 ...

    # 新增：并发执行相关
    concurrent_result: Optional[ConcurrentOrderResult] = None
    rollback_event: Optional[LegRollbackEvent] = None

    # 新增：极简平仓相关
    simple_close_decision: Optional[SimpleCloseDecision] = None

    # 新增：订单类型标记
    order_type: str = "IOC"  # 强制使用IOC
```

### 5. 扩展SpreadArbConfig（配置）

**现有实体**: `spread/config.py`

**新增字段**:

```python
@dataclass
class SpreadArbConfig:
    # ... 现有字段 ...

    # 新增：并发执行配置
    enable_dual_leg_concurrent: bool = True
    concurrent_order_send_threshold_ms: float = 5.0

    # 新增：IOC订单配置
    ioc_slippage_tolerance_rate: Decimal = Decimal('0.0005')  # 0.05%
    ioc_slippage_min_rate: Decimal = Decimal('0.0003')       # 0.03%
    ioc_slippage_max_rate: Decimal = Decimal('0.0005')       # 0.05%

    # 新增：单腿回滚配置
    enable_leg_rollback: bool = True
    rollback_timeout_ms: float = 500.0
    rollback_max_retries: int = 3

    # 新增：极简平仓配置
    enable_simple_close: bool = True
    simple_close_target_profit_rate: Decimal = Decimal('0.0002')  # 0.02%
    simple_close_stop_loss_rate: Decimal = Decimal('0.0010')      # 0.10%

    # 新增：利润检查配置
    enable_enhanced_profit_check: bool = True
    min_net_profit_rate: Decimal = Decimal('0.0002')  # 0.02%
    expected_slippage_cost_rate: Decimal = Decimal('0.0001')  # 0.01%
```

## 数据流图

```
[WebSocket订单簿] → [价差计算] → [利润检查] → [并发执行]
                                        ↓
                                   [拒绝/允许]
                                        ↓
                              [ConcurrentOrderResult]
                                        ↓
                        ┌───────────────┴───────────────┐
                        ↓                               ↓
                   [双边成交]                      [单腿持仓]
                        ↓                               ↓
                   [SimpleCloseDecision]          [LegRollbackEvent]
                        ↓                               ↓
                   [极简平仓]                      [紧急回滚]
```

## 存储策略

### 内存存储

- 所有实体的主数据存储在内存中
- 使用Python dataclass + weakref管理生命周期

### 日志存储

- 关键事件写入 `logs/trade.log`
- 性能指标写入 `logs/performance.log`

### CSV导出

- 交易记录 → `data/trades_YYYY_MM_DD.csv`
- 决策记录 → `data/operations_YYYY_MM_DD.csv`
- 性能数据 → `data/performance_YYYY_MM_DD.csv`

## 验证规则汇总

| 实体 | 规则 | 优先级 |
|------|------|--------|
| ConcurrentOrderResult | send_gap_ms <= 5ms | P0 |
| ConcurrentOrderResult | total_latency_ms <= 500ms | P0 |
| LegRollbackEvent | rollback_latency_ms <= 1000ms | P0 |
| LegRollbackEvent | rollback_filled_qty == legging_qty | P0 |
| SimpleCloseDecision | 不能同时是take_profit和stop_loss | P1 |
| SpreadArbConfig | ioc_slippage在min和max范围内 | P1 |
