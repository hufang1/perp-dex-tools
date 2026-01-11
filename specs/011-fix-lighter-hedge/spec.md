# Feature Specification: 修复Lighter对冲失败和实现双腿并发IOC订单系统

**Feature Branch**: `011-fix-lighter-hedge`
**Created**: 2026-01-11
**Status**: Draft
**Input**: 用户描述: "现在这是价差套利程序运行几分钟的日志输出。我发现了一个很严重的问题，ext在疯狂的挂单开仓，但是lig却没有任何反应。请你修复这个可怕的bug。并检查一下其余的逻辑是否吻合 @docs/requirement/02.md 文档的诉求"

## 问题分析摘要

根据日志分析（operations_2026_01_11.csv），系统存在以下严重问题：

1. **开仓成功率极低**: 30次开仓尝试仅3次成功，成功率10%
2. **Extended疯狂开仓但Lighter无响应**: 日志显示Extended订单成功但Lighter对冲失败
3. **根本原因**:
   - `exchanges/lighter.py`的`place_open_order`方法使用限价单+10秒等待成交循环
   - 并发执行器虽然使用`asyncio.gather`，但Lighter订单阻塞10秒，破坏了并发性
   - 违反了需求文档02.md的核心要求：必须使用IOC订单实现毫秒级并发

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 实现真正的双腿并发IOC订单 (Priority: P1)

**描述**: 修复当前的伪并发问题，实现Extended和Lighter两个交易所订单在5ms内同时发送，使用IOC（立即成交或取消）订单类型，避免任何等待循环。

**Why this priority**: 这是导致"Extended疯狂开仓但Lighter无响应"的根本原因。根据需求文档02.md第1.2节，必须使用asyncio.gather同时构建并发送两边的订单请求，且订单类型必须是IOC。当前系统使用限价单+10秒等待，完全违背了核心设计。

**Independent Test**: 可以通过日志验证发送时间差（send_gap_ms）是否<5ms，以及两个订单是否在同一毫秒级时间窗口内发送。

**Acceptance Scenarios**:

1. **Given** 系统检测到价差套利机会，**When** 执行双腿并发下单，**Then** Extended和Lighter订单发送时间差<5ms，且两个订单都使用IOC类型（不等待成交）
2. **Given** Extended订单成功但Lighter订单失败，**When** 检测到单腿持仓，**Then** 系统在500ms内自动触发紧急平仓回滚，记录[CRITICAL]日志
3. **Given** 双边订单都发送成功，**When** 订单执行完成，**Then** 系统记录完整的性能指标（发送时间差、总延迟、成交状态）

---

### User Story 2 - 实现Lighter IOC订单支持 (Priority: P1)

**描述**: 为Lighter交易所实现IOC订单类型支持，替代当前的限价单+等待成交模式。IOC订单应该立即成交，不能成交则自动取消，无需等待。

**Why this priority**: 当前Lighter客户端(exchanges/lighter.py)只有限价单实现，且place_open_order方法包含10秒等待循环（第321-324行）。这直接导致并发下单变成串行执行，违反了需求文档02.md第2.1节的要求。

**Independent Test**: 单独测试Lighter IOC订单，验证订单发送后立即返回结果，不包含任何等待循环。

**Acceptance Scenarios**:

1. **Given** 需要在Lighter下单，**When** 调用place_ioc_order方法，**Then** 订单在100ms内返回结果，成功则返回订单ID，失败则返回错误
2. **Given** IOC订单部分成交，**When** 订单执行完成，**Then** 返回部分成交的数量和价格，未成交部分自动取消
3. **Given** IOC订单无法立即成交，**When** 订单发送，**Then** 订单被自动取消，返回0成交数量

---

### User Story 3 - 实现闪电回滚机制 (Priority: P1)

**描述**: 当检测到单腿持仓（Extended成交但Lighter失败，或反之）时，立即在500ms内对已成交的腿执行市价平仓，消除风险敞口。

**Why this priority**: 需求文档02.md第6节明确要求：当A成交而B失败时，触发时间应在收到B失败/超时回报的0ms后，动作为对A持仓部分发起市价全平。当前系统虽然有LegRollbackHandler，但依赖于并发下单的正确执行。

