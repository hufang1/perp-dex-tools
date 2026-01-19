# 实施计划：价差套利系统改进

**分支**: `003-spreading-improvements` | **日期**: 2026-01-19 | **规格**: [spec.md](spec.md)

## 摘要

本功能是对现有 Lighter-Extended 价差套利系统的四项关键改进：

1. **修复重复挂单Bug** - 确保修改挂单价格时先取消旧订单，避免多个挂单同时存在
2. **阶梯价差开仓** - 实现递增式开仓阈值策略，优化资金使用效率
3. **双模式平仓逻辑** - 根据利润水平选择限价或市价平仓，最大化收益
4. **可用仓位检测系统** - 开仓前检查两个交易所余额，防止单边持仓风险

技术方法基于现有的 spread/ 模块架构，通过修改状态管理器、交易执行器和策略模块来实现这些改进。

## 技术上下文

**编程语言/版本**: Python 3.10+

**主要依赖**:
- lighter-sdk 0.1.4（Lighter 交易所 API）
- x10-python-trading-starknet 0.0.10（Extended 交易所 API）
- websockets 12.0+（WebSocket 连接）
- aiohttp 3.8+（异步 HTTP 客户端）
- tenacity 9.1.2+（重试逻辑）
- python-dotenv 1.0.0+（环境变量管理）

**存储**: 文件系统（JSON 状态文件 logs/spread_arb_state.json + CSV 交易日志）

**测试**: pytest + pytest-asyncio

**目标平台**: Linux 服务器（云基础设施）

**项目类型**: 单项目（Python 应用程序）

**性能目标**:
- 价差检测延迟: < 100ms
- 订单发送时间: < 1s
- 单边成交响应: < 500ms
- 内存使用: < 500MB
- 挂单修改响应: < 2s（包括取消订单）
- 市价平仓执行: < 500ms

**约束条件**:
- 网络延迟: < 500ms（正常条件）
- 取消订单操作: 持续重试直到成功
- 单边成交超时: 3 秒
- 极端价差阈值: 5%
- WebSocket 自动重连（指数退避）

**规模/范围**:
- 修改现有模块: spread/state_manager.py, spread/trade_executor.py, spread/arithmetic_open_strategy.py, spread/smart_close_strategy.py
- 新增模块: spread/balance_checker.py（可用仓位检测）
- 预计代码量: 500-800 行（修改 + 新增）

## 章程检查

*关卡：必须在阶段0研究前通过。阶段1设计后重新检查。*

当前项目未定义具体章程。基于通用软件工程最佳实践进行评估：

| 原则 | 状态 | 说明 |
|------|------|------|
| 代码复用 | ✅ 通过 | 基于现有 spread/ 模块进行改进 |
| 测试优先 | ⚠️ 部分通过 | 需要补充新增功能的单元测试 |
| 简单架构 | ✅ 通过 | 不引入新的架构层次，保持现有设计 |
| 可观察性 | ✅ 通过 | 完整的日志记录和错误处理 |
| 安全性 | ✅ 通过 | 现有安全机制保持不变 |

**结论**: 通过基本检查，建议在实施时补充完整的测试覆盖。

## 项目结构

### 文档结构（本功能）

```text
specs/003-spreading-improvements/
├── plan.md              # 本文件（/speckit.plan 命令输出）
├── research.md          # 阶段0输出
├── data-model.md        # 阶段1输出
├── quickstart.md        # 阶段1输出
├── contracts/
│   └── internal-api-contract.md  # 阶段1输出（模块间接口）
├── checklists/
│   └── requirements.md  # 需求检查清单
└── tasks.md             # 阶段2输出（/speckit.tasks 命令生成）
```

### 源代码结构（仓库根目录）

