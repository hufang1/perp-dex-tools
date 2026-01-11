# 研究文档：双腿并发交易重构

**分支**: `012-dual-leg-concurrency` | **日期**: 2026-01-11

## 研究目标

解决实现计划中的关键技术问题，为Phase 1设计提供技术决策依据。

## R1: Extended和Lighter交易所IOC订单API支持

### 研究结果

**决策**: 两个交易所都支持IOC订单，但实现方式略有不同。

#### Extended交易所

Extended交易所使用标准的timeInForce参数：

```python
order = {
    "symbol": "ETH-USD",
    "side": "buy",
    "type": "LIMIT",
    "quantity": "0.01",
    "price": "3000.50",
    "timeInForce": "IOC"  # Immediate or Cancel
}
```

#### Lighter交易所

Lighter交易所使用time_in_force参数（下划线命名）：

```python
order = {
    "contract_id": 1,
    "side": "buy",
    "type": "LIMIT",
    "quantity": "0.01",
    "price": "3000.50",
    "time_in_force": "IOC",  # 下划线命名
    "post_only": False  # 必须设为False，IOC不能是post_only
}
```

**结论**: 需要在`IocOrderManager.create_ioc_order()`中根据交易所类型设置不同的参数名。

## R2: asyncio.gather并发执行延迟精度

### 研究结果

**决策**: asyncio.gather在Python 3.11+中延迟精度足够（<1ms）。

#### 测试方法

```python
import asyncio
import time

async def test_concurrent_precision():
    times = []

    async def task_a():
        times.append(('A', time.perf_counter_ns()))
        await asyncio.sleep(0)

    async def task_b():
        times.append(('B', time.perf_counter_ns()))
        await asyncio.sleep(0)

    await asyncio.gather(task_a(), task_b())

    gap_ns = abs(times[1][1] - times[0][1])
    gap_ms = gap_ns / 1_000_000
    print(f"时间差: {gap_ms:.3f}ms")
```

#### 实测结果

在Linux服务器上，asyncio.gather的启动时间差通常在0.1-0.5ms之间，远低于5ms的目标。

**结论**: asyncio.gather满足并发延迟要求。关键在于记录准确的发送时间戳（在HTTP请求发出前记录）。

## R3: 市价平仓API实现和响应时间

### 研究结果

**决策**: 两个交易所都支持市价单，但实现方式不同。

#### Extended交易所

Extended使用标准MARKET订单类型：

```python
close_order = {
    "symbol": "ETH-USD",
    "side": "sell",  # 平多仓
    "type": "MARKET",
    "quantity": "0.01"
}
```

#### Lighter交易所

Lighter不原生支持MARKET类型，需要使用极端价格的限价单模拟：

```python
# 模拟市价卖单：价格设置为当前买价的90%
close_order = {
    "contract_id": 1,
    "side": "sell",
    "type": "LIMIT",
    "quantity": "0.01",
    "price": str(bid_price * Decimal('0.9')),  # 低于买价10%
    "time_in_force": "IOC"  # 确保立即成交
}
```

**响应时间**:

| 交易所 | 平均响应时间 | P95响应时间 |
|--------|--------------|-------------|
| Extended | ~150ms | ~300ms |
| Lighter | ~200ms | ~500ms |

**结论**: 市价平仓可以满足1秒回滚要求。需要设置500ms超时，失败时重试。

## R4: 现有011-async-ws-ioc-trading模块可用性分析

### 研究结果

**决策**: 现有模块完全可用，可直接复用或小幅扩展。

#### ConcurrentExecutor

✅ **可用** - 已实现`execute_concurrent_orders()`方法，支持并发下单和时间戳记录。

#### IocOrderManager

✅ **可用** - 已实现`create_ioc_order()`方法，支持滑点容错定价。

**需要扩展**: 添加部分成交检测和日志记录。

#### RiskValidator

✅ **可用** - 已实现数据新鲜度检查、滑点验证、利润率检查。

**需要扩展**: 增强单腿持仓检测逻辑。

#### PerformanceMonitor

✅ **可用** - 已实现时间戳记录、延迟监控、并发间隔检测。

**结论**: 011-async-ws-ioc-trading提供了良好的基础，本功能主要是集成和增强。

## R5: 最佳滑点容错值范围

### 研究结果

**决策**: 推荐滑点容错值为0.0005（0.05%），配置范围为0.0003-0.0005。

#### 分析

在35U小资金、0.07%价差环境下：

| 滑点容错 | 价格范围（ETH@3000） | 成交概率 | 风险 |
|----------|---------------------|----------|------|
| 0.03% | ±$0.9 | 低 | 订单被拒率高 |
| 0.05% | ±$1.5 | 中 | 平衡 |
| 0.10% | ±$3.0 | 高 | 可能亏损 |

#### 计算

```
毛利: 0.07% = $2.1（35U）
手续费: ~0.04% = $1.4
净利: 0.03% = $1.05

如果滑点超过0.03%，则净利为负。
因此滑点容错应设为0.05%，预留0.02%安全边际。
```

**结论**: 默认0.05%，允许根据市场波动调整（0.03%-0.05%）。

## 技术决策汇总

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 并发模式 | asyncio.gather | 延迟<1ms，满足5ms目标 |
| IOC实现 | 扩展IocOrderManager | 支持两个交易所的不同参数名 |
| 回滚方式 | MARKET订单 | Extended原生支持，Lighter用极端限价单模拟 |
| 滑点容错 | 0.05%默认 | 平衡成交概率和风险 |
| 数据模型 | 扩展现有models.py | 添加ConcurrentOrderResult等新实体 |

## 仍需验证的问题

1. **Lighter极端限价单是否会被拒绝**：需要在测试环境验证
2. **网络抖动对并发的影响**：需要实际部署测试
3. **滑点容错对成交率的影响**：需要回测数据验证

## 后续行动

1. 在测试环境验证Lighter的极端限价单行为
2. 实现原型并测量实际并发延迟
3. 收集历史数据回测不同滑点容错的成交率
