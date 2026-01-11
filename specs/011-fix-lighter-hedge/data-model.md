# Data Model: 修复Lighter对冲失败和实现双腿并发IOC订单系统

**Feature**: 011-fix-lighter-hedge
**Date**: 2026-01-11
**Status**: Final

## 概述

本文档定义了修复Lighter对冲失败和实现双腿并发IOC订单系统所需的所有数据实体。这些模型支持高性能并发交易、闪电回滚、利润验证和数据时效性检查。

## 核心实体

### 1. ConcurrentOrderResult（并发订单执行结果）

**用途**: 表示双腿并发订单的执行结果，包含性能指标和成交状态

```python
@dataclass
class ConcurrentOrderResult:
    """并发订单执行结果

    用于记录Extended和Lighter双腿订单的并发执行情况，
    包含发送时间差、总延迟和成交状态等关键指标。
    """
    # Extended结果
    extended_success: bool
    extended_order_id: Optional[str]
    extended_filled_qty: Decimal
    extended_filled_price: Optional[Decimal]
    extended_error: Optional[str]

    # Lighter结果
    lighter_success: bool
    lighter_order_id: Optional[str]
    lighter_filled_qty: Decimal
    lighter_filled_price: Optional[Decimal]
    lighter_error: Optional[str]

    # 性能指标
    send_a_ts: float          # Extended发送时间戳（毫秒）
    send_b_ts: float          # Lighter发送时间戳（毫秒）
    send_gap_ms: float        # 发送时间差（必须<5ms）
    total_latency_ms: float   # 总执行时间（必须<500ms）

    # 成交状态判断
    is_both_filled: bool      # 双边成交
    is_legging: bool          # 单腿持仓
    is_both_failed: bool      # 双边失败
```

**验证规则**:
- `send_gap_ms < 5.0` (95%的订单)
- `total_latency_ms < 500.0` (90%的订单)
- `is_legging` 时触发闪电回滚
- `is_both_failed` 时放弃交易

**状态转换**:
```
初始 -> 并发发送 -> 等待结果 -> {
    is_both_filled: True  -> 创建SpreadPair
    is_legging: True      -> 触发闪电回滚
    is_both_failed: True  -> 记录失败
}
```

---

### 2. LegRollbackEvent（闪电回滚事件）

**用途**: 记录单腿持仓后的紧急平仓操作

```python
@dataclass
class LegRollbackEvent:
    """闪电回滚事件

    当检测到单腿持仓时，记录紧急平仓的执行情况和性能。
    """
    # 基本信息
    pair_id: int
    legging_side: str              # 'extended' 或 'lighter'
    triggered_at: float            # 触发时间戳（毫秒）

    # 回滚执行
    rollback_started_at: float     # 回滚开始时间（毫秒）
    rollback_completed_at: float   # 回滚完成时间（毫秒）
    rollback_latency_ms: float     # 回滚延迟（必须<500ms）

    # 平仓订单
    exchange: str                  # 执行平仓的交易所
    side: str                      # 平仓方向 ('buy'/'sell')
    quantity: Decimal              # 平仓数量
    order_id: Optional[str]        # 平仓订单ID

    # 执行结果
    rollback_success: bool         # 回滚是否成功
    filled_qty: Decimal            # 实际平仓数量
    filled_price: Optional[Decimal]  # 平仓价格
    rollback_error: Optional[str]  # 错误信息（如果失败）
```

**验证规则**:
- `rollback_latency_ms < 500.0` (95%的回滚)
- `rollback_success = True` 时 `filled_qty == quantity`
- 失败时必须包含`rollback_error`

**重要性**: P1 - 关键安全机制

---

### 3. ProfitabilityCheck（利润检查结果）

**用途**: 验证交易的净利润是否满足要求

