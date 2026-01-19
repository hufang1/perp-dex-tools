# 技术研究：价差套利系统改进

**功能**: 003-spreading-improvements | **日期**: 2026-01-19

## 研究目标

本研究解决实施计划中提出的技术问题，为阶段1的设计提供技术基础。

## 研究问题

### 1. 如何在 maker_order_monitor.py 中验证订单已成功取消？

**问题背景**：
当前系统中修改挂单价格时存在bug，旧订单可能未成功取消就创建了新订单，导致多个挂单同时存在。

**研究方案**：

**方案A：扩展 MakerOrderMonitor 支持取消订单监控**
```python
class MakerOrderMonitor:
    def start_cancellation_monitoring(self, order_id: str) -> None:
        """开始监控订单取消过程"""
        self._cancellation_target = order_id
        self._cancellation_confirmed = False

    async def handle_order_update(self, order_data: Dict[str, Any]) -> None:
        """处理WebSocket订单更新"""
        if self._cancellation_target:
            if order_data.get('id') == self._cancellation_target:
                status = order_data.get('status')
                if status in ['CANCELED', 'CANCELLED', 'FILLED']:
                    self._cancellation_confirmed = True
                    self._cancellation_target = None
```

**优点**：
- 复用现有的 WebSocket 监控机制
- 实时响应取消状态变化
- 不需要额外的 API 调用

**缺点**：
- 依赖 WebSocket 消息的可靠性
- 需要确保取消订单的 WebSocket 事件能正确触发

**方案B：调用 REST API 轮询验证**
```python
async def verify_order_cancellation(self, order_id: str, timeout: float = 10.0) -> bool:
    """通过 REST API 验证订单已取消"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        order = await self.extended_client.get_order(order_id)
        if order.status in ['CANCELED', 'CANCELLED']:
            return True
        await asyncio.sleep(0.5)
    return False
```

**优点**：
- 不依赖 WebSocket 消息
- 可以设置超时保证不会无限等待
- 更可靠的验证机制

**缺点**：
- 增加 API 调用次数
- 可能有速率限制问题

**决策：方案B（REST API 轮询验证）**

**理由**：
1. 根据边界情况说明"继续取消，直到取消成功"，需要可靠的验证机制
2. REST API 比 WebSocket 更可靠，不容易丢失消息
3. 可以通过设置合理的超时和重试间隔来控制性能影响
4. 作为取消订单后的最终确认步骤，不需要频繁调用

**实施细节**：
```python
# 在 TradeExecutor 中添加取消订单方法
async def cancel_maker_order_with_verification(
    self,
    order_id: str,
    max_retries: int = 5,
    retry_interval: float = 2.0
) -> bool:
    """
    取消订单并验证取消成功

    Args:
        order_id: 要取消的订单ID
        max_retries: 最大重试次数
        retry_interval: 重试间隔（秒）

    Returns:
        是否成功取消
    """
    for attempt in range(max_retries):
        try:
            # 调用取消订单API
            await self.extended_client.cancel_order(order_id)

            # 验证取消成功
            if await self._verify_order_cancellation(order_id, timeout=5.0):
                logger.info(f"订单取消成功: {order_id}")
                return True

            logger.warning(f"订单取消验证失败，重试 {attempt + 1}/{max_retries}")
            await asyncio.sleep(retry_interval)

        except Exception as e:
            logger.error(f"取消订单异常: {e}")
            await asyncio.sleep(retry_interval)

    return False

async def _verify_order_cancellation(self, order_id: str, timeout: float = 5.0) -> bool:
    """验证订单已取消"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            order = await self.extended_client.get_order(order_id)
            if order.status in ['CANCELED', 'CANCELLED']:
                return True
        except Exception as e:
            logger.debug(f"获取订单状态失败: {e}")

        await asyncio.sleep(0.5)

    return False
```

---

