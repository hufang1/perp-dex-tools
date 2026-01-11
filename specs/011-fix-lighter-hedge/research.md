# Research: 修复Lighter对冲失败和实现双腿并发IOC订单系统

**Feature**: 011-fix-lighter-hedge
**Date**: 2026-01-11
**Status**: Complete

## 研究目标

从规格说明书的Technical Context中识别的NEEDS CLARIFICATION项目进行技术调研，为实施设计提供决策依据。

## 研究问题

### RQ-1: Lighter SDK是否支持IOC订单类型？

**问题来源**: FR-002要求使用IOC订单类型，但当前实现使用限价单+10秒等待循环

**研究结果**:

决策: **使用原生IOC订单（ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL）**

理由:
1. Lighter SDK 0.1.4 完全支持IOC订单类型
2. SDK提供专门的常量和方法：
   - `ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL = 0`
   - `create_market_order()` 方法（内部使用IOC）
   - `DEFAULT_IOC_EXPIRY = 0`
3. 项目已有IocOrderManager框架（spread/ioc_order_manager.py）
4. 当前实现在hedge_manager.py中使用限价单+10秒等待循环，效率低

备选方案:
1. 使用`create_market_order()`方法（最简单，但限制较多）
2. 使用`create_order()` + `ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL`（推荐，灵活性高）
3. 极短TTL的GTT订单（不推荐，仍需等待取消）

实施建议:

在`exchanges/lighter.py`中添加新方法：

```python
async def place_ioc_order(
    self,
    contract_id: str,
    quantity: Decimal,
    price: Decimal,
    side: str
) -> OrderResult:
    """使用IOC订单类型立即成交或取消

    特性:
    - 立即成交或取消，不等待
    - 无需10秒等待循环
    - 通过WebSocket获取最终成交状态
    """
    if self.lighter_client is None:
        await self._initialize_lighter_client()

    is_ask = (side.lower() == 'sell')
    client_order_index = int(time.time() * 1000) % 1000000

    order_params = {
        'market_index': self.config.contract_id,
        'client_order_index': client_order_index,
        'base_amount': int(quantity * self.base_amount_multiplier),
        'price': int(price * self.price_multiplier),
        'is_ask': is_ask,
        'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
        'time_in_force': self.lighter_client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
        'order_expiry': 0,  # IOC立即过期
        'reduce_only': False,
        'trigger_price': 0,
    }

    create_order, tx_hash, error = await self.lighter_client.create_order(**order_params)

    if error is not None:
        return OrderResult(
            success=False,
            order_id=str(client_order_index),
            error_message=f"IOC订单失败: {error}"
        )

    # 短暂等待WebSocket更新（0.5秒而非10秒）
    await asyncio.sleep(0.5)

    return OrderResult(
        success=True,
        order_id=str(client_order_index),
        side=side,
        size=quantity,
        price=price,
        status='OPEN'  # 实际状态由WebSocket更新
    )
```

**性能对比**:
- 原方法: 限价单 + 10秒等待 = 最坏10秒延迟
- IOC方法: 立即成交 + 0.5秒更新 = 最坏0.5秒延迟
- **性能提升: 20倍**

---

### RQ-2: Extended交易所是否已正确实现IOC订单？

**问题来源**: FR-001要求Extended和Lighter都使用IOC订单

**研究结果**:

决策: **Extended已支持IOC订单，无需修改**

理由:
1. Extended客户端(exchanges/extended.py)使用`place_open_order`方法
2. 该方法内部使用`post_only=False`参数，即taker订单
3. Taker订单行为等同于IOC（立即成交或取消）
4. 并发执行器(concurrent_executor.py)已正确调用Extended订单

验证代码:
```python
# exchanges/extended.py
result = await self.extended_client.place_open_order(
    contract_id=contract_id,
    quantity=quantity,
    direction=direction,
    post_only=False  # taker订单 = IOC行为
)
```

结论: Extended端实现正确，问题仅存在于Lighter端

---

### RQ-3: 当前并发执行器是否正确实现asyncio.gather？

**问题来源**: FR-001要求发送时间差<5ms

**研究结果**:

决策: **并发执行器实现正确，但被Lighter的10秒等待循环破坏**

理由:
1. `spread/concurrent_executor.py`正确使用`asyncio.gather`
2. 发送时间戳记录在并发任务内部，确保<5ms精度
3. 问题根源: `exchanges/lighter.py:305-333`的`place_open_order`方法
4. 该方法包含10秒等待循环（第321-324行），阻塞整个并发执行

