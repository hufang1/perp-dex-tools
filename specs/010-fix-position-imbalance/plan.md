# Implementation Plan: 修复仓位失衡和优化开仓标准

**Branch**: `010-fix-position-imbalance` | **Date**: 2026-01-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-fix-position-imbalance/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

本功能需要修复两个关键问题：

1. **P0 - 严重仓位失衡**：Extended累积0.21 ETH但Lighter仅对冲0.02 ETH（90%未对冲），需要实现对冲失败检测、熔断机制和仓位保护
2. **P1 - 优化开仓频率**：当前10小时仅2次开仓机会，需要降低阈值（0.10%→0.06%）但前提是对冲成功率>90%
3. **P2 - 优化平仓策略**：降低盈利目标和平仓阈值，加快资金周转

## Technical Context

**Language/Version**: Python 3.10.19
**Primary Dependencies**: websockets 12.0+, x10-python-trading-starknet 0.0.10, lighter-sdk 0.1.4, pytest, decimal.Decimal
**Storage**: 内存状态存储 + 文件日志（logs/trade.log） + CSV导出（data/）
**Testing**: pytest（单元测试25+个，集成测试10+个）
**Target Platform**: Linux/macOS服务器，WebSocket实时数据流
**Project Type**: single - 单体Python项目
**Performance Goals**: 对冲失败检测<5秒，仓位平衡计算<100ms，订单处理<1秒
**Constraints**: 必须在检测到对冲失败后立即停止开仓，仓位失衡率>50%时进入安全模式
**Scale/Scope**: 最大3个并发套利对，25 USDT总持仓，5秒采样间隔

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Note**: 项目当前没有 constitution.md 文件，使用默认的开发最佳实践：
- 测试驱动开发（TDD）：先写测试，再实现功能
- 单元测试覆盖：所有新增功能必须有单元测试
- 集成测试覆盖：对冲失败检测、熔断机制需要集成测试
- 代码审查：所有P0代码需要仔细审查

## Project Structure

### Documentation (this feature)

```text
specs/010-fix-position-imbalance/
├── plan.md              # 本文件 (/speckit.plan 命令输出)
├── research.md          # Phase 0 输出 (/speckit.plan 命令)
├── data-model.md        # Phase 1 输出 (/speckit.plan 命令)
├── quickstart.md        # Phase 1 输出 (/speckit.plan 命令)
├── contracts/           # Phase 1 输出 (/speckit.plan 命令)
└── tasks.md             # Phase 2 输出 (/speckit.tasks 命令 - 非 /speckit.plan 创建)
```

### Source Code (repository root)

```text
spread/                     # 价差套利核心模块
├── bot.py                   # 主引擎（P0: 对冲失败检测）
├── position_aggregator.py   # 仓位聚合器（P0: 修复失衡率计算）
├── hedge_manager.py         # 对冲管理器（P0: 失败率统计）
├── config.py                # 配置类（P0/P1: 新增安全配置）
├── order_manager.py         # 订单管理器（P0: 状态跟踪）
├── models.py                # 数据模型（P0: HedgeFailureTracking）
├── safety_monitor.py        # [NEW] 安全监控模块（P0: 熔断器）
└── trade_logger.py          # 交易日志（P0: 失败事件记录）

exchanges/                  # 交易所客户端
├── lighter_custom_websocket.py # P0: 对冲失败检测
└── extended.py             # P0: 订单状态跟踪

tests/                      # 测试框架
├── test_safety_monitor.py      # [NEW] P0安全监控测试
├── test_hedge_failure_detection.py  # [NEW] P0对冲失败检测测试
├── test_position_balance_fix.py    # [NEW] P0仓位平衡计算修复测试
└── integration/
    └── test_circuit_breaker_integration.py  # [NEW] P0熔断机制集成测试
```

**Structure Decision**: 选择单项目结构（Option 1），因为这是一个Python异步交易系统，所有模块在同一个进程中运行。新增`safety_monitor.py`模块专门处理P0安全功能。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | 使用现有项目结构，无新增复杂度 |

## Phase 0: Research & Technical Decisions

### 研究任务

#### R1: 对冲失败检测机制
**目标**: 确定如何可靠检测Extended成交但Lighter失败的情况

**研究点**:
- Extended订单状态回调时机（WebSocket vs REST轮询）
- Lighter订单失败的原因（流动性、滑点、API限制）
- 当前代码中的订单状态追踪机制
- 如何在5秒内检测到对冲失败

