# 技术调研: 优化价差套利策略

**功能**: 002-optimize-spread-arb
**日期**: 2026-01-08
**状态**: 完成

## 概述

本文档记录优化价差套利策略的技术调研结果,包括关键技术决策、设计选择和实现考量。

---

## 1. 单边持仓风险控制机制

### 决策
采用多层防护机制,结合主动检测和自动平仓。

### 技术方案

**检测机制**:
- 在 `_reconciliation_loop()` 中定期检查未对冲持仓列表 (`unhedged_positions`)
- 检查间隔: 配置化 (`unhedged_position_timeout`, 默认60秒)
- 超时判定: `current_time - position['timestamp'] > timeout`

**处理策略**:
1. **立即禁止开新仓**: 在策略循环中检查 `len(unhedged_positions) > max_unhedged_positions`
2. **紧急平仓**: 实现自动平仓未对冲持仓的机制 (谨慎使用,需用户确认)
3. **告警机制**: 通过日志和统计报告持续提醒

### 替代方案

| 方案 | 优点 | 缺点 | 选择结果 |
|------|------|------|----------|
| 完全自动平仓 | 响应最快,风险最小 | 可能误平,用户失去控制 | 不采用 - 风险太高 |
| 仅告警+手动处理 | 安全,用户掌控 | 响应慢,可能错过最佳时机 | 当前实现 - 作为保底 |
| 自动+手动混合 | 平衡风险和效率 | 复杂度高 | **采用** - 分级处理 |

### 实现细节

```python
# 在 bot.py 的 _strategy_loop() 中增加检查
if len(self.unhedged_positions) > self.config.max_unhedged_positions:
    self.logger.error(f"🚨 检测到 {len(self.unhedged_positions)} 个未对冲仓位!")
    # 禁止开新仓
    await asyncio.sleep(5)
    continue
```

---

## 2. 价差阈值计算优化

### 决策
基于手续费结构动态计算开仓阈值,降低固定阈值以提高交易频率。

### 技术方案

**手续费结构**:
- Lighter: taker 0%, maker 0%
- Extended: taker 0.0225% (0.000225), maker 0%

**计算逻辑**:
```python
# 单次交易成本 (开仓+平仓)
extended_taker_fee = Decimal('0.000225')  # 0.0225%
lighter_fee = Decimal('0')                 # 0%

# 总成本 (Extended开仓 taker + Extended平仓 taker)
total_cost = extended_taker_fee * 2 = 0.00045 (0.045%)

# 加上安全边际 (建议20%)
min_spread_rate = total_cost * 1.2 = 0.00054 (0.054%)
```

### 配置实现

在 `config.py` 中调整默认值:
```python
min_spread_rate: Decimal = Decimal('0.0005')  # 0.05% (覆盖手续费+利润)
```

### 替代方案

| 方案 | 优点 | 缺点 | 选择结果 |
|------|------|------|----------|
| 固定阈值 0.08% | 简单,保守 | 错过机会,频率低 | 当前实现 - 需优化 |
| 动态计算 | 精确,适应性强 | 复杂,依赖费率准确性 | **采用** - 更优 |
| 机器学习预测 | 最优 | 过度设计,数据需求大 | 不采用 - 过于复杂 |

---

## 3. 多层智能平仓策略

### 决策
实现基于时间和盈亏的多层平仓决策,优先级: 盈利目标 > 时间小额 > 回本止损。

### 技术方案

**平仓优先级** (从高到低):
1. **盈利目标平仓**: PnL >= 盈利目标 (0.05%) → 立即平仓
2. **时间小额平仓**: 持仓 > 60秒 且 PnL > 0 → 平仓锁定小额利润
3. **回本止损**: 持仓 > 60秒 且 PnL < 0 → 等待 PnL >= 0 时平仓
4. **强制平仓**: 持仓 > 最大时间 (5分钟) → 无论盈亏强制平仓

### 实现逻辑

修改 `_check_force_close()` 方法:

```python
def _check_force_close(self, pair, current_extended, current_lighter):
    unrealized_pnl = pair.calculate_unrealized_pnl(current_extended, current_lighter)
    holding_time = pair.holding_time

    # 1. 盈利目标检查 (最高优先级)
    profit_target = pair.extended_quantity * current_extended * self.config.profit_target_rate
    if unrealized_pnl >= profit_target:
        return True, f"盈利目标 (${unrealized_pnl:.2f})"

    # 2. 时间小额平仓
    if holding_time > self.config.time_close_threshold:
        if unrealized_pnl > 0:
            return True, f"时间小额 (持仓{holding_time:.0f}秒, PnL=${unrealized_pnl:.2f})"
        elif unrealized_pnl == 0:
            return True, f"回本止损 (持仓{holding_time:.0f}秒)"

    # 3. 强制平仓
    if holding_time > self.config.max_holding_time:
        return True, f"强制平仓 (持仓{holding_time:.0f}秒)"

    return False, None
```

### 配置参数

在 `config.py` 中新增:
```python
# 新增配置
profit_target_rate: Decimal = Decimal('0.0005')     # 盈利目标 0.05%
time_close_threshold: int = 60                      # 时间阈值 60秒
max_holding_time: int = 300                         # 最大持仓时间 5分钟
```

### 替代方案

| 方案 | 优点 | 缺点 | 选择结果 |
|------|------|------|----------|
| 固定时间平仓 | 简单 | 可能错过利润 | 不够灵活 |
| 仅盈亏平仓 | 利润最大化 | 可能长期持仓 | 风险高 |
| **多层策略** | 平衡频率和利润 | 稍复杂 | **采用** - 最优平衡 |

