# Feature Specification: 修复Lighter WebSocket连接失败和订单簿为None的bug

**Feature Branch**: `002-fix-lighter-ws`
**Created**: 2026-01-07
**Status**: Draft
**Input**: 用户描述: "修复Lighter WebSocket连接失败和订单簿为None的bug"

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - 防止程序因订单簿数据缺失而崩溃 (Priority: P1)

当用户运行hedge_mode或spread_arb策略时，如果Lighter WebSocket连接失败或订单簿数据未加载完成，程序应该优雅地处理这种情况，而不是崩溃。程序应该能够检测到订单簿数据不可用，并且不尝试在Lighter上执行对冲订单，或者等待订单簿数据就绪后再执行。

**Why this priority**: 这是最高优先级，因为当前程序会在Lighter连接失败时崩溃（TypeError: 'NoneType' object is not subscriptable），导致整个交易策略中断，用户可能因此单边持仓而遭受损失。

**Independent Test**: 可以通过模拟Lighter WebSocket连接失败的场景进行测试 - 程序应该能够检测到订单簿为空的情况并优雅地处理，而不是抛出异常崩溃。

**Acceptance Scenarios**:

1. **Given** Lighter WebSocket连接失败（HTTP 400或429），**When** 程序尝试获取best_bid或best_ask价格，**Then** 程序应该检测到订单簿为None并跳过Lighter对冲订单，记录警告日志，不崩溃
2. **Given** Lighter订单簿未加载完成（snapshot_loaded=False），**When** Extended订单成交并需要在Lighter对冲，**Then** 程序应该等待订单簿数据就绪（最多等待一定时间），超时后取消Extended订单或使用REST API获取价格
3. **Given** best_bid或best_ask为None，**When** place_lighter_market_order函数尝试计算价格，**Then** 函数应该提前返回或抛出有意义的异常，不尝试访问None[0]

---

### User Story 2 - 处理Lighter速率限制错误 (Priority: P2)

当Lighter服务器返回HTTP 429（Too Many Requests）或HTTP 400错误时，程序应该能够识别这些错误并使用适当的退避策略重新连接，而不是无限快速重试导致进一步触发速率限制。

**Why this priority**: 这是中等优先级，虽然不影响程序的核心功能，但适当的错误处理可以提高程序的稳定性和用户体验，避免过度请求导致账户被临时封禁。

**Independent Test**: 可以通过模拟Lighter返回HTTP 429/400错误进行测试 - 程序应该能够识别这些错误并使用指数退避策略重新连接，而不是立即重试。

**Acceptance Scenarios**:

1. **Given** Lighter WebSocket连接返回HTTP 429错误，**When** 程序检测到这个错误，**Then** 程序应该等待至少60秒后再重试连接
2. **Given** Lighter WebSocket连接返回HTTP 400错误，**When** 程序检测到这个错误，**Then** 程序应该等待至少30秒后再重试连接
3. **Given** 连续多次连接失败，**When** 程序进行重试，**Then** 等待时间应该按照指数退避策略增加（1秒 -> 2秒 -> 4秒...最多30秒）

---

### User Story 3 - 提供Lighter连接状态的可观测性 (Priority: P3)

用户应该能够清楚地知道Lighter WebSocket的连接状态和订单簿数据状态，以便在出现问题时快速诊断。程序应该提供清晰的日志输出，显示连接是否成功、订单簿是否加载、当前的重连状态等。

**Why this priority**: 这是较低优先级，因为虽然它不影响功能，但良好的可观测性可以帮助用户快速定位问题，减少调试时间。

**Independent Test**: 可以通过查看日志输出进行验证 - 当Lighter连接成功、失败、重连时，日志应该包含清晰的状态信息。

**Acceptance Scenarios**:

1. **Given** 程序启动并尝试连接Lighter WebSocket，**When** 连接成功或失败，**Then** 日志应该显示清晰的连接状态消息
2. **Given** 订单簿数据加载完成，**When** snapshot_loaded变为True，**Then** 日志应该显示订单簿就绪和买卖价数量
3. **Given** 连接失败并触发重连，**When** 程序进入等待状态，**Then** 日志应该显示等待时间信息

---

### Edge Cases

- Lighter WebSocket连接成功但订单簿数据为空（bids和asks都为空）
- Lighter WebSocket连接在程序运行过程中意外断开
- 程序启动时Lighter服务器暂时不可用
- 订单簿数据部分加载（有bids但没有asks，或反之）
- 多个程序实例同时连接Lighter导致速率限制
- 网络不稳定导致连接频繁断开重连

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须在尝试访问Lighter订单簿数据（best_bid, best_ask）之前检查数据是否为None
- **FR-002**: 当Lighter订单簿数据为None时，系统必须禁止在Lighter上执行任何交易操作
- **FR-003**: 系统必须能够识别HTTP 429（Too Many Requests）错误并应用至少60秒的退避时间
- **FR-004**: 系统必须能够识别HTTP 400（Bad Request）错误并应用至少30秒的退避时间
- **FR-005**: 系统在连接失败时必须使用指数退避策略（1秒 -> 2秒 -> 4秒...最多30秒）
- **FR-006**: 系统必须在日志中清晰显示Lighter WebSocket连接状态（连接中、成功、失败、等待重连）
- **FR-007**: 系统必须在日志中显示订单簿数据状态（未加载、加载中、已就绪、数据为空）
- **FR-008**: 当Extended订单成交但Lighter不可用时，系统必须记录警告并不尝试Lighter对冲
- **FR-009**: 系统必须能够检测订单簿是否真正可用（bids和asks都有数据），而不仅仅是检查None
- **FR-010**: 在place_lighter_market_order函数中，系统必须在访问best_bid[0]或best_ask[0]之前验证这些值不为None

### Key Entities *(include if feature involves data)*

- **Lighter WebSocket连接状态**: 包括连接URL、market_index、account_index、当前连接状态、重连次数、等待时间
- **Lighter订单簿数据**: 包括bids字典、asks字典、best_bid价格、best_ask价格、snapshot_loaded标志、order_book_offset
- **连接错误信息**: 包括错误类型（HTTP 400/429）、错误消息、错误时间戳、重连计划

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 程序在Lighter WebSocket连接失败时继续运行不崩溃，持续运行时间超过24小时
- **SC-002**: 程序在Lighter订单簿为None时正确跳过Lighter对冲，不产生TypeError异常
- **SC-003**: 程序在遇到HTTP 429错误后使用正确的退避时间（>=60秒），不在10秒内产生超过3次连接尝试
- **SC-004**: 日志中包含足够的信息来诊断Lighter连接问题，包括连接状态、订单簿状态、错误类型和重连计划
- **SC-005**: Extended订单成交后，如果Lighter不可用，程序在5秒内决定是否取消Extended订单或等待，不会无限期挂起

## Assumptions

- Lighter服务器的速率限制是基于IP地址和账户的
- HTTP 400错误可能是由于协议不匹配或服务器临时问题导致的
- 订单簿数据为None或空是WebSocket连接失败的直接结果
- 用户希望程序在Lighter不可用时继续运行，而不是完全停止
- 用户希望通过日志了解Lighter连接问题的详细信息，而不是仅通过异常堆栈
