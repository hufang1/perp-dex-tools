# Feature Specification: Extended Maker模式降低手续费

**Feature Branch**: `017-ext-maker-mode`
**Created**: 2026-01-18
**Status**: Draft
**Input**: 用户需求：将Extended改为Maker模式降低手续费，固定开仓/平仓价差阈值

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extended使用Maker模式降低手续费 (Priority: P1)

作为价差套利交易者，我希望Extended交易所使用Maker挂单模式而不是Taker吃单模式，这样可以避免支付0.025%的手续费（目前Taker模式每笔交易0.025%，来回一次就是0.05%），从而提高套利利润率。

根据历史数据分析：
- 平均价差：~8.6 bps (0.0086%)
- 最低价差：3.94 bps (0.0039%)
- 最高价差：12.49 bps (0.0125%)

在0.05%手续费下每天只能开10多单，降低到0.025%或更低可以显著增加交易次数。

**Why this priority**: 这是核心诉求，直接影响盈利能力和交易频率。手续费降低是提高套利策略收益的关键因素。

**Independent Test**: 可以通过模拟交易测试，验证Extended使用Maker挂单后手续费计算是否正确，以及订单是否正常成交。

**Acceptance Scenarios**:

1. **Given** Extended当前使用Taker模式支付0.025%手续费，**When** 切换到Maker模式，**Then** Extended手续费降至接近0%
2. **Given** Extended订单簿显示实时价格，**When** 满足开仓条件（价差 >= 0.09%），**Then** 系统从IDLE进入OPENING状态，在Extended挂出Maker限价单（post-only）
3. **Given** Extended Maker订单已挂出，**When** 订单创建成功，**Then** 系统进入OPENING_MAKER_WAIT状态，开始持续监控
4. **Given** 系统在OPENING_MAKER_WAIT状态，**When** Extended订单完全成交（FILLED），**Then** 系统进入LIGHTER_HEDGING状态，在Lighter执行对冲订单
5. **Given** 系统在OPENING_MAKER_WAIT状态挂单0.01 ETH，**When** Extended订单部分成交0.003 ETH（PARTIALLY_FILLED），**Then** 系统进入LIGHTER_HEDGING状态对冲0.003 ETH，完成后回到OPENING_MAKER_WAIT继续等待剩余0.007 ETH成交
6. **Given** 系统在OPENING_MAKER_WAIT状态，**When** 实时价差缩小到0.08%（<0.09%），**Then** 系统立即取消Extended挂单并回到IDLE状态
7. **Given** 系统在LIGHTER_HEDGING状态，**When** Lighter对冲订单完成，**Then** 系统进入OPENING_WAIT状态验证实际仓位（等待10秒）
8. **Given** 系统在OPENING_WAIT状态，**When** 验证成功（两边仓位相等且>0），**Then** 系统进入HOLDING状态
9. **Given** 系统在OPENING_WAIT状态，**When** 验证发现仓位不对等（Extended有0.01 ETH，Lighter有0 ETH），**Then** 系统识别Extended较大，强制平仓Extended的本次开仓数量（0.01 ETH），验证后回到IDLE（无持仓）
10. **Given** 系统在OPENING_WAIT状态，**When** 验证发现仓位不对等（Extended有0.03 ETH=原有0.02+本次0.01，Lighter有0.02 ETH），**Then** 系统识别Extended较大，强制平仓Extended的本次开仓数量（0.01 ETH），验证后回到HOLDING（仍有0.02 ETH持仓）
11. **Given** 系统在LIGHTER_HEDGING状态，**When** Lighter对冲订单失败，**Then** 系统只强制平仓本次新开仓的Extended仓位（保留原有持仓），失败则进入PAUSED状态
12. **Given** 系统在OPENING_MAKER_WAIT状态，**When** 价格频繁波动导致连续重挂达到10次，**Then** 系统取消挂单并回到IDLE状态，记录警告日志
13. **Given** 系统在HOLDING状态，**When** 满足平仓条件（开仓价差 - 当前价差 - 手续费 > 0.06%），**Then** 系统进入CLOSING状态，在Extended挂出Maker卖单
14. **Given** Extended Maker卖单已挂出，**When** 订单创建成功，**Then** 系统进入CLOSING_MAKER_WAIT状态
15. **Given** 系统在CLOSING_MAKER_WAIT状态，**When** Extended卖单完全成交，**Then** 系统进入LIGHTER_HEDGING状态，在Lighter执行买入对冲
16. **Given** 系统在CLOSING_MAKER_WAIT状态，**When** 平仓条件不再满足（价差扩大），**Then** 系统取消Extended挂单并回到HOLDING状态
17. **Given** 系统在LIGHTER_HEDGING状态完成平仓对冲，**When** Lighter买入订单完成，**Then** 系统进入CLOSING_WAIT状态验证仓位（等待3秒）
18. **Given** 系统在CLOSING_WAIT状态，**When** 验证成功（两边都为0），**Then** 系统进入IDLE状态并更新统计信息

---

### User Story 2 - 固定开仓/平仓价差阈值策略 (Priority: P2)