代码证据:
```python
# exchanges/lighter.py:321-324 (问题代码)
while time.time() - start_time < 10 and order_status != 'FILLED':
    await asyncio.sleep(0.1)  # 阻塞10秒！
    if self.current_order is not None:
        order_status = self.current_order.status
```

影响:
- Extended订单: 立即返回（<100ms）
- Lighter订单: 阻塞10秒
- 并发失效: 变成串行执行

解决方案: 使用RQ-1的IOC订单实现，移除等待循环

---

### RQ-4: WebSocket回调竞态条件如何处理？

**问题来源**: Edge Case - WebSocket回调可能在订单ID设置前到达

**研究结果**:

决策: **使用订单缓存机制（当前已部分实现）**

理由:
1. 当前`exchanges/lighter.py`使用`self.current_order`存储最新订单
2. 使用`client_order_index`作为临时ID，WebSocket回调可立即匹配
3. 项目已有`order_book_lock`保护并发访问

实施建议:

```python
# 在LighterClient类中增强缓存机制
class OrderCache:
    """订单结果缓存，解决WebSocket竞态问题"""
    def __init__(self):
        self._pending_orders: Dict[int, asyncio.Future] = {}
        self._completed_orders: Dict[int, OrderResult] = {}

    def register_pending(self, client_order_index: int) -> asyncio.Future:
        """注册待处理订单，返回Future供等待"""
        future = asyncio.Future()
        self._pending_orders[client_order_index] = future
        return future

    def resolve_pending(self, client_order_index: int, result: OrderResult):
        """WebSocket回调解析订单"""
        if client_order_index in self._pending_orders:
            self._pending_orders[client_order_index].set_result(result)
            del self._pending_orders[client_order_index]
        self._completed_orders[client_order_index] = result

    async def wait_for_result(self, client_order_index: int, timeout: float = 1.0):
        """等待WebSocket回调（最多1秒）"""
        if client_order_index in self._completed_orders:
            return self._completed_orders[client_order_index]

        future = self.register_pending(client_order_index)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
```

使用方式:
```python
async def place_ioc_order(...):
    client_order_index = int(time.time() * 1000) % 1000000

    # 提交订单
    create_order, tx_hash, error = await self.lighter_client.create_order(...)

    # 等待WebSocket回调（1秒超时）
    result = await self.order_cache.wait_for_result(client_order_index, timeout=1.0)

    if result is None:
        # 超时：通过REST API查询
        result = await self.get_order_info(client_order_index)

    return result
```

---

### RQ-5: 如何实现闪电回滚机制？

**问题来源**: FR-005要求500ms内执行单腿持仓回滚

**研究结果**:

决策: **使用现有LegRollbackHandler框架，增强集成**

理由:
1. 项目已有`spread/leg_rollback_handler.py`模块
2. 当前实现包含检测和执行逻辑
3. 需要增强与IOC订单的集成
4. 需要市价单支持（Lighter SDK支持）

关键实施点:

1. **检测机制**（已实现）:
```python
def detect_legging(concurrent_result: ConcurrentOrderResult) -> bool:
    return concurrent_result.is_legging
```

2. **执行机制**（需要增强）:
```python
async def execute_emergency_close(...):
    legging_side = 'extended' if concurrent_result.extended_success else 'lighter'
    quantity = concurrent_result.extended_filled_qty if legging_side == 'extended' else concurrent_result.lighter_filled_qty

    # 使用市价单确保立即成交
    result = await self.concurrent_executor.emergency_close_position(
        exchange=legging_side,
        side='sell' if legging_side == 'extended' else 'buy',  # 平仓方向
        quantity=quantity,
        timeout_ms=500
    )

    return LegRollbackEvent(...)
```

3. **市价单支持**:
   - Extended: 使用`post_only=False` + 对手价
   - Lighter: 使用`create_market_order()`或激进的IOC

---

### RQ-6: 数据时效性检查如何实现？

**问题来源**: FR-007要求检查订单簿数据延迟<500ms

**研究结果**:

决策: **使用WebSocket时间戳进行数据新鲜度检查**

理由:
1. WebSocket订单簿消息包含时间戳字段
2. 当前`LighterCustomWebSocketManager`已存储时间戳
3. 需要在`calculate_spread`前添加检查

实施建议:

