# Implementation Plan: 修复Spread套利脚本价格同步问题

**Branch**: `001-fix-spread-price` | **Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-fix-spread-price/spec.md`

---

## Summary

修复spread套利脚本中Extended交易所开仓成本高于Lighter的问题。根本原因是：
1. **价格获取不同步**：两个交易所独立获取BBO价格导致时间差
2. **Extended缺乏滑点保护**：0%滑点导致IOC订单频繁被取消并重试，重试时使用新价格导致最终成交价不一致
3. **存在Maker模式遗留代码**：可能被误用导致非预期的订单行为

**技术方案**：
- 在execute_open_position层面统一获取两个交易所的价格（时间差<10ms）
- 为Extended加入0.2%滑点保护（与Lighter保持一致）
- 清理/弃用Maker模式的遗留代码
- 限制Extended的重试逻辑（最多1次，使用原始价格）

---

## Technical Context

**Language/Version**: Python 3.10.19 + asyncio, aiohttp, websockets
**Primary Dependencies**: lighter-sdk, x10-python-trading-starknet, pydantic, tenacity
**Storage**: JSON文件状态持久化 (logs/spread_arb_state.json)
**Testing**: 现有日志监控 + CSV埋点数据分析
**Target Platform**: Linux服务器（生产环境）
**Project Type**: 单一Python项目（spread套利脚本）
**Performance Goals**:
  - 价格获取时间差 <10ms
  - 从价格获取到订单发送 <50ms
  - IOC订单失败率降低80%
  - Ext开仓成本 < Lig开仓成本（100%符合套利逻辑）
**Constraints**:
  - 不得影响现有开仓和平仓功能
  - Extended SDK不支持真正的市价单，只能用IOC限价单模拟
  - 0.2%滑点是平衡成交率和成本的最优值
  - 必须保持向后兼容（其他脚本可能使用交易所客户端）
**Scale/Scope**:
  - 修改文件：约3-5个核心文件
  - 新增代码：约100-150行
  - 删除/弃用代码：约50-80行
  - 测试场景：3个主要用户故事

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**状态**: ✅ 通过（Constitution文件为空模板，无需检查）

**说明**：
- 当前项目没有定义Constitution规则
- 实施将遵循Python最佳实践和asyncio异步编程规范
- 所有改动将保持向后兼容性
- 不引入新的外部依赖

---

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-spread-price/
├── spec.md                        # 功能规格说明
├── plan.md                        # 本文件（实施计划）
├── research.md                    # Phase 0输出（技术调研）
├── data-model.md                  # Phase 1输出（数据模型）
├── quickstart.md                  # Phase 1输出（快速开始）
├── contracts/                     # Phase 1输出（API契约）
├── checklists/
│   └── requirements.md            # 需求质量检查清单
├── EXT_TAKER_ANALYSIS.md          # Ext Taker模式分析
└── LIGHTER_MAKER_ANALYSIS.md      # Lighter Maker模式分析
```

### Source Code (repository root)

```text
spread/                            # 核心套利脚本目录
├── trade_executor.py              # 【主要修改】交易执行器
│   ├── execute_open_position()    # 修改：统一价格获取
│   ├── _place_extended_order_taker()  # 修改：加入滑点保护
│   ├── _place_lighter_order_taker()   # 验证：确保taker模式
│   └── _place_*_order()           # 弃用：标记为deprecated
├── spread_arb_bot.py              # 【次要修改】主控制器
│   └── _process_opening_state()   # 修改：价格验证逻辑
├── models.py                      # 【扩展】数据模型
│   └── PriceSnapshot              # 新增：价格快照类
└── utils.py                       # 【扩展】工具函数
    └── validate_price_consistency() # 新增：价格一致性验证

exchanges/                         # 交易所客户端目录
├── extended.py                    # 【主要修改】Extended客户端
│   └── place_taker_order()        # 修改：限制重试逻辑
└── lighter.py                     # 【弃用标记】Lighter客户端
    ├── place_open_order()         # 弃用：标记为deprecated
    └── get_order_price()          # 弃用：标记为deprecated

tests/                             # 测试目录（新增）
├── unit/
│   ├── test_trade_executor.py     # 单元测试
│   └── test_price_sync.py         # 价格同步测试
└── integration/
    └── test_opening_flow.py       # 集成测试
```

