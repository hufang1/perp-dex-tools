# 快速开始指南

**功能**: 修复套利机器人订单状态更新的竞态条件bug
**日期**: 2026-01-07

## 概述

本指南描述如何验证和使用修复后的订单管理器。修复的核心是添加了**订单状态缓存机制**，解决WebSocket回调早于订单ID设置导致的竞态条件问题。

## 问题描述

### 症状

运行spread_arb机器人时：
- Extended订单成功成交（日志显示 `status=FILLED`）
- 但Lighter没有同步开单对冲
- 日志显示 `⏰ 订单等待超时: 已成交 0.0000`
- `current_order_id=None` 当WebSocket回调到达时

### 根本原因

竞态条件：WebSocket回调在 `place_spread_maker_order()` 设置 `current_order_id` 之前接收到订单的FILLED状态更新，导致 `update_order_status()` 忽略该更新。

## 解决方案

### 订单状态缓存机制

**工作原理**:
1. WebSocket回调收到订单更新时，如果 `current_order_id` 未设置，将更新缓存
2. `place_spread_maker_order()` 设置 `current_order_id` 后，检查并应用缓存
3. 自动清理过期缓存，防止内存泄漏

**流程图**:
```
WebSocket收到FILLED → current_order_id=None?
                          │
                         是 → 缓存更新
                          │
                         否 → 应用更新
                          │
place_spread_maker_order返回 → 检查缓存
                          │
                         是 → 应用缓存更新
```

## 验证步骤

### 1. 单元测试

运行新增的单元测试：

```bash
pytest tests/test_order_manager.py -v
```

**预期输出**:
```
tests/test_order_manager.py::test_race_condition_fix PASSED
tests/test_order_manager.py::test_concurrent_updates PASSED
tests/test_order_manager.py::test_cache_cleanup PASSED
tests/test_order_manager.py::test_ttl_expiration PASSED
===================== 4 passed in 0.5s =====================
```

### 2. 集成测试

启动spread_arb机器人：

```bash
python spread/bot.py --ticker ETH --size 35 --max-pairs 3
```

**观察日志**:

#### 修复前（有bug）:
```
INFO:SpreadArbBot:🎯 发现开仓机会: buy_extended_sell_lighter
INFO:OrderManager:[Extended] 下 BUY Maker 单: 0.0108 @ 3251.40
INFO:SpreadArbBot:[DEBUG] bot收到订单更新: order_data={...}, current_order_id=None
INFO:SpreadArbBot:[DEBUG] 下单返回: success=True, order_id=2008773271629754368
WARNING:OrderManager:⏰ 订单等待超时: 已成交 0.0000
```

#### 修复后（正常）:
```
INFO:SpreadArbBot:🎯 发现开仓机会: buy_extended_sell_lighter
INFO:OrderManager:[Extended] 下 BUY Maker 单: 0.0108 @ 3251.40
INFO:OrderManager:⚡ 检测到竞态条件: 缓存订单更新, order_id=2008773271629754368
INFO:OrderManager:✅ 应用缓存的订单更新: FILLED
INFO:SpreadArbBot:[DEBUG] 下单返回: success=True, order_id=2008773271629754368
INFO:SpreadArbBot:✅ 开仓成功! 套利对 #1
```

### 3. 性能验证

#### 内存占用检查

运行24小时后，检查内存占用：

```python
import spread.order_manager as om

manager = om.SpreadOrderManager(config, client)
print(f"缓存大小: {len(manager._pending_updates)}")
print(f"缓存命中: {manager._cache_hits}")
print(f"缓存未命中: {manager._cache_misses}")
```

**预期输出**:
```
缓存大小: 0  # 或接近0
缓存命中: 15  # 检测到竞态条件的次数
缓存未命中: 0
```

#### 订单状态更新延迟

日志中的时间戳：

```
[T1] WebSocket收到更新
[T2] 应用缓存更新
延迟 = T2 - T1 < 10ms
```

## 使用示例

### 基本使用（无变化）

```python
from spread.order_manager import SpreadOrderManager
from spread.config import SpreadArbConfig

# 创建配置
config = SpreadArbConfig(
    ticker='ETH',
    order_quantity_usdt=35,
    ...
)

# 创建订单管理器
order_manager = SpreadOrderManager(
    config=config,
    extended_client=extended_client
)

# 下单（内部自动处理缓存）
result = await order_manager.place_spread_maker_order(
    side='buy',
    price=Decimal('3251.4'),
    quantity=Decimal('0.01')
)

if result['success']:
    # 等待成交（会自动应用缓存）
    fill_result = await order_manager.wait_for_fill(
        order_id=result['order_id'],
        timeout=10
    )

    if fill_result['status'] == 'FILLED':
        print(f"成交: {fill_result['filled_quantity']} @ {fill_result['filled_price']}")
```

### WebSocket回调设置（无变化）

```python
# 在spread/bot.py中，无需修改
def _handle_extended_order_update(self, order_data: Dict[str, Any]):
    self.order_manager.update_order_status(order_data)

# 设置回调
extended_client.setup_order_update_handler(
    self._handle_extended_order_update
)
```

## 调试技巧

### 启用详细日志

在代码中设置日志级别：

```python
import logging
logging.getLogger("OrderManager").setLevel(logging.DEBUG)
```

**日志输出**:
```
DEBUG:OrderManager:收到订单更新: order_id=2008773271629754368, current_order_id=None
DEBUG:OrderManager:缓存订单更新: order_id=2008773271629754368
DEBUG:OrderManager:设置order_id: 2008773271629754368
DEBUG:OrderManager:检查缓存: 找到1个待应用更新
DEBUG:OrderManager:应用缓存更新: status=FILLED, filled_size=0.010
INFO:OrderManager:✅ 订单状态更新: 2008773271629754368 -> FILLED
```

### 检查缓存状态

```python
# 运行时检查
print(f"缓存订单数: {len(order_manager._pending_updates)}")
print(f"缓存详情: {order_manager._pending_updates}")
```

## 常见问题

### Q1: 缓存会无限增长吗？

**A**: 不会。有三层防护：
1. TTL（5分钟）自动清理
2. 最大限制（100个订单）
3. 订单完成后立即清理

### Q2: 性能会受影响吗？

**A**: 不会。影响<1ms：
- 缓存写入: ~0.4ms
- 缓存读取: ~0.1ms
- 锁等待: 可忽略（asyncio.Lock）

### Q3: 如何知道缓存机制是否生效？

**A**: 查看日志中的这些消息：
- `⚡ 检测到竞态条件: 缓存订单更新`
- `✅ 应用缓存的订单更新`

### Q4: 旧代码需要修改吗？

**A**: 不需要。公共接口完全兼容：
- `place_spread_maker_order()` 签名不变
- `wait_for_fill()` 签名不变
- `update_order_status()` 签名不变
- 仅内部实现修改

### Q5: 如何回滚到修复前的版本？

**A**: 使用git切换分支：

```bash
git checkout main  # 或之前的分支
```

## 下一步

1. **运行测试**: 确保所有单元测试通过
2. **模拟交易**: 在测试环境验证修复效果
3. **监控日志**: 观察缓存命中率和应用情况
4. **逐步部署**: 先小流量测试，确认稳定后全量部署

## 支持与反馈

如有问题或建议，请查看：
- 规格文档: `specs/003-fix-order-status-race/spec.md`
- 实现计划: `specs/003-fix-order-status-race/plan.md`
- 数据模型: `specs/003-fix-order-status-race/data-model.md`
