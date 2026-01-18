# Implementation Plan: Extended Maker模式降低手续费

**Branch**: `017-ext-maker-mode` | **Date**: 2026-01-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/017-ext-maker-mode/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

将现有spread价差套利程序的Extended交易所从Taker模式（吃单，0.025%手续费）改造为Maker模式（挂单，接近0%手续费），从而降低50%以上的手续费成本，提高套利利润率。同时将阶梯式开仓策略改为固定阈值策略（开仓0.09%，平仓0.06%），简化策略逻辑。

**核心变化**：
- Extended从Taker并发执行改为Maker串行执行（Extended先成交，然后Lighter对冲）
- 新增3个状态：OPENING_MAKER_WAIT、CLOSING_MAKER_WAIT、LIGHTER_HEDGING
- 实现实时价差保护和价格位置优化机制
- 支持部分成交处理和智能回滚逻辑

**预期收益**：
- 手续费成本降低50%以上（从0.05%/交易降至接近0%）
- 每日交易次数增加
- 整体利润率提高20%

## Technical Context

**Language/Version**: Python 3.10.19 + asyncio, aiohttp, websockets, lighter-sdk, x10-python-trading-starknet, pydantic, tenacity

**Primary Dependencies**:
- Extended: x10.perpetual.trading_client (官方SDK)
- Lighter: lighter.SignerClient (官方SDK)
- 现有模块: spread, exchanges (extended.py, lighter.py)

**Storage**: JSON文件状态持久化 (logs/spread_arb_state.json)

**Testing**: pytest (单元测试), asyncio集成测试, 回测框架

**Target Platform**: Linux/macOS服务器，Python 3.10+

**Project Type**: single - 单一Python项目，spread套利交易机器人

**Performance Goals**:
- 状态转换延迟 < 100ms
- MAKER_WAIT监控循环处理时间 < 50ms（支持0.5秒监控频率）
- 价差保护响应时间 < 1秒
- Extended Maker订单成交率 >= 80%

**Constraints**:
- 必须向后兼容现有状态机和持仓管理
- WebSocket连接稳定性要求高（Extended和Lighter双连接）
- 必须处理部分成交、订单取消、网络异常等边界情况
- 日志完整性要求100%（关键事件不得遗漏）

**Scale/Scope**:
- 修改现有文件：spread/spread_arb_bot.py, spread/trade_executor.py, spread/models.py, spread/state_manager.py
- 新增文件：可能需要新增spread/maker_order_monitor.py, spread/price_monitor.py
- 新增状态：3个新状态（OPENING_MAKER_WAIT, CLOSING_MAKER_WAIT, LIGHTER_HEDGING）
- 功能需求：23个功能需求
- 成功标准：13个成功标准

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: ⚠️ **CONSTITUTION FILE NOT FOUND** - 使用默认原则

**默认原则应用**：

1. **代码兼容性**: 必须向后兼容现有状态机、持仓管理和配置系统
2. **测试优先**: 新状态和复杂逻辑必须有单元测试和集成测试
3. **可观测性**: 必须添加详细的中文日志，确保状态转换和关键事件可追踪
4. **简洁性**: 复用现有代码结构和模式，避免过度抽象
5. **安全性**: 价差保护、强制平仓、风控暂停等机制必须健壮可靠

**无违规项** - Feature implementation aligns with existing project principles

## Project Structure

### Documentation (this feature)

```text
specs/017-ext-maker-mode/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
spread/                              # Spread套利核心模块
├── spread_arb_bot.py          # 主控制器：状态机逻辑（主要修改）
├── trade_executor.py          # 交易执行：Extended Maker订单 + Lighter对冲（主要修改）
├── models.py                   # 数据模型：BotState枚举，新增状态（主要修改）
├── state_manager.py            # 状态管理：STATE_NAMES_CN映射（主要修改）
├── maker_order_monitor.py      # [新增] Extended Maker订单监控器
├── price_monitor.py             # [新增] 实时价差和价格监控
├── arithmetic_open_strategy.py # 开仓策略：改为固定阈值策略（修改）
└── smart_close_strategy.py     # 平仓策略：保持不变

exchanges/                           # 交易所客户端
├── extended.py                  # Extended客户端：添加Maker订单API（修改）
└── lighter.py                   # Lighter客户端：保持不变

tests/
├── unit/                         # 单元测试
│   ├── test_maker_order_monitor.py      # [新增] Maker订单监控测试
│   ├── test_price_monitor.py           # [新增] 价格监控测试
│   ├── test_extended_maker_mode.py     # [新增] Extended Maker模式集成测试
│   └── test_state_machine.py            # [新增] 状态机转换测试
└── integration/
    └── test_maker_opening_flow.py      # [新增] Maker开仓流程集成测试

logs/
└── spread_arb_state.json          # 状态持久化文件
```