**Structure Decision**: 选择单一项目结构（Option 1），因为这是一个纯后端的Python套利脚本，没有前端或移动端组件。所有代码在spread/目录下，exchanges/目录提供交易所客户端封装。

---

## Complexity Tracking

> 本功能不违反任何Constitution规则，此部分无需填写。

---

## Phase 0: Research & Technical Decisions

### Research Tasks

由于当前项目已经完成了详细的代码分析（EXT_TAKER_ANALYSIS.md和LIGHTER_MAKER_ANALYSIS.md），Phase 0的研究工作已经基本完成。以下是对关键问题的决策总结：

#### 决策1：滑点保护比例

**问题**：Extended应该使用多大的滑点保护？

**选项**：
- A. 0%（当前实现）- 失败率30-50%，频繁重试
- B. 0.2%（Lighter方案）- 失败率<5%，已验证可行
- C. 5%（高人建议）- 失败率接近0%，但成本太高

**决策**: 选择 **B. 0.2%滑点保护**

**理由**：
- Lighter已经使用0.2%滑点保护，证明可行
- 平衡了成交率和成本，适合套利策略
- 与Lighter保持一致，便于维护

**替代方案拒绝原因**：
- 0%滑点：失败率太高，导致频繁重试和价格不一致
- 5%滑点：虽然成交率更高，但增加了不必要的成本，对于小价差套利不适用

#### 决策2：价格获取同步方式

**问题**：如何确保两个交易所的价格获取时间同步？

**选项**：
- A. 在execute_open_position层面统一获取
- B. 在_place_*_order_taker内部各自获取
- C. 使用SpreadMonitor的价差数据

**决策**: 选择 **A. 在execute_open_position层面统一获取**

**理由**：
- 可以精确控制两个价格获取的时间差
- 可以在获取后立即验证价格一致性
- 可以在价差异常时跳过开仓，避免损失

**替代方案拒绝原因**：
- B方案：无法控制时间差，当前实现就是这种方式导致问题
- C方案：SpreadMonitor的更新频率可能不够实时

#### 决策3：Extended重试策略

**问题**：Extended IOC订单失败后应该如何重试？

**选项**：
- A. 保持当前10次重试，每次重新获取价格
- B. 禁用内部重试，在execute_open_position层面控制
- C. 限制重试1次，使用原始价格

**决策**: 选择 **C. 限制重试1次，使用原始价格**

**理由**：
- 减少重试期间价格变化的风险
- 降低订单查询延迟
- 保持一定的容错能力（流动性暂时不足）

**替代方案拒绝原因**：
- A方案：当前实现，已证明会导致价格不一致
- B方案：完全禁用重试可能降低成功率，0.2%滑点已能大幅降低失败率

#### 决策4：Maker模式代码处理

**问题**：如何处理exchanges/lighter.py中的Maker模式代码？

**选项**：
- A. 立即删除
- B. 重命名为_legacy
- C. 添加弃用标记

**决策**: 选择 **C. 添加弃用标记**

**理由**：
- 保持向后兼容（其他脚本可能使用）
- 给开发者明确的迁移提示
- 避免破坏性变更

**替代方案拒绝原因**：
- A方案：可能破坏其他脚本
- B方案：不如弃用标记清晰，且需要更新所有调用处

### Technology Stack

**保持不变**：
- Python 3.10.19
- asyncio（异步编程）
- aiohttp（HTTP客户端）
- websockets（WebSocket连接）
- lighter-sdk（Lighter交易所SDK）
- x10-python-trading-starknet（Extended交易所SDK）
- pydantic（数据验证）
- tenacity（重试机制）

**不引入新依赖**，所有改动使用现有技术栈实现。

---

## Phase 1: Design & Contracts

### Data Model

新增数据模型定义在 [data-model.md](./data-model.md)：

