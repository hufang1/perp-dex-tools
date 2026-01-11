# 研究文档：异步重构技术决策

**功能**: 011-async-ws-ioc-trading
**日期**: 2026-01-11

本文档记录实施计划中的技术问题研究结果，包括决策、理由和替代方案评估。

---

## T001: Python asyncio最佳实践

### 问题
在高频交易场景中，如何正确使用asyncio实现并发下单？

### 研究发现

#### 1. 并发下单模式
**决策**: 使用`asyncio.gather`实现真正的并发

```python
async def execute_concurrent_orders(extended_order, lighter_order):
    """并发执行两个交易所的下单"""
    results = await asyncio.gather(
        place_order_extended(extended_order),
        place_order_lighter(lighter_order),
        return_exceptions=True
    )
    return results
```

**理由**:
- `asyncio.gather`在事件循环中调度多个协程，实现I/O并发
- 两个HTTP请求几乎同时发出（时间差通常 < 5ms）
- `return_exceptions=True`确保一个失败不影响另一个

**替代方案评估**:
| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| `asyncio.gather` | 真正并发，时间差最小 | 需要异步API | ✅ 选择 |
| 顺序await | 简单 | 串行执行，延迟累加 | ❌ |
| 线程池 | 可用于同步代码 | 线程开销大，GIL限制 | ❌ |

#### 2. 超时和取消处理
**决策**: 使用`asyncio.wait_for`包装每个订单

```python
async def place_order_with_timeout(order, timeout_ms=500):
    """带超时的订单发送"""
    try:
        result = await asyncio.wait_for(
            place_order(order),
            timeout=timeout_ms / 1000
        )
        return {'success': True, 'data': result}
    except asyncio.TimeoutError:
        return {'success': False, 'error': 'timeout'}
```

**理由**:
- 防止单个交易所响应慢阻塞整个流程
- 超时后可快速进入决策逻辑（是否平仓另一边）

#### 3. 与现有同步代码集成
**决策**: 在主循环中使用`asyncio.run`启动事件循环

```python
def main():
    """主入口：启动异步事件循环"""
    asyncio.run(bot.run_async())

async def run_async(self):
    """异步主循环"""
    # 初始化WebSocket连接
    await self.ws_manager.connect_all()

    # 策略循环
    while self.running:
        # 获取订单簿数据（从WebSocket缓存）
        extended_ob = self.ws_manager.get_orderbook('extended')
        lighter_ob = self.ws_manager.get_orderbook('lighter')

        # 计算价差
        opportunity = self.calculate_opportunity(extended_ob, lighter_ob)

        if opportunity and self.validate_opening(opportunity):
            # 并发下单
            await self.execute_opening(opportunity)

        await asyncio.sleep(0.1)  # 100ms检查间隔
```

**理由**:
- 最小化对现有代码的改动
- bot.py的__init__保持同步
- 只将交易执行部分改为异步

---

## T002: WebSocket连接管理

### 问题
如何实现稳定的WebSocket连接，处理断线重连和数据同步？

### 研究发现

#### 1. WebSocket库选择
**决策**: 使用`websockets`库（而非`websocket-client`）

**理由**:
- 原生asyncio支持
- 自动处理ping/pong心跳
- 成熟稳定，广泛使用

**替代方案评估**:
| 库 | 优点 | 缺点 | 决策 |
|----|------|------|------|
| websockets | 原生async，API简洁 | 需要Python 3.7+ | ✅ 选择 |
| websocket-client | 同步API，兼容性好 | 不适合asyncio | ❌ |
| aiohttp | 内置WebSocket | WebSocket支持较弱 | ❌ |

#### 2. 心跳保活机制
**决策**: 使用WebSocket内置ping/pong + 应用层心跳

