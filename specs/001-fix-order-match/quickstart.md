# 快速开始: 订单更新缓存修复

**功能分支**: 001-fix-order-match
**创建日期**: 2026-01-09

---

## 问题回顾

Extended交易所WebSocket成交通知在订单ID设置前到达，导致对冲逻辑无法触发，造成单边持仓风险。

---

## 修复方案概览

本次修复通过在 `SpreadOrderManager` 中实现订单更新缓存机制来解决竞态条件问题。

### 核心机制

```
WebSocket消息到达
    ↓
检查 current_order_id
    ↓
    ├─ 为 None → 缓存更新
    └─ 不为 None → 直接应用
    ↓
设置 current_order_id 后
    ↓
应用缓存更新
    ↓
触发对冲逻辑
```

---

## 修改文件清单

| 文件 | 修改类型 | 描述 |
|------|----------|------|
| `spread/order_manager.py` | 修改 | 增强日志，修复缓存应用逻辑 |
| `spread/bot.py` | 修改 | 改进回调处理和熔断机制 |
| `tests/test_order_manager.py` | 新增 | 单元测试 |

---

## 关键修改点

### 1. 增强日志输出

**文件**: `spread/order_manager.py`

**修改内容**: 在关键路径添加详细日志，区分两种处理路径：

```python
async def _apply_pending_updates(self, order_id: str) -> None:
    self.logger.info(f"🔍 检查缓存: order_id={order_id}")
    if order_id not in self._pending_updates:
        self.logger.info(f"❌ 无缓存更新: order_id={order_id}")
        return

    updates = self._pending_updates.pop(order_id)
    self.logger.info(f"✅ 找到缓存: order_id={order_id}, 数量={len(updates)}")

    for update in updates:
        order_data = update['order_data']
        self.logger.info(
            f"✅ 应用缓存的订单更新: order_id={order_id}, "
            f"status={order_data.get('status')}, "
            f"filled_size={self.filled_quantity:.4f}, "
            f"price={self.filled_price:.2f}"
        )
        # ... 应用更新
```

**预期日志**:
```
🔍 检查缓存: order_id=2009619315649257472
✅ 找到缓存: order_id=2009619315649257472, 数量=1
✅ 应用缓存的订单更新: order_id=2009619315649257472, status=FILLED, filled_size=0.0100, price=3094.30
📊 缓存统计: 命中率=100.0%, 命中=1, 未命中=0
```

### 2. 在wait_for_fill中检查缓存

**文件**: `spread/order_manager.py`

**修改内容**: 在等待成交循环开始前检查缓存：

```python
async def wait_for_fill(self, order_id: str, timeout: int, allow_partial: bool = True):
    start_time = time.time()

    # 【新增】在循环开始前检查是否有缓存的更新
    await self._apply_pending_updates(order_id)

    while time.time() - start_time < timeout:
        # ... 现有逻辑
```

### 3. 修复bot的回调处理

**文件**: `spread/bot.py`

**修改内容**: 当订单成交时，无论 `current_order_id` 是否为None，都尝试触发对冲：

```python
def _handle_extended_order_update(self, order_data: Dict[str, Any]):
    order_id = order_data.get('order_id')
    status = order_data.get('status')

    # 更新订单管理器状态
    self.order_manager.update_order_status(order_data)

    # 【新增】如果订单成交，直接触发对冲
    if status == 'FILLED':
        self.logger.info(f"🎯 订单成交: {order_id}, 准备触发对冲逻辑")
        # 检查是否需要触发对冲
        if self.is_opening and self.order_manager.current_order_id == order_id:
            asyncio.create_task(self._hedge_on_fill(order_data))
```

### 4. 增强熔断机制

**文件**: `spread/bot.py`

**新增内容**: 熔断状态跟踪和处理：

```python
# 在 Bot 类中添加
self.circuit_breaker = {
    'is_tripped': False,
    'reason': None,
    'trip_time': None,
    'uncleared_positions': []
}

def _check_circuit_breaker(self) -> bool:
    """检查熔断状态"""
    if self.circuit_breaker['is_tripped']:
        self.logger.warning(
            f"⛔ 熔断已触发: {self.circuit_breaker['reason']}"
        )
        return False
    return True

def _trip_circuit_breaker(self, reason: str, position: Dict[str, Any]):
    """触发熔断"""
    self.circuit_breaker['is_tripped'] = True
    self.circuit_breaker['reason'] = reason
    self.circuit_breaker['trip_time'] = datetime.now()
    self.circuit_breaker['uncleared_positions'].append(position)

    # 记录到交易日志
    self.trade_logger.log_uncleared_position(position)

    self.logger.error(
        f"🚨 熔断触发: {reason}\n"
        f"未对冲仓位: {position}\n"
        f"已记录到 logs/trade.log"
    )
```

---

## 测试

### 单元测试

**文件**: `tests/test_order_manager.py`

**测试用例**:

