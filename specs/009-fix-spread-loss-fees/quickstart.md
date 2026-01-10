# Quickstart: 价差套利核心问题修复

**Feature**: 009-fix-spread-loss-fees
**Date**: 2026-01-10

## 概述

本功能修复价差套利系统的三个致命问题：
1. **中间价陷阱** - 改用对手价计算真实价差
2. **Post-Only逻辑冲突** - 实现真正的Maker策略
3. **负期望收益** - 提高开仓阈值确保正期望

---

## 安装前置要求

### 环境要求
- Python 3.11+
- asyncio
- websockets
- decimal.Decimal
- pytest (用于测试)

### 无需额外安装
- 本修复不引入新的外部依赖
- 所有新功能使用Python标准库实现

---

## 快速开始

### 1. 更新配置文件

编辑 `spread/config.py`，更新以下默认值：

```python
@dataclass
class SpreadArbConfig:
    # ... 其他配置 ...

    # 修复: 提高最小价差率
    min_spread_rate: Decimal = Decimal('0.0010')  # 从0.0005改为0.0010 (0.10%)

    # 新增: Maker价格偏移
    maker_price_tick: Decimal = Decimal('0.01')  # 0.01美元

    # 新增: 最小利润率阈值
    min_profit_threshold: Decimal = Decimal('0.0002')  # 0.02%
```

### 2. 使用新的价差计算器

```python
from spread.real_spread_calculator import RealSpreadCalculator

# 创建计算器实例
calculator = RealSpreadCalculator(config)

# 计算做多价差机会
result = calculator.calculate_best_opportunity(
    extended_bid=Decimal('3090.00'),
    extended_ask=Decimal('3092.00'),
    lighter_bid=Decimal('3091.00'),
    lighter_ask=Decimal('3093.00'),
    min_spread_rate=Decimal('0.0010')
)

if result.is_valid:
    print(f"真实价差: {result.spread_rate:.4%}")
    print(f"期望收益: {result.expected_profit_rate:.4%}")
    print(f"Extended开仓价: {result.extended_entry_price}")
    print(f"Lighter开仓价: {result.lighter_entry_price}")
else:
    print(f"无效机会: {result.failure_reason}")
```

### 3. 运行修复后的套利机器人

```bash
# 使用新的配置运行
python spread/run_spread_arb.py \
    --ticker ETH \
    --size 35 \
    --max-pairs 3 \
    --min-spread 0.0010  # 使用新的阈值
```

### 4. 查看改进后的日志

修复后，日志会显示：

```log
# 开仓日志（新增字段）
=== 交易开仓 ===
时间: 2026-01-10 12:00:00
套利对ID: 1
方向: 做多价差

[真实价差信息]
真实价差率: 0.1200% (对手价计算)
期望收益率: 0.0400% (扣除成本后)

[开仓价格]
Extended开仓: $3092.00 (ask)
Lighter开仓: $3091.00 (bid)

[成本分解]
Extended手续费: $0.00 (maker)
Lighter手续费: $0.00
Extended点差成本: $0.31
Lighter点差成本: $0.31
总开仓成本: $0.62

[订单执行]
Extended订单类型: maker (手续费0%)
Lighter订单类型: taker (手续费0%)
```

---

## 核心修复说明

### 修复1: 对手价价差计算

**问题**: 使用中间价计算虚假套利机会

**修复**: 创建 `RealSpreadCalculator` 类

```python
# 旧的（错误）
spread = extended_mid - lighter_mid

# 新的（正确）
# 做多: spread = lighter_bid - extended_ask
# 做空: spread = extended_bid - lighter_ask
```

**影响文件**:
- `spread/calculator.py` - 主要修改
- `spread/real_spread_calculator.py` - 新增

---

### 修复2: 真正的Maker策略

**问题**: Post-Only订单100%被拒绝

**修复**: 正确定价maker订单

```python
# 做多时（买入）
price = extended_bid - price_tick  # 挂在买一价下方
post_only = True

# 做空时（卖出）
price = extended_ask + price_tick  # 挂在卖一价上方
post_only = True
```

**影响文件**:
- `spread/bot.py` - 修改下单逻辑
- `spread/order_manager.py` - 改进超时处理

---

### 修复3: 提高开仓阈值

**问题**: 0.06%阈值导致负期望收益

**修复**: 提高到0.10%

```python
# 旧的配置
min_spread_rate = 0.05%
latency_buffer = 0.01%
实际阈值 = 0.06%
期望收益 = -0.01% (负！)

# 新的配置
min_spread_rate = 0.10%
latency_buffer = 0.01%
实际阈值 = 0.11%
期望收益 = +0.04% (正！)
```

**影响文件**:
- `spread/config.py` - 更新默认值

---

### 修复4: 仓位平衡计算

**问题**: 使用绝对值相加导致200%差异率

**修复**: 使用相减计算净仓位

```python
# 旧的（错误）
diff = abs(extended_total) + abs(lighter_total)

# 新的（正确）
diff = abs(extended_total - lighter_total)
```

**影响文件**:
- `spread/bot.py` - 修改 `_log_position_status` 方法

---

### 修复5: 改进平仓策略

