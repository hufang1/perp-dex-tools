# 快速开始指南: 优化价差套利策略

**功能**: 002-optimize-spread-arb
**日期**: 2026-01-08
**状态**: 完成

## 概述

本指南提供开发和部署优化价差套利策略的快速参考,包括环境配置、开发流程、测试方法和部署步骤。

---

## 1. 环境配置

### 1.1 系统要求

- **操作系统**: Linux / macOS
- **Python**: 3.11+
- **内存**: 最少 2GB
- **网络**: 稳定的 WebSocket 连接

### 1.2 依赖安装

```bash
# 克隆仓库
git clone <repository-url>
cd hufangperp

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt
```

### 1.3 核心依赖

```
websockets>=11.0
pytest>=7.4.0
python-dotenv>=1.0.0
```

---

## 2. 配置管理

### 2.1 环境变量配置

创建 `.env` 文件:

```bash
# 交易配置
TICKER=ETH
ORDER_QUANTITY_USDT=35

# 价差配置
MIN_SPREAD_RATE=0.0005  # 0.05%
LATENCY_BUFFER=0.0001   # 0.01%

# 平仓策略 (新增)
PROFIT_TARGET_RATE=0.0005   # 0.05% 盈利目标
TIME_CLOSE_THRESHOLD=60      # 60秒时间阈值
MAX_HOLDING_TIME=300         # 5分钟最大持仓时间

# 风险控制
MAX_OPEN_PAIRS=3
MAX_UNHEDGED_POSITIONS=0     # 0 = 禁止未对冲持仓
UNHEDGED_TIMEOUT=60          # 60秒超时
AUTO_CLOSE_UNHEDGED=false    # 谨慎启用!

# 日志配置
LOG_LEVEL=INFO
```

### 2.2 加载配置

```python
from spread.config import SpreadArbConfig
from dotenv import load_dotenv
import os

# 加载 .env 文件
load_dotenv()

# 从环境变量创建配置
config = SpreadArbConfig.from_env()

# 或使用默认配置
config = SpreadArbConfig()
```

---

## 3. 开发流程

### 3.1 项目结构

```text
spread/                    # 主要代码目录
├── bot.py                 # 主引擎 (修改重点)
├── spread_pair.py         # 套利对模型 (新增字段)
├── config.py              # 配置类 (新增参数)
├── order_manager.py       # 订单管理 (增强日志)
├── hedge_manager.py       # 对冲管理 (失败处理)
└── calculator.py          # 价差计算 (阈值调整)

tests/                     # 测试目录
├── test_spread_pair.py    # 新增
├── test_config.py         # 新增
└── integration/
    └── test_closing_strategy.py  # 新增
```

### 3.2 开发步骤

#### 步骤 1: 更新配置类

修改 `spread/config.py`:

```python
@dataclass
class SpreadArbConfig:
    # ... 现有配置 ...

    # 新增: 平仓策略配置
    profit_target_rate: Decimal = Decimal('0.0005')     # 0.05%
    time_close_threshold: int = 60                      # 秒
    max_holding_time: int = 300                         # 5分钟

    # 新增: 未对冲持仓配置
    unhedged_position_timeout: int = 60                 # 秒

    @classmethod
    def from_env(cls) -> 'SpreadArbConfig':
        """从环境变量加载"""
        return cls(
            profit_target_rate=Decimal(os.getenv('PROFIT_TARGET_RATE', '0.0005')),
            time_close_threshold=int(os.getenv('TIME_CLOSE_THRESHOLD', '60')),
            max_holding_time=int(os.getenv('MAX_HOLDING_TIME', '300')),
            unhedged_position_timeout=int(os.getenv('UNHEDGED_TIMEOUT', '60')),
            # ... 其他配置 ...
        )
```

#### 步骤 2: 增强套利对模型

修改 `spread/spread_pair.py`:

```python
class SpreadPair:
    def __init__(self, ...):
        # ... 现有字段 ...

        # 新增: 订单ID记录
        self.open_extended_order_id: Optional[str] = None
        self.open_lighter_order_id: Optional[str] = None
        self.close_extended_order_id: Optional[str] = None
        self.close_lighter_order_id: Optional[str] = None
```

#### 步骤 3: 改进平仓决策

修改 `spread/bot.py` 中的 `_check_force_close()`:

