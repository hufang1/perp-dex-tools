# 模块接口契约：价差套利系统改进

**功能**: 003-spreading-improvements | **日期**: 2026-01-19

## 概述

本文档定义价差套利系统改进中涉及的模块间接口契约，包括新增模块的接口和现有模块的扩展接口。

---

## 1. BalanceChecker (新增模块)

**文件**: `spread/balance_checker.py`

**用途**: 开仓前检查两个交易所的可用余额是否足够支持目标仓位

### 接口定义

```python
class BalanceChecker:
    """
    可用余额检测器

    职责：
    1. 查询两个交易所的可用余额
    2. 计算开仓所需金额
    3. 比较并返回检测结果
    """

    def __init__(
        self,
        lighter_client,
        extended_client,
        config: BotConfig
    ):
        """
        初始化余额检测器

        Args:
            lighter_client: Lighter交易所客户端
            extended_client: Extended交易所客户端
            config: 机器人配置
        """
        pass

    async def check_before_opening(
        self,
        target_quantity: Decimal,
        ext_price: Decimal,
        lig_price: Optional[Decimal] = None
    ) -> BalanceCheckResult:
        """
        开仓前检查两个交易所的可用余额

        Args:
            target_quantity: 目标开仓数量
            ext_price: Extended开仓价格
            lig_price: Lighter开仓价格（可选，默认使用ext_price）

        Returns:
            BalanceCheckResult: 检测结果

        Raises:
            BalanceCheckError: 余额查询失败
        """
        pass

    async def _get_extended_balance(self) -> Decimal:
        """
        获取Extended可用USDT余额

        Returns:
            可用USDT余额

        Raises:
            ExchangeAPIError: API调用失败
        """
        pass

    async def _get_lighter_balance(self, symbol: str) -> Decimal:
        """
        获取Lighter可用代币余额

        Args:
            symbol: 交易对符号（如 "ETH"）

        Returns:
            可用代币余额

        Raises:
            ExchangeAPIError: API调用失败
        """
        pass

    def _calculate_required_amount(
        self,
        quantity: Decimal,
        price: Decimal
    ) -> Decimal:
        """
        计算所需金额（考虑杠杆）

        Args:
            quantity: 数量
            price: 价格

        Returns:
            所需金额（保证金）
        """
        pass
```

### 调用时机

- 在 `SpreadArbBot._check_open_signal()` 中，检测到开仓信号后立即调用
- 在执行任何开仓操作之前（Extended 挂单和 Lighter 对冲之前）

### 返回值处理

```python
result = await self.balance_checker.check_before_opening(
    target_quantity=self.config.target_quantity,
    ext_price=current_ext_price,
    lig_price=current_lig_price
)

if not result.is_sufficient:
    logger.warning(f"余额不足: {result.format_log()}")
    # 跳过本次开仓，状态保持不变
    return
```

### 错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| ExchangeAPIError | 记录错误，跳过本次开仓，保持当前状态 |
| 网络超时 | 记录警告，跳过本次开仓，保持当前状态 |
| 数据解析失败 | 记录错误，跳过本次开仓，保持当前状态 |

---

## 2. TradeExecutor 扩展接口

**文件**: `spread/trade_executor.py`

**扩展内容**: 新增取消订单验证方法

### 新增接口

```python
class TradeExecutor:
    """
    交易执行器（扩展）

    新增功能：取消订单验证机制
    """

    async def cancel_maker_order_with_verification(
        self,
        order_id: str,
        max_retries: int = 5,
        retry_interval: float = 2.0,
        verify_timeout: float = 5.0
    ) -> CancelOrderResult:
        """
        取消订单并验证取消成功

        Args:
            order_id: 要取消的订单ID
            max_retries: 最大重试次数（默认5次）
            retry_interval: 重试间隔秒数（默认2秒）
            verify_timeout: 验证超时秒数（默认5秒）

        Returns:
            CancelOrderResult: 取消结果

        行为：
            1. 调用 extended_client.cancel_order(order_id)
            2. 轮询验证订单状态直到取消成功
            3. 如果验证失败，重试取消操作
            4. 达到最大重试次数后返回失败结果

        错误处理：
            - 如果交易所API异常，记录错误并重试
            - 如果超时仍未取消，返回失败但不抛出异常
        """
        pass

    async def _verify_order_cancellation(
        self,
        order_id: str,
        timeout: float = 5.0
    ) -> bool:
        """
        验证订单已取消

        Args:
            order_id: 订单ID
            timeout: 超时秒数

        Returns:
            True 如果订单已取消，否则 False

        实现细节：
            - 通过 REST API 轮询订单状态
            - 每0.5秒查询一次
            - 检查状态是否为 CANCELED 或 CANCELLED
            - 超时后返回 False
        """
        pass
```

### 调用时机