**Independent Test**: 模拟Lighter下单失败场景，验证Extended持仓是否在500ms内被平仓。

**Acceptance Scenarios**:

1. **Given** Extended订单成交但Lighter订单超时/失败，**When** 检测到单腿持仓，**Then** 系统在500ms内对Extended持仓执行市价平仓
2. **Given** 执行了闪电回滚，**When** 回滚完成，**Then** 系统记录[CRITICAL] Legging detected, rolling back position日志，包含回滚延迟时间
3. **Given** 闪电回滚失败，**When** 重试3次后仍失败，**Then** 系统触发完全暂停，发送紧急告警

---

### User Story 4 - 动态利润风控验证 (Priority: P2)

**描述**: 在开仓前进行严格的利润验证，确保扣除双边手续费、滑点成本、最小净利要求后的净利为正。对于0.07%的微小价差，必须精确计算。

**Why this priority**: 需求文档02.md第3节强调：只有当"扣除所有成本后的净利"依然为正时，才允许开仓。0.07%的毛利极易被手续费吃光。如果Taker费率总和>0.06%，应该禁止交易。

**Independent Test**: 使用不同价差率测试开仓决策，验证系统是否正确拒绝利润不足的交易。

**Acceptance Scenarios**:

1. **Given** 价差率为0.07%，双边手续费总和为0.045%，**When** 计算净利，**Then** 系统应该拒绝开仓（净利仅0.025% < 最小净利要求0.02%）
2. **Given** 价差率为0.10%，双边手续费总和为0.045%，**When** 计算净利，**Then** 系统允许开仓（净利0.055% > 0.02%）
3. **Given** 配置的Taker费率总和>0.06%，**When** 系统启动，**Then** 系统记录警告日志并禁用策略（0.07%价差在数学上无法盈利）

---

### User Story 5 - 数据时效性熔断 (Priority: P2)

**描述**: 在计算价差前，强制检查订单簿数据的时效性。如果数据延迟超过500ms，放弃本次机会，防止基于过期数据交易。

**Why this priority**: 需求文档02.md第4.1节要求：MAX_DATA_DELAY = 500ms，逻辑必须放在calculate_spread之前。使用过期数据会导致开仓价格与实际市场严重偏离。

**Independent Test**: 人为延迟订单簿数据，验证系统是否拒绝基于过期数据的交易机会。

**Acceptance Scenarios**:

1. **Given** 订单簿数据时间戳为600ms前，**When** 系统检测到套利机会，**Then** 系统放弃本次机会并记录"数据过期(600ms)"警告
2. **Given** 订单簿数据时间戳为300ms前，**When** 系统检测到套利机会，**Then** 系统正常处理该机会
3. **Given** 数据延迟连续超过阈值3次，**When** 系统检测，**Then** 触发数据质量警告，建议检查WebSocket连接

---

### User Story 6 - 极简平仓策略 (Priority: P3)

**描述**: 简化平仓逻辑，只监控当前净价差。当价差回归满足止盈条件（Current_Spread <= Open_Spread - Target_Profit）或扩大满足止损条件（Current_Spread >= Open_Spread + Stop_Loss_Threshold）时平仓。

**Why this priority**: 需求文档02.md第5节要求废弃复杂的holding_time和P1-P5优先级逻辑，只监控价差变化。简化逻辑可以减少误判和延迟。

**Independent Test**: 模拟不同价差变化场景，验证平仓决策是否基于净价差变化。

**Acceptance Scenarios**:

1. **Given** 开仓价差为0.10%，目标利润为0.02%，**When** 当前价差降至0.08%，**Then** 系统执行止盈平仓
2. **Given** 开仓价差为0.10%，止损阈值为0.10%，**When** 当前价差升至0.20%，**Then** 系统执行止损平仓
3. **Given** 持仓超过300秒但价差仍在可接受范围，**When** 检查平仓条件，**Then** 系统不平仓（等待价差回归）

---

### Edge Cases

- **网络分区**: 如果Lighter WebSocket连接断开但Extended仍在线，系统如何防止单腿持仓？
  - 应该检测到连接断开后立即禁止开仓，已持仓的触发紧急平仓

- **部分成交**: 如果Extended订单成交50%但Lighter完全失败，如何处理？
  - 应该对Extended已成交的50%执行紧急平仓，未成交的50%自动取消

