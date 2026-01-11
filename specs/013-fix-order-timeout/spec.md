# Feature Specification: 修复订单执行超时和假阳性成交问题

**Feature Branch**: `013-fix-order-timeout`
**Created**: 2026-01-11
**Status**: Draft
**Input**: User description: "修复订单执行超时和假阳性成交问题。Extended订单500ms超时，Lighter错误报告success=True但order_id=None"

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extended订单立即返回不阻塞 (Priority: P1)

交易系统在下单后应立即获得响应，而不是等待订单状态查询完成。

**Why this priority**: 这是核心性能瓶颈。Extended的`get_order_info()`方法阻塞导致500ms超时，使得所有订单都失败。

**Independent Test**: Extended IOC订单提交后，系统应在100ms内返回`success=True`且包含有效的`order_id`，不需要等待订单状态确认。

**Acceptance Scenarios**:

1. **Given** Extended IOC订单已提交到SDK，**When** SDK返回成功响应，**Then** 系统立即返回`success=True, order_id=<有效ID>`，不调用`get_order_info()`
2. **Given** Extended IOC订单提交到SDK，**When** SDK返回失败响应，**Then** 系统返回`success=False`并包含错误信息
3. **Given** Extended IOC订单超时（SDK无响应），**When** 超过500ms，**Then** 系统返回`success=False, error=timeout`

---

### User Story 2 - Lighter订单状态验证 (Priority: P1)

Lighter订单只有在确认有效订单ID存在时才报告成功。

**Why this priority**: 当前Lighter错误地报告`success=True`但`order_id=None`，导致系统误判为单腿持仓并触发不必要的紧急回滚。

**Independent Test**: Lighter订单完成后，如果`order_id=None`或`current_order.order_id`为`None`，应返回`success=False`而不是`success=True`。

**Acceptance Scenarios**:

1. **Given** Lighter WebSocket回调设置了`current_order`，**When** `current_order.order_id`不是`None`且`status='FILLED'`，**Then** 返回`success=True, order_id=<有效ID>`
2. **Given** Lighter WebSocket回调设置了`current_order`，**When** `current_order.order_id`是`None`，**Then** 返回`success=False`并查询API验证
3. **Given** Lighter WebSocket未收到回调，**When** 等待0.5秒后查询API，**Then** 使用`get_inactive_orders()`验证订单状态

---

### User Story 3 - 增强错误日志诊断 (Priority: P2)

当订单执行失败时，日志应显示详细的失败原因，帮助快速定位问题。

**Why this priority**: 当前日志只显示`success=False`但没有具体错误，使得问题诊断困难。

**Independent Test**: 任何订单执行失败时，日志应包含：交易所名称、成功状态、订单ID、具体错误原因。

**Acceptance Scenarios**:

1. **Given** Extended订单超时，**When** 记录失败日志，**Then** 日志包含`Extended: success=False, order_id=None, error=timeout`
2. **Given** Lighter订单失败，**When** 记录失败日志，**Then** 日志包含`Lighter: success=False, order_id=None, error=<具体原因>`
3. **Given** 双边订单都失败，**When** 记录失败日志，**Then** 日志分别显示两个交易所的失败原因

---

### Edge Cases

- Extended订单提交成功但网络延迟导致SDK响应时间 > 400ms：系统应在500ms超时前返回成功，不等待`get_order_info()`
- Lighter WebSocket回调到达但`order_id`字段缺失：系统应返回`success=False`并查询API验证
- Extended和Lighter都返回`success=False`但`order_id=None`：系统应记录为"双边失败"，而不是"单腿持仓"
- 并发执行中一个交易所响应快（<50ms），另一个响应慢（>450ms）：不应触发单腿持仓逻辑

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Extended IOC订单提交后，系统MUST在SDK返回成功时立即返回结果，不调用阻塞的`get_order_info()`方法
- **FR-002**: Extended IOC订单返回时MUST包含有效的`order_id`（不为`None`）
- **FR-003**: Lighter订单MUST只有当`current_order.order_id`不是`None`且`status='FILLED'`时才返回`success=True`
- **FR-004**: Lighter订单当`current_order.order_id`为`None`时MUST返回`success=False`并查询API验证
- **FR-005**: 系统MUST使用`get_inactive_orders()`查询Lighter已成交/已取消订单（因为`get_active_orders()`返回空列表）
- **FR-006**: 订单执行失败时，日志MUST包含：交易所名称、成功状态、订单ID、错误消息
- **FR-007**: 单腿持仓检测MUST只有在一边`success=True, order_id=<有效ID>`且另一边`success=False`时才触发
- **FR-008**: 系统MUST区分"双边失败"（都返回`success=False`）和"单腿持仓"（一边成功一边失败）

### Key Entities

- **订单执行结果**: 包含交易所、成功状态、订单ID、错误消息、成交数量、成交价格
- **单腿持仓事件**: 当一个交易所订单成功而另一个失败时触发，包含成功交易所名称和失败原因
- **订单超时**: 订单执行时间超过配置的超时阈值（默认500ms）

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Extended IOC订单在100ms内返回结果（从SDK调用到返回），成功返回时包含有效`order_id`
- **SC-002**: Lighter订单不再出现`success=True, order_id=None`的假阳性情况
- **SC-003**: 订单失败时日志100%显示具体的失败原因（error字段不为空或"unknown"）
- **SC-004**: 单腿持仓误报率降低到0%（当双边都失败时不应触发单腿持仓逻辑）
- **SC-005**: 订单执行成功率（双边都成功）从当前的0%提升到>90%

---

## Assumptions

1. Extended的`get_order_info()`方法是阻塞的，且需要多次重试（最多50次，每次等待0.5秒）
2. Lighter的`get_active_orders()`总是返回空列表，必须使用`get_inactive_orders()`验证
3. Extended IOC订单使用GTT（Good Till Time）类型，但使用对手价（`best_ask`买单、`best_bid`卖单）会立即成交
4. Lighter WebSocket回调可能在订单提交前或后到达，需要处理竞态条件
5. 并发执行器的500ms超时是合理的性能要求

---

## Dependencies

### Technical Dependencies

- Extended交易所SDK的`place_order()`API响应时间
- Lighter交易所WebSocket回调的可靠性
- 并发执行器的超时配置（`order_timeout_ms`）

### Feature Dependencies

- 依赖011-fix-lighter-hedge中实现的WebSocket OrderCache机制处理竞态条件
- 依赖010-fix-position-imbalance中实现的安全监控器正确记录失败率

---

## Out of Scope

以下内容不在本修复范围内：

1. 修改Extended订单类型（保持GTT不变）
2. 修改并发执行器的超时阈值（保持500ms）
3. 实现Extended WebSocket回调机制（仍使用REST API）
4. 修改单腿持仓回滚逻辑（只确保正确触发）
5. 实现订单重试机制（失败直接返回，不重试）
