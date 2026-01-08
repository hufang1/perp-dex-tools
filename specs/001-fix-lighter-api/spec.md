# Feature Specification: 修复Lighter API调用失败和持仓不平衡问题

**Feature Branch**: `001-fix-lighter-api`
**Created**: 2026-01-07
**Status**: Draft
**Input**: 用户描述: "修复Lighter API调用失败和持仓不平衡问题。日志显示'OrderApi' object has no attribute 'account_active_orders'错误。当前Lighter持仓$95.72，Extended持仓$31.9，存在净空头风险。需要修复API错误并添加持仓对账机制。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 修复Lighter API订单查询失败 (Priority: P1)

当套利机器人尝试查询Lighter订单状态时，系统应该能够正确获取订单信息，而不是因为API方法不存在而失败。

**Why this priority**: 这是最严重的问题，导致所有对冲操作失败，累积单边持仓风险。

**Independent Test**: 可以通过查询一个已存在的Lighter订单来测试 - 系统应该能够返回订单状态、成交价格和成交数量，不抛出AttributeError异常。

**Acceptance Scenarios**:

1. **Given** Lighter订单已成功提交，**When** 系统调用get_order_info()方法查询订单状态，**Then** 系统应该返回OrderInfo对象（包含status、filled_price、filled_size），不抛出"'OrderApi' object has no attribute 'account_active_orders'"异常
2. **Given** Lighter订单刚刚成交，**When** WebSocket订单更新回调到达，**Then** 系统应该能够通过current_order获取订单信息
3. **Given** API查询失败（WebSocket未收到更新），**When** 系统回退到REST API查询，**Then** 系统应该使用正确的API方法名获取订单信息

---

### User Story 2 - 实施持仓对账机制 (Priority: P2)

当系统检测到两端持仓价值不平衡超过阈值时，应该能够自动识别并警告用户，防止风险累积。

**Why this priority**: 当前Lighter持仓($95.72)是Extended($31.9)的3倍，存在严重的净空头暴露，需要及时发现和处理。

**Independent Test**: 可以通过模拟持仓不平衡场景来测试 - 当Lighter持仓价值与Extended持仓价值差异超过10%时，系统应该发出警告并记录详细的对账信息。

**Acceptance Scenarios**:

1. **Given** Extended持仓$35，Lighter空头持仓$95（差异>50%），**When** 对账循环运行，**Then** 系统应该检测到不平衡并记录警告日志"持仓不平衡: Lighter空头$95 vs Extended多头$35，差异$60"
2. **Given** 两端持仓完全平衡，**When** 对账循环运行，**Then** 系统应该记录"持仓对账: 平衡"日志（INFO级别）
3. **Given** 检测到持仓不平衡，**When** 差异超过安全阈值（如20%），**Then** 系统应该触发紧急熔断，禁止开新仓

---

### User Story 3 - 自动平仓不平衡持仓 (Priority: P3)

当系统检测到严重的持仓不平衡且无法自动恢复平衡时，应该能够提供自动平仓选项或清晰的平仓指引。

**Why this priority**: 这是风险控制的最后一道防线，防止小不平衡演变成大损失。

**Independent Test**: 可以通过配置启用自动平仓功能，当检测到不平衡时验证系统是否能够自动平掉多余的持仓。

**Acceptance Scenarios**:

1. **Given** 检测到Lighter空头多于Extended多头，**When** auto_close_unhedged=True，**Then** 系统应该自动平掉多余的Lighter空头以恢复平衡
2. **Given** 检测到不平衡但auto_close_unhedged=False，**When** 不平衡超过阈值，**Then** 系统应该发送清晰的平仓指令："需要平仓 Lighter空头 0.03 ETH 以恢复平衡"
3. **Given** 自动平仓执行失败，**When** 平仓操作返回错误，**Then** 系统应该记录错误日志并保持熔断状态，不继续开仓

---

### Edge Cases

- WebSocket订单更新延迟到达（在get_order_info调用之后到达）
- Lighter API方法名在未来版本中再次变化
- 订单在查询过程中被取消或部分成交
- 持仓对账时价格波动导致价值计算不稳定
- 网络中断导致无法获取实时持仓信息
- 多个套利对同时存在时的复杂持仓计算

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须修复`get_order_info()`方法中的Lighter API调用，使用正确的方法名替代`account_active_orders`
- **FR-002**: 系统必须提供多层回退机制获取订单信息：WebSocket current_order → REST API查询 → 持仓推断
- **FR-003**: 系统必须每60秒执行一次持仓对账，比较Extended和Lighter的持仓价值
- **FR-004**: 系统必须在对账日志中记录：Extended持仓价值、Lighter持仓价值、净暴露、差异百分比
- **FR-005**: 当持仓差异超过20%时，系统必须触发警告并禁止开新仓
- **FR-006**: 系统必须支持配置化的自动平仓功能（auto_close_unhedged参数）
- **FR-007**: 系统必须在检测到不平衡时计算并提供具体的平仓建议（方向、数量、价格）
- **FR-008**: 对账日志必须包含足够信息用于事后分析：时间戳、两端持仓明细、计算过程
- **FR-009**: 系统必须在API调用失败时记录详细的错误信息（方法名、参数、返回值）
- **FR-010**: 修复后的代码必须向后兼容旧版本Lighter SDK（如果适用）

### Key Entities

- **持仓对账记录**: 包含时间戳、Extended持仓（价值、数量、方向）、Lighter持仓（价值、数量、方向）、净暴露、差异百分比、是否触发警报
- **API调用失败记录**: 包含时间戳、调用的方法名、期望的方法名、错误类型、重试次数
- **不平衡警告**: 包含警告时间、不平衡详情、建议的平仓操作、是否已自动处理

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 系统能够成功查询100%的Lighter订单信息，不再出现"'OrderApi' object has no attribute 'account_active_orders'"错误
- **SC-002**: 持仓对账每60秒执行一次，准确率100%（正确计算两端持仓价值和差异）
- **SC-003**: 当持仓差异超过20%时，系统在5秒内触发警告并停止开新仓
- **SC-004**: 对账日志包含所有必要信息，支持事后完整重现对账过程
- **SC-005**: 自动平仓功能（启用时）能在检测到不平衡后30秒内完成平仓操作
- **SC-006**: 系统在修复后能够稳定运行24小时不因API错误或持仓问题崩溃

## Assumptions

- Lighter SDK确实有API方法名的变化（需要通过文档或源码验证）
- 当前持仓不平衡是由于历史对冲失败累积导致的，而非正常的套利对
- 用户有足够的权限和保证金执行自动平仓操作
- 交易所在对账期间不会改变持仓（不计入费用和未实现盈亏的微小变化）
- WebSocket和REST API返回的持仓信息是一致的

## Out of Scope

- 修改Lighter SDK源码（假设我们只能适配我们的代码）
- 实现完整的持仓管理系统（仅对账和简单平仓）
- 自动优化持仓比例（仅检测不平衡，不主动调整策略）
- 多币种同时套利的持仓管理（仅针对单币种ETH）
