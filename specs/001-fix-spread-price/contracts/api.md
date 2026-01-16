# API Contracts: 修复Spread套利脚本价格同步问题

**Feature**: 001-fix-spread-price
**Date**: 2026-01-16

---

## 概述

本文档定义了修复spread套利脚本价格同步问题所涉及的核心API契约。

---

## 核心API契约

### 1. execute_open_position

**位置**: `spread/trade_executor.py`

**签名**:
```python
async def execute_open_position(
    self,
    quantity: Decimal,
    spread: Union[RealTimeSpreadInfo, SpreadInfo]
) -> ExecutionResult
```

**行为变更**:
- **Before**: 从spread参数获取价格，各自独立获取BBO价格
- **After**: 在execute_open_position层面统一并发获取价格

**输入**:
```python
quantity: Decimal          # 交易数量，例如 Decimal('0.21')
spread: Union[RealTimeSpreadInfo, SpreadInfo]  # 价差信息（仅用于日志）
```

**输出**:
```python
ExecutionResult {
    success: bool              # 是否成功
    extended_order_id: str      # Ext订单ID
    lighter_order_id: str       # Lig订单ID
    extended_price: Decimal     # Ext使用价格
    lighter_price: Decimal      # Lig使用价格
    error_message: str | None   # 错误信息
    execution_time: float       # 执行耗时（秒）
    extended_filled: bool       # Ext是否成交
    lighter_filled: bool        # Lig是否成交
}
```

**异常处理**:
- `ValueError`: 价格获取失败或价格不一致
- 记录错误日志并返回失败的ExecutionResult

---

### 2. _place_extended_order_taker

**位置**: `spread/trade_executor.py`

**签名**:
```python
async def _place_extended_order_taker(
    self,
    side: str,
    quantity: Decimal,
    price: Optional[Decimal]
) -> Dict[str, Any]
```

**行为变更**:
- **Before**: 买入价 = `best_ask`（0%滑点）
- **After**: 买入价 = `best_ask * 1.002`（0.2%滑点）

**输入**:
```python
side: str                   # "buy" 或 "sell"
quantity: Decimal           # 交易数量
price: Optional[Decimal]    # 价格（None时自动计算，通常从execute_open_position传入）
```

**输出**:
```python
Dict[str, Any] {
    "order_id": str,          # 订单ID
    "price": Decimal          # 使用价格
}
```

**滑点计算**:
```python
# 买入（做多）
price = best_ask * Decimal('1.002')

# 卖出（做空）
price = best_bid * Decimal('0.998')
```

---

### 3. place_taker_order (Extended Client)

**位置**: `exchanges/extended.py`

**签名**:
```python
async def place_taker_order(
    self,
    contract_id: str,
    quantity: Decimal,
    side: str,
    price: Decimal,
    max_retries: int = 1  # ✅ 新增参数
) -> OrderResult
```

**行为变更**:
- **Before**: 最多重试10次，每次重试重新获取价格
- **After**: 最多重试1次，使用原始价格

**输入**:
```python
contract_id: str           # 合约ID
quantity: Decimal          # 数量
side: str                 # "buy" 或 "sell"
price: Decimal             # 价格（不变）
max_retries: int = 1      # 最大重试次数（新增，默认1）
```

**输出**:
```python
OrderResult {
    success: bool
    order_id: str
    side: str
    size: Decimal
    price: Decimal
    status: str
    filled_size: Decimal
    error_message: str | None
}
```

**重试行为**:
- 使用缓存的 `original_price`，不重新获取BBO价格
- 最多重试1次（总共最多2次下单尝试）
- 失败后记录日志：`"Taker order not filled, retrying (1/1)..."`

---

### 4. PriceSnapshot

**位置**: `spread/price_snapshot.py`（新建）

**签名**:
```python
@dataclass
class PriceSnapshot:
    ext_bid: Decimal
    ext_ask: Decimal
    ext_timestamp: float
    lig_bid: Decimal
    lig_ask: Decimal
    lig_timestamp: float
    time_delta: float

    def is_valid(self) -> bool
    def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]
    def validate_price_consistency(self) -> bool
```

**验证规则**:

| 方法 | 条件 |
|------|------|
| `is_valid()` | `time_delta < 0.01` 且所有价格有效 |
| `calculate_taker_prices()` | `return (ext_ask*1.002, lig_bid*0.998)` |
| `validate_price_consistency()` | `ext_ask*1.002 < lig_bid*0.998` |

---

## 数据流契约

### 开仓流程数据流