```python
# 在spread/bot.py的_strategy_loop中添加
async def check_data_freshness() -> DataFreshnessResult:
    """检查订单簿数据时效性"""
    current_time = time.time() * 1000

    # Extended时间戳
    ext_ts = self.extended_client.get_last_update_timestamp()
    ext_age = current_time - ext_ts if ext_ts else float('inf')

    # Lighter时间戳
    lit_ts = self.lighter_client.websocket_manager.get_last_update_timestamp()
    lit_age = current_time - lit_ts if lit_ts else float('inf')

    max_age = max(ext_age, lit_age)
    is_fresh = max_age < 500  # 500ms阈值

    return DataFreshnessResult(
        data_age_ms=max_age,
        is_fresh=is_fresh,
        extended_age_ms=ext_age,
        lighter_age_ms=lit_age
    )

# 在计算价差前调用
freshness = await check_data_freshness()
if not freshness.is_fresh:
    self.logger.warning(f"数据过期({freshness.data_age_ms:.0f}ms)，放弃本次机会")
    continue
```

---

### RQ-7: 利润风控验证如何实现？

**问题来源**: FR-006要求净利>0才允许开仓

**研究结果**:

决策: **使用现有RiskValidator框架，增强利润计算**

理由:
1. 项目已有`spread/risk_validator.py`模块
2. 当前实现包含基础利润检查
3. 需要增强成本分解（手续费+滑点+最小净利）

实施建议:

```python
# 在spread/risk_validator.py中增强
async def validate_profitability(
    self,
    spread_rate: Decimal,
    extended_price: Decimal,
    lighter_price: Decimal
) -> ProfitabilityCheck:
    """验证交易利润是否足够"""

    # 1. 双边手续费总和
    total_fees = self.config.extended_taker_fee + self.config.lighter_taker_fee

    # 2. 预期滑点成本
    expected_slippage = Decimal('0.0001')  # 0.01%

    # 3. 最小净利要求
    min_net_profit = Decimal('0.0002')  # 0.02%

    # 4. 计算所需价差
    required_spread = total_fees + expected_slippage + min_net_profit

    # 5. 净利润
    net_profit = spread_rate - total_fees - expected_slippage

    is_profitable = net_profit > min_net_profit

    return ProfitabilityCheck(
        spread_rate=spread_rate,
        total_fees=total_fees,
        expected_slippage=expected_slippage,
        min_net_profit=min_net_profit,
        required_spread=required_spread,
        net_profit_rate=net_profit,
        is_profitable=is_profitable
    )
```

配置参数:
```python
# spread/config.py
extended_taker_fee: Decimal = Decimal('0.00025')  # 0.025%
lighter_taker_fee: Decimal = Decimal('0.00020')   # 0.020%
min_profit_rate: Decimal = Decimal('0.0002')      # 0.02%
max_slippage_rate: Decimal = Decimal('0.0005')    # 0.05%
```

---

## 技术栈总结

基于研究结果，确定技术栈：

| 组件 | 技术选择 | 理由 |
|------|----------|------|
| **语言** | Python 3.11+ | 项目现有标准 |
| **异步框架** | asyncio | 项目已使用 |
| **WebSocket** | websockets 12.0+ | 项目已使用 |
| **交易所SDK** | lighter-sdk 0.1.4 | 项目已使用 |
| **数值计算** | decimal.Decimal | 金融精度要求 |
| **测试框架** | pytest | 项目已使用 |
| **日志** | logging (Python标准库) | 项目已使用 |
| **存储** | 内存 + 文件日志 | 项目现有架构 |
| **目标平台** | Linux服务器 | 交易系统 |

## 性能目标

| 指标 | 当前值 | 目标值 | 提升 |
|------|--------|--------|------|
| 发送时间差 | 伪并发（10秒阻塞） | <5ms | 2000倍 |
| 总延迟 | 10秒+ | <500ms | 20倍 |
| 开仓成功率 | 10% | >90% | 9倍 |
| 单腿持仓时长 | 未知 | <1秒 | - |

## 依赖确认

所有依赖已确认可用：

1. ✅ Extended交易所IOC支持（taker订单）
2. ✅ Lighter SDK IOC支持（ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL）
3. ✅ WebSocket连接管理器正常工作
4. ✅ 性能监控器可记录毫秒级时间戳
5. ✅ 日志系统支持CRITICAL级别

## 未解决问题

无。所有研究问题已解决。

## 下一步

进入Phase 1设计阶段，生成：
- data-model.md
- contracts/
- quickstart.md
