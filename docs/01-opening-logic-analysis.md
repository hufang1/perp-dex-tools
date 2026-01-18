# 价差套利程序开仓逻辑详细分析

## 目录
1. [状态机概览](#1-状态机概览)
2. [OPENING 状态详细分析](#2-opening-状态详细分析)
3. [OPENING_WAIT 状态详细分析](#3-opening_wait状态详细分析)
4. [开仓触发条件](#4-开仓触发条件)
5. [开仓调用的方法和API](#5-开仓调用的方法和api)
6. [完整执行流程](#6-完整执行流程)
7. [平仓逻辑详细分析](#7-平仓逻辑详细分析)
8. [CLOSING 状态详细分析](#8-closing-状态详细分析)
9. [平仓调用的方法和API](#9-平仓调用的方法和api)
10. [CLOSING_WAIT 状态详细分析](#10-closing_wait状态详细分析)
11. [平仓完整执行流程](#11-平仓完整执行流程)
12. [平仓总结](#12-平仓总结)

---

## 1. 状态机概览

### 1.1 相关状态定义

```python
class BotState(Enum):
    IDLE = "IDLE"                      # 空闲，等待机会
    OPENING = "OPENING"                # 开仓中（发送订单）
    OPENING_WAIT = "OPENING_WAIT"      # 开仓后等待确认仓位
    HOLDING = "HOLDING"                # 持仓中
    CLOSING = "CLOSING"                # 平仓中
    PAUSED = "PAUSED"                  # 风控暂停模式
    ERROR = "ERROR"                    # 错误状态
```

### 1.2 开仓相关状态转换路径

```
┌─────────┐
│  IDLE   │  首次开仓入口
└────┬────┘
     │ 满足开仓条件
     ↓
┌─────────┐
│ OPENING │  发送订单
└────┬────┘
     │ 订单已发送（不管成功失败）
     ↓
┌─────────────┐
│OPENING_WAIT │  等待仓位确认（最多10秒）
└─────┬───────┘
     │
     ├──────────┬─────────────┬─────────────┐
     │          │             │             │
  仓位确认成功   两边都是0    仓位不对等    超时
     │          │             │             │
     ↓          ↓             ↓             ↓
┌─────────┐  ┌───────┐   ┌───────┐   ┌───────┐
│ HOLDING │  │ IDLE  │   │检查  │   │ IDLE  │
└─────────┘  └───────┘   │决定  │   └───────┘
                       └──↓───┘
                     ├─ HOLDING
                     └─ IDLE/PAUSED

┌─────────┐
│HOLDING  │  继续开仓（加仓）
└────┬────┘
     │ 满足加仓条件
     ↓
┌─────────┐
│ OPENING │  发送加仓订单
└────┬────┘
     │ 订单已发送
     ↓
┌─────────────┐
│OPENING_WAIT │  等待加仓确认
└─────┬───────┘
     │
     └──→（后续逻辑同首次开仓）
```

---

## 2. OPENING 状态详细分析

### 2.1 状态入口

**文件位置**: `spread/spread_arb_bot.py:407-498`

```python
async def _process_opening_state(self) -> None:
    """处理 OPENING 状态：执行开仓"""
```

**进入 OPENING 状态的条件**:
- 从 IDLE 进入：首次开仓
- 从 HOLDING 进入：继续开仓（加仓）

### 2.2 状态核心职责

OPENING 状态的**唯一职责**是：**发送开仓订单**，不管订单成功还是失败，都直接进入 OPENING_WAIT 状态。

### 2.3 执行步骤详解

#### Step 1: 记录开仓时间
```python
# spread_arb_bot.py:412-413
import time
self._last_open_time = time.time()
```
**目的**: 防止连续开仓导致 API 限流

#### Step 2: 获取当前价差
```python
# spread_arb_bot.py:415-422
spread_info = self.spread_monitor.get_current_spread()

if spread_info is None or not spread_info.is_valid():
    logger.warning("无法获取价差信息，取消开仓")
    self.state_manager.set_state(BotState.IDLE, "无法获取价差信息")
    await self.state_manager.save_state()
    return
```

**API调用**: `SpreadMonitor.get_current_spread()`
- 内部并发获取两个交易所的 BBO 价格
- 计算价差百分比

#### Step 3: 执行开仓（核心）
```python
# spread_arb_bot.py:424-428
result = await self.trade_executor.execute_open_position(
    self.config.target_quantity,
    spread_info
)
```

**返回对象**: `ExecutionResult`
```python
@dataclass
class ExecutionResult:
    success: bool                          # 订单是否成功
    extended_order_id: Optional[str]       # Extended订单ID
    lighter_order_id: Optional[str]        # Lighter订单ID
    extended_price: Optional[Decimal]      # Extended成交价格
    lighter_price: Optional[Decimal]       # Lighter成交价格
    extended_filled: bool                   # Extended是否成交
    lighter_filled: bool                    # Lighter是否成交
    error_message: Optional[str]            # 错误信息
```

#### Step 4: 创建持仓记录（临时）
```python
# spread_arb_bot.py:441-453
position = Position(
    state=PositionState.LONG,  # 多头：Extended买入，Lighter卖出
    extended_entry_price=result.extended_price or spread_info.ext_ask,
    lighter_entry_price=result.lighter_price or spread_info.lig_bid,
    entry_spread=spread_info.spread_pct,
    entry_time=datetime.now(),
    extended_quantity=self.config.target_quantity,
    lighter_quantity=-self.config.target_quantity,
    extended_order_id=result.extended_order_id,
    lighter_order_id=result.lighter_order_id,
)

self.state_manager.update_position(position)
```

**关键点**:
- 此时仓位还未确认，只是创建临时记录
- `extended_quantity` > 0（多头）
- `lighter_quantity` < 0（空头）

#### Step 5: 创建待确认仓位对象
```python
# spread_arb_bot.py:462-472
self._pending_open_position = OpenPosition(
    position_id=str(uuid.uuid4()),
    open_time=datetime.now().timestamp(),
    ext_price=result.extended_price or spread_info.ext_ask,
    lig_price=result.lighter_price or spread_info.lig_bid,
    open_spread=spread_info.spread_pct,  # 重要：记录开仓价差
    quantity=self.config.target_quantity,
    ext_order_id=result.extended_order_id,
    lig_order_id=result.lighter_order_id,
    is_active=True,
)
```

**用途**: 等待确认成功后添加到智能平仓系统

#### Step 6: 输出订单状态日志
```python
# spread_arb_bot.py:475-490
if result.success:
    logger.info(f"订单发送成功: Ext={result.extended_price} Lig={result.lighter_price} 价差={spread_info.spread_pct:.3%}")
elif result.extended_order_id or result.lighter_order_id:
    logger.warning(f"订单发送超时/部分成功: Ext_filled={result.extended_filled} Lig_filled={result.lighter_filled}")
else:
    logger.error(f"订单发送失败: {result.error_message}，仍需检查仓位以防部分成交")
```

#### Step 7: 切换到 OPENING_WAIT 状态
```python
# spread_arb_bot.py:493-498
import time
self._opening_wait_start_time = time.time()
self._last_open_success_time = time.time()
logger.info(f"等待仓位确认 (超时{self.config.open_wait_timeout}s)")
self.state_manager.set_state(BotState.OPENING_WAIT, f"订单已发送: Ext={result.extended_order_id}, Lig={result.lighter_order_id}")
await self.state_manager.save_state()
```

**关键设计决策**:
1. **不管订单状态如何都进入 OPENING_WAIT**：即使订单失败也要检查实际仓位（防止部分成交）
2. **不更新 cached_open_spread**：等待仓位确认成功后再更新
3. **不添加到智能平仓系统**：等待仓位确认成功后再添加

### 2.4 OPENING 状态不处理的事项

```python
# spread_arb_bot.py:455-461
# 注意：不在这里更新 cached_open_spread！
# 需要等到仓位确认成功后再更新（在 OPENING_WAIT 状态中）
# 如果仓位确认失败并回滚，cached_open_spread 保持不变

# 注意：不在这里添加仓位到智能平仓系统！
# 需要等到仓位确认成功后再添加（在 OPENING_WAIT 状态中）
```

**原因**:
- 订单状态可能不准确（网络延迟、交易所处理时间）
- 实际仓位是最终判断标准
- 避免误更新策略状态

---

## 3. OPENING_WAIT 状态详细分析

### 3.1 状态入口

**文件位置**: `spread/spread_arb_bot.py:672-878`

```python
async def _process_opening_wait_state(self) -> None:
    """处理 OPENING_WAIT 状态：等待确认仓位"""
```

**进入条件**: 从 OPENING 状态自动切换（订单已发送后）

### 3.2 状态核心职责

OPENING_WAIT 状态的**核心职责**是：
1. **验证实际仓位**：通过查询交易所 API 获取实际持仓
2. **判断开仓结果**：根据实际仓位决定下一步状态
3. **更新策略状态**：只在确认成功后才更新 cached_open_spread 和添加仓位

### 3.3 执行步骤详解

#### Step 1: 初始化等待时间
```python
# spread_arb_bot.py:676-678
current_time = time.time()
if self._opening_wait_start_time is None:
    self._opening_wait_start_time = current_time
```

#### Step 2: 检查超时
```python
# spread_arb_bot.py:680-697
elapsed = current_time - self._opening_wait_start_time
timeout = self.config.open_wait_timeout  # 默认10秒

if elapsed > timeout:
    logger.warning(f"等待超时({elapsed:.1f}s)，强平")
    await self._force_close_positions()
    # 强平后进入冷却期
    self._last_open_fail_time = time.time()
    # 检查API错误，决定进入PAUSED还是IDLE
    if self._api_error_count > 0:
        self.state_manager.set_state(BotState.PAUSED, "等待超时且API异常，已强平")
    else:
        self.state_manager.set_state(BotState.IDLE, f"等待超时({elapsed:.1f}s)，已强平")
    return
```

**超时处理**: 强制平仓所有仓位，防止风险暴露

#### Step 3: 并发获取实际仓位（核心）
```python
# spread_arb_bot.py:700-701
ext_position = await self.extended_client.get_account_positions()
lig_position = await self.lighter_client.get_account_positions()
```

**API调用详情**:

**Extended API**:
```python
# exchanges/extended.py
async def get_account_positions(self) -> Decimal:
    """获取当前持仓数量"""
    account = await self.perpetual_trading_client.get_positions()
    # 返回绝对值（正数）
    return account.total_quantity
```

**Lighter API**:
```python
# exchanges/lighter.py
async def get_account_positions(self) -> Decimal:
    """获取当前持仓数量"""
    account = await self.lighter_client.account_api.account()
    # 计算净持仓：long_positions - short_positions
    # 返回绝对值（正数）
    return abs(total_position)
```

#### Step 4: 仓位验证逻辑
```python
# spread_arb_bot.py:703-718
tolerance = Decimal("0.001")

# 计算仓位差值
ext_lig_diff = abs(ext_position - lig_position)
positions_match = ext_lig_diff < tolerance

# 检查是否都是0
both_zero = ext_position < tolerance and lig_position < tolerance

logger.info(f"仓位验证: Ext={ext_position} Lig={lig_position} diff={ext_lig_diff} {'✓' if positions_match else '✗'}")
```

**验证逻辑**:
- `positions_match = True`: 两边仓位相等（套利成功或两边都没开）
- `both_zero = True`: 两边都是0（开仓失败）
- `positions_match = False` and `not both_zero`: 仓位不对等（部分成交）

#### Step 5: 处理验证结果

##### 场景A: 两边都是0（开仓失败）
```python
# spread_arb_bot.py:721-750
if positions_match and both_zero:
    logger.warning(f"开仓失败：两边都没有仓位")

    # 1. CSV埋点
    self._log_open_to_csv(status='开仓失败_两边无仓位', ...)

    # 2. 进入冷却期
    self._last_open_fail_time = time.time()

    # 3. 清除待确认仓位
    self._pending_open_position = None

    # 4. 切换到 IDLE 状态
    self.state_manager.set_state(BotState.IDLE, "开仓失败：两边都没有仓位")
    self._opening_wait_start_time = None
```

**状态变化**:
- `cached_open_spread`: **保持不变**（失败不更新）
- 下一状态: `IDLE`
- 冷却时间: 10秒

##### 场景B: 两边相等且非0（开仓成功）
```python
# spread_arb_bot.py:751-779
logger.info(f"仓位确认成功 Ext={ext_position} Lig={lig_position}")

# 1. 添加到智能平仓系统
self.close_strategy.add_position(self._pending_open_position)

# 2. 更新 cached_open_spread（只增不减）
logger.info(f"准备更新开仓价差: 当前={self.config.cached_open_spread:.3%}, 新值={self._pending_open_position.open_spread:.3%}")
self.open_strategy.update_cached_spread(self._pending_open_position.open_spread)
logger.info(f"更新后开仓价差: {self.config.cached_open_spread:.3%}")

# 3. CSV埋点
self._log_open_to_csv(status='开仓成功', ...)

# 4. 清除待确认仓位
self._pending_open_position = None

# 5. 切换到 HOLDING 状态
self.state_manager.set_state(BotState.HOLDING, f"仓位确认成功 Ext={ext_position} Lig={lig_position}")
self._opening_wait_start_time = None
```

**状态变化**:
- `cached_open_spread`: **更新**为本次开仓价差（只增不减）
- 持仓记录: 添加到 `SmartCloseStrategy.portfolio`
- 下一状态: `HOLDING`

##### 场景C: 仓位不对等（部分成交）
```python
# spread_arb_bot.py:780-803
elif elapsed >= 2.0 and not positions_match:
    # 等待2秒后仓位仍不一致
    logger.warning(f"仓位验证失败 (elapsed={elapsed:.1f}s >= 2.0s): Ext={ext_position} Lig={lig_position}")

    # 1. 获取当前持仓量（回滚前）
    portfolio = self.close_strategy.get_portfolio()
    current_qty = portfolio.total_quantity if portfolio else Decimal("0")

    # 2. 只回滚多出来的部分（不平全仓）
    await self._rollback_partial_positions(current_qty, ext_position, lig_position)

    # 3. 检查回滚后实际仓位，决定下一步状态
    # - 两边都平了 → IDLE
    # - 两边都有且相等 → HOLDING
    # - 仍不一致 → 强制全平 → IDLE/PAUSED
```

**回滚策略**:
```python
# 取两边较小仓位作为基准，平掉多出来的部分
base_qty = min(ext_current, lig_current)
ext_extra = max(Decimal("0"), ext_current - base_qty)
lig_extra = max(Decimal("0"), lig_current - base_qty)

# 平掉多出的部分
await self._force_close_positions()
```

### 3.4 OPENING_WAIT 状态的循环机制

OPENING_WAIT 状态是**循环执行**的，主交易循环每1秒调用一次：

```python
# spread_arb_bot.py:268-269
elif state == BotState.OPENING_WAIT:
    await self._process_opening_wait_state()
```

**检查频率**: 每1秒一次
**超时时间**: 10秒（配置项 `open_wait_timeout`）

---

## 4. 开仓触发条件

### 1.1 状态机触发路径

开仓逻辑主要在 **IDLE** 和 **HOLDING** 状态下触发：

#### IDLE状态触发（首次开仓）
**文件位置**: `spread/spread_arb_bot.py:298-406`

```python
async def _process_idle_state(self) -> None:
    """处理 IDLE 状态：监控价差，寻找开仓机会"""
```

**触发条件**:
1. **订单簿就绪**: `self.order_book_manager.is_ready()` 返回 True
2. **冷却期检查**:
   - 失败冷却期: 距离上次开仓失败 >= 10秒
   - 成功冷却期: 距离上次开仓成功 >= 3秒
3. **价差条件**: 通过等差数列开仓策略判断

#### HOLDING状态触发（继续开仓/加仓）
**文件位置**: `spread/spread_arb_bot.py:500-562`

```python
async def _process_holding_state(self) -> None:
    """处理 HOLDING 状态：监控价差，寻找平仓机会和继续开仓机会"""
```

**额外条件**:
- 距离上次开仓时间 >= 5秒（防止API限流）

---

### 1.2 等差数列开仓策略判断

**文件位置**: `spread/arithmetic_open_strategy.py:41-82`

```python
def should_open(self, spread_info: RealTimeSpreadInfo) -> tuple[bool, str]:
    """判断是否应该开仓"""
```

#### 首次开仓（cached_open_spread == 0）
```
条件: current_spread >= min_spread_threshold
示例: 价差0.08% >= 阈值0.07% → 开仓
```

#### 后续开仓（cached_open_spread > 0）
```
条件: current_spread >= cached_open_spread + spread_step
示例:
  - 上次开仓价差: 0.08%
  - 步长: 0.005%
  - 当前价差: 0.09%
  - 判断: 0.09% >= 0.085% → 开仓
```

**核心原则**:
- **只增不减**: 价差缩小时不降低上次开仓价差
- **等差递增**: 每次开仓后阈值递增 spread_step

---

### 1.3 风控验证

**文件位置**: `spread/spread_arb_bot.py:393-401`

```python
validation = await self.risk_manager.validate_open_position(
    self.order_book_manager,
    self.config.target_quantity,
    spread_info
)
```

风控检查包括:
- 订单簿深度足够
- 流动性检查
- 仓位限制检查

---

## 2. 开仓调用的方法和API

### 2.1 核心调用链

```
_process_idle_state() / _process_holding_state()
  ↓
trade_executor.execute_open_position(quantity, spread_info)
  ↓
[并发执行]
  ├─ _place_extended_order_taker("buy", quantity, ext_price)
  └─ _place_lighter_order_taker("sell", quantity, lig_price)
```

---

### 2.2 execute_open_position 方法

**文件位置**: `spread/trade_executor.py:86-270`

#### Step 1: 并发获取BBO价格
```python
# 并发获取两个交易所的BBO价格
ext_bbo_future = self.extended_client.fetch_bbo_prices(contract_id)
lig_bbo_future = self.lighter_client.fetch_bbo_prices(contract_id)

ext_bid, ext_ask = await ext_bbo_future
lig_bid, lig_ask = await lig_bbo_future
```

#### Step 2: 创建价格快照
**文件位置**: `spread/price_snapshot.py`

```python
price_snapshot = PriceSnapshot(
    ext_bid=ext_bid,
    ext_ask=ext_ask,
    ext_timestamp=ext_fetch_time,
    lig_bid=lig_bid,
    lig_ask=lig_ask,
    lig_timestamp=lig_fetch_time,
    time_delta=time_delta
)
```

**价格同步验证**:
- 时间差 < 10ms (`time_delta < 0.01`)
- 所有价格 > 0
- bid < ask (两边都满足)

#### Step 3: 计算Taker价格（带滑点保护）
**文件位置**: `spread/price_snapshot.py:75-91`

```python
def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]:
    """计算taker价格（0.02%滑点保护）"""
    ext_price = self.ext_ask * Decimal('1.0002')  # 买入ask+0.02%
    lig_price = self.lig_bid * Decimal('0.9998')  # 卖出bid-0.02%
    return ext_price, lig_price
```

**滑点保护说明**:
- Extended买入: `ask * 1.0002` (跨越ask，确保即时成交)
- Lighter卖出: `bid * 0.9998` (跨越bid，确保即时成交)

#### Step 4: 价格一致性验证
```python
if not price_snapshot.validate_price_consistency():
    return ExecutionResult(success=False, error_message="价差异常")
```

验证条件: `ext_buy_price < lig_sell_price` (套利有盈利空间)

#### Step 5: 并发发送订单
```python
results = await asyncio.gather(
    self._place_extended_order_taker("buy", quantity, ext_price),
    self._place_lighter_order_taker("sell", quantity, lig_price),
    return_exceptions=True
)
```

---

### 2.3 Extended Taker订单

**文件位置**: `exchanges/extended.py:301-399`

```python
async def place_taker_order(self, contract_id, quantity, side, price):
    """下Extended Taker订单（IOC模式）"""
    order_result = await self.perpetual_trading_client.place_order(
        market_name=contract_id,
        amount_of_synthetic=quantity,
        price=price,
        side=OrderSide.BUY,  # 开仓时买入
        time_in_force=TimeInForce.IOC,  # 立即成交或取消
        post_only=False,  # 允许taker成交
        expire_time=utc_now() + timedelta(minutes=1),
    )
```

**API调用**:
- 使用官方SDK: `x10.perpetual.trading_client.PerpetualTradingClient`
- 订单类型: IOC (Immediate or Cancel)
- 执行模式: Taker (吃单，即时成交)

---

### 2.4 Lighter Taker订单

**文件位置**: `exchanges/lighter.py:271-325`

```python
async def place_limit_order(self, contract_id, quantity, price, side, time_in_force=0):
    """下Lighter Taker订单（IOC模式）"""
    order_params = {
        'market_index': self.config.contract_id,
        'client_order_index': client_order_index,
        'base_amount': int(quantity * self.base_amount_multiplier),
        'price': int(price * self.price_multiplier),
        'is_ask': True,  # 卖出
        'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
        'time_in_force': 0,  # IOC
        'reduce_only': False,
        'trigger_price': 0,
        'order_expiry': 0,
    }

    create_order, tx_hash, error = await self.lighter_client.create_order(**order_params)
```

**API调用**:
- 使用官方SDK: `lighter.SignerClient`
- 订单类型: 限价单 + IOC (time_in_force=0)
- 执行模式: Taker (跨越价差即时成交)

---

## 3. 开仓后的状态变化

### 3.1 状态转换流程

```
IDLE/HOLDING
  ↓ (满足开仓条件)
OPENING (执行开仓)
  ↓ (订单已发送)
OPENING_WAIT (等待仓位确认)
  ↓ (仓位检查)
  ├─ 成功 → HOLDING (进入持仓)
  ├─ 失败 → IDLE (进入冷却)
  └─ 超时 → 强平 → IDLE/PAUSED
```

---

### 3.2 OPENING状态处理

**文件位置**: `spread/spread_arb_bot.py:407-498`

**关键操作**:
1. 记录开仓时间（防止连续开仓API限流）
2. 调用 `execute_open_position()`
3. 创建Position对象
4. **不更新** `cached_open_spread`（等待确认成功后更新）
5. **不添加** 仓位到智能平仓系统（等待确认后添加）
6. 转换到 `OPENING_WAIT` 状态

```python
# 创建持仓记录（先创建，后续验证）
position = Position(
    state=PositionState.LONG,
    extended_entry_price=result.extended_price or spread_info.ext_ask,
    lighter_entry_price=result.lighter_price or spread_info.lig_bid,
    entry_spread=spread_info.spread_pct,
    entry_time=datetime.now(),
    extended_quantity=self.config.target_quantity,
    lighter_quantity=-self.config.target_quantity,
    extended_order_id=result.extended_order_id,
    lighter_order_id=result.lighter_order_id,
)

self.state_manager.update_position(position)

# 预创建OpenPosition对象，等待确认后添加
self._pending_open_position = OpenPosition(
    position_id=str(uuid.uuid4()),
    open_time=datetime.now().timestamp(),
    ext_price=result.extended_price or spread_info.ext_ask,
    lig_price=result.lighter_price or spread_info.lig_bid,
    open_spread=spread_info.spread_pct,
    quantity=self.config.target_quantity,
    ext_order_id=result.extended_order_id,
    lig_order_id=result.lighter_order_id,
    is_active=True,
)

# 转换到OPENING_WAIT状态
self._opening_wait_start_time = time.time()
self.state_manager.set_state(BotState.OPENING_WAIT, "订单已发送，等待确认")
```

---

### 3.3 OPENING_WAIT状态处理

**文件位置**: `spread/spread_arb_bot.py:672-878`

#### 3.3.1 仓位验证逻辑
```python
# 并发获取两边仓位
ext_position = await self.extended_client.get_account_positions()
lig_position = await self.lighter_client.get_account_positions()

# 验证仓位是否相等
ext_lig_diff = abs(ext_position - lig_position)
positions_match = ext_lig_diff < tolerance  # tolerance = 0.001

both_zero = ext_position < tolerance and lig_position < tolerance
```

#### 3.3.2 成功场景（两边仓位相等且非零）

```python
if positions_match and not both_zero:
    # 仓位确认成功
    logger.info(f"仓位确认成功 Ext={ext_position} Lig={lig_position}")

    # 1. 添加仓位到智能平仓系统
    self.close_strategy.add_position(self._pending_open_position)

    # 2. 更新cached_open_spread（只在确认成功后更新）
    self.open_strategy.update_cached_spread(
        self._pending_open_position.open_spread
    )

    # 3. CSV埋点：开仓成功
    self._log_open_to_csv(status='开仓成功', ...)

    # 4. 转换到HOLDING状态
    self.state_manager.set_state(BotState.HOLDING, "仓位确认成功")
    self._pending_open_position = None
```

**状态变化**:
- `cached_open_spread`: 更新为本次开仓价差（只增不减）
- 持仓记录: 添加到智能平仓系统的Portfolio中
- 机器人状态: `OPENING_WAIT` → `HOLDING`

#### 3.3.3 失败场景（两边都没开）

```python
if positions_match and both_zero:
    # 开仓失败：两边都没有仓位
    logger.warning(f"开仓失败：两边都没有仓位")

    # 1. CSV埋点
    self._log_open_to_csv(status='开仓失败_两边无仓位', ...)

    # 2. 进入冷却期
    self._last_open_fail_time = time.time()

    # 3. 清除待确认仓位
    self._pending_open_position = None

    # 4. 转换到IDLE状态
    self.state_manager.set_state(BotState.IDLE, "开仓失败：两边都没有仓位")
```

**状态变化**:
- `cached_open_spread`: **保持不变**（失败不更新）
- 冷却时间: 设置失败冷却期（10秒）
- 机器人状态: `OPENING_WAIT` → `IDLE`

#### 3.3.4 部分失败场景（仓位不对等）

```python
elif elapsed >= 2.0 and not positions_match:
    # 等待2秒后仓位仍不一致，只平掉本次开仓数量
    logger.warning(f"仓位验证失败: Ext={ext_position} Lig={lig_position}")

    # 1. 只回滚多出来的仓位（不平全仓）
    current_qty = portfolio.total_quantity if portfolio else Decimal("0")
    await self._rollback_partial_positions(current_qty, ext_position, lig_position)

    # 2. 检查回滚后实际仓位，决定下一步状态
    # - 两边都平了 → IDLE
    # - 两边都有且相等 → HOLDING
    # - 仍不一致 → 强制全平 → IDLE/PAUSED
```

**回滚策略**: 取两边较小仓位作为基准，平掉多出的部分

#### 3.3.5 超时场景

```python
if elapsed > timeout:  # timeout = 10秒
    logger.warning(f"等待超时({elapsed:.1f}s)，强平")
    await self._force_close_positions()

    # 强平后进入冷却期
    self._last_open_fail_time = time.time()

    # 检查是否有API错误，决定进入PAUSED还是IDLE
    if self._api_error_count > 0:
        self.state_manager.set_state(BotState.PAUSED, "等待超时且API异常")
    else:
        self.state_manager.set_state(BotState.IDLE, "等待超时，已强平")
```

---

## 4. 具体执行流程

### 4.1 完整开仓流程时序图

```
1. IDLE/HOLDING状态循环（每1秒检查一次）
   ├─ 检查订单簿就绪
   ├─ 检查冷却期（失败10秒，成功3秒）
   ├─ 检查实际仓位（清理残留）
   └─ 获取实时价差

2. 价差监控
   └─ SpreadMonitor.get_current_spread()
      ├─ Extended: fetch_bbo_prices() → bid/ask
      └─ Lighter: fetch_bbo_prices() → bid/ask

3. 开仓策略判断
   └─ ArithmeticOpenStrategy.should_open(spread_info)
      ├─ 首次: spread >= min_threshold (0.07%)
      └─ 后续: spread >= cached_spread + step (0.005%)

4. 风控验证
   └─ RiskManager.validate_open_position()
      ├─ 订单簿深度检查
      ├─ 流动性检查
      └─ 仓位限制检查

5. 状态转换
   └─ IDLE/HOLDING → OPENING

6. 执行开仓（OPENING状态）
   ├─ 并发获取BBO价格（记录时间戳）
   ├─ 创建PriceSnapshot（验证time_delta < 10ms）
   ├─ 计算Taker价格（0.02%滑点保护）
   ├─ 验证价格一致性（ext_buy < lig_sell）
   ├─ 并发发送订单
   │  ├─ Extended: place_taker_order("buy", IOC)
   │  └─ Lighter: place_limit_order("sell", IOC)
   ├─ 等待订单成交（timeout=3秒）
   └─ 创建Position对象

7. 状态转换
   └─ OPENING → OPENING_WAIT

8. 仓位确认（OPENING_WAIT状态）
   ├─ 并发获取实际仓位
   │  ├─ Extended: get_account_positions()
   │  └─ Lighter: get_account_positions()
   ├─ 验证仓位一致性
   │  ├─ 成功: ext ≈ lig > 0 → HOLDING
   │  ├─ 失败: ext ≈ lig = 0 → IDLE + 冷却
   │  ├─ 不对等: 部分回滚 → 检查后决定
   │  └─ 超时: 强制平仓 → IDLE/PAUSED
   └─ 成功时更新状态
      ├─ 添加到智能平仓系统
      ├─ 更新cached_open_spread
      └─ CSV埋点记录
```

---

### 4.2 关键时间节点

| 阶段 | 时间限制 | 说明 |
|------|---------|------|
| 价格同步 | <10ms | 两个交易所BBO获取时间差 |
| 订单成交 | 3秒 | wait_for_execution超时时间 |
| 仓位验证 | 2秒 | 开始检查不对等的最小等待时间 |
| 开仓等待 | 10秒 | OPENING_WAIT总超时时间 |
| 失败冷却 | 10秒 | 开仓失败后等待时间 |
| 成功冷却 | 3秒 | 开仓成功后等待时间 |
| 继续开仓间隔 | 5秒 | 加仓时防止API限流 |

---

### 4.3 API调用清单

#### Extended API调用

```python
# 1. 获取BBO价格
await extended_client.fetch_bbo_prices(contract_id)
# → 内部从WebSocket缓存的orderbook读取

# 2. 下Taker订单
await extended_client.place_taker_order(
    contract_id, quantity, "buy", price
)
# → 调用 x10 SDK: perpetual_trading_client.place_order()
# → 参数: time_in_force=IOC, post_only=False

# 3. 查询订单状态
await extended_client.get_order_info(order_id)
# → HTTP GET: /api/v1/user/orders/{order_id}

# 4. 获取账户仓位
await extended_client.get_account_positions()
# → 调用 x10 SDK: account.get_positions()
```

#### Lighter API调用

```python
# 1. 获取BBO价格
await lighter_client.fetch_bbo_prices(contract_id)
# → 内部从WebSocket缓存的best_bid/best_ask读取

# 2. 下Taker订单
await lighter_client.place_limit_order(
    contract_id, quantity, price, "sell", time_in_force=0
)
# → 调用 lighter SDK: lighter_client.create_order()
# → 参数: time_in_force=0 (IOC), is_ask=True

# 3. 查询订单状态
await lighter_client.get_order_info(order_id)
# → 调用 lighter SDK: account_api.account()

# 4. 获取账户仓位
await lighter_client.get_account_positions()
# → 调用 lighter SDK: account_api.account()
```

---

### 4.4 错误处理机制

#### 价格同步失败
```python
if not price_snapshot.is_valid():
    # 跳过此次开仓，返回IDLE
    return ExecutionResult(success=False, error_message="价格快照无效")
```

#### 订单发送失败
```python
if isinstance(extended_result, Exception):
    return ExecutionResult(error_message=f"Extended 订单失败: {extended_result}")

if isinstance(lighter_result, Exception):
    return ExecutionResult(error_message=f"Lighter 订单失败: {lighter_result}")
```

#### 订单查询连续失败
```python
if extended_fail_count >= max_fail_count:  # 10次
    raise Exception(f"Extended订单查询连续失败{max_fail_count}次，可能API异常")
```

#### 仓位不对等回滚
```python
await self._rollback_partial_positions(current_qty, ext_position, lig_position)
# 策略：取两边较小仓位作为基准，平掉多出的部分
```

#### 强制平仓
```python
await self._force_close_positions()
# 场景：超时、回滚后仍不一致、检测到异常仓位
# 最大重试3次，每次间隔1秒
```

---

### 4.5 CSV埋点记录

#### 开仓埋点字段

**文件位置**: `spread/spread_arb_bot.py:1802-1840`

```python
def _log_open_to_csv(self, status, ext_pos, lig_pos, position_diff,
                     target_qty, elapsed, open_spread, ext_order_id, lig_order_id):
    """记录开仓结果到CSV"""
    # 字段：
    # - timestamp: 时间戳
    # - status: 状态（开仓成功、开仓失败_两边无仓位、仓位不对等）
    # - ext_position: Extended实际仓位
    # - lig_position: Lighter实际仓位
    # - position_diff: 仓位差值
    # - target_qty: 目标数量
    # - elapsed_time: 耗时
    # - open_spread: 开仓价差
    # - ext_order_id: Extended订单ID
    # - lig_order_id: Lighter订单ID
```

---

## 5. 总结

### 核心特点

1. **等差数列策略**: 每次开仓后阈值递增，避免频繁开仓
2. **价格同步机制**: 确保两个交易所价格获取时间差<10ms
3. **Taker模式**: 使用IOC订单+0.02%滑点保护，确保即时成交
4. **双层验证**: 先验证订单状态，再验证实际仓位
5. **只增不减**: cached_open_spread只在成功开仓后更新
6. **容错机制**: 部分回滚、强制平仓、风控暂停

---

### 关键文件清单

- **主控制器**: `spread/spread_arb_bot.py`
- **交易执行**: `spread/trade_executor.py`
- **开仓策略**: `spread/arithmetic_open_strategy.py`
- **价格快照**: `spread/price_snapshot.py`
- **Extended客户端**: `exchanges/extended.py`
- **Lighter客户端**: `exchanges/lighter.py`

---

### 开仓决策树

```
开始
  ↓
订单簿就绪？
  ├─ 否 → 等待
  └─ 是 → ↓
冷却期已过？
  ├─ 否 → 等待
  └─ 是 → ↓
价差满足条件？
  ├─ 否 → 继续监控
  └─ 是 → ↓
风控验证通过？
  ├─ 否 → 跳过
  └─ 是 → ↓
价格同步（<10ms）？
  ├─ 否 → 跳过
  └─ 是 → ↓
价差一致性验证？
  ├─ 否 → 跳过
  └─ 是 → ↓
并发发送订单
  ↓
等待仓位确认（10秒）
  ├─ 成功 → HOLDING + 更新cached_spread
  ├─ 失败 → IDLE + 冷却期
  ├─ 不对等 → 部分回滚
  └─ 超时 → 强制平仓
```

---

## 7. 平仓逻辑详细分析

### 7.1 平仓相关状态定义

```python
class BotState(Enum):
    HOLDING = "HOLDING"                # 持仓中（监控平仓机会）
    CLOSING = "CLOSING"                # 平仓中（发送平仓订单）
    CLOSING_WAIT = "CLOSING_WAIT"      # 平仓等待确认
    IDLE = "IDLE"                      # 空闲（平仓完成后）
```

### 7.2 平仓状态转换路径

```
┌─────────┐
│HOLDING  │  监控价差，寻找平仓机会
└────┬────┘
     │ 满足平仓条件
     │ 开仓价差 >= 当前价差 + 利润目标 + 手续费
     ↓
┌─────────┐
│CLOSING  │  发送平仓订单
└────┬────┘
     │ 订单已发送（不管成功失败）
     ↓
┌─────────────┐
│CLOSING_WAIT │  等待3秒后确认仓位
└─────┬───────┘
     │
     ├──────────┬─────────────┐
     │          │             │
  两边都平了    单边平仓     两边都没平
     │          │             │
     ↓          ↓             ↓
┌─────────┐  ┌───────┐   ┌───────┐
│  IDLE   │  │强平→  │   │HOLDING│
│ 更新统计│  │ IDLE  │   │等待再试│
└─────────┘  └───────┘   └───────┘
```

### 7.3 平仓触发条件

**文件位置**: `spread/spread_arb_bot.py:610-620`

#### 智能平仓策略判断

```python
# spread_arb_bot.py:611-618
trigger = self.close_strategy.should_close(spread_info)

if trigger.is_triggered:
    # 切换到平仓状态
    close_reason = (f"开仓{trigger.entry_spread:.3%} >= 当前{trigger.current_spread:.3%} + "
                  f"利润{trigger.profit_target:.3%} + 手续费{trigger.fee_rate:.3%} | "
                  f"预期利润{trigger.expected_profit:.3%}")
    self.state_manager.set_state(BotState.CLOSING, f"利润目标达成: {close_reason}")
```

**平仓公式**:
```
开仓价差 >= 当前价差 + 利润目标 + 手续费
```

**示例**:
```
开仓价差: 0.08%
当前价差: 0.02%
利润目标: 0.03%
手续费: 0.02%
判断: 0.08% >= 0.02% + 0.03% + 0.02% = 0.07% ✓ → 触发平仓
```

#### 加权平均开仓价差计算

**文件位置**: `spread/smart_close_strategy.py:78-79`

```python
# 获取加权平均开仓价差（支持多笔仓位）
entry_spread = self.portfolio.get_total_entry_spread()
```

**计算方式**: 使用多笔仓位的加权平均

```python
# spread/models.py:Portfolio
def get_total_entry_spread(self) -> Decimal:
    """计算加权平均开仓价差"""
    if self.total_quantity == 0:
        return Decimal("0")

    total_spread_value = Decimal("0")
    for pos in self.positions:
        # 价差 × 数量 = 总价差值
        total_spread_value += pos.open_spread * pos.quantity

    # 加权平均 = 总价差值 / 总数量
    return total_spread_value / self.total_quantity
```

**示例计算**:
```
仓位1: 价差0.08%, 数量0.01 ETH → 价差值 = 0.0008
仓位2: 价差0.09%, 数量0.02 ETH → 价差值 = 0.0018
总数量: 0.03 ETH
总价差值: 0.0026
加权平均: 0.0026 / 0.03 = 0.0867%
```

---

## 8. CLOSING 状态详细分析

### 8.1 状态入口

**文件位置**: `spread/spread_arb_bot.py:621-671`

```python
async def _process_closing_state(self) -> None:
    """处理 CLOSING 状态：执行平仓"""
    logger.info("执行平仓...")
```

**进入条件**: 从 HOLDING 状态触发（满足平仓条件）

### 8.2 状态核心职责

CLOSING 状态的**唯一职责**是：**发送平仓订单**，不管订单成功还是失败，都直接进入 CLOSING_WAIT 状态。

### 8.3 执行步骤详解

#### Step 1: 获取持仓组合

```python
# spread_arb_bot.py:626-631
portfolio = self.close_strategy.get_portfolio()
if portfolio is None or portfolio.total_quantity == 0:
    logger.warning("持仓信息丢失或无持仓")
    self.state_manager.set_state(BotState.IDLE, "持仓信息丢失或无持仓")
    await self.state_manager.save_state()
    return
```

**API调用**: `SmartCloseStrategy.get_portfolio()`
- 返回类型: `Portfolio` 对象
- 包含多笔开仓记录

#### Step 2: 获取总持仓数量和加权开仓价差

```python
# spread_arb_bot.py:634-638
total_quantity = portfolio.total_quantity
entry_spread = portfolio.get_total_entry_spread()
first_open_time = portfolio.first_open_time

logger.info(f"平仓总数量: {total_quantity} ETH, 加权开仓价差: {entry_spread:.3%}")
```

#### Step 3: 创建临时Position对象（向后兼容）

```python
# spread_arb_bot.py:640-652
temp_position = Position(
    state=PositionState.LONG,
    extended_entry_price=Decimal("0"),  # 平仓时不需要
    lighter_entry_price=Decimal("0"),  # 平仓时不需要
    entry_spread=entry_spread,
    entry_time=datetime.now(),
    extended_quantity=total_quantity,
    lighter_quantity=-total_quantity,
    extended_order_id="close",
    lighter_order_id="close"
)
```

**说明**: 创建临时Position对象用于传递给 `execute_close_position()` 方法

#### Step 4: 执行平仓（核心）

```python
# spread_arb_bot.py:654-658
result = await self.trade_executor.execute_close_position(
    temp_position,
    total_quantity
)
```

**返回对象**: `ExecutionResult`
```python
@dataclass
class ExecutionResult:
    success: bool                          # 订单是否成功
    extended_order_id: Optional[str]       # Extended订单ID
    lighter_order_id: Optional[str]        # Lighter订单ID
    extended_price: Optional[Decimal]      # Extended成交价格
    lighter_price: Optional[Decimal]       # Lighter成交价格
    extended_filled: bool                   # Extended是否成交
    lighter_filled: bool                    # Lighter是否成交
    error_message: Optional[str]            # 错误信息
```

#### Step 5: 输出订单状态日志

```python
# spread_arb_bot.py:660-664
if result.success or result.extended_order_id or result.lighter_order_id:
    logger.info(f"平仓订单已发送: Ext={result.extended_order_id}, Lig={result.lighter_order_id}")
else:
    logger.error(f"平仓订单发送失败: {result.error_message}")
```

#### Step 6: 切换到 CLOSING_WAIT 状态

```python
# spread_arb_bot.py:666-670
import time
self._closing_wait_start_time = time.time()
self.state_manager.set_state(BotState.CLOSING_WAIT, f"平仓订单已发送，等待确认")
await self.state_manager.save_state()
```

**关键设计决策**:
1. **不管订单状态如何都进入 CLOSING_WAIT**：即使订单失败也要检查实际仓位（防止部分成交）
2. **等待3秒后检查**：比开仓等待时间短（开仓等待10秒）

---

## 9. 平仓调用的方法和API

### 9.1 核心调用链

```
_process_closing_state()
  ↓
trade_executor.execute_close_position(position, total_quantity)
  ↓
[并发执行 Taker模式]
  ├─ _place_extended_order_taker("sell", quantity, None)
  └─ _place_lighter_order_taker("buy", quantity, None)
```

**平仓方向**:
- **Extended**: 卖出（`sell`）- 平掉多仓
- **Lighter**: 买入（`buy`）- 平掉空仓

### 9.2 execute_close_position 方法

**文件位置**: `spread/trade_executor.py:272-358`

#### Step 1: 并发发送平仓订单

```python
# trade_executor.py:295-300
# Taker模式：使用市价单确保即时成交
results = await asyncio.gather(
    self._place_extended_order_taker("sell", quantity, None),
    self._place_lighter_order_taker("buy", quantity, None),
    return_exceptions=True
)
```

**价格参数**: `None`（使用市价单）

#### Step 2: 检查错误

```python
# trade_executor.py:302-316
extended_result = results[0]
lighter_result = results[1]

if isinstance(extended_result, Exception):
    return ExecutionResult(
        error_message=f"Extended 订单失败: {extended_result}",
        execution_time=time.time() - start_time
    )

if isinstance(lighter_result, Exception):
    return ExecutionResult(
        error_message=f"Lighter 订单失败: {lighter_result}",
        execution_time=time.time() - start_time
    )
```

#### Step 3: 等待订单成交

```python
# trade_executor.py:318-323
execution_status = await self.wait_for_execution(
    extended_result["order_id"],
    lighter_result["order_id"],
    self.timeout  # 默认3秒
)
```

#### Step 4: 处理执行结果

```python
# trade_executor.py:328-351
if execution_status["both_filled"]:
    return ExecutionResult(
        success=True,
        extended_order_id=extended_result["order_id"],
        lighter_order_id=lighter_result["order_id"],
        extended_price=extended_result.get("price"),
        lighter_price=lighter_result.get("price"),
        execution_time=execution_time,
        extended_filled=True,
        lighter_filled=True
    )
else:
    logger.error(f"平仓失败或超时")
    return ExecutionResult(
        error_message="平仓失败或超时",
        execution_time=execution_time,
        extended_filled=execution_status["extended_filled"],
        lighter_filled=execution_status["lighter_filled"]
    )
```

---

### 9.3 Extended Taker平仓订单（卖出）

**文件位置**: `spread/trade_executor.py` 内部调用

```python
async def _place_extended_order_taker("sell", quantity, None):
    """
    下Extended Taker卖出订单（IOC模式）

    Args:
        side: "sell" - 卖出平多仓
        quantity: 卖出数量
        price: None - 使用市价单

    Returns:
        order_id: 订单ID
    """
```

**API调用**: `exchanges/extended.py:place_taker_order()`

```python
# exchanges/extended.py
async def place_taker_order(self, contract_id, quantity, side, price):
    """下Extended Taker订单（IOC模式）"""
    order_result = await self.perpetual_trading_client.place_order(
        market_name=contract_id,
        amount_of_synthetic=quantity,
        price=price,  # None表示市价单
        side=OrderSide.SELL,  # 平仓时卖出
        time_in_force=TimeInForce.IOC,  # 立即成交或取消
        post_only=False,  # 允许taker成交
        expire_time=utc_now() + timedelta(minutes=1),
    )
```

**订单参数**:
- `side`: `OrderSide.SELL`（卖出）
- `time_in_force`: `IOC`（立即成交或取消）
- `post_only`: `False`（允许taker成交）
- `price`: `None`（市价单，即时成交）

---

### 9.4 Lighter Taker平仓订单（买入）

**文件位置**: `spread/trade_executor.py` 内部调用

```python
async def _place_lighter_order_taker("buy", quantity, None):
    """
    下Lighter Taker买入订单（IOC模式）

    Args:
        side: "buy" - 买入平空仓
        quantity: 买入数量
        price: None - 使用市价单

    Returns:
        order_id: 订单ID
    """
```

**API调用**: `exchanges/lighter.py:place_limit_order()`

```python
# exchanges/lighter.py
async def place_limit_order(self, contract_id, quantity, price, side, time_in_force=0):
    """下Lighter Taker订单（IOC模式）"""
    order_params = {
        'market_index': self.config.contract_id,
        'client_order_index': client_order_index,
        'base_amount': int(quantity * self.base_amount_multiplier),
        'price': int(price * self.price_multiplier) if price else 0,  # 市价单
        'is_ask': False,  # 买入
        'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
        'time_in_force': 0,  # IOC
        'reduce_only': True,  # 只减仓（重要！）
        'trigger_price': 0,
        'order_expiry': 0,
    }

    create_order, tx_hash, error = await self.lighter_client.create_order(**order_params)
```

**订单参数**:
- `is_ask`: `False`（买入）
- `time_in_force`: `0`（IOC）
- `reduce_only`: `True`（只减仓，防止开新仓）
- `price`: `0`（市价单）

**重要**: `reduce_only=True` 确保只平仓，不会意外开新仓

---

## 10. CLOSING_WAIT 状态详细分析

### 10.1 状态入口

**文件位置**: `spread/spread_arb_bot.py:880-979`

```python
async def _process_closing_wait_state(self) -> None:
    """处理 CLOSING_WAIT 状态：等待确认平仓结果"""
```

**进入条件**: 从 CLOSING 状态自动切换（平仓订单已发送后）

### 10.2 状态核心职责

CLOSING_WAIT 状态的**核心职责**是：
1. **等待3秒**：让平仓订单有足够时间成交
2. **验证实际仓位**：通过查询交易所 API 获取实际持仓
3. **判断平仓结果**：根据实际仓位决定下一步状态
4. **更新统计信息**：只在确认成功后才更新统计

### 10.3 执行步骤详解

#### Step 1: 初始化等待时间

```python
# spread_arb_bot.py:884-888
current_time = time.time()
if self._closing_wait_start_time is None:
    self._closing_wait_start_time = current_time

elapsed = current_time - self._closing_wait_start_time
```

#### Step 2: 等待3秒后检查仓位

```python
# spread_arb_bot.py:890-892
# 等待 3 秒后检查仓位
if elapsed < 3.0:
    return
```

**关键设计**: 等待时间比开仓（10秒）短，因为平仓使用市价单，成交更快

#### Step 3: 并发获取实际仓位

```python
# spread_arb_bot.py:895-897
ext_position = await self.extended_client.get_account_positions()
lig_position = await self.lighter_client.get_account_positions()
tolerance = Decimal("0.001")
```

**API调用详情**:

**Extended API**:
```python
# exchanges/extended.py
async def get_account_positions(self) -> Decimal:
    """获取当前持仓数量"""
    account = await self.perpetual_trading_client.get_positions()
    # 返回绝对值（正数）
    return account.total_quantity
```

**Lighter API**:
```python
# exchanges/lighter.py
async def get_account_positions(self) -> Decimal:
    """获取当前持仓数量"""
    account = await self.lighter_client.account_api.account()
    # 计算净持仓：long_positions - short_positions
    # 返回绝对值（正数）
    return abs(total_position)
```

#### Step 4: 仓位验证逻辑

```python
# spread_arb_bot.py:902-903
ext_closed = ext_position < tolerance
lig_closed = lig_position < tolerance
```

#### Step 5: 处理验证结果

##### 场景A: 两边都平了（平仓成功）

```python
# spread_arb_bot.py:905-957
if ext_closed and lig_closed:
    # 1. 获取持仓信息
    portfolio = self.close_strategy.get_portfolio()
    total_quantity = portfolio.total_quantity if portfolio else Decimal("0")
    entry_spread = portfolio.get_total_entry_spread() if portfolio else Decimal("0")
    first_open_time = portfolio.first_open_time if portfolio else None

    # 2. 计算利润（简化计算）
    if portfolio:
        avg_price = Decimal("3000")  # 估算价格
        profit = total_quantity * (entry_spread - self.config.total_fee_rate) * avg_price
    else:
        profit = Decimal("0")

    # 3. 更新统计
    stats = self.state_manager.get_stats()
    stats.total_trades += 1
    if profit > 0:
        stats.profitable_trades += 1
    stats.total_profit += profit
    stats.total_fees += self._calculate_fees_for_portfolio(portfolio) if portfolio else Decimal("0")
    stats.last_trade_time = datetime.now()
    self.state_manager.update_stats(stats)

    # 4. 清除所有持仓记录
    self.close_strategy.close_all()

    # 5. 清除旧的 Position（向后兼容）
    old_position = self.state_manager.get_position()
    if old_position:
        self.state_manager.update_position(None)

    # 6. 计算持仓时长
    elapsed_time = time.time() - first_open_time if first_open_time else 0.0

    # 7. CSV埋点：平仓成功
    fees = self._calculate_fees_for_portfolio(portfolio) if portfolio else Decimal("0")
    self._log_close_to_csv(
        entry_spread=entry_spread,
        close_spread=Decimal("0.001"),
        total_qty=total_quantity,
        profit=profit,
        fees=fees,
        elapsed=elapsed_time,
        status='平仓成功'
    )

    # 8. 切换到 IDLE 状态
    self.state_manager.set_state(BotState.IDLE, f"平仓成功: 利润=${profit:.2f}")
    await self.state_manager.save_state()
```

**状态变化**:
- 统计信息: 更新交易次数、利润、手续费
- 持仓记录: 清空所有仓位
- 机器人状态: `CLOSING_WAIT` → `IDLE`

##### 场景B: 单边平仓（仓位不对等）

```python
# spread_arb_bot.py:959-970
elif ext_closed or lig_closed:
    # 两边有差异，强平
    logger.error(f"⚠️ 平仓后仓位不一致！Ext={'已平' if ext_closed else f'有仓位{ext_position}'}, "
              f"Lig={'已平' if lig_closed else f'有仓位{lig_position}'}")
    logger.error("立即强平所有仓位...")

    await self._force_close_positions()

    # 强平后进入 IDLE 状态
    logger.info("✅ 强平完成，进入IDLE状态")
    self.state_manager.set_state(BotState.IDLE, "平仓后仓位不一致，已强制清理")
    await self.state_manager.save_state()
```

**处理策略**: 立即强制平仓所有剩余仓位

##### 场景C: 两边都没平（平仓失败）

```python
# spread_arb_bot.py:972-979
else:
    # 两边都有持仓，平仓失败
    logger.warning(f"⚠️ 平仓失败：两边都仍有仓位 Ext={ext_position} Lig={lig_position}")

    # 保持 HOLDING 状态，等待下一次机会
    self.state_manager.set_state(BotState.HOLDING, "平仓失败，仍有持仓")
    await self.state_manager.save_state()
```

**状态变化**: 回到 HOLDING 状态，继续等待平仓机会

### 10.4 CLOSING_WAIT 状态的循环机制

CLOSING_WAIT 状态是**循环执行**的，主交易循环每1秒调用一次：

```python
# spread_arb_bot.py:277-278
elif state == BotState.CLOSING_WAIT:
    await self._process_closing_wait_state()
```

**检查频率**: 每1秒一次
**等待时间**: 3秒（固定）

---

## 11. 平仓完整执行流程

### 11.1 完整平仓流程时序图

```
1. HOLDING状态循环（每1秒检查一次）
   ├─ 监控实时价差
   └─ 判断是否满足平仓条件

2. 平仓策略判断
   └─ SmartCloseStrategy.should_close(spread_info)
      ├─ 计算加权平均开仓价差
      ├─ 判断: entry_spread >= current_spread + profit + fees
      └─ 返回 CloseTrigger 对象

3. 状态转换
   └─ HOLDING → CLOSING

4. 执行平仓（CLOSING状态）
   ├─ 获取Portfolio（多笔仓位）
   ├─ 获取总持仓数量和加权开仓价差
   ├─ 创建临时Position对象
   ├─ 并发发送平仓订单（Taker模式）
   │  ├─ Extended: place_taker_order("sell", IOC) - 卖出平多仓
   │  └─ Lighter: place_limit_order("buy", IOC, reduce_only=True) - 买入平空仓
   ├─ 等待订单成交（timeout=3秒）
   └─ 创建ExecutionResult

5. 状态转换
   └─ CLOSING → CLOSING_WAIT

6. 仓位确认（CLOSING_WAIT状态）
   ├─ 等待3秒
   ├─ 并发获取实际仓位
   │  ├─ Extended: get_account_positions()
   │  └─ Lighter: get_account_positions()
   ├─ 验证仓位
   │  ├─ 成功: ext=lig=0 → IDLE + 更新统计
   │  ├─ 不对等: 强制平仓 → IDLE
   │  └─ 失败: ext>0 and lig>0 → HOLDING（等待再试）
   └─ 成功时更新状态
      ├─ 计算利润
      ├─ 更新统计信息
      ├─ 清空持仓记录
      └─ CSV埋点记录
```

---

### 11.2 平仓关键时间节点

| 阶段 | 时间限制 | 说明 |
|------|---------|------|
| 订单成交 | 3秒 | wait_for_execution超时时间 |
| 平仓等待 | 3秒 | CLOSING_WAIT固定等待时间 |
| 仓位验证 | 3秒后 | 开始检查实际仓位 |

**对比开仓**:
- 开仓等待: 10秒（因为需要确认两边都开成功）
- 平仓等待: 3秒（使用市价单，成交更快）

---

### 11.3 平仓API调用清单

#### Extended 平仓API调用

```python
# 1. 下Taker卖出订单
await extended_client.place_taker_order(
    contract_id, quantity, "sell", None  # None=市价单
)
# → 调用 x10 SDK: perpetual_trading_client.place_order()
# → 参数: side=SELL, time_in_force=IOC, post_only=False

# 2. 查询订单状态
await extended_client.get_order_info(order_id)
# → HTTP GET: /api/v1/user/orders/{order_id}

# 3. 获取账户仓位
await extended_client.get_account_positions()
# → 调用 x10 SDK: account.get_positions()
```

#### Lighter 平仓API调用

```python
# 1. 下Taker买入订单
await lighter_client.place_limit_order(
    contract_id, quantity, 0, "buy", time_in_force=0
)
# → 调用 lighter SDK: lighter_client.create_order()
# → 参数: is_ask=False, time_in_force=0 (IOC), reduce_only=True

# 2. 查询订单状态
await lighter_client.get_order_info(order_id)
# → 调用 lighter SDK: account_api.account()

# 3. 获取账户仓位
await lighter_client.get_account_positions()
# → 调用 lighter SDK: account_api.account()
```

---

### 11.4 平仓错误处理机制

#### 订单发送失败

```python
if isinstance(extended_result, Exception):
    return ExecutionResult(
        error_message=f"Extended 订单失败: {extended_result}",
        execution_time=time.time() - start_time
    )
```

#### 仓位不对等（单边平仓）

```python
elif ext_closed or lig_closed:
    # 两边有差异，强平
    await self._force_close_positions()
    self.state_manager.set_state(BotState.IDLE, "平仓后仓位不一致，已强制清理")
```

#### 平仓失败（两边都没平）

```python
else:
    # 两边都有持仓，平仓失败
    self.state_manager.set_state(BotState.HOLDING, "平仓失败，仍有持仓")
```

#### 强制平仓

```python
await self._force_close_positions()
# 场景：超时、仓位不对等、检测到异常仓位
# 最大重试3次，每次间隔1秒
```

---

### 11.5 平仓CSV埋点记录

#### 平仓埋点字段

**文件位置**: `spread/spread_arb_bot.py` (具体方法需查找)

```python
def _log_close_to_csv(self, entry_spread, close_spread, total_qty, profit, fees, elapsed, status):
    """记录平仓结果到CSV"""
    # 字段：
    # - timestamp: 时间戳
    # - status: 状态（平仓成功、平仓失败）
    # - entry_spread: 开仓价差（加权平均）
    # - close_spread: 平仓价差
    # - total_qty: 总数量
    # - profit: 利润
    # - fees: 手续费
    # - elapsed: 持仓时长（秒）
```

---

## 12. 平仓总结

### 核心特点

1. **智能平仓策略**: 使用加权平均开仓价差，支持多笔仓位
2. **Taker模式**: 使用市价单+IOC，确保即时成交
3. **双向平仓**: Extended卖出 + Lighter买入
4. **快速确认**: 等待3秒后检查仓位（比开仓快）
5. **容错机制**: 强制平仓、重试、回到HOLDING状态
6. **统计更新**: 只在确认成功后更新统计信息

---

### 平仓决策树

```
开始（HOLDING状态）
  ↓
获取实时价差
  ↓
计算加权平均开仓价差
  ↓
判断平仓条件
  ├─ entry_spread >= current_spread + profit + fees?
  ├─ 否 → 继续监控
  └─ 是 → ↓
进入CLOSING状态
  ↓
并发发送平仓订单
  ├─ Extended: place_taker_order("sell", IOC)
  └─ Lighter: place_limit_order("buy", IOC, reduce_only=True)
  ↓
进入CLOSING_WAIT状态
  ↓
等待3秒
  ↓
获取实际仓位
  ├─ Ext=0, Lig=0 → IDLE + 更新统计
  ├─ Ext=0, Lig>0 或 Ext>0, Lig=0 → 强制平仓 → IDLE
  └─ Ext>0, Lig>0 → HOLDING（等待再试）
```

---

### 关键文件清单（平仓相关）

- **主控制器**: `spread/spread_arb_bot.py` (CLOSING/CLOSING_WAIT状态处理)
- **交易执行**: `spread/trade_executor.py` (execute_close_position)
- **平仓策略**: `spread/smart_close_strategy.py` (should_close判断)
- **Extended客户端**: `exchanges/extended.py` (place_taker_order卖出)
- **Lighter客户端**: `exchanges/lighter.py` (place_limit_order买入)

---

## 附录：配置参数

### 默认配置

```python
# 交易参数
symbol: "ETH"
target_quantity: 0.01  # 交易数量
min_spread_threshold: 0.07%  # 最小开仓阈值

# 策略参数
spread_step: 0.005%  # 价差步长
cached_open_spread: 0%  # 上次开仓价差（初始值）

# 风控参数
slippage_buffer: 0.01%  # 滑点保护
min_profit: 0%  # 最小利润
max_spread: 5%  # 极端价差阈值

# 超时配置
single_side_timeout: 3.0秒  # 单边订单超时
open_wait_timeout: 10.0秒  # 开仓等待超时
close_wait_timeout: 10.0秒  # 平仓等待超时

# 冷却配置
_open_cooldown: 10.0秒  # 失败冷却期
_open_success_cooldown: 3.0秒  # 成功冷却期
```

---

*文档创建时间: 2026-01-18*
*基于版本: 001-fix-spread-price*