作为策略执行者，我希望使用固定的开仓和平仓价差阈值，而不是阶梯式的等差数列策略，这样可以简化策略逻辑并更灵活地响应市场变化。

- **开仓阈值**：固定0.09%（可配置），当前价差 >= 0.09%时开仓
- **平仓阈值**：固定0.06%（可配置），当 开仓价差 - 手续费 > 0.06%时平仓

**Why this priority**: 简化策略逻辑，去掉阶梯模式，使策略更易于理解和调整。优先级低于P1因为可以先用Maker模式测试。

**Independent Test**: 可以通过回测历史数据验证固定阈值策略的效果，并与现有阶梯策略对比。

**Acceptance Scenarios**:

1. **Given** 当前价差为0.10%，**When** 开仓阈值设置为0.09%，**Then** 触发开仓条件
2. **Given** 当前价差为0.085%，**When** 开仓阈值设置为0.09%，**Then** 不触发开仓条件
3. **Given** 开仓价差为0.095%，当前价差为0.02%，**When** 计算平仓条件，**Then** 判断：0.095% - 0.02% - 0.02%(手续费) = 0.055% < 0.06%，不满足平仓
4. **Given** 开仓价差为0.095%，当前价差为0.01%，**When** 计算平仓条件，**Then** 判断：0.095% - 0.01% - 0.02%(手续费) = 0.065% > 0.06%，满足平仓条件
5. **Given** 配置文件中修改开仓/平仓阈值，**When** 重启程序，**Then** 使用新的阈值进行判断

---

### User Story 3 - Extended挂单监控与价格动态调整 (Priority: P3)

作为系统监控者，我希望Extended的Maker挂单能够实时监控市场价格变化和价差变化，确保：

1. **价格位置优化**：当挂单价格不再处于最优位置时能够主动取消并重新挂单
2. **价差保护**：实时计算两个交易所的价差，当价差不满足开仓条件时立即取消挂单

参考hedge_mode_ext.py的实现逻辑：
- 挂单后监控订单簿最佳买卖价（best bid/ask）
- 当挂单价格不再处于最优位置时取消订单并重新挂单
- **实时价差监控**：持续计算Extended和Lighter的实时价差
- **价差保护机制**：当价差 < 开仓阈值（0.09%）时，立即取消Extended挂单并回到IDLE状态

**价差保护逻辑详解**：
- Extended Maker订单挂出后，系统持续监控两个交易所的实时价差
- 监控频率：每0.5秒计算一次实时价差（可配置）
- 如果实时价差 < 0.09%（开仓阈值），说明套利空间已消失
- 此时立即取消Extended挂单，不做任何交易，回到IDLE状态
- 等待下一次价差 >= 0.09%时，再重新进入开仓逻辑

**Why this priority**: 这是核心风控功能，防止在价差缩小的情况下仍然持有挂单而意外成交导致亏损。优先级设为P3是因为它依赖于P1和P2的实现，但一旦实现后与P1同等重要。

**Independent Test**: 可以模拟价差快速缩小的场景，验证系统是否在价差 < 0.09%时立即取消挂单并回到IDLE状态。

**Acceptance Scenarios**:

1. **Given** Extended挂出买单价格为3000.00，**When** 最佳买价变为3000.01，**Then** 检测到价格偏离，取消旧单并重新挂单到3000.01或更好
2. **Given** Extended挂出卖单价格为3000.00，**When** 最佳卖价变为2999.99，**Then** 检测到价格偏离，取消旧单并重新挂单到2999.99或更好
3. **Given** Extended订单等待期间，**When** 实时价差从0.10%缩小到0.08%（<0.09%），**Then** 立即取消Extended挂单，回到IDLE状态
4. **Given** Extended订单等待超过10秒，**When** 价格仍满足开仓条件（价差 >= 0.09%），**Then** 保持订单活跃，继续等待成交
5. **Given** 系统在IDLE状态，**When** 价差从0.08%上升到0.10%（>=0.09%），**Then** 重新进入开仓逻辑，在Extended挂出Maker单
6. **Given** Extended挂单后价差缩小到0.05%，**When** 系统检测到价差不满足条件，**Then** 在1秒内取消挂单并输出警告日志
7. **Given** Extended挂单期间价差波动，**When** 价差在0.08%~0.12%之间波动，**Then** 只在价差 < 0.09%时取消挂单，价差恢复 >= 0.09%时保持挂单

---

### Edge Cases

- **Extended挂单超时未成交**：如果Extended Maker订单在MAKER_WAIT状态等待超过配置的超时时间（如30秒）仍未成交，系统应该如何处理？
  - 选项A：取消订单，回到IDLE/HOLDING状态
  - 选项B：继续等待直到成交或价格不满足条件
  - **建议**：选项B，因为Maker模式不急于成交，等待最佳价格更重要
  - 我的结论：B

- **Extended部分成交**：如果Extended Maker订单只成交了部分数量（例如挂单0.01 ETH，只成交了0.003 ETH），应该如何处理？
  - 系统应该立即进入LIGHTER_HEDGING状态
  - 只在Lighter对冲已成交的0.003 ETH
  - Extended剩余0.007 ETH部分保持挂单状态
  - 系统回到OPENING_MAKER_WAIT，继续开0.007ETH。

