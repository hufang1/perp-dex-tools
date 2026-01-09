# Implementation Plan: 平仓逻辑修复与持仓监控调试

**Branch**: `003-close-position-debug` | **Date**: 2026-01-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-close-position-debug/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

本功能旨在修复价差套利机器人的自动平仓逻辑。当前 `_force_close_pair` 函数未实现（仅包含 `pass`），导致触发平仓条件后系统无法实际执行平仓操作，造成持仓持续增长。同时，在持仓期间添加详细的调试信息输出，帮助用户实时监控持仓状态。

**问题根因**：
- `_force_close_pair` 函数体只有 `pass`，未实现任何平仓逻辑
- 触发平仓条件后，套利对永远不会从 `open_pairs` 中移除
- 持仓时间持续增长，重复触发平仓警告

**技术方案**：
1. 实现 `_force_close_pair` 函数，使用对手价模拟市价单快速平仓
2. 在 `_monitor_pairs` 循环中添加持仓状态监控输出
3. 添加 `is_closing` 标志防止重复平仓

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, logging, pytest
**Storage**: 状态在内存中，日志写入文件 (N/A数据库)
**Testing**: pytest (单元测试和集成测试)
**Target Platform**: Linux/macOS 服务器
**Project Type**: single (单项目 Python 应用)
**Performance Goals**:
  - 平仓订单提交延迟 < 5 秒
  - 持仓状态刷新频率: 每 5-10 秒
  - 控制台输出不影响主循环性能
**Constraints**:
  - 金融数值计算必须使用 Decimal 类型
  - 所有 I/O 操作必须使用 async/await
  - 日志输出必须线程安全
  - 所有输出使用简体中文
**Scale/Scope**:
  - 同时监控最多 10 个套利对
  - 控制台输出每周期不超过 20 行
  - 不增加超过 200 行新代码

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

基于项目的开发实践（参考 CLAUDE.md）：

| 原则 | 状态 | 说明 |
|------|------|------|
| 异步编程 | ✅ 通过 | 所有 I/O 操作使用 async/await |
| 金融精度 | ✅ 通过 | 使用 Decimal 进行所有数值计算 |
| 日志规范 | ✅ 通过 | 使用 logging 模块，中文输出 |
| 测试优先 | ⚠️ 注意 | 需要为新功能添加单元测试 |
| 错误处理 | ✅ 通过 | 通过返回值传递错误，不抛异常 |

**结论**: 符合项目开发规范，可以继续。

## Project Structure

### Documentation (this feature)

```text
specs/003-close-position-debug/
├── spec.md              # 功能规格说明书
├── plan.md              # 本文件 (实施计划)
├── research.md          # Phase 0 输出 (研究结果) ✅
├── data-model.md        # Phase 1 输出 (数据模型) ✅
├── quickstart.md        # Phase 1 输出 (快速开始) ✅
├── contracts/           # Phase 1 输出 (合约定义) ✅
│   └── api.md           # 内部 API 契约
└── tasks.md             # Phase 2 输出 (/speckit.tasks 命令生成)
```

### Source Code (repository root)

```text
spread/                    # 价差套利模块
├── bot.py                # 修改：实现强制平仓逻辑，添加持仓监控输出
├── spread_pair.py         # 可选修改：添加 is_closing 属性
├── order_manager.py       # 参考：订单管理器
└── hedge_manager.py       # 参考：对冲管理器

tests/                     # 测试文件
├── test_force_close.py    # 新增：强制平仓单元测试
└── integration/
    └── test_close_flow.py # 新增：完整平仓流程集成测试
```

**Structure Decision**: 单项目结构。新功能主要修改 `spread/bot.py`，可选择性地在 `spread/spread_pair.py` 中添加 `is_closing` 属性。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

本功能无需违反任何项目原则。设计保持简单：
- 强制平仓逻辑复用现有的 `_close_pair` 函数
- 持仓监控输出直接集成到现有的 `_monitor_pairs` 循环
- 不引入新的依赖或复杂的抽象层
- 预计代码增加量 < 200 行

## Phase 0: Research ✅

**状态**: 完成

**研究结果**: 详见 [research.md](./research.md)

**关键发现**：
1. `_force_close_pair` 函数未实现（只有 `pass`）
2. 现有 `_close_pair` 函数已实现完整平仓流程
3. Extended 使用限价单，Lighter 使用市价单
4. 订单簿数据已由 WebSocket 实时更新