```python
import pytest
from decimal import Decimal
from spread.order_manager import SpreadOrderManager

@pytest.mark.asyncio
async def test_race_condition_cache():
    """测试竞态条件：WebSocket消息在订单ID设置前到达"""
    # 准备测试数据
    order_data = {
        'order_id': 'test_order_123',
        'status': 'FILLED',
        'side': 'buy',
        'size': '0.01',
        'price': '3094.3',
        'contract_id': 'ETH-USD',
        'filled_size': '0.01',
        'order_type': 'OPEN'
    }

    # 在 current_order_id = None 时调用
    manager = SpreadOrderManager(config, extended_client)
    manager.update_order_status(order_data)

    # 验证：更新被缓存
    assert 'test_order_123' in manager._pending_updates
    assert manager.current_order_status is None

    # 设置订单ID并应用缓存
    manager.current_order_id = 'test_order_123'
    await manager._apply_pending_updates('test_order_123')

    # 验证：状态已更新
    assert manager.current_order_status == 'FILLED'
    assert manager.filled_quantity == Decimal('0.01')
    assert manager.filled_price == Decimal('3094.3')
    assert 'test_order_123' not in manager._pending_updates

@pytest.mark.asyncio
async def test_cache_ttl():
    """测试缓存TTL清理"""
    manager = SpreadOrderManager(config, extended_client)

    # 添加一个6秒前的缓存
    old_time = time.time() - 360
    manager._pending_updates['old_order'] = [{
        'order_data': {...},
        'timestamp': old_time
    }]

    # 清理过期缓存
    await manager._cleanup_cache()

    # 验证：旧缓存被删除
    assert 'old_order' not in manager._pending_updates
```

### 集成测试

**文件**: `tests/integration/test_race_condition_fix.py`

**测试场景**:
1. 模拟Extended下单
2. 在SDK返回前模拟WebSocket成交消息
3. 验证对冲订单是否正确触发
4. 验证日志输出是否正确

---

## 部署步骤

1. **备份当前代码**
   ```bash
   git diff 001-fix-lighter-ws > backup.patch
   ```

2. **应用修改**
   ```bash
   # 切换到功能分支
   git checkout 001-fix-order-match

   # 验证修改
   git diff
   ```

3. **运行测试**
   ```bash
   # 单元测试
   pytest tests/test_order_manager.py -v

   # 集成测试
   pytest tests/integration/test_race_condition_fix.py -v
   ```

4. **部署到测试环境**
   ```bash
   # 在测试服务器上
   python spread/bot.py --ticker ETH --size 35 --max-pairs 1
   ```

5. **监控日志**
   ```bash
   # 实时查看日志
   tail -f logs/trade.log

   # 检查竞态条件是否发生
   grep "竞态条件" logs/*.log
   ```

6. **验证修复**
   - 检查是否还有 "Order not found" 日志
   - 验证缓存命中率是否 > 0
   - 确认未对冲仓位为 0

---

## 验收标准

### 功能验收

- [ ] WebSocket消息在订单ID设置前到达时，对冲订单成功触发
- [ ] 日志能够区分"通过缓存处理"和"直接处理"两种路径
- [ ] 缓存命中率 > 50%（表明竞态条件确实存在）
- [ ] 未对冲仓位检测和熔断机制正常工作

### 性能验收

- [ ] 缓存应用延迟 < 50ms
- [ ] 熔断触发延迟 < 100ms
- [ ] 日志写入不影响交易执行

### 稳定性验收

- [ ] 连续运行24小时无单边持仓
- [ ] 熔断机制能够正确触发和恢复
- [ ] 日志记录完整，便于问题诊断

---

## 回滚计划

如果修复后出现问题，可以按以下步骤回滚：

1. **停止机器人**
   ```bash
   # 发送SIGTERM信号
   kill -TERM $(pidof python)
   ```

2. **回滚代码**
   ```bash
   git checkout 002-fix-lighter-ws
   ```

3. **重启机器人**
   ```bash
   python spread/bot.py --ticker ETH --size 35 --max-pairs 3
   ```

4. **验证**
   - 检查进程是否正常运行
   - 查看日志是否有错误
   - 确认持仓正常

---

## 常见问题

### Q1: 缓存命中率很高（>80%）是否正常？

**A**: 是的，这表明竞态条件确实存在，缓存机制正在发挥作用。如果命中率为0%，说明WebSocket消息总是在订单ID设置后到达，这种情况下缓存机制不会被触发。

### Q2: 熔断触发后如何恢复？

**A**: 有两种恢复方式：
1. **自动恢复**: 未对冲仓位被清理后自动恢复
2. **人工恢复**: 手动调用 `_reset_circuit_breaker(manual_override=True)`

### Q3: 如何验证修复是否有效？

**A**: 检查以下几点：
1. 日志中不再出现 "Order not found attempt 1-50"
2. 出现 "✅ 找到缓存: order_id=..." 日志
3. 未对冲仓位始终为 0
4. 缓存命中率 > 0

---

## 联系方式

如有问题，请联系开发团队或提交Issue。