#### PriceSnapshot（价格快照）

```python
@dataclass
class PriceSnapshot:
    """价格快照：记录某一时刻两个交易所的BBO价格"""
    # Extended价格
    ext_bid: Decimal
    ext_ask: Decimal
    ext_timestamp: float

    # Lighter价格
    lig_bid: Decimal
    lig_ask: Decimal
    lig_timestamp: float

    # 元数据
    time_delta: float  # 两个时间戳之差（秒）

    def is_valid(self) -> bool:
        """验证价格快照是否有效"""
        return (
            self.ext_bid > 0 and self.ext_ask > 0 and
            self.lig_bid > 0 and self.lig_ask > 0 and
            self.ext_bid < self.ext_ask and
            self.lig_bid < self.lig_ask and
            self.time_delta < 0.01  # 时间差<10ms
        )

    def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]:
        """计算taker订单价格（加入0.2%滑点保护）"""
        ext_price = self.ext_ask * Decimal('1.002')  # Ext买入
        lig_price = self.lig_bid * Decimal('0.998')  # Lig卖出
        return ext_price, lig_price

    def validate_price_consistency(self) -> bool:
        """验证价格一致性（ext买入价 < lig卖出价）"""
        ext_price, lig_price = self.calculate_taker_prices()
        return ext_price < lig_price
```

#### OpenPositionRecord（开仓记录扩展）

扩展现有的OpenPosition模型：

```python
@dataclass
class OpenPositionRecord:
    """开仓记录（扩展）"""
    # 现有字段保持不变
    position_id: str
    open_time: float
    ext_price: Decimal
    lig_price: Decimal
    open_spread: Decimal
    quantity: Decimal
    ext_order_id: str
    lig_order_id: str
    is_active: bool

    # 新增字段
    price_snapshot: PriceSnapshot  # 价格快照
    ext_execution_price: Decimal     # Ext实际成交价
    lig_execution_price: Decimal     # Lig实际成交价
```

### API Contracts

内部API契约定义在 [contracts/](./contracts/)：

#### trade_executor.execute_open_position()

```python
async def execute_open_position(
    self,
    quantity: Decimal,
    spread: Union[RealTimeSpreadInfo, SpreadInfo]
) -> ExecutionResult:
    """
    执行开仓（P0优化：统一价格获取+滑点保护）

    Changes:
    - Phase Before: 各自独立获取价格，Ext无滑点保护
    - Phase After: 统一获取价格，Ext加入0.2%滑点保护

    Args:
        quantity: 交易数量
        spread: 价差信息（仅用于日志记录，实际价格重新获取）

    Returns:
        ExecutionResult:
        - success: 是否成功
        - extended_order_id: Ext订单ID
        - lighter_order_id: Lig订单ID
        - extended_price: Ext使用价格
        - lighter_price: Lig使用价格
        - execution_time: 执行耗时

    Raises:
        ValueError: 价格获取失败或价格不一致
    """
```

#### trade_executor._place_extended_order_taker()

```python
async def _place_extended_order_taker(
    self,
    side: str,
    quantity: Decimal,
    price: Optional[Decimal]
) -> Dict[str, Any]:
    """
    下Extended Taker订单（P0优化：加入0.2%滑点保护）

    Changes:
    - Phase Before: price = best_ask (0%滑点)
    - Phase After: price = best_ask * 1.002 (0.2%滑点)

    Args:
        side: "buy" 或 "sell"
        quantity: 数量
        price: 价格（None表示自动计算）

    Returns:
        Dict: {"order_id": str, "price": Decimal}
    """
```

#### exchanges/extended.place_taker_order()

```python
async def place_taker_order(
    self,
    contract_id: str,
    quantity: Decimal,
    side: str,
    price: Decimal,
    max_retries: int = 1  # 新增：限制重试次数
) -> OrderResult:
    """
    下Extended Taker订单（P0优化：限制重试）

    Changes:
    - Phase Before: max_retries = 10，每次重试重新获取价格
    - Phase After: max_retries = 1，使用原始价格

    Args:
        contract_id: 合约ID
        quantity: 数量
        side: 方向
        price: 价格（不变）
        max_retries: 最大重试次数（新增，默认1）

    Returns:
        OrderResult: 订单结果
    """
```