```python
async def maintain_connection(self, exchange):
    """保持WebSocket连接活跃"""
    while self.running:
        try:
            # 发送应用层心跳（每30秒）
            await self.ws.send(json.dumps({'type': 'ping', 'ts': time.time()}))
            await asyncio.sleep(30)
        except Exception as e:
            self.logger.error(f"心跳失败: {e}")
            break
```

**理由**:
- WebSocket ping/pong检测连接状态
- 应用层心跳检测应用层逻辑健康
- 双重保险确保连接可靠性

#### 3. 断线检测和自动重连
**决策**: 指数退避重连策略

```python
async def auto_reconnect(self, exchange):
    """自动重连逻辑"""
    retry_delay = 1  # 初始1秒
    max_delay = 60   # 最大60秒

    while self.running:
        try:
            await self.connect(exchange)
            retry_delay = 1  # 成功后重置延迟
        except Exception as e:
            self.logger.warning(f"连接失败，{retry_delay}秒后重试: {e}")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)
```

**理由**:
- 指数退避避免频繁重连
- 最大延迟限制防止间隔过长
- 断线期间暂停交易（数据过期）

#### 4. 订单簿数据同步
**决策**: 本地缓存 + 更新回调

```python
class WebSocketManager:
    def __init__(self):
        self.orderbooks = {
            'extended': {'bid': None, 'ask': None, 'timestamp': None},
            'lighter': {'bid': None, 'ask': None, 'timestamp': None}
        }

    async def handle_message(self, exchange, message):
        """处理WebSocket消息"""
        data = json.loads(message)

        if data['type'] == 'bookTicker':
            # 更新本地缓存
            self.orderbooks[exchange]['bid'] = Decimal(data['bid'])
            self.orderbooks[exchange]['ask'] = Decimal(data['ask'])
            self.orderbooks[exchange]['timestamp'] = data['timestamp'] or time.time() * 1000

            # 触发回调（如果设置）
            if self.orderbook_callback:
                self.orderbook_callback(exchange, self.orderbooks[exchange])
```

**理由**:
- 本地缓存避免等待网络
- 时间戳记录用于数据新鲜度检查
- 回调机制解耦数据处理

---

## T003: IOC订单实现

### 问题
Extended和Lighter交易所如何支持IOC订单类型？

### 研究发现

#### 1. IOC订单参数
**决策**: IOC订单通过`timeInForce`参数指定

```python
def create_ioc_order(exchange, side, price, quantity):
    """创建IOC订单"""
    order = {
        'symbol': 'ETH-USD',
        'side': side,           # 'buy' or 'sell'
        'type': 'LIMIT',
        'price': str(price),
        'quantity': str(quantity),
        'timeInForce': 'IOC',   # Immediate or Cancel
        'postOnly': False       # IOC必须为False
    }

    if exchange == 'lighter':
        # Lighter可能使用不同字段名
        order['time_in_force'] = 'IOC'
        order['post_only'] = False

    return order
```

**理由**:
- IOC是标准订单类型，主流交易所都支持
- `timeInForce='IOC'`表示立即成交否则撤销
- `postOnly=False`允许充当taker

#### 2. 激进限价定价
**决策**: 价格 = 对手价 * (1 ± 滑点容忍度)

```python
def calculate_ioc_price(base_price, side, slippage_tolerance):
    """计算IOC订单价格（激进限价）"""
    if side == 'buy':
        # 买入：价格高于ask确保成交
        return base_price * (Decimal('1') + slippage_tolerance)
    else:
        # 卖出：价格低于bid确保成交
        return base_price * (Decimal('1') - slippage_tolerance)

# 使用示例
buy_price = calculate_ioc_price(
    base_price=ask_price,           # $3000
    side='buy',
    slippage_tolerance=Decimal('0.0005')  # 0.05%
)
# 结果：$3001.5（如果市场价在$3001.5以下，立即成交）
```

**理由**:
- 略微让步价格确保成交概率
- 滑点容忍度控制最大损失
- 价格跳涨时自动撤单（IOC特性）

