# 快速开始：异步重构调试输出

**功能**: 011-async-ws-ioc-trading
**日期**: 2026-01-11

本文档帮助开发者快速了解异步重构的配置、调试输出和测试方法。

---

## 1. 配置参数

在 `spread/config.py` 中已添加新的配置参数：

### 性能相关

```python
# 行情处理最大延迟（毫秒，默认10ms）
max_tick_to_trade_latency_ms: float = 10.0

# 执行最大延迟（毫秒，默认300ms）
max_execution_latency_ms: float = 300.0

# 数据最大有效期（毫秒，默认500ms）
max_data_age_ms: float = 500.0

# 并发订单发送时间差阈值（毫秒，默认5ms）
concurrent_order_send_threshold_ms: float = 5.0
```

### 订单相关

```python
# 是否使用IOC订单（默认True）
use_ioc_orders: bool = True

# IOC滑点容忍度（默认0.05%）
ioc_slippage_tolerance_rate: Decimal = Decimal('0.0005')

# 订单超时时间（毫秒，默认500ms）
order_timeout_ms: int = 500

# 紧急平仓超时时间（毫秒，默认1000ms）
emergency_close_timeout_ms: int = 1000
```

### 利润与风控

```python
# 最低净利要求（默认0.02%）
min_net_profit_rate: Decimal = Decimal('0.0002')

# 预期滑点成本（默认0.01%）
expected_slippage_cost_rate: Decimal = Decimal('0.0001')

# 最大滑点警告阈值（默认0.2%）
max_slippage_warning_rate: Decimal = Decimal('0.002')

# 止损阈值（默认0.5%）
stop_loss_threshold_rate: Decimal = Decimal('0.005')

# 单腿持仓警告时间（秒，默认2秒）
single_leg_warning_seconds: int = 2
```

### 日志相关

```python
# 启用增强日志（默认True）
enable_enhanced_logging: bool = True

# 记录所有时间戳（默认True）
log_all_timestamps: bool = True

# 启用控制台高亮警告（默认True）
enable_console_warnings: bool = True
```

### 风控相关

```python
# 启用原子性风控（默认True）
enable_leg_risk_guard: bool = True

# 启用利润率检查（默认True）
enable_profitability_check: bool = True

# 启用数据新鲜度检查（默认True）
enable_data_freshness_check: bool = True
```

---

## 2. 查看调试输出

### 2.1 控制台输出

运行程序后，控制台会实时输出以下信息：

#### 性能延迟监控
```
⏱️ [行情→交易延迟] 8.45ms | 信号: 1704960123456.78ms | 发送: 1704960123465.23ms
⏱️ [执行延迟] 245.67ms | 发送: 1704960123465.23ms | ACK: 1704960123710.90ms
🔄 [并发发送] Extended→Lighter间隔: 3.21ms ✅ | 阈值: 5ms
```

#### 数据新鲜度检查
```
📡 [数据新鲜度] ✅ 新鲜 | extended | 数据年龄: 45.2ms | 阈值: 500ms
📡 [数据新鲜度] ✅ 新鲜 | lighter | 数据年龄: 52.8ms | 阈值: 500ms

# 数据过期时
🚨 [数据过期] ❌ 过期 | extended | 数据年龄: 623.5ms | 阈值: 500ms
⚠️ [数据新鲜度] 双边数据不新鲜，禁止交易 | Extended: 623.5ms, Lighter: 52.8ms
```

#### 滑点检查
```
📊 [滑点检查] ✅ 可接受 | buy | 预期价: $3000.00 | 当前价: $3001.50 | 滑点: 0.05%

# 滑点超限时
🚨 [滑点超限] ❌ 超阈值 | buy | 预期价: $3000.00 | 当前价: $3010.00 | 滑点: 0.33%

# 严重滑点警告（红色高亮）
🔴🔴🔴 [严重滑点警告] 🔴🔴🔴
   实际成交价与预期价格偏差过大!
   ❌ 超阈值 | sell | 预期价: $3000.00 | 当前价: $2940.00 | 滑点: 2.00%
   当前滑点: 2.00% > 警告阈值: 0.20%
   🔴🔴🔴
```

