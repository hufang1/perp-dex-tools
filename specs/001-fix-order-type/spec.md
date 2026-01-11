# Feature Specification: 修复订单类型问题并增加交易成功率统计

**Feature Branch**: `001-fix-order-type`
**Created**: 2026-01-11
**Status**: Draft
**Input**: User description: "修复订单类型问题并增加交易成功率统计功能：1) 所有Extended和Lighter开仓订单统一使用taker订单；2) 修复开仓仓位数量不一致问题；3) 增加开仓/平仓成功率统计，包含失败原因记录，CSV输出双语列名"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 统一使用Taker订单进行开仓 (Priority: P1)

交易系统运行时，所有开仓订单必须使用taker订单类型（市价单），确保订单能够立即成交，避免maker订单挂单未成交导致的仓位失衡问题。

**Why this priority**: 这是核心问题修复。当前Extended交易所部分开仓订单使用maker类型导致挂单未成交，直接造成Lighter比Extended多0.01ETH的仓位失衡。此问题直接影响交易系统稳定性和对冲效果。

**Independent Test**: 可以独立测试开仓流程，监控订单类型是否正确设置为taker，并验证订单是否立即成交。

**Acceptance Scenarios**:

1. **Given** 系统检测到开仓机会，**When** 执行开仓操作，**Then** Extended和Lighter交易所都使用taker订单类型
2. **Given** Extended交易所使用taker订单开仓，**When** 订单提交，**Then** 订单立即成交，不会挂单等待
3. **Given** Lighter交易所使用taker订单开仓，**When** 订单提交，**Then** 订单立即成交，与Extended仓位数量一致

---

### User Story 2 - 修复开仓仓位数量不一致 (Priority: P1)

开仓操作完成后，Extended和Lighter两个交易所的仓位数量必须完全一致（例如Extended 0.01 ETH，Lighter -0.01 ETH），消除当前存在的0.01 ETH差异。

**Why this priority**: 仓位不一致直接导致对冲失效，造成单边风险敞口。这是P1优先级的核心安全修复，直接影响系统风险管理能力。

**Independent Test**: 可以独立验证开仓后两个交易所的仓位数量差异是否为零。

**Acceptance Scenarios**:

1. **Given** 系统执行开仓操作，**When** 两个交易所订单都成交，**Then** Extended和Lighter仓位数量差异为0
2. **Given** 仓位数量检测到差异，**When** 差异超过阈值，**Then** 系统触发仓位失衡警告并记录日志
3. **Given** 开仓订单数量为0.01 ETH，**When** Extended成交0.01 ETH，**Then** Lighter也必须成交0.01 ETH

---

### User Story 3 - 开仓/平仓成功率统计与失败原因追踪 (Priority: P2)

系统需要收集并统计开仓和平仓操作的成功率，作为衡量系统稳定性的核心指标。每次交易操作的结果（成功、失败、仓位上限等）都需要记录到CSV文件中，失败时必须记录具体失败原因。

**Why this priority**: 这是新增的可观测性功能。虽然不影响核心交易逻辑，但对于监控系统稳定性、发现系统瓶颈、优化交易策略至关重要。P2优先级确保在核心问题修复后实现。

**Independent Test**: 可以独立验证CSV文件是否正确记录了每次交易操作的结果和失败原因。

**Acceptance Scenarios**:

1. **Given** 系统识别到开仓机会并成功开仓，**When** 交易完成，**Then** CSV记录此操作为"成功"状态
2. **Given** 系统识别到开仓机会但已达仓位上限，**When** 检测到仓位限制，**Then** CSV记录此操作为"仓位上限"特殊标识
3. **Given** 开仓操作失败，**When** 捕获到失败原因，**Then** CSV记录失败原因（如"余额不足"、"订单拒绝"、"网络超时"等）
4. **Given** 平仓操作执行，**When** 交易完成或失败，**Then** CSV记录平仓成功状态或失败原因
5. **Given** CSV数据文件生成，**When** 查看列名，**Then** 所有列名都使用"英文名 | 中文名"双语格式
6. **Given** 系统运行一段时间，**When** 计算成功率统计，**Then** 可以汇总得到开仓成功率、平仓成功率、各失败原因占比

---

### Edge Cases

- 当Extended订单成交但Lighter订单失败时，系统如何处理未对冲仓位？
- 当订单类型设置为taker但交易所仍返回maker状态时，系统如何验证和重试？
- 当CSV文件写入失败时，系统如何保证统计数据不丢失？
- 当交易所API返回未知错误码时，如何记录失败原因？
- 当仓位检测发现不一致时，是否自动触发对冲修复还是仅记录警告？
- 当达到最大持仓数量限制时，新机会是否被跳过并记录？

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须强制所有Extended交易所开仓订单使用taker订单类型
- **FR-002**: 系统必须强制所有Lighter交易所开仓订单使用taker订单类型
- **FR-003**: 系统必须在开仓完成后验证Extended和Lighter仓位数量一致性
- **FR-004**: 系统必须记录每次开仓操作的结果状态（成功、失败、仓位上限）
- **FR-005**: 系统必须记录每次平仓操作的结果状态（成功、失败）
- **FR-006**: 系统必须记录每次失败操作的具体失败原因
- **FR-007**: 系统必须将所有交易操作结果导出到CSV文件
- **FR-008**: CSV文件所有列名必须使用"英文名 | 中文名"双语格式
- **FR-009**: 系统必须能够计算并展示开仓成功率指标
- **FR-010**: 系统必须能够计算并展示平仓成功率指标
- **FR-011**: 系统必须能够统计各失败原因的分布情况
- **FR-012**: 达到仓位上限时必须记录为特殊标识状态（非成功也非失败）

### Key Entities

- **交易操作记录 (Trade Operation Record)**: 记录每次开仓/平仓操作的完整信息，包括时间戳、操作类型、交易所、订单ID、结果状态、失败原因等
- **成功率统计 (Success Rate Statistics)**: 汇总计算开仓/平仓的成功率，按时间段、失败原因等维度分组统计
- **失败原因分类 (Failure Reason Category)**: 定义标准化的失败原因枚举，如余额不足、订单拒绝、网络超时、仓位上限、价格滑点过大等

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100%的开仓订单使用taker订单类型，无maker订单挂单未成交情况
- **SC-002**: 开仓后Extended和Lighter仓位数量差异为0，无仓位失衡情况
- **SC-003**: 所有交易操作结果100%记录到CSV文件，无遗漏
- **SC-004**: 所有失败操作100%记录具体失败原因，无"未知错误"记录
- **SC-005**: CSV文件所有列名100%使用双语格式（英文|中文）
- **SC-006**: 系统能够实时计算并展示开仓成功率和平仓成功率
- **SC-007**: 用户可以通过CSV数据分析出各失败原因的占比和趋势

## Assumptions

- Extended和Lighter交易所都支持taker订单类型
- 系统已有CSV数据导出功能，可以扩展新的字段
- 仓位数量差异检测功能已存在，可以增强验证逻辑
- 交易所API会返回明确的订单状态和失败原因

## Out of Scope

- 修改平仓订单类型（平仓逻辑不在本次修复范围）
- 自动修复仓位失衡的机制（本次仅记录和警告）
- 失败后自动重试机制（本次仅记录失败原因）
- 实时监控仪表板（本次仅CSV数据导出）
- 历史数据回填（本次仅记录新数据）