- **价格快速波动导致价差缩小**：在OPENING_MAKER_WAIT状态期间，如果价格快速波动导致价差从0.10%缩小到0.08%，应该如何处理？
  - 立即取消Extended挂单（如果部分成交，只取消未成交部分）
  - 回到IDLE状态
  - 等待下一次价差 >= 0.09%时重新开仓

- **价格快速波动导致价差扩大**：在CLOSING_MAKER_WAIT状态期间，如果价差扩大导致平仓不再有利，应该如何处理？
  - 取消Extended挂单
  - 回到HOLDING状态
  - 等待下一次满足平仓条件

- **WebSocket连接中断**：如果Extended或Lighter的WebSocket连接在MAKER_WAIT状态期间中断，应该如何处理？
  - 使用REST API备份查询Extended订单状态
  - 重连WebSocket后恢复监控
  - 如果无法恢复，取消挂单并进入风控暂停状态

- **订单取消失败**：如果Extended订单取消请求失败（网络问题、API异常），应该如何处理？
  - 重试取消操作（最多3次）
  - 如果仍失败，记录错误并进入风控暂停状态（PAUSED）

- **Lighter对冲失败**：如果Extended成交后，Lighter对冲订单失败，应该如何处理？
  - 立即尝试强制平仓Extended仓位（只设计本次开仓的仓位 原先已经存在的仓位不动）
  - 如果强制平仓失败，进入风控暂停状态（PAUSED）

- **MAKER_WAIT状态循环重挂**：如果价格频繁波动导致系统不断取消并重新挂单，应该如何处理？
  - 限制连续重挂次数（例如最多10次）
  - 超过限制后取消挂单并回到IDLE/HOLDING状态
  - 记录警告日志

- **OPENING_WAIT验证失败**：如果进入OPENING_WAIT状态后发现Extended和Lighter仓位不对等，应该如何处理？
  - 判断两边仓位谁大，谁大的话就代表另一边没有开仓成功，回退仓位大的那一边的这次开单的仓位
  - 根据平仓后的两边仓位是否都大于0判断是回到HOLDING还是回到IDLE状态

- **CLOSING_WAIT验证失败**：如果进入CLOSING_WAIT状态后发现仍有残余仓位，应该如何处理？
  - 如果两边都为0：进入IDLE（成功）
  - 如果单边有仓位：强制平仓后进入IDLE
  - 如果两边都有仓位：回到HOLDING状态（平仓失败，等待再试）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须支持Extended交易所使用Maker模式（post-only限价单）进行开仓和平仓操作
- **FR-002**: 系统必须在Extended挂单后实时监控订单簿价格，当挂单价格不再处于最优位置时取消并重新挂单，保持订单竞争力
- **FR-003**: 系统必须在Extended挂单等待期间持续监控两个交易所的实时价差（监控频率可配置，默认0.5秒），当实时价差 < 开仓阈值（0.09%）时立即取消Extended挂单并回到IDLE状态，防止在不利价差下成交
- **FR-003.1**: 系统必须提供价差监控配置项，包括监控频率（默认0.5秒）和价差计算方式
- **FR-004**: 系统必须支持固定开仓阈值配置（默认0.09%），当前价差 >= 阈值时触发开仓
- **FR-005**: 系统必须支持固定平仓阈值配置（默认0.06%），当 开仓价差 - 当前价差 - 手续费 > 阈值时触发平仓
- **FR-006**: 系统必须在Extended Maker订单成交时立即在Lighter执行对冲订单（Taker模式）
- **FR-007**: 系统必须处理Extended部分成交情况，只对冲实际成交的数量到Lighter，然后回到OPENING_MAKER_WAIT或CLOSING_MAKER_WAIT状态继续等待剩余部分成交
- **FR-008**: 系统必须支持配置项控制Maker模式的各项参数（挂单超时时间、价格监控频率、连续重挂次数限制等）
- **FR-009**: 系统必须计算Extended Maker模式下的手续费（接近0%），并在统计中体现手续费节省
- **FR-010**: 系统必须保持现有的状态机逻辑（IDLE, OPENING, HOLDING, CLOSING等），但调整OPENING和CLOSING状态的处理流程以适配Maker模式
- **FR-011**: 系统必须新增OPENING_MAKER_WAIT状态，用于等待Extended Maker订单成交，该状态需要同时监控三个条件：价差保护、价格位置优化、订单成交状态
- **FR-012**: 系统必须新增CLOSING_MAKER_WAIT状态，用于等待Extended Maker平仓订单成交，该状态需要监控平仓条件、价格位置优化、订单成交状态
- **FR-013**: 系统必须新增LIGHTER_HEDGING状态，用于在Extended成交后执行Lighter对冲订单，该状态需要确保对冲数量与Extended成交数量一致
- **FR-014**: 系统必须支持Extended部分成交场景，在LIGHTER_HEDGING状态对冲已成交部分后，记录本次成交数量，剩余未成交部分回到MAKER_WAIT状态继续挂单等待
- **FR-015**: 系统必须在MAKER_WAIT状态中实现价差保护机制，当价差不满足条件时能够立即取消挂单并返回到前序状态（IDLE或HOLDING）
- **FR-016**: 系统必须实现MAKER_WAIT状态的连续重挂次数限制（可配置，默认10次），超过限制后取消挂单并回到前序状态，记录警告日志
- **FR-017**: 系统必须在Lighter对冲失败时，只强制平仓本次新开仓的Extended仓位，保留原先已存在的仓位不动；如果强制平仓失败，进入风控暂停状态（PAUSED）
- **FR-018**: 系统必须在OPENING_WAIT状态验证仓位不对等时，识别哪边仓位较大（代表该边成功开仓），强制平仓仓位较大那一边的本次开仓数量，然后根据平仓后的实际仓位判断回到HOLDING（仍有持仓）或IDLE（无持仓）
- **FR-019**: 系统必须为所有新增状态（OPENING_MAKER_WAIT、CLOSING_MAKER_WAIT、LIGHTER_HEDGING）提供中文名称映射，并在STATE_NAMES_CN字典中定义
- **FR-020**: 系统必须在每次状态转换时输出统一格式的日志：`💥 {旧状态中文} -> {新状态中文} | {原因}`，同时使用print()强制输出到控制台和logger.info()记录到日志文件
- **FR-021**: 系统必须在OPENING_MAKER_WAIT和CLOSING_MAKER_WAIT状态持续输出监控日志（中文显示），包括：实时价差监控、价格位置优化、订单成交状态、价差保护触发、部分成交处理、重挂次数限制
- **FR-022**: 系统必须在LIGHTER_HEDGING状态输出详细的执行日志（中文显示），包括：对冲订单发送、订单执行进度、成交结果、失败处理、部分成交对冲
- **FR-023**: 系统必须确保所有日志使用中文名称显示状态，数值格式化为易读格式（价差使用百分比，数量保留3位小数），关键事件必须包含上下文信息（订单ID、价格、数量等）