```python
def _check_force_close(self, pair, current_extended, current_lighter):
    unrealized_pnl = pair.calculate_unrealized_pnl(current_extended, current_lighter)
    holding_time = pair.holding_time

    # 1. 盈利目标 (最高优先级)
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

#### 步骤 4: 增强日志记录

修改开仓和平仓的日志输出:

```python
# 开仓日志
self.logger.info(
    f"✅ 开仓成功! 套利对 #{pair.pair_id}: "
    f"{pair.extended_side.upper()} {pair.extended_quantity:.4f} "
    f"Extended@{pair.extended_price:.2f} (订单ID: {order['order_id']}) "
    f"Lighter@{pair.lighter_price:.2f} (订单ID: {hedge_result['order_id']}) "
    f"开仓价差: ${pair.open_spread:.2f} ({pair.open_spread_rate:.4%})"
)

# 平仓日志
self.logger.info(
    f"💰 平仓成功! 套利对 #{pair.pair_id}: "
    f"盈亏 ${profit:.2f} "
    f"持仓 {pair.holding_time:.0f}秒 "
    f"Extended@{pair.close_extended_price:.2f} "
    f"Lighter@{pair.close_lighter_price:.2f}"
)
```

---

## 4. 测试

### 4.1 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_spread_pair.py -v

# 运行特定测试用例
pytest tests/test_spread_pair.py::test_calculate_unrealized_pnl -v

# 生成覆盖率报告
pytest tests/ --cov=spread --cov-report=html
open htmlcov/index.html
```

### 4.2 编写测试

**单元测试示例** (`tests/test_spread_pair.py`):

```python
import pytest
from decimal import Decimal
from spread.spread_pair import SpreadPair

def test_calculate_unrealized_pnl_buy():
    """测试买入方向的盈亏计算"""
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 当前价格: Extended涨, Lighter跌 (盈利)
    pnl = pair.calculate_unrealized_pnl(
        current_extended_price=Decimal('2501.00'),
        current_lighter_price=Decimal('2500.25')
    )

    assert pnl > 0
    assert abs(pnl - Decimal('1.75')) < Decimal('0.01')

def test_close_pair():
    """测试平仓流程"""
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    realized_pnl = pair.close(
        close_extended_price=Decimal('2501.00'),
        close_lighter_price=Decimal('2500.25')
    )

    assert pair.is_closed
    assert pair.realized_pnl == realized_pnl
    assert pair.close_time is not None
```

**配置测试示例** (`tests/test_config.py`):

```python
import pytest
from decimal import Decimal
from spread.config import SpreadArbConfig

def test_default_config():
    """测试默认配置"""
    config = SpreadArbConfig()
    assert config.min_spread_rate == Decimal('0.0005')
    assert config.profit_target_rate == Decimal('0.0005')
    assert config.time_close_threshold == 60
    assert config.max_holding_time == 300

def test_config_validation():
    """测试配置验证"""
    with pytest.raises(ValueError):
        SpreadArbConfig(min_spread_rate=Decimal('-0.001'))

    with pytest.raises(AssertionError):
        SpreadArbConfig(
            min_spread_rate=Decimal('0.0001'),
            latency_buffer=Decimal('0.0002')  # 大于 min_spread_rate
        )
```

**集成测试示例** (`tests/integration/test_closing_strategy.py`):

```python
import pytest
from decimal import Decimal
from spread.bot import SpreadArbitrageBot
from spread.config import SpreadArbConfig

@pytest.mark.asyncio
async def test_profit_target_closing():
    """测试盈利目标平仓"""
    config = SpreadArbConfig(
        profit_target_rate=Decimal('0.0005'),
        time_close_threshold=60
    )
    # ... 创建测试环境 ...
    # ... 验证盈利目标触发平仓 ...

@pytest.mark.asyncio
async def test_time_based_closing():
    """测试时间小额平仓"""
    config = SpreadArbConfig(
        profit_target_rate=Decimal('0.001'),  # 较高目标
        time_close_threshold=60
    )
    # ... 验证60秒后小额利润平仓 ...
```

### 4.3 测试覆盖率目标

- 核心逻辑: >= 90%
- 配置类: >= 80%
- 整体: >= 85%

---

## 5. 运行

### 5.1 本地运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行套利机器人
python spread/bot.py \
    --ticker ETH \
    --size 35 \
    --max-pairs 3 \
    --log-level INFO
