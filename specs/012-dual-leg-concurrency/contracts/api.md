# API契约文档：双腿并发交易重构

**分支**: `012-dual-leg-concurrency` | **日期**: 2026-01-11

## 概述

本文档定义双腿并发交易功能涉及的主要API接口和模块间契约。

## 模块接口

### 1. ConcurrentExecutor（并发执行器）

**文件**: `spread/concurrent_executor.py`

```python
class ConcurrentExecutor:
    """并发执行器 - 同时向两个交易所发送订单"""

    async def execute_dual_leg_orders(
        self,
        extended_order: Dict[str, Any],
        lighter_order: Dict[str, Any],
        opportunity: Dict[str, Any]
    ) -> ConcurrentOrderResult:
        """执行双腿并发订单

        Args:
            extended_order: Extended订单字典（由IocOrderManager创建）
            lighter_order: Lighter订单字典（由IocOrderManager创建）
            opportunity: 套利机会字典（用于日志记录）

        Returns:
            ConcurrentOrderResult对象，包含：
            - 双边订单执行结果
            - 并发发送时间差
            - 成交状态判断

        Raises:
            TimeoutError: 两个订单都超时（500ms）
            ConnectionError: 网络连接失败

        契约:
            - send_gap_ms 必须 <= 5ms（否则警告）
            - total_latency_ms 必须 <= 500ms（否则超时）
            - 必须记录send_A_ts和send_B_ts时间戳

        Example:
            result = await executor.execute_dual_leg_orders(ext_order, lit_order, opp)
            if result.is_both_filled:
                logger.info("双边成交")
            elif result.is_legging:
                rollback_handler.execute(result)
        """
```

### 2. LegRollbackHandler（单腿回滚处理器）

**文件**: `spread/leg_rollback_handler.py` [新增]

```python
class LegRollbackHandler:
    """单腿回滚处理器 - 处理单腿持仓的紧急平仓"""

    async def execute_emergency_close(
        self,
        exchange: str,
        side: str,
        quantity: Decimal,
        reason: str
    ) -> LegRollbackEvent:
        """执行紧急回滚平仓

        Args:
            exchange: 'extended' 或 'lighter'
            side: 'buy' 或 'sell'（与原持仓相反）
            quantity: 需要平仓的数量
            reason: 回滚原因（用于日志）

        Returns:
            LegRollbackEvent对象，包含：
            - 回滚执行时间
            - 回滚成交结果
            - 风险敞口时间

        契约:
            - rollback_latency_ms 必须 <= 1000ms（P0要求）
            - 必须记录[CRITICAL]日志
            - 失败时最多重试3次

        Example:
            event = await handler.execute_emergency_close('extended', 'sell', Decimal('0.01'), 'Lighter订单失败')
            if event.is_within_sla():
                logger.info("回滚成功")
        """

    def detect_legging(
        self,
        result: ConcurrentOrderResult
    ) -> Optional[LegRollbackEvent]:
        """检测单腿持仓

        Args:
            result: 并发订单执行结果

        Returns:
            如果检测到单腿持仓，返回初始化的LegRollbackEvent
            否则返回None

        契约:
            - 检测逻辑：一边success=True，另一边success=False
            - 必须在收到结果后0ms内执行
        """
```

### 3. SimpleCloseStrategy（极简平仓策略）

**文件**: `spread/simple_close_strategy.py` [新增]

```python
class SimpleCloseStrategy:
    """极简平仓策略 - 基于净价差的简化平仓逻辑"""

    def should_close(
        self,
        pair: SpreadPair,
        current_spread_rate: Decimal
    ) -> SimpleCloseDecision:
        """判断是否应该平仓

        Args:
            pair: 套利对对象（包含开仓价差信息）
            current_spread_rate: 当前价差率

        Returns:
            SimpleCloseDecision对象，包含：
            - should_close: 是否平仓
            - close_reason: 'take_profit', 'stop_loss', 或 'hold'
            - unrealized_pnl: 未实现盈亏估算

        契约:
            - 止盈: current_spread <= open_spread - target_profit
            - 止损: current_spread >= open_spread + stop_loss
            - 不考虑持仓时间（移除复杂P1-P5逻辑）

        Example:
            decision = strategy.should_close(pair, Decimal('0.0008'))
            if decision.should_close:
                logger.info(f"平仓: {decision.close_reason}")
        """

    async def execute_close(
        self,
        pair: SpreadPair,
        decision: SimpleCloseDecision
    ) -> ConcurrentOrderResult:
        """执行平仓（使用并发IOC）

        Args:
            pair: 套利对对象
            decision: 平仓决策

        Returns:
            并发订单执行结果

        契约:
            - 必须使用并发IOC模式
            - 平仓价格使用对手价（bid/ask）
        """
```

