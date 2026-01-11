# Research Document: 修复仓位失衡和优化开仓标准

**Feature**: 010-fix-position-imbalance
**Date**: 2026-01-11
**Status**: Phase 0 Research Complete

## 研究目标

解决两个关键问题：
1. **P0**: Extended累积0.21 ETH但Lighter仅对冲0.02 ETH（90%未对冲）
2. **P1**: 开仓机会太少（10小时仅2次）

## R1: 对冲失败检测机制

### 决策：现有机制完善但执行存在问题

**研究发现**：
- 系统已有完整的对冲失败检测机制（bot.py 937-957行）
- 有重试机制（最多3次，延迟1秒）
- 有未对冲仓位跟踪（`unhedged_positions`）
- 有对冲失败率监控（`hedge_attempts`滑动窗口）

**关键问题**：
虽然机制完善，但**对冲失败率高达90%**（0.21 ETH vs 0.02 ETH），说明：
1. 检测机制正常工作
2. 但**持续开仓**导致未对冲仓位累积
3. 熔断机制没有被正确触发

### 决策：修复熔断触发逻辑

**根本原因**：
- bot.py 968-969行：未对冲仓位时设置`pause_until = time.time() + 3600`
- 但可能存在**时序问题**：暂停检查在开仓决策之前
- 或者暂停被其他逻辑覆盖

**技术方案**：
1. 在开仓决策前**先检查是否暂停**（`is_paused`）
2. 在任何对冲失败后**立即设置暂停标志**
3. 增强`_check_can_open_new_position()`方法

## R2: 仓位平衡计算修复

### 决策：统一使用绝对值计算方式

**研究发现**：
- `PositionBalance.__post_init__`（models.py 98-120行）使用错误的计算方式
- `PositionAggregator.calculate_balance()`（position_aggregator.py 191-248行）使用正确的计算方式

**当前错误计算**（PositionBalance）：
```python
self.diff_rate = abs(self.diff_qty) / self.lighter_total_qty
```

对于完全对冲仓位（Extended 0.01, Lighter -0.01）：
- `diff_qty = abs(0.01 - (-0.01)) = 0.02`
- `diff_rate = 0.02 / abs(-0.01) = 200%` ❌ 错误！

**正确计算**（使用绝对值）：
```python
total_exposure = abs(extended_total) + abs(lighter_total)
diff_qty = abs(abs(extended_total) - abs(lighter_total))
diff_rate = diff_qty / total_exposure if total_exposure > 0 else 0
```

对于完全对冲仓位：
- `total_exposure = 0.01 + 0.01 = 0.02`
- `diff_qty = |0.01 - 0.01| = 0`
- `diff_rate = 0 / 0.02 = 0%` ✅ 正确！

对于实际失衡情况（Extended 0.21, Lighter 0.02）：
- `total_exposure = 0.21 + 0.02 = 0.23`
- `diff_qty = |0.21 - 0.02| = 0.19`
- `diff_rate = 0.19 / 0.23 = 82.6%` ✅ 正确！

### 决策：修改PositionBalance模型

**技术方案**：
1. 修改`models.py`中`PositionBalance.__post_init__`的计算逻辑
2. 与`PositionAggregator.calculate_balance()`保持一致
3. 更新`trade_logger.py`中的格式化输出

## R3: 熔断机制设计

### 决策：增强现有熔断机制

**研究发现**：
- 系统已有熔断机制（consecutive_failures, pause_until）
- 触发条件：
  - 未对冲仓位：暂停1小时（bot.py 968-969行）
  - 连续失败：暂停60秒（config.py 77-78行）
  - 对冲失败率>30%：警告（bot.py 2069-2096行）

**关键问题**：
熔断机制存在，但**没有阻止持续开仓**！

### 决策：新增安全监控模块

