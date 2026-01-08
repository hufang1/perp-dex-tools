# Quickstart: 修复Lighter API和持仓不平衡问题

**Feature**: 001-fix-lighter-api
**Date**: 2026-01-07

---

## 概述

本指南提供快速实施步骤，修复两个关键问题：
1. ❌ `'OrderApi' object has no attribute 'account_active_orders'` 错误
2. ⚠️ 持仓不平衡风险（Lighter $95.72 vs Extended $31.9）

---

## ⚡ 快速修复（5分钟）

### 步骤1: 修复API方法名

**文件**: `exchanges/lighter.py`
**行数**: 467

**修改前**:
```python
orders_response = await order_api.account_active_orders(
    account_index=self.account_index,
    market_id=self.config.contract_id,
    auth=auth_token
)
```

**修改后**:
```python
orders_response = await order_api.account_inactive_orders(
    account_index=self.account_index,
    market_id=self.config.contract_id,
    auth=auth_token
)
```

**验证**: 运行测试确保不再出现`AttributeError`

---

### 步骤2: 验证修复

运行套利机器人并观察日志：
```bash
python spread/run_spread_arb.py --ticker ETH --quantity 35 --max-pairs 3 --log-level DEBUG
```

**期望结果**:
- ✅ 不再出现`'OrderApi' object has no attribute 'account_active_orders'`错误
- ✅ Lighter订单查询成功
- ✅ 对冲操作完成

---

## 🔧 完整实施（30分钟）

### 阶段1: 配置更新

**文件**: `spread/config.py`

添加新配置项（已在之前会话完成）：
```python
# 未对冲持仓保护
max_unhedged_positions: int = 0
auto_close_unhedged: bool = False
unhedged_position_timeout: int = 300

# 对冲失败监控
hedge_failure_threshold: Decimal = Decimal('0.3')
hedge_failure_window: int = 10

# 持仓对账
enable_reconciliation: bool = True
reconciliation_interval: int = 60
```

---

### 阶段2: 持仓对账实现

**文件**: `spread/bot.py`

**添加到`__init__`方法**:
```python
# 对冲失败率统计
self.hedge_attempts = []
```

**添加新方法**:
```python
async def _reconciliation_loop(self):
    """持仓对账循环"""
    self.logger.info("持仓对账循环启动")

    while not self.stop_flag:
        try:
            await asyncio.sleep(self.config.reconciliation_interval)

            if not self.config.enable_reconciliation:
                continue

            # 获取持仓
            extended_value = self._get_extended_position_value()
            lighter_value = self._get_lighter_position_value()

            # 计算不平衡
            net_exposure = extended_value - lighter_value
            max_value = max(extended_value, lighter_value)
            imbalance_ratio = abs(net_exposure) / max_value if max_value > 0 else Decimal('0')

            # 记录日志
            self.logger.info(
                f"持仓对账: Extended=${extended_value:.2f}, "
                f"Lighter=${lighter_value:.2f}, "
                f"净暴露=${net_exposure:.2f}, "
                f"不平衡={imbalance_ratio:.2%}"
            )

            # 检查阈值
            if imbalance_ratio > Decimal('0.20'):
                self.logger.error(
                    f"🚨 持仓不平衡超过阈值! {imbalance_ratio:.2%} > 20%"
                )

                # 建议平仓
                if lighter_value > extended_value:
                    suggested_qty = (lighter_value - extended_value) / self._get_current_price()
                    self.logger.error(f"建议平仓: Lighter空头 {suggested_qty:.4f} ETH")

        except Exception as e:
            self.logger.error(f"对账循环错误: {e}")
```

**添加到主循环**:
```python
async def run(self):
    # ... 现有代码 ...

    tasks = [
        asyncio.create_task(self._strategy_loop(), name="strategy"),
        asyncio.create_task(self._monitor_pairs(), name="monitor"),
        asyncio.create_task(self._stats_reporter(), name="stats"),
        asyncio.create_task(self._reconciliation_loop(), name="reconciliation")  # 新增
    ]
```

---

### 阶段3: 测试

**单元测试**:
```bash
pytest tests/test_lighter_api_fix.py -v
pytest tests/test_position_reconciliation.py -v
```

**集成测试**:
```bash
# 小额度测试
python spread/run_spread_arb.py --ticker ETH --quantity 10 --max-pairs 1
```

**监控日志**:
- 每分钟查看对账日志
- 确认不平衡检测正常工作
- 验证API错误已修复

---

## 📊 验证清单

- [ ] API方法名已修复（`account_inactive_orders`）
- [ ] 不再出现`AttributeError`
- [ ] 持仓对账每60秒执行
- [ ] 不平衡超过20%时触发警告
- [ ] 日志包含所有必要信息
- [ ] 单元测试通过
- [ ] 集成测试成功

---

## 🚨 紧急操作

如果当前持仓不平衡：

1. **手动平仓多余的Lighter空头**:
   ```bash
   # 在Lighter UI或API中平掉 0.03 ETH 空头
   ```

2. **验证平衡**:
   ```
   Lighter持仓价值 ≈ Extended持仓价值
   ```

3. **重启机器人**:
   ```bash
   python spread/run_spread_arb.py --ticker ETH --quantity 35 --max-pairs 3
   ```

---

## 📝 相关文档

- [规格说明](./spec.md)
- [实施计划](./plan.md)
- [研究文档](./research.md)
- [数据模型](./data-model.md)
- [API契约](./contracts/api.md)

---

## ❓ 常见问题

### Q1: 为什么SDK方法是`account_inactive_orders`而不是`account_active_orders`？

**A**: Lighter API的设计是：
- `account_inactive_orders` = 已成交、已取消、已过期的历史订单
- `order_book_orders` = 当前订单簿中的活跃订单
- WebSocket推送实时订单更新

我们应该主要依赖WebSocket，`account_inactive_orders`仅作为回退。

### Q2: 20%的不平衡阈值是否合适？

**A**: 基于：
- 正常价差波动: <5%
- 部分成交可能导致: 5-10%
- **累积不平衡**: >20% (需要立即处理)

您可以根据风险承受能力调整此阈值。

### Q3: 自动平仓安全吗？

**A**: 默认**关闭**自动平仓，因为：
- 极端市场下可能滑点巨大
- 网络延迟可能导致平仓失败
- 手动决策更安全

仅在您充分理解风险后才启用：
```python
auto_close_unhedged = True  # ⚠️ 谨慎使用
```

---

## 🎯 下一步

实施完成后，运行：
```bash
/speckit.tasks
```

这将生成详细的任务清单到`tasks.md`。
