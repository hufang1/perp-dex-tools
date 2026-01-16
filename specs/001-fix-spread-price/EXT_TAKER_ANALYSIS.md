# Ext Taker模式分析总结

**分析日期**: 2026-01-16
**分析文件**: `spread/trade_executor.py`, `exchanges/extended.py`

---

## 一、当前Ext实现分析

### 1. 是否使用Taker模式？

**答案**: ✅ 是的，使用IOC限价单模拟Taker

```python
# trade_executor.py:580-595
if price is None:
    best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
    if side == "buy":
        price = best_ask  # ❌ 直接用ask价格
    else:
        price = best_bid  # ❌ 直接用bid价格

result = await self.extended_client.place_taker_order(
    contract_id=contract_id,
    quantity=quantity,
    side=side,
    price=price
)
```

### 2. Extended SDK的place_taker_order实现

```python
# exchanges/extended.py:301-397
async def place_taker_order(...):
    # 使用IOC模式 + post_only=False
    order_result = await self.perpetual_trading_client.place_order(
        market_name=contract_id,
        amount_of_synthetic=quantity,
        price=price,  # ⚠️ 价格参数必填
        side=order_side,
        time_in_force=TimeInForce.IOC,  # 立即成交或取消
        post_only=False,  # 允许taker执行
    )

    # 下单后等待0.05秒
    await asyncio.sleep(0.05)

    # 查询订单状态
    order_info = await self.get_order_info(order_id)

    if order_info.status in ['CANCELED', 'REJECTED']:
        # ❌ IOC订单被取消 = 没成交 = 重试
        self.logger.log(f"Taker order not filled, retrying...")
        retry_count += 1
        continue  # 最多重试10次！
```

---

## 二、与Lighter对比

| 项目 | Extended | Lighter |
|------|----------|---------|
| **滑点保护** | ❌ 0% | ✅ 0.2% |
| **买入价格** | `best_ask` | `best_ask * 1.002` |
| **卖出价格** | `best_bid` | `best_bid * 0.998` |
| **内部重试** | ✅ 最多10次 | ❌ 无 |
| **重试时价格** | 🔄 **重新获取BBO** | N/A |
| **失败日志** | 频繁出现 | 较少出现 |

---

## 三、问题诊断

### 您看到的日志

```
Order 2011824898020290560 not found attempt 1
Order 2011824898020290560 not found attempt 2
Order 2011824898020290560 not found attempt 3
Order 2011824898020290560 not found attempt 4
Taker order not filled, retrying...
```

### 发生的原因

```
时刻T1: ext获取ask价格 = 3000.00
时刻T2: 下单 price=3000.00 (IOC)
时刻T3: ask价格变化为3000.05（价格波动）
时刻T4: IOC订单在3000.00没有足够流动性 → 被取消
时刻T5: 重试，重新获取ask价格 = 3000.10 → 用新价格下单
时刻T6: 重试1-4次后，最终在3000.15成交

结果：最终成交价3000.15 vs 最初价格3000.00，价差0.15！
```

### 为什么Ext成本高于Lig？

1. **Ext**: 没有滑点保护 → 频繁重试 → 每次重试用新价格 → 最终价高
2. **Lig**: 有0.2%滑点保护 → 一次成交 → 价格稳定 → 成本低

---

## 四、高人建议分析

### 高人的核心观点

> Extended SDK不提供真正的市价单，只能用place_order + IOC + 激进价格来模拟

### 高人建议的方案

```python
# 买入：ask * 1.05（加5%滑点）
execution_price = market_price * Decimal(1 + 0.05)

# 卖出：bid * 0.95（减5%滑点）
execution_price = market_price * Decimal(1 - 0.05)
```

### 我们的评估

| 方案 | 滑点 | 优点 | 缺点 |
|------|------|------|------|
| **高人建议** | 5% | 几乎100%成交 | 成本太高，不适合套利 |
| **Lighter方案** | 0.2% | 平衡成交率和成本 | 已验证可行 |
| **当前Ext** | 0% | 成本最低 | 频繁失败和重试 |

---

## 五、改进方案

### 核心改动点

**文件**: `spread/trade_executor.py`
**函数**: `_place_extended_order_taker`

**修改前**:
```python
if price is None:
    best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
    if side == "buy":
        price = best_ask  # ❌ 没有滑点
    else:
        price = best_bid  # ❌ 没有滑点
```

**修改后**:
```python
if price is None:
    best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
    if side == "buy":
        price = best_ask * Decimal('1.002')  # ✅ 加0.2%滑点
    else:
        price = best_bid * Decimal('0.998')  # ✅ 减0.2%滑点
```

### 次要改动点

**文件**: `exchanges/extended.py`
**函数**: `place_taker_order`

**选项A**: 禁用内部重试
```python
# 将 max_retries = 10 改为 max_retries = 1
max_retries = 1
```

**选项B**: 重试时使用原始价格
```python
# 缓存第一次的价格，重试时使用相同价格
original_price = price
# 在重试循环中使用original_price而非重新获取
```

---

## 六、预期效果

### 改进前
- IOC订单失败率：~30-50%（估算）
- 平均重试次数：3-5次
- 价格不一致概率：高
- 您看到的日志：频繁出现

### 改进后
- IOC订单失败率：<5%（目标）
- 平均重试次数：<1次
- 价格不一致概率：接近0%
- 预期日志：很少出现

---

## 七、验证清单

- [ ] 1. 在`trade_executor.py`中为Ext加入0.2%滑点保护
- [ ] 2. 限制Ext的重试次数为1次
- [ ] 3. 测试开仓，验证"Order not found"日志显著减少
- [ ] 4. 检查最终成交价，验证ext成本 < lig成本
- [ ] 5. 对比改进前后的失败率数据

---

## 八、相关文件

1. **Spec文档**: `specs/001-fix-spread-price/spec.md` - 已更新包含滑点保护要求
2. **核心代码**:
   - `spread/trade_executor.py:555-609` - Ext taker订单
   - `spread/trade_executor.py:611-666` - Lig taker订单
   - `exchanges/extended.py:301-397` - Ext SDK封装
3. **检查清单**: `specs/001-fix-spread-price/checklists/requirements.md`

---

## 结论

**当前Ext实现不完全符合真正的Taker模式**：
- ✅ 使用了IOC模式（正确）
- ❌ 缺乏滑点保护（导致频繁重试）
- ❌ 重试时重新获取价格（导致价格不一致）

**改进优先级**：
1. **P0**: 加入0.2%滑点保护（与Lighter一致）
2. **P1**: 禁用或限制内部重试
3. **P2**: 重试时使用原始价格

**预期收益**：
- 减少"Order not found"日志90%以上
- 消除ext成本高于lig的问题
- 提高套利成功率