---

## 4. 交易价格日志记录

### 决策
在关键交易节点记录详细价格信息,使用结构化日志格式便于后续分析。

### 技术方案

**记录时机**:
1. 开仓时: 记录 Extended 和 Lighter 的成交价格、数量、订单ID
2. 平仓时: 记录平仓价格、持仓时间、实现盈亏
3. 套利对完成时: 输出完整交易总结

**日志格式**:
```python
# 开仓日志
self.logger.info(
    f"✅ 开仓成功! 套利对 #{pair.pair_id}: "
    f"{pair.extended_side.upper()} {pair.extended_quantity:.4f} "
    f"Extended@{pair.extended_price:.2f} Lighter@{pair.lighter_price:.2f} "
    f"开仓价差: ${pair.open_spread:.2f} ({pair.open_spread_rate:.4%})"
)

# 平仓日志
self.logger.info(
    f"💰 平仓成功! 套利对 #{pair.pair_id}: "
    f"盈亏 ${profit:.2f} "
    f"持仓 {pair.holding_time:.0f}秒"
)
```

### 数据模型增强

在 `SpreadPair` 类中增加价格记录字段:
```python
class SpreadPair:
    # 新增字段
    open_extended_order_id: Optional[str] = None
    open_lighter_order_id: Optional[str] = None
    close_extended_order_id: Optional[str] = None
    close_lighter_order_id: Optional[str] = None

    open_timestamp: float
    close_timestamp: Optional[float] = None
```

### 性能考虑

- 使用 f-string 格式化 (性能优于 % 或 .format())
- 避免在热循环中创建临时对象
- 日志级别使用 INFO,避免 DEBUG 被过滤

### 替代方案

| 方案 | 优点 | 缺点 | 选择结果 |
|------|------|------|----------|
| 数据库存储 | 易于查询分析 | 额外依赖,延迟 | 过度设计 |
| 文件日志 | 简单,低延迟 | 查询不便 | **采用** - 足够使用 |
| 结构化JSON | 易解析 | 可读性差 | 可选 - 按需启用 |

---

## 5. 配置参数化

### 决策
所有关键阈值支持通过环境变量或配置文件调整,无需修改代码。

### 技术方案

**配置加载优先级**:
1. 环境变量 (最高优先级)
2. 配置文件 (YAML/TOML)
3. 默认值 (代码中的 dataclass)

**实现示例**:
```python
import os
from dataclasses import dataclass

@dataclass
class SpreadArbConfig:
    profit_target_rate: Decimal = Decimal('0.0005')
    time_close_threshold: int = 60

    @classmethod
    def from_env(cls):
        return cls(
            profit_target_rate=Decimal(os.getenv('PROFIT_TARGET_RATE', '0.0005')),
            time_close_threshold=int(os.getenv('TIME_CLOSE_THRESHOLD', '60'))
        )
```

### 配置参数清单

| 参数 | 默认值 | 说明 | 环境变量 |
|------|--------|------|----------|
| `min_spread_rate` | 0.05% | 最小价差阈值 | `MIN_SPREAD_RATE` |
| `profit_target_rate` | 0.05% | 盈利目标 | `PROFIT_TARGET_RATE` |
| `time_close_threshold` | 60秒 | 时间平仓阈值 | `TIME_CLOSE_THRESHOLD` |
| `max_holding_time` | 300秒 | 最大持仓时间 | `MAX_HOLDING_TIME` |
| `unhedged_position_timeout` | 60秒 | 未对冲超时 | `UNHEDGED_TIMEOUT` |

---

## 6. 测试策略

### 决策
使用 pytest 进行单元测试和集成测试,覆盖核心逻辑。

### 测试覆盖

**单元测试**:
- `test_spread_pair.py`: 测试套利对的盈亏计算
- `test_config.py`: 测试配置参数验证
- `test_calculator.py`: 测试价差计算逻辑

**集成测试**:
- `test_closing_strategy.py`: 测试平仓策略的完整流程
- 模拟单边持仓场景
- 模拟不同盈亏情况

### 测试工具

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_spread_pair.py::test_calculate_unrealized_pnl -v

# 生成覆盖率报告
pytest tests/ --cov=spread --cov-report=html
```

---

## 总结

### 技术决策汇总

| 决策点 | 选择方案 | 理由 |
|--------|----------|------|
| 单边持仓处理 | 多层防护 (检测+禁止+告警) | 平衡安全和效率 |
| 价差阈值 | 动态计算 0.05% | 覆盖手续费,提高频率 |
| 平仓策略 | 多层决策 (盈利>时间>回本) | 最大化资金利用 |
| 日志记录 | 结构化文件日志 | 简单高效 |
| 配置管理 | 环境变量+默认值 | 灵活且向后兼容 |

### 待澄清问题

无 - 所有关键技术决策已明确。

### 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 自动平仓误操作 | 中 | 默认关闭,需用户明确启用 |
| 日志性能影响 | 低 | 异步日志,可配置级别 |
| 配置参数过多 | 低 | 提供合理默认值 |
| 测试覆盖不足 | 中 | 优先测试核心逻辑 |

### 下一步

完成本调研后,进入 Phase 1 设计阶段:
1. 生成 `data-model.md` - 详细的数据模型定义
2. 生成 `quickstart.md` - 开发和部署指南
3. 更新 agent context - 同步项目上下文
