# Specification Quality Checklist: 价差套利平仓逻辑修复与磨损优化

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-01-10
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

## Validation Results

### ✅ All Checklist Items Passed

### Summary of Changes

The specification has been significantly enhanced with:

1. **Detailed Problem Analysis** (新增):
   - 现有平仓逻辑总结（三种方式）
   - 从交易日志分析的具体问题（两个案例）
   - 核心问题总结表（5个主要问题类别）

2. **Proposed Solutions** (新增):
   - 方案1: 修复价差计算和开仓逻辑
   - 方案2: 修复平仓价格选择
   - 方案3: 增加价差收敛检查
   - 方案4: 增强诊断日志

3. **Enhanced User Stories**:
   - User Story 1: 修复价差方向计算逻辑 (P1)
   - User Story 2: 修复平仓价格选择逻辑 (P1)
   - User Story 3: 增加价差收敛检查 (P2)
   - User Story 4: 增强诊断日志 (P3)

4. **Detailed Functional Requirements** (18条):
   - 价差计算修复 (FR-001 to FR-004)
   - 平仓逻辑修复 (FR-005 to FR-008)
   - 平仓触发条件优化 (FR-009 to FR-010)
   - 诊断日志增强 (FR-011 to FR-014)
   - 仓位平衡保护 (FR-015 to FR-018)

## Key Findings from Code Analysis

### Current Closing Logic Issues

| 问题 | 位置 | 影响 |
|------|------|------|
| `_close_pair`使用opportunity价格 | bot.py:647 | 平仓价格与市价脱节 |
| 缺乏价差收敛检查 | bot.py:1079-1158 | 在价差扩大时平仓亏损 |
| 依赖反向机会触发平仓 | bot.py:408-413 | 持仓累积无法平仓 |
| 强制平仓时间过短 | config.py:28 | 70秒在不利时机平仓 |

### Example Loss Trade from Log

```
开仓: Extended $3094.50 / Lighter $3065.96 (价差 -$28.54)
平仓: Extended $3092.70 / Lighter $3127.21 (价差 +$34.51)
结果: 亏损 -$0.63 (-2.04%)
原因: 价差扩大而非收敛
```

## Specification Status

✅ **READY FOR PLANNING** - 规格说明已完成并验证通过

### Next Steps

可运行以下命令继续：
- `/speckit.plan` - 创建实现计划
- `/speckit.tasks` - 生成任务列表
- `/speckit.implement` - 开始实现
