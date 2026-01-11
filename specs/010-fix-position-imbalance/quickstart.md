# Quickstart Guide: 修复仓位失衡和优化开仓标准

**Feature**: 010-fix-position-imbalance
**Date**: 2026-01-11
**Status**: Phase 1 Design Complete

## 概述

本指南提供修复仓位失衡和优化开仓标准的实现路径。

## 实现优先级

### P0 - 关键安全（必须立即修复）

**目标**: 修复Extended 0.21 ETH vs Lighter 0.02 ETH的严重失衡问题

**估计工作量**: 4-6小时

### P1 - 核心功能（在对冲成功率>90%后实现）

**目标**: 降低开仓阈值，增加交易频率

**估计工作量**: 2-3小时

### P2 - 优化功能（最后实现）

**目标**: 优化平仓策略，加快资金周转

**估计工作量**: 1-2小时

## P0 实现步骤

### 步骤1: 修复仓位平衡计算（30分钟）

**文件**: `spread/models.py`

**任务**:
1. 修改`PositionBalance.__post_init__`方法
2. 使用绝对值计算`diff_rate`
3. 更新`warning_level`判断逻辑

**代码变更**:
```python
# spread/models.py 第98-120行

def __post_init__(self):
    """计算仓位平衡状态"""
    # 使用绝对值计算总暴露度
    total_exposure = abs(self.extended_total_qty) + abs(self.lighter_total_qty)

    # 计算实际差异（绝对值之间的差异）
    actual_diff_qty = abs(abs(self.extended_total_qty) - abs(self.lighter_total_qty))

    # 计算差异率
    if total_exposure > 0:
        self.diff_rate = actual_diff_qty / total_exposure
    else:
        self.diff_rate = Decimal('0')

    # 判断失衡级别
    if self.diff_rate >= Decimal('0.5'):  # 50%以上
        self.warning_level = 'CRITICAL'
    elif self.diff_rate >= Decimal('0.1'):  # 10%以上
        self.warning_level = 'WARN'
    else:
        self.warning_level = 'OK'

    self.is_imbalanced = self.warning_level != 'OK'
```

**测试**:
```bash
pytest tests/test_position_balance_fix.py -v
```

### 步骤2: 创建SafetyMonitor模块（2小时）

**文件**: `spread/safety_monitor.py`

**任务**:
1. 实现`SafetyMonitor`类
2. 实现对冲失败率追踪
3. 实现仓位失衡率计算
4. 实现熔断器逻辑

**基本结构**:
```python
# spread/safety_monitor.py

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Tuple, Optional
import logging
import time
from .config import SpreadArbConfig
from .models import SafetyState

class SafetyMonitor:
    """安全监控器"""

    def __init__(self, config: SpreadArbConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.state = SafetyState()
        self.failure_tracking: List[Dict] = []

    async def record_hedge_attempt(self, success: bool, failure_reason: Optional[str] = None):
        """记录对冲尝试"""
        # 更新滑动窗口
        # 更新统计
        # 检查熔断条件
        pass

    def get_hedge_failure_rate(self) -> Decimal:
        """获取对冲失败率"""
        pass

    def check_circuit_breaker(self) -> Tuple[int, str]:
        """检查熔断器"""
        pass

    def should_pause_opening(self) -> bool:
        """检查是否应该暂停开仓"""
        pass

    def update_position_imbalance(self, extended_qty: Decimal, lighter_qty: Decimal):
        """更新仓位失衡率"""
        pass
```

**测试**:
```bash
pytest tests/test_safety_monitor.py -v
```

### 步骤3: 集成SafetyMonitor到Bot（1.5小时）

**文件**: `spread/bot.py`

**任务**:
1. 在`__init__`中初始化`safety_monitor`
2. 在开仓决策前调用安全检查
3. 在对冲执行后记录结果
4. 定期记录仓位快照

**集成点**:

**初始化**（第60行附近）:
```python
# 在__init__中添加
self.safety_monitor = SafetyMonitor(self.config, self.logger)
```