**问题**: 在不利时机强制平仓导致亏损

**修复**: 多级优先级平仓系统

```python
def _should_close_position(self, pair, current_real_spread):
    """多级平仓决策"""
    close_pnl = self._calculate_close_pnl(pair, current_real_spread)

    # P1: 有利润 → 立即平仓
    if close_pnl > 0:
        return True, "P1: 有利润"

    # P2: 时间短 + 微利 → 平仓
    if holding_time < 60 and close_pnl > -small_loss:
        return True, "P2: 时间小额平仓"

    # P3: 时间长 + 接近回本 → 平仓
    if holding_time > 240 and close_pnl > -small_loss * 2:
        return True, "P3: 接近回本"

    # P4: 超时 → 检查价差方向
    if holding_time > max_time:
        if is_spread_diverging:
            return False, "延迟: 价差扩大"
        return True, "P4: 超时平仓"

    return False, "继续持有"
```

**影响文件**:
- `spread/bot.py` - 重写 `_check_close_conditions`

---

## 数据收集

### 验证核心修复

运行修复后的系统，日志会记录：

```log
# 验证1: 真实价差计算
[价差检查(对手价)]
Extended: bid=3090.00, ask=3092.00
Lighter: bid=3091.00, ask=3093.00
做多真实价差: -1.00 (-0.0323%) ❌ 不通过阈值
做空真实价差: -1.00 (-0.0323%) ❌ 不通过阈值

# 验证2: Maker订单成功
[Extended] 下买入 MAKER 单: 0.0113 @ 3089.99 (买一价: 3090.00)
✅ 订单已提交: order_123
✅ Maker订单成交: 0.0113 @ 3089.99
手续费: $0.00 (0.00%) ← 确认是maker！

# 验证3: 仓位平衡
📊 仓位平衡状态:
Extended总仓位: 0.0340 ETH
Lighter总仓位: 0.0340 ETH
净仓位: 0.0000 ETH
差异率: 0.00% ✅ (之前200%)
```

### 导出分析数据

```python
from spread.data_collector import DataCollector

collector = DataCollector()

# 导出交易记录
collector.export_trades_csv('data/trades_2026_01_10.csv')

# 导出订单记录
collector.export_orders_csv('data/orders_2026_01_10.csv')
```

生成的CSV文件包含：
- 每笔交易的详细成本分解
- 订单类型（maker/taker）
- 实际手续费和滑点
- 持仓时间和收益率

---

## 测试

### 单元测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_real_spread_calculator.py -v
pytest tests/test_position_balance.py -v
```

### 新增测试文件

- `tests/test_real_spread_calculator.py` - 对手价计算测试
- `tests/test_maker_pricing.py` - Maker定价测试
- `tests/test_position_balance.py` - 仓位平衡测试
- `tests/test_cost_breakdown.py` - 成本分解测试

### 集成测试

```bash
# 模拟交易测试
python tests/integration/test_real_spread_trading.py \
    --duration 300 \  # 5分钟
    --min-spread 0.0010
```

---

## 故障排除

### 问题1: Maker订单仍然被拒绝

**症状**: 日志显示"订单被拒绝"

**原因**: price_tick可能太小

**解决方案**:
```python
# 增加price_tick
maker_price_tick = Decimal('0.02')  # 从0.01增加到0.02
```

---

### 问题2: 开仓次数大幅减少

**症状**: 修复后几乎没有交易

**原因**: 阈值0.10%可能太高

**解决方案**:
```bash
# 临时降低阈值测试
python spread/run_spread_arb.py --min-spread 0.0008

# 或者收集24小时数据后，使用动态阈值
python spread/analyze_spreads.py --recommend-threshold
```

---

### 问题3: 仍然有亏损交易

**症状**: 即使修复后，仍有亏损

**检查**:
1. 确认使用的是对手价计算
2. 检查日志中的成本分解
3. 验证实际手续费是否与配置一致
4. 查看是否在不利时机平仓

**调试**:
```python
# 启用详细日志
import logging
logging.getLogger("SpreadCalculator").setLevel(logging.DEBUG)
logging.getLogger("OrderManager").setLevel(logging.DEBUG)
```

---

## 性能影响

| 指标 | 修复前 | 修复后 | 说明 |
|------|--------|--------|------|
| 开仓频率 | ~100次/小时 | ~10-20次/小时 | 质量优先 |
| 胜率 | ~0% | 预期>60% | 正期望 |
| 平均收益率 | -2.00% | 预期+0.03% | 正期望 |
| Maker成功率 | 0% | 预期50%+ | 手续费降低 |
| 仓位差异率 | 200% | <1% | 正确计算 |

---

## 下一步

1. ✅ 部署修复到测试环境
2. ✅ 运行24小时收集数据
3. ✅ 分析数据调整参数
4. ✅ 部署到生产环境
5. ✅ 持续监控和优化

---

## 参考资料

- 功能规范: `specs/009-fix-spread-loss-fees/spec.md`
- 研究文档: `specs/009-fix-spread-loss-fees/research.md`
- 数据模型: `specs/009-fix-spread-loss-fees/data-model.md`
- 接口契约: `specs/009-fix-spread-loss-fees/contracts/`