在 `PriceMonitor` 或 `MakerOrderMonitor` 检测到需要修改挂单价格时：

```python
# 1. 先取消旧订单
cancel_result = await self.trade_executor.cancel_maker_order_with_verification(
    order_id=current_order.order_id
)

# 2. 验证结果
if not cancel_result.canceled:
    logger.error(f"取消订单失败，停止创建新订单: {cancel_result.format_log()}")
    # 进入安全状态，停止尝试修改价格
    return

# 3. 创建新订单
new_order = await self._create_maker_order(new_price)
```

### 向后兼容

现有的 `cancel_order()` 方法保持不变，新增的方法是原有功能的增强版本。

---

## 3. ArithmeticOpenStrategy 扩展接口

**文件**: `spread/arithmetic_open_strategy.py`

**扩展内容**: 支持阶梯价差开仓

### 修改的接口

```python
class ArithmeticOpenStrategy:
    """
    等差数列开仓策略（扩展）

    新增功能：阶梯价差开仓
    """

    async def should_open(
        self,
        spread_info: SpreadInfo
    ) -> tuple[bool, str]:
        """
        判断是否应该开仓（修改）

        Returns:
            (should_open, reason)

        新逻辑：
            1. 使用 config.current_open_threshold 获取当前阈值
            2. 比较 spread_info.opening_spread >= threshold
            3. reason 中包含当前开仓次数、阈值等信息

        示例输出：
            - True, "价差 0.60% >= 阈值 0.60% (初始=0.50%, 次数=1, 步长=0.10%)"
            - False, "价差 0.55% < 阈值 0.60% (初始=0.50%, 次数=1, 步长=0.10%)"
        """
        pass

    async def on_position_opened(self, position: OpenPosition) -> None:
        """
        开仓成功回调（新增）

        Args:
            position: 新开的仓位

        行为：
            1. 增加 config.opening_count
            2. 记录开仓历史
            3. 更新策略状态
        """
        pass

    async def on_all_positions_closed(self) -> None:
        """
        所有仓位平仓回调（新增）

        行为：
            1. 重置 config.opening_count = 0
            2. 清空开仓历史
            3. 记录日志
        """
        pass

    def get_current_tier_state(self) -> TieredOpeningState:
        """
        获取当前阶梯开仓状态（新增）

        Returns:
            TieredOpeningState: 当前状态快照

        用途：
            - 日志输出
            - 状态监控
            - 调试信息
        """
        pass
```

### 配置依赖

需要在 `BotConfig` 中新增以下字段：

```python
@dataclass
class BotConfig:
    # 新增字段
    initial_open_spread: Decimal = Decimal("0.005")  # 初始开仓价差
    spread_step: Decimal = Decimal("0.001")           # 开仓步长
    opening_count: int = 0                            # 开仓次数

    @property
    def current_open_threshold(self) -> Decimal:
        """计算当前开仓阈值"""
        return self.initial_open_spread + (self.opening_count * self.spread_step)
```

### 状态持久化

需要在 `StateManager` 中持久化 `opening_count`：

```python
async def save_state(self, ...) -> None:
    data = {
        # ... 现有字段 ...
        "config_state": {
            "opening_count": self._config.opening_count,
            "initial_open_spread": str(self._config.initial_open_spread),
            "spread_step": str(self._config.spread_step),
        }
    }
```

---

## 4. SmartCloseStrategy 扩展接口

**文件**: `spread/smart_close_strategy.py`

**扩展内容**: 支持双模式平仓（限价/市价）

### 修改的接口

```python
class SmartCloseStrategy:
    """
    智能平仓策略（扩展）

    新增功能：根据利润水平选择限价或市价平仓
    """

    async def should_close(
        self,
        spread_info: SpreadInfo
    ) -> tuple[bool, str, bool]:
        """
        判断是否应该平仓（修改）

        Returns:
            (should_close, reason, use_market)
            - should_close: 是否应该平仓
            - reason: 原因说明
            - use_market: True=市价平仓, False=限价平仓

        新逻辑：
            1. 获取总开仓仓位的价差（从交易所API或本地计算）
            2. 计算两个阈值：
               - market_threshold = total_spread - market_close_spread_b
               - limit_threshold = total_spread - limit_close_spread_a
            3. 判断：
               - current_spread < market_threshold → (True, reason, True)
               - current_spread < limit_threshold → (True, reason, False)
               - 否则 → (False, "", False)

        示例输出：
            - (True, "市价平仓 | 价差0.30% < 市价阈值0.40%", True)
            - (True, "限价平仓 | 价差0.50% < 限价阈值0.60%", False)
            - (False, "", False)
        """
        pass

    async def get_total_position_spread(self) -> Decimal:
        """
        获取总开仓仓位的价差（新增）

        Returns:
            总开仓仓位的平均价差

        实现策略：
            1. 优先从交易所API获取两个总仓位的平均开仓成本
            2. 如果API失败，使用Portfolio的加权平均作为降级策略
            3. 计算价差： (lig_avg - ext_avg) / ext_avg

        降级处理：
            - 如果任一交易所API失败，记录警告
            - 自动切换到本地计算
            - 不抛出异常，确保平仓逻辑继续执行
        """
        pass

    async def _fetch_exchange_avg_prices(self) -> tuple[Decimal, Decimal]:
        """
        从交易所获取平均开仓价格（新增）

        Returns:
            (ext_avg_price, lig_avg_price)

        异常处理：
            - 如果API调用失败，返回 (Decimal("0"), Decimal("0"))
            - 并发查询两个交易所以提高效率
        """
        pass
```

