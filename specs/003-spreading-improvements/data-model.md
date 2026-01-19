# 数据模型：价差套利系统改进

**功能**: 003-spreading-improvements | **日期**: 2026-01-19

## 概述

本文档定义价差套利系统改进所需的数据模型，包括新增模型和对现有模型的修改。

## 修改的现有模型

### 1. BotState (状态枚举)

**文件**: `spread/models.py`

**修改内容**: 新增两个状态用于区分市价平仓和限价平仓

```python
class BotState(Enum):
    """机器人状态枚举"""
    # 现有状态保持不变...
    IDLE = "IDLE"
    OPENING = "OPENING"
    OPENING_MAKER_WAIT = "OPENING_MAKER_WAIT"
    OPENING_WAIT = "OPENING_WAIT"
    HOLDING = "HOLDING"
    # 修改：重命名和新增
    CLOSING_LIMIT = "CLOSING_LIMIT"      # 限价平仓中（等待成交），取代 CLOSING_MAKER_WAIT
    CLOSING_MARKET = "CLOSING_MARKET"    # 市价平仓中（立即执行），新增
    LIGHTER_HEDGING = "LIGHTER_HEDGING"
    CLOSING_WAIT = "CLOSING_WAIT"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
```

**验证规则**:
- 新状态必须与现有状态不冲突
- 状态转换逻辑必须明确（参考状态转换图）

**向后兼容性**: 需要处理旧的状态文件中的 `CLOSING_MAKER_WAIT` 状态

---

### 2. BotConfig (配置数据类)

**文件**: `spread/models.py`

**修改内容**: 新增阶梯开仓和双模式平仓配置字段

```python
@dataclass
class BotConfig:
    """机器人配置数据类"""

    # ========== 现有字段保持不变 ==========

    # ========== 新增字段 (003-spreading-improvements) ==========

    # 阶梯价差开仓配置
    initial_open_spread: Decimal = field(default_factory=lambda: Decimal("0.005"))
    """
    初始开仓价差阈值
    - 默认0.5% = 0.005
    - 第一次开仓使用此阈值
    """

    spread_step: Decimal = field(default_factory=lambda: Decimal("0.001"))
    """
    开仓步长
    - 默认0.1% = 0.001
    - 第N次开仓阈值 = initial_open_spread + (N-1) * spread_step
    """

    opening_count: int = 0
    """
    当前开仓次数
    - 初始值为0
    - 每次开仓成功后+1
    - 所有仓位平仓后重置为0
    - 用于计算当前开仓阈值
    """

    # 双模式平仓配置
    limit_close_spread_a: Decimal = field(default_factory=lambda: Decimal("0.002"))
    """
    限价平仓阈值A
    - 默认0.2% = 0.002
    - 用于判断是否使用限价平仓
    """

    market_close_spread_b: Decimal = field(default_factory=lambda: Decimal("0.004"))
    """
    市价平仓阈值B
    - 默认0.4% = 0.004
    - 用于判断是否使用市价平仓
    - 必须大于 limit_close_spread_a
    """

    @property
    def current_open_threshold(self) -> Decimal:
        """计算当前开仓阈值"""
        return self.initial_open_spread + (self.opening_count * self.spread_step)
```

**验证规则**:
- `initial_open_spread` > 0
- `spread_step` > 0
- `opening_count` >= 0
- `limit_close_spread_a` > 0
- `market_close_spread_b` > `limit_close_spread_a`

**状态持久化**: 需要在 `StateManager` 中持久化 `opening_count`

---

## 新增模型

### 3. BalanceCheckResult (余额检测结果)

**文件**: `spread/models.py` (已存在，需扩展)

**用途**: 开仓前余额检测结果

```python
@dataclass
class BalanceCheckResult:
    """
    开仓前余额检测结果

    验证规则：
    - 两个交易所余额都必须充足才能通过检测
    - 详细的日志信息用于调试
    """
    is_sufficient: bool                   # 余额是否充足
    ext_available: Decimal                # Extended可用USDT余额
    ext_required: Decimal                 # Extended所需USDT金额
    lig_available: Decimal                # Lighter可用代币余额
    lig_required: Decimal                 # Lighter所需代币数量
    check_time: float                     # 检查时间戳

    # 失败原因
    failure_reason: Optional[str] = None  # 失败原因（哪个交易所不足）
    shortage_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    """
    缺少金额
    - 如果 Extended 不足，缺少 USDT 数量
    - 如果 Lighter 不足，缺少代币数量
    """

    def format_log(self) -> str:
        """格式化为日志字符串"""
        if self.is_sufficient:
            return (
                f"余额检测通过 | "
                f"Ext: {self.ext_available:.2f}/{self.ext_required:.2f} USDT | "
                f"Lig: {self.lig_available:.4f}/{self.lig_required:.4f} 代币"
            )
        else:
            return (
                f"余额检测失败 | {self.failure_reason} | "
                f"缺少 {self.shortage_amount:.4f} | "
                f"Ext: {self.ext_available:.2f}/{self.ext_required:.2f} USDT | "
                f"Lig: {self.lig_available:.4f}/{self.lig_required:.4f} 代币"
            )
```

