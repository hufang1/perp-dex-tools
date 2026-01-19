# 价差套利程序完整逻辑文档

> 版本: v1.0
> 更新时间: 2026-01-19
> 项目: Lighter-Extended 单向价差收敛套利系统

---

## 目录

1. [系统概述](#1-系统概述)
2. [核心状态定义](#2-核心状态定义)
3. [状态转换逻辑](#3-状态转换逻辑)
4. [开仓逻辑详解](#4-开仓逻辑详解)
5. [平仓逻辑详解](#5-平仓逻辑详解)
6. [API调用详情](#6-api调用详情)
7. [风控机制](#7-风控机制)
8. [异常处理](#8-异常处理)

---

## 1. 系统概述

### 1.1 套利策略

本系统实现 **Lighter-Extended 单向价差收敛套利** 策略：

- **套利方向**: Extended买入 + Lighter卖出
- **盈利逻辑**: 当Extended价格低于Lighter价格时，在Extended买入、在Lighter卖出，等待价差收敛后平仓获利
- **价差计算**: `spread = (Lighter_Bid - Extended_Ask) / Extended_Ask`

### 1.2 两种交易模式

| 模式 | 描述 | 执行方式 | 手续费 | 优缺点 |
|------|------|----------|--------|--------|
| **Taker模式** | 即时成交模式 | Extended和Lighter并发下单 | Extended ~0.025% | 速度快但手续费较高 |
| **Maker模式** | 挂单等待成交模式 | Extended先挂单Maker，成交后Lighter对冲 | Extended ~0% | 手续费低但需等待成交 |

### 1.3 核心组件

```
spread_arb_bot.py          # 主控制器（状态机）
├── state_manager.py       # 状态管理器
├── trade_executor.py      # 交易执行器
├── spread_calculator.py   # 价差计算器
├── risk_manager.py        # 风控管理器
├── spread_monitor.py      # 价差监控器
├── price_monitor.py       # 价格监控器（Maker模式）
├── maker_order_monitor.py # Maker订单监控器（Maker模式）
├── arithmetic_open_strategy.py  # 等差数列开仓策略（Taker模式）
└── smart_close_strategy.py      # 智能平仓策略
```

---

## 2. 核心状态定义

### 2.1 BotState 枚举

| 状态值 | 中文名称 | 描述 | 适用模式 |
|--------|----------|------|----------|
| `IDLE` | 空闲 | 等待开仓机会 | 全部 |
| `OPENING` | 开仓中 | 执行开仓订单 | Taker |
| `OPENING_MAKER_WAIT` | 开仓挂单等待成交 | 等待Extended Maker订单成交 | Maker |
| `OPENING_WAIT` | 开仓等待确认 | 等待仓位确认 | 全部 |
| `HOLDING` | 持仓中 | 持有仓位，监控平仓/加仓机会 | 全部 |
| `CLOSING` | 平仓中 | 执行平仓订单 | Taker |
| `CLOSING_MAKER_WAIT` | 平仓挂单等待成交 | 等待Extended Maker平仓订单成交 | Maker |
| `LIGHTER_HEDGING` | Lighter对冲中 | 在Lighter执行对冲订单 | Maker |
| `CLOSING_WAIT` | 平仓等待确认 | 等待平仓确认 | 全部 |
| `PAUSED` | 风控暂停 | API异常时暂停交易 | 全部 |
| `ERROR` | 错误 | 错误状态 | 全部 |

### 2.2 PositionState 枚举

| 状态值 | 描述 | Extended数量 | Lighter数量 |
|--------|------|--------------|-------------|
| `NONE` | 无持仓 | 0 | 0 |
| `LONG` | 多头套利 | > 0 | < 0 |

### 2.3 配置参数 (BotConfig)

```python
# ========== 基础参数 ==========
symbol: str = "ETH"                          # 交易对
target_quantity: Decimal = Decimal("0.01")   # 目标交易数量

# ========== Taker模式阈值 ==========
min_spread_threshold: Decimal = Decimal("0.0007")  # 最小价差阈值 0.07%
slippage_buffer: Decimal = Decimal("0.0001")       # 滑点保护 0.01%
min_profit: Decimal = Decimal("0")                  # 最小利润 0%

# ========== Maker模式阈值 ==========
fixed_open_threshold: Decimal = Decimal("0.0003")  # 固定开仓阈值 0.03%
fixed_close_threshold: Decimal = Decimal("0.0002") # 固定平仓阈值 0.02%

# ========== 等差数列策略（Taker模式）==========
cached_open_spread: Decimal = Decimal("0")     # 上次开仓价差
spread_step: Decimal = Decimal("0.00005")      # 价差步长 0.005%

# ========== 风控参数 ==========
single_side_timeout: float = 3.0               # 单边超时 3秒
open_wait_timeout: float = 10.0                # 开仓等待确认超时 10秒
balance_check_buffer: float = 3.0              # 仓位平衡检测缓冲期 3秒
max_spread: Decimal = Decimal("0.05")          # 极端价差阈值 5%
total_fee_rate: Decimal = Decimal("0.0005")    # 总手续费率 0.05%

# ========== Maker模式参数 ==========
use_maker_mode: bool = True                    # 是否使用Maker模式
maker_order_timeout: float = 30.0              # Maker挂单超时时间 30秒
price_monitor_interval: float = 1              # 价格监控间隔 1秒
reposition_cooldown: float = 2.0               # 重挂冷却时间 2秒
max_reposition_count: int = 10                 # 连续重挂次数限制 10次
```

---

## 3. 状态转换逻辑

### 3.1 状态转换图

```
┌─────────────────────────────────────────────────────────────────┐
│                        状态转换流程图                              │
└─────────────────────────────────────────────────────────────────┘

                        [程序启动]
                            ↓
                          ┌─────┐
                          │IDLE │ ←────────────────────────────────┐
                          └──┬──┘                                 │
                             │ 满足开仓条件                        │
                             ↓                                    │
                    ┌─────────────────┐                          │
                    │   OPENING       │ ←─────┐                  │
                    │   (Taker模式)   │       │                  │
                    └────────┬─────────┘       │                  │
                             │                 │                  │
                             ↓                 │                  │
                    ┌─────────────────┐       │                  │
                    │   OPENING_WAIT  │       │                  │
                    │   (等待仓位确认) │       │                  │
                    └────────┬─────────┘       │                  │
                             │                 │                  │
              ┌──────────────┴──────────────┐  │                  │
              │                              │  │                  │
        仓位成功                          超时/失败             │
              │                              │  │                  │
              ↓                              ↓  │                  │
        ┌──────────┐                    ┌─────┴──┴────────┐       │
        │ HOLDING  │                    │   IDLE (冷却)   │       │
        └─────┬────┘                    └──────────────────┘       │
              │                                                    │
              │ 满足平仓条件 或 继续开仓                           │
              ↓                                                    │
        ┌─────────────────┐                                         │
        │   CLOSING       │ ←───────────────────────────────────┘
        │   (Taker模式)   │
        └────────┬─────────┘
                 ↓
        ┌─────────────────┐
        │  CLOSING_WAIT   │
        └────────┬─────────┘
                 │
        ┌────────┴────────┐
        │                 │
    平仓成功          失败/超时
        │                 │
        ↓                 ↓
    ┌─────┐         ┌──────┐
    │IDLE │         │HOLDING│
    └─────┘         └──────┘


┌─────────────────────────────────────────────────────────────────┐
│                    Maker模式状态转换                              │
└─────────────────────────────────────────────────────────────────┘

                          [IDLE]
                            ↓ 满足开仓条件
                    ┌─────────────────┐
                    │   OPENING       │
                    │ (下Maker订单)    │
                    └────────┬─────────┘
                             ↓
                    ┌─────────────────┐
                    │OPENING_MAKER_WAIT│
                    │  (等待成交)       │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
          订单完全成交    订单部分成交      订单取消
              │              │              │
              ↓              ↓              ↓
    ┌─────────────────┐ ┌─────────────────┐ ┌─────┐
    │LIGHTER_HEDGING  │ │LIGHTER_HEDGING  │ │ IDLE│
    │  (对冲全部)     │ │  (对冲部分)     │ └─────┘
    └────────┬─────────┘ └────────┬─────────┘
             │                      │
             ↓                      ↓
    ┌─────────────────┐   ┌─────────────────┐
    │  OPENING_WAIT   │   │  OPENING_WAIT   │
    │  (验证仓位)     │   │  (验证仓位)     │
    └────────┬─────────┘   └────────┬─────────┘
             │                      │
             ↓                      ↓
        ┌─────┐              ┌──────┐
        │HOLDING│              │ IDLE │
        └─────┘              └──────┘
```

### 3.2 详细状态转换说明

#### 3.2.1 IDLE → OPENING

**触发条件**:
- Taker模式: `价差 >= min_spread_threshold + slippage_buffer` 或 `价差 >= cached_open_spread + spread_step`
- Maker模式: `价差 >= fixed_open_threshold`

**前置检查**:
1. 失败冷却期检查 (`_open_cooldown`)
2. 成功冷却期检查 (`_open_success_cooldown`)
3. 风控验证 (`risk_manager.validate_open_position`)
4. 仓位恢复检查（检测是否有残留仓位）

**状态转换代码**:
```python
# spread_arb_bot.py:422-430
if self.config.use_maker_mode:
    self.state_manager.set_state(
        BotState.OPENING,
        f"价差{spread_info.spread_pct:.3%} >= 开仓阈值{threshold:.3%}"
    )
else:
    self.state_manager.set_state(
        BotState.OPENING,
        f"价差{spread_info.spread_pct:.3%} > 阈值{self.config.min_spread_threshold:.3%}"
    )
```

#### 3.2.2 OPENING → OPENING_WAIT (Taker模式)

**执行逻辑**:
```python
# trade_executor.py:86-270
async def execute_open_position(self, quantity: Decimal, spread) -> ExecutionResult:
    # 1. 并发获取两个交易所的BBO价格
    ext_bid, ext_ask = await extended_client.fetch_bbo_prices()
    lig_bid, lig_ask = await lighter_client.fetch_bbo_prices()

    # 2. 创建价格快照并验证时间差 (<10ms)
    price_snapshot = PriceSnapshot(
        ext_bid, ext_ask, ext_fetch_time,
        lig_bid, lig_ask, lig_fetch_time,
        time_delta
    )

    # 3. 计算Taker价格（0.02%滑点保护）
    ext_price = ext_ask * Decimal('1.0002')  # 买入价
    lig_price = lig_bid * Decimal('0.9998')  # 卖出价

    # 4. 并发发送订单
    await asyncio.gather(
        extended_client.place_taker_order("buy", quantity, ext_price),
        lighter_client.place_limit_order("sell", quantity, lig_price, time_in_force=0)
    )

    # 5. 等待订单成交（最多3秒）
    await self.wait_for_execution(ext_order_id, lig_order_id, timeout=3.0)
```

**API调用**:
| 交易所 | 端点 | 方向 | 价格计算 |
|--------|------|------|----------|
| Extended | `place_open_order` | buy | `ask * 1.0002` |
| Lighter | `place_limit_order` | sell | `bid * 0.9998`, IOC=0 |

#### 3.2.3 OPENING → OPENING_MAKER_WAIT (Maker模式)

**执行逻辑**:
```python
# spread_arb_bot.py:455-503
async def _process_opening_maker_mode(self, spread_info):
    # 1. 下Extended Maker订单（post_only）
    result = await trade_executor.place_maker_open_order(quantity)

    # 2. 初始化Maker等待状态
    self._maker_wait_state.current_order = MakerOrder(
        order_id=result.extended_order_id,
        price=result.extended_price,
        quantity=quantity,
        side='buy',
        is_opening=True
    )

    # 3. 启动WebSocket订单监控
    self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

    # 4. 进入OPENING_MAKER_WAIT状态
    self.state_manager.set_state(BotState.OPENING_MAKER_WAIT)
```

**API调用**:
| 交易所 | 端点 | 参数 |
|--------|------|------|
| Extended | `place_maker_order` | `post_only=True`, `reduce_only=False` |

#### 3.2.4 OPENING_MAKER_WAIT → LIGHTER_HEDGING (Maker模式)

**触发方式**: WebSocket订单更新回调

```python
# spread_arb_bot.py:1917-1966
def _on_maker_order_filled(self, order: MakerOrder):
    """Maker订单完全成交回调"""
    # 1. 停止订单监控
    self.maker_order_monitor.stop_monitoring()

    # 2. 更新HedgingState
    self._hedging_state.ext_filled_quantity = order.filled_quantity
    self._hedging_state.ext_filled_price = order.avg_fill_price

    # 3. 进入LIGHTER_HEDGING状态
    self.state_manager.set_state(BotState.LIGHTER_HEDGING)
```

#### 3.2.5 LIGHTER_HEDGING → OPENING_WAIT

**执行逻辑**:
```python
# trade_executor.py:934-1016
async def execute_lighter_hedge(self, quantity, side, ext_filled_price):
    # 1. 获取Lighter BBO价格
    lig_bid, lig_ask = await lighter_client.fetch_bbo_prices()

    # 2. 计算对冲价格
    lig_price = lig_ask if side == 'buy' else lig_bid

    # 3. 下Lighter Taker订单
    result = await _place_lighter_order_taker(side, quantity, lig_price)

    # 4. 等待Lighter订单成交（3秒超时）
    lighter_success = await _wait_for_lighter_order(order_id, 3.0)

    return ExecutionResult(...)
```

**API调用**:
| 交易所 | 端点 | 方向 | 价格 |
|--------|------|------|------|
| Lighter | `place_limit_order` | sell | `bid`, IOC=0 |

#### 3.2.6 OPENING → OPENING_MAKER_WAIT (Maker模式)

**执行逻辑**:
```python
# spread_arb_bot.py:455-503
async def _process_opening_maker_mode(self, spread_info):
    # 1. 下Extended Maker订单（post_only）
    result = await self.trade_executor.place_maker_open_order(quantity)

    # 2. 初始化Maker等待状态
    self._maker_wait_state.current_order = MakerOrder(
        order_id=result.extended_order_id,
        price=result.extended_price,
        quantity=quantity,
        side='buy',
        is_opening=True
    )

    # 3. 启动WebSocket订单监控
    self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

    # 4. 进入OPENING_MAKER_WAIT状态
    self.state_manager.set_state(BotState.OPENING_MAKER_WAIT)
```

**API调用**:
| 交易所 | 端点 | 参数 |
|--------|------|------|
| Extended | `place_maker_order` | `post_only=True`, `reduce_only=False` |

---

#### 3.2.7 OPENING_MAKER_WAIT → LIGHTER_HEDGING (Maker模式订单成交)

**触发方式**: WebSocket订单更新回调

```python
# spread_arb_bot.py:1917-1966
def _on_maker_order_filled(self, order: MakerOrder):
    """Maker订单完全成交回调（WebSocket实时触发）"""
    # 1. 停止订单监控
    self.maker_order_monitor.stop_monitoring()

    # 2. 更新HedgingState
    self._hedging_state.ext_filled_quantity = order.filled_quantity
    self._hedging_state.ext_filled_price = order.avg_fill_price

    # 3. 进入LIGHTER_HEDGING状态
    self.state_manager.set_state(BotState.LIGHTER_HEDGING,
                                 f"Extended完全成交（WebSocket），开始Lighter对冲")
```

**OPENING_MAKER_WAIT 状态监控逻辑**:
```python
# spread_arb_bot.py:2339-2469
async def _process_opening_maker_wait_state(self):
    """处理 OPENING_MAKER_WAIT 状态：等待Extended Maker订单成交"""

    # ========== 订单成交/取消由 WebSocket 处理 ==========
    # WebSocket 回调会处理：
    # - FILLED: 完全成交 -> LIGHTER_HEDGING
    # - PARTIALLY_FILLED: 部分成交 -> LIGHTER_HEDGING
    # - CANCELED: 订单取消 -> IDLE

    # ========== 主循环只处理：价差保护 + 价格偏离 ==========

    # 1. 检查价差保护
    if spread_info.spread_pct < self.config.fixed_open_threshold:
        # 价差不满足条件，取消订单
        await self.trade_executor.cancel_extended_maker_order(order_id)
        # 检查实际仓位，决定进入IDLE还是HOLDING
        ...

    # 2. 检查价格偏离（只对未成交的订单）
    price_deviated = await self.price_monitor.check_and_notify_price_deviation(...)
    if price_deviated:
        # 取消旧订单并重新挂单
        await self._reposition_maker_order(is_opening=True)
```

---

#### 3.2.8 LIGHTER_HEDGING → OPENING_WAIT (Maker模式对冲完成)

**执行逻辑**:
```python
# spread_arb_bot.py:2525-2590
async def _process_lighter_hedging_state(self):
    """处理 LIGHTER_HEDGING 状态：在Lighter执行对冲订单"""

    # 1. 判断是开仓还是平仓对冲
    if self._hedging_state.is_closing:
        side = 'buy'   # 平仓时Lighter买入
        next_state = BotState.CLOSING_WAIT
    else:
        side = 'sell'  # 开仓时Lighter卖出
        next_state = BotState.OPENING_WAIT

    # 2. 在Lighter执行对冲订单（Taker模式，即时成交）
    result = await self.trade_executor.execute_lighter_hedge(
        quantity=self._hedging_state.ext_filled_quantity,
        side=side,
        ext_filled_price=self._hedging_state.ext_filled_price
    )

    # 3. 对冲成功后进入验证状态
    if result.success:
        self.state_manager.set_state(next_state, f"Lighter对冲成功，等待仓位确认")
    else:
        # 对冲失败，触发强制平仓
        await self._force_close_positions()
```

**API调用**:
| 交易所 | 端点 | 方向 | 价格 |
|--------|------|------|------|
| Lighter | `place_limit_order` | sell (开仓) / buy (平仓) | bid/ask, IOC=0 |

---

#### 3.2.9 OPENING_WAIT → HOLDING (仓位确认成功)

**确认逻辑**:
```python
# spread_arb_bot.py:840-919
async def _process_opening_wait_state(self):
    # 1. 获取两边实际仓位
    ext_position = await extended_client.get_account_positions()
    lig_position = await lighter_client.get_account_positions()

    # 2. 检查仓位是否平衡 (abs(ext - lig) < 0.001)
    positions_match = abs(ext_position - lig_position) < tolerance

    # 3. 仓位确认成功
    if positions_match and not both_zero:
        # 添加仓位到智能平仓系统
        self.close_strategy.add_position(self._pending_open_position)

        # 更新开仓价差
        self.open_strategy.update_cached_spread(self._pending_open_position.open_spread)

        # 进入HOLDING状态
        self.state_manager.set_state(BotState.HOLDING)
```

**API调用**:
| 交易所 | 端点 | 返回值 |
|--------|------|--------|
| Extended | `get_account_positions` | 绝对值持仓数量 |
| Lighter | `get_account_positions` | 原始值持仓数量（空头为负） |

#### 3.2.10 HOLDING → CLOSING

**触发条件**:
- Taker模式: `entry_spread >= current_spread + min_profit + total_fee_rate`
- Maker模式: `entry_spread - current_spread > fixed_close_threshold`

**开仓价差计算**:
```python
# smart_close_strategy.py:57-115
def should_close(self, spread_info: RealTimeSpreadInfo) -> CloseTrigger:
    # 1. 获取加权平均开仓价差（多笔仓位）
    entry_spread = self.portfolio.get_total_entry_spread()

    # 2. 计算预期利润
    expected_profit = entry_spread - current_spread - fee_rate

    # 3. 判断是否触发平仓
    is_triggered = entry_spread >= current_spread + profit_target + fee_rate

    return CloseTrigger(is_triggered, entry_spread, current_spread, ...)
```

#### 3.2.11 CLOSING → CLOSING_WAIT

**执行逻辑**:
```python
# trade_executor.py:272-358
async def execute_close_position(self, position: Position, quantity: Decimal):
    # Taker模式：并发发送平仓订单
    await asyncio.gather(
        _place_extended_order_taker("sell", quantity, None),  # Extended卖出
        _place_lighter_order_taker("buy", quantity, None),   # Lighter买入
        return_exceptions=True
    )

    # 等待订单成交（3秒超时）
    await self.wait_for_execution(ext_order_id, lig_order_id, timeout=3.0)
```

**API调用**:
| 交易所 | 端点 | 方向 | 价格计算 |
|--------|------|------|----------|
| Extended | `place_close_order` | sell | `bid * 0.9998` |
| Lighter | `place_limit_order` | buy | `ask * 1.002`, IOC=0 |

#### 3.2.12 CLOSING_WAIT → IDLE (平仓成功)

**确认逻辑**:
```python
# spread_arb_bot.py:1021-1097
async def _process_closing_wait_state(self):
    # 1. 等待3秒后检查仓位
    await asyncio.sleep(3.0)

    # 2. 获取两边仓位
    ext_position = await extended_client.get_account_positions()
    lig_position = await lighter_client.get_account_positions()

    # 3. 检查是否都已平仓
    ext_closed = ext_position < tolerance
    lig_closed = lig_position < tolerance

    if ext_closed and lig_closed:
        # 平仓成功，清除所有持仓记录
        self.close_strategy.close_all()

        # 更新统计数据
        stats.total_trades += 1
        stats.total_profit += profit

        # 进入IDLE状态
        self.state_manager.set_state(BotState.IDLE)
```

---

## 4. 开仓逻辑详解

### 4.1 Taker模式开仓流程

```python
# ========== 1. IDLE状态：判断是否满足开仓条件 ==========
async def _process_idle_state(self):
    # 获取实时价差
    spread_info = self.spread_monitor.get_current_spread()

    # 等差数列策略判断
    should_open, reason = self.open_strategy.should_open(spread_info)

    if should_open:
        # 风控验证
        validation = await self.risk_manager.validate_open_position(...)
        if validation.is_valid:
            # 进入OPENING状态
            self.state_manager.set_state(BotState.OPENING)

# ========== 2. OPENING状态：执行并发开仓订单 ==========
async def _process_opening_taker_mode(self, spread_info):
    # 执行开仓（并发发送订单）
    result = await self.trade_executor.execute_open_position(
        self.config.target_quantity,
        spread_info
    )

    # 创建待确认的持仓记录
    self._pending_open_position = OpenPosition(
        position_id=str(uuid.uuid4()),
        open_time=datetime.now().timestamp(),
        ext_price=result.extended_price,
        lig_price=result.lighter_price,
        open_spread=spread_info.spread_pct,
        quantity=self.config.target_quantity,
        ext_order_id=result.extended_order_id,
        lig_order_id=result.lighter_order_id,
        is_active=True,
    )

    # 进入OPENING_WAIT状态
    self.state_manager.set_state(BotState.OPENING_WAIT)

# ========== 3. OPENING_WAIT状态：验证仓位确认 ==========
async def _process_opening_wait_state(self):
    # 获取两边实际仓位
    ext_position = await self.extended_client.get_account_positions()
    lig_position = await self.lighter_client.get_account_positions()

    # 检查仓位是否平衡
    positions_match = abs(ext_position - lig_position) < tolerance

    if positions_match and not both_zero:
        # 仓位确认成功
        self.close_strategy.add_position(self._pending_open_position)
        self.open_strategy.update_cached_spread(self._pending_open_position.open_spread)
        self.state_manager.set_state(BotState.HOLDING)
    elif elapsed >= 2.0 and not positions_match:
        # 仓位不对等，执行部分回滚
        await self._rollback_partial_positions(current_qty, ext_position, lig_position)
```

### 4.2 Maker模式开仓流程

```python
# ========== 1. IDLE状态：判断是否满足开仓条件 ==========
async def _process_idle_state(self):
    # 获取实时价差
    spread_info = self.spread_monitor.get_current_spread()

    # Maker模式：固定阈值判断
    current_spread = spread_info.spread_pct
    should_open = current_spread >= self.config.fixed_open_threshold

    if should_open:
        # 进入OPENING状态
        self.state_manager.set_state(BotState.OPENING)

# ========== 2. OPENING状态：下Extended Maker订单 ==========
async def _process_opening_maker_mode(self, spread_info):
    # 下Extended Maker订单
    result = await self.trade_executor.place_maker_open_order(quantity)

    # 初始化Maker等待状态
    self._maker_wait_state.current_order = MakerOrder(
        order_id=result.extended_order_id,
        price=result.extended_price,
        side='buy',
        is_opening=True
    )

    # 启动WebSocket订单监控
    self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

    # 进入OPENING_MAKER_WAIT状态
    self.state_manager.set_state(BotState.OPENING_MAKER_WAIT)

# ========== 3. OPENING_MAKER_WAIT状态：等待订单成交 ==========
async def _process_opening_maker_wait_state(self):
    # 订单成交由WebSocket回调处理，主循环只处理：
    # 1. 价差保护：实时价差 < 开仓阈值时取消订单
    if spread_info.spread_pct < self.config.fixed_open_threshold:
        await self.trade_executor.cancel_extended_maker_order(order_id)
        # 检查实际仓位，决定进入IDLE还是HOLDING
        ...

    # 2. 价格偏离：挂单价格偏离时重新挂单
    price_deviated = await self.price_monitor.check_and_notify_price_deviation(...)
    if price_deviated:
        await self._reposition_maker_order(is_opening=True)

# ========== WebSocket回调：订单成交 ==========
def _on_maker_order_filled(self, order: MakerOrder):
    """Maker订单完全成交回调"""
    # 停止监控
    self.maker_order_monitor.stop_monitoring()

    # 更新HedgingState
    self._hedging_state.ext_filled_quantity = order.filled_quantity
    self._hedging_state.ext_filled_price = order.avg_fill_price

    # 进入LIGHTER_HEDGING状态
    self.state_manager.set_state(BotState.LIGHTER_HEDGING)

# ========== 4. LIGHTER_HEDGING状态：执行Lighter对冲 ==========
async def _process_lighter_hedging_state(self):
    # 在Lighter执行对冲订单（Taker模式）
    result = await self.trade_executor.execute_lighter_hedge(
        quantity=self._hedging_state.ext_filled_quantity,
        side='sell',  # 开仓时Lighter卖出
        ext_filled_price=self._hedging_state.ext_filled_price
    )

    if result.success:
        # 对冲成功，进入OPENING_WAIT验证仓位
        self.state_manager.set_state(BotState.OPENING_WAIT)
    else:
        # 对冲失败，触发强制平仓
        await self._force_close_positions()
```

### 4.3 等差数列开仓策略 (Taker模式)

```python
# arithmetic_open_strategy.py:41-82
def should_open(self, spread_info: RealTimeSpreadInfo) -> tuple[bool, str]:
    current_spread = spread_info.spread_pct
    cached_spread = self.config.cached_open_spread
    spread_step = self.config.spread_step

    # 首次开仓：上次开仓价差为0时，使用最小阈值
    if cached_spread == 0:
        if current_spread >= self.config.min_spread_threshold:
            return True, f"开仓: 价差{current_spread:.3%} >= 阈值{min_threshold:.3%}"

    # 后续开仓：价差必须大于等于上次开仓价差+步长
    threshold = cached_spread + spread_step
    if current_spread >= threshold:
        return True, f"开仓: 价差{current_spread:.3%} >= 阈值{threshold:.3%}"
    else:
        return False, f"价差{current_spread:.3%}未达到开仓条件{threshold:.3%}"

def update_cached_spread(self, new_spread: Decimal) -> None:
    """更新上次开仓价差（只增不减）"""
    if new_spread > self.config.cached_open_spread:
        self.config.cached_open_spread = new_spread
```

### 4.4 风控验证

```python
# risk_manager.py:核心逻辑
async def validate_open_position(self, order_book_manager, quantity, spread_info):
    # 1. 检查订单簿深度
    ext_depth = order_book_manager.check_depth("extended", quantity)
    lig_depth = order_book_manager.check_depth("lighter", quantity)
    if not ext_depth or not lig_depth:
        return ValidationResult(False, "订单簿深度不足")

    # 2. 检查极端价差
    if spread_info.spread_pct > self.config.max_spread:
        return ValidationResult(False, f"极端价差: {spread_info.spread_pct:.3%}")

    # 3. 余额检查
    ext_balance = await extended_client.get_balance()
    lig_balance = await lighter_client.get_balance()
    if ext_balance < required_margin or lig_balance < required_margin:
        return ValidationResult(False, "余额不足")

    return ValidationResult(True, "")
```

---

## 5. 平仓逻辑详解

### 5.1 Taker模式平仓流程

```python
# ========== 1. HOLDING状态：判断是否满足平仓条件 ==========
async def _process_holding_state(self):
    spread_info = self.spread_monitor.get_current_spread()

    # 智能平仓策略判断
    trigger = self.close_strategy.should_close(spread_info)

    if trigger.is_triggered:
        # 进入CLOSING状态
        self.state_manager.set_state(BotState.CLOSING, f"利润目标达成: ...")

# ========== 2. CLOSING状态：执行并发平仓订单 ==========
async def _process_closing_taker_mode(self, total_quantity, entry_spread):
    # 执行平仓
    result = await self.trade_executor.execute_close_position(
        temp_position,
        total_quantity
    )

    # 进入CLOSING_WAIT状态
    self.state_manager.set_state(BotState.CLOSING_WAIT)

# ========== 3. CLOSING_WAIT状态：验证平仓结果 ==========
async def _process_closing_wait_state(self):
    # 等待3秒后检查仓位
    await asyncio.sleep(3.0)

    # 获取两边仓位
    ext_position = await self.extended_client.get_account_positions()
    lig_position = await self.lighter_client.get_account_positions()

    # 检查是否都已平仓
    if ext_closed and lig_closed:
        # 平仓成功，清除所有持仓记录
        self.close_strategy.close_all()

        # 计算利润
        profit = self._calculate_profit_for_portfolio(portfolio, result)

        # 更新统计
        stats.total_trades += 1
        stats.total_profit += profit

        # 进入IDLE状态
        self.state_manager.set_state(BotState.IDLE)
```

### 5.2 Maker模式平仓流程

```python
# ========== 1. HOLDING状态：判断是否满足平仓条件 ==========
async def _process_holding_state(self):
    spread_info = self.spread_monitor.get_current_spread()

    # Maker模式：固定阈值判断
    entry_spread = self.close_strategy.get_weighted_avg_spread()
    current_spread = spread_info.spread_pct
    profit = entry_spread - current_spread

    if profit > self.config.fixed_close_threshold:
        # 进入CLOSING状态
        self.state_manager.set_state(BotState.CLOSING)

# ========== 2. CLOSING状态：下Extended Maker平仓订单 ==========
async def _process_closing_maker_mode(self, total_quantity):
    # 下Extended Maker平仓订单
    result = await self.trade_executor.place_maker_close_order(total_quantity)

    # 初始化Maker等待状态
    self._maker_wait_state.current_order = MakerOrder(
        order_id=result.extended_order_id,
        price=result.extended_price,
        side='sell',
        is_opening=False  # 平仓订单
    )

    # 启动WebSocket订单监控
    self.maker_order_monitor.start_monitoring(self._maker_wait_state.current_order)

    # 进入CLOSING_MAKER_WAIT状态
    self.state_manager.set_state(BotState.CLOSING_MAKER_WAIT)

# ========== 3. CLOSING_MAKER_WAIT状态：等待订单成交 ==========
async def _process_closing_maker_wait_state(self):
    # 订单成交由WebSocket回调处理，主循环只处理价格偏离
    price_deviated = await self.price_monitor.check_and_notify_price_deviation(...)
    if price_deviated:
        await self._reposition_maker_order(is_opening=False)

# ========== WebSocket回调：订单成交 ==========
def _on_maker_order_filled(self, order: MakerOrder):
    """Maker平仓订单完全成交回调"""
    # 停止监控
    self.maker_order_monitor.stop_monitoring()

    # 更新HedgingState
    self._hedging_state.ext_filled_quantity = order.filled_quantity
    self._hedging_state.ext_filled_price = order.avg_fill_price
    self._hedging_state.is_closing = True

    # 进入LIGHTER_HEDGING状态
    self.state_manager.set_state(BotState.LIGHTER_HEDGING)

# ========== 4. LIGHTER_HEDGING状态：执行Lighter对冲 ==========
async def _process_lighter_hedging_state(self):
    # 判断是开仓还是平仓对冲
    if self._hedging_state.is_closing:
        side = 'buy'  # 平仓时Lighter买入
    else:
        side = 'sell'  # 开仓时Lighter卖出

    # 在Lighter执行对冲订单
    result = await self.trade_executor.execute_lighter_hedge(
        quantity=self._hedging_state.ext_filled_quantity,
        side=side,
        ext_filled_price=self._hedging_state.ext_filled_price
    )

    if result.success:
        # 对冲成功，进入CLOSING_WAIT验证仓位
        self.state_manager.set_state(BotState.CLOSING_WAIT)
```

### 5.3 智能平仓策略

```python
# smart_close_strategy.py:57-115
def should_close(self, spread_info: RealTimeSpreadInfo) -> CloseTrigger:
    # 获取加权平均开仓价差（多笔仓位）
    entry_spread = self.portfolio.get_total_entry_spread()

    current_spread = spread_info.spread_pct
    profit_target = self.config.min_profit
    fee_rate = self.config.total_fee_rate

    # 计算预期利润
    expected_profit = entry_spread - current_spread - fee_rate

    # 判断是否触发平仓：开仓价差 >= 当前价差 + 盈利目标 + 手续费
    is_triggered = entry_spread >= current_spread + profit_target + fee_rate

    return CloseTrigger(
        is_triggered=is_triggered,
        entry_spread=entry_spread,
        current_spread=current_spread,
        profit_target=profit_target,
        fee_rate=fee_rate,
        expected_profit=expected_profit
    )
```

### 5.4 多笔仓位管理 (Portfolio)

```python
# models.py:589-671
@dataclass
class Portfolio:
    positions: list[OpenPosition]  # 持仓列表
    total_quantity: Decimal        # 总持仓数量
    weighted_avg_entry_spread: Decimal  # 加权平均开仓价差

    def add_position(self, position: OpenPosition) -> None:
        """添加新仓位"""
        self.positions.append(position)
        self._recalculate()

    def _recalculate(self) -> None:
        """重新计算统计信息"""
        active = self.get_active_positions()
        total_qty = Decimal("0")
        weighted_spread = Decimal("0")

        for pos in active:
            total_qty += pos.quantity
            weighted_spread += pos.open_spread * pos.quantity

        self.total_quantity = total_qty
        self.weighted_avg_entry_spread = weighted_spread / total_qty
```

---

## 6. API调用详情

### 6.1 Extended交易所API

#### 6.1.1 获取BBO价格

```python
# exchanges/extended.py
async def fetch_bbo_prices(self, contract_id: str) -> tuple[Decimal, Decimal]:
    """
    获取最佳买价/卖价

    Returns:
        (bid_price, ask_price)
    """
    # 从WebSocket订单簿获取
    orderbook = self.orderbook
    best_bid = Decimal(orderbook['bid'][0]['p'])
    best_ask = Decimal(orderbook['ask'][0]['q'])
    return best_bid, best_ask
```

#### 6.1.2 下Taker订单

```python
async def place_taker_order(
    self,
    contract_id: str,
    quantity: Decimal,
    side: str,
    price: Decimal
) -> PlaceOrderResult:
    """
    下Taker订单（即时成交）

    Args:
        contract_id: 合约ID
        quantity: 数量
        side: 方向 ('buy' or 'sell')
        price: 价格（跨越价差确保成交）

    Returns:
        PlaceOrderResult {success, order_id, price, error_message}
    """
    # 调用交易所API
    result = await self.place_order(
        contract_id=contract_id,
        quantity=quantity,
        side=side,
        price=price,
        post_only=False,  # Taker模式
        reduce_only=False
    )
    return result
```

#### 6.1.3 下Maker订单

```python
async def place_maker_order(
    self,
    contract_id: str,
    quantity: Decimal,
    direction: str  # 'buy' or 'sell'
) -> PlaceOrderResult:
    """
    下Maker订单（挂单等待成交）

    Args:
        contract_id: 合约ID
        quantity: 数量
        direction: 方向

    Returns:
        PlaceOrderResult {success, order_id, price, size, status}
    """
    # 获取BBO价格
    best_bid, best_ask = await self.fetch_bbo_prices(contract_id)

    # 设置挂单价格（BBO价格）
    if direction == 'buy':
        price = best_bid  # 买单挂在最佳买价
    else:
        price = best_ask  # 卖单挂在最佳卖价

    # 调用交易所API（post_only=True）
    result = await self.place_order(
        contract_id=contract_id,
        quantity=quantity,
        side=direction,
        price=price,
        post_only=True,  # Maker模式
        reduce_only=False
    )
    return result
```

#### 6.1.4 获取仓位

```python
async def get_account_positions(self) -> Decimal:
    """
    获取账户持仓

    Returns:
        持仓数量（绝对值）
    """
    # 调用交易所API
    position_info = await self.get_position()
    position = abs(Decimal(position_info['size']))
    return position
```

#### 6.1.5 查询订单

```python
async def get_order_info(self, order_id: str) -> OrderInfo:
    """
    查询订单信息

    Args:
        order_id: 订单ID

    Returns:
        OrderInfo {order_id, status, price, filled_size}
    """
    # 调用交易所API
    result = await self.query_order(order_id)
    return OrderInfo(
        order_id=result['order_id'],
        status=result['status'],  # NEW, OPEN, PARTIALLY_FILLED, FILLED, CANCELED
        price=Decimal(result['price']),
        filled_size=Decimal(result['filled_size'])
    )
```

#### 6.1.6 取消订单

```python
async def cancel_order(self, order_id: str) -> CancelOrderResult:
    """
    取消订单

    Args:
        order_id: 订单ID

    Returns:
        CancelOrderResult {success, error_message}
    """
    # 调用交易所API
    result = await self.cancel_order_by_id(order_id)
    return CancelOrderResult(
        success=result['success'],
        error_message=result.get('error_message', '')
    )
```

### 6.2 Lighter交易所API

#### 6.2.1 获取BBO价格

```python
# exchanges/lighter.py
async def fetch_bbo_prices(self, contract_id: str) -> tuple[Decimal, Decimal]:
    """
    获取最佳买价/卖价

    Returns:
        (bid_price, ask_price)
    """
    # 从WebSocket获取
    best_bid = Decimal(self.ws_manager.best_bid)
    best_ask = Decimal(self.ws_manager.best_ask)
    return best_bid, best_ask
```

#### 6.2.2 下Taker订单

```python
async def place_limit_order(
    self,
    contract_id: str,
    quantity: Decimal,
    price: Decimal,
    side: str,
    time_in_force: int = 0  # 0=IOC (Immediate or Cancel)
) -> PlaceOrderResult:
    """
    下限价订单

    Args:
        contract_id: 合约ID
        quantity: 数量
        price: 价格
        side: 方向 ('buy' or 'sell')
        time_in_force: 0=IOC立即成交或取消，1=GTC

    Returns:
        PlaceOrderResult {success, order_id, price, error_message}
    """
    # 调用交易所API
    result = await self._place_order(
        contract_id=contract_id,
        quantity=quantity,
        price=price,
        side=side,
        time_in_force=time_in_force
    )
    return result
```

#### 6.2.3 获取仓位

```python
async def get_account_positions(self) -> Decimal:
    """
    获取账户持仓

    Returns:
        持仓数量（原始值，空头为负数）
    """
    # 调用交易所API
    position_info = await self.get_position()
    position = Decimal(position_info['size'])
    return position
```

---

## 7. 风控机制

### 7.1 API异常检测与风控暂停

```python
# spread_arb_bot.py:1191-1218
def _handle_api_error(self, error_message: str) -> None:
    """
    处理API错误，决定是否进入风控模式
    """
    # 检测是否是API错误（HTTP 400, 500, 超时等）
    api_error_keywords = ["HTTP 400", "HTTP 500", "timeout", "connection", "500", "502", "503", "504"]
    is_api_error = any(keyword in error_message.lower() for keyword in api_error_keywords)

    if is_api_error:
        self._api_error_count += 1

        # 达到阈值（连续3次），进入风控模式
        if self._api_error_count >= self._api_error_threshold:
            self._paused_start_time = time.time()
            self.state_manager.set_state(BotState.PAUSED, f"API异常: {error_message}")
```

### 7.2 PAUSED状态：等待API恢复

```python
# spread_arb_bot.py:1139-1189
async def _process_paused_state(self) -> None:
    """处理 PAUSED 状态：风控暂停模式，定期检测API是否恢复"""
    current_time = time.time()

    # 定期检测API是否恢复（每10秒）
    if current_time - self._last_api_check_time >= self._paused_check_interval:
        self._last_api_check_time = current_time

        # 尝试调用API检测是否恢复
        api_recovered = await self._check_api_recovery()

        if api_recovered:
            # API已恢复，退出风控模式
            self._api_error_count = 0

            # 检查是否有持仓，决定返回哪个状态
            position = self.state_manager.get_position()
            if position and position.is_open():
                self.state_manager.set_state(BotState.HOLDING, "API恢复，继续监控持仓")
            else:
                self.state_manager.set_state(BotState.IDLE, "API恢复，等待交易机会")
```

### 7.3 极端价差检测

```python
# spread_calculator.py:275-292
def is_spread_reasonable(self, spread: Decimal) -> bool:
    """
    检查价差是否合理（不是极端价差）

    Returns:
        价差是否合理（<= max_spread）
    """
    reasonable = validate_spread(spread, self.max_spread)

    if not reasonable:
        logger.warning(f"极端价差检测: {spread:.3%} > {self.max_spread:.3%}")

    return reasonable
```

### 7.4 订单簿深度检查

```python
# risk_manager.py
async def validate_open_position(self, order_book_manager, quantity, spread_info):
    # 检查订单簿深度
    ext_orderbook = order_book_manager.get_order_book("extended")
    lig_orderbook = order_book_manager.get_order_book("lighter")

    if not ext_orderbook.check_depth(quantity):
        return ValidationResult(False, "Extended订单簿深度不足")

    if not lig_orderbook.check_depth(quantity):
        return ValidationResult(False, "Lighter订单簿深度不足")

    return ValidationResult(True, "")
```

### 7.5 仓位平衡检查

```python
# spread_arb_bot.py:813-919
async def _process_opening_wait_state(self):
    # 检查仓位是否平衡
    ext_position = await self.extended_client.get_account_positions()
    lig_position = await self.lighter_client.get_account_positions()

    ext_lig_diff = abs(ext_position - lig_position)
    positions_match = ext_lig_diff < tolerance

    if positions_match:
        # 仓位平衡，确认成功
        ...
    elif elapsed >= 2.0 and not positions_match:
        # 等待2秒后仓位仍不对等，执行部分回滚
        await self._rollback_partial_positions(current_qty, ext_position, lig_position)
```

---

## 8. 异常处理

### 8.1 单边成交处理

```python
# trade_executor.py:360-448
async def wait_for_execution(self, extended_order_id, lighter_order_id, timeout=3.0):
    """
    等待订单执行

    重要变更：不再立即判定单边成交，而是等待到超时
    让系统进入OPENING_WAIT状态通过实际仓位检查来判断
    """
    while time.time() - start_time < timeout:
        # 检查订单状态
        extended_status = await self._check_order_status("extended", extended_order_id)
        lighter_status = await self._check_order_status("lighter", lighter_order_id)

        extended_filled = extended_status.get("filled", False)
        lighter_filled = lighter_status.get("filled", False)

        if extended_filled and lighter_filled:
            return {"both_filled": True, "timeout": False}

        # 不再立即判定单边成交，继续等待
        await asyncio.sleep(check_interval)

    # 超时：返回当前状态，让上层逻辑处理
    return {"both_filled": False, "extended_filled": extended_filled, "lighter_filled": lighter_filled, "timeout": True}
```

### 8.2 强平逻辑

```python
# spread_arb_bot.py:1220-1294
async def _force_close_positions(self) -> None:
    """强制平掉所有仓位"""
    max_retries = 3

    for attempt in range(max_retries):
        # 获取当前仓位
        ext_position = await self.extended_client.get_account_positions()
        lig_position = await self.lighter_client.get_account_positions()

        # 并发强平两边
        close_tasks = []
        if abs(ext_position) >= tolerance:
            side = "sell" if ext_position > 0 else "buy"
            close_tasks.append(("extended", abs(ext_position), side))

        if abs(lig_position) >= tolerance:
            side = "buy"  # 空头强平 = 买入
            close_tasks.append(("lighter", lig_position, side))

        # 并发执行强平
        await asyncio.gather(
            *[self.trade_executor.rollback_position(exchange, qty, side)
              for exchange, qty, side in close_tasks],
            return_exceptions=True
        )

        # 验证最终仓位
        final_ext = await self.extended_client.get_account_positions()
        final_lig = await self.lighter_client.get_account_positions()

        if abs(final_ext) < tolerance and abs(final_lig) < tolerance:
            return  # 强平成功
```

### 8.3 部分回滚逻辑

```python
# spread_arb_bot.py:1296-1388
async def _rollback_partial_positions(self, before_qty, ext_current, lig_current) -> None:
    """
    只回滚多出来的仓位，使两边相等（不平全仓）

    策略：取两边较小的仓位作为基准，回滚多出来的部分
    """
    tolerance = Decimal("0.001")

    # 策略：取两边较小的仓位作为基准
    base_qty = min(ext_current, lig_current)

    # 计算两边比基准多出的部分
    ext_extra = max(Decimal("0"), ext_current - base_qty)
    lig_extra = max(Decimal("0"), lig_current - base_qty)

    # 并发回滚两边多出来的仓位
    close_tasks = []
    if ext_extra >= tolerance:
        close_tasks.append(("extended", ext_extra, "sell"))
    if lig_extra >= tolerance:
        close_tasks.append(("lighter", lig_extra, "buy"))

    await asyncio.gather(
        *[self.trade_executor.rollback_position(exchange, qty, side)
          for exchange, qty, side in close_tasks],
        return_exceptions=True
    )
```

### 8.4 Maker订单价格偏离处理

```python
# price_monitor.py:307-392
async def check_and_notify_price_deviation(
    self,
    order_side: str,
    order_price: Decimal,
    order_id: str
) -> bool:
    """
    检查价格偏离并通知（用于Maker订单动态重挂）

    Returns:
        True if price has deviated beyond threshold, False otherwise
    """
    if not self.current_snapshot.is_valid():
        return False

    deviation_threshold = self._tick_size * self.config.price_deviation_threshold

    if order_side.lower() == 'buy':
        # Buy order: should be at or near best bid
        best_bid = self.current_snapshot.ext_bid
        deviation = abs(order_price - best_bid)
        if deviation > deviation_threshold:
            if self.on_price_deviation:
                self.on_price_deviation(order_side, order_price, best_bid)
            return True
    else:  # sell order
        # Sell order: should be at or near best ask
        best_ask = self.current_snapshot.ext_ask
        deviation = abs(order_price - best_ask)
        if deviation > deviation_threshold:
            if self.on_price_deviation:
                self.on_price_deviation(order_side, order_price, best_ask)
            return True

    return False
```

---

## 附录

### A. 状态转换日志格式

```
💥 {旧状态中文} -> {新状态中文} | {原因}
```

示例:
```
💥 空闲 -> 开仓中 | 价差0.080% >= 阈值0.070%
💥 开仓中 -> 开仓等待确认 | 订单已发送: Ext=0x123..., Lig=0x456...
💥 开仓等待确认 -> 持仓中 | 仓位确认成功 Ext=0.01 Lig=0.01
💥 持仓中 -> 平仓中 | 利润目标达成: 开仓0.080% >= 当前0.020% + 利润0.000% + 手续费0.050%
💥 平仓中 -> 平仓等待确认 | 平仓订单已发送，等待确认
💥 平仓等待确认 -> 空闲 | 平仓成功: 利润=$0.50
```

### B. CSV埋点数据

#### 开仓CSV (`logs/trades/open_trades_YYYYMMDD.csv`)

```csv
timestamp,status,ext_position,lig_position,position_diff,target_qty,elapsed_time,open_spread,ext_order_id,lig_order_id
2026-01-19 10:30:45,开仓成功,0.01,0.01,0.000,0.01,1.23,0.0008,0x123...,0x456...
```

#### 平仓CSV (`logs/trades/close_trades_YYYYMMDD.csv`)

```csv
timestamp,entry_spread,close_spread,total_qty,profit,fees,elapsed,status
2026-01-19 10:35:12,0.0008,0.0002,0.01,0.50,0.05,230.5,平仓成功
```

### C. 配置文件示例

```python
# config.py
from decimal import Decimal
from models import BotConfig

config = BotConfig(
    # 交易参数
    symbol="ETH",
    target_quantity=Decimal("0.01"),

    # Taker模式阈值
    min_spread_threshold=Decimal("0.0007"),  # 0.07%
    slippage_buffer=Decimal("0.0001"),        # 0.01%
    min_profit=Decimal("0"),

    # Maker模式阈值
    use_maker_mode=True,
    fixed_open_threshold=Decimal("0.0003"),   # 0.03%
    fixed_close_threshold=Decimal("0.0002"),  # 0.02%

    # 等差数列策略
    spread_step=Decimal("0.00005"),           # 0.005%

    # 风控参数
    single_side_timeout=3.0,
    open_wait_timeout=10.0,
    max_spread=Decimal("0.05"),               # 5%
    total_fee_rate=Decimal("0.0005"),         # 0.05%

    # Maker模式参数
    maker_order_timeout=30.0,
    price_monitor_interval=1.0,
    reposition_cooldown=2.0,
    max_reposition_count=10,
)
```

---

**文档结束**