### 配置依赖

需要在 `BotConfig` 中新增以下字段：

```python
@dataclass
class BotConfig:
    # 新增字段
    limit_close_spread_a: Decimal = Decimal("0.002")  # 限价平仓阈值A
    market_close_spread_b: Decimal = Decimal("0.004") # 市价平仓阈值B
```

### 状态转换

调用方根据 `use_market` 参数选择不同的状态：

```python
should_close, reason, use_market = await self.close_strategy.should_close(spread_info)

if should_close:
    if use_market:
        self.state_manager.set_state(BotState.CLOSING_MARKET, reason)
        await self._execute_market_close()
    else:
        self.state_manager.set_state(BotState.CLOSING_LIMIT, reason)
        await self._execute_limit_close()
```

---

## 5. StateManager 扩展接口

**文件**: `spread/state_manager.py`

**扩展内容**: 支持新增状态的映射和持久化

### 修改的接口

```python
class StateManager:
    """
    状态管理器（扩展）

    新增功能：
    1. 新增状态中文映射
    2. 持久化阶梯开仓配置
    3. 向后兼容旧状态
    """

    # 新增状态中文映射
    STATE_NAMES_CN = {
        # ... 现有映射 ...
        BotState.CLOSING_MARKET: "市价平仓中",
        BotState.CLOSING_LIMIT: "限价平仓中",
    }

    async def load_state(self) -> BotState:
        """
        加载状态（修改：向后兼容）

        新增逻辑：
            1. 检测旧状态 CLOSING_MAKER_WAIT，转换为 CLOSING_LIMIT
            2. 加载阶梯开仓配置（opening_count等）
        """
        pass

    async def save_state(
        self,
        state: Optional[BotState] = None,
        position: Optional[Position] = None,
        stats: Optional[BotStats] = None
    ) -> None:
        """
        保存状态（修改：保存阶梯开仓配置）

        新增逻辑：
            1. 保存 config_state 包含 opening_count
        """
        pass
```

---

## 6. SpreadArbBot 主控制器集成

**文件**: `spread/spread_arb_bot.py`

**修改内容**: 集成所有新功能模块

### 新增初始化

```python
class SpreadArbBot:
    def __init__(self, config: BotConfig):
        # ... 现有初始化 ...

        # 新增：余额检测器
        self.balance_checker: Optional[BalanceChecker] = None
```

### 修改的方法

```python
async def _check_open_signal(self) -> None:
    """
    检查开仓信号（修改）

    新增流程：
        1. 检测价差满足条件
        2. **新增**：调用 BalanceChecker.check_before_opening()
        3. 如果余额不足，跳过本次开仓
        4. 如果余额充足，继续开仓流程
    """
    pass

async def _check_close_signal(self) -> None:
    """
    检查平仓信号（修改）

    新增流程：
        1. 调用 SmartCloseStrategy.should_close()
        2. 根据返回的 use_market 选择状态
        3. 执行相应的平仓操作
    """
    pass

async def _execute_market_close(self) -> None:
    """
    执行市价平仓（新增）

    流程：
        1. 并发发送 Extended 和 Lighter 市价平仓单
        2. 等待成交确认
        3. 更新持仓和统计
        4. 转换到 IDLE 状态
    """
    pass

async def _execute_limit_close(self) -> None:
    """
    执行限价平仓（新增）

    流程：
        1. 发送 Extended 限价平仓单
        2. 等待成交（监控订单状态）
        3. 成交后发送 Lighter 对冲单
        4. 更新持仓和统计
        5. 转换到 IDLE 或 HOLDING 状态（取决于是否全部平仓）
    """
    pass
```

---

## 接口调用序列图

### 开仓流程（含余额检测）