**开仓前检查**（第800行附近）:
```python
# 在_check_can_open_new_position中添加
async def _check_can_open_new_position(self, opportunity: Dict) -> Tuple[bool, Optional[str]]:
    # 现有检查...

    # 新增: 安全检查
    if self.safety_monitor.should_pause_opening():
        return False, "安全监控器暂停开仓"

    circuit_level, reason = self.safety_monitor.check_circuit_breaker()
    if circuit_level >= 2:
        return False, f"熔断器级别{circuit_level}: {reason}"

    # 继续其他检查...
```

**对冲结果记录**（第950行附近）:
```python
# 在_open_new_pair中，对冲执行后添加
await self.safety_monitor.record_hedge_attempt(
    success=hedge_result['success'],
    failure_reason=hedge_result.get('error')
)
```

### 步骤4: 更新配置文件（30分钟）

**文件**: `spread/config.py`

**任务**: 添加P0安全配置项

**新增配置**:
```python
# spread/config.py 第68行附近添加

# ==================== P0: 安全监控配置 ====================
safety_enabled: bool = True
safety_hedge_failure_threshold: Decimal = Decimal('0.3')
safety_position_imbalance_threshold: Decimal = Decimal('0.5')
safety_failure_window: int = 10
safety_pause_duration: int = 3600
```

**验证**:
```bash
python -c "from spread.config import SpreadArbConfig; c = SpreadArbConfig(); print(c.safety_hedge_failure_threshold)"
```

### 步骤5: 编写测试（1.5小时）

**文件**: `tests/test_safety_monitor.py`

**必需测试**:
```python
import pytest
from spread.safety_monitor import SafetyMonitor
from spread.config import SpreadArbConfig
from decimal import Decimal

@pytest.fixture
def safety_monitor():
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    return SafetyMonitor(config, logger)

def test_record_hedge_attempt_success(safety_monitor):
    """测试记录成功的对冲尝试"""
    # 实现测试
    pass

def test_hedge_failure_rate_calculation(safety_monitor):
    """测试对冲失败率计算"""
    # 记录7次成功，3次失败
    for _ in range(7):
        safety_monitor.record_hedge_attempt(True)
    for _ in range(3):
        safety_monitor.record_hedge_attempt(False, reason="test")

    assert safety_monitor.get_hedge_failure_rate() == Decimal('0.3')

def test_circuit_breaker_trigger(safety_monitor):
    """测试熔断器触发"""
    # 记录超过阈值的失败率
    for _ in range(3):
        safety_monitor.record_hedge_attempt(True)
    for _ in range(7):
        safety_monitor.record_hedge_attempt(False, reason="test")

    level, reason = safety_monitor.check_circuit_breaker()
    assert level >= 2  # 应该触发至少级别2熔断

def test_position_imbalance_calculation(safety_monitor):
    """测试仓位失衡率计算"""
    # Extended 0.21, Lighter 0.02
    safety_monitor.update_position_imbalance(
        extended_qty=Decimal('0.21'),
        lighter_qty=Decimal('0.02')
    )

    imbalance_rate = safety_monitor.get_position_imbalance_rate()
    # 失衡率应该约为82.6%
    assert imbalance_rate > Decimal('0.8')
    assert imbalance_rate < Decimal('0.9')
```

**文件**: `tests/test_position_balance_fix.py`

```python
from spread.models import PositionBalance
from decimal import Decimal
import time

def test_fully_hedged_position():
    """测试完全对冲仓位"""
    balance = PositionBalance(
        timestamp=time.time(),
        extended_total_qty=Decimal('0.01'),
        lighter_total_qty=Decimal('-0.01'),
        diff_qty=Decimal('0.02')
    )

    assert balance.diff_rate == Decimal('0'), f"Expected 0%, got {balance.diff_rate}"
    assert balance.warning_level == 'OK'
    assert not balance.is_imbalanced

def test_imbalanced_position_82_percent():
    """测试82.6%失衡仓位（Extended 0.21, Lighter 0.02）"""
    balance = PositionBalance(
        timestamp=time.time(),
        extended_total_qty=Decimal('0.21'),
        lighter_total_qty=Decimal('0.02'),
        diff_qty=Decimal('0.19')
    )

    # 期望: 0.19 / 0.23 = 82.6%
    expected_rate = Decimal('0.19') / Decimal('0.23')
    assert balance.diff_rate == expected_rate
    assert balance.warning_level == 'CRITICAL'
    assert balance.is_imbalanced
```

