# 011-async-ws-ioc-trading Feature Implementation Summary

## Overview
异步重构：使用WebSocket实时行情和IOC订单实现高频价差套利

## Key Features Implemented

### 1. Performance Monitoring (performance_monitor.py)
- **时间戳记录**: 记录signal → data → calc → send → ACK完整时间链
- **数据新鲜度检查**: 验证订单簿数据年龄（默认500ms阈值）
- **滑点检查**: 验证实际滑点是否在容忍范围内（默认0.05%）
- **利润率验证**: 计算净利润率（价差 - 手续费 - 预期滑点）
- **CSV导出**:
  - `export_performance_data()`: 导出延迟数据
  - `export_decision_records()`: 导出决策记录
  - `export_latency_distribution()`: 延迟分布统计
  - `export_slippage_analysis()`: 滑点分析
  - `export_profitability_analysis()`: 利润率分析

### 2. WebSocket Manager (websocket_manager.py)
- **双交易所连接**: 同时连接Extended和Lighter WebSocket
- **订单簿订阅**: 实时接收订单簿更新
- **时间戳跟踪**: 记录每次更新的时间戳用于数据新鲜度检查
- **自动重连**: 连接断开时自动重连
- **心跳机制**: 定期ping/pong保持连接

### 3. Concurrent Executor (concurrent_executor.py)
- **并发下单**: 使用asyncio.gather同时发送双边订单
- **间隔追踪**: 测量双边订单发送时间差（目标<5ms）
- **超时控制**: 订单超时处理（默认500ms）
- **紧急平仓**: 单边失败时紧急平仓（默认1000ms超时）

### 4. IOC Order Manager (ioc_order_manager.py)
- **IOC订单创建**: 创建Immediate-Or-Cancel订单
- **激进定价**:
  - 买入: base_price * (1 + slippage_tolerance)
  - 卖出: base_price * (1 - slippage_tolerance)
- **部分成交处理**: 处理IOC订单的部分成交情况
- **交易所适配**: Extended使用camelCase，Lighter使用snake_case

### 5. Risk Validator (risk_validator.py)
- **开仓前验证**:
  - 数据新鲜度检查
  - 滑点阈值检查
  - 利润率验证
- **单腿风险守护**: 检测并处理单边成交情况
- **综合决策**: 整合所有验证结果给出最终决策

### 6. Bot Integration (bot.py)
- **时间戳记录**: 在策略循环和开仓函数中记录关键时间戳
- **TradeOperationRecord**: 创建完整的操作记录用于CSV导出
- **数据新鲜度检查**: 开仓前验证订单簿数据新鲜度
- **CSV导出**: 清理时导出性能数据和决策记录

## Configuration Parameters

```python
# Performance
max_tick_to_trade_latency_ms: float = 10.0      # 行情到交易延迟阈值
max_execution_latency_ms: float = 300.0          # 执行延迟阈值
max_data_age_ms: float = 500.0                   # 数据新鲜度阈值
concurrent_order_send_threshold_ms: float = 5.0  # 并发发送间隔阈值

# IOC Orders
use_ioc_orders: bool = True                      # 启用IOC订单
ioc_slippage_tolerance_rate: Decimal = 0.0005   # IOC滑点容忍度（0.05%）
order_timeout_ms: int = 500                     # 订单超时时间
emergency_close_timeout_ms: int = 1000          # 紧急平仓超时

# Profit & Risk
min_net_profit_rate: Decimal = 0.0002           # 最小净利润率（0.02%）
expected_slippage_cost_rate: Decimal = 0.0001   # 预期滑点成本（0.01%）
max_slippage_warning_rate: Decimal = 0.002      # 最大滑点警告（0.2%）
stop_loss_threshold_rate: Decimal = 0.005       # 止损阈值（0.5%）

# Logging & Risk Control
enable_enhanced_logging: bool = True             # 启用增强日志
log_all_timestamps: bool = True                  # 记录所有时间戳
enable_console_warnings: bool = True             # 启用控制台警告
enable_leg_risk_guard: bool = True               # 启用单腿风险守护
enable_profitability_check: bool = True          # 启用利润率检查
enable_data_freshness_check: bool = True         # 启用数据新鲜度检查
```

