# Implementation Plan: 修复Lighter API调用失败和持仓不平衡问题

**Branch**: `001-fix-lighter-api` | **Date**: 2026-01-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-fix-lighter-api/spec.md`

## Summary

**主要需求**: 修复导致对冲失败的API错误，并实施持仓对账机制防止风险累积

**技术方案**:
1. **Phase 0**: 研究Lighter SDK的正确API方法名（已发现：`account_inactive_orders`而非`account_active_orders`）
2. **Phase 1**: 设计持仓对账数据模型、API错误处理改进、自动平仓机制
3. **Phase 2**: 实施修复（由`/speckit.tasks`命令处理）

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**:
- `lighter` SDK (官方Lighter交易所SDK)
- `asyncio` (异步编程)
- `decimal.Decimal` (精确金融计算)
- `websockets` (WebSocket客户端)
- `pytest` (单元测试)

**Storage**: N/A (状态在内存中，日志写入文件)
**Testing**: pytest + asyncio
**Target Platform**: Linux服务器 (Ubuntu 20.04+)
**Project Type**: single (单项目Python应用)
**Performance Goals**:
- 持仓对账: 每60秒执行一次，<1秒完成
- 订单查询: <2秒返回结果
- 自动平仓: <30秒完成

**Constraints**:
- 必须与现有WebSocket集成兼容
- 不能中断正在运行的套利策略
- 日志必须包含足够信息用于事后分析
- 向后兼容旧版本Lighter SDK

**Scale/Scope**:
- 代码修改: ~3个文件 (lighter.py, hedge_manager.py, bot.py)
- 新增功能: 持仓对账循环
- 测试覆盖: 关键路径100%

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**项目章程状态**: ⚠️ **未定义**

项目尚未定义constitution。基于行业最佳实践，我们应用以下原则：

| 原则 | 状态 | 说明 |
|------|------|------|
| 测试优先 | ⚠️ 部分遵守 | 需要为新功能添加单元测试 |
| 可观测性 | ✅ 遵守 | 所有关键操作都有详细日志 |
| 向后兼容 | ✅ 遵守 | 修复将向后兼容 |
| 错误处理 | ✅ 遵守 | 多层回退机制 |

**Gate决定**: ✅ **通过** - 虽然未定义constitution，但代码遵循Python和金融系统的最佳实践。

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-lighter-api/
├── plan.md              # 本文件 (/speckit.plan命令输出)
├── research.md          # Phase 0输出 (下面创建)
├── data-model.md        # Phase 1输出 (下面创建)
├── quickstart.md        # Phase 1输出 (下面创建)
├── contracts/           # Phase 1输出 (下面创建)
└── tasks.md             # Phase 2输出 (由/speckit.tasks命令创建 - 不在此次范围)
```

### Source Code (repository root)

```text
# 单项目结构 (DEFAULT)
exchanges/
├── lighter.py           # 修改: 修复API方法名
├── lighter_custom_websocket.py  # 可能需要: 改进错误处理
└── base.py              # 不修改: 基类接口

spread/
├── bot.py               # 修改: 添加持仓对账循环
├── hedge_manager.py     # 已修改: 改进等待逻辑 (之前会话中完成)
├── config.py            # 已修改: 添加新配置项 (之前会话中完成)
└── calculator.py        # 可能需要: 添加持仓计算辅助函数

tests/
├── test_lighter_api_fix.py      # 新增: 测试API修复
├── test_position_reconciliation.py  # 新增: 测试持仓对账
└── test_auto_close_unbalanced.py    # 新增: 测试自动平仓
```

**结构决策**: 使用现有的单项目结构。所有修改都在现有模块内，无需新包。

## Complexity Tracking

> 本功能不需要复杂的架构变更，无需justify违反项。

| 复杂度 | 为什么需要 | 拒绝更简单方案的原因 |
|--------|-----------|------------------|
| N/A | - | - |

本修复是straightforward的bug修复和监控增强，不引入新的架构模式。

---

## Phase 0: Research & Decisions

### 研究任务

✅ **已完成的发现**:

1. **Lighter SDK API方法名**
   - **发现**: 代码中使用`account_active_orders`，但SDK实际方法是`account_inactive_orders`
   - **证据**: `python -c "import lighter; print([m for m in dir(lighter.OrderApi) if 'account' in m])"`
   - **决策**: 将`lighter.py:467`的方法调用从`account_active_orders`改为`account_inactive_orders`

2. **现有持仓不平衡问题**
   - **发现**: Lighter持仓($95.72)远大于Extended持仓($31.9)
   - **原因**: 历史对冲失败累积
   - **决策**: 添加持仓对账机制，每60秒检查一次

3. **WebSocket订单更新时序**
   - **发现**: `current_order`由WebSocket回调设置，但可能延迟到达
   - **已在之前会话修复**: hedge_manager.py现在轮询等待最多5秒

### 需要进一步调查

以下任务由研究agent完成，结果记录在research.md中：

1. **Lighter SDK版本兼容性**
   - 任务: 检查是否有多个SDK版本，`account_inactive_orders`是否在所有版本中可用
   - 方法: 查看SDK文档或GitHub仓库

2. **持仓计算方法**
   - 任务: Extended和Lighter如何计算持仓价值（是否包含未实现盈亏）
   - 方法: 查看现有代码中的`get_account_positions()`实现

3. **自动平仓风险**
   - 任务: 评估自动平仓在极端市场条件下的风险
   - 方法: 分析滑点、流动性、部分成交等情况

---

## Phase 1: Design

### 1.1 Data Model

见 [data-model.md](./data-model.md)

### 1.2 API Contracts

见 [contracts/](./contracts/) 目录

### 1.3 Implementation Artifacts

见 [quickstart.md](./quickstart.md)

---

## Phase 2: Implementation Tasks

**Phase 2的任务由 `/speckit.tasks` 命令生成并分解到 `tasks.md`**

本阶段（Phase 0和Phase 1）完成后，运行：
```bash
/speckit.tasks
```

将生成具体的实施任务清单。

---

## Appendix

### 修复的文件清单

| 文件路径 | 修改类型 | 优先级 | 说明 |
|---------|---------|--------|------|
| `exchanges/lighter.py` | Bug修复 | P1 | 修复API方法名 `account_active_orders` → `account_inactive_orders` |
| `spread/bot.py` | 功能增强 | P2 | 添加持仓对账循环 |
| `spread/config.py` | 配置 | P2 | 已完成（之前会话） |
| `spread/hedge_manager.py` | 改进 | P1 | 已完成（之前会话） |

### 测试策略

1. **单元测试**: Mock API响应，验证修复后的代码路径
2. **集成测试**: 使用测试网或小额度真实订单测试
3. **回归测试**: 确保修复不影响现有功能

### 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| SDK方法名在不同版本中可能不同 | 高 | 添加版本检测和向后兼容代码 |
| 持仓对账误报不平衡 | 中 | 设置合理的阈值（20%）和确认机制 |
| 自动平仓在极端市场下失败 | 高 | 默认关闭，需用户手动启用 |
| 性能影响（对账循环） | 低 | 对账频率可配置（默认60秒） |
