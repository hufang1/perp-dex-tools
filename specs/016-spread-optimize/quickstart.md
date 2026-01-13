# Quick Start Guide: 价差套利程序优化

**Feature**: 016-spread-optimize
**Date**: 2026-01-13

## Overview

本指南提供价差套利程序优化的快速入门说明，包括开发环境设置、架构概览和实现指导。

## Prerequisites

### 环境要求

- Python 3.10+
- asyncio
- 现有项目依赖（requirements.txt）

### 知识要求

- Python异步编程（async/await）
- WebSocket基础
- DEX交易基础概念

## Project Structure

```
spread/
├── models.py                    # 数据模型（需扩展）
├── spread_arb_bot.py            # 主控制器（需修改）
├── spread_monitor.py            # [新增] 实时价差监控
├── arithmetic_open_strategy.py  # [新增] 等差数列开仓策略
├── smart_close_strategy.py      # [新增] 智能平仓系统
├── position_balance_checker.py  # [新增] 仓位平衡检测
└── logger_config.py             # [新增] 日志配置
```

## Component Overview

### 1. SpreadMonitor (实时价差监控)

**职责**:
- 订阅order_book_manager的价格更新
- 计算两个交易所的价差
- 输出单行精简日志

**接口**:
```python
class SpreadMonitor:
    async def start() -> None
    async def stop() -> None
    def get_current_spread() -> Optional[SpreadInfo]
```

**使用方式**:
```python
monitor = SpreadMonitor(order_book_manager)
await monitor.start()

# 获取当前价差
spread = monitor.get_current_spread()
if spread:
    print(spread.format_log())  # 价差: Ext[3325.5/3326.5] Lig[3320.0/3321.0] = 5.5 (0.17%)
```

### 2. ArithmeticOpenStrategy (等差数列开仓策略)

**职责**:
- 管理价差缓存状态
- 判断是否满足开仓条件
- 更新价差阈值

**接口**:
```python
class ArithmeticOpenStrategy:
    def should_open(spread: Decimal, config: BotConfig) -> bool
    def update_cached_spread(spread: Decimal, config: BotConfig) -> None
```

**使用方式**:
```python
strategy = ArithmeticOpenStrategy()

# 检查是否应该开仓
if strategy.should_open(current_spread, config):
    # 执行开仓
    await execute_open_position()
    # 更新缓存价差
    strategy.update_cached_spread(current_spread, config)
```

### 3. SmartCloseStrategy (智能平仓系统)

**职责**:
- 维护仓位组合信息
- 计算加权平均开仓价差
- 判断是否满足平仓条件

**接口**:
```python
class SmartCloseStrategy:
    def add_position(position: OpenPosition) -> None
    def should_close(current_spread: Decimal, config: BotConfig) -> CloseTrigger
    def close_position(position_id: str) -> None
    def close_all() -> List[OpenPosition]
```

**使用方式**:
```python
strategy = SmartCloseStrategy()

# 添加开仓记录
strategy.add_position(open_position)

# 检查是否应该平仓
trigger = strategy.should_close(current_spread, config)
if trigger.is_triggered:
    # 执行平仓
    await execute_close_position()
    # 更新仓位状态
    strategy.close_all()
```

### 4. PositionBalanceChecker (仓位平衡检测)

**职责**:
- 开仓后验证两边仓位
- 不平衡时触发紧急平仓

**接口**:
```python
class PositionBalanceChecker:
    async def verify_balance(ext_client, lig_client, quantity: Decimal) -> BalanceCheckResult
    async def start_monitoring(ext_client, lig_client, quantity: Decimal) -> None
    async def stop() -> None
```

**使用方式**:
```python
checker = PositionBalanceChecker(buffer_seconds=3.0)

# 启动平衡检测（异步）
await checker.start_monitoring(ext_client, lig_client, quantity)

# 或立即验证一次
result = await checker.verify_balance(ext_client, lig_client, quantity)
if not result.is_balanced:
    # 立即平仓
    await emergency_close()
```

### 5. LoggerConfig (日志配置)

**职责**:
- 配置精简的日志格式
- 设置日志级别

**使用方式**:
```python
from logger_config import setup_logging

# 配置日志
setup_logging(level=logging.INFO, compact=True)

# 使用日志
logger.info("配置: ETH|0.01|开仓0.20%|盈利0.10%|缓冲3s")
```

## Development Workflow

### 1. 开发新组件

```bash
# 创建新组件文件
cd spread/
touch spread_monitor.py

# 实现组件
vim spread_monitor.py

# 创建单元测试
mkdir -p tests/unit/
touch tests/unit/test_spread_monitor.py
```

### 2. 测试组件

```bash
# 运行单元测试
python -m pytest tests/unit/test_spread_monitor.py -v

# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/unit/test_spread_monitor.py::test_spread_calculation -v
```

### 3. 集成到主程序

```python
# 在spread_arb_bot.py中集成
from spread_monitor import SpreadMonitor
from arithmetic_open_strategy import ArithmeticOpenStrategy
from smart_close_strategy import SmartCloseStrategy
from position_balance_checker import PositionBalanceChecker

class SpreadArbBot:
    async def _init_components(self):
        # 新增组件
        self.spread_monitor = SpreadMonitor(self.order_book_manager)
        self.open_strategy = ArithmeticOpenStrategy()
        self.close_strategy = SmartCloseStrategy()
        self.balance_checker = PositionBalanceChecker(
            buffer_seconds=self.config.balance_check_buffer
        )

        await self.spread_monitor.start()

    async def _process_idle_state(self):
        # 使用新组件
        spread_info = self.spread_monitor.get_current_spread()
        if spread_info and self.open_strategy.should_open(spread_info.spread_pct, self.config):
            # 执行开仓...
```

