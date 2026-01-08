# Implementation Plan: 优化价差套利策略

**Branch**: `002-optimize-spread-arb` | **Date**: 2026-01-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-optimize-spread-arb/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

本功能旨在优化现有价差套利策略,解决四个核心问题: (1) 单边持仓风险控制, (2) 基于手续费的开仓阈值优化, (3) 多层智能平仓策略, (4) 完整的交易价格日志记录。

技术方法: 基于现有的Python asyncio架构,通过配置参数化、增强监控循环、改进平仓决策逻辑和扩展日志系统来实现。无新增外部依赖,主要优化现有代码逻辑。

## Technical Context

**Language/Version**: Python 3.11+ (asyncio)
**Primary Dependencies**: websockets, decimal.Decimal, logging, pytest
**Storage**: 状态在内存中,日志写入文件 (N/A数据库)
**Testing**: pytest (单元测试和集成测试)
**Target Platform**: Linux/macOS服务器运行环境
**Project Type**: single (单项目应用)
**Performance Goals**:
  - 订单处理延迟 < 100ms (p95)
  - WebSocket消息处理延迟 < 50ms
  - 监控循环检查间隔 5秒
  - 策略循环检查间隔 100ms

**Constraints**:
  - 单边持仓必须在60秒内检测并处理
  - 配置参数必须可外部调整(环境变量或配置文件),无需修改代码
  - 日志记录不能显著影响交易执行速度(< 5ms开销)
  - 必须处理订单部分成交场景
  - 必须兼容现有的WebSocket订单更新机制

**Scale/Scope**:
  - 当前最大同时持仓: 3个套利对
  - 单次下单金额: $35 USDT
  - 预期处理能力: 10+ 并发套利对
  - 日志数据量: 每个套利对约10条关键日志记录

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**当前状态**: 项目尚未建立宪章 (constitution.md 为模板)

**质量门禁** (基于现有代码库最佳实践):
- [x] 代码必须使用 Decimal 进行所有金融计算 (避免浮点精度问题)
- [x] 所有 I/O 操作必须使用 async/await 模式
- [x] 不抛出异常,通过返回值传递错误信息
- [x] 使用 logging 模块记录关键事件 (debug级别记录详细信息, info级别记录关键事件)
- [x] 单元测试覆盖核心逻辑 (使用 pytest)

**风险评估**:
- 单边持仓风险: 当前代码已检测但未完全解决,需要增强紧急平仓机制
- 配置硬编码: 部分阈值硬编码在代码中,需要迁移到配置类
- 日志完整性: 当前缺少交易价格详细记录,需要增强日志结构

**结论**: 通过 - 无阻塞性违规,建议在实现过程中遵循上述最佳实践

## Project Structure

### Documentation (this feature)

```text
specs/002-optimize-spread-arb/
├── spec.md              # 功能规格说明 (已完成)
├── plan.md              # 本文件 - 实现计划
├── research.md          # Phase 0 输出 - 技术调研
├── data-model.md        # Phase 1 输出 - 数据模型
├── quickstart.md        # Phase 1 输出 - 快速开始指南
├── contracts/           # Phase 1 输出 - API合约 (本功能不适用)
└── checklists/
    └── requirements.md  # 质量检查清单 (已完成)
```

### Source Code (repository root)

本项目使用单一项目结构 (Option 1: Single Project):

```text
spread/                      # 价差套利模块 (主要修改目录)
├── bot.py                   # 套利机器人主引擎 - 修改: 增强单边持仓监控,改进平仓逻辑
├── spread_pair.py           # 套利对数据模型 - 修改: 增加价格记录字段
├── config.py                # 配置类 - 修改: 新增可配置参数 (时间阈值、盈利目标)
├── order_manager.py         # 订单管理器 - 修改: 增强价格日志记录
├── hedge_manager.py         # 对冲管理器 - 修改: 增强对冲失败处理
└── calculator.py            # 价差计算器 - 修改: 调整价差阈值计算逻辑

exchanges/                   # 交易所客户端 (无修改,仅引用)
├── extended.py             # Extended交易所客户端
└── lighter_custom_websocket.py  # Lighter WebSocket客户端

tests/                       # 测试文件 (新增)
├── test_spread_pair.py      # 套利对单元测试
├── test_config.py           # 配置参数测试
└── integration/
    └── test_closing_strategy.py  # 平仓策略集成测试
```

**Structure Decision**: 选择单一项目结构,因为:
1. 现有代码库已采用此结构
2. 功能专注于优化现有模块,无需新增独立服务
3. 所有修改集中在 spread/ 目录内
4. 测试文件遵循现有测试目录布局

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

N/A - Constitution Check 通过,无需要 justify 的违规项。