- **价格剧烈跳动**: 如果网络传输期间价格跳动了5%超过滑点容忍，IOC订单如何处理？
  - IOC订单自动取消，系统记录"价格跳过大，放弃机会"日志

- **并发竞态**: 如果WebSocket回调在订单ID设置前到达，如何处理？
  - 使用缓存机制存储订单更新，等待订单ID设置后再处理

- **流动性不足**: 如果Lighter订单簿深度不足，如何检测？
  - 在开仓前检查订单簿深度是否足够（如要求$5000流动性）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须使用asyncio.gather同时发送Extended和Lighter订单，发送时间差必须<5ms
- **FR-002**: 系统必须使用IOC订单类型（Immediate or Cancel），不能使用限价单+等待成交模式
- **FR-003**: Lighter客户端必须实现place_ioc_order方法，订单发送后必须在100ms内返回，不包含等待循环
- **FR-004**: 系统必须检测单腿持仓（双边成交状态不一致），检测延迟<100ms
- **FR-005**: 系统必须在检测到单腿持仓后500ms内执行闪电回滚（市价平仓已成交的腿）
- **FR-006**: 系统必须在开仓前计算净利（价差率 - 双边手续费 - 滑点成本 - 最小净利），净利必须>0
- **FR-007**: 系统必须检查订单簿数据时效性，延迟>500ms的数据必须拒绝
- **FR-008**: 系统必须记录完整的性能指标：send_gap_ms、total_latency_ms、tick_to_trade_latency_ms
- **FR-009**: 系统必须记录[CRITICAL]级别日志：单腿持仓检测、闪电回滚执行、数据过期警告
- **FR-010**: 平仓决策必须基于净价差变化（当前价差 vs 开仓价差），移除时间优先级逻辑

### Key Entities

- **ConcurrentOrderResult**: 并发订单执行结果
  - extended_success/lighter_success: 双边成交状态
  - send_gap_ms: 发送时间差（必须<5ms）
  - total_latency_ms: 总执行时间（必须<500ms）
  - is_legging: 是否单腿持仓
  - is_both_failed: 是否双边失败

- **LegRollbackEvent**: 闪电回滚事件
  - rollback_latency_ms: 回滚执行延迟（必须<500ms）
  - rollback_success: 回滚是否成功
  - legging_side: 持仓的腿（extended/lighter）

- **ProfitabilityCheck**: 利润检查结果
  - spread_rate: 当前价差率
  - total_fees: 双边手续费总和
  - net_profit_rate: 净利润率
  - is_profitable: 是否可交易

- **DataFreshnessResult**: 数据新鲜度检查
  - data_age_ms: 数据年龄（毫秒）
  - is_fresh: 是否新鲜（<500ms）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 双腿订单发送时间差<5ms（95%的订单）
- **SC-002**: 总执行延迟<500ms（90%的订单）
- **SC-003**: 开仓成功率>90%（当前仅10%）
- **SC-004**: 单腿持仓检测延迟<100ms
- **SC-005**: 闪电回滚执行延迟<500ms（95%的回滚）
- **SC-006**: 数据过期检测率100%（所有延迟>500ms的数据都被拒绝）
- **SC-007**: 利润不足拒绝率100%（所有净利<=0的交易都被拒绝）
- **SC-008**: 系统不产生单腿持仓超过1秒的情况
- **SC-009**: 交易日志包含完整的性能指标和诊断信息
- **SC-010**: 符合需求文档02.md的所有P0要求

## Assumptions

1. Extended和Lighter交易所都支持IOC订单类型或等效机制
2. WebSocket连接稳定，网络延迟<100ms（本地环境）
3. 双边Taker费率总和<0.06%，否则0.07%价差无法盈利
4. 订单簿数据包含时间戳字段，可用于时效性检查
5. 市价单可以在Lighter交易所执行（用于紧急平仓）
6. 系统可以在500ms内完成市价平仓操作

## Dependencies

1. Extended交易所客户端已正确实现IOC订单支持
2. Lighter交易所SDK支持IOC订单或可通过配置参数实现
3. WebSocket连接管理器正常工作，订单回调及时到达
4. 性能监控器可以记录毫秒级时间戳
5. 日志系统支持[CRITICAL]级别日志记录
