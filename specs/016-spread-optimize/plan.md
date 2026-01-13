# Implementation Plan: 价差套利程序优化

**Branch**: `016-spread-optimize` | **Date**: 2026-01-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/016-spread-optimize/spec.md`

## Summary

优化现有价差套利程序（spread目录），实现6个主要功能模块：精简日志输出、实时价差监控、等差数列开仓策略、智能平仓系统、仓位平衡检测、统一Taker交易模式。项目使用Python 3.10，基于asyncio异步架构，与Extended和Lighter两个DEX交易所进行WebSocket实时通信和REST API交易执行。

## Technical Context

**Language/Version**: Python 3.10.19
**Primary Dependencies**: asyncio, aiohttp, websockets, lighter-sdk, x10-python-trading-starknet, pydantic, tenacity
**Storage**: JSON文件状态持久化 (logs/spread_arb_state.json)
**Testing**: pytest (需要添加单元测试)
**Target Platform**: Linux/macOS服务器 (7x24小时运行)
**Project Type**: single - 单体Python项目，spread模块独立但集成到主项目
**Performance Goals**:
- 价差监控延迟 < 100ms
- 订单簿更新频率与WebSocket同步（约每秒多次）
- 开仓/平仓决策延迟 < 200ms
- 仓位平衡检测在配置缓冲期内完成（默认3秒）

**Constraints**:
- 必须与现有交易所客户端兼容（exchanges/lighter.py, exchanges/extended.py）
- 不能破坏现有的状态管理和持久化机制
- WebSocket连接断开时需要自动重连
- 交易所API可能有速率限制

**Scale/Scope**:
- 当前代码规模: ~3500行 (spread模块)
- 6个功能模块需要独立实现和测试
- 支持2个DEX交易所（Extended、Lighter）
- 单一交易对（BTC或ETH）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

当前项目没有专门的Constitution文件。基于代码分析，项目遵循以下原则：

1. **模块化设计**: spread模块包含独立组件（order_book_manager, spread_calculator, risk_manager, trade_executor, state_manager）
2. **异步优先**: 所有I/O操作使用async/await模式
3. **状态持久化**: 使用JSON文件保存状态，支持程序重启恢复
4. **错误处理**: 使用自定义异常类（exceptions.py）

**所有检查通过** - 可以继续Phase 0研究

## Project Structure

### Documentation (this feature)

```text
specs/016-spread-optimize/
├── plan.md              # 本文件
├── research.md          # Phase 0输出
├── data-model.md        # Phase 1输出
├── quickstart.md        # Phase 1输出
├── contracts/           # Phase 1输出（如需要API契约）
└── tasks.md             # Phase 2输出（由/speckit.tasks生成）
```

### Source Code (repository root)

```text
spread/                      # 价差套利模块（现有）
├── __init__.py
├── models.py               # 数据模型（BotConfig, BotState, Position等）
├── spread_arb_bot.py       # 主控制器（需修改）
├── order_book_manager.py   # 订单簿管理（需增强）
├── spread_calculator.py    # 价差计算（需重构）
├── trade_executor.py       # 交易执行（需修改为taker模式）
├── state_manager.py        # 状态管理（需扩展）
├── risk_manager.py         # 风控管理（需添加平衡检测）
├── env_validator.py        # 环境验证（需精简日志）
├── exceptions.py           # 异常定义
├── utils.py                # 工具函数
├── spread_monitor.py       # [新增] 实时价差监控组件
├── arithmetic_open_strategy.py  # [新增] 等差数列开仓策略
├── smart_close_strategy.py      # [新增] 智能平仓系统
├── position_balance_checker.py  # [新增] 仓位平衡检测
└── logger_config.py        # [新增] 精简日志配置

exchanges/                   # 交易所客户端（现有，不修改）
├── lighter.py              # Lighter交易所客户端
├── lighter_custom_websocket.py  # Lighter WebSocket实现
└── extended.py             # Extended交易所客户端

