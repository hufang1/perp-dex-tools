# Data Model: 修复仓位失衡和优化开仓标准

**Feature**: 010-fix-position-imbalance
**Date**: 2026-01-11
**Status**: Phase 1 Design

## 概述

本文档定义了修复仓位失衡和优化开仓标准所需的数据模型。

## 新增实体

### 1. HedgeFailureTracking（对冲失败跟踪）

**用途**: 跟踪单次对冲操作的详细信息和失败原因

**字段**:
```python
@dataclass
class HedgeFailureTracking:
    """对冲失败跟踪记录"""

    # 基本信息
    timestamp: float                    # 失败时间戳
    pair_id: int                        # 关联的套利对ID
    extended_order_id: str             # Extended订单ID
    extended_fill_qty: Decimal         # Extended成交数量

    # 对冲尝试信息
    hedge_attempts: int                # 对冲尝试次数
    hedge_order_ids: List[str]         # Lighter订单ID列表

    # 失败原因
    failure_reason: str                # 失败原因分类
    # 可能值: "liquidity_insufficient", "api_error", "network_error", "timeout", "unknown"

    failure_details: str               # 详细错误信息

    # 状态
    is_resolved: bool = False          # 是否已解决（已补对冲或已平仓）
    resolved_at: Optional[float] = None  # 解决时间戳
    resolution_method: Optional[str] = None  # 解决方式: "hedge_success", "force_close", "manual_close"
```

**验证规则**:
- `hedge_attempts` >= 1
- `failure_reason` 必须是预定义值之一
- `timestamp` < `resolved_at`（如果已解决）

**状态转换**:
```
CREATED → RESOLVED
          ↓
     [hedge_success, force_close, manual_close]
```

### 2. SafetyState（安全状态）

**用途**: 实时跟踪系统安全状态，用于熔断决策

**字段**:
```python
@dataclass
class SafetyState:
    """系统安全状态"""

    # 基本状态
    is_paused: bool = False              # 是否暂停
    pause_reason: str = ""               # 暂停原因
    pause_since: Optional[float] = None  # 暂停开始时间

    # 对冲失败率监控
    hedge_failure_window: int = 10       # 统计窗口大小
    recent_hedge_attempts: List[bool] = field(default_factory=list)  # 最近对冲尝试
    hedge_failure_rate: Decimal = Decimal('0')  # 对冲失败率

    # 仓位失衡监控
    position_imbalance_rate: Decimal = Decimal('0')  # 仓位失衡率
    last_imbalance_check: Optional[float] = None    # 上次检查时间

    # 未对冲仓位
    unhedged_positions: List[Dict] = field(default_factory=list)  # 未对冲仓位列表
    total_unhedged_value: Decimal = Decimal('0')  # 未对冲总价值（USDT）

    # 熔断级别
    circuit_breaker_level: int = 0      # 熔断级别: 0=正常, 1=警告, 2=暂停开仓, 3=完全暂停

    # 统计
    total_hedge_attempts: int = 0       # 总对冲尝试次数
    total_hedge_failures: int = 0       # 总对冲失败次数
```

**验证规则**:
- `hedge_failure_rate` = `total_hedge_failures` / `total_hedge_attempts`
- `circuit_breaker_level` ∈ {0, 1, 2, 3}
- `recent_hedge_attempts` 长度 <= `hedge_failure_window`

**状态转换**:
```
NORMAL (0) → WARNING (1) → PAUSE_OPENING (2) → FULL_PAUSE (3)
    ↑            ↓              ↓                ↓
    └────────────┴──────────────┴────────────────┘
           (条件改善后自动降级)
```

### 3. PositionSnapshot（仓位快照）

**用途**: 定期记录仓位状态，用于分析和调试

**字段**:
```python
@dataclass
class PositionSnapshot:
    """仓位状态快照"""

    # 时间信息
    timestamp: float                    # 快照时间戳

    # 仓位信息
    extended_position: Decimal         # Extended仓位（带符号）
    lighter_position: Decimal          # Lighter仓位（带符号）
    diff_qty: Decimal                  # 差异数量
    diff_rate: Decimal                 # 差异率

    # 套利对信息
    open_pairs_count: int              # 开放套利对数量
    pair_details: List[Dict]           # 每个套利对的详细信息

    # 安全状态
    safety_level: str                   # 安全级别: "OK", "WARNING", "CRITICAL"
    is_hedge_needed: bool              # 是否需要对冲

    # 市场信息
    current_spread: Optional[Decimal] = None  # 当前价差
    market_conditions: Dict = field(default_factory=dict)  # 市场条件
```

**验证规则**:
- `extended_position` 和 `lighter_position` 必须有符号
- `diff_rate` >= 0
- `open_pairs_count` >= 0

## 修改现有实体

### PositionBalance（models.py）

**修改**: 修复`diff_rate`计算逻辑

**当前实现**（错误）:
```python
def __post_init__(self):
    if self.lighter_total_qty == 0:
        if self.extended_total_qty == 0:
            self.diff_rate = Decimal('0')
        else:
            self.diff_rate = Decimal('999')
    else:
        self.diff_rate = abs(self.diff_qty) / self.lighter_total_qty
```

**修改后**（正确）:
```python
def __post_init__(self):
    # 计算总暴露度（两个交易所的绝对值之和）
    total_exposure = abs(self.extended_total_qty) + abs(self.lighter_total_qty)

    # 计算实际差异（两个绝对值之间的差异）
    actual_diff_qty = abs(abs(self.extended_total_qty) - abs(self.lighter_total_qty))

    # 计算差异率
    if total_exposure > 0:
        self.diff_rate = actual_diff_qty / total_exposure
    else:
        self.diff_rate = Decimal('0')

    # 判断是否失衡
    if self.diff_rate >= Decimal('0.5'):  # 50%以上
        self.warning_level = 'CRITICAL'
    elif self.diff_rate >= Decimal('0.1'):  # 10%以上
        self.warning_level = 'WARN'
    else:
        self.warning_level = 'OK'

    self.is_imbalanced = self.warning_level != 'OK'
```