### Key Entities

- **MakerOrder（挂单订单）**：代表Extended上的Maker限价单
  - 订单ID
  - 挂单价格
  - 挂单数量
  - 挂单方向（buy/sell）
  - 订单状态（NEW, OPEN, PARTIALLY_FILLED, FILLED, CANCELED）
  - 成交数量
  - 成交均价
  - 创建时间
  - 最后更新时间
  - 是否为开仓订单（用于区分OPENING_MAKER_WAIT和CLOSING_MAKER_WAIT）

- **SpreadConfig（价差配置）**：固定阈值策略配置
  - 开仓阈值（默认0.09%）
  - 平仓阈值（默认0.06%）
  - Maker挂单超时时间（默认30秒）
  - 价格监控间隔（默认0.5秒）
  - 价差监控间隔（默认0.5秒）

- **PriceMonitor（价格监控器）**：监控Extended订单簿价格变化和实时价差
  - Extended当前最佳买价/卖价
  - Lighter当前最佳买价/卖价
  - 实时价差（Lighter卖价 - Extended买价）
  - 上次检查时间
  - 价格偏离阈值
  - 价差监控频率（默认0.5秒）
  - 价差保护状态（满足/不满足开仓条件）

- **MakerWaitState（Maker等待状态）**：用于OPENING_MAKER_WAIT和CLOSING_MAKER_WAIT状态
  - 当前等待的Maker订单
  - 等待开始时间
  - 价差保护触发次数
  - 价格调整次数（连续重挂计数）
  - 连续重挂次数限制（可配置，默认10次）
  - 部分成交累计数量
  - 本次开仓成交记录（用于识别"本次开仓"部分）
  - 是否需要重新挂单

- **HedgingState（对冲状态）**：用于LIGHTER_HEDGING状态
  - Extended成交数量
  - Extended成交价格
  - Lighter对冲订单ID
  - Lighter对冲数量
  - 对冲开始时间
  - 对冲超时时间（默认3秒）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Extended手续费从当前的0.025%每笔降低至接近0%，每日手续费成本降低至少50%
- **SC-002**: 系统能够在Extended挂单价格偏离最优位置时，在5秒内检测并执行取消/重新挂单操作
- **SC-003**: Extended Maker订单成交率达到至少80%（相比Taker模式的100%即时成交，Maker模式需要等待）
- **SC-004**: 使用固定阈值策略后，每日交易次数相比阶梯策略保持稳定或增加
- **SC-005**: 系统在OPENING_MAKER_WAIT或CLOSING_MAKER_WAIT状态能够正确处理价差不满足条件的情况，在1秒内检测到价差变化并取消挂单
- **SC-006**: Extended部分成交场景下，系统能够准确识别成交数量并在Lighter执行对应对冲，误差不超过0.001 ETH
- **SC-007**: 整体套利利润率提高至少20%（由于手续费降低和固定阈值策略优化）
- **SC-008**: 新状态（OPENING_MAKER_WAIT、CLOSING_MAKER_WAIT、LIGHTER_HEDGING）的状态转换延迟不超过100ms
- **SC-009**: 系统在MAKER_WAIT状态下的监控循环（价差+价格+订单状态）处理时间不超过50ms，确保0.5秒的监控频率
- **SC-010**: LIGHTER_HEDGING状态下的对冲订单执行成功率 >= 99%，失败时能够正确触发强制平仓流程
- **SC-011**: 所有状态转换必须在100ms内输出日志（使用print()强制显示和logger.info()记录），日志格式为中文状态名
- **SC-012**: OPENING_MAKER_WAIT和CLOSING_MAKER_WAIT状态的监控日志输出延迟不超过100ms，确保实时监控信息的及时性
- **SC-013**: 所有监控日志必须使用中文显示状态名，关键事件日志（成交、取消、失败）的完整性达到100%（不得遗漏任何关键事件）

