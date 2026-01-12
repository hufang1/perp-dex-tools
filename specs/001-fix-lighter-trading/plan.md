# Implementation Plan: 修复Lighter交易所下单失败和日志混乱问题

**Branch**: `001-fix-lighter-trading` | **Date**: 2026-01-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-fix-lighter-trading/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

修复套利程序中Lighter交易所下单总是失败（AttributeError异常）和日志标识混乱导致无法快速定位问题的问题。

**主要需求**:
1. **P0**: 修复Lighter SDK初始化问题，解决`AttributeError: 'NoneType' object has no attribute 'code'`错误
2. **P1**: 统一日志标识，所有Extended日志包含`[EXTENDED]`，所有Lighter日志包含`[LIGHTER]`
3. **P1**: 紧急平仓改用taker订单（post_only=False）确保立即成交

**技术方法**: 修复Lighter客户端的代理配置和SDK初始化逻辑，更新TradingLogger添加明确的交易所标识，修改紧急平仓流程使用taker订单。

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
- `lighter-sdk 0.1.4`: Lighter交易所官方SDK
- `websockets 12.0+`: WebSocket客户端库
- `x10-python-trading-starknet 0.0.10`: Extended交易所SDK
- `pytest`: 单元测试框架
- `decimal.Decimal`: 精确的金融数值计算

**Storage**: 内存状态存储 + 文件日志（logs/trade.log）
**Testing**: pytest (单元测试) + 集成测试
**Target Platform**: Linux/macOS服务器
**Project Type**: 单项目 (Python异步应用)
**Performance Goals**:
- 并发下单延迟 < 5ms
- 订单响应时间 < 500ms
- 日志写入延迟 < 50ms

**Constraints**:
- 必须使用asyncio异步编程
- 所有金融计算使用Decimal避免浮点误差
- 不抛出异常，通过返回值传递错误

**Scale/Scope**:
- 同时监控2个交易所（Extended + Lighter）
- 最多3个并发套利对
- 每秒约1-2次套利机会检查

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

由于项目没有提供constitution.md文件，以下基于常见软件工程最佳实践进行验证：

| 原则 | 状态 | 说明 |
|------|------|------|
| **代码简洁性** | ✅ PASS | 修复现有bug，不引入新的复杂性 |
| **测试优先** | ✅ PASS | 为每个修复编写单元测试 |
| **向后兼容** | ✅ PASS | 只修改内部实现，不改变外部API |
| **可观测性** | ✅ PASS | 增强日志标识，提升可观测性 |
| **错误处理** | ✅ PASS | 改进错误处理和异常捕获 |

**所有检查项通过**，可以继续Phase 0研究。

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-lighter-trading/
├── plan.md              # 本文件
├── research.md          # Phase 0输出
├── data-model.md        # Phase 1输出
├── quickstart.md        # Phase 1输出
├── contracts/           # Phase 1输出（本功能不需要API契约）
├── checklists/          # 质量检查清单
│   └── requirements.md  # 需求检查清单
└── tasks.md             # Phase 2输出（由/speckit.tasks创建）
```

### Source Code (repository root)

```text
# 修改的文件
exchanges/
├── lighter.py           # 修复SDK初始化和代理配置
└── extended.py          # 添加[EXTENDED]日志标识

helpers/
└── logger.py            # 添加[EXTENDED]/[LIGHTER]标识

spread/
├── concurrent_executor.py  # 添加[EXTENDED]/[LIGHTER]日志，修复紧急平仓使用taker
└── bot.py               # 更新日志标识

# 新增测试
tests/
├── test_lighter_client_fix.py       # Lighter客户端修复测试
├── test_logger_identifiers.py       # 日志标识测试
└── integration/
    └── test_lighter_order_fix_integration.py  # Lighter下单集成测试
```

**Structure Decision**: 单项目Python异步应用结构。修改现有交易所客户端和日志模块，不改变项目架构。

## Complexity Tracking

本功能是bug修复，不引入新的复杂性。所有修改都在现有代码范围内，不违反简洁性原则。
