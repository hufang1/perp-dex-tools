# Research: 价差套利磨损修复

**Feature**: 001-fix-spread-loss
**Date**: 2026-01-10
**Status**: 完成

## 研究目标

通过代码分析和现有数据，确定以下技术决策：

1. Extended maker/taker费率结构
2. Extended post_only订单支持
3. 日志格式选择
4. Maker单超时策略

## 决策1: Extended maker/taker费率结构

### 研究发现

通过阅读`exchanges/extended.py:259`发现：
```python
# For arbitrage, we need fast execution. Always use regular limit orders (not post-only)
# This ensures immediate execution - arbitrage profits should cover taker fees
post_only = False
```

**当前实现**：Extended使用`post_only=False`，意味着订单可以立即成交成为taker。

**配置文件**：`spread/config.py:72`中只有：
```python
extended_fee_rate: Decimal = Decimal('0.000225')  # Extended taker手续费率 (0.0225%)
```

### 决策

**选择**: 假设Extended有maker费率 < taker费率的典型结构

**依据**：
- 大多数交易所的maker费率低于taker费率
- config.py明确标注"taker手续费率"，暗示存在maker费率
- 用户要求"能使用marker这样能节约0.0225的手续费"

**配置建议**：
```python
extended_maker_fee_rate: Decimal = Decimal('0.0001')   # 假设值：0.01%
extended_taker_fee_rate: Decimal = Decimal('0.000225')  # 确认值：0.0225%
```

**后续验证**：运行程序后从实际交易日志中验证手续费率

---

## 决策2: Extended post_only订单支持

### 研究发现

检查`exchanges/extended.py:257-273`：

```python
# 当前代码
post_only = False  # 硬编码为False

order_result = await self.perpetual_trading_client.place_order(
    market_name=contract_id,
    amount_of_synthetic=quantity,
    price=rounded_price,
    side=side,
    time_in_force=TimeInForce.GTT,
    post_only=post_only,  # 支持post_only参数
    expire_time = utc_now() + timedelta(days=1)
)
```

**发现**：Extended SDK的`place_order`方法已经支持`post_only`参数！

### 决策

**选择**: Extended支持post_only maker单，修改`exchanges/extended.py`添加post_only参数控制

**实施方式**：
1. 修改`place_open_order`方法添加`post_only`参数
2. 修改`order_manager.py`调用时传入`post_only=True`
3. 添加超时处理逻辑

**风险**：
- post_only订单可能不成交
- 需要设置合理的超时时间

---

## 决策3: 日志格式选择

### 研究发现

现有`spread/trade_logger.py`使用传统文本格式：
```python
self.logger.info(f"✅ 开仓成功! 套利对 #{pair.pair_id}...")
```

### 决策

**选择**: **JSON Lines格式** (每行一个JSON对象)

**理由**：
1. **易于解析**：可以使用jq、python json库直接处理
2. **结构化**：字段名固定，便于自动化分析
3. **性能**：按行写入，不需要解析整个文件
4. **兼容性**：标准格式，广泛支持

**格式示例**：
```json
{"timestamp": "2026-01-10T05:01:23.456Z", "level": "INFO", "event_type": "EXTENDED_ORDER_PLACED", "data": {...}}
```

**日志轮转**：使用Python的`RotatingFileHandler`或`TimedRotatingFileHandler`

---

## 决策4: Maker单超时策略

### 研究发现

当前`spread/config.py:61`有：
```python
extended_fill_timeout: int = 10  # Extended 成交超时 (秒)
```

### 决策

**超时时间**: **5秒**（新建配置项`maker_timeout_seconds`）

**理由**：
- 太短(3秒)：可能错过成交机会
- 太长(10秒)：价格可能变化，失去套利机会
- 5秒是平衡点

**超时后处理**: **转为taker立即成交**

**理由**：
- 取消订单浪费机会成本
- 转taker可以确保执行
- taker费率成本已计算在预期利润中

**实施**：
```python
# 配置
maker_timeout_seconds: int = 5
maker_timeout_action: str = "convert_to_taker"  # 或 "cancel"

# 逻辑
if wait_duration > maker_timeout_seconds:
    cancel_maker_order()
    place_taker_order()
    log_event("EXTENDED_MAKER_TIMEOUT", converted_to_taker=True)
```

---

## 技术约束确认

| 约束 | 状态 | 说明 |
|------|------|------|
| Decimal精度 | ✅ | 所有价格计算已使用Decimal |
| 异步编程 | ✅ | 已使用asyncio |
| WebSocket | ✅ | 已使用websockets库 |
| 原子性 | ⚠️ | 需要加强：对冲失败时的处理 |
| 日志不阻塞 | ⚠️ | 需要实现：异步日志写入 |

---

## 实施风险评估更新

基于研究，更新风险评估：

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Extended API限制post_only | 低 | 高 | 代码显示SDK支持，测试验证 |
| Maker单成交率 < 50% | 中 | 中 | 5秒超时后转taker |
| 日志I/O阻塞交易 | 低 | 低 | 使用异步写入 |
| 转taker时价格不利 | 中 | 低 | 记录日志，后续分析 |

---

## 后续验证清单

实施后需要验证：

1. ✅ Extended post_only订单能成功提交
2. ✅ Maker单在合理时间内成交
3. ✅ 超时转taker逻辑正常工作
4. ✅ 日志文件格式正确且完整
5. ✅ 可以从日志提取手续费数据
6. ✅ 实际盈亏为正（运行1小时后）

---

**研究结论**: 所有关键决策已确定，可以进入Phase 1设计和实施。