```text
spread/                              # 现有套利模块（修改）
├── __init__.py
├── spread_arb_bot.py               # 主控制器（需要修改）
├── state_manager.py                # 状态管理器（需要修改 - 支持新状态）
├── trade_executor.py               # 交易执行器（需要修改 - 挂单管理）
├── arithmetic_open_strategy.py     # 阶梯开仓策略（需要修改）
├── smart_close_strategy.py         # 智能平仓策略（需要修改）
├── maker_order_monitor.py          # Maker订单监控器（需要修改 - 验证取消）
├── balance_checker.py              # 新增：可用仓位检测器
├── models.py                       # 数据模型（需要扩展）
└── [其他现有文件保持不变...]

exchanges/                           # 现有模块（复用）
├── base.py                         # 基础交易所客户端接口
├── lighter.py                      # Lighter 客户端
├── lighter_custom_websocket.py    # Lighter WebSocket
└── extended.py                     # Extended 客户端

tests/                              # 测试目录（新增）
├── test_balance_checker.py         # 余额检测测试
├── test_tiered_opening.py          # 阶梯开仓测试
├── test_dual_mode_close.py         # 双模式平仓测试
└── integration/
    └── test_order_management.py    # 挂单管理集成测试

logs/                               # 运行时目录
├── spread_arb_YYYYMMDD.log        # 每日日志
├── spread_arb_trades.csv          # 交易记录
└── spread_arb_state.json          # 状态快照
```

**结构决策**: 选择单项目架构，因为这是对现有套利系统的改进，无需创建新的项目结构。在现有 `spread/` 模块基础上进行修改和扩展，保持代码组织的一致性。

## 实施阶段

### 阶段0：研究与技术分析

**输出**: research.md

需要研究的问题：
1. 如何在 maker_order_monitor.py 中验证订单已成功取消？
2. 如何在 arithmetic_open_strategy.py 中实现阶梯价差计算？
3. 如何从交易所 API 获取平均开仓成本？
4. 双模式平仓需要新增哪些状态？

### 阶段1：设计

**输出**: data-model.md, contracts/, quickstart.md

需要设计的内容：
1. 新增的数据模型（BalanceCheckResult, TieredOpeningConfig 等）
2. 模块间接口契约（BalanceChecker, TradeExecutor 扩展）
3. 状态转换图（包含市价平仓和限价平仓）

### 阶段2：任务分解（下一步）

**命令**: `/speckit.tasks`

将生成详细的任务列表，包括：
1. 修复重复挂单Bug的任务
2. 实现阶梯价差开仓的任务
3. 实现双模式平仓逻辑的任务
4. 实现可用仓位检测系统的任务
5. 测试和集成任务

## 复杂度追踪

无需填写 - 无章程违规需要说明。

## 关键里程碑

1. **M1: 重复挂单Bug修复** - 确保取消订单验证机制工作正常
2. **M2: 阶梯开仓实现** - 完成阶梯价差计算和阈值管理
3. **M3: 双模式平仓** - 完成市价/限价平仓状态机和逻辑
4. **M4: 余额检测** - 完成开仓前余额检查功能
5. **M5: 集成测试** - 端到端验证所有改进功能

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 取消订单验证失败 | 高 | 持续重试直到取消成功，记录详细日志 |
| 阶梯开仓阈值计算错误 | 中 | 单元测试覆盖各种开仓次数场景 |
| 交易所API不提供平均成本 | 中 | 使用本地记录的加权平均作为降级策略 |
| 余额检测失败导致单边持仓 | 高 | 在发送任何订单前执行检测，失败则跳过 |
| 双模式平仓状态混乱 | 高 | 明确的状态转换图，充分测试 |

## 下一步行动

1. 完成 research.md，研究技术细节
2. 完成 data-model.md，设计数据模型
3. 完成 contracts/，定义模块接口
4. 完成 quickstart.md，编写快速开始指南
5. 运行 `/speckit.tasks` 生成详细任务列表
6. 按优先级实施任务（P1 → P2 → P3）

---

**文档版本**: 1.0 | **最后更新**: 2026-01-19