### Quickstart Guide

完整的快速开始指南定义在 [quickstart.md](./quickstart.md)。

---

## Phase 2: Implementation Plan

### 实施策略

采用**渐进式实施**策略，确保每一步都可以独立验证和回滚。

**实施顺序**：
1. 先添加新功能（价格快照、同步获取）
2. 再修改现有逻辑（Ext滑点保护）
3. 最后清理遗留代码（Maker弃用）

### 详细实施步骤

#### 步骤1：创建价格快照类（30分钟）

**文件**: `spread/models.py`（或创建新文件 `spread/price_snapshot.py`）

**操作**：
```python
# 添加PriceSnapshot类
@dataclass
class PriceSnapshot:
    """价格快照类"""
    ext_bid: Decimal
    ext_ask: Decimal
    ext_timestamp: float
    lig_bid: Decimal
    lig_ask: Decimal
    lig_timestamp: float
    time_delta: float

    def is_valid(self) -> bool:
        """验证价格快照"""
        ...

    def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]:
        """计算taker价格（0.2%滑点）"""
        ...

    def validate_price_consistency(self) -> bool:
        """验证价格一致性"""
        ...
```

**验证**：
- 运行Python导入测试：`python -c "from spread.price_snapshot import PriceSnapshot; print('OK')"`
- 单元测试：创建价格快照并验证方法

**风险**：低（新增代码，不影响现有逻辑）

---

#### 步骤2：在execute_open_position中统一获取价格（1小时）

**文件**: `spread/trade_executor.py`

**当前代码**（Line 85-207）：
```python
async def execute_open_position(self, quantity, spread):
    # 从spread参数获取价格
    if hasattr(spread, 'ext_ask'):
        ext_price = spread.ext_ask  # ❌ 可能是旧价格
        lig_price = spread.lig_bid
    else:
        ext_price = getattr(spread, 'extended_ask_vwap', None)
        lig_price = getattr(spread, 'lighter_bid_vwap', None)

    # 并发发送订单
    results = await asyncio.gather(
        self._place_extended_order_taker("buy", quantity, ext_price),
        self._place_lighter_order_taker("sell", quantity, lig_price),
        return_exceptions=True
    )
```

**修改后代码**：
```python
async def execute_open_position(self, quantity, spread):
    """执行开仓（统一价格获取）"""
    import time

    # Step 1: 统一获取两个交易所的价格
    start_time = time.time()

    ext_bbo_future = self.extended_client.fetch_bbo_prices(
        self.extended_client.config.contract_id
    )
    lig_bbo_future = self.lighter_client.fetch_bbo_prices(
        self.lighter_client.config.contract_id
    )

    # 并发获取，记录时间戳
    ext_fetch_start = time.time()
    ext_bid, ext_ask = await ext_bbo_future
    ext_fetch_time = time.time()

    lig_fetch_start = time.time()
    lig_bid, lig_ask = await lig_bbo_future
    lig_fetch_time = time.time()

    # 计算时间差
    time_delta = abs(lig_fetch_time - ext_fetch_time)

    # Step 2: 创建价格快照
    price_snapshot = PriceSnapshot(
        ext_bid=ext_bid,
        ext_ask=ext_ask,
        ext_timestamp=ext_fetch_time,
        lig_bid=lig_bid,
        lig_ask=lig_ask,
        lig_timestamp=lig_fetch_time,
        time_delta=time_delta
    )

    # Step 3: 验证价格快照
    if not price_snapshot.is_valid():
        logger.warning(
            f"价格快照无效: time_delta={time_delta*1000:.1f}ms, "
            f"跳过此次开仓"
        )
        return ExecutionResult(
            success=False,
            error_message=f"价格快照无效: time_delta={time_delta*1000:.1f}ms",
            execution_time=time.time() - start_time
        )

    # Step 4: 计算taker价格（0.2%滑点）
    ext_price, lig_price = price_snapshot.calculate_taker_prices()

    # Step 5: 验证价格一致性
    if not price_snapshot.validate_price_consistency():
        logger.error(
            f"价差异常: ext买入={ext_price} >= lig卖出={lig_price}, "
            f"跳过此次开仓"
        )
        return ExecutionResult(
            success=False,
            error_message=f"价差异常: ext={ext_price} >= lig={lig_price}",
            execution_time=time.time() - start_time
        )

    logger.info(
        f"价格快照: ext={ext_price:.2f}, lig={lig_price:.2f}, "
        f"time_delta={time_delta*1000:.1f}ms, spread={spread.spread_pct:.2%}"
    )

    # Step 6: 并发发送订单（使用计算好的价格）
    results = await asyncio.gather(
        self._place_extended_order_taker("buy", quantity, ext_price),
        self._place_lighter_order_taker("sell", quantity, lig_price),
        return_exceptions=True
    )

    # ... 后续逻辑保持不变 ...
```

