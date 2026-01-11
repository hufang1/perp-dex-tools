# Module Contracts: 修复仓位失衡和优化开仓标准

**Feature**: 010-fix-position-imbalance
**Date**: 2026-01-11

## 概述

本文档定义了新增和修改的模块接口契约。

## P0: 安全监控模块

### SafetyMonitor（新增模块）

**文件**: `spread/safety_monitor.py`

**职责**: 实时监控系统安全状态，触发熔断机制

**接口**:

```python
class SafetyMonitor:
    """安全监控器"""

    def __init__(self, config: SpreadArbConfig, logger: logging.Logger):
        """
        初始化安全监控器

        Args:
            config: 配置对象
            logger: 日志记录器
        """

    async def record_hedge_attempt(self, success: bool, failure_reason: Optional[str] = None) -> None:
        """
        记录对冲尝试结果

        Args:
            success: 对冲是否成功
            failure_reason: 失败原因（如果失败）

        Raises:
            ValueError: 如果failure_reason在success=True时提供
        """

    def get_hedge_failure_rate(self) -> Decimal:
        """
        获取当前对冲失败率

        Returns:
            对冲失败率（0-1之间的Decimal）
        """

    def check_circuit_breaker(self) -> Tuple[int, str]:
        """
        检查是否应该触发熔断

        Returns:
            (熔断级别, 原因)
            级别: 0=正常, 1=警告, 2=禁止开仓, 3=完全暂停
        """

    def should_pause_opening(self) -> bool:
        """
        检查是否应该暂停开仓

        Returns:
            True表示应该暂停开仓
        """

    def should_force_close(self) -> bool:
        """
        检查是否应该强制平仓

        Returns:
            True表示应该强制平仓所有持仓
        """

    def update_position_imbalance(self, extended_qty: Decimal, lighter_qty: Decimal) -> None:
        """
        更新仓位失衡率

        Args:
            extended_qty: Extended总仓位（带符号）
            lighter_qty: Lighter总仓位（带符号）
        """

    def get_position_imbalance_rate(self) -> Decimal:
        """
        获取当前仓位失衡率

        Returns:
            仓位失衡率（0-1之间的Decimal）
        """

    def get_safety_state(self) -> SafetyState:
        """
        获取当前安全状态快照

        Returns:
            SafetyState对象
        """

    def reset_circuit_breaker(self) -> None:
        """
        手动重置熔断器

        用于用户确认问题解决后恢复交易
        """
```

**异常**:
- `SafetyError`: 安全检查失败的基类异常
- `CircuitBreakerError`: 熔断器触发时的异常

## P0: 修改现有模块

### PositionBalance（models.py）

**修改**: 修复`diff_rate`计算逻辑

**接口变更**:
```python
@dataclass
class PositionBalance:
    """仓位平衡状态"""

    timestamp: float
    extended_total_qty: Decimal
    lighter_total_qty: Decimal
    diff_qty: Decimal  # 计算方式不变
    diff_rate: Decimal  # 修改计算逻辑
    is_imbalanced: bool  # 由__post_init__计算
    warning_level: str  # 由__post_init__计算

    def __post_init__(self):
        """
        修改后的计算逻辑：

        1. 使用绝对值计算总暴露度
        2. 使用绝对值计算实际差异
        3. 计算正确的差异率
        4. 判断失衡级别（OK/WARN/CRITICAL）
        """
```

**向后兼容性**: 破坏性变更，所有调用方需要更新

### SpreadArbitrageBot（bot.py）

**修改**: 集成SafetyMonitor

**新增方法**:
```python
class SpreadArbitrageBot:

    def __init__(self, ...):
        # 现有初始化...
        self.safety_monitor = SafetyMonitor(self.config, self.logger)

    async def _check_safety_before_opening(self) -> Tuple[bool, Optional[str]]:
        """
        开仓前安全检查

        Returns:
            (是否允许开仓, 拒绝原因)

        集成点: 在_strategy_loop()中的开仓决策前调用
        """

    async def _handle_hedge_result(self, hedge_result: Dict, pair_id: int) -> None:
        """
        处理对冲结果，更新安全状态

        Args:
            hedge_result: 对冲结果字典
            pair_id: 套利对ID

        集成点: 在_open_new_pair()的对冲执行后调用
        """

    def _log_position_snapshot(self) -> None:
        """
        记录仓位快照

        集成点: 在_monitor_pairs()中定期调用
        """
```

**修改的方法签名**:
```python
# 修改前
async def _check_can_open_new_position(self, opportunity: Dict) -> Tuple[bool, Optional[str]]

# 修改后
async def _check_can_open_new_position(self, opportunity: Dict) -> Tuple[bool, Optional[str]]:
    """
    新增安全检查：
    1. 检查SafetyMonitor是否允许开仓
    2. 检查对冲失败率
    3. 检查仓位失衡率
    """
```