## Configuration

### 环境变量

```bash
# .env文件
LIGHTER_ACCOUNT_INDEX=106774
LIGHTER_API_KEY_INDEX=0
API_KEY_PRIVATE_KEY=xxx
EXTENDED_VAULT=xxx
EXTENDED_STARK_KEY_PRIVATE=xxx
EXTENDED_STARK_KEY_PUBLIC=xxx
EXTENDED_API_KEY=xxx
```

### 命令行参数

```bash
# 基础运行
python -m spread.spread_arb_bot --symbol ETH --size 0.01

# 配置开仓参数
python -m spread.spread_arb_bot \
    --symbol ETH \
    --size 0.01 \
    --spread-threshold 0.002 \
    --min-profit 0.001

# 配置等差数列策略（需要扩展参数）
python -m spread.spread_arb_bot \
    --symbol ETH \
    --size 0.01 \
    --spread-step 0.0005 \
    --balance-buffer 3.0
```

### 配置文件

```python
# 创建配置
config = BotConfig(
    symbol="ETH",
    target_quantity=Decimal("0.01"),
    min_spread_threshold=Decimal("0.002"),
    spread_step=Decimal("0.0005"),
    balance_check_buffer=3.0,
    total_fee_rate=Decimal("0.0005"),
)
```

## Testing Guide

### 单元测试示例

```python
# tests/unit/test_arithmetic_open_strategy.py
import pytest
from decimal import Decimal
from spread.arithmetic_open_strategy import ArithmeticOpenStrategy
from spread.models import BotConfig

def test_first_open():
    """测试首次开仓"""
    strategy = ArithmeticOpenStrategy()
    config = BotConfig(
        symbol="ETH",
        target_quantity=Decimal("0.01"),
        min_spread_threshold=Decimal("0.002"),
        spread_step=Decimal("0.0005"),
    )

    # 首次开仓：价差 > 阈值
    assert strategy.should_open(Decimal("0.0025"), config) == True

    # 价差未达到阈值
    assert strategy.should_open(Decimal("0.0015"), config) == False

def test_subsequent_open():
    """测试后续开仓（等差数列）"""
    strategy = ArithmeticOpenStrategy()
    config = BotConfig(
        symbol="ETH",
        target_quantity=Decimal("0.01"),
        min_spread_threshold=Decimal("0.002"),
        spread_step=Decimal("0.0005"),
    )

    # 首次开仓，缓存价差0.25%
    strategy.update_cached_spread(Decimal("0.0025"), config)

    # 下次开仓需要 > 0.25% + 0.05% = 0.30%
    assert strategy.should_open(Decimal("0.0031"), config) == True
    assert strategy.should_open(Decimal("0.0029"), config) == False
```

### 集成测试示例

```python
# tests/integration/test_spread_optimization_integration.py
import pytest
from spread.spread_arb_bot import SpreadArbBot
from spread.models import BotConfig
from decimal import Decimal

@pytest.mark.asyncio
async def test_full_arbitrage_cycle():
    """测试完整套利周期"""
    config = BotConfig(
        symbol="ETH",
        target_quantity=Decimal("0.01"),
        min_spread_threshold=Decimal("0.002"),
    )

    bot = SpreadArbBot(config)
    await bot.start()

    # 验证状态转换
    assert bot.state_manager.get_state() == BotState.IDLE

    # 模拟价差变化...
    # 验证开仓...
    # 验证平仓...

    await bot.stop()
```

## Debugging

### 启用详细日志

```python
# 使用--verbose参数
python -m spread.spread_arb_bot --verbose

# 或在代码中设置
logging.basicConfig(level=logging.DEBUG)
```

### 检查WebSocket连接

```bash
# 查看订单簿日志
tail -f logs/spread_arb.log | grep "价差"

# 查看交易日志
tail -f logs/spread_arb.log | grep -E "开仓|平仓"
```

### 常见问题

1. **价差数据异常**
   - 检查WebSocket连接状态
   - 验证bid/ask价格有效性
   - 查看`SpreadMonitor.is_valid()`实现

2. **开仓不触发**
   - 检查价差阈值设置
   - 查看缓存价差状态
   - 验证`should_open()`逻辑

3. **仓位不平衡**
   - 检查交易所API响应
   - 验证缓冲期配置
   - 查看平衡检测日志

## Deployment

### 启动服务

```bash
# 前台运行（测试）
python -m spread.spread_arb_bot --symbol ETH --size 0.01

# 后台运行（生产）
nohup python -m spread.spread_arb_bot \
    --symbol ETH \
    --size 0.01 \
    > logs/bot.log 2>&1 &

# 使用systemd（推荐）
sudo systemctl start spread-arb-bot
sudo systemctl status spread-arb-bot
```

### 监控

```bash
# 查看日志
tail -f logs/spread_arb.log

# 检查状态
cat logs/spread_arb_state.json | jq .

# 查看统计
# 在bot中实现统计API或日志输出
```

## Next Steps

1. 阅读[data-model.md](./data-model.md)了解数据结构
2. 阅读[research.md](./research.md)了解设计决策
3. 查看[plan.md](./plan.md)了解实现计划
4. 等待`/speckit.tasks`生成详细任务列表