```
[SpreadMonitor]
    │
    │ RealTimeSpreadInfo
    │ (仅用于日志，不用于价格)
    ▼
[execute_open_position]
    │
    ├─→ [并发获取价格]
    │   ├─ ext.fetch_bbo_prices()
    │   │   返回: (ext_bid, ext_ask)
    │   │   记录: ext_timestamp
    │   │
    │   └─ lig.fetch_bbo_prices()
    │       返回: (lig_bid, lig_ask)
    │       记录: lig_timestamp
    │
    ├─→ [创建PriceSnapshot]
    │   输入: ext_bid, ext_ask, ext_timestamp
    │         lig_bid, lig_ask, lig_timestamp
    │   计算: time_delta = abs(lig_timestamp - ext_timestamp)
    │
    ├─→ [验证价格快照]
    │   条件: is_valid() == True
    │   失败 → 返回 ExecutionResult(success=False)
    │
    ├─→ [计算taker价格]
    │   ext_price = ext_ask * 1.002
    │   lig_price = lig_bid * 0.998
    │
    ├─→ [验证价格一致性]
    │   条件: ext_price < lig_price
    │   失败 → 返回 ExecutionResult(success=False)
    │
    └─→ [并发发送订单]
        ├─ _place_extended_order_taker("buy", quantity, ext_price)
        └─ _place_lighter_order_taker("sell", quantity, lig_price)
            │
            └─→ [返回ExecutionResult]
```

---

## 时间要求

### 性能指标

| 阶段 | 目标时间 | 测量方法 |
|------|----------|----------|
| 价格获取（并发） | <10ms | time_delta |
| 价格计算 | <1ms | 代码执行时间 |
| 订单发送 | <20ms | API调用时间 |
| 总执行时间 | <50ms | execution_time |

### 延迟来源

- **并发获取**: 5-10ms（取决于两个交易所API响应时间）
- **价格计算**: <1ms（简单的乘法运算）
- **订单发送**: 10-20ms（取决于网络和交易所处理）
- **订单查询**: 10-20ms（Extended需要查询订单状态）

---

## 错误处理契约

### 错误类型

| 错误类型 | 触发条件 | 处理方式 |
|----------|----------|----------|
| 价格快照无效 | time_delta >= 10ms | 返回失败，跳过开仓 |
| 价差异常 | ext_price >= lig_price | 返回失败，跳过开仓 |
| 价格获取失败 | API异常 | 返回失败，跳过开仓 |
| 订单失败 | IOC被取消 | 根据重试策略处理 |

### 日志级别

| 级别 | 用途 | 示例 |
|------|------|------|
| INFO | 正常流程 | "价格同步: ext=XXX, lig=XXX, time_delta=5.2ms" |
| WARNING | 非致命问题 | "价格快照无效: time_delta=15.2ms" |
| ERROR | 致命问题 | "价差异常: ext=XXX >= lig=XXX" |

---

## 向后兼容性

### 保持兼容

- ✅ `_place_lighter_order_taker`: 接口不变
- ✅ `ExecutionResult`: 返回值结构不变
- ✅ `OpenPositionRecord`: 现有字段保持

### 新增接口

- ✅ `PriceSnapshot`: 新增类
- ✅ `place_taker_order.max_retries`: 新增参数（有默认值）
- ✅ `execute_open_position`: 内部实现变更，接口不变

### 弃用接口

- ⚠️ `place_open_order`: 添加DeprecationWarning
- ⚠️ `get_order_price`: 添加DeprecationWarning

---

## 测试契约

### 单元测试要求

| 测试类 | 覆盖方法 | 测试场景 |
|--------|----------|----------|
| TestPriceSnapshot | PriceSnapshot所有方法 | 有效/无效快照、taker价格计算、一致性验证 |
| TestTradeExecutor | execute_open_position | 价格同步、价差异常、超时处理 |
| TestExtendedSlippage | _place_extended_order_taker | 滑点计算、价格正确性 |
| TestExtendedRetry | place_taker_order | 重试逻辑、原始价格使用 |

### 集成测试要求

| 测试场景 | 验证内容 | 成功标准 |
|----------|----------|----------|
| 正常开仓 | 完整开仓流程 | 仓位平衡、成本正确 |
| 价差异常 | 跳过开仓逻辑 | 不开仓、无错误 |
| 时间超时 | 处理超时场景 | 优雅降级、记录日志 |
| IOC失败 | 重试机制 | 最多1次重试、使用原始价格 |

---

**版本**: 1.0
**最后更新**: 2026-01-16