```python
@dataclass
class ProfitabilityCheck:
    """利润检查结果

    计算扣除所有成本后的净利润，确保交易有利可图。
    """
    # 输入参数
    spread_rate: Decimal           # 当前价差率
    extended_price: Decimal        # Extended价格
    lighter_price: Decimal         # Lighter价格

    # 成本分解
    total_fees: Decimal            # 双边手续费总和
    extended_fee: Decimal          # Extended手续费
    lighter_fee: Decimal           # Lighter手续费
    expected_slippage: Decimal     # 预期滑点成本

    # 利润计算
    min_net_profit: Decimal        # 最小净利要求（配置）
    required_spread: Decimal       # 所需价差 = fees + slippage + min_profit
    net_profit_rate: Decimal       # 净利润率 = spread - fees - slippage

    # 决策结果
    is_profitable: bool            # 是否可交易
    rejection_reason: Optional[str]  # 拒绝原因（如果不盈利）
```

**验证规则**:
- `is_profitable` 当且仅当 `net_profit_rate > min_net_profit`
- `required_spread = total_fees + expected_slippage + min_net_profit`
- 如果 `total_fees > 0.0006` (0.06%)，记录警告（0.07%价差无法盈利）

**示例计算**:
```
价差率: 0.0010 (0.10%)
双边手续费: 0.00045 (0.045%)
预期滑点: 0.0001 (0.01%)
最小净利: 0.0002 (0.02%)
所需价差: 0.00075 (0.075%)
净利润: 0.00045 (0.045%) > 0.0002 ✅ 可交易
```

**重要性**: P2 - 重要风控机制

---

### 4. DataFreshnessResult（数据新鲜度检查）

**用途**: 检查订单簿数据的时效性，防止基于过期数据交易

```python
@dataclass
class DataFreshnessResult:
    """数据新鲜度检查结果

    验证订单簿数据是否足够新鲜，避免使用过期数据导致交易失败。
    """
    # 检查结果
    data_age_ms: float             # 最大数据年龄（毫秒）
    is_fresh: bool                 # 是否新鲜（<500ms）

    # 详细信息
    extended_age_ms: float         # Extended数据年龄
    lighter_age_ms: float          # Lighter数据年龄
    checked_at: float              # 检查时间戳（毫秒）

    # 警告级别
    warning_level: int             # 0=正常, 1=警告, 2=严重
    warning_message: Optional[str]  # 警告信息
```

**验证规则**:
- `is_fresh` 当且仅当 `data_age_ms < 500.0`
- `warning_level`:
  - 0: `data_age_ms < 300ms`
  - 1: `300ms <= data_age_ms < 500ms`
  - 2: `data_age_ms >= 500ms`（拒绝交易）

**重要性**: P2 - 数据质量保证

---

### 5. OrderCache（订单缓存）

**用途**: 解决WebSocket回调竞态条件，缓存订单结果

```python
class OrderCache:
    """订单结果缓存

    用于解决WebSocket回调可能在订单ID设置前到达的竞态问题。
    """
    def __init__(self):
        self._pending_orders: Dict[int, asyncio.Future] = {}
        self._completed_orders: Dict[int, OrderResult] = {}

    def register_pending(self, client_order_index: int) -> asyncio.Future:
        """注册待处理订单，返回Future供等待"""

    def resolve_pending(self, client_order_index: int, result: OrderResult):
        """WebSocket回调解析订单"""

    def resolve_from_rest(self, client_order_index: int, result: OrderResult):
        """REST API查询结果解析订单"""

    async def wait_for_result(
        self,
        client_order_index: int,
        timeout: float = 1.0
    ) -> Optional[OrderResult]:
        """等待订单结果（WebSocket或REST API）"""

    def cleanup_old(self, max_age_seconds: int = 300):
        """清理旧订单缓存"""
```

**线程安全**: 使用`asyncio.Lock`保护
**容量限制**: 最多保留1000个已完成订单

**重要性**: P1 - 并发安全

---

## 扩展现有实体

### 修改 SpreadPair

**现有字段**（保持不变）:
```python
@dataclass
class SpreadPair:
    pair_id: int
    extended_side: str
    extended_price: Decimal
    extended_quantity: Decimal
    lighter_price: Decimal
    lighter_quantity: Decimal
    open_extended_order_id: str
    open_lighter_order_id: str
    # ... 其他字段
```

