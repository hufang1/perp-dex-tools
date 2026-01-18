# Specification Quality Checklist: Extended Maker模式降低手续费

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-01-18
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS_CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Validation Results

### Pass Summary

All validation items have passed the quality check. The specification:

1. **Content Quality**: All sections are complete and focused on business value rather than implementation
2. **Requirement Completeness**: All 23 functional requirements are testable, unambiguous, and have clear acceptance criteria
3. **Success Criteria**: All 13 success criteria are measurable and technology-agnostic
4. **Edge Cases**: 10 major edge cases have been identified with detailed handling approaches (including user decisions marked)
5. **User Stories**: 3 prioritized user stories (P1, P2, P3) with comprehensive acceptance scenarios (18 scenarios for P1)
6. **State Machine Design**: Complete state transition flows documented with ASCII diagrams and detailed failure handling
7. **Monitoring & Logging**: Comprehensive logging requirements documented with Chinese state names and detailed format specifications

### Key Strengths

- Clear priority structure (P1: Maker mode with complete state machine, P2: Fixed thresholds, P3: Price monitoring + Spread protection)
- **Complete state machine redesign**: Documents new states (OPENING_MAKER_WAIT, CLOSING_MAKER_WAIT, LIGHTER_HEDGING) with detailed transition flows
- Comprehensive edge case analysis with suggested solutions for each new state
- Well-defined acceptance scenarios for each user story (15 scenarios for P1 covering both opening and closing flows)
- Specific, measurable success criteria (e.g., "50% cost reduction", "80% fill rate", "100ms state transition delay")
- Strong context section linking to existing system documentation
- Reference to existing implementation (hedge_mode_ext.py) for guidance
- **Enhanced User Story 3** with real-time spread monitoring and automatic cancellation when spread < 0.09%
- **New entity definitions**: MakerWaitState and HedgingState to support the new states
- **Comprehensive logging requirements**: Complete log format specifications with Chinese state names for all new states, including real-time monitoring logs for MAKER_WAIT states and detailed execution logs for LIGHTER_HEDGING state

### State Machine Highlights

**Key Design Changes**:
- Taker mode: Parallel execution (Extended + Lighter simultaneously)
- Maker mode: Serial execution (Extended first, then Lighter hedging)

**New States**:
1. OPENING_MAKER_WAIT: Monitors spread protection, price optimization, and order fill status
2. CLOSING_MAKER_WAIT: Similar monitoring for closing orders
3. LIGHTER_HEDGING: Executes Lighter hedge orders after Extended fills

**Critical State Transitions**:
- IDLE → OPENING → OPENING_MAKER_WAIT → LIGHTER_HEDGING → OPENING_WAIT → HOLDING
- HOLDING → CLOSING → CLOSING_MAKER_WAIT → LIGHTER_HEDGING → CLOSING_WAIT → IDLE

**Protection Mechanisms**:
- Spread protection: Cancel orders when spread < 0.09% (opening) or condition no longer favorable (closing)
- Price optimization: Cancel and replace orders when not at optimal price position
- Partial fill handling: Hedge filled portion, continue waiting for remainder

### Notes

- The specification is ready to proceed to `/speckit.plan` for implementation planning
- All 18 functional requirements are clear and actionable:
  - FR-001 to FR-010: Core requirements for Maker mode and fixed threshold strategy
  - FR-011 to FR-015: New state requirements (OPENING_MAKER_WAIT, CLOSING_MAKER_WAIT, LIGHTER_HEDGING)
  - FR-016: Continuous reposition limit requirement
  - FR-017: Lighter hedge failure handling (only force close new positions)
  - FR-018: OPENING_WAIT verification failure rollback logic
- User has made specific decisions on edge cases (marked with "我的结论：B" and detailed rollback logic)
- Assumptions are documented, particularly around Extended's maker fee structure and order fill behavior
- Edge case recommendations are provided for all 10 identified edge cases with user decisions incorporated
- **Spread protection mechanism**: Real-time monitoring every 0.5 seconds (configurable) to cancel orders when spread < 0.09%
- **Enhanced priority**: User Story 3 is now marked as core risk control feature, equally important as P1 once implemented
- **Performance requirements**: Added success criteria for state transition latency (SC-008), monitoring loop processing time (SC-009), and logging latency (SC-011, SC-012)
- **Logging requirements**: FR-019 to FR-023 define comprehensive logging requirements with Chinese state names, including:
  - State name mapping for new states (OPENING_MAKER_WAIT, CLOSING_MAKER_WAIT, LIGHTER_HEDGING)
  - Unified state transition log format with emoji 💥
  - Detailed monitoring logs for MAKER_WAIT states (spread, price, order status, partial fills, reposition limits)
  - Detailed execution logs for LIGHTER_HEDGING state (order sending, progress, success/failure, partial fills)
  - Log formatting requirements: Chinese display, percentage for spreads, 3 decimal places for quantities

### User Decisions on Edge Cases

The following decisions have been made by the user (marked in spec.md):

1. **Extended挂单超时未成交**: 选项B - 继续等待直到成交或价格不满足条件（Maker模式不急于成交）
2. **Extended部分成交**: 对冲已成交部分，回到OPENING_MAKER_WAIT继续等待剩余部分成交（明确"继续开0.007ETH"）
3. **Lighter对冲失败**: 只强制平仓本次新开仓的Extended仓位，原先已经存在的仓位不动（重要：保护原有持仓）
4. **OPENING_WAIT验证失败**: 判断两边仓位谁大（代表另一边没开仓成功），回退仓位大的那一边的本次开单仓位，根据平仓后两边仓位是否都>0判断回到HOLDING还是IDLE

These decisions are critical for the implementation and must be strictly followed during development.
- **Key design decisions**:
  - Extended挂单超时：继续等待（选项B）
  - 部分成交处理：对冲已成交部分，回到MAKER_WAIT继续等待剩余部分
  - Lighter对冲失败：只平本次开仓的仓位，保留原有持仓
  - OPENING_WAIT验证失败：识别较大仓位并回滚本次开仓数量，根据结果决定IDLE或HOLDING
  - MAKER_WAIT循环重挂：限制最多10次，超过后取消并回到前序状态