### SpreadArbConfig（config.py）

**新增配置项**:

```python
@dataclass
class SpreadArbConfig:
    # ... 现有配置 ...

    # ==================== P0: 安全监控配置 ====================
    safety_enabled: bool = True                          # 启用安全监控
    safety_hedge_failure_threshold: Decimal = Decimal('0.3')   # 对冲失败率阈值（30%）
    safety_position_imbalance_threshold: Decimal = Decimal('0.5')  # 仓位失衡率阈值（50%）
    safety_failure_window: int = 10                      # 失败率统计窗口（最近N次）
    safety_pause_duration: int = 3600                    # 安全暂停时长（秒，默认1小时）

    # ==================== P1: 动态阈值调整配置 ====================
    adaptive_threshold_enabled: bool = False            # 启用动态阈值调整
    adaptive_min_hedge_success_rate: Decimal = Decimal('0.9')   # 最低对冲成功率（90%）
    adaptive_min_spread_rate_safe: Decimal = Decimal('0.15')    # 安全阈值（对冲成功率低时）
    adaptive_min_spread_rate_aggressive: Decimal = Decimal('0.06')  # 激进阈值（对冲成功率高时）
    adaptive_adjustment_interval: int = 300             # 阈值调整间隔（秒，默认5分钟）

    # ==================== P1: 降低阈值配置 ====================
    reduced_min_spread_rate: Decimal = Decimal('0.06')  # 降低后的开仓阈值
    reduced_profit_target_rate: Decimal = Decimal('0.02')  # 降低后的盈利目标
    reduced_min_close_profit_rate: Decimal = Decimal('0.03')  # 降低后的平仓阈值
```

**验证规则**（__post_init__）:
```python
# 验证安全配置
if self.safety_hedge_failure_threshold < 0 or self.safety_hedge_failure_threshold > 1:
    raise ValueError("safety_hedge_failure_threshold 必须在 [0, 1] 范围内")

if self.safety_position_imbalance_threshold < 0 or self.safety_position_imbalance_threshold > 1:
    raise ValueError("safety_position_imbalance_threshold 必须在 [0, 1] 范围内")

if self.safety_failure_window < 1:
    raise ValueError("safety_failure_window 必须大于 0")

# 验证动态阈值配置
if self.adaptive_min_hedge_success_rate < 0 or self.adaptive_min_hedge_success_rate > 1:
    raise ValueError("adaptive_min_hedge_success_rate 必须在 [0, 1] 范围内")

if self.adaptive_min_spread_rate_safe <= self.adaptive_min_spread_rate_aggressive:
    raise ValueError("adaptive_min_spread_rate_safe 必须大于 adaptive_min_spread_rate_aggressive")

# 验证降低阈值配置
if self.reduced_min_spread_rate <= 0:
    raise ValueError("reduced_min_spread_rate 必须大于 0")

if self.reduced_profit_target_rate <= 0:
    raise ValueError("reduced_profit_target_rate 必须大于 0")

if self.reduced_min_spread_rate <= self.reduced_min_close_profit_rate:
    raise ValueError("reduced_min_spread_rate 必须大于 reduced_min_close_profit_rate（确保盈利空间）")
```

## 数据流

### 对冲失败检测流程

```
Extended订单成交
    ↓
hedge_manager.execute_hedge()
    ↓
Lighter订单提交
    ↓
[检查订单状态]
    ↓
┌─────────────┬─────────────┬─────────────┐
│ 成功         │ 部分成功      │ 失败         │
└─────────────┴─────────────┴─────────────┘
      ↓              ↓              ↓
记录成功        记录部分成功    创建HedgeFailureTracking
更新SafetyState                    更新SafetyState
                                  检查是否触发熔断
```

### 熔断决策流程

```
SafetyState更新
    ↓
计算对冲失败率
    ↓
计算仓位失衡率
    ↓
┌─────────────────────────────────────┐
│ 判断熔断级别                         │
│ - 失败率>50% OR 失衡率>50% → 级别3  │
│ - 失败率>30% → 级别2                │
│ - 失败率>20% → 级别1                │
│ - 否则 → 级别0                      │
└─────────────────────────────────────┘
    ↓
执行对应级别的动作
    ↓
[级别0] 正常运行
[级别1] 记录警告，继续监控
[级别2] 禁止新开仓
[级别3] 完全暂停，通知用户
```

## 存储策略

### 内存存储
- `SafetyState`: bot.py中的实例变量，实时更新
- `HedgeFailureTracking`: 列表存储，最多保留100条记录

### 文件存储
- `PositionSnapshot`: 定期写入CSV（data/positions_YYYY_MM_DD.csv）
- `HedgeFailureTracking`: 写入日志文件（logs/hedge_failures.log）

### 日志格式

```python
# logs/hedge_failures.log
{"timestamp": "2026-01-11T12:34:56.789", "pair_id": 1, "failure_reason": "liquidity_insufficient", "extended_fill_qty": "0.01", "hedge_attempts": 3}
```

## 性能考虑

1. **内存限制**: `HedgeFailureTracking`列表最大100条
2. **计算频率**: `SafetyState`更新频率为每次对冲尝试后
3. **快照频率**: `PositionSnapshot`每60秒记录一次
4. **清理策略**: 超过24小时的记录自动清理