tests/                       # 测试目录（需创建）
├── unit/                   # 单元测试
│   ├── test_spread_monitor.py
│   ├── test_arithmetic_open_strategy.py
│   ├── test_smart_close_strategy.py
│   └── test_position_balance_checker.py
└── integration/            # 集成测试
    └── test_spread_optimization_integration.py
```

**Structure Decision**: 选择单项目结构（Option 1），因为：
1. 这是一个独立的Python模块（spread/），不是web应用或移动应用
2. 所有功能组件都在同一进程中运行
3. 不需要前后端分离
4. 符合现有项目结构

## Complexity Tracking

> **无需填写** - Constitution Check没有违规项

## Phase 0: Research & Design Decisions

### Research Tasks

1. **日志优化最佳实践**
   - Task: 研究Python异步应用的日志精简方案
   - 需要确定: 如何在保持关键信息的同时减少日志输出量

2. **等差数列开仓策略实现**
   - Task: 研究价差套利中的分批建仓策略
   - 需要确定: 如何缓存价差状态、如何在价差波动时避免频繁开仓

3. **Taker vs Maker交易模式**
   - Task: 研究现有代码如何实现taker交易
   - 需要确定: extended.py中place_open_order使用maker模式，需要改造为taker

4. **仓位平衡验证机制**
   - Task: 研究如何在开仓后验证两边仓位
   - 需要确定: 缓冲期内的验证逻辑、不平衡时的处理流程

5. **价差计算和监控**
   - Task: 研究现有的spread_calculator和order_book_manager实现
   - 需要确定: 如何增强实时价差监控、如何输出单行日志

### Design Decisions

| 决策点 | 选择 | 原因 | 替代方案 |
|--------|------|------|----------|
| 日志格式 | 单行紧凑格式 | 用户明确要求所有关键信息在一行内 | 多行详细日志（被拒绝） |
| 价差缓存位置 | models.py中BotConfig | 配置需要在状态持久化中保存 | 独立文件（增加复杂度） |
| 开仓策略模块 | 独立类arithmetic_open_strategy.py | 符合解耦要求，可独立测试 | 集成到spread_calculator（违反解耦） |
| 平仓触发机制 | 独立类smart_close_strategy.py | 符合解耦要求，可独立测试 | 集成到spread_calculator（违反解耦） |
| Taker实现 | 直接调用API，不使用post_only | 确保即时成交 | 保持maker模式（违反需求） |
| 仓位平衡检测 | 独立类position_balance_checker.py | 符合解耦要求 | 集成到trade_executor（耦合度高） |

## Phase 1: Design Artifacts

### Data Model

详见 [data-model.md](./data-model.md)

### API Contracts

不适用 - 这是内部模块，不对外暴露API

### Quick Start Guide

详见 [quickstart.md](./quickstart.md)

## Implementation Phases

### Phase 0: Research (已完成)

- [x] 分析现有代码结构
- [x] 确定技术栈和依赖
- [x] 制定设计决策

### Phase 1: Design (进行中)

- [x] 创建data-model.md
- [x] 创建quickstart.md
- [x] 更新agent context

### Phase 2: Task Breakdown (待执行)

将由 `/speckit.tasks` 命令生成tasks.md

## Risk Assessment

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| WebSocket连接不稳定 | 无法获取实时价格 | 实现自动重连机制 |
| 交易所API变更 | 交易失败 | 保持与现有客户端兼容 |
| 价差剧烈波动 | 策略失效 | 添加风控检查 |
| 单边成交风险 | 资金损失 | 仓位平衡检测+紧急平仓 |
| 状态文件损坏 | 无法恢复状态 | 添加状态验证和备份 |

## Dependencies

### Internal
- exchanges/lighter.py - Lighter交易所客户端
- exchanges/extended.py - Extended交易所客户端
- spread/models.py - 共享数据模型
- spread/state_manager.py - 状态管理

### External
- lighter-sdk==0.1.4 - Lighter官方SDK
- x10-python-trading-starknet==0.0.10 - Extended官方SDK
- asyncio - 异步I/O
- websockets - WebSocket连接

## Open Questions

无 - 所有设计决策已确定