**Structure Decision**: 使用Option 1单项目结构。所有spread相关代码集中在spread/目录下，exchanges/目录包含交易所客户端。测试文件按类型分为unit/和integration/。

## Complexity Tracking

> **Not applicable** - No constitution violations to justify

## Phase 0: Outline & Research

### Research Tasks

基于技术上下文中的NEEDS CLARIFICATION，以下研究任务需要完成：

1. **Extended Maker订单API研究** (CRITICAL)
   - 目标：研究Extended官方SDK如何提交post-only限价单
   - 参考资料：hedge/hedge_mode_ext.py中的place_extended_post_only_order()方法
   - 输出：Extended Maker订单API文档、参数说明、返回值格式
   - 决策：确认Extended支持post-only订单且手续费为0%

2. **Extended订单状态WebSocket监控研究** (CRITICAL)
   - 目标：研究Extended WebSocket如何实时推送订单状态变化
   - 参考资料：hedge/hedge_mode_ext.py中的handle_extended_order_update()方法
   - 输出：WebSocket订阅方式、订单状态推送格式、监听接口设计
   - 决策：确认能够实时监听NEW → PARTIALLY_FILLED → FILLED状态

3. **Extended订单簿WebSocket监控研究** (IMPORTANT)
   - 目标：研究Extended WebSocket如何获取实时订单簿数据
   - 参考资料：hedge/hedge_mode_ext.py中的handle_extended_order_book_update()方法
   - 输出：订单簿订阅方式、BBO价格更新机制
   - 决策：确认能够实时获取best_bid/best_price用于价格位置优化

4. **Maker订单挂单策略研究** (IMPORTANT)
   - 目标：研究如何确定Maker挂单价格以保持最优位置
   - 参考资料：hedge_mode_ext.py中的价格计算逻辑
   - 输出：挂单价格计算公式、价格偏离检测算法、重挂策略
   - 决策：确认挂单价格=best_bid（买入）或best_ask（卖出）

5. **Python异步并发模式研究** (OPTIONAL)
   - 目标：研究如何实现MAKER_WAIT状态的三路并发监控（价差、价格、订单）
   - 参考资料：现有代码中的asyncio.gather模式
   - 输出：最佳实践建议、性能考虑
   - 决策：使用asyncio.gather + 共享锁的模式

6. **部分成交回滚策略研究** (IMPORTANT)
   - 目标：研究如何识别和回滚"本次开仓"的仓位
   - 参考资料：spec.md中的Edge Cases和User Story 1场景9-10
   - 输出：回滚逻辑设计、仓位识别算法
   - 决策：使用累计成交记录识别"本次开仓"部分

### Research Output

将研究结果整合到 `research.md`，包括：
- Extended Maker订单API使用方法和示例
- WebSocket监听接口设计
- 价格监控和价差保护实现方案
- 部分成交处理策略
- 技术选型理由

## Phase 1: Design & Contracts

### Prerequisites

- ✅ `research.md` complete with all findings
- ✅ Spec reviewed and understood
- ✅ Existing codebase reviewed (spread/, exchanges/)

### Data Model (`data-model.md`)

从spec.md的Key Entities提取数据模型：

1. **MakerOrder（挂单订单）**
   - 字段：订单ID、挂单价格、挂单数量、挂单方向、订单状态、成交数量、成交均价、创建时间、最后更新时间、是否为开仓订单

2. **SpreadConfig（价差配置）**
   - 字段：开仓阈值、平仓阈值、Maker挂单超时时间、价格监控间隔、价差监控间隔

3. **PriceMonitor（价格监控器）**
   - 字段：Extended当前最佳买价/卖价、Lighter当前最佳买价/卖价、实时价差、上次检查时间、价格偏离阈值、价差监控频率、价差保护状态

4. **MakerWaitState（Maker等待状态）**
   - 字段：当前等待的Maker订单、等待开始时间、价差保护触发次数、价格调整次数、连续重挂次数限制、部分成交累计数量、本次开仓成交记录、是否需要重新挂单

5. **HedgingState（对冲状态）**
   - 字段：Extended成交数量、Extended成交价格、Lighter对冲订单ID、Lighter对冲数量、对冲开始时间、对冲超时时间

6. **BotState枚举扩展**
   - 新增：OPENING_MAKER_WAIT = "OPENING_MAKER_WAIT"
   - 新增：CLOSING_MAKER_WAIT = "CLOSING_MAKER_WAIT"
   - 新增：LIGHTER_HEDGING = "LIGHTER_HEDGING"