## P1: 动态阈值调整

### AdaptiveThresholdManager（新增模块）

**文件**: `spread/adaptive_threshold_manager.py`

**职责**: 根据对冲成功率动态调整开仓阈值

**接口**:

```python
class AdaptiveThresholdManager:
    """动态阈值管理器"""

    def __init__(self, config: SpreadArbConfig, safety_monitor: SafetyMonitor):
        """
        初始化

        Args:
            config: 配置对象
            safety_monitor: 安全监控器
        """

    def get_effective_min_spread_rate(self) -> Decimal:
        """
        获取当前有效的最小价差率

        根据对冲成功率动态调整：
        - 成功率>90%: 使用reduced_min_spread_rate (0.06%)
        - 成功率>80%: 使用中间值
        - 成功率<80%: 使用adaptive_min_spread_rate_safe (0.15%)

        Returns:
            当前有效的最小价差率
        """

    def should_enable_reduced_thresholds(self) -> bool:
        """
        检查是否应该启用降低的阈值

        Returns:
            True表示对冲成功率足够高，可以使用降低的阈值
        """

    async def update_thresholds(self) -> None:
        """
        定期更新阈值

        每adaptive_adjustment_interval秒调用一次
        """
```

## 测试契约

### 单元测试要求

**test_safety_monitor.py**:
```python
def test_record_hedge_attempt_success():
    """测试记录成功的对冲尝试"""

def test_record_hedge_attempt_failure():
    """测试记录失败的对冲尝试"""

def test_hedge_failure_rate_calculation():
    """测试对冲失败率计算"""

def test_circuit_breaker_trigger():
    """测试熔断器触发"""

def test_position_imbalance_calculation():
    """测试仓位失衡率计算"""

def test_should_pause_opening():
    """测试开仓暂停判断"""

def test_should_force_close():
    """测试强制平仓判断"""

def test_circuit_breaker_reset():
    """测试熔断器重置"""
```

**test_position_balance_fix.py**:
```python
def test_fully_hedged_position():
    """测试完全对冲仓位的diff_rate计算（应为0%）"""

def test_imbalanced_position():
    """测试失衡仓位的diff_rate计算"""

def test_critical_imbalance():
    """测试严重失衡（Extended 0.21 vs Lighter 0.02）"""

def test_warning_level_determination():
    """测试警告级别判断"""

def test_edge_cases():
    """测试边界情况（零仓位、单边仓位等）"""
```

### 集成测试要求

**test_circuit_breaker_integration.py**:
```python
async def test_hedge_failure_triggers_pause():
    """测试对冲失败触发暂停"""

async def test_position_imbalance_triggers_force_close():
    """测试仓位失衡触发强制平仓"""

async def test_safety_monitor_with_bot():
    """测试SafetyMonitor与Bot的集成"""

async def test_circuit_breaker_recovery():
    """测试熔断器恢复流程"""
```

## 配置契约

### 环境变量

**新增环境变量**（可选）:
```bash
# P0: 安全监控
SAFETY_ENABLED=true
SAFETY_HEDGE_FAILURE_THRESHOLD=0.3
SAFETY_POSITION_IMBALANCE_THRESHOLD=0.5
SAFETY_FAILURE_WINDOW=10
SAFETY_PAUSE_DURATION=3600

# P1: 动态阈值
ADAPTIVE_THRESHOLD_ENABLED=false
ADAPTIVE_MIN_HEDGE_SUCCESS_RATE=0.9
ADAPTIVE_MIN_SPREAD_RATE_SAFE=0.15
ADAPTIVE_MIN_SPREAD_RATE_AGGRESSIVE=0.06
ADAPTIVE_ADJUSTMENT_INTERVAL=300

# P1: 降低阈值
REDUCED_MIN_SPREAD_RATE=0.06
REDUCED_PROFIT_TARGET_RATE=0.02
REDUCED_MIN_CLOSE_PROFIT_RATE=0.03
```

### 默认值

如果环境变量未设置，使用代码中的默认值（参见data-model.md）。

## 向后兼容性

### 破坏性变更

1. **PositionBalance.diff_rate计算方式变更**
   - 影响: 所有使用`PositionBalance`的代码
   - 迁移: 更新调用方，使用新的计算方式

2. **新增必需的配置项**
   - 影响: 现有配置文件
   - 迁移: 提供默认值，向后兼容

### 非破坏性变更

1. **新增SafetyMonitor模块**
   - 影响: 无（新模块）
   - 迁移: 可选集成

2. **新增AdaptiveThresholdManager模块**
   - 影响: 无（新模块）
   - 迁移: 可选集成