**新增字段**:
```python
@dataclass
class SpreadPair:
    # ... 现有字段 ...

    # 新增：并发执行信息
    concurrent_result: Optional[ConcurrentOrderResult] = None
    order_type: str = "IOC"  # 订单类型（IOC/LIMIT）
    send_gap_ms: float = 0.0  # 发送时间差

    # 新增：利润验证信息
    profitability_check: Optional[ProfitabilityCheck] = None

    # 新增：数据新鲜度信息
    data_freshness: Optional[DataFreshnessResult] = None

    # 新增：回滚信息（如果发生过）
    rollback_events: List[LegRollbackEvent] = field(default_factory=list)
```

---

## 关系图

```
ConcurrentOrderResult
    ├── is_legging → LegRollbackEvent (1对多)
    ├── is_both_filled → SpreadPair (1对1)
    └── 性能指标 → PerformanceMonitor

ProfitabilityCheck
    ├── is_profitable → 允许/拒绝交易
    └── 净利润计算 → RiskValidator

DataFreshnessResult
    ├── is_fresh → 允许/拒绝交易
    └── 警告级别 → SafetyMonitor

OrderCache
    ├── client_order_index → OrderResult
    └── WebSocket回调 → resolve_pending()
```

---

## 状态机

### 并发订单执行状态机

```
[开始]
  ↓
[构建订单]
  ↓
[asyncio.gather并发发送] → 记录send_a_ts, send_b_ts
  ↓
[等待结果] (timeout=500ms)
  ↓
┌─────────────────┬─────────────────┬─────────────────┐
│ 双边成交        │ 单腿持仓        │ 双边失败        │
│ (is_both_filled)│ (is_legging)    │ (is_both_failed)│
└─────────────────┴─────────────────┴─────────────────┘
  ↓                  ↓                  ↓
[创建SpreadPair]  [闪电回滚]        [记录失败]
                    ↓
                 [平仓已成交腿]
                    ↓
                 [记录RollbackEvent]
```

### 闪电回滚状态机

```
[检测单腿持仓] (is_legging=True)
  ↓
[触发回滚] (0ms延迟)
  ↓
[市价平仓] (timeout=500ms)
  ↓
┌─────────────────┬─────────────────┐
│ 成功            │ 失败            │
│ (success=True)  │ (success=False) │
└─────────────────┴─────────────────┘
  ↓                  ↓
[记录成功]        [重试/告警]
  ↓
[更新SafetyMonitor]
```

---

## 数据验证

### 并发订单验证

```python
def validate_concurrent_order(result: ConcurrentOrderResult) -> bool:
    """验证并发订单结果"""
    # 性能检查
    if result.send_gap_ms > 5.0:
        logger.warning(f"发送时间差过大: {result.send_gap_ms:.2f}ms")

    if result.total_latency_ms > 500.0:
        logger.warning(f"总延迟过长: {result.total_latency_ms:.2f}ms")

    # 一致性检查
    if result.is_legging:
        # 单腿持仓：必须恰好一边成功
        assert result.extended_success != result.lighter_success

    if result.is_both_failed:
        # 双边失败：两边都失败
        assert not result.extended_success and not result.lighter_success

    return True
```

### 利润验证

```python
def validate_profitability(check: ProfitabilityCheck) -> bool:
    """验证利润检查"""
    # 成本不能超过价差
    if check.total_fees >= check.spread_rate:
        logger.error("手续费超过价差！")
        return False

    # 净利必须为正
    if check.net_profit_rate <= 0:
        logger.warning(f"净利润为负: {check.net_profit_rate:.4%}")
        return False

    # 净利必须超过最小要求
    if check.net_profit_rate < check.min_net_profit:
        logger.info(f"利润不足: {check.net_profit_rate:.4%} < {check.min_net_profit:.4%}")
        return False

    return True
```

---

## 性能考虑

