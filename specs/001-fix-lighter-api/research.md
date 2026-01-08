# Research: 修复Lighter API调用失败和持仓不平衡问题

**Feature**: 001-fix-lighter-api
**Date**: 2026-01-07
**Status**: ✅ 已完成所有关键研究

---

## 研究问题汇总

本节记录在规格说明中发现的所有技术未知项，以及我们的研究决策。

### RQ-1: Lighter SDK的正确API方法名

**问题**: 代码中使用`account_active_orders`方法，但该方法不存在。

**研究过程**:
```bash
python -c "import lighter; print([m for m in dir(lighter.OrderApi) if 'account' in m])"
```

**发现**:
- SDK实际方法: `account_inactive_orders` (不是`account_active_orders`)
- 相关方法: `account_inactive_orders_with_http_info`, `account_inactive_orders_without_preload_content`

**决策**: 将`lighter.py`第467行的方法调用改为`account_inactive_orders`

**理由**:
- 方法名表明API返回的是"非活跃"订单，可能是已成交或已取消的历史订单
- 对于活跃订单，应该使用`order_book_orders`方法或依赖WebSocket更新

**替代方案考虑**:
- ❌ 使用`order_book_orders`: 这个方法需要`order_book_id`，而我们只有`account_index`
- ✅ 保留WebSocket作为主要数据源，`account_inactive_orders`仅作为回退

---

### RQ-2: 持仓价值计算方法

**问题**: Extended和Lighter如何计算持仓价值？是否包含未实现盈亏？

**研究过程**: 查看现有代码实现

**发现**:
1. **Extended持仓**: 使用`position_size * mark_price`计算
2. **Lighter持仓**: SDK返回的`position * value`已经包含未实现盈亏

**决策**:
- Extended持仓价值 = `abs(position_size) * current_mark_price`
- Lighter持仓价值 = `abs(position_value)` (从SDK获取)
- 净暴露 = Extended多头价值 - Lighter空头价值

**理由**:
- 使用统一的标记价格确保可比性
- 绝对值确保我们比较的是"暴露程度"而非方向

**替代方案考虑**:
- ❌ 使用开仓价格: 无法反映当前真实风险
- ❌ 包含未实现盈亏: 会混淆"不平衡"与"盈亏"

---

### RQ-3: 自动平仓的风险评估

**问题**: 在什么条件下自动平仓可能失败或造成更大损失？

**研究过程**: 分析极端市场场景

**发现**:

| 场景 | 风险 | 缓解措施 |
|------|------|---------|
| 流动性枯竭 | 无法成交或大幅滑点 | 设置最大滑点容忍度(1%) |
| 价格快速波动 | 平仓期间价格继续不利变动 | 使用市价单但限制滑点 |
| 部分成交 | 只平掉部分仓位，剩余仍不平衡 | 重试机制或手动介入 |
| 网络延迟 | 平仓指令延迟到达 | 超时机制 + 手动警告 |

**决策**:
- 默认**关闭**自动平仓 (`auto_close_unhedged = False`)
- 提供清晰的日志和建议，让用户手动决策
- 如果启用，添加多重安全检查

**理由**:
- 金融交易中，自动操作风险高
- 用户更信任手动确认重大决策

**替代方案考虑**:
- ❌ 默认启用自动平仓: 风险太高，可能在极端情况下放大损失
- ✅ 仅提供平仓建议: 安全但需要用户主动监控

---

### RQ-4: 持仓对账的性能影响

**问题**: 每60秒执行对账是否会影响主交易循环的性能？

**研究过程**:
- 分析现有`_stats_reporter`循环（每60秒）
- 对账将作为独立的`asyncio.create_task`运行

**发现**:
- 对账操作主要是计算和日志，无网络IO
- 预计耗时: <100ms

**决策**:
- 使用独立的asyncio任务，不阻塞主循环
- 配置化的对账间隔（默认60秒）

**理由**:
- 异步执行确保不影响交易速度
- 可配置允许用户根据需要调整频率

---

## 未解决的问题

### ❓ SDK版本兼容性

**问题**: 不同版本的Lighter SDK是否有不同的API？

**状态**: ⚠️ **需要验证**

**建议**:
- 在部署前检查生产环境的SDK版本
- 添加版本检测和条件代码（如果需要）

**后续行动**:
```python
import lighter
print(f"Lighter SDK版本: {lighter.__version__}")
```

---

## 技术决策记录

### TD-1: 订单信息获取的回退策略

**决策**: 以下列顺序尝试获取订单信息：

1. **WebSocket current_order** (最快，实时)
2. **REST API account_inactive_orders** (回退1)
3. **持仓推断** (最后手段，不可靠)

**理由**: WebSocket是最可靠的数据源，REST API是必要的回退，持仓推断仅用于紧急情况

---

### TD-2: 持仓不平衡的阈值

**决策**: 设置20%为警告阈值

**计算**:
```
差异百分比 = |Extended价值 - Lighter价值| / max(Extended价值, Lighter价值)
```

**示例**:
- Extended $35, Lighter $95 → 差异 = |35-95|/95 = 63% → ⚠️ 超过阈值
- Extended $35, Lighter $40 → 差异 = |35-40|/40 = 12.5% → ✅ 在阈值内

**理由**:
- 20%允许正常的价差波动
- 超过20%表明有明显的累积不平衡

---

### TD-3: 日志级别使用

**决策**:
- **INFO**: 正常对账结果、持仓平衡
- **WARNING**: 轻微不平衡（<20%）、首次检测到问题
- **ERROR**: 严重不平衡（>20%）、对冲失败、API错误

**理由**: 清晰的级别帮助用户快速识别问题严重性

---

## 参考资料

1. **Lighter SDK文档**: (需要查找官方文档URL)
2. **现有代码**:
   - `exchanges/lighter.py:467` - 错误的API调用
   - `spread/bot.py:743` - 持仓对账循环（已添加）
   - `spread/hedge_manager.py:93` - 改进的等待逻辑（已完成）

---

## 下一步

Phase 0研究完成。现在进入Phase 1设计阶段，创建：
1. `data-model.md` - 数据模型
2. `contracts/` - API契约
3. `quickstart.md` - 快速开始指南