**创建时机**: 在每次开仓前调用 `BalanceChecker.check_before_opening()`

**使用场景**:
- 用户故事4：开仓前检测两个交易所余额

---

### 4. CancelOrderResult (取消订单结果)

**文件**: `spread/models.py` (新增)

**用途**: 订单取消操作的结果

```python
@dataclass
class CancelOrderResult:
    """
    取消订单操作结果

    验证规则：
    - 只有 canceled=True 时才能创建新订单
    - 详细的重试信息用于日志和调试
    """
    order_id: str                        # 被取消的订单ID
    canceled: bool                       # 是否成功取消
    attempts: int                        # 尝试次数
    total_time: float                    # 总耗时（秒）

    # 失败信息
    final_status: Optional[str] = None   # 最终订单状态
    error_message: Optional[str] = None  # 错误信息

    @property
    def is_successful(self) -> bool:
        """是否成功"""
        return self.canceled

    def format_log(self) -> str:
        """格式化为日志字符串"""
        if self.canceled:
            return (
                f"订单取消成功 | ID={self.order_id[:12]}... | "
                f"尝试={self.attempts}次 | 耗时={self.total_time:.1f}秒"
            )
        else:
            return (
                f"订单取消失败 | ID={self.order_id[:12]}... | "
                f"尝试={self.attempts}次 | "
                f"最终状态={self.final_status} | "
                f"错误={self.error_message or '未知'}"
            )
```

**创建时机**: 在 `TradeExecutor.cancel_maker_order_with_verification()` 中创建

**使用场景**:
- 用户故事1：取消订单验证机制

---

### 5. TieredOpeningState (阶梯开仓状态)

**文件**: `spread/models.py` (新增)

**用途**: 阶梯开仓策略的状态信息

```python
@dataclass
class TieredOpeningState:
    """
    阶梯开仓策略状态

    用于记录和追踪阶梯开仓的当前状态
    """
    current_count: int                   # 当前开仓次数
    current_threshold: Decimal           # 当前开仓阈值
    next_threshold: Decimal              # 下次开仓阈值

    # 配置参数
    initial_spread: Decimal              # 初始开仓价差
    step_size: Decimal                   # 步长

    # 历史记录
    opening_history: list[dict] = field(default_factory=list)
    """
    开仓历史记录
    每条记录包含：
    {
        'count': int,          # 第几次开仓
        'threshold': Decimal,  # 使用的阈值
        'actual_spread': Decimal,  # 实际开仓价差
        'timestamp': float,    # 时间戳
    }
    """

    def calculate_threshold(self, count: int) -> Decimal:
        """计算指定次数的阈值"""
        return self.initial_spread + (count - 1) * self.step_size

    def advance(self) -> None:
        """推进到下一级"""
        self.current_count += 1
        self.current_threshold = self.calculate_threshold(self.current_count)
        self.next_threshold = self.calculate_threshold(self.current_count + 1)

    def reset(self) -> None:
        """重置（所有仓位平仓后）"""
        self.current_count = 0
        self.current_threshold = self.initial_spread
        self.next_threshold = self.calculate_threshold(1)
        self.opening_history.clear()

    def record_opening(self, actual_spread: Decimal) -> None:
        """记录一次开仓"""
        self.opening_history.append({
            'count': self.current_count,
            'threshold': self.current_threshold,
            'actual_spread': actual_spread,
            'timestamp': time.time()
        })

    def format_log(self) -> str:
        """格式化为日志字符串"""
        return (
            f"阶梯开仓 | 次数={self.current_count} | "
            f"当前阈值={self.current_threshold:.3%} | "
            f"下次阈值={self.next_threshold:.3%} | "
            f"初始={self.initial_spread:.3%} | "
            f"步长={self.step_size:.3%}"
        )
```

**创建时机**: 在 `ArithmeticOpenStrategy` 初始化时创建

**使用场景**:
- 用户故事2：阶梯价差开仓

---

### 6. CloseModeDecision (平仓模式决策)

**文件**: `spread/models.py` (新增)

**用途**: 双模式平仓的决策结果