### 2. 如何在 arithmetic_open_strategy.py 中实现阶梯价差计算？

**问题背景**：
需要实现递增式开仓阈值策略，第N次开仓使用阈值 = 初始价差 + (N-1) × 步长。

**当前实现分析**：
根据现有代码，`ArithmeticOpenStrategy` 使用 `cached_open_spread` 来跟踪当前开仓价差。

**研究方案**：

**方案A：在 BotConfig 中添加开仓次数追踪**
```python
# models.py
@dataclass
class BotConfig:
    # 现有字段...
    initial_open_spread: Decimal = Decimal("0.005")  # 初始开仓价差
    spread_step: Decimal = Decimal("0.001")  # 开仓步长
    opening_count: int = 0  # 开仓次数

# arithmetic_open_strategy.py
def get_current_open_threshold(self) -> Decimal:
    """计算当前开仓阈值"""
    return self.config.initial_open_spread + (self.config.opening_count * self.config.spread_step)

async def on_open_success(self) -> None:
    """开仓成功后增加开仓次数"""
    self.config.opening_count += 1
    logger.info(f"开仓成功，当前开仓次数: {self.config.opening_count}")
```

**优点**：
- 简单直接，易于理解
- 开仓次数持久化到状态文件
- 易于调试和监控

**缺点**：
- 需要修改 BotConfig 和状态持久化逻辑
- 开仓次数需要在平仓后重置

**方案B：使用 Portfolio 中的仓位数量计算**
```python
def get_current_open_threshold(self) -> Decimal:
    """根据当前持仓数量计算阈值"""
    position_count = len(self.portfolio.get_active_positions())
    return self.config.initial_open_spread + (position_count * self.config.spread_step)
```

**优点**：
- 不需要额外追踪开仓次数
- 基于实际持仓状态计算

**缺点**：
- 如果持仓状态不一致，计算可能错误
- 难以区分是开仓还是加仓

**决策：方案A（在 BotConfig 中追踪开仓次数）**

**理由**：
1. 更精确的控制，不受持仓状态异常影响
2. 易于在平仓后重置开仓次数
3. 可以在日志中明确显示当前是第几次开仓
4. 符合用户故事2的验收场景要求

**实施细节**：
```python
# models.py 扩展
@dataclass
class BotConfig:
    # 现有字段...
    initial_open_spread: Decimal = Decimal("0.005")  # 初始开仓价差 0.5%
    spread_step: Decimal = Decimal("0.001")  # 开仓步长 0.1%

    @property
    def current_open_threshold(self) -> Decimal:
        """计算当前开仓阈值"""
        return self.initial_open_spread + (self.opening_count * self.spread_step)

# arithmetic_open_strategy.py 修改
class ArithmeticOpenStrategy:
    async def should_open(self, spread_info: SpreadInfo) -> tuple[bool, str]:
        """
        判断是否应该开仓

        使用阶梯价差阈值：第N次开仓使用阈值 = 初始价差 + (N-1) × 步长
        """
        current_threshold = self.config.current_open_threshold

        if spread_info.opening_spread >= current_threshold:
            reason = (
                f"价差 {spread_info.opening_spread:.3%} >= "
                f"阈值 {current_threshold:.3%} "
                f"(初始={self.config.initial_open_spread:.3%}, "
                f"次数={self.config.opening_count}, "
                f"步长={self.config.spread_step:.3%})"
            )
            return True, reason

        return False, ""

    async def on_position_opened(self) -> None:
        """开仓成功回调"""
        self.config.opening_count += 1
        logger.info(
            f"开仓成功，开仓次数: {self.config.opening_count}, "
            f"下次阈值: {self.config.current_open_threshold:.3%}"
        )

    async def on_all_positions_closed(self) -> None:
        """所有仓位平仓回调"""
        old_count = self.config.opening_count
        self.config.opening_count = 0
        logger.info(f"所有仓位已平仓，重置开仓次数: {old_count} -> 0")
```

