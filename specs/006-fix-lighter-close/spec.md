# Feature Specification: 修复强制平仓时Extended和Lighter都无法正常平仓的问题

**Feature Branch**: `006-fix-lighter-close`
**Created**: 2026-01-09
**Status**: Draft
**Input**: 用户描述: "现在有一个问题就是平仓的时候 log输出如下 [日志显示Extended成交但Lighter无法平仓，导致套利对仍持仓的错误]，我希望Lighter也能正常平仓"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 修复强制平仓时两个交易所都无法正常平仓 (Priority: P1)

当系统触发强制平仓时（例如持仓时间超过最大限制），Extended交易所的平仓订单虽然实际成交但系统无法识别（因为CLOSE类型订单更新被忽略），导致Lighter交易所的平仓订单无法执行。整个平仓流程失败，套利对仍然处于持仓状态。系统需要能够正确识别Extended的成交状态，并成功执行Lighter的平仓订单，确保两个交易所的仓位都能被正常平仓。

**Why this priority**: 这是关键的安全问题。当强制平仓触发时，系统无法正确平仓导致风险敞口持续存在，可能导致用户资金损失。根本原因是CLOSE类型订单的WebSocket更新被忽略，导致Extended成交状态无法识别，进而导致Lighter平仓逻辑无法执行。

**Independent Test**: 可以通过触发强制平仓场景来独立测试：设置一个较短的最大持仓时间（如70秒），等待触发强制平仓，观察系统是否能够正确识别Extended的成交状态并成功执行Lighter平仓。

**Acceptance Scenarios**:

1. **Given** 套利对已持仓且超过最大持仓时间, **When** 触发强制平仓, **Then** Extended平仓订单成交后，系统应正确识别成交状态，并成功执行Lighter平仓订单
2. **Given** Extended平仓订单已成交且Lighter平仓订单成功执行, **When** 平仓流程完成, **Then** 套利对应从open_pairs列表中移除，并记录完整的平仓信息（两个交易所的成交价格和数量）
3. **Given** 平仓订单的WebSocket更新到达时current_order_id尚未设置, **When** 系统接收到订单更新, **Then** 系统应正确缓存CLOSE类型订单的更新，并在订单ID设置后应用该更新
4. **Given** 订单更新被正确处理, **When** wait_for_fill检查订单状态, **Then** 应正确返回FILLED状态和filled_quantity，而不是超时返回0
5. **Given** Extended平仓成功后, **When** 系统准备执行Lighter平仓, **Then** Lighter平仓订单应使用正确的对手价（bid/ask）并且成功成交

---

### User Story 2 - 确保Lighter平仓订单能够成功执行 (Priority: P1)

当Extended平仓订单成功成交后，系统必须能够成功执行Lighter的平仓订单，完成套利对的完整平仓流程。这要求Lighter平仓订单能够正确提交、成交，并且系统能够正确处理Lighter的订单状态更新。

**Why this priority**: 这是完整平仓流程的关键部分。如果只平仓Extended而不平仓Lighter，会留下Lighter的未对冲仓位，造成新的风险敞口。用户明确要求Lighter也能正常平仓，以确保套利对两个交易所的仓位都能被正确平仓。

**Independent Test**: 可以通过触发强制平仓场景来测试：观察Extended成交后，Lighter平仓订单是否能够成功提交并成交，验证完整的平仓流程。

**Acceptance Scenarios**:

1. **Given** Extended平仓订单已成功成交, **When** 系统准备执行Lighter平仓, **Then** Lighter平仓订单必须能够成功提交到交易所
2. **Given** Lighter平仓订单已提交, **When** 订单在交易所成交, **Then** 系统必须能够正确识别Lighter的成交状态（通过HTTP查询或WebSocket更新）
3. **Given** 两个交易所的平仓订单都已成交, **When** 平仓流程结束, **Then** 套利对应从open_pairs列表中移除，并记录完整的平仓信息（包括两个交易所的成交价格和数量）
4. **Given** Lighter平仓订单提交失败, **When** 系统检测到失败, **Then** 应记录详细的错误日志并重试（如果可重试），或触发紧急处理流程

---

### Edge Cases

