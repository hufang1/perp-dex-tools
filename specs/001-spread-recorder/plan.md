# Implementation Plan: 价差实时记录器

**Branch**: `001-spread-recorder` | **Date**: 2026-01-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-spread-recorder/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

创建一个价差实时记录器模块，定期采样两个交易所（Extended和Lighter）的订单簿价格，计算真实价差（使用对手价），并将数据同时输出到CSV文件和终端日志。CSV文件按日期自动管理，支持程序重启后追加数据。终端日志显示详细的计算公式和步骤，使用简体中文输出。

核心需求：
- 定期采样价差数据（默认5秒间隔，可配置）
- 记录到CSV文件（按日期归档，`spreads_YYYY_MM_DD.csv`格式）
- 终端日志显示计算公式和详细步骤
- 处理无效数据并记录警告
- 使用现有的`RealSpreadCalculator`计算逻辑

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, logging, csv (Python标准库)
**Storage**: 本地CSV文件系统存储
**Testing**: pytest
**Target Platform**: Linux/macOS服务器环境
**Project Type**: 单一项目（spread模块扩展）
**Performance Goals**: 记录操作耗时 < 50毫秒/次，对交易性能影响 < 1%
**Constraints**: 必须非阻塞（不能影响主交易循环），线程安全的CSV写入
**Scale/Scope**: 每天约17,280条记录（24小时 × 720分钟 × 12次/分钟），单个CSV文件约2-3MB

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

由于项目没有定制的constitution文件，我们使用通用的最佳实践原则：

### 设计原则

1. **简单性优先**: 使用Python标准库（csv, logging, asyncio），不引入新依赖
2. **非侵入式设计**: 记录功能作为独立模块，不修改现有交易逻辑
3. **线程安全**: 使用asyncio确保异步环境下的数据一致性
4. **容错性**: 记录失败不应中断交易，只记录警告日志
5. **可测试性**: 独立的测试用例覆盖核心功能

### 技术约束

- **无数据库依赖**: 使用CSV文件存储（符合需求假设）
- **异步设计**: 必须与现有的asyncio事件循环集成
- **资源限制**: 单个CSV文件大小控制在合理范围（< 10MB/天）
- **性能要求**: 记录操作不能阻塞主交易循环

### 设计权衡

| 决策 | 理由 | 替代方案及拒绝原因 |
|------|------|-------------------|
| CSV文件存储 | 简单、兼容pandas/Excel | 数据库：过度设计，增加依赖和复杂度 |
| asyncio异步任务 | 与现有架构一致 | 线程：增加锁的复杂性，与asyncio不兼容 |
| 按日期分割文件 | 简单归档和管理 | 单文件：文件过大，难以管理 |
| 缓冲写入+定时刷新 | 性能优化 | 每次写入：频繁IO，性能差 |

## Project Structure

### Documentation (this feature)

```text
specs/001-spread-recorder/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
└── checklists/          # Quality checklists
    └── requirements.md  # Specification quality checklist
```

### Source Code (repository root)

```text
spread/                    # 现有价差套利模块
├── spread_recorder.py     # [NEW] 价差记录器主模块
├── spread_recorder_config.py  # [NEW] 记录器配置（可合并到config.py）
├── models.py              # [EXTEND] 添加SpreadRecord数据模型
└── bot.py                 # [MODIFY] 集成记录器到主循环

tests/                     # 测试文件
├── test_spread_recorder.py  # [NEW] 记录器单元测试
└── integration/
    └── test_spread_recorder_integration.py  # [NEW] 集成测试

data/                      # [EXISTING] 数据导出目录
└── spreads_YYYY_MM_DD.csv # [NEW] 价差记录CSV文件

logs/                      # [EXISTING] 日志目录
└── spread_recorder.log    # [NEW] 记录器专用日志（可选）
```

**Structure Decision**: 将记录器作为独立模块添加到现有的`spread/`目录，与`data_collector.py`和`trade_analyzer.py`保持一致的架构风格。核心类是`SpreadRecorder`，负责定期采样、计算和记录。

## Complexity Tracking

> **无宪法违规需要复杂度追踪**

设计遵循简单性原则，没有引入不必要的复杂性：
- 使用Python标准库，无新依赖
- CSV存储简单直观
- 异步任务与现有架构一致
- 按日期分割文件是简单有效的归档策略