```
SpreadArbBot                BalanceChecker           ExtendedClient           LighterClient
     │                            │                         │                      │
     ├─ _check_open_signal()       │                         │                      │
     │                            │                         │                      │
     ├─ check_before_opening() ───>│                         │                      │
     │                            │                         │                      │
     │                            ├─ get_balance() ────────>│                      │
     │                            │<─ USDT余额 ─────────────┤                      │
     │                            │                         │                      │
     │                            ├─ get_balance(symbol) ──────────────────────>│
     │                            │<─ 代币余额 ──────────────────────────────────┤
     │                            │                         │                      │
     │                            ├─ compare & calculate   │                      │
     │                            │                         │                      │
     │<─ BalanceCheckResult ──────┤                         │                      │
     │                            │                         │                      │
     ├─ is_sufficient?            │                         │                      │
     │                            │                         │                      │
     ├─ Yes: continue             │                         │                      │
     │  No: skip opening          │                         │                      │
```

### 修改挂单价格（含取消验证）

```
PriceMonitor              TradeExecutor              ExtendedClient
     │                          │                          │
     ├─ detect price change     │                          │
     │                          │                          │
     ├─ cancel_and_reorder() ──>│                          │
     │                          │                          │
     │                          ├─ cancel_order() ────────>│
     │                          │<─ OK ────────────────────┤
     │                          │                          │
     │                          ├─ verify_cancellation() ─>│
     │                          │  (轮询 get_order)        │
     │                          │<─ CANCELED ──────────────┤
     │                          │                          │
     │                          ├─ create_new_order() ────>│
     │                          │<─ order_id ──────────────┤
     │                          │                          │
     │<─ success ────────────────┤                          │
```

### 双模式平仓流程

```
SpreadArbBot            SmartCloseStrategy         Portfolio
     │                         │                        │
     ├─ _check_close() ──────>│                        │
     │                         │                        │
     │                         ├─ get_total_spread() ──>│
     │                         │<─ weighted_avg ─────────┤
     │                         │                        │
     │                         ├─ calculate thresholds  │
     │                         │                        │
     │<─ CloseModeDecision ────┤                        │
     │  (should_close,          │                        │
     │   reason, use_market)    │                        │
     │                         │                        │
     ├─ use_market?            │                        │
     │  ├─ True: market close  │                        │
     │  └─ False: limit close  │                        │
```

---

## 错误处理契约

### BalanceChecker

| 异常情况 | 返回值 | 调用方处理 |
|---------|--------|----------|
| Extended API 失败 | BalanceCheckResult(is_sufficient=False, failure_reason="Extended API错误") | 跳过开仓，记录错误 |
| Lighter API 失败 | BalanceCheckResult(is_sufficient=False, failure_reason="Lighter API错误") | 跳过开仓，记录错误 |
| 两个 API 都失败 | BalanceCheckResult(is_sufficient=False, failure_reason="两个交易所都不可用") | 跳过开仓，记录错误 |
| 数据解析失败 | BalanceCheckResult(is_sufficient=False, failure_reason="数据解析失败") | 跳过开仓，记录错误 |

**不抛出异常**，所有错误都通过返回值传递，确保调用方可以优雅降级。

### TradeExecutor.cancel_maker_order_with_verification

| 异常情况 | CancelOrderResult | 调用方处理 |
|---------|------------------|----------|
| 正常取消 | canceled=True | 继续创建新订单 |
| 超时未取消 | canceled=False, attempts=max_retries | 停止创建新订单，进入安全状态 |
| API 异常 | canceled=False, error_message=异常信息 | 停止创建新订单，进入安全状态 |

**不抛出异常**，所有错误都通过返回值传递。

---

## 性能要求

| 接口 | 最大响应时间 | 说明 |
|------|-------------|------|
| BalanceChecker.check_before_opening | 2 秒 | 包括两个 API 调用 |
| TradeExecutor.cancel_maker_order_with_verification | 15 秒 | 包括重试和验证 |
| TradeExecutor._verify_order_cancellation | 5 秒 | 单次验证超时 |
| SmartCloseStrategy.get_total_position_spread | 3 秒 | 包括两个 API 调用或本地计算 |
| SmartCloseStrategy.should_close | 3.5 秒 | 包括获取价差和计算 |

---

## 测试契约

### 单元测试要求

| 模块 | 测试覆盖率 | 关键测试用例 |
|------|----------|------------|
| BalanceChecker | >= 90% | 余额充足、不足、API失败、数据解析失败 |
| TradeExecutor 扩展 | >= 85% | 取消成功、取消失败、重试、超时 |
| ArithmeticOpenStrategy 扩展 | >= 90% | 阶梯阈值计算、开仓次数递增、重置 |
| SmartCloseStrategy 扩展 | >= 90% | 市价平仓、限价平仓、API降级 |

### 集成测试要求

- 端到端开仓流程（含余额检测）
- 端到端修改挂单价格（含取消验证）
- 端到端双模式平仓流程
- 状态持久化和恢复

---

## 下一步

基于接口契约，继续完成：
1. **quickstart.md** - 编写快速开始指南
2. 更新 agent context

---

**文档版本**: 1.0 | **最后更新**: 2026-01-19
