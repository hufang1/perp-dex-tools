# Feature Specification: 修复套利机器人订单状态更新的竞态条件bug

**Feature Branch**: `003-fix-order-status-race`
**Created**: 2026-01-07
**Status**: Draft
**Input**: 用户描述: "现在程序可以正常运行了 但是lighter没有同步开单。Extended订单成交后，订单状态更新通过WebSocket回调到达，但是current_order_id在下单函数返回后才被设置，导致WebSocket回调中的订单更新被忽略。这是一个race condition问题。订单更新消息在下单函数返回前就到达了，此时current_order_id还是None，导致update_order_status函数中的order_id != current_order_id检查失败，订单状态没有被更新，最终wait_for_fill超时。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 确保套利对完整执行，避免未对冲的单边持仓风险 (Priority: P1)

当用户运行spread_arb策略时，如果Extended订单成交，程序必须能够及时识别订单成交状态并在Lighter执行对冲订单，不能因为订单状态更新的竞态条件而忽略成交通知，导致单边持仓风险。

**Why this priority**: 这是最高优先级，因为当前bug导致Extended订单成交后Lighter没有同步开单，用户面临单边持仓的市场风险，可能导致严重损失。

**Independent Test**: 可以通过模拟快速成交场景进行测试 - 在Extended下单后立即通过WebSocket发送FILLED状态更新（在下单函数返回前），程序应该能够正确接收并处理这个更新，不忽略订单成交状态。

**Acceptance Scenarios**:

1. **Given** Extended下单请求已发送但订单ID还未返回给order_manager，**When** WebSocket回调收到该订单的FILLED状态更新，**Then** 程序应该缓存这个更新并在订单ID设置后应用它，确保filled_quantity和filled_price被正确更新
2. **Given** 订单在下单后1秒内快速成交，**When** wait_for_fill函数等待订单成交，**Then** 函数应该在2秒内检测到FILLED状态并返回，不触发超时
3. **Given** 订单成交后订单状态更新被正确处理，**When** execute_hedge被调用，**Then** Lighter应该成功下对冲单，日志显示"✅ 开仓成功"而不是"❌ 对冲失败"

---

### User Story 2 - 处理并发的订单状态更新消息 (Priority: P2)

当Extended WebSocket快速发送多个订单状态更新时（例如PARTIALLY_FILLED followed by FILLED），程序应该能够按顺序处理这些更新，不会因为时序问题而丢失任何状态更新。

**Why this priority**: 这是中等优先级，虽然不影响核心功能，但确保程序在高频交易场景下的稳定性，避免部分成交场景下的状态不一致。

**Independent Test**: 可以通过模拟并发WebSocket消息进行测试 - 在短时间内发送多个订单状态更新（PARTIALLY_FILLED -> FILLED），程序应该能够正确追踪所有中间状态，最终filled_quantity反映完全成交的数量。

**Acceptance Scenarios**:

1. **Given** Extended订单部分成交后完全成交，**When** WebSocket收到PARTIALLY_FILLED然后FILLED状态更新，**Then** filled_quantity应该从部分数量更新到完全成交数量
2. **Given** 多个订单同时存在，**When** WebSocket回调收到不同订单的更新，**Then** 每个订单的状态应该被独立正确跟踪，不相互干扰

---

### User Story 3 - 提供订单状态更新的可观测性 (Priority: P3)

用户应该能够通过日志清楚地了解订单状态更新的时序和处理情况，包括何时收到WebSocket回调、何时更新order_manager状态、是否检测到竞态条件等。

**Why this priority**: 这是较低优先级，但良好的可观测性对于调试和验证竞态条件修复非常重要，可以帮助用户确认问题已解决。

**Independent Test**: 可以通过查看日志输出进行验证 - 当订单状态更新到达时，日志应该显示时间戳、订单ID、当前状态、是否被处理等详细信息。

**Acceptance Scenarios**:

1. **Given** WebSocket回调收到订单状态更新，**When** update_order_status函数处理这个更新，**Then** 日志应该显示订单ID、当前current_order_id、是否匹配、是否被处理
2. **Given** 检测到订单更新早于current_order_id设置的情况，**When** 缓存机制被触发，**Then** 日志应该明确显示"缓存订单更新，等待订单ID设置"
3. **Given** 订单ID设置后应用缓存的更新，**When** 延迟更新被处理，**Then** 日志应该显示"应用缓存的订单更新"

---

### Edge Cases

- 订单更新在下单前到达（订单ID尚未分配）
- 同一订单的多个状态更新同时到达（乱序）
- 订单被取消后收到FILLED更新（不一致状态）
- 订单ID类型不匹配（字符串 vs 数字）
- WebSocket连接断开时订单成交，重连后收到状态更新

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须在收到订单状态更新时检查current_order_id是否已设置，如果未设置则缓存该更新
- **FR-002**: 系统必须在设置current_order_id后立即检查是否有该订单的缓存更新，如有则应用
- **FR-003**: 系统必须支持缓存多个订单的状态更新，使用订单ID作为key
- **FR-004**: 系统必须在wait_for_fill函数中检查缓存的订单更新，不依赖实时WebSocket回调
- **FR-005**: 系统必须在日志中记录订单状态更新的时序信息（接收时间、订单ID、处理状态）
- **FR-006**: 系统必须防止缓存的订单更新无限累积（例如设置最大缓存数量或TTL）
- **FR-007**: 系统必须在应用缓存更新时验证订单ID匹配，防止应用错误的更新
- **FR-008**: 系统必须在订单完成（FILLED/CANCELLED）后清理该订单的缓存更新
- **FR-009**: 系统必须处理并发场景下的订单状态更新，避免数据竞争
- **FR-010**: 系统必须在detect到竞态条件时在日志中明确标记，便于问题诊断

### Key Entities

- **订单状态缓存**: 存储提前到达的订单状态更新，key为订单ID，value为订单数据和时间戳
- **订单更新时序记录**: 记录每个订单状态更新的接收时间和处理时间
- **竞态条件检测标志**: 标记是否检测到订单更新早于订单ID设置的情况
- **current_order_id锁**: 保护current_order_id和缓存更新的并发访问

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 程序在快速成交场景下（下单后1秒内成交）能够正确识别订单成交，Lighter对冲成功率100%
- **SC-002**: wait_for_fill函数在订单成交后2秒内返回FILLED状态，不触发超时
- **SC-003**: 日志中包含足够的时序信息来验证竞态条件是否被正确处理
- **SC-004**: 在连续运行24小时后，缓存中未处理的订单更新数量为0（无内存泄漏）
- **SC-005**: 当Extended订单成交后，Lighter对冲订单在5秒内成功下单，对冲延迟不超过5秒

## Assumptions

- Extended WebSocket可能会在下单函数返回前发送订单状态更新
- current_order_id在place_spread_maker_order函数返回前被设置
- 订单更新到达的顺序可能与订单状态变更的顺序不一致
- 用户希望通过日志验证竞态条件已被修复，而不仅仅是功能正常
- 缓存机制不会显著增加内存使用（假设同时存在的订单数量有限）