```python
@dataclass
class CloseModeDecision:
    """
    双模式平仓决策结果

    包含是否平仓、使用哪种模式、以及详细的决策依据
    """
    should_close: bool                   # 是否应该平仓
    use_market: bool                     # True=市价平仓, False=限价平仓

    # 决策依据
    total_position_spread: Decimal       # 总开仓仓位的价差
    current_spread: Decimal              # 当前市场价差
    market_threshold: Decimal            # 市价平仓阈值
    limit_threshold: Decimal             # 限价平仓阈值

    # 计算结果
    expected_profit_limit: Decimal       # 限价平仓预期利润
    expected_profit_market: Decimal      # 市价平仓预期利润

    decision_time: float = field(default_factory=lambda: time.time())

    @property
    def close_mode_name(self) -> str:
        """平仓模式名称"""
        return "市价" if self.use_market else "限价"

    @property
    def reason(self) -> str:
        """决策原因"""
        if not self.should_close:
            return "不满足平仓条件"

        if self.use_market:
            return (
                f"市价平仓 | 利润大 | "
                f"价差{self.current_spread:.3%} < 市价阈值{self.market_threshold:.3%}"
            )
        else:
            return (
                f"限价平仓 | 利润小 | "
                f"价差{self.current_spread:.3%} < 限价阈值{self.limit_threshold:.3%}"
            )

    def format_log(self) -> str:
        """格式化为日志字符串"""
        if not self.should_close:
            return (
                f"持仓监控 | 总开仓={self.total_position_spread:.3%} | "
                f"当前={self.current_spread:.3%} | "
                f"限价阈值={self.limit_threshold:.3%} | "
                f"市价阈值={self.market_threshold:.3%}"
            )
        else:
            return (
                f"平仓触发 | {self.close_mode_name} | {self.reason} | "
                f"总开仓={self.total_position_spread:.3%}"
            )
```

**创建时机**: 在 `SmartCloseStrategy.should_close()` 中创建

**使用场景**:
- 用户故事3：双模式平仓逻辑

---

## 数据流图

### 开仓流程

```
┌─────────────────────────────────────────────────────────────────┐
│                         开仓前余额检测                           │
├─────────────────────────────────────────────────────────────────┤
│ 1. BalanceChecker.check_before_opening()                       │
│ 2. 查询 Extended 和 Lighter 可用余额                           │
│ 3. 计算所需金额 (target_quantity * price)                     │
│ 4. 返回 BalanceCheckResult                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │  BalanceCheckResult          │
              │  .is_sufficient == True?     │
              └──────────────────────────────┘
                     │                │
                    Yes              No
                     │                │
                     ▼                ▼
              ┌──────────────┐   ┌──────────────┐
              │ 继续开仓流程  │   │ 跳过本次开仓 │
              └──────────────┘   └──────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                     阶梯价差开仓判断                            │
├─────────────────────────────────────────────────────────────────┤
│ 1. ArithmeticOpenStrategy.should_open()                       │
│ 2. 获取当前阈值: config.current_open_threshold                │
│ 3. 比较: current_spread >= threshold?                         │
│ 4. 返回 (should_open, reason)                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 平仓流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     双模式平仓决策                              │
├─────────────────────────────────────────────────────────────────┤
│ 1. SmartCloseStrategy.should_close()                          │
│ 2. 获取总开仓仓位价差（交易所API或本地加权平均）              │
│ 3. 计算阈值：                                                 │
│    - market_threshold = total_spread - market_close_spread_b  │
│    - limit_threshold = total_spread - limit_close_spread_a    │
│ 4. 判断：                                                     │
│    - current_spread < market_threshold → 市价平仓            │
│    - current_spread < limit_threshold → 限价平仓            │
│ 5. 返回 CloseModeDecision                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │   CloseModeDecision         │
              │   .should_close == True?    │
              └──────────────────────────────┘
                     │                │
                    Yes              No
                     │                │
                     ▼                ▼
          ┌────────────────┐    ┌────────────────┐
          │ .use_market?   │    │  继续持有      │
          └────────────────┘    └────────────────┘
              │         │
             True      False
              │         │
              ▼         ▼
     ┌──────────┐ ┌──────────┐
     │市价平仓  │ │限价平仓  │
     │立即执行  │ │等待成交  │
     └──────────┘ └──────────┘
```

### 挂单修改流程