- 当CLOSE订单的WebSocket更新在订单ID设置前到达时（竞态条件），系统应正确缓存并应用该更新
- 当Extended订单成交但filled_size字段为0或缺失时，系统应从filled_size字段解析正确的成交数量
- 当Lighter平仓失败时，系统应区分是网络问题、订单簿深度不足还是其他错误类型
- 当多个套利对同时触发强制平仓时，系统应能够独立处理每个套利对的平仓流程
- 当订单簿数据不足（如bids或asks为空）时，系统应提供清晰的错误信息
- 当Lighter平仓订单提交后长时间未成交时，系统应能够检测并处理超时情况
- 当Lighter交易所WebSocket连接断开时，系统应能够通过HTTP查询订单状态作为备用方案

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须正确处理CLOSE类型订单的WebSocket更新，不能因为order_type是CLOSE就忽略状态更新
- **FR-002**: 当订单更新在current_order_id设置前到达时，系统必须缓存CLOSE类型订单的更新，并在订单ID设置后应用
- **FR-003**: wait_for_fill方法必须能够正确检测到CLOSE订单的成交状态，返回正确的filled_quantity和filled_price
- **FR-004**: Extended平仓成功后，系统必须能够成功提交并执行Lighter的平仓订单
- **FR-005**: 系统必须能够正确识别Lighter平仓订单的成交状态（通过WebSocket或HTTP查询）
- **FR-006**: 当两个交易所的平仓订单都成功成交后，系统必须将套利对从持仓列表中移除
- **FR-007**: 系统必须记录详细的平仓日志，明确指出Extended和Lighter的平仓状态（成交价格、数量、订单ID）
- **FR-008**: 平仓失败后，系统必须重置套利对的is_closing标志，允许重试（如果适用）
- **FR-009**: 系统必须在日志中输出订单的实际成交数量（filled_size字段），而不是显示0
- **FR-010**: 当Lighter平仓订单超时未成交时，系统必须能够检测超时并执行适当的处理逻辑（取消订单、重试或记录失败）

### Key Entities

- **套利对（SpreadPair）**: 包含Extended和Lighter的仓位信息、开仓/平仓价格、订单ID、持仓状态等关键属性
- **平仓订单（CloseOrder）**: 包含订单ID、交易所（Extended/Lighter）、订单类型（OPEN/CLOSE）、成交状态、成交数量、成交价格等信息
- **订单状态更新（OrderUpdate）**: WebSocket推送的订单状态变化，包含order_id、status、filled_size、price、order_type等字段

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 强制平仓触发后，Extended平仓订单能够被正确识别为成交状态，成功率达到100%
- **SC-002**: Extended成交后，Lighter平仓订单能够成功提交并成交，成功率达到95%以上
- **SC-003**: 平仓流程中的订单更新能够被正确处理，wait_for_fill不再出现"已成交 0.0000"的错误日志
- **SC-004**: 当两个交易所的平仓订单都成功成交后，套利对能够被正确从持仓列表中移除
- **SC-005**: 平仓日志清晰显示Extended和Lighter的实际平仓状态（成交价格、数量、订单ID），便于人工审核和问题排查
- **SC-006**: 系统在收到CLOSE订单WebSocket更新后，能够在1秒内更新订单状态，避免wait_for_fill超时
- **SC-007**: Lighter平仓订单从提交到成交的平均时间不超过3秒（在正常市场条件下）

## Assumptions

- Extended交易所的WebSocket订单更新是可靠的，会推送所有订单（包括CLOSE类型）的状态变化
- 当前系统中CLOSE类型订单被忽略是历史遗留问题，原意可能是防止CLOSE订单影响开仓流程的状态管理
- Lighter交易所的平仓失败是由于Extended成交状态无法识别导致的，一旦修复CLOSE订单处理逻辑，Lighter应该能够正常平仓
- Lighter交易所API能够正常接受平仓订单并返回订单ID
- Lighter交易所的订单簿深度足够，能够支持强制平仓时的对手价成交
- 套利对需要两个交易所的仓位都被平仓才算完成平仓流程
- filled_size字段在订单更新消息中总是存在且为字符串格式，需要转换为Decimal类型
- 强制平仓使用对手价（bid/ask）模拟市价单，能够确保快速成交
