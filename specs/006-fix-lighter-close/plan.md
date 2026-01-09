# Implementation Plan: 修复强制平仓时Extended和Lighter都无法正常平仓的问题

**Branch**: `006-fix-lighter-close` | **Date**: 2026-01-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-fix-lighter-close/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

修复强制平仓失败问题：当前系统中CLOSE类型订单的WebSocket更新被忽略，导致Extended交易所成交状态无法被识别（`wait_for_fill`返回filled_quantity=0），进而导致Lighter平仓逻辑无法执行。

**主要需求**：
- FR-001: 正确处理CLOSE类型订单的WebSocket更新
- FR-002: 缓存机制处理竞态条件（订单更新在订单ID设置前到达）
- FR-003: `wait_for_fill`正确检测CLOSE订单成交状态
- FR-004至FR-010: 确保Lighter平仓订单能够成功提交、成交并被正确识别

**技术方法**：
- 修改`order_manager.py`中的`update_order_status`方法，移除CLOSE订单的忽略逻辑
- 扩展现有的缓存机制，支持CLOSE订单更新的缓存
- 确保Lighter平仓流程能够正常执行（修复CLOSE订单识别后应该自动恢复）

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
- `websockets>=12.0`: WebSocket客户端库（用于Extended和Lighter订单更新）
- `asyncio`: 异步编程框架
- `decimal.Decimal`: 精确的金融数值计算
- `lighter-sdk==0.1.4`: Lighter交易所SDK
- `x10-python-trading-starknet==0.0.10`: Extended交易所SDK
- `edgex-python-sdk`: Extended官方Python SDK（fork版本，支持post_only限价单）

**Storage**: 内存状态存储（无数据库）
- 套利对状态保存在`SpreadPair`对象中
- 订单状态保存在`SpreadOrderManager`的实例变量中
- 日志写入文件（`logs/trade.log`）

**Testing**: pytest (单元测试和集成测试)
- 单元测试：`tests/test_order_manager.py`
- 集成测试：`tests/integration/`

**Target Platform**: Linux服务器（运行套利机器人）

**Project Type**: 单一Python项目（异步事件驱动系统）

**Performance Goals**:
- WebSocket订单更新处理延迟 < 100ms（SC-006: 1秒内更新状态）
- `wait_for_fill`超时检测准确率 100%（SC-001: Extended成交识别率100%）
- Lighter平仓订单平均成交时间 < 3秒（SC-007）

**Constraints**:
- 金融级精度要求：所有价格和数量必须使用Decimal类型
- 不抛出异常：错误通过返回值传递
- 异步I/O：所有网络操作使用async/await
- 日志级别：debug详细信息，info关键事件

**Scale/Scope**:
- 最多同时维护`max_open_pairs`个套利对（默认3个）
- 单个套利对持仓时间最长30分钟（1800秒）
- 强制平仓触发时间：70秒（测试配置）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

基于项目CLAUDE.md中定义的开发标准：

### ✅ 代码风格检查

- [x] **异步函数**: 所有I/O操作使用async/await → 本功能涉及的订单更新处理是异步的
- [x] **日志**: 使用logging模块，debug级别记录详细信息，info级别记录关键事件 → 将添加详细的平仓流程日志
- [x] **数值计算**: 使用Decimal进行所有金融计算 → filled_size和price处理使用Decimal
- [x] **错误处理**: 不抛出异常，通过返回值传递错误信息 → 保持现有模式

### ✅ 架构一致性检查

- [x] **模块职责**: 修改在`order_manager.py`中，符合订单管理器职责
- [x] **状态管理**: 状态保存在内存中，不引入新依赖
- [x] **测试策略**: 添加单元测试验证CLOSE订单处理逻辑

### ⚠️ 潜在复杂度增加

- **风险**: 移除CLOSE订单忽略逻辑可能影响开仓流程的状态管理
- **缓解措施**: 原代码注释说明"防止CLOSE订单影响开仓流程"，需要验证是否需要隔离OPEN和CLOSE订单的状态管理
- **研究任务**: Phase 0需要研究现有缓存机制是否需要扩展以支持CLOSE订单

### ✅ 测试覆盖要求

- 单元测试：验证`update_order_status`正确处理CLOSE订单
- 集成测试：验证完整的平仓流程（Extended成交 → Lighter平仓）
- 边界测试：竞态条件（订单更新在订单ID设置前到达）

**结论**: ✅ 通过宪法检查，可以进入Phase 0研究

## Project Structure

### Documentation (this feature)

```text
specs/006-fix-lighter-close/
├── spec.md              # 功能规格说明（已完成）
├── plan.md              # 本文件 - 实施计划
├── research.md          # Phase 0输出 - 技术研究
├── data-model.md        # Phase 1输出 - 数据模型
├── quickstart.md        # Phase 1输出 - 快速开始指南
├── contracts/           # Phase 1输出 - API合约（如适用）
│   └── order_update_contract.md  # 订单更新处理合约
└── checklists/
    └── requirements.md  # 质量检查清单（已完成）
```

