# 实现计划：双腿并发交易重构

**分支**: `012-dual-leg-concurrency` | **日期**: 2026-01-11 | **规格**: [spec.md](./spec.md)
**输入**: 功能规格说明书 `/specs/012-dual-leg-concurrency/spec.md`

## 摘要

本功能旨在重构价差套利系统的执行层，将当前串行交易模式（Extended下单 → 等待成交 → Lighter对冲，延迟12秒+）改造为双腿并发IOC模式（目标延迟<500ms）。主要变更包括：

1. **并发执行**：使用asyncio.gather同时向两个交易所发送IOC订单
2. **IOC订单**：替换限价单+轮询等待为立即成交或撤销机制
3. **快速回滚**：单腿持仓1秒内市价平仓
4. **极简平仓**：移除复杂P1-P5系统，基于净价差止盈止损
5. **利润检查**：开仓前严格验证扣除所有成本后的净利

## 技术上下文

**语言/版本**: Python 3.11+
**主要依赖**: asyncio, websockets, decimal.Decimal, logging, pytest
**存储**: 内存状态存储 + 文件日志（logs/trade.log）+ CSV导出（data/）
**测试**: pytest + pytest-asyncio（单元测试和集成测试）
**目标平台**: Linux服务器（运行价差套利机器人）
**项目类型**: 单项目（单一Python包）
**性能目标**:
- 并发订单发送时间差 < 5ms
- 单次交易执行时间 < 500ms
- 单腿回滚平仓 < 1秒
**约束**:
- 小资金环境（35U）
- 微利价差（0.07%）
- 双边Taker费率总和必须 < 0.05%
**规模/范围**:
- 修改 spread/bot.py 核心交易逻辑
- 增强现有模块（ConcurrentExecutor, IocOrderManager, RiskValidator）
- 新增单腿回滚处理器
- 简化平仓逻辑

## 章程检查

*门控：必须在Phase 0研究前通过。Phase 1设计后重新检查。*

### 原则遵守情况

| 原则 | 状态 | 说明 |
|------|------|------|
| 代码质量 | ✅ | 使用Decimal进行金融计算，异步IO模式，遵循现有代码风格 |
| 测试优先 | ⚠️ | 需要为新增和修改的模块添加单元测试和集成测试 |
| 日志可观测 | ✅ | 使用logging模块，详细记录决策过程和异常情况 |
| 简化原则 | ✅ | 移除复杂P1-P5系统，使用简单的价差阈值判断 |

### 需要注意的约束

1. **不得破坏现有功能**：修改核心bot.py时需保持向后兼容
2. **性能关键路径**：交易执行路径必须优化，避免不必要的IO操作
3. **风险控制**：单腿回滚是最后防线，必须可靠执行

## 项目结构

### 文档结构（本功能）

```text
specs/012-dual-leg-concurrency/
├── plan.md              # 本文件（/speckit.plan命令输出）
├── research.md          # Phase 0输出（/speckit.plan命令）
├── data-model.md        # Phase 1输出（/speckit.plan命令）
├── quickstart.md        # Phase 1输出（/speckit.plan命令）
├── contracts/           # Phase 1输出（/speckit.plan命令）
│   └── api.md           # API契约文档
└── tasks.md             # Phase 2输出（/speckit.tasks命令 - 非本阶段创建）
```

### 源代码结构（仓库根）

```text
spread/                         # 价差套利核心模块
├── bot.py                      # [主要修改] 主交易引擎
├── order_manager.py            # [修改] Extended订单管理（移除wait_for_fill）
├── hedge_manager.py            # [修改] Lighter对冲管理（支持并发）
├── concurrent_executor.py      # [已存在] 并发执行器（011-async-ws-ioc-trading）
├── ioc_order_manager.py        # [已存在] IOC订单管理器（011-async-ws-ioc-trading）
├── risk_validator.py           # [已存在] 风控验证器（011-async-ws-ioc-trading）
├── performance_monitor.py      # [已存在] 性能监控器（011-async-ws-ioc-trading）
├── websocket_manager.py        # [已存在] WebSocket管理器（011-async-ws-ioc-trading）
├── leg_rollback_handler.py     # [新增] 单腿回滚处理器
├── simple_close_strategy.py    # [新增] 极简平仓策略
└── config.py                   # [修改] 新增配置项

exchanges/                       # 交易所客户端
├── extended.py                 # [可能需要调整] 确认IOC订单支持
└── lighter_custom_websocket.py # [可能需要调整] 确认IOC订单支持

tests/                          # 测试文件
├── test_dual_leg_concurrent.py # [新增] 并发执行测试
├── test_ioc_order_pricing.py   # [新增] IOC订单定价测试
├── test_leg_rollback.py        # [新增] 单腿回滚测试
├── test_profit_check.py        # [新增] 利润检查测试
├── test_simple_close.py        # [新增] 极简平仓测试
└── integration/
    └── test_dual_leg_integration.py # [新增] 端到端集成测试
```