**技术方案**：
创建`safety_monitor.py`模块，实现：
1. **对冲失败率监控**（滑动窗口10次）
2. **仓位失衡率监控**（实时计算）
3. **多级熔断**：
   - Level 1: 失败率>30% → 禁止新开仓
   - Level 2: 失败率>50% → 暂停所有交易
   - Level 3: 失衡率>50% → 强制平仓模式

**配置项**（config.py新增）：
```python
safety_hedge_failure_threshold: Decimal = Decimal('0.3')  # 30%
safety_position_imbalance_threshold: Decimal = Decimal('0.5')  # 50%
safety_pause_on_failure: bool = True
safety_force_close_threshold: Decimal = Decimal('0.5')  # 50%
```

## R4: Lighter交易所深度问题

### 决策：保持当前策略但增强检查

**研究发现**：
- 使用限价单模拟市价单（±1%价格）
- 深度检查：最小200 USDT，35 USDT订单相对安全
- 重试机制：最多3次，延迟1秒

**问题分析**：
90%失败率说明**不是订单类型问题**，而是：
1. Lighter深度可能不足（虽然检查通过）
2. WebSocket连接不稳定
3. API限流或拒绝订单

### 决策：增强Lighter错误处理

**技术方案**：
1. 记录详细的失败原因（hedge_manager.py）
2. 区分"流动性不足"、"API错误"、"网络问题"
3. 根据失败原因调整策略：
   - 流动性不足：提高价格容忍度（±2%）
   - API错误：延长重试延迟
   - 网络问题：检查WebSocket连接

## R5: 配置项设计

### 决策：新增安全相关配置项

**新增配置项**（SpreadArbConfig）：

```python
# 安全监控配置
safety_enabled: bool = True                      # 启用安全监控
safety_hedge_failure_threshold: Decimal = Decimal('0.3')  # 对冲失败率阈值
safety_position_imbalance_threshold: Decimal = Decimal('0.5')  # 仓位失衡率阈值
safety_failure_window: int = 10                  # 失败率统计窗口

# 动态阈值调整（P1）
adaptive_threshold_enabled: bool = False         # 启用动态阈值调整
adaptive_min_hedge_success_rate: Decimal = Decimal('0.9')  # 最低对冲成功率
adaptive_min_spread_rate_safe: Decimal = Decimal('0.15')  # 安全阈值（对冲成功率低时）
adaptive_min_spread_rate_aggressive: Decimal = Decimal('0.06')  # 激进阈值（对冲成功率高时）

# P1: 降低阈值配置（仅在对冲成功率>90%后生效）
reduced_min_spread_rate: Decimal = Decimal('0.06')  # 降低后的开仓阈值
reduced_profit_target_rate: Decimal = Decimal('0.02')  # 降低后的盈利目标
reduced_min_close_profit_rate: Decimal = Decimal('0.03')  # 降低后的平仓阈值
```

## 技术决策总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 对冲失败检测 | 使用现有机制，修复触发逻辑 | 机制完善，问题是执行时序 |
| 仓位平衡计算 | 统一使用绝对值计算 | 当前计算方式错误 |
| 熔断机制 | 新增safety_monitor模块 | 增强监控，多级保护 |
| Lighter订单 | 保持限价单+重试 | 问题不在订单类型 |
| 配置管理 | 新增安全+动态配置 | 支持P0/P1分阶段实现 |

## 未解决问题（需在实现中澄清）

1. **Q1**: 为什么90%的Lighter订单失败？
   - 需要详细日志分析失败原因
   - 可能需要Lighter侧的调试

2. **Q2**: 熔断机制为什么没有阻止持续开仓？
   - 需要检查`is_paused`的检查时机
   - 可能存在竞态条件

3. **Q3**: 是否需要强制平仓当前0.21 ETH vs 0.02 ETH的仓位？
   - 用户可能需要手动干预
   - 系统可以提供辅助工具

## 下一步

Phase 1: 设计阶段
- 创建data-model.md（新数据模型）
- 创建contracts/（模块接口定义）
- 创建quickstart.md（实现指南）