### Source Code (repository root)

```text
spread/                          # 价差套利模块
├── order_manager.py            # [修改] 订单管理器 - 修复CLOSE订单处理
├── hedge_manager.py            # [验证] 对冲管理器 - 确保Lighter平仓正常
├── bot.py                      # [验证] 套利机器人主逻辑 - 平仓流程
└── spread_pair.py              # [验证] 套利对数据模型

tests/                          # 测试文件
├── test_order_manager.py       # [扩展] 添加CLOSE订单处理测试
├── test_close_order_flow.py    # [新增] 平仓流程集成测试
└── integration/
    └── test_force_close.py     # [新增] 强制平仓集成测试
```

**Structure Decision**: 单一Python项目结构，修改集中在`spread/order_manager.py`，添加相关测试验证修复效果。

---

## Phase 0: Research & Technical Decisions

### Research Tasks

基于Technical Context中的NEEDS CLARIFICATION和潜在复杂度，需要研究以下问题：

1. **CLOSE订单忽略的原因和影响范围**
   - 任务: 分析为什么CLOSE订单被忽略
   - 目标: 理解"防止CLOSE订单影响开仓流程"的具体含义
   - 交付: 决策是否需要隔离OPEN和CLOSE订单的状态管理

2. **现有缓存机制分析**
   - 任务: 研究`_pending_updates`缓存机制如何工作
   - 目标: 确定是否需要扩展以支持CLOSE订单
   - 交付: 缓存机制设计方案

3. **Lighter平仓流程验证**
   - 任务: 分析`hedge_manager.execute_hedge`在平仓场景下的行为
   - 目标: 确认修复CLOSE订单处理后Lighter平仓能否自动恢复
   - 交付: Lighter平仓流程验证报告

4. **竞态条件处理最佳实践**
   - 任务: 研究WebSocket订单更新在订单ID设置前到达的处理模式
   - 目标: 设计健壮的竞态条件处理方案
   - 交付: 竞态条件处理策略

### Research Output

研究结果将记录在 `research.md` 文件中，包括：
- **决策**: 每个研究问题的最终选择
- **理由**: 为什么选择该方案
- **替代方案**: 考虑过但未采用的其他方案

---

## Phase 1: Design & Contracts

### Prerequisites

- `research.md` 完成，所有技术决策已确定

### Data Model Design

基于功能规格中的Key Entities，设计以下数据模型：

**套利对（SpreadPair）** - 现有实体，验证属性
- 字段: `pair_id`, `extended_side`, `extended_quantity`, `extended_price`, `lighter_quantity`, `lighter_price`, `close_extended_price`, `close_lighter_price`, `is_closing`, `close_extended_order_id`, `close_lighter_order_id`
- 状态转换: OPEN → CLOSING → CLOSED

**平仓订单（CloseOrder）** - 概念实体，通过订单管理器处理
- 属性: `order_id`, `exchange` (Extended/Lighter), `order_type` (OPEN/CLOSE), `status`, `filled_size`, `filled_price`

**订单状态更新（OrderUpdate）** - WebSocket消息结构
- 字段: `order_id`, `status`, `filled_size`, `price`, `order_type`

### API Contracts

本功能不涉及新的API端点，但需要定义内部合约：

**订单更新处理合约** (`contracts/order_update_contract.md`)
- `update_order_status(order_data: Dict) -> None`
- 输入: WebSocket订单更新消息
- 副作用: 更新内部状态，触发回调
- 异常处理: 不抛出异常，记录错误日志

### Quickstart Guide

`quickstart.md` 将包含：
- 如何运行测试验证修复
- 如何在实际环境中测试强制平仓
- 如何解读日志确认CLOSE订单被正确处理

---

## Phase 2: Implementation Tasks

> 由 `/speckit.tasks` 命令生成，不在本计划范围内

---

## Constitution Re-Check (Post-Design)

*在Phase 1设计完成后重新评估*

### 设计阶段引入的复杂度

本功能的核心修改是移除一段代码（CLOSE订单忽略逻辑），不引入新的架构复杂度。主要工作是：
- 理解现有代码的意图
- 验证修改后的行为符合预期
- 添加测试覆盖边界情况

### 最终评估

- ✅ 代码风格: 符合Python异步编程规范
- ✅ 架构一致性: 修改在现有模块内，不改变系统架构
- ✅ 测试覆盖: 将添加单元测试和集成测试
- ✅ 复杂度控制: 修复性改动，不增加系统复杂度

**结论**: ✅ 设计符合项目宪法，可以进入实施阶段