**状态持久化**：
```python
# state_manager.py 扩展
async def save_state(self, ...) -> None:
    data = {
        # 现有字段...
        "config_state": {
            "opening_count": self._config.opening_count,
            "initial_open_spread": str(self._config.initial_open_spread),
            "spread_step": str(self._config.spread_step),
        }
    }

async def load_state(self) -> BotState:
    # 解析配置状态
    config_state_data = data.get("config_state")
    if config_state_data:
        self._config.opening_count = config_state_data.get("opening_count", 0)
        logger.info(f"策略状态已恢复: 开仓次数={self._config.opening_count}")
```

---

### 3. 如何从交易所 API 获取平均开仓成本？

**问题背景**：
双模式平仓逻辑需要获取总开仓仓位的平均价差，这需要从交易所获取两个总仓位的平均开仓成本。

**研究方案**：

**方案A：调用交易所 REST API 获取持仓信息**
```python
# Extended 交易所
async def get_position(self, symbol: str) -> PositionInfo:
    """获取持仓信息"""
    response = await self._request("GET", f"/positions/{symbol}")
    return PositionInfo(
        symbol=response['symbol'],
        size=Decimal(response['size']),
        avg_entry_price=Decimal(response['avg_entry_price']),  # 平均开仓价格
        unrealized_pnl=Decimal(response['unrealized_pnl']),
    )

# Lighter 交易所
async def get_position(self, symbol: str) -> PositionInfo:
    """获取持仓信息"""
    response = await self._request("GET", f"/api/v1/positions")
    for pos in response:
        if pos['symbol'] == symbol:
            return PositionInfo(
                symbol=pos['symbol'],
                size=Decimal(pos['size']),
                avg_entry_price=Decimal(pos['entryPrice']),  # 平均开仓价格
                unrealized_pnl=Decimal(pos['unrealized_pnl']),
            )
```

**优点**：
- 直接从交易所获取，数据权威
- 实时反映实际持仓成本

**缺点**：
- 依赖交易所 API 提供此功能
- 如果 API 不支持或返回错误，需要降级处理

**方案B：使用本地记录的加权平均计算**
```python
# 在 Portfolio 中计算
class Portfolio:
    @property
    def weighted_avg_entry_spread(self) -> Decimal:
        """计算加权平均开仓价差"""
        if not self.positions or self.total_quantity == 0:
            return Decimal("0")

        total_spread_value = Decimal("0")
        for pos in self.positions:
            if pos.is_active:
                total_spread_value += pos.open_spread * pos.quantity

        return total_spread_value / self.total_quantity

    def get_avg_entry_prices(self) -> tuple[Decimal, Decimal]:
        """
        获取两个交易所的平均开仓价格

        Returns:
            (ext_avg_price, lig_avg_price)
        """
        if not self.positions or self.total_quantity == 0:
            return Decimal("0"), Decimal("0")

        ext_total = Decimal("0")
        lig_total = Decimal("0")
        for pos in self.positions:
            if pos.is_active:
                ext_total += pos.ext_price * pos.quantity
                lig_total += pos.lig_price * pos.quantity

        return ext_total / self.total_quantity, lig_total / self.total_quantity
```

**优点**：
- 不依赖交易所 API
- 基于本地记录，计算可靠
- 已经在 016-spread-optimize 中实现了类似功能

**缺点**：
- 如果本地记录与交易所实际持仓不一致，会有偏差
- 需要确保本地记录的准确性

**决策：方案A为主，方案B为降级策略**

**理由**：
1. 根据用户故事3的说明，优先从交易所 API 获取
2. 如果交易所 API 失败，使用本地加权平均作为降级
3. 这样既有权威性，又有容错能力

