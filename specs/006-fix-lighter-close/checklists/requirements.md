# Specification Quality Checklist: 修复强制平仓时Extended和Lighter都无法正常平仓的问题

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-01-09
**Updated**: 2026-01-09 (更新：增加了Lighter正常平仓的需求)
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
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

## Notes

### 验证结果摘要

所有检查项均已通过：

1. **内容质量**: 规格说明专注于业务需求（修复平仓失败问题，确保两个交易所都能正常平仓），没有包含具体实现细节如编程语言或API设计

2. **需求完整性**: 所有10个功能需求（FR-001至FR-010）都是可测试的，没有需要澄清的标记

3. **成功标准**: 7个成功标准（SC-001至SC-007）都是可量化的，包括：
   - Extended成交识别率100%
   - Lighter平仓成功率95%以上
   - 不再出现"已成交 0.0000"错误日志
   - 两个交易所都成功后移除套利对
   - Lighter平仓平均时间不超过3秒

4. **用户场景**: 两个优先级用户故事（都是P1）覆盖了完整场景：
   - User Story 1: 修复CLOSE订单处理逻辑，确保Extended成交能被识别
   - User Story 2: 确保Lighter平仓订单能够成功提交并成交

5. **边界情况**: 识别了7个关键边界情况，包括竞态条件、多套利对同时平仓、Lighter超时、WebSocket断线等

6. **假设**: 明确列出了8个假设，包括WebSocket可靠性、Lighter API可用性、订单簿深度等

### 问题根本原因分析

基于用户提供的日志和代码分析，问题的完整原因是：

1. **根本原因**: `order_manager.py` 第245-247行忽略了CLOSE类型订单的WebSocket更新
   ```python
   if order_type == 'CLOSE':
       # 关闭订单不更新maker_order的状态
       return
   ```

2. **导致的问题链条**:
   - Extended平仓订单实际已成交（日志显示 `status=FILLED`）
   - 但 `wait_for_fill` 无法获取成交信息，因为CLOSE订单更新被忽略
   - 超时后返回 `filled_quantity=0`，显示"已成交 0.0000"
   - 平仓流程被判定为失败，Lighter平仓逻辑未执行
   - 套利对仍留在 `open_pairs` 列表中，继续触发强制平仓

3. **用户期望的完整流程**:
   - Extended平仓订单成交（能够被正确识别）
   - Lighter平仓订单成功提交并成交
   - 两个交易所都成功后，套利对从持仓列表移除

### 更新说明

根据用户的补充需求"我希望Lighter也能正常的平仓"，规格说明书已更新：
- 将User Story 2从"改进平仓失败处理机制（P2）"改为"确保Lighter平仓订单能够成功执行（P1）"
- 增加了关于Lighter平仓的功能需求（FR-004至FR-005、FR-010）
- 增加了Lighter平仓相关的成功标准（SC-002、SC-007）
- 增加了关于Lighter平仓的边界情况
- 更新了假设部分，明确Lighter应该能够正常平仓的前提条件

### 准备就绪

规格说明已完成并更新，包含用户对Lighter正常平仓的完整需求，可以进入下一阶段：
- 使用 `/speckit.clarify` 进行进一步澄清（当前无需澄清，所有需求已明确）
- 使用 `/speckit.plan` 开始实施计划
