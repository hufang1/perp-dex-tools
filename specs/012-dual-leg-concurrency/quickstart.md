# 快速开始：双腿并发交易重构

**分支**: `012-dual-leg-concurrency` | **日期**: 2026-01-11

## 概述

本文档提供双腿并发交易功能的快速入门指南，包括配置、运行和验证步骤。

## 前置条件

1. **Python环境**: Python 3.11+
2. **依赖安装**: `pip install -r requirements.txt`
3. **交易所账户**: Extended和Lighter交易所账户（测试环境优先）
4. **费率确认**: 双边Taker费率总和必须 < 0.05%

## 安装步骤

### 1. 配置检查

编辑 `spread/config.py`，确认以下配置：

```python
# 并发执行配置
config.enable_dual_leg_concurrent = True
config.concurrent_order_send_threshold_ms = 5.0

# IOC订单配置
config.ioc_slippage_tolerance_rate = Decimal('0.0005')  # 0.05%

# 单腿回滚配置
config.enable_leg_rollback = True
config.rollback_timeout_ms = 500.0

# 极简平仓配置
config.enable_simple_close = True
config.simple_close_target_profit_rate = Decimal('0.0002')  # 0.02%

# 利润检查配置
config.enable_enhanced_profit_check = True
config.min_net_profit_rate = Decimal('0.0002')  # 0.02%
```

### 2. 费率验证

```python
# 检查您的费率配置
extended_taker_fee = config.extended_taker_fee_rate
lighter_taker_fee = config.lighter_fee_rate
total_fees = extended_taker_fee + lighter_taker_fee

if total_fees > Decimal('0.0006'):
    print(f"⚠️ 警告: 双边费率总和 {total_fees:.4%} > 0.06%, 策略可能无法盈利")
```

### 3. 新增模块

确保以下模块文件存在：

```bash
spread/leg_rollback_handler.py      # [新增]
spread/simple_close_strategy.py     # [新增]
```

## 运行指南

### 测试环境运行

```bash
# 1. 运行单元测试
pytest tests/test_dual_leg_concurrent.py -v
pytest tests/test_leg_rollback.py -v
pytest tests/test_profit_check.py -v

# 2. 运行集成测试
pytest tests/integration/test_dual_leg_integration.py -v

# 3. 验证性能指标
pytest tests/test_performance_targets.py -v
```

### 模拟交易运行

```bash
# 使用模拟模式运行（不发送真实订单）
python spread/bot.py --ticker ETH --size 35 --max-pairs 3 --dry-run
```

### 实盘运行（仅测试环境）

```bash
# ⚠️ 警告: 仅在确认以下条件后运行实盘
# 1. 所有测试通过
# 2. 性能指标满足要求
# 3. 费率确认 < 0.05%
# 4. 已完成模拟交易验证

python spread/bot.py --ticker ETH --size 35 --max-pairs 3
```

## 验证清单

### 性能验证

| 指标 | 目标 | 验证方法 |
|------|------|----------|
| 并发发送时间差 | < 5ms | 查看 logs/performance.log |
| 总执行时间 | < 500ms | 查看 logs/performance.log |
| 单腿回滚延迟 | < 1s | 模拟单腿持仓场景 |

### 日志检查

```bash
# 查看交易日志
tail -f logs/trade.log

# 查看性能日志
tail -f logs/performance.log

# 查找并发发送记录
grep "并发发送" logs/performance.log

# 查找回滚记录
grep "CRITICAL.*Legging" logs/trade.log
```

### 数据导出

```python
# 导出性能数据
from spread.performance_monitor import PerformanceMonitor

monitor = PerformanceMonitor(config)
monitor.export_performance_data(last_n_minutes=60)
# 输出: data/performance_YYYY_MM_DD.csv

# 导出决策记录
monitor.export_decision_records(last_n_minutes=60)
# 输出: data/operations_YYYY_MM_DD.csv
```

## 故障排查

### 问题1: 并发发送时间差 > 5ms

**可能原因**:
- 网络延迟
- CPU负载过高
- asyncio事件循环阻塞

**解决方案**:
```bash
# 检查系统负载
top

# 检查网络延迟
ping exchange.extended.com

# 检查asyncio任务
# 在代码中添加调试日志
```

### 问题2: IOC订单被拒

**可能原因**:
- 滑点容错设置过小
- 价格跳变剧烈
- 流动性不足

**解决方案**:
```python
# 增加滑点容错
config.ioc_slippage_tolerance_rate = Decimal('0.0005')  # 增加到0.05%

# 检查订单簿深度
# 在下单前验证bid/ask数量是否足够
```

### 问题3: 单腿回滚失败

**可能原因**:
- 网络连接中断
- 交易所API错误
- 账户余额不足

**解决方案**:
```python
# 检查网络连接
# 验证账户余额
# 启用回滚重试

config.rollback_max_retries = 3  # 增加重试次数
```

### 问题4: 利润检查拒绝所有交易

**可能原因**:
- 费率设置过高
- min_net_profit设置过高
- 价差率确实太小

**解决方案**:
```python
# 检查利润计算
result = monitor.check_profitability(spread_rate)
print(f"净利: {result.net_profit_rate:.4%}")

# 调整最低净利要求
config.min_net_profit_rate = Decimal('0.0001')  # 降低到0.01%
```

## 监控指标

### 关键指标

```python
# 在代码中添加性能监控
monitor = PerformanceMonitor(config)

# 记录并发发送间隔
monitor.record_concurrent_send_gap(send_a_ts, send_b_ts)

# 记录数据新鲜度
monitor.check_data_freshness('extended', orderbook_ts)

# 记录利润检查
monitor.check_profitability(spread_rate)
```

### 告警阈值

| 指标 | 告警阈值 | 严重阈值 |
|------|----------|----------|
| 并发发送时间差 | > 5ms | > 10ms |
| 总执行时间 | > 500ms | > 1000ms |
| 单腿回滚延迟 | > 1s | > 2s |
| 数据年龄 | > 500ms | > 1000ms |

## 下一步

1. **完成Phase 2任务分解**: 运行 `/speckit.tasks`
2. **实施开发**: 按任务顺序开发功能
3. **编写测试**: 单元测试 + 集成测试
4. **性能测试**: 验证延迟目标
5. **模拟交易**: 验证策略效果
6. **实盘部署**: 确认后部署到测试环境

## 相关文档

- [功能规格](./spec.md): 详细功能需求
- [实现计划](./plan.md): 技术实现方案
- [数据模型](./data-model.md): 数据结构设计
- [API契约](./contracts/api.md): 接口定义
- [研究文档](./research.md): 技术研究结果