**验证**：
- 启动脚本，观察日志中的"价格快照"输出
- 验证time_delta是否<10ms
- 模拟价差异常场景，验证是否跳过开仓

**风险**：中（核心逻辑修改，需要充分测试）

**回滚方案**：保留旧代码分支，通过配置开关控制新旧逻辑

---

#### 步骤3：修改_place_extended_order_taker加入滑点保护（30分钟）

**文件**: `spread/trade_executor.py`

**当前代码**（Line 580-587）：
```python
if price is None:
    best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
    if side == "buy":
        price = best_ask  # ❌ 0%滑点
    else:
        price = best_bid  # ❌ 0%滑点
```

**修改后代码**：
```python
if price is None:
    # 注意：price通常不再为None，因为execute_open_position已经计算好了
    # 这里保留fallback逻辑，但加入滑点保护
    best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
    if side == "buy":
        price = best_ask * Decimal('1.002')  # ✅ 0.2%滑点
    else:
        price = best_bid * Decimal('0.998')  # ✅ 0.2%滑点
```

**验证**：
- 单元测试：验证滑点计算正确性
- 集成测试：实际下单，验证成交率提升

**风险**：低（简单修改，向后兼容）

---

#### 步骤4：修改Extended客户端限制重试（45分钟）

**文件**: `exchanges/extended.py`

**当前代码**（Line 301-397）：
```python
async def place_taker_order(self, contract_id, quantity, side, price):
    max_retries = 10  # ❌ 最多10次重试
    ...
    while retry_count < max_retries:
        # 下单逻辑
        ...
        if order_info.status in ['CANCELED', 'REJECTED']:
            self.logger.log(f"Taker order not filled, retrying...")
            retry_count += 1
            continue  # 重新获取价格并重试
```

**修改后代码**：
```python
async def place_taker_order(
    self,
    contract_id: str,
    quantity: Decimal,
    side: str,
    price: Decimal,
    max_retries: int = 1  # ✅ 新增参数，默认1次
) -> OrderResult:
    """
    下Extended Taker订单（限制重试版本）

    Args:
        max_retries: 最大重试次数（默认1次，使用原始价格）
    """
    retry_count = 0
    original_price = price  # 缓存原始价格

    while retry_count < max_retries:
        try:
            # 下单逻辑（使用原始价格）
            order_result = await self.perpetual_trading_client.place_order(
                market_name=contract_id,
                amount_of_synthetic=quantity,
                price=original_price,  # ✅ 使用原始价格，不重新获取
                side=order_side,
                time_in_force=TimeInForce.IOC,
                post_only=False,
                expire_time=utc_now() + timedelta(minutes=1),
            )
            ...
            if order_info.status in ['FILLED', 'PARTIALLY_FILLED']:
                # 成功
                return OrderResult(success=True, ...)
            elif order_info.status in ['CANCELED', 'REJECTED']:
                # 失败
                if retry_count < max_retries - 1:
                    self.logger.log(f"Taker order not filled, retrying ({retry_count+1}/{max_retries})...")
                    retry_count += 1
                    await asyncio.sleep(0.05)
                else:
                    return OrderResult(success=False, error_message='Taker order not filled')
        except Exception as e:
            if retry_count < max_retries - 1:
                retry_count += 1
                await asyncio.sleep(0.05)
            else:
                return OrderResult(success=False, error_message=str(e))

    return OrderResult(success=False, error_message='Max retries exceeded')
```