## Assumptions

1. Extended交易所支持Maker模式的post-only订单类型，且该订单类型不会立即吃单成交（避免意外手续费）
2. Extended交易所WebSocket API提供实时的订单状态更新和订单簿深度数据
3. Extended Maker订单在市场正常情况下能够在合理时间（30秒内）成交
4. Lighter交易所保持现有的Taker模式不变，继续作为对冲侧
5. 用户理解Maker模式的成交概率低于Taker模式，可能需要等待更长时间才能成交
6. 固定阈值0.09%（开仓）和0.06%（平仓）是基于历史数据分析得出的合理值，后续可以根据实际表现调整
7. 系统能够通过Extended WebSocket实时获取订单状态变化（NEW → PARTIALLY_FILLED → FILLED）
8. Maker模式下Extended手续费为0%或接近0%（实际费率需根据Extended交易所最新规则确认）

## Context & Dependencies

**现有系统分析**（基于docs/01-opening-logic-analysis.md）：

当前spread套利程序的状态机流程：
- **IDLE** → **OPENING** → **OPENING_WAIT** → **HOLDING** → **CLOSING** → **CLOSING_WAIT** → **IDLE**

开仓逻辑（Taker模式）：
1. IDLE状态监控价差，满足条件后进入OPENING
2. OPENING状态并发发送订单：Extended Taker买入 + Lighter Taker卖出
3. OPENING_WAIT状态验证实际仓位（等待10秒）
4. 确认成功后进入HOLDING状态

平仓逻辑（Taker模式）：
1. HOLDING状态监控价差，满足平仓条件后进入CLOSING
2. CLOSING状态并发发送订单：Extended Taker卖出 + Lighter Taker买入
3. CLOSING_WAIT状态验证实际仓位（等待3秒）
4. 确认成功后进入IDLE状态

**Maker模式状态机重新设计**：

### 核心变化

Taker模式是**并发执行**（Extended和Lighter同时下单），Maker模式是**串行执行**（Extended先成交，然后Lighter对冲）。这需要引入新的中间状态来处理Extended的挂单等待。

### 新的状态定义

需要新增以下状态：

1. **OPENING_MAKER_WAIT**：开仓时等待Extended Maker订单成交
2. **CLOSING_MAKER_WAIT**：平仓时等待Extended Maker订单成交
3. **LIGHTER_HEDGING**：在Lighter执行对冲订单

### 完整的开仓状态转换流程（Maker模式）

```
┌─────────┐
│  IDLE   │  监控价差
└────┬────┘
     │ 当前价差 >= 0.09%（开仓阈值）
     ↓
┌─────────┐
│ OPENING │  Extended挂出Maker买单（post-only）
└────┬────┘
     │ Maker订单已挂出
     ↓
┌───────────────────┐
│ OPENING_MAKER_WAIT │  等待Extended成交（持续监控）
└─────┬─────────────┘
     │
     ├─ 价差 < 0.09% ──────────────────────┐
     │  (价差保护触发)                      │
     │                                      ↓
     │                                  取消Extended订单
     │                                      ↓
     │                                  ┌─────────┐
     │                                  │  IDLE   │  等待下一次机会
     │                                  └─────────┘
     │
     ├─ Extended完全成交 ─────────────────┐
     │                                    ↓
     │                               ┌─────────────────┐
     │                               │ LIGHTER_HEDGING │  在Lighter执行Taker卖出对冲
     │                               └─────────┬───────┘
     │                                         │
     │                                         ↓
     │                                    Lighter订单完成
     │                                         │
     └─────────────────────────────────────────┤
                                               ↓
                                         ┌──────────────────┐
                                         │  OPENING_WAIT    │  验证实际仓位（等待10秒）
                                         └─────────┬────────┘
                                                   │
                                                   ├─ 两边都为0 → IDLE（开仓失败）
                                                   ├─ 两边相等且>0 → HOLDING（开仓成功）
                                                   └─ 仓位不对等 → 强制平仓（只平仓本次开仓的部分） → IDLE/HOLDING/PAUSED

                                         ┌─────────┐
                                         │ HOLDING │  持仓监控
                                         └─────────┘
```

### OPENING_MAKER_WAIT状态的核心职责

这个状态是Maker模式的核心，需要同时监控三个条件：

1. **价差保护**（每0.5秒检查）：
   - 实时计算Extended和Lighter的价差
   - 如果价差 < 0.09%，立即取消Extended挂单 → IDLE