**实施细节**：
```python
# smart_close_strategy.py 扩展
class SmartCloseStrategy:
    async def get_total_position_spread(self) -> Decimal:
        """
        获取总开仓仓位的价差

        Returns:
            总开仓仓位的平均价差
        """
        try:
            # 方案A：从交易所获取
            ext_avg, lig_avg = await self._fetch_exchange_avg_prices()
            if ext_avg > 0 and lig_avg > 0:
                total_spread = (lig_avg - ext_avg) / ext_avg
                logger.debug(f"从交易所获取平均价差: {total_spread:.3%}")
                return total_spread
        except Exception as e:
            logger.warning(f"从交易所获取平均价格失败: {e}，使用本地记录")

        # 方案B：使用本地记录的加权平均
        total_spread = self.portfolio.weighted_avg_entry_spread
        logger.debug(f"使用本地平均价差: {total_spread:.3%}")
        return total_spread

    async def _fetch_exchange_avg_prices(self) -> tuple[Decimal, Decimal]:
        """从交易所获取平均开仓价格"""
        # 并发获取两个交易所的持仓信息
        ext_pos, lig_pos = await asyncio.gather(
            self.extended_client.get_position(self.config.symbol),
            self.lighter_client.get_position(self.config.symbol),
            return_exceptions=True
        )

        ext_avg = ext_pos.avg_entry_price if not isinstance(ext_pos, Exception) else Decimal("0")
        lig_avg = lig_pos.avg_entry_price if not isinstance(lig_pos, Exception) else Decimal("0")

        return ext_avg, lig_avg
```

---

### 4. 双模式平仓需要新增哪些状态？

**问题背景**：
需要区分市价平仓和限价平仓，两种模式的状态转换逻辑不同。

**当前状态分析**：
根据 state_manager.py，当前状态包括：
- `IDLE`: 空闲
- `OPENING`: 开仓中
- `OPENING_MAKER_WAIT`: 开仓挂单等待成交
- `OPENING_WAIT`: 开仓等待确认
- `HOLDING`: 持仓中
- `CLOSING`: 平仓中
- `CLOSING_MAKER_WAIT`: 平仓挂单等待成交
- `LIGHTER_HEDGING`: lighter对冲中
- `CLOSING_WAIT`: 平仓等待确认
- `PAUSED`: 风控暂停
- `ERROR`: 错误

**研究方案**：

**方案A：复用现有状态，通过参数区分模式**
```python
# 不新增状态，在 CLOSING 和 CLOSING_MAKER_WAIT 中通过参数区分
async def close_position(self, use_market: bool = False) -> None:
    """平仓"""
    if use_market:
        # 市价平仓，直接发送市价单
        await self._execute_market_close()
        self.state_manager.set_state(BotState.CLOSING, "市价平仓")
    else:
        # 限价平仓，发送限价单等待成交
        await self._execute_limit_close()
        self.state_manager.set_state(BotState.CLOSING_MAKER_WAIT, "限价平仓")
```

**优点**：
- 不需要修改状态枚举
- 向后兼容

**缺点**：
- 状态含义不明确，CLOSING 可能是市价也可能是限价
- 日志和监控不够清晰

**方案B：新增市价平仓专用状态**
```python
# models.py 扩展
class BotState(Enum):
    # 现有状态...
    CLOSING_MARKET = "CLOSING_MARKET"  # 市价平仓中
    CLOSING_LIMIT = "CLOSING_LIMIT"    # 限价平仓中（取代 CLOSING_MAKER_WAIT）

# state_manager.py 扩展
STATE_NAMES_CN = {
    # 现有映射...
    BotState.CLOSING_MARKET: "市价平仓中",
    BotState.CLOSING_LIMIT: "限价平仓中",
}
```

**优点**：
- 状态含义明确
- 日志和监控清晰
- 易于调试和问题排查

**缺点**：
- 需要修改状态枚举
- 需要更新状态转换逻辑

**决策：方案B（新增市价平仓专用状态）**