**验证**：
- 单元测试：验证重试逻辑
- 日志分析：验证"Taker order not filled"日志减少

**风险**：中（修改核心下单逻辑，需要谨慎测试）

---

#### 步骤5：弃用Maker模式代码（30分钟）

**文件**: `exchanges/lighter.py`, `trade_executor.py`

**操作**：
```python
# exchanges/lighter.py

import warnings

async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
    """
    ⚠️ DEPRECATED: 此方法使用Maker模式（中间价+GTT+等待循环）

    此方法将于未来版本移除。

    请使用以下Taker模式替代：
    - spread套利：使用 trade_executor._place_lighter_order_taker()
    - 直接调用：使用 place_limit_order(..., time_in_force=0)

    Migration Guide:
    - 旧代码：await client.place_open_order(contract_id, qty, direction)
    - 新代码：await client.place_limit_order(contract_id, qty, price, direction, time_in_force=0)

    Args:
        contract_id: 合约ID
        quantity: 数量
        direction: 方向 ('buy' or 'sell')

    Returns:
        OrderResult: 订单结果
    """
    warnings.warn(
        "place_open_order is DEPRECATED and uses Maker mode. "
        "Use Taker mode with time_in_force=0 instead. "
        "This method will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )

    # 原有实现保持不变
    ...

async def get_order_price(self, side: str = '') -> Decimal:
    """
    ⚠️ DEPRECATED: 此方法使用中间价计算，不适合Taker模式

    此方法将于未来版本移除。

    Migration Guide:
    - Taker买入价：best_ask * 1.002
    - Taker卖出价：best_bid * 0.998

    Args:
        side: 方向

    Returns:
        Decimal: 订单价格（中间价）
    """
    warnings.warn(
        "get_order_price is DEPRECATED. "
        "For Taker mode, use: ask*1.002 (buy) or bid*0.998 (sell). "
        "This method will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )

    # 原有实现保持不变
    ...
```

**验证**：
- 运行脚本，观察是否有DeprecationWarning输出
- 搜索代码库，确认没有调用这些已弃用的方法

**风险**：低（只是添加警告，不改变功能）

---

#### 步骤6：添加单元测试（1小时）

**文件**: `tests/unit/test_trade_executor.py`（新建）

```python
import pytest
from decimal import Decimal
from spread.price_snapshot import PriceSnapshot
from spread.trade_executor import TradeExecutor

class TestPriceSnapshot:
    """价格快照测试"""

    def test_valid_snapshot(self):
        """测试有效的价格快照"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,  # 5ms后
            time_delta=0.005
        )
        assert snapshot.is_valid()

    def test_invalid_snapshot_time_delta(self):
        """测试无效的价格快照（时间差过大）"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.05,  # 50ms后
            time_delta=0.05
        )
        assert not snapshot.is_valid()

    def test_calculate_taker_prices(self):
        """测试taker价格计算"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        ext_price, lig_price = snapshot.calculate_taker_prices()

        # Ext买入 = ask * 1.002
        assert ext_price == Decimal('3000.50') * Decimal('1.002')

        # Lig卖出 = bid * 0.998
        assert lig_price == Decimal('2999.50') * Decimal('0.998')

    def test_validate_price_consistency(self):
        """测试价格一致性验证"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        assert snapshot.validate_price_consistency()

class TestTradeExecutorSlippage:
    """TradeExecutor滑点保护测试"""

    @pytest.mark.asyncio
    async def test_extended_slippage_protection(self):
        """测试Ext滑点保护"""
        # Mock fetch_bbo_prices
        # 调用 _place_extended_order_taker
        # 验证价格包含滑点
        pass

    @pytest.mark.asyncio
    async def test_price_sync(self):
        """测试价格同步获取"""
        # Mock 两个交易所的fetch_bbo_prices
        # 调用 execute_open_position
        # 验证时间差<10ms
        pass
```