2. **价格位置优化**（每0.5秒检查）：
   - 监控Extended订单簿的best bid/ask
   - 如果挂单价格不再是最优位置，取消旧单并重新挂单
   - 继续保持在OPENING_MAKER_WAIT状态

3. **订单成交监控**（WebSocket实时推送）：
   - 监听Extended订单状态变化
   - NEW → PARTIALLY_FILLED → FILLED
   - 一旦成交（部分或全部），进入LIGHTER_HEDGING状态

### 部分成交处理

如果Extended订单部分成交（PARTIALLY_FILLED）：
- 立即进入LIGHTER_HEDGING状态
- 只在Lighter对冲实际成交的数量（例如：挂单0.01 ETH，成交0.003 ETH，只对冲0.003 ETH）
- 记录本次已成交数量，用于后续识别哪部分是"本次开仓"
- Extended剩余未成交部分继续挂单，回到OPENING_MAKER_WAIT状态继续等待
- 重复此过程直到全部成交或价差不满足条件

### OPENING_WAIT验证失败处理

当进入OPENING_WAIT状态后发现仓位不对等时：

**识别逻辑**：
1. 获取Extended和Lighter的实际仓位
2. 获取本次开仓前的原有持仓数量
3. 判断哪边仓位较大（代表该边成功开仓）
4. 计算需要回滚的数量 = 较大边的仓位 - 较小边的仓位

**回滚逻辑**：
1. 只强制平仓"本次新开仓"的仓位数量（不是全部仓位）
2. 保留原有持仓不动
3. 回滚后验证实际仓位
4. 根据回滚后的结果决定下一状态：
   - 两边都为0 → IDLE（开仓完全失败，无持仓）
   - 两边都有且相等 → HOLDING（仍有原有持仓）
   - 仍不对等 → 强制全平 → IDLE/PAUSED

**示例1：无原有持仓**
- 本次开仓：Extended 0.01 ETH，Lighter 0 ETH（失败）
- 原有持仓：0 ETH
- 识别：Extended较大（0.01 > 0）
- 回滚：强制平仓Extended 0.01 ETH
- 结果：两边都为0 → IDLE

**示例2：有原有持仓**
- 本次开仓：Extended +0.01 ETH，Lighter +0 ETH（失败）
- 原有持仓：Extended 0.02 ETH，Lighter 0.02 ETH
- 验证时：Extended 0.03 ETH，Lighter 0.02 ETH
- 识别：Extended较大（0.03 > 0.02）
- 回滚：强制平仓Extended 0.01 ETH（只平本次开仓部分）
- 结果：Extended 0.02 ETH，Lighter 0.02 ETH → HOLDING

### 完整的平仓状态转换流程（Maker模式）

```
┌─────────┐
│ HOLDING │  监控价差
└────┬────┘
     │ 开仓价差 - 当前价差 - 手续费 > 0.06%（平仓阈值）
     ↓
┌─────────┐
│ CLOSING │  Extended挂出Maker卖单（post-only）
└────┬────┘
     │ Maker订单已挂出
     ↓
┌───────────────────┐
│ CLOSING_MAKER_WAIT │  等待Extended成交（持续监控）
└─────┬─────────────┘
     │
     ├─ 平仓条件不再满足（价差扩大） ──────────┐
     │                                         ↓
     │                                     取消Extended订单
     │                                         ↓
     │                                     ┌─────────┐
     │                                     │ HOLDING │  继续持仓
     │                                     └─────────┘
     │
     ├─ Extended完全成交 ─────────────────┐
     │                                    ↓
     │                               ┌─────────────────┐
     │                               │ LIGHTER_HEDGING │  在Lighter执行Taker买入对冲
     │                               └─────────┬───────┘
     │                                         │
     └─────────────────────────────────────────┤
                                               ↓
                                          Lighter订单完成
                                               │
                                               ↓
                                         ┌──────────────────┐
                                         │  CLOSING_WAIT    │  验证实际仓位（等待3秒）
                                         └─────────┬────────┘
                                                   │
                                                   ├─ 两边都为0 → IDLE（平仓成功，更新统计）
                                                   ├─ 单边有仓位 → 强制平仓 → IDLE
                                                   └─ 两边都有仓位 → HOLDING（平仓失败）

                                         ┌─────────┐
                                         │  IDLE   │  空闲
                                         └─────────┘
```

### CLOSING_MAKER_WAIT状态的核心职责

与OPENING_MAKER_WAIT类似，但平仓时的价差保护逻辑不同：

1. **平仓条件监控**：
   - 不需要监控价差下限（因为是平仓）
   - 但需要监控是否仍然满足平仓条件
   - 如果价差扩大导致平仓不再有利，取消挂单回到HOLDING

2. **价格位置优化**：同开仓逻辑

3. **订单成交监控**：同开仓逻辑

### 状态机变化总结

**新增状态**：
- OPENING_MAKER_WAIT：开仓时等待Extended Maker成交
- CLOSING_MAKER_WAIT：平仓时等待Extended Maker成交
- LIGHTER_HEDGING：执行Lighter对冲订单

