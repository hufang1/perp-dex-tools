# Research: 价差套利程序优化

**Feature**: 016-spread-optimize
**Date**: 2026-01-13

## Overview

本文档记录了价差套利程序优化的研究过程和设计决策。

## Research Topics

### 1. 日志优化最佳实践

**研究问题**: 如何在保持关键信息的同时减少日志输出量？

**分析**:
- 当前程序使用Python标准logging模块，输出大量INFO级别日志
- 用户要求精简为单行关键信息
- 需要保留的关键信息：API验证、价差状态、交易决策、仓位平衡

**决策**:
1. 创建新的`logger_config.py`模块，配置精简的日志格式
2. 将非关键日志从INFO降级到DEBUG
3. 关键信息使用单行紧凑格式输出
4. 启动时输出配置摘要单行：`配置: ETH|0.01|开仓0.20%|盈利0.10%|缓冲3s`

**替代方案考虑**:
- 使用结构化日志（JSON格式）: 增加了机器可读性但降低了人类可读性
- 完全禁用INFO日志: 过于极端，用户无法监控运行状态

### 2. 等差数列开仓策略

**研究问题**: 如何实现价差扩大时的分批建仓策略？

**分析**:
- 当前`spread_calculator.py`使用单一阈值判断是否开仓
- 需要缓存上次开仓时的价差，并按step递增
- 价差缩小时不应降低阈值
- 需要防止价差波动时的频繁开仓

**决策**:
1. 创建独立的`arithmetic_open_strategy.py`类
2. 在`BotConfig`中添加新字段：
   - `cached_open_spread`: 缓存的开仓价差
   - `spread_step`: 价差步进值（默认0.05%）
3. 开仓逻辑：
   - 首次：`spread > min_threshold` → 开仓，缓存spread
   - 后续：`spread > cached + step` → 开仓，更新cached
4. 价差缩小时保持cached不变

**替代方案考虑**:
- 使用固定多个阈值（0.2%, 0.3%, 0.4%）: 不够灵活
- 使用动态阈值（基于波动率）: 复杂度高，不符合用户简单等差数列需求

### 3. Taker vs Maker交易模式

**研究问题**: 如何将现有的maker模式改造为taker模式？

**分析**:
- `exchanges/extended.py`中`place_open_order`使用`post_only=True`
- maker模式可能导致订单未成交，影响套利策略
- 用户明确要求统一使用taker模式

**决策**:
1. 修改`trade_executor.py`中的开仓逻辑
2. Extended交易所：
   - 买入：使用ask价格（略高于当前best_ask）
   - 卖出：使用bid价格（略低于当前best_bid）
   - 移除`post_only=True`参数
3. Lighter交易所：
   - 检查`place_limit_order`实现
   - 使用对手价确保即时成交

**替代方案考虑**:
- 保持maker模式但增加重试逻辑: 仍然可能失败
- 混合模式（部分taker部分maker）: 增加复杂度

### 4. 仓位平衡验证机制

**研究问题**: 如何在开仓后验证两边仓位是否平衡？

**分析**:
- 需要在开仓后等待配置的缓冲期（默认3秒）
- 验证两个交易所的仓位数量是否相等
- 不平衡时需要立即平仓保护

**决策**:
1. 创建独立的`position_balance_checker.py`类
2. 在`BotConfig`中添加：
   - `balance_check_buffer`: 缓冲期秒数（默认3）
3. 验证流程：
   - 开仓后启动异步任务，等待缓冲期
   - 定期轮询两个交易所的仓位
   - 如发现不平衡，触发紧急平仓
   - 平衡后更新状态为HOLDING

**替代方案考虑**:
- 通过WebSocket订单更新验证: 可能有延迟，不够可靠
- 只验证一次（不轮询）: 可能错过中间状态变化

### 5. 价差计算和实时监控

**研究问题**: 如何增强实时价差监控并输出单行日志？

**分析**:
- 当前`order_book_manager.py`已经监听WebSocket
- 当前`spread_calculator.py`已有价差计算逻辑
- 需要新增实时监控输出