```
┌─────────────────────────────────────────────────────────────────┐
│                   修改挂单价格（防止重复挂单）                  │
├─────────────────────────────────────────────────────────────────┤
│ 1. 检测需要修改价格                                           │
│ 2. TradeExecutor.cancel_maker_order_with_verification()        │
│ 3. 调用 extended_client.cancel_order(order_id)                │
│ 4. 轮询验证: _verify_order_cancellation()                     │
│ 5. 返回 CancelOrderResult                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌──────────────────────────────┐
              │  CancelOrderResult           │
              │  .canceled == True?          │
              └──────────────────────────────┘
                     │                │
                    Yes              No
                     │                │
                     ▼                ▼
              ┌──────────────┐   ┌──────────────┐
              │ 创建新订单   │   │ 停止，记录   │
              │ 并更新监控   │   │ 错误，安全   │
              └──────────────┘   │ 状态         │
                                └──────────────┘
```

---

## 状态转换图

### 新增状态转换

```
HOLDING (持仓中)
  │
  ├─ 检测到平仓信号（SmartCloseStrategy.should_close）
  │   │
  │   ├─ current_spread < market_threshold
  │   │   └─→ CLOSING_MARKET (市价平仓中)
  │   │       └─→ 执行市价平仓
  │   │       └─→ IDLE (平仓完成)
  │   │
  │   └─ current_spread < limit_threshold
  │       └─→ CLOSING_LIMIT (限价平仓中)
  │           └─→ 等待限价单成交
  │           ├─→ 全部成交 → IDLE
  │           └─→ 部分成交 → LIGHTER_HEDGING
  │
  └─ 继续监控价差
```

### 开仓次数状态转换

```
IDLE
  │
  ├─ 首次开仓
  │   └─→ opening_count = 0
  │   └─→ threshold = initial_open_spread
  │   └─→ OPENING
  │
  └─ 开仓成功
      └─→ opening_count += 1
      └─→ HOLDING

HOLDING
  │
  ├─ 检测到新的开仓机会
  │   └─→ threshold = initial_open_spread + opening_count * step
  │   └─→ OPENING
  │
  └─ 所有仓位平仓
      └─→ opening_count = 0
      └─→ IDLE
```

---

## 验证规则总结

### 配置验证

```python
def validate_config_003(self) -> bool:
    """验证003功能相关配置"""
    errors = []

    # 阶梯开仓配置
    if self.initial_open_spread <= 0:
        errors.append("initial_open_spread 必须 > 0")
    if self.spread_step <= 0:
        errors.append("spread_step 必须 > 0")
    if self.opening_count < 0:
        errors.append("opening_count 必须 >= 0")

    # 双模式平仓配置
    if self.limit_close_spread_a <= 0:
        errors.append("limit_close_spread_a 必须 > 0")
    if self.market_close_spread_b <= 0:
        errors.append("market_close_spread_b 必须 > 0")
    if self.market_close_spread_b <= self.limit_close_spread_a:
        errors.append("market_close_spread_b 必须 > limit_close_spread_a")

    return len(errors) == 0, errors
```

### 状态转换验证

```python
def validate_state_transition(
    old_state: BotState,
    new_state: BotState,
    context: dict
) -> tuple[bool, Optional[str]]:
    """
    验证状态转换是否合法

    Returns:
        (is_valid, error_message)
    """
    # CLOSING_MARKET 只能从 HOLDING 转换而来
    if new_state == BotState.CLOSING_MARKET:
        if old_state != BotState.HOLDING:
            return False, f"只能从 HOLDING 转换到 CLOSING_MARKET，当前状态: {old_state}"

    # CLOSING_LIMIT 只能从 HOLDING 转换而来
    if new_state == BotState.CLOSING_LIMIT:
        if old_state != BotState.HOLDING:
            return False, f"只能从 HOLDING 转换到 CLOSING_LIMIT，当前状态: {old_state}"

    return True, None
```

---

## 向后兼容性

### 状态文件兼容

```python
async def load_state(self) -> BotState:
    """加载状态（支持向后兼容）"""
    # ... 现有代码 ...

    # 处理旧状态 CLOSING_MAKER_WAIT
    if self._current_state == BotState.CLOSING_MAKER_WAIT:
        logger.info("检测到旧状态 CLOSING_MAKER_WAIT，转换为 CLOSING_LIMIT")
        self._current_state = BotState.CLOSING_LIMIT

    # 加载新增的配置字段
    config_state_data = data.get("config_state")
    if config_state_data:
        self._config.opening_count = config_state_data.get("opening_count", 0)
        # ... 其他字段 ...
```

---

## 下一步

基于数据模型，继续完成：
1. **contracts/** - 定义模块间接口契约
2. **quickstart.md** - 编写快速开始指南

---

**文档版本**: 1.0 | **最后更新**: 2026-01-19