**状态转换变化**：
- IDLE → OPENING → OPENING_MAKER_WAIT → LIGHTER_HEDGING → OPENING_WAIT → HOLDING
- HOLDING → CLOSING → CLOSING_MAKER_WAIT → LIGHTER_HEDGING → CLOSING_WAIT → IDLE

**关键设计点**：
1. Maker模式是串行执行，不是并发
2. 需要持续监控价差、价格位置、订单状态
3. 价差保护机制可以在任何时候取消挂单
4. 部分成交需要特殊处理（对冲已成交部分，继续挂未成交部分）

### 监控日志需求

**状态中文名称映射**：

系统必须为所有状态提供中文名称映射（STATE_NAMES_CN），包括新增状态：

```python
STATE_NAMES_CN = {
    # 现有状态
    BotState.IDLE: "空闲",
    BotState.OPENING: "开仓中",
    BotState.OPENING_WAIT: "开仓等待确认",
    BotState.HOLDING: "持仓中",
    BotState.CLOSING: "平仓中",
    BotState.CLOSING_WAIT: "平仓等待确认",
    BotState.PAUSED: "风控暂停",
    BotState.ERROR: "错误",

    # 新增状态
    BotState.OPENING_MAKER_WAIT: "开仓挂单等待成交",
    BotState.CLOSING_MAKER_WAIT: "平仓挂单等待成交",
    BotState.LIGHTER_HEDGING: "lighter对冲中",
}
```

**状态转换日志格式**：

所有状态转换必须输出统一格式的日志（参考现有格式）：

```
💥 {旧状态中文} -> {新状态中文} | {原因}
```

示例：
- `💥 空闲 -> 开仓中 | 满足开仓条件：价差0.10% >= 阈值0.09%`
- `💥 开仓中 -> 开仓挂单等待成交 | Extended挂单成功：订单ID=xxx`
- `💥 开仓挂单等待成交 -> 对冲平仓中 | Extended成交0.003 ETH，执行Lighter对冲`
- `💥 对冲平仓中 -> 开仓等待确认 | Lighter对冲完成，验证实际仓位`

**OPENING_MAKER_WAIT状态监控日志**：

在OPENING_MAKER_WAIT状态下，系统必须持续输出监控日志（中文显示）：

1. **状态进入日志**：
   ```
   💥 开仓中 -> 开仓挂单等待成交 | Extended挂单成功：价格=3000.00，数量=0.01 ETH
   ```

2. **价差监控日志**（每0.5秒或配置的间隔）：
   ```
   📊 状态「开仓挂单等待成交」 实时价差0.10% ✓ 满足开仓条件
   📊 状态「开仓挂单等待成交」 实时价差0.08% ✗ 不满足开仓条件
   ```

3. **价格位置优化日志**（当检测到价格偏离时）：
   ```
   🔄 状态「开仓挂单等待成交」 价格偏离：当前最佳买价3000.01 > 挂单价格3000.00，重新挂单
   🔄 状态「开仓挂单等待成交」 重新挂单完成：新价格=3000.01，重挂次数=1/10
   ```

4. **订单成交日志**：
   ```
   ✅ 状态「开仓挂单等待成交」 Extended订单部分成交：0.003/0.01 ETH，价格=3000.00
   ✅ 状态「开仓挂单等待成交」 Extended订单完全成交：0.01 ETH，价格=3000.00
   ```

5. **价差保护触发日志**：
   ```
   ⚠️ 状态「开仓挂单等待成交」 价差保护触发：实时价差0.08% < 阈值0.09%，取消挂单
   ⚠️ 状态「开仓挂单等待成交」 取消挂单完成，回到空闲状态
   ```

6. **部分成交处理日志**：
   ```
   📊 状态「开仓挂单等待成交」 本次已成交0.003 ETH，剩余0.007 ETH继续挂单
   📊 状态「开仓挂单等待成交」 累计成交0.003/0.01 ETH，继续等待
   ```

7. **重挂次数限制日志**：
   ```
   ⚠️ 状态「开仓挂单等待成交」 连续重挂达到上限(10次)，取消挂单
   ⚠️ 状态「开仓挂单等待成交」 回到空闲状态，等待下一次机会
   ```

**CLOSING_MAKER_WAIT状态监控日志**：

在CLOSING_MAKER_WAIT状态下，系统必须持续输出监控日志（中文显示）：

1. **状态进入日志**：
   ```
   💥 平仓中 -> 平仓挂单等待成交 | Extended挂单成功：价格=3000.00，数量=0.01 ETH
   ```

2. **平仓条件监控日志**：
   ```
   📊 状态「平仓挂单等待成交」 实时价差0.02% ✓ 满足平仓条件
   📊 状态「平仓挂单等待成交」 实时价差0.05% ✗ 不满足平仓条件
   ```

3. **价格位置优化日志**：同OPENING_MAKER_WAIT格式

4. **订单成交日志**：同OPENING_MAKER_WAIT格式

5. **平仓条件不再满足日志**：
   ```
   ⚠️ 状态「平仓挂单等待成交」 平仓条件不再满足：价差扩大到0.05%，取消挂单
   ⚠️ 状态「平仓挂单等待成交」 回到持仓状态
   ```