**文件**: `tests/integration/test_circuit_breaker_integration.py`

```python
import pytest
from spread.bot import SpreadArbitrageBot
from spread.config import SpreadArbConfig

@pytest.mark.asyncio
async def test_hedge_failure_triggers_pause():
    """测试对冲失败触发暂停"""
    # 集成测试: 模拟对冲失败场景
    # 验证: bot.is_paused应该变为True
    pass

@pytest.mark.asyncio
async def test_circuit_breaker_recovery():
    """测试熔断器恢复"""
    # 测试手动重置熔断器
    pass
```

### 步骤6: 运行测试并修复（1小时）

**命令**:
```bash
# 运行P0相关测试
pytest tests/test_safety_monitor.py tests/test_position_balance_fix.py -v

# 运行集成测试
pytest tests/integration/test_circuit_breaker_integration.py -v

# 运行所有测试（确保没有破坏现有功能）
pytest tests/ -v
```

**验证清单**:
- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 没有破坏现有测试
- [ ] 手动验证安全监控日志

## P1 实现步骤（P0完成后）

### 前置条件

- 对冲成功率>90%
- 仓位失衡率<10%
- 所有P0测试通过

### 步骤1: 创建AdaptiveThresholdManager（1小时）

**文件**: `spread/adaptive_threshold_manager.py`

**任务**:
1. 实现`AdaptiveThresholdManager`类
2. 根据对冲成功率动态调整阈值
3. 提供阈值查询接口

### 步骤2: 集成到Bot（30分钟）

**文件**: `spread/bot.py`

**任务**:
1. 在`__init__`中初始化`adaptive_threshold_manager`
2. 在价差检查中使用动态阈值

### 步骤3: 更新配置（30分钟）

**文件**: `spread/config.py`

**任务**: 添加P1动态阈值配置项

### 步骤4: 测试（30分钟）

**命令**:
```bash
pytest tests/test_adaptive_threshold.py -v
```

## P2 实现步骤（P0和P1完成后）

### 步骤1: 更新平仓配置（30分钟）

**文件**: `spread/config.py`

**任务**: 调整盈利目标和平仓阈值

### 步骤2: 测试验证（30分钟）

**命令**:
```bash
pytest tests/test_closing_logic.py -v
```

## 验证和部署

### 本地验证

**步骤**:
1. 启动机器人（使用测试网络或小资金）
2. 触发对冲失败场景，验证熔断器
3. 监控仓位平衡状态
4. 验证日志输出

**监控命令**:
```bash
# 查看安全状态
tail -f logs/trade.log | grep "安全"

# 查看对冲失败
tail -f logs/hedge_failures.log

# 查看仓位快照
tail -f data/positions_*.csv
```

### 生产部署前检查

- [ ] 所有测试通过
- [ ] 配置文件已更新
- [ ] 日志级别设置正确
- [ ] 监控告警已配置
- [ ] 回滚计划已准备

### 回滚计划

如果P0功能出现问题：
1. 设置`SAFETY_ENABLED=false`禁用安全监控
2. 恢复到旧的仓位平衡计算方式
3. 重启bot

## 故障排查

### 问题: 熔断器没有触发

**检查**:
1. 确认`SAFETY_ENABLED=true`
2. 检查`safety_hedge_failure_threshold`值
3. 查看日志中对冲失败的记录

### 问题: 仓位失衡率计算仍然不正确

**检查**:
1. 确认使用的是新的`PositionBalance.__post_init__`
2. 验证输入数据是否包含正确的符号
3. 添加debug日志查看中间计算结果

### 问题: 对冲失败率仍然很高（>90%）

**可能原因**:
1. Lighter深度不足
2. WebSocket连接不稳定
3. API限流

**解决方案**:
1. 查看详细的失败原因日志
2. 考虑切换到限价单策略
3. 降低订单规模或增加重试延迟

## 下一步

Phase 1设计已完成。继续执行：
- `/speckit.tasks` - 生成详细的任务列表
- 开始实现P0功能