**结构决策**: 单项目结构（选项1）。所有交易逻辑在spread/包中，测试文件分离，保持现有代码组织方式。

## 复杂度跟踪

> **仅当章程检查有需要证明的违规时填写**

| 违规 | 为何需要 | 更简单的替代方案被拒绝的原因 |
|------|---------|------------------------------|
| 新增单腿回滚处理器 | 风控需求：单腿持仓必须在1秒内平仓 | 直接嵌入bot.py会使代码过长，分离便于测试和维护 |
| 新增极简平仓策略 | 需求明确要求移除复杂P1-P5系统 | 保持现有复杂系统会违反"简化原则"，且响应速度不够快 |

## Phase 0: 研究与技术决策

### 研究任务

| 任务 | 描述 | 状态 |
|------|------|------|
| R1 | 确认Extended和Lighter交易所IOC订单API支持 | 待研究 |
| R2 | 评估asyncio.gather并发执行的延迟精度 | 待研究 |
| R3 | 研究市价平仓API的实现和响应时间 | 待研究 |
| R4 | 分析现有011-async-ws-ioc-trading模块的可用性 | 待研究 |
| R5 | 确定最佳滑点容错值范围（0.03%-0.05%） | 待研究 |

### 技术决策

| 决策点 | 选择 | 理由 | 备选方案 |
|--------|------|------|----------|
| 并发模式 | asyncio.gather | Python原生支持，符合现有代码架构 | threading（不适用于异步IO） |
| IOC订单实现 | 复用IocOrderManager | 011-async-ws-ioc-trading已实现基础功能 | 新建独立模块 |
| 回滚机制 | 新增LegRollbackHandler | 分离关注点，便于测试和复用 | 嵌入bot.py |
| 配置管理 | 扩展SpreadArbConfig | 保持现有配置方式 | 新增独立配置文件 |

## Phase 1: 设计与合约

### 数据模型设计

详见 [data-model.md](./data-model.md)

关键实体：
- `ConcurrentOrderResult`: 并发订单执行结果
- `LegRollbackEvent`: 单腿回滚事件
- `SimpleCloseDecision`: 极简平仓决策

### API契约

详见 [contracts/api.md](./contracts/api.md)

主要接口：
- `ConcurrentExecutor.execute_dual_leg_orders()`: 双腿并发下单
- `LegRollbackHandler.execute_emergency_close()`: 紧急回滚平仓
- `SimpleCloseStrategy.should_close()`: 极简平仓判断

### 快速开始

详见 [quickstart.md](./quickstart.md)

## Phase 2: 实施任务分解

**注意**: 本阶段由 `/speckit.tasks` 命令生成，不在本计划范围。

## 依赖与风险

### 外部依赖

1. **交易所API文档**：需确认IOC订单的精确参数和响应格式
2. **WebSocket稳定性**：实时数据流必须可靠，否则影响时效性检查

### 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| IOC订单API不兼容 | 高 | 需要在Phase 0研究阶段确认，准备备选方案 |
| 并发延迟精度不足 | 高 | 使用高精度时间戳，添加性能监控 |
| 回滚失败 | 高 | 多重重试机制，告警通知 |
| 网络抖动 | 中 | 滑点容错设计，数据时效性检查 |

## 验收标准

对应规格中的成功标准：

- [ ] SC-001: 并发订单发送时间差 < 5ms
- [ ] SC-002: 单次交易执行时间 < 500ms
- [ ] SC-003: 单腿回滚 < 1秒
- [ ] SC-004: 正确拒绝负净利交易
- [ ] SC-005: 过期数据拒绝率100%
- [ ] SC-006: 移除P1-P5复杂逻辑
- [ ] SC-007: IOC订单使用率100%
- [ ] SC-008: 单腿损失可控

## 后续步骤

1. 执行 `/speckit.tasks` 生成详细任务分解
2. 按任务顺序实施开发
3. 编写单元测试和集成测试
4. 性能测试验证延迟目标
5. 模拟交易验证策略效果