## Data Models

### TradeOperationRecord
记录完整的交易操作时间戳链和结果：
- `timestamp`: 记录时间戳
- `operation_type`: 操作类型（OPEN, CLOSE, EMERGENCY_CLOSE）
- `exchange`: 交易所（BOTH, EXTENDED, LIGHTER）
- `signal_ts`: 策略信号触发时间
- `data_ts_A/B`: Extended/Lighter数据时间
- `calc_ts`: 计算完成时间
- `send_A/B_ts`: Extended/Lighter发送时间
- `ack_A/B_ts`: Extended/Lighter ACK时间
- `spread_rate`: 价差率
- `slippage_rate`: 实际滑点率
- `profit_rate`: 利润率
- `decision`: 决策（ALLOWED, REJECTED）
- `status`: 状态（SUCCESS, FAILED, PARTIAL）
- `reason`: 失败原因

### Other Models
- `OrderBookSnapshot`: 订单簿快照
- `TimingRecord`: 时间戳记录
- `DataFreshnessResult`: 数据新鲜度检查结果
- `SlippageCheckResult`: 滑点检查结果
- `ProfitabilityCheckResult`: 利润率检查结果

## CSV Export Files

### performance_YYYY_MM_DD.csv
性能指标数据：
- tick_to_trade_latency_ms
- execution_latency_ms
- concurrent_gap_ms

### operations_YYYY_MM_DD.csv
交易决策记录：
- 完整时间戳链
- 操作类型和结果
- 价差和滑点数据
- 决策理由

## Unit Tests (73 tests)

- `test_performance_monitor.py` (27 tests)
- `test_ioc_order_manager.py` (16 tests)
- `test_risk_validator.py` (16 tests)
- `test_concurrent_executor.py` (14 tests)

## Integration Tests (43 tests passing)

- `test_concurrent_orders_integration.py`: 并发下单集成测试
- `test_risk_validation_integration.py`: 风险验证集成测试
- `test_performance_monitoring_integration.py`: 性能监控集成测试

## Usage Example

```python
from spread.bot import SpreadArbitrageBot
from spread.config import SpreadArbConfig

# 配置
config = SpreadArbConfig(
    ticker='ETH',
    size=35,
    max_pairs=3,
    enable_data_freshness_check=True,
    use_ioc_orders=True
)

# 创建并启动机器人
bot = SpreadArbitrageBot(config)
await bot.run()

# 清理时自动导出CSV
# - data/performance_YYYY_MM_DD.csv
# - data/operations_YYYY_MM_DD.csv
```

## Key Improvements

1. **实时性**: WebSocket替代12秒HTTP轮询，延迟从>10s降至<10ms
2. **并发性**: asyncio.gather实现双边订单同时发送，间隔<5ms
3. **可控性**: IOC订单保证立即成交或取消，避免挂单风险
4. **可观测性**: 完整时间戳链和CSV导出，支持性能分析和复盘
5. **安全性**: 数据新鲜度检查、滑点验证、利润率检查、单腿风险守护

## Files Created/Modified

### New Files (011 feature)
- `spread/performance_monitor.py`
- `spread/websocket_manager.py`
- `spread/concurrent_executor.py`
- `spread/ioc_order_manager.py`
- `spread/risk_validator.py`
- `spread/models.py` (新增6个dataclass)

### Modified Files
- `spread/config.py` (新增18个配置参数)
- `spread/bot.py` (集成011模块)
- `tests/test_performance_monitor.py`
- `tests/test_ioc_order_manager.py`
- `tests/test_risk_validator.py`
- `tests/test_concurrent_executor.py`
- `tests/integration/test_concurrent_orders_integration.py`
- `tests/integration/test_risk_validation_integration.py`
- `tests/integration/test_performance_monitoring_integration.py`

## Next Steps

1. 完善WebSocket集成测试（当前有实现差异）
2. 添加更多性能监控指标
3. 优化CSV导出性能
4. 添加延迟报警机制