**LIGHTER_HEDGING状态监控日志**：

在LIGHTER_HEDGING状态下，系统必须输出详细的执行日志（中文显示）：

1. **状态进入日志**：
   ```
   💥 开仓挂单等待成交 -> lighter对冲中 | Extended成交0.003 ETH，开始Lighter对冲
   💥 平仓挂单等待成交 -> lighter对冲中 | Extended成交0.01 ETH，开始Lighter对冲
   ```

2. **对冲订单发送日志**：
   ```
   🚀 状态「lighter对冲中」 发送Lighter对冲订单：方向=卖出，数量=0.003 ETH，价格=2999.95
   🚀 状态「lighter对冲中」 订单ID=xxx，等待成交（超时3秒）
   ```

3. **对冲订单执行日志**：
   ```
   ⏳ 状态「lighter对冲中」 对冲订单执行中... 已等待1.0秒
   ⏳ 状态「lighter对冲中」 对冲订单执行中... 已等待2.0秒
   ```

4. **对冲成功日志**：
   ```
   ✅ 状态「lighter对冲中」 对冲订单成交：数量=0.003 ETH，价格=2999.95
   ✅ 状态「lighter对冲中」 对冲完成，进入开仓等待确认状态
   ```

5. **对冲失败日志**：
   ```
   ❌ 状态「lighter对冲中」 对冲订单失败：订单超时未成交
   ❌ 状态「lighter对冲中」 尝试强制平仓Extended本次仓位（0.003 ETH）
   ```

6. **部分成交对冲日志**：
   ```
   📊 状态「lighter对冲中」 对冲已成交部分：0.003 ETH，回到挂单等待状态
   📊 状态「lighter对冲中」 剩余未成交：0.007 ETH，继续等待Extended成交
   ```

**日志输出级别要求**：

1. **状态转换日志**：必须同时输出：
   - `print()`：强制输出到控制台（使用emoji 💥）
   - `logger.info()`：记录到日志文件

2. **监控日志**：
   - 重要事件（成交、价差保护触发、订单取消）：使用 `logger.info()` 或 `logger.warning()`
   - 实时监控信息（价差、价格位置）：使用 `print()` 或 `logger.info()`
   - 错误信息：使用 `logger.error()`

3. **日志格式要求**：
   - 所有状态名必须使用中文显示
   - 所有数值必须格式化为易读格式（价差使用百分比，数量保留3位小数）
   - 时间戳使用可读格式（例如：`2026-01-18 10:30:45`）
   - 关键事件必须包含上下文信息（订单ID、价格、数量等）

**日志示例完整流程**：

```
# 开仓流程完整日志示例
💥 空闲 -> 开仓中 | 满足开仓条件：价差0.10% >= 阈值0.09%
📊 状态「开仓中」 Extended挂单：买入 0.01 ETH @ 3000.00 (post-only)
💥 开仓中 -> 开仓挂单等待成交 | Extended挂单成功：订单ID=ext_12345
📊 状态「开仓挂单等待成交」 实时价差0.10% ✓ 挂单价格=3000.00，数量=0.01 ETH
📊 状态「开仓挂单等待成交」 实时价差0.10% ✓ 持续监控中...
✅ 状态「开仓挂单等待成交」 Extended订单部分成交：0.003/0.01 ETH @ 3000.00
💥 开仓挂单等待成交 -> lighter对冲中 | Extended成交0.003 ETH，开始Lighter对冲
🚀 状态「lighter对冲中」 发送Lighter对冲订单：卖出 0.003 ETH @ 2999.95
✅ 状态「lighter对冲中」 对冲订单成交：0.003 ETH @ 2999.95
💥 lighter对冲中 -> 开仓挂单等待成交 | 对冲完成，继续等待剩余0.007 ETH
📊 状态「开仓挂单等待成交」 累计成交0.003/0.01 ETH，继续等待...
✅ 状态「开仓挂单等待成交」 Extended订单完全成交：0.01 ETH
💥 开仓挂单等待成交 -> lighter对冲中 | Extended成交0.007 ETH，开始Lighter对冲
🚀 状态「lighter对冲中」 发送Lighter对冲订单：卖出 0.007 ETH @ 2999.95
✅ 状态「lighter对冲中」 对冲订单成交：0.007 ETH @ 2999.95
💥 lighter对冲中 -> 开仓等待确认 | 对冲完成，验证实际仓位
📊 状态「开仓等待确认」 验证仓位：Extended=0.01 ETH，Lighter=0.01 ETH ✓
💥 开仓等待确认 -> 持仓中 | 开仓成功，进入持仓状态
```

### 其他调整

4. **策略模块**：从阶梯策略改为固定阈值策略
5. **手续费计算**：更新为Maker模式的费率（Extended接近0%）
6. **价差保护机制**：在MAKER_WAIT状态中持续监控实时价差

**参考实现**（hedge/hedge_mode_ext.py）：
- 提供了Extended Maker模式的挂单逻辑
- place_extended_post_only_order()方法展示了如何挂post-only订单
- 订单状态监控和取消/重新挂单的逻辑
- WebSocket订单更新处理