#### 利润率检查
```
💰 [利润检查] ✅ 可交易 | 价差率: 0.10% | 手续费: 0.04% | 预期滑点: 0.01% | 最小净利: 0.02% | 净利: 0.05%

# 利润不足时
⚠️ [利润不足] ❌ 不足利润 | 价差率: 0.07% | 净利: 0.02%
```

#### 开仓决策详情
```
======================================================================
📋 [开仓决策详情]
----------------------------------------------------------------------
🎯 套利机会:
   类型: 做多价差
   方向: buy
   价差率: 0.10%
   Extended价格: $3000.00
   Lighter价格: $3003.00

📡 数据新鲜度检查:
   ✅ 新鲜 | extended | 数据年龄: 45.2ms | 阈值: 500ms
   ✅ 新鲜 | lighter | 数据年龄: 52.8ms | 阈值: 500ms

📊 滑点检查:
   ✅ 可接受 | buy | 预期价: $3000.00 | 当前价: $3001.50 | 滑点: 0.05%

💰 利润率检查:
   ✅ 可交易 | 价差率: 0.10% | 净利: 0.05% | 决策: 允许开仓

🎯 ✅ 最终决策: 允许开仓
======================================================================
```

#### 性能统计报告（每分钟）
```
======================================================================
📊 [性能监控统计]
----------------------------------------------------------------------
数据新鲜度检查:
   总检查次数: 1250
   过期数据次数: 3
   过期率: 0.24%

延迟统计:
   平均行情→交易延迟: 8.23ms
   最大行情→交易延迟: 15.67ms
   平均执行延迟: 248.45ms
   最大执行延迟: 512.33ms
   并发发送间隔: 3.45ms

拒绝统计:
   滑点拒绝: 12 次
   利润不足拒绝: 45 次
   数据过期拒绝: 3 次

风控统计:
   对冲失败率: 2.5% (3/120)
   仓位失衡率: 1.2%
   单腿持仓次数: 1 次
======================================================================
```

### 2.2 日志文件

#### 交易日志 (`logs/trade.log`)
```text
2026-01-11 10:00:01,234 | INFO | === 交易开仓 ===
2026-01-11 10:00:01,235 | INFO | 套利对ID: 1
2026-01-11 10:00:01,236 | INFO | 方向: 做多价差
...
2026-01-11 10:00:01,710 | INFO | Extended订单已发送: order_id=ext_123
2026-01-11 10:00:01,715 | INFO | Lighter订单已发送: order_id=lit_456
```

#### 性能日志 (`logs/performance.log`)
```text
2026-01-11 10:00:01,234 | INFO | [延迟] 行情→交易: 8.45ms
2026-01-11 10:00:01,710 | INFO | [延迟] 执行: 245.67ms
2026-01-11 10:00:01,715 | INFO | [并发] 间隔: 3.21ms
```

### 2.3 CSV导出

#### 操作记录 (`data/operations_2026_01_11.csv`)
```csv
timestamp,operation_type,exchange,signal_ts,data_ts_A,data_ts_B,send_A_ts,send_B_ts,ack_A_ts,ack_B_ts,spread_rate,slippage_rate,profit_rate,decision,status,send_gap_ms
1704960123,OPEN,BOTH,1704960123456.78,1704960123411.23,1704960123404.56,1704960123465.23,1704960123468.44,1704960123710.90,1704960123715.33,0.001000,0.000500,0.000500,ALLOWED,SUCCESS,3.21
1704960189,CLOSE,BOTH,1704960189123.45,1704960189100.00,1704960189095.00,1704960189130.12,1704960189132.67,1704960189380.00,1704960189385.00,0.000200,0.000300,0.000150,ALLOWED,SUCCESS,2.55
```

#### 性能数据 (`data/performance_2026_01_11.csv`)
```csv
timestamp,tick_to_trade_latency_ms,execution_latency_ms,concurrent_gap_ms,data_age_A_ms,data_age_B_ms,slippage_rate,decision
1704960123,8.45,245.67,3.21,45.55,52.22,0.000500,ALLOWED
1704960189,6.78,249.88,2.55,23.45,28.45,0.000300,ALLOWED
```