**决策**:
1. 创建独立的`spread_monitor.py`组件
2. 订阅`order_book_manager`的价格更新
3. 计算价差后输出单行日志：
   ```
   价差: Ext[3325.5/3326.5] Lig[3320.0/3321.0] = 5.5 (0.17%)
   ```
4. 异常情况输出ERROR但继续运行

**替代方案考虑**:
- 在主循环中定期检查: 延迟较高
- 使用独立线程: asyncio已有异步机制，不需要

### 6. 智能平仓系统

**研究问题**: 如何实现基于总仓位的智能平仓？

**分析**:
- 需要计算所有仓位的加权平均开仓价差
- 平仓条件：`entry_spread >= current_spread + profit_target + fees`
- 当前平仓逻辑在主循环中，需要独立出来

**决策**:
1. 创建独立的`smart_close_strategy.py`类
2. 维护总仓位信息：
   - 总开仓价差（加权平均）
   - 各个分笔仓位
3. 平仓触发检查：
   - 实时监控当前价差
   - 判断是否满足平仓条件
   - 满足时触发平仓

**替代方案考虑**:
- 使用当前单一仓位逻辑: 不支持等差数列分批建仓
- 使用期权对冲: 增加复杂度，不符合需求

## Data Model Changes

需要在`models.py`中添加的字段：

```python
class BotConfig:
    # 新增字段
    cached_open_spread: Decimal = Decimal("0")  # 缓存的开仓价差
    spread_step: Decimal = Decimal("0.0005")    # 价差步进值 0.05%
    balance_check_buffer: float = 3.0           # 仓位平衡检测缓冲期（秒）
    total_fee_rate: Decimal = Decimal("0.0005") # 总手续费率 0.05%

class Position:
    # 可能需要扩展以支持多笔仓位
    # 或者创建新的Portfolio类管理多笔仓位
```

## Component Architecture

```
spread_arb_bot.py (主控制器)
    ├── spread_monitor.py (实时价差监控)
    ├── arithmetic_open_strategy.py (等差数列开仓)
    ├── smart_close_strategy.py (智能平仓)
    ├── position_balance_checker.py (仓位平衡检测)
    ├── logger_config.py (日志配置)
    ├── order_book_manager.py (订单簿管理 - 现有)
    ├── spread_calculator.py (价差计算 - 现有)
    ├── trade_executor.py (交易执行 - 现有)
    ├── state_manager.py (状态管理 - 现有)
    └── risk_manager.py (风控管理 - 现有)
```

## Testing Strategy

1. **单元测试**: 每个新组件独立测试
   - `test_spread_monitor.py`: 价差计算和日志输出
   - `test_arithmetic_open_strategy.py`: 开仓逻辑和缓存
   - `test_smart_close_strategy.py`: 平仓触发条件
   - `test_position_balance_checker.py`: 平衡检测逻辑

2. **集成测试**: 完整流程测试
   - 模拟WebSocket价格更新
   - 模拟交易所响应
   - 验证端到端流程

3. **回测**: 使用历史数据验证策略
   - 模拟价差波动
   - 验证开仓和平仓时机

## Performance Considerations

1. **价差监控延迟**: WebSocket订阅后立即处理，延迟<50ms
2. **开仓决策**: 价差计算+策略判断，延迟<100ms
3. **仓位平衡检查**: 缓冲期内异步轮询，不阻塞主流程
4. **内存使用**: 缓存价差和仓位信息，内存占用<1MB

## Security & Risk

1. **API密钥管理**: 继续使用环境变量
2. **状态文件**: JSON格式，需添加校验和备份
3. **异常处理**: 所有新增组件需要try-catch
4. **资金安全**: 仓位不平衡时立即平仓保护

## Open Questions

无 - 所有设计决策已确定

## Next Steps

1. 创建`data-model.md`详细定义数据结构
2. 创建`quickstart.md`提供开发指南
3. 等待`/speckit.tasks`生成任务列表