**验证**：
- 运行单元测试：`pytest tests/unit/test_trade_executor.py`
- 确保所有测试通过

**风险**：低（新增测试，不影响现有功能）

---

#### 步骤7：集成测试和监控（1小时）

**文件**: `tests/integration/test_opening_flow.py`（新建）

```python
import pytest
import asyncio
from decimal import Decimal
from spread.spread_arb_bot import SpreadArbBot
from spread.models import BotConfig

class TestOpeningFlow:
    """开仓流程集成测试"""

    @pytest.mark.asyncio
    async def test_opening_with_price_sync(self):
        """测试价格同步开仓"""
        # 模拟价差监控信号
        # 执行开仓
        # 验证：
        # 1. 价格获取时间差<10ms
        # 2. Ext买入价 < Lig卖出价
        # 3. 开仓成功
        pass

    @pytest.mark.asyncio
    async def test_opening_skip_on_price_inconsistency(self):
        """测试价差异常时跳过开仓"""
        # 模拟价差异常场景
        # 验证开仓被跳过
        pass
```

**日志监控**：

在 `spread/trade_executor.py` 中添加详细日志：

```python
logger.info(
    f"[价格同步] "
    f"ext_bid={ext_bid:.2f}, ext_ask={ext_ask:.2f}, "
    f"lig_bid={lig_bid:.2f}, lig_ask={lig_ask:.2f}, "
    f"time_delta={time_delta*1000:.1f}ms, "
    f"ext_price={ext_price:.2f}, lig_price={lig_price:.2f}, "
    f"spread={ext_price/lig_price - 1:.4%}"
)

logger.info(
    f"[开仓成功] "
    f"ext_order_id={extended_order_id}, lig_order_id={lighter_order_id}, "
    f"ext_price={extended_price:.2f}, lig_price={lighter_price:.2f}, "
    f"execution_time={execution_time:.3f}s"
)
```

**验证**：
- 运行集成测试
- 观察生产环境日志
- 统计"Order not found"日志减少比例

**风险**：低（测试和监控，不改变核心逻辑）

---

### 测试策略

#### 单元测试

| 测试类 | 覆盖范围 | 优先级 |
|--------|----------|--------|
| TestPriceSnapshot | 价格快照类所有方法 | P0 |
| TestTradeExecutorSlippage | 滑点保护计算 | P0 |
| TestExtendedRetry | Extended重试逻辑 | P1 |

#### 集成测试

| 测试场景 | 验证内容 | 优先级 |
|----------|----------|--------|
| 正常开仓流程 | 价格同步+滑点保护 | P0 |
| 价差异常场景 | 跳过开仓 | P0 |
| 价格超时场景 | 处理逻辑 | P1 |
| IOC订单失败 | 重试机制 | P1 |

#### 生产验证

| 验证项 | 当前值 | 目标值 | 验证方法 |
|--------|--------|--------|----------|
| 价格获取时间差 | N/A | <10ms | 日志分析 |
| Ext IOC失败率 | ~30-50% | <5% | 日志统计 |
| Ext成本>Lig成本 | 经常出现 | 0% | 仓位分析 |
| "Order not found"日志 | 频繁 | 减少80%+ | 日志统计 |

---

### 风险控制

#### 风险1：破坏现有开仓功能

**概率**: 中
**影响**: 高
**缓解措施**:
- 使用特性开关控制新旧逻辑
- 在测试环境充分验证
- 保留旧代码分支便于回滚
- 分阶段发布（先小仓位测试）

#### 风险2：价格同步延迟增加

**概率**: 低
**影响**: 中
**缓解措施**:
- 并发获取价格（asyncio.gather）
- 只在execute_open_position层面同步
- 不影响价差监控（SpreadMonitor）

#### 风险3：滑点成本增加

**概率**: 低
**影响**: 低
**缓解措施**:
- 0.2%滑点已由Lighter验证可行
- 相比频繁重试的价格波动，0.2%更可控
- 可通过配置调整滑点大小