---

## 3. 测试

### 3.1 单元测试

```bash
# 性能监控测试
pytest tests/test_performance_monitor.py -v

# WebSocket管理测试
pytest tests/test_websocket_manager.py -v

# 并发执行测试
pytest tests/test_concurrent_executor.py -v

# IOC订单测试
pytest tests/test_ioc_order_manager.py -v

# 风控验证测试
pytest tests/test_risk_validator.py -v
```

### 3.2 集成测试

```bash
# 异步交易流程测试
pytest tests/integration/test_async_trading_flow.py -v

# 时间精度测试
pytest tests/integration/test_timing_accuracy.py -v
```

### 3.3 测试覆盖

确保以下场景都有测试覆盖：
- ✅ WebSocket连接和断线重连
- ✅ 并发下单时间间隔 < 5ms
- ✅ 数据过期检测和拒绝
- ✅ 滑点超限检测和拒绝
- ✅ 利润不足检测和拒绝
- ✅ IOC订单部分成交处理
- ✅ 单腿持仓紧急平仓
- ✅ 时间戳记录完整性

---

## 4. 性能调优

### 4.1 数据收集

运行程序一段时间后，收集以下数据：

1. **CSV文件**: 从 `data/` 目录导出
2. **日志文件**: 从 `logs/` 目录提取关键信息
3. **控制台输出**: 复制性能统计报告

### 4.2 调优流程

```python
# 1. 导出性能数据
from spread.performance_monitor import PerformanceMonitor

monitor = PerformanceMonitor(config)
stats = monitor.get_stats_summary()

# 2. 分析延迟分布
latency_data = export_latency_distribution(last_n_minutes=60)

# 3. 分析滑点
slippage_data = export_slippage_analysis(last_n_minutes=60)

# 4. 分析利润率
profit_data = export_profitability_analysis(last_n_minutes=60)
```

### 4.3 参数调整

根据实际数据调整以下参数：

| 参数 | 调低 | 调高 |
|------|------|------|
| `max_data_age_ms` | 更严格检查 | 更宽松检查 |
| `ioc_slippage_tolerance_rate` | 减少滑点损失 | 增加成交概率 |
| `min_net_profit_rate` | 更多交易机会 | 更高利润保证 |
| `max_tick_to_trade_latency_ms` | 更敏感告警 | 更宽松告警 |

### 4.4 将数据提供给AI

将以下内容提供给AI分析：
- `data/performance_YYYY_MM_DD.csv`
- `data/operations_YYYY_MM_DD.csv`
- 控制台性能统计报告
- 具体问题和目标

AI将帮助：
- 识别性能瓶颈
- 分析拒绝原因分布
- 推荐参数调整
- 生成优化建议

---

## 5. 常见问题

### Q1: 为什么日志显示"数据过期"？
**A**: 订单簿数据超过 `max_data_age_ms`（默认500ms）未更新。检查：
- WebSocket连接是否稳定
- 交易所是否正常推送数据
- 网络延迟是否过高

### Q2: 为什么订单被拒绝？
**A**: 检查拒绝原因：
- "数据过期": 延迟问题
- "滑点超限": 价格跳动
- "利润不足": 价差太小
- "单腿持仓": 对冲失败

### Q3: 如何验证并发间隔？
**A**: 查看 `🔄 [并发发送]` 日志，确保间隔 < 5ms。

### Q4: CSV文件在哪里？
**A**: `data/` 目录，文件名格式为 `operations_YYYY_MM_DD.csv`。

### Q5: 如何减少滑点拒绝？
**A**: 调高 `ioc_slippage_tolerance_rate`，但会增加成交成本。

---

## 6. 下一步

1. ✅ 配置参数已设置
2. ✅ 运行程序查看调试输出
3. ✅ 收集数据和日志
4. ⏭️ 将数据提供给AI进行调优分析