**需要澄清**:
- 当前`hedge_manager.py`中的订单失败处理逻辑
- `order_manager.py`中的订单状态缓存机制
- WebSocket回调与订单处理的竞态条件

#### R2: 仓位平衡计算修复
**目标**: 确定正确的仓位平衡率计算公式

**研究点**:
- 当前`PositionBalance.__post_init__`中的计算逻辑
- `PositionAggregator.calculate_balance()`的实现
- 对冲仓位的符号约定（多头/空头）
- 正确的`diff_rate`计算公式

**需要澄清**:
- 为什么两个不同的计算方式存在
- 日志显示的仓位是否包含符号信息
- 理想的完全对冲状态应该显示什么值

#### R3: 熔断机制设计
**目标**: 设计多级熔断机制防止资金损失

**研究点**:
- 熔断触发条件（失败率、失衡率、连续失败次数）
- 熔断后的行为（停止开仓、强制平仓、通知用户）
- 熔断解除条件（手动重置、自动恢复）
- 与现有`circuit_breaker`逻辑的集成

**需要澄清**:
- 当前代码中是否已有熔断机制
- `consecutive_failures`和`pause_until`的使用
- 如何区分"暂时性失败"和"系统性问题"

#### R4: Lighter交易所深度问题
**目标**: 确定Lighter对冲失败的根本原因

**研究点**:
- Lighter订单簿深度（35 USDT订单的影响）
- 当前使用的市价单vs限价单策略
- 价格滑点对成交的影响
- Lighter WebSocket的可靠性

**需要澄清**:
- 当前`hedge_manager.py`中的订单类型（市价/限价）
- 深度检查逻辑（`max_lighter_depth_ratio`）
- 是否需要切换到限价单+Post-Only策略

#### R5: 配置项设计
**目标**: 确定需要新增的配置项

**研究点**:
- 安全相关的配置项（失败率阈值、失衡率阈值）
- 动态阈值调整的配置
- 熔断机制配置
- 日志级别配置

**需要澄清**:
- 当前`SpreadArbConfig`中的安全配置
- 环境变量vs硬编码配置的选择
- 配置热更新的需求

### 研究执行

**研究已完成** - 参见 [research.md](./research.md)

**关键发现**：
1. 系统已有对冲失败检测机制，但熔断器没有被正确触发
2. `PositionBalance.__post_init__`使用错误的计算方式
3. 90%对冲失败率不是订单类型问题，而是系统性问题
4. 需要新增`safety_monitor.py`模块增强监控

**技术决策**：
- 修复`PositionBalance`计算逻辑（使用绝对值）
- 新增`SafetyMonitor`模块实现多级熔断
- 保持当前订单策略，增强错误处理

## Phase 1: Design & Contracts

**Phase 1 已完成** - 参见以下文档：
- [data-model.md](./data-model.md) - 数据模型设计
- [contracts/modules.md](./contracts/modules.md) - 模块接口契约
- [quickstart.md](./quickstart.md) - 实现指南

**设计摘要**：

### 新增数据模型

1. **HedgeFailureTracking** - 跟踪对冲失败记录
2. **SafetyState** - 实时安全状态
3. **PositionSnapshot** - 仓位快照

### 新增模块

1. **SafetyMonitor** (spread/safety_monitor.py)
   - 对冲失败率监控
   - 仓位失衡率计算
   - 多级熔断器逻辑

2. **AdaptiveThresholdManager** (spread/adaptive_threshold_manager.py) - P1
   - 动态阈值调整
   - 根据对冲成功率切换

### 修改现有模块

1. **PositionBalance** (models.py) - 修复`diff_rate`计算
2. **SpreadArbConfig** (config.py) - 新增安全配置
3. **SpreadArbitrageBot** (bot.py) - 集成SafetyMonitor

### 测试文件

1. `test_safety_monitor.py` - 单元测试
2. `test_position_balance_fix.py` - 计算修复测试
3. `test_circuit_breaker_integration.py` - 集成测试

## Phase 2: Implementation Tasks

**下一步**: 运行 `/speckit.tasks` 生成详细的任务列表

**实现顺序**：
1. P0-1: 修复仓位平衡计算（30分钟）
2. P0-2: 创建SafetyMonitor模块（2小时）
3. P0-3: 集成到Bot（1.5小时）
4. P0-4: 更新配置（30分钟）
5. P0-5: 编写测试（1.5小时）
6. P0-6: 验证和修复（1小时）

**P0总工作量**: 约6小时

完成P0后，根据对冲成功率决定是否继续P1和P2。