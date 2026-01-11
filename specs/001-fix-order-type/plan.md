# Implementation Plan: 修复订单类型问题并增加交易成功率统计

**Branch**: `001-fix-order-type` | **Date**: 2026-01-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-fix-order-type/spec.md`

## Summary

本功能修复价差套利交易系统中的两个核心问题并增加成功率统计功能：

1. **P1-核心修复**: 强制所有开仓订单使用taker订单类型，确保订单立即成交，避免maker订单挂单未成交导致的仓位失衡
2. **P1-核心修复**: 验证开仓后Extended和Lighter仓位数量一致性，消除当前存在的0.01 ETH差异
3. **P2-功能增强**: 增加开仓/平仓成功率统计功能，记录失败原因，CSV输出使用双语列名

**技术方案**:
- 修改`order_manager.py`和`hedge_manager.py`，强制开仓订单使用taker类型
- 在`bot.py`中增加仓位一致性验证逻辑
- 创建`success_tracker.py`模块记录和统计交易成功率
- 扩展CSV导出功能，增加成功率相关字段

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, logging, pytest, dataclasses, csv
**Storage**: 内存状态存储 + 文件日志（logs/trade.log） + CSV导出（data/）
**Testing**: pytest
**Target Platform**: Linux/macOS服务器
**Project Type**: 单一项目（价差套利交易机器人）
**Performance Goals**: 订单提交延迟 < 100ms，成功率统计开销 < 10ms/次
**Constraints**: 不引入外部依赖，使用Python标准库
**Scale/Scope**: 单机器人实例，每日约1000-10000次交易操作

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

当前项目使用模板Constitution，核心原则检查：

| 原则 | 状态 | 说明 |
|------|------|------|
| 测试优先 (Test-First) | ✅ 通过 | 使用pytest，TDD流程 |
| 可观测性 (Observability) | ✅ 通过 | 增加成功率统计，符合日志和监控要求 |
| 简单性 (Simplicity) | ✅ 通过 | 无新增外部依赖，复用现有CSV导出机制 |
| 向后兼容 | ✅ 通过 | 扩展现有模块，不破坏现有功能 |

**GATE结果**: ✅ 全部通过，可以进入Phase 0研究阶段

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-order-type/
├── spec.md              # 功能规格说明
├── plan.md              # 本文件（实现计划）
├── research.md          # Phase 0输出（技术研究）
├── data-model.md        # Phase 1输出（数据模型）
├── quickstart.md        # Phase 1输出（快速开始）
├── contracts/           # Phase 1输出（合约/接口定义）
└── tasks.md             # Phase 2输出（任务列表，由/speckit.tasks命令生成）
```

### Source Code (repository root)

```text
spread/                    # 价差套利模块（现有）
├── order_manager.py       # [修改] 增加taker订单强制逻辑
├── hedge_manager.py       # [修改] 增加taker订单强制逻辑
├── bot.py                 # [修改] 增加仓位一致性验证
├── success_tracker.py     # [新增] 成功率追踪器
├── models.py              # [扩展] 增加成功率相关数据模型
└── data_collector.py      # [修改] 扩展CSV导出，增加成功率字段

exchanges/                 # 交易所客户端（现有）
├── extended.py           # [可能修改] 确认taker订单API
└── lighter_custom_websocket.py  # [可能修改] 确认taker订单API

tests/                     # 测试文件（扩展）
├── test_order_manager.py        # [扩展] taker订单测试
├── test_hedge_manager.py        # [扩展] taker订单测试
├── test_success_tracker.py      # [新增] 成功率追踪器测试
├── test_position_consistency.py # [新增] 仓位一致性测试
└── integration/
    └── test_success_tracking_integration.py # [新增] 成功率统计集成测试

data/                      # 数据导出目录（扩展）
├── trades_YYYY_MM_DD.csv        # [扩展] 增加成功率字段
├── orders_YYYY_MM_DD.csv        # [现有]
└── success_stats_YYYY_MM_DD.csv # [新增] 成功率统计汇总
```

**Structure Decision**: 单一项目结构，复用现有spread/模块架构，新增success_tracker.py模块处理成功率统计逻辑。

## Complexity Tracking

> 无宪法违规，此部分留空