#### 3. 部分成交处理
**决策**: 接受部分成交，记录实际数量

```python
def handle_ioc_result(order_result):
    """处理IOC订单结果"""
    if order_result['status'] == 'filled':
        # 完全成交
        return {
            'success': True,
            'filled_qty': Decimal(order_result['executed_qty']),
            'avg_price': Decimal(order_result['avg_price'])
        }
    elif order_result['status'] == 'partially_filled':
        # 部分成交（IOC未成交部分自动撤销）
        return {
            'success': True,
            'filled_qty': Decimal(order_result['executed_qty']),
            'avg_price': Decimal(order_result['avg_price']),
            'is_partial': True
        }
    else:
        # 完全未成交
        return {
            'success': False,
            'reason': 'no_fill'
        }
```

**理由**:
- IOC部分成交是正常情况
- 记录实际成交数量用于仓位对账
- 未成交部分不需要手动撤销

---

## T004: 精确时间戳记录

### 问题
如何确保毫秒级时间戳记录不影响性能？

### 研究发现

#### 1. 时间函数选择
**决策**: 使用`time.time()`而非`time.perf_counter()`

| 函数 | 精度 | 用途 | 选择 |
|------|------|------|------|
| `time.time()` | 系统时间 | 绝对时间戳 | ✅ 选择 |
| `time.perf_counter()` | 单调递增 | 性能测量 | ❌ |
| `time.monotonic()` | 单调递增 | 超时计算 | ❌ |

**理由**:
- 需要绝对时间戳用于日志分析
- `time.time()`在Python 3.7+精度足够（微秒级）
- 与交易所时间戳可比对

#### 2. 时间戳记录开销
**决策**: 测量显示开销可忽略

```python
# 测试：记录10000次时间戳
import time

start = time.perf_counter()
for _ in range(10000):
    ts = time.time() * 1000  # 毫秒
end = time.perf_counter()

print(f"10000次调用耗时: {(end - start) * 1000:.2f}ms")
# 结果：约2-3ms
# 平均每次：0.0002-0.0003ms
```

**结论**: 单次调用开销约0.0003ms，对10ms目标影响可忽略。

#### 3. 异步环境下的准确性
**决策**: 时间戳记录在协程切换点

```python
async def execute_with_timing():
    """带时间戳的执行"""
    # 信号触发时间（计算完成）
    signal_ts = time.time() * 1000

    # 并发发送（记录每个发送时间）
    send_a_ts = None
    send_b_ts = None

    async def send_extended():
        nonlocal send_a_ts
        send_a_ts = time.time() * 1000
        return await place_order_extended(...)

    async def send_lighter():
        nonlocal send_b_ts
        send_b_ts = time.time() * 1000
        return await place_order_lighter(...)

    results = await asyncio.gather(send_extended(), send_lighter())

    return {
        'signal_ts': signal_ts,
        'send_a_ts': send_a_ts,
        'send_b_ts': send_b_ts,
        'send_gap': abs(send_b_ts - send_a_ts)
    }
```

**理由**:
- 在实际发送前记录时间戳（最接近真实发送时间）
- 非阻塞操作不影响协程调度
- 时间戳差值反映真实并发度

---

## T005: 测试策略

### 问题
如何测试异步交易流程？

### 研究发现

#### 1. pytest-asyncio使用
**决策**: 使用`@pytest.mark.asyncio`装饰器

```python
import pytest

@pytest.mark.asyncio
async def test_concurrent_orders():
    """测试并发下单"""
    executor = ConcurrentExecutor()

    # Mock交易所API
    async def mock_place_extended(order):
        await asyncio.sleep(0.01)  # 10ms模拟延迟
        return {'success': True, 'order_id': 'ext_123'}

    async def mock_place_lighter(order):
        await asyncio.sleep(0.012)  # 12ms模拟延迟
        return {'success': True, 'order_id': 'lit_456'}

    # Patch方法
    with patch.object(executor, '_place_extended', mock_place_extended):
        with patch.object(executor, '_place_lighter', mock_place_lighter):
            # 执行并发下单
            result_a, result_b, gap = await executor.execute_concurrent_orders(
                {'side': 'buy', 'qty': 0.01},
                {'side': 'sell', 'qty': 0.01}
            )

            # 验证
            assert result_a['success']
            assert result_b['success']
            assert gap < 5  # 并发间隔 < 5ms
```

