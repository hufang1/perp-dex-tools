# Feature Specification: 开仓等待确认流程修复

**Feature Branch**: `001-open-position-wait`
**Created**: 2026-01-14
**Status**: Draft
**Input**: User description: "修复开仓等待确认流程：检查价差机会后开仓，等待xs秒确认仓位对等，超时或不对等则强平所有仓位"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 开仓等待确认机制 (Priority: P1)

用户期望机器人在检测到价差机会后开仓，然后等待一段时间（可配置）确认两个交易所的仓位是否都对等且正确。如果超时或仓位不对等，则强平所有仓位并进入冷却期。

**Why this priority**: 这是核心风控机制，防止仓位不对等导致的资金损失

**Independent Test**: 可以通过模拟开仓场景，检查等待确认、仓位检查、强平和冷却期逻辑

**Acceptance Scenarios**:

1. **Given** 机器人处于IDLE状态，**When** 检测到价差机会并开仓成功，**Then** 进入OPENING_WAIT状态开始等待确认
2. **Given** 处于OPENING_WAIT状态，**When** 两个交易所仓位都正确对等，**Then** 转入HOLDING状态
3. **Given** 处于OPENING_WAIT状态，**When** 超过等待时间（配置项xs秒）仓位仍不对等，**Then** 强平所有仓位并进入冷却期
4. **Given** 处于OPENING_WAIT状态，**When** 等待2秒后检测到仓位不对等，**Then** 立即强平所有仓位并进入冷却期

---

### User Story 2 - 强平后冷却期 (Priority: P1)

强平后必须进入冷却期，防止立即重新开仓导致频繁交易和资金损失。

**Why this priority**: 防止在市场不稳定时频繁开仓平仓

**Independent Test**: 检查强平后的冷却期逻辑和IDLE状态的冷却检查

**Acceptance Scenarios**:

1. **Given** 执行了强平操作，**When** 强平完成，**Then** 记录失败时间并进入冷却期
2. **Given** 处于冷却期中，**When** 检测到新的价差机会，**Then** 跳过开仓直到冷却期结束

---

### User Story 3 - 启动时仓位检查 (Priority: P2)

程序启动时检查是否有残留仓位，如果有则清理。

**Why this priority**: 防止残留仓位影响新的交易

**Independent Test**: 模拟有残留仓位启动程序，验证清理逻辑

**Acceptance Scenarios**:

1. **Given** 程序启动，**When** 检测到有残留仓位但状态文件显示无持仓，**Then** 执行强平清理残留仓位
2. **Given** 程序启动，**When** 无残留仓位，**Then** 正常启动

---

### User Story 4 - 强平重试机制 (Priority: P2)

强平失败时自动重试，确保两边仓位都被平掉。

**Why this priority**: 确保风险控制，避免单边持仓

**Independent Test**: 模拟强平失败场景，验证重试逻辑

**Acceptance Scenarios**:

1. **Given** 执行强平，**When** 强平订单未成交，**Then** 最多重试3次
2. **Given** 强平重试3次后仍有仓位，**Then** 记录错误日志并警告

---

### Edge Cases

- 开仓订单部分成交的情况
- 强平订单超时未成交的情况
- 网络延迟导致仓位查询不准确的情况
- 程序异常退出后重启的情况
- 两个交易所同时有仓位但数量不对等的情况

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须在开仓后进入OPENING_WAIT状态，等待配置的时间（xs秒）确认仓位
- **FR-002**: 系统必须在等待期间定期检查两个交易所的仓位是否都对等于目标数量
- **FR-003**: 系统必须在仓位确认成功后转入HOLDING状态
- **FR-004**: 系统必须在等待超时后强平所有仓位
- **FR-005**: 系统必须在检测到仓位不对等（等待2秒后）立即强平所有仓位
- **FR-006**: 系统必须在强平后进入冷却期（默认5秒），冷却期内不允许开仓
- **FR-007**: 系统必须在强平时同时处理两个交易所的仓位
- **FR-008**: 系统必须实现强平重试机制（最多3次）
- **FR-009**: 系统必须在启动时检查并清理残留仓位
- **FR-010**: 系统必须验证强平订单的实际成交情况

### Key Entities

- **BotState**: 机器人状态（IDLE, OPENING, OPENING_WAIT, HOLDING, CLOSING, ERROR）
- **Position**: 持仓信息（数量、价格、时间）
- **Config**: 配置参数（目标数量、等待超时、冷却期）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 仓位不对等的情况在2秒内被检测到并触发强平
- **SC-002**: 强平操作成功清理两个交易所的所有仓位（误差<0.001 ETH）
- **SC-003**: 冷却期内不会执行新的开仓操作
- **SC-004**: 程序启动时残留仓位被成功清理

## Assumptions

1. 两个交易所的仓位查询API返回实时准确的仓位数据
2. 强平订单使用taker模式确保即时成交
3. 网络延迟在可接受范围内（<500ms）
4. 配置的等待时间（xs秒）默认为10秒，可通过命令行参数调整
5. 配置的冷却期默认为5秒，可通过代码调整

## Dependencies

- 两个交易所的API连接正常
- 仓位查询功能正常工作
- 订单执行功能正常工作
