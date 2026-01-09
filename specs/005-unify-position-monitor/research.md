# Research: 统一持仓监控显示并增加平仓收益实时计算

**Feature**: 005-unify-position-monitor
**Date**: 2026-01-09

## 研究决策总结

### 1. 手续费计算规则

| 交易所 | 手续费率 | 数据来源 |
|--------|---------|---------|
| Extended | 0.0225% (taker) | `tests/integration/test_spread_threshold.py:124` |
| Lighter | 0% | `spread/README.md` 描述 |

**决策**：
- Extended手续费率：`0.000225` (0.0225%)
- Lighter手续费率：`0.0` (0%)
- 双边交易成本：`0.00045` (0.045%)
- **rationale**：测试代码中明确定义了Extended taker费率；README明确说明Lighter为0%手续费

**替代方案考虑**：
- 使用固定费率（已采用）：简单可靠，符合当前业务逻辑
- 动态获取费率：需要API支持，增加复杂度，当前不需要

### 2. 持仓合并策略

| 问题 | 决策 | 理由 |
|------|------|------|
| 平均开仓价格 | **加权平均**（按数量加权） | 金融标准做法，反映真实成本 |
| 开仓时间显示 | **时间范围**（最早-最晚） | 保留完整信息，用户可了解持仓跨度 |
| pair_id显示 | **统一编号 + 列表** | 主标题使用统一标识，详情中列出包含的pair_id |

**rationale**：
- 加权平均价格：`Σ(quantity × price) / Σ(quantity)` 符合会计准则
- 时间范围：用户能看到"持仓了37-49秒"，更直观
- pair_id显示：主标题简化为"做多仓位"，副标题显示"共3个套利对"

### 3. 对手价获取机制

**确认**：bot.py中已有完整的订单簿数据结构

```python
# spread/bot.py:54-61
self.extended_orderbook: Dict[str, Dict[Decimal, Decimal]] = {
    'bids': {price: quantity, ...},  # 买单
    'asks': {price: quantity, ...}   # 卖单
}
self.lighter_orderbook: Dict[str, Dict[Decimal, Decimal]] = {
    'bids': {},
    'asks': {}
}
```

**获取最优价格的方法**（已在代码中使用）：
```python
extended_bid = max(orderbook['bids'].keys()) if orderbook['bids'] else Decimal('0')
extended_ask = min(orderbook['asks'].keys()) if orderbook['asks'] else Decimal('999999')
```

**rationale**：复用现有代码逻辑，无需新的API调用

## 技术约束确认

1. **精度要求**：所有计算必须使用`Decimal`类型，避免浮点数误差
2. **性能要求**：计算过程应在100ms内完成，不影响交易主循环
3. **错误处理**：订单簿为空时返回0或inf值，需要健壮的错误处理

## 依赖模块分析

| 模块 | 依赖关系 | 影响评估 |
|------|---------|---------|
| `SpreadPair` | 需要添加手续费计算方法 | 轻微修改，添加新方法 |
| `SpreadArbConfig` | 需要添加手续费率配置 | 轻微修改，添加新字段 |
| `bot.py` | 需要重构监控输出逻辑 | 中等修改，重写_log_position_status |

## 未知数已全部解决

- [x] Extended手续费率：0.0225%
- [x] Lighter手续费率：0%
- [x] 持仓合并策略：加权平均、时间范围、统一编号
- [x] 对手价获取：复用现有orderbook结构