**状态转换关系图**：
- IDLE → OPENING → OPENING_MAKER_WAIT → LIGHTER_HEDGING → OPENING_WAIT → HOLDING
- HOLDING → CLOSING → CLOSING_MAKER_WAIT → LIGHTER_HEDGING → CLOSING_WAIT → IDLE

### API Contracts (`contracts/`)

由于这不是REST API项目，而是交易机器人，contracts/目录将包含：

1. **internal-apis.md** - 内部模块接口定义
   - ExtendedClient.place_maker_order() 接口
   - ExtendedClient.cancel_order() 接口
   - MakerOrderMonitor 类接口
   - PriceMonitor 类接口

2. **state-machine.md** - 状态机接口定义
   - 新增状态的转换接口
   - MAKER_WAIT状态监控接口
   - LIGHTER_HEDGING状态执行接口

3. **logging-spec.md** - 日志规范
   - 状态转换日志格式
   - 监控日志格式
   - 中文状态名映射规范

### Quickstart Guide (`quickstart.md`)

包含：
1. 配置项说明（新增的Maker模式相关配置）
2. 状态机流程图
3. 启动和测试步骤
4. 监控日志示例
5. 故障排查指南

### Agent Context Update

运行 `.specify/scripts/bash/update-agent-context.sh claude` 更新AI上下文，添加：
- Extended Maker模式相关技术栈
- 新增状态和状态转换逻辑
- 监控和日志要求

---

## Phase 2: Task Generation (由 /speckit.tasks 命令执行)

**Note**: Phase 2 tasks are NOT created by `/speckit.plan`. Use `/speckit.tasks` command to generate `tasks.md` after completing Phase 1.

## Implementation Strategy

### MVP Scope

**Phase 1 (Core功能)**:
1. 实现Extended Maker挂单功能（开仓+平仓）
2. 实现OPENING_MAKER_WAIT和CLOSING_MAKER_WAIT状态
3. 实现LIGHTER_HEDGING状态
4. 实现价差保护机制
5. 实现基本监控日志（中文）

**Phase 2 (优化功能)**:
1. 实现价格位置优化（自动重挂）
2. 实现连续重挂次数限制
3. 完善监控日志（所有监控指标）
4. 单元测试和集成测试

### Implementation Order

**顺序依赖关系**：
1. 数据模型扩展（models.py）→ 状态机扩展（spread_arb_bot.py）
2. Extended客户端Maker订单API（extended.py）→ 交易执行器改造（trade_executor.py）
3. 新增监控器模块（price_monitor.py, maker_order_monitor.py）→ 状态机集成
4. 状态机逻辑改造（spread_arb_bot.py）→ 测试验证
5. 日志系统完善 → 文档更新

### Risk Mitigation

**风险1**：Extended Maker订单成交率低（<80%）
- 缓解：配置合理的价格位置优化策略
- 应对：允许更长的等待时间，保持耐心等待最佳价格

**风险2**：WebSocket连接不稳定导致监控失效
- 缓解：实现WebSocket断线重连机制
- 应对：添加REST API备份查询

**风险3**：部分成交场景复杂导致状态混乱
- 缓解：严格的状态转换逻辑和仓位验证
- 应对：完善的回滚机制和风控暂停

**风险4**：价差保护触发过于频繁导致错失机会
- 缓解：配置合理的价差监控频率（0.5秒）和容忍度
- 应对：添加价差波动容忍度参数，避免频繁触发

### Rollback Plan

如果Maker模式测试失败：
- 可以通过配置项快速切换回Taker模式
- 保留现有Taker模式代码路径作为备份
- 状态机设计支持两种模式共存（通过配置开关）

## Success Criteria Verification

实施完成后必须验证以下成功标准：

- ✅ SC-001: Extended手续费接近0%（通过交易统计验证）
- ✅ SC-002: 价格偏离检测 < 5秒
- ✅ SC-003: Maker订单成交率 >= 80%
- ✅ SC-005: 价差保护响应 < 1秒
- ✅ SC-006: 部分成交对冲误差 < 0.001 ETH
- ✅ SC-008: 状态转换延迟 < 100ms
- ✅ SC-009: 监控循环处理 < 50ms
- ✅ SC-010: 对冲订单执行成功率 >= 99%
- ✅ SC-011: 状态转换日志延迟 < 100ms
- ✅ SC-012: 监控日志输出延迟 < 100ms
- ✅ SC-013: 关键事件日志完整性 = 100%

---

**Plan Created**: 2026-01-18
**Next Steps**: Execute Phase 0 research tasks, then proceed to Phase 1 design & contracts