### 4. IocOrderManager（IOC订单管理器）- 扩展

**文件**: `spread/ioc_order_manager.py` [扩展]

```python
class IocOrderManager:
    """IOC订单管理器 - 扩展"""

    def create_dual_leg_orders(
        self,
        opportunity: Dict[str, Any],
        extended_orderbook: Dict,
        lighter_orderbook: Dict
    ) -> tuple[Dict, Dict]:
        """创建双腿IOC订单

        Args:
            opportunity: 套利机会字典
            extended_orderbook: Extended订单簿（bid, ask）
            lighter_orderbook: Lighter订单簿（bid, ask）

        Returns:
            (extended_order, lighter_order) 订单字典元组

        新增契约:
            - Extended订单使用timeInForce参数
            - Lighter订单使用time_in_force参数（下划线）
            - 买入价 = ask * (1 + SLIPPAGE_TOLERANCE)
            - 卖出价 = bid * (1 - SLIPPAGE_TOLERANCE)
            - SLIPPAGE_TOLERANCE默认0.05%，范围0.03%-0.05%

        Example:
            ext_order, lit_order = ioc_manager.create_dual_leg_orders(
                opportunity, ext_ob, lit_ob
            )
        """

    def handle_partial_fill(
        self,
        result: ConcurrentOrderResult
    ) -> Dict[str, Any]:
        """处理部分成交

        Args:
            result: 并发订单执行结果

        Returns:
            部分成交处理结果

        新增契约:
            - 检测部分成交：filled_qty < expected_qty
            - 记录部分成交警告日志
            - 返回未成交数量供后续处理
        """
```

### 5. RiskValidator（风控验证器）- 扩展

**文件**: `spread/risk_validator.py` [扩展]

```python
class RiskValidator:
    """风控验证器 - 扩展"""

    def validate_profitability(
        self,
        spread_rate: Decimal,
        extended_fee: Optional[Decimal] = None,
        lighter_fee: Optional[Decimal] = None
    ) -> ProfitabilityCheckResult:
        """验证利润率 - 扩展版本

        新增契约:
            - 净利 = 价差率 - 双边手续费 - 预期滑点 - 最低净利要求
            - 如果双边费率总和 > 0.06%，发出警告
            - 返回详细的利润分解

        Example:
            result = validator.validate_profitability(Decimal('0.0007'))
            # 返回: is_profitable=True, net_profit_rate=0.0002
        """

    def check_leg_risk_enhanced(
        self,
        result: ConcurrentOrderResult
    ) -> tuple[bool, str, Optional[LegRollbackEvent]]:
        """增强的单腿风险检测

        新增契约:
            - 检测单腿持仓（一边成交，一边失败）
            - 检测部分成交不对等
            - 返回初始化的LegRollbackEvent供回滚使用
        """
```

## 配置接口

### SpreadArbConfig（配置类）- 扩展

**文件**: `spread/config.py` [扩展]

```python
@dataclass
class SpreadArbConfig:
    # 并发执行配置
    enable_dual_leg_concurrent: bool = True
    concurrent_order_send_threshold_ms: float = 5.0

    # IOC订单配置
    ioc_slippage_tolerance_rate: Decimal = Decimal('0.0005')
    ioc_slippage_min_rate: Decimal = Decimal('0.0003')
    ioc_slippage_max_rate: Decimal = Decimal('0.0005')

    # 单腿回滚配置
    enable_leg_rollback: bool = True
    rollback_timeout_ms: float = 500.0
    rollback_max_retries: int = 3

    # 极简平仓配置
    enable_simple_close: bool = True
    simple_close_target_profit_rate: Decimal = Decimal('0.0002')
    simple_close_stop_loss_rate: Decimal = Decimal('0.0010')

    # 利润检查配置
    enable_enhanced_profit_check: bool = True
    min_net_profit_rate: Decimal = Decimal('0.0002')
    expected_slippage_cost_rate: Decimal = Decimal('0.0001')

    def validate_ioc_slippage(self) -> bool:
        """验证IOC滑点配置是否在有效范围内"""
        return (
            self.ioc_slippage_min_rate <=
            self.ioc_slippage_tolerance_rate <=
            self.ioc_slippage_max_rate
        )
```