**理由**：
1. 用户故事3明确说明"市价平仓和限价平仓的状态变化是不一样的"
2. 状态明确有助于监控和调试
3. 方便在未来添加不同的处理逻辑

**实施细节**：
```python
# models.py
class BotState(Enum):
    """机器人状态枚举"""
    IDLE = "IDLE"
    OPENING = "OPENING"
    OPENING_MAKER_WAIT = "OPENING_MAKER_WAIT"
    OPENING_WAIT = "OPENING_WAIT"
    HOLDING = "HOLDING"
    CLOSING_LIMIT = "CLOSING_LIMIT"      # 限价平仓中（等待成交）
    CLOSING_MARKET = "CLOSING_MARKET"    # 市价平仓中（立即执行）
    LIGHTER_HEDGING = "LIGHTER_HEDGING"
    CLOSING_WAIT = "CLOSING_WAIT"
    PAUSED = "PAUSED"
    ERROR = "ERROR"

# smart_close_strategy.py
class SmartCloseStrategy:
    async def should_close(self, spread_info: SpreadInfo) -> tuple[bool, str, bool]:
        """
        判断是否应该平仓

        Returns:
            (should_close, reason, use_market)
            use_market: True表示市价平仓，False表示限价平仓
        """
        total_spread = await self.get_total_position_spread()

        # 计算阈值
        market_close_threshold = total_spread - self.config.market_close_spread_b
        limit_close_threshold = total_spread - self.config.limit_close_spread_a

        current_spread = spread_info.closing_spread

        # 市价平仓：利润大，立即兑现
        if current_spread < market_close_threshold:
            reason = (
                f"价差 {current_spread:.3%} < 市价平仓阈值 {market_close_threshold:.3%} "
                f"(总开仓价差={total_spread:.3%}, B={self.config.market_close_spread_b:.3%})"
            )
            return True, reason, True

        # 限价平仓：利润小，使用限价单降低成本
        if current_spread < limit_close_threshold:
            reason = (
                f"价差 {current_spread:.3%} < 限价平仓阈值 {limit_close_threshold:.3%} "
                f"(总开仓价差={total_spread:.3%}, A={self.config.limit_close_spread_a:.3%})"
            )
            return True, reason, False

        return False, "", False

# spread_arb_bot.py 主循环
async def _check_close_signal(self) -> None:
    """检查平仓信号"""
    should_close, reason, use_market = await self.close_strategy.should_close(self.current_spread)

    if should_close:
        if use_market:
            self.state_manager.set_state(BotState.CLOSING_MARKET, reason)
            await self._execute_market_close()
        else:
            self.state_manager.set_state(BotState.CLOSING_LIMIT, reason)
            await self._execute_limit_close()
```

**状态转换图**：
```
HOLDING
  ├─ 价差 < 市价平仓阈值 → CLOSING_MARKET → IDLE（立即完成）
  └─ 市价平仓阈值 < 价差 < 限价平仓阈值 → CLOSING_LIMIT → HOLDING（成交后）或 LIGHTER_HEDGING（部分成交）
```

---

## 技术决策总结

| 问题 | 决策方案 | 理由 |
|------|---------|------|
| 取消订单验证 | REST API 轮询验证 | 更可靠，符合"持续重试直到取消成功"的要求 |
| 阶梯价差计算 | 在 BotConfig 中追踪开仓次数 | 精确控制，易于调试和持久化 |
| 平均开仓成本 | 交易所 API + 本地加权平均降级 | 权威性与容错能力兼顾 |
| 双模式平仓状态 | 新增 CLOSING_MARKET 和 CLOSING_LIMIT | 状态明确，易于监控和调试 |

---

## 下一步

基于本研究结果，进入阶段1设计：
1. **data-model.md** - 定义新增和修改的数据模型
2. **contracts/** - 定义模块间接口契约
3. **quickstart.md** - 编写快速开始指南

---

**研究完成日期**: 2026-01-19