### 内存使用

- `ConcurrentOrderResult`: ~200 bytes/实例
- `LegRollbackEvent`: ~150 bytes/实例
- `ProfitabilityCheck`: ~100 bytes/实例
- `OrderCache`: 最多1000个订单 ~200KB

### 并发安全

- `OrderCache`: 使用`asyncio.Lock`
- `ConcurrentOrderResult`: 不可变（dataclass+frozen）
- `SpreadPair`: 单线程访问（bot主循环）

### 序列化

所有dataclass支持`asdict()`导出到JSON：
```python
from dataclasses import asdict
import json

# 导出到CSV
result_dict = asdict(concurrent_result)
json_str = json.dumps(result_dict)
```

---

## 迁移路径

### Phase 1: 添加新实体（不破坏现有代码）

```python
# spread/models.py

@dataclass
class ConcurrentOrderResult:
    """新增：并发订单执行结果"""
    ...

@dataclass
class LegRollbackEvent:
    """新增：闪电回滚事件"""
    ...

# 现有SpreadPair保持不变
```

### Phase 2: 扩展现有实体

```python
@dataclass
class SpreadPair:
    # 现有字段
    ...

    # 新增字段（可选，默认值保证兼容性）
    concurrent_result: Optional[ConcurrentOrderResult] = None
    rollback_events: List[LegRollbackEvent] = field(default_factory=list)
```

### Phase 3: 更新业务逻辑

```python
# spread/bot.py

async def _open_new_pair_concurrent(...):
    # 使用新的ConcurrentOrderResult
    result = await self.concurrent_executor.execute_dual_leg_orders(...)

    if result.is_legging:
        # 使用新的LegRollbackEvent
        rollback = await self.leg_rollback_handler.execute_emergency_close(...)
        pair.rollback_events.append(rollback)
```

---

## 测试数据

### 并发订单测试数据

```python
# 测试用例1: 双边成交
result = ConcurrentOrderResult(
    extended_success=True,
    lighter_success=True,
    send_gap_ms=2.5,
    total_latency_ms=150.0,
    is_both_filled=True,
    is_legging=False,
    is_both_failed=False,
    ...
)

# 测试用例2: 单腿持仓（Extended成交，Lighter失败）
result = ConcurrentOrderResult(
    extended_success=True,
    lighter_success=False,
    lighter_error="timeout",
    send_gap_ms=3.0,
    total_latency_ms=505.0,
    is_both_filled=False,
    is_legging=True,
    is_both_failed=False,
    ...
)
```

### 利润验证测试数据

```python
# 测试用例1: 利润充足
check = ProfitabilityCheck(
    spread_rate=Decimal('0.0010'),  # 0.10%
    total_fees=Decimal('0.00045'),  # 0.045%
    expected_slippage=Decimal('0.0001'),  # 0.01%
    min_net_profit=Decimal('0.0002'),  # 0.02%
    net_profit_rate=Decimal('0.00045'),  # 0.045%
    is_profitable=True,
    ...
)

# 测试用例2: 利润不足
check = ProfitabilityCheck(
    spread_rate=Decimal('0.0007'),  # 0.07%
    total_fees=Decimal('0.00045'),  # 0.045%
    expected_slippage=Decimal('0.0001'),  # 0.01%
    min_net_profit=Decimal('0.0002'),  # 0.02%
    net_profit_rate=Decimal('0.00015'),  # 0.015%
    is_profitable=False,
    rejection_reason="净利润(0.015%) < 最小要求(0.02%)",
    ...
)
```

---

## 总结

本数据模型定义了实现双腿并发IOC订单系统所需的所有实体：

1. **ConcurrentOrderResult**: 核心并发执行结果
2. **LegRollbackEvent**: 闪电回滚记录
3. **ProfitabilityCheck**: 利润验证
4. **DataFreshnessResult**: 数据新鲜度检查
5. **OrderCache**: WebSocket竞态解决方案

所有实体都支持高性能并发操作，并通过验证规则确保数据一致性。