## 集成接口

### Bot（主交易引擎）- 主要修改

**文件**: `spread/bot.py` [主要修改]

```python
class SpreadArbBot:
    """价差套利机器人 - 主要修改"""

    async def _open_new_pair(
        self,
        opportunity: Dict[str, Any]
    ) -> Optional[SpreadPair]:
        """开新仓 - 重构版本

        修改要点:
            1. 使用RiskValidator验证利润
            2. 使用IocOrderManager创建IOC订单
            3. 使用ConcurrentExecutor并发执行
            4. 检测单腿持仓并触发回滚
            5. 移除wait_for_fill等待逻辑

        新增契约:
            - 总执行时间 <= 500ms
            - 发送时间差 <= 5ms
            - 单腿持仓 <= 1秒内回滚
        """

    async def _monitor_pairs(
        self
    ) -> None:
        """监控持仓 - 重构版本

        修改要点:
            1. 使用SimpleCloseStrategy判断平仓
            2. 移除P1-P5复杂逻辑
            3. 移除holding_time > 300s判断
            4. 使用并发IOC平仓
        """
```

## 测试接口

### 单元测试

```python
# tests/test_dual_leg_concurrent.py
class TestConcurrentExecutor:
    async def test_concurrent_send_gap_under_5ms(self):
        """测试并发发送时间差 < 5ms"""

    async def test_both_filled_success(self):
        """测试双边成交成功场景"""

    async def test_legging_detected(self):
        """测试单腿持仓检测"""

# tests/test_leg_rollback.py
class TestLegRollbackHandler:
    async def test_rollback_under_1s(self):
        """测试回滚在1秒内完成"""

    async def test_rollback_max_retries(self):
        """测试回滚重试机制"""
```

### 集成测试

```python
# tests/integration/test_dual_leg_integration.py
class TestDualLegIntegration:
    async def test_end_to_end_dual_leg_trade(self):
        """端到端测试：双腿并发交易流程"""

    async def test_legging_rollback_flow(self):
        """端到端测试：单腿持仓回滚流程"""
```

## 性能契约

### 延迟要求

| 指标 | 目标 | 最大值 | 监控方式 |
|------|------|--------|----------|
| 并发发送时间差 | < 2ms | 5ms | PerformanceMonitor.record_concurrent_send_gap() |
| 总执行时间 | < 300ms | 500ms | PerformanceMonitor记录时间戳 |
| 单腿回滚延迟 | < 500ms | 1000ms | LegRollbackEvent.rollback_latency_ms |

### 可用性要求

| 指标 | 目值 | 监控方式 |
|------|------|----------|
| IOC订单成功率 | > 95% | SuccessTracker统计 |
| 回滚成功率 | > 99% | LegRollbackEvent.rollback_success |
| 过期数据拒绝率 | 100% | RiskValidator.validate_data_freshness |

## 错误处理

### 异常类型

```python
class ConcurrentExecutionError(Exception):
    """并发执行异常"""

class LegRollbackError(Exception):
    """单腿回滚异常"""

class IOCOrderError(Exception):
    """IOC订单异常"""

class ProfitabilityError(Exception):
    """利润不足异常"""
```

### 错误处理策略

| 错误类型 | 处理策略 | 日志级别 |
|----------|----------|----------|
| 并发发送超时（500ms） | 取消订单，记录失败 | ERROR |
| 单腿持仓 | 立即回滚，记录CRITICAL | CRITICAL |
| 利润不足 | 拒绝开仓，记录WARNING | WARNING |
| 数据过期（>500ms） | 拒绝交易，记录WARNING | WARNING |
| 回滚失败 | 告警通知，记录CRITICAL | CRITICAL |