#### 风险4：弃用警告影响其他脚本

**概率**: 低
**影响**: 低
**缓解措施**:
- 只添加警告，不改变功能
- 提供清晰的迁移指南
- 保留向后兼容性

---

### 回滚计划

如果实施后出现问题，按以下步骤回滚：

1. **立即回滚**：恢复修改前的文件
   ```bash
   git checkout HEAD~1 spread/trade_executor.py
   git checkout HEAD~1 exchanges/extended.py
   ```

2. **配置回滚**：如果使用了特性开关，修改配置
   ```python
   # spread/config.py
   USE_UNIFIED_PRICE_FETCH = False  # 禁用新逻辑
   EXT_SLIPPAGE_PROTECTION = False  # 禁用滑点保护
   ```

3. **验证回滚**：确认旧功能恢复正常
   - 检查日志输出
   - 执行测试开仓
   - 验证仓位平衡

---

### 部署计划

#### 阶段1：测试环境（1天）

- 部署到测试服务器
- 执行单元测试和集成测试
- 模拟开仓流程
- 监控日志和性能指标

#### 阶段2：小仓位试运行（1-2天）

- 部署到生产环境
- 限制开仓数量（如0.01 ETH）
- 密切监控日志
- 验证Ext成本<Lig成本

#### 阶段3：全量发布（确认后）

- 移除仓位限制
- 持续监控3-7天
- 收集数据并优化

---

## Success Criteria

### 验收标准

| 标准 | 测量方法 | 目标值 |
|------|----------|--------|
| 价格获取时间差 | 日志分析 | <10ms (100%) |
| Ext IOC失败率 | 日志统计 | <5% |
| Ext成本>Lig成本 | 仓位分析 | 0次 |
| "Order not found"减少 | 日志对比 | 减少80%+ |
| 开仓成功率 | 功能测试 | >95% |

### 完成定义

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 测试环境验证通过
- [ ] 小仓位试运行成功（24小时无异常）
- [ ] Ext成本<Lig成本（100笔开仓样本）
- [ ] "Order not found"日志减少80%+
- [ ] Maker代码已添加弃用标记
- [ ] 文档已更新（quickstart.md, data-model.md）

---

## Appendix

### 相关文档

- [Feature Spec](./spec.md) - 功能规格说明
- [Ext Taker Analysis](./EXT_TAKER_ANALYSIS.md) - Ext Taker模式详细分析
- [Lighter Maker Analysis](./LIGHTER_MAKER_ANALYSIS.md) - Lighter Maker模式代码分析
- [Requirements Checklist](./checklists/requirements.md) - 需求质量检查清单

### 修改文件清单

| 文件 | 改动类型 | 代码行数 | 风险等级 |
|------|----------|----------|----------|
| `spread/price_snapshot.py` | 新增 | ~80 | 低 |
| `spread/trade_executor.py` | 修改 | ~50 | 中 |
| `exchanges/extended.py` | 修改 | ~30 | 中 |
| `exchanges/lighter.py` | 弃用标记 | ~20 | 低 |
| `tests/unit/test_*.py` | 新增 | ~150 | 低 |
| `tests/integration/test_*.py` | 新增 | ~80 | 低 |
| `docs/*.md` | 新增 | ~500 | 低 |

**总计**: 新增约910行，修改约80行

### 时间估算

| 阶段 | 任务 | 估算时间 |
|------|------|----------|
| Phase 0 | 技术调研 | ✅ 已完成 |
| Phase 1 | 设计和数据模型 | 2小时 |
| Phase 2 | 代码实施 | 4小时 |
| | 单元测试 | 1小时 |
| | 集成测试 | 1小时 |
| | 测试环境验证 | 1小时 |
| | 小仓位试运行 | 1-2天 |
| **总计** | | **约8小时开发 + 1-2天验证** |

---

**计划版本**: 1.0
**最后更新**: 2026-01-16
**状态**: Ready for Phase 0 Execution (Research已完成，可直接进入Phase 1)