**决策**：
- 复用 `_close_pair` 函数实现强制平仓
- 使用对手价模拟市价单
- 持仓监控输出集成到 `_monitor_pairs` 循环

## Phase 1: Design ✅

**状态**: 完成

**产出文件**：
- [data-model.md](./data-model.md) - 数据模型分析
- [contracts/api.md](./contracts/api.md) - 内部 API 契约
- [quickstart.md](./quickstart.md) - 开发快速开始指南

**设计决策**：

### 1. 强制平仓实现

```python
async def _force_close_pair(self, pair: SpreadPair) -> bool:
    """
    使用对手价模拟市价单，快速平仓以避免进一步损失。

    流程：
    1. 检查 is_closing 标志，防止重复平仓
    2. 获取当前订单簿的对手价
    3. 构造 opportunity 字典
    4. 调用 _close_pair 执行平仓
    """
```

### 2. 持仓状态输出

```python
def _log_position_status(
    self,
    pair: SpreadPair,
    current_extended_price: Decimal,
    current_lighter_price: Decimal
) -> None:
    """
    输出持仓状态信息到控制台（简体中文）

    包含：持仓时间、剩余时间、仓位、当前价格、未实现盈亏、距离盈利目标
    """
```

### 3. 数据模型变更

**可选新增属性**：
```python
class SpreadPair:
    is_closing: bool = False  # 是否正在平仓中
```

## Constitution Check (Re-evaluation)

*GATE: Re-check after Phase 1 design*

| 原则 | Phase 0 | Phase 1 | 说明 |
|------|---------|---------|------|
| 异步编程 | ✅ | ✅ | 所有修改的方法保持异步 |
| 金融精度 | ✅ | ✅ | 使用 Decimal 进行计算 |
| 日志规范 | ✅ | ✅ | 输出使用简体中文 |
| 测试优先 | ⚠️ | ✅ | 已规划单元测试和集成测试 |
| 错误处理 | ✅ | ✅ | 通过返回值传递错误 |

**结论**: 设计阶段完成后，所有原则均符合要求。

## Phase 2: Implementation Planning

**状态**: 待执行（通过 `/speckit.tasks` 命令生成）

**实现任务概览**：

1. **实现 `_force_close_pair` 函数** (P1)
   - 使用对手价模拟市价单
   - 添加 is_closing 标志检查
   - 复用 _close_pair 逻辑

2. **添加持仓状态输出** (P2)
   - 实现 _log_position_status 方法
   - 集成到 _monitor_pairs 循环
   - 格式化中文输出

3. **添加 is_closing 属性** (P2, 可选)
   - 在 SpreadPair.__init__ 中添加
   - 在平仓流程中正确设置和重置

4. **编写测试** (P2)
   - test_force_close.py 单元测试
   - test_close_flow.py 集成测试

## Success Criteria

| 标准 | 测量方法 | 目标 |
|------|----------|------|
| 强制平仓成功执行 | 运行测试，观察日志 | 触发平仓条件后30秒内完成平仓 |
| 持仓状态正常输出 | 观察控制台 | 每5-10秒输出一次完整状态 |
| 套利对正确移除 | 检查 open_pairs | 平仓后从列表中移除 |
| 统计信息更新 | 检查 stats | 成功平仓计数正确 |
| 无重复平仓 | 触发平仓后观察 | 只执行一次平仓操作 |

## Risks & Mitigations

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 对手价滑点过大 | 平仓价格不理想 | 记录实际成交价格，监控滑点 |
| 平仓订单失败 | 套利对仍持仓 | 重置 is_closing 标志，允许重试 |
| 输出信息过多 | 影响日志可读性 | 使用 INFO 级别，格式清晰 |
| 并发平仓冲突 | 多个循环同时平仓 | is_closing 标志防护 |

## Dependencies

- **必须**: 001-trade-log (交易日志功能)
- **参考**: 现有的 `_close_pair` 实现
- **无外部依赖**: 不涉及新的第三方库

## Next Steps

1. ✅ Phase 0: 研究完成
2. ✅ Phase 1: 设计完成
3. ⏭️ **Phase 2**: 运行 `/speckit.tasks` 生成详细任务列表
4. ⏭️ **Phase 3**: 实施代码修改
5. ⏭️ **Phase 4**: 测试验证
6. ⏭️ **Phase 5**: 合并部署