**理由**:
- pytest-asyncio原生支持异步测试
- Mock避免真实API调用
- 可测试超时、异常等情况

#### 2. WebSocket Mock
**决策**: 使用`aiohttp`测试服务器模拟WebSocket

```python
import pytest
from aiohttp import web

@pytest.mark.asyncio
async def test_websocket_reconnect():
    """测试WebSocket重连"""
    # 模拟WebSocket服务器
    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # 接收一条消息后断开
        await ws.send_str('{"type": "bookTicker", "bid": 3000}')
        await ws.close()

        return ws

    app = web.Application()
    app.router.add_get('/ws', ws_handler)

    # 启动测试服务器
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8765)
    await site.start()

    # 测试客户端
    manager = WebSocketManager('ws://localhost:8765/ws')
    await manager.connect()

    # 验证重连逻辑
    assert manager.is_connected()

    await runner.cleanup()
```

**理由**:
- 无需依赖真实WebSocket服务
- 可控制断线时机
- 测试重连逻辑正确性

#### 3. 集成测试策略
**决策**: 端到端流程测试 + 关键组件单元测试

```
tests/
├── test_performance_monitor.py      # 单元测试
├── test_websocket_manager.py        # 单元测试
├── test_concurrent_executor.py      # 单元测试
├── test_ioc_order_manager.py        # 单元测试
├── test_risk_validator.py           # 单元测试
└── integration/
    ├── test_async_trading_flow.py   # 集成测试
    └── test_timing_accuracy.py      # 性能测试
```

**集成测试示例**:
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_opening_flow():
    """测试完整开仓流程"""
    # 初始化所有组件
    ws_manager = WebSocketManager()
    perf_monitor = PerformanceMonitor(config)
    executor = ConcurrentExecutor()
    validator = RiskValidator(config)

    # 连接WebSocket（使用测试服务器）
    await ws_manager.connect_all()

    # 获取订单簿
    extended_ob = ws_manager.get_orderbook('extended')
    lighter_ob = ws_manager.get_orderbook('lighter')

    # 验证数据新鲜度
    is_valid, results = validator.validate_data_freshness(
        extended_ob['timestamp'],
        lighter_ob['timestamp']
    )
    assert is_valid

    # 验证利润率
    profit_result = validator.validate_profitability(Decimal('0.001'))
    assert profit_result.is_profitable

    # 执行并发下单
    result = await executor.execute_concurrent_orders(
        {'exchange': 'extended', ...},
        {'exchange': 'lighter', ...}
    )

    # 验证时间间隔
    assert result[2] < 5  # send_gap < 5ms
```

---

## 总结

### 技术决策汇总

| 问题 | 决策 | 关键技术 |
|------|------|----------|
| 并发下单 | asyncio.gather | 异步I/O并发 |
| WebSocket连接 | websockets库 | ping/pong心跳 |
| IOC订单 | timeInForce='IOC' | 激进限价定价 |
| 时间戳 | time.time() | 毫秒精度 |
| 测试 | pytest-asyncio | Mock集成测试 |

### 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 异步复杂度 | 分阶段迁移，保持同步兼容 |
| WebSocket稳定性 | 心跳 + 指数退避重连 |
| 交易所API变更 | 抽象层封装 |
| 性能不达标 | 性能测试 + Profiling |

### 下一步

1. ✅ 技术问题已澄清
2. ⏭️ 进入Phase 1：数据模型与API设计
3. ⏭️ 更新agent上下文