```

### 5.2 生产部署

**使用 systemd**:

创建 `/etc/systemd/system/spread-arb.service`:

```ini
[Unit]
Description=Spread Arbitrage Bot
After=network.target

[Service]
Type=simple
User=<username>
WorkingDirectory=/path/to/hufangperp
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python spread/bot.py \
    --ticker ETH \
    --size 35 \
    --max-pairs 3
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务:

```bash
sudo systemctl daemon-reload
sudo systemctl enable spread-arb
sudo systemctl start spread-arb
sudo systemctl status spread-arb
```

**使用 Docker** (可选):

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "spread/bot.py", "--ticker", "ETH", "--size", "35"]
```

```bash
docker build -t spread-arb .
docker run -d --name spread-arb \
    -e TICKER=ETH \
    -e ORDER_QUANTITY_USDT=35 \
    -e PROFIT_TARGET_RATE=0.0005 \
    spread-arb
```

---

## 6. 监控

### 6.1 日志监控

```bash
# 实时查看日志
tail -f spread_arb.log

# 过滤关键事件
grep "✅ 开仓成功" spread_arb.log
grep "💰 平仓成功" spread_arb.log
grep "🚨 检测到" spread_arb.log
```

### 6.2 性能指标

关键指标:
- 订单处理延迟 < 100ms
- WebSocket 消息延迟 < 50ms
- 单边持仓检测 < 60秒
- 平均持仓时间 < 120秒

### 6.3 告警规则

建议监控告警:
- 连续 3 次开仓失败
- 未对冲持仓 > 0
- 对冲失败率 > 30%
- 持仓时间 > 5分钟

---

## 7. 调优指南

### 7.1 价差阈值调优

根据手续费调整:
```bash
# 保守策略 (低频, 高利润)
MIN_SPREAD_RATE=0.0008  # 0.08%

# 平衡策略 (中频, 中利润)
MIN_SPREAD_RATE=0.0005  # 0.05%

# 激进策略 (高频, 低利润)
MIN_SPREAD_RATE=0.0003  # 0.03%
```

### 7.2 平仓策略调优

```bash
# 快速周转
PROFIT_TARGET_RATE=0.0003   # 0.03%
TIME_CLOSE_THRESHOLD=30      # 30秒

# 平衡策略
PROFIT_TARGET_RATE=0.0005   # 0.05%
TIME_CLOSE_THRESHOLD=60      # 60秒

# 等待更好价格
PROFIT_TARGET_RATE=0.001    # 0.1%
TIME_CLOSE_THRESHOLD=120     # 120秒
```

---

## 8. 故障排除

### 8.1 常见问题

**问题**: 单边持仓累积
- **原因**: Lighter 连接中断或流动性不足
- **解决**: 检查 Lighter WebSocket 状态, 调整深度检查参数

**问题**: 平仓不及时
- **原因**: 监控循环间隔过长
- **解决**: 调整 `_monitor_pairs()` 的 sleep 时间

**问题**: 交易频率低
- **原因**: 价差阈值过高
- **解决**: 降低 `MIN_SPREAD_RATE` 值

### 8.2 日志级别

```bash
# 开发环境 (详细信息)
LOG_LEVEL=DEBUG

# 生产环境 (关键事件)
LOG_LEVEL=INFO

# 故障排查 (全部日志)
LOG_LEVEL=DEBUG
```

---

## 9. 检查清单

### 开发前
- [ ] Python 3.11+ 已安装
- [ ] 虚拟环境已创建
- [ ] 依赖已安装
- [ ] `.env` 文件已配置

### 开发中
- [ ] 配置类已更新
- [ ] 数据模型已增强
- [ ] 平仓逻辑已改进
- [ ] 日志记录已完善

### 测试
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 覆盖率 >= 85%

### 部署
- [ ] 环境变量已设置
- [ ] systemd/Docker 配置就绪
- [ ] 日志监控已启用
- [ ] 告警规则已配置

---

## 10. 参考文档

- [功能规格说明](./spec.md)
- [实现计划](./plan.md)
- [技术调研](./research.md)
- [数据模型](./data-model.md)
- [项目 CLAUDE.md](../../CLAUDE.md)

---

## 总结

本快速开始指南提供了开发、测试、部署价差套利策略优化的完整流程。遵循本指南可以:
1. ✅ 快速搭建开发环境
2. ✅ 理解核心修改点
3. ✅ 编写有效测试
4. ✅ 安全部署到生产
