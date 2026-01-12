# 实施计划：Lighter-Extended 单向价差收敛套利系统

**分支**: `002-spread-arb` | **日期**: 2026-01-12 | **规格**: [spec.md](spec.md)

## 摘要

本功能实现一个 Lighter-Extended 交易所之间的单向价差收敛套利系统。系统通过 WebSocket 实时监控两个交易所的订单簿，基于 VWAP（成交量加权平均价）计算价差，当价差满足阈值时自动执行开仓/平仓操作。核心组件包括订单簿管理器、价差计算器、风控管理器和状态管理器，采用事件驱动架构和 asyncio 异步编程模型。

## 技术上下文

**编程语言/版本**: Python 3.10+

**主要依赖**:
- lighter-sdk 0.1.4（Lighter 交易所 API）
- x10-python-trading-starknet 0.0.10（Extended 交易所 API）
- websockets 12.0+（WebSocket 连接）
- aiohttp 3.8+（异步 HTTP 客户端）
- tenacity 9.1.2+（重试逻辑）
- python-dotenv 1.0.0+（环境变量管理）

**存储**: 文件系统（JSON 状态文件 + CSV 交易日志）

**测试**: pytest + pytest-asyncio

**目标平台**: Linux 服务器（云基础设施）

**项目类型**: 单项目（Python 应用程序）

**性能目标**:
- 价差检测延迟: < 100ms
- 订单发送时间: < 1s
- 单边成交响应: < 500ms
- 内存使用: < 500MB
- 连续运行: 24 小时无故障

**约束条件**:
- 网络延迟: < 500ms（正常条件）
- 单边成交超时: 3 秒
- 极端价差阈值: 5%
- WebSocket 自动重连（指数退避）

**规模/范围**:
- 交易所数量: 2 个（Lighter + Extended）
- 交易对: 单一（可配置）
- 并发套利: 1 个活跃循环
- 预计代码量: 2000-3000 行

## 章程检查

*关卡：必须在阶段0研究前通过。阶段1设计后重新检查。*

当前项目未定义具体章程。基于通用软件工程最佳实践进行评估：

| 原则 | 状态 | 说明 |
|------|------|------|
| 代码复用 | ✅ 通过 | 复用现有的 `exchanges/` 模块和 `helpers/` 工具 |
| 测试优先 | ⚠️ 部分通过 | 需要补充单元测试和集成测试 |
| 简单架构 | ✅ 通过 | 采用事件驱动架构，避免过度设计 |
| 可观察性 | ✅ 通过 | 完整的日志记录和交易历史 |
| 安全性 | ✅ 通过 | API 密钥通过环境变量管理，限价保护 |

**结论**: 通过基本检查，建议在实施时补充完整的测试覆盖。

## 项目结构

### 文档结构（本功能）

```text
specs/002-spread-arb/
├── plan.md              # 本文件（/speckit.plan 命令输出）
├── research.md          # 阶段0输出
├── data-model.md        # 阶段1输出
├── quickstart.md        # 阶段1输出
├── contracts/
│   └── api-contract.md  # 阶段1输出
├── checklists/
│   └── requirements.md  # 需求检查清单
└── tasks.md             # 阶段2输出（/speckit.tasks 命令生成）
```

### 源代码结构（仓库根目录）

```text
spread_arb/                          # 新建套利模块
├── __init__.py
├── spread_arb_bot.py               # 主控制器
├── order_book_manager.py           # 订单簿管理器
├── spread_calculator.py            # 价差计算器
├── risk_manager.py                 # 风控管理器
└── state_manager.py                # 状态管理器

exchanges/                           # 现有模块（复用）
├── base.py                         # 基础交易所客户端接口
├── lighter.py                      # Lighter 客户端
├── lighter_custom_websocket.py    # Lighter WebSocket
└── extended.py                     # Extended 客户端

helpers/                            # 现有模块（复用）
├── logger.py                       # 交易日志记录器
└── telegram_bot.py                 # Telegram 通知（可选）

tests/                              # 新建测试目录
├── __init__.py
├── test_spread_calculator.py       # 价差计算测试
├── test_risk_manager.py            # 风控测试
├── test_order_book_manager.py      # 订单簿测试
└── integration/
    └── test_spread_arb_flow.py     # 集成测试

logs/                               # 运行时目录
├── spread_arb_YYYYMMDD.log        # 每日日志
├── spread_arb_trades.csv          # 交易记录
└── spread_arb_state.json          # 状态快照
```

**结构决策**: 选择单项目架构，因为套利机器人是独立运行的 Python 应用程序，无需前后端分离。新增 `spread_arb/` 模块存放套利逻辑，复用现有的 `exchanges/` 和 `helpers/` 模块，保持代码组织的一致性。

## 实施阶段

### 阶段0：研究与技术分析 ✅

**输出**: [research.md](research.md)

已完成的决策：
- Python 3.10+ 作为编程语言
- 事件驱动架构 + asyncio 异步编程
- 文件系统存储（JSON + CSV）
- pytest 测试框架
- 复用现有交易所客户端

### 阶段1：设计 ✅

**输出**: [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

已完成的设计：
- 10 个核心数据实体（OrderBook、Position、SpreadInfo 等）
- 6 个主要组件接口（OrderBookManager、SpreadCalculator、RiskManager 等）
- 完整的快速开始指南

### 阶段2：任务分解（下一步）

**命令**: `/speckit.tasks`

将生成详细的任务列表，包括：
- 模块实现任务
- 测试编写任务
- 集成和部署任务

## 复杂度追踪

无需填写 - 无章程违规需要说明。

## 关键里程碑

1. **M1: 核心模块实现** - 完成 6 个主要组件
2. **M2: 集成测试** - 端到端套利流程验证
3. **M3: 实盘测试** - 小资金试运行 1-2 周
4. **M4: 生产部署** - 正式运行并监控

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 单边成交 | 高 | 3 秒超时 + 自动强平 |
| 订单簿数据不一致 | 中 | 序列号验证 + 快照重获取 |
| 网络延迟 | 中 | 指数退避重连 + WebSocket 保活 |
| 极端市场波动 | 中 | 5% 价差阈值保护 |
| 余额不足 | 低 | 交易前检查 + Telegram 通知 |

## 下一步行动

1. 运行 `/speckit.tasks` 生成详细任务列表
2. 按优先级实施任务（P1 → P2 → P3）
3. 完成单元测试和集成测试
4. 进行模拟交易测试
5. 小资金实盘验证

---

**文档版本**: 1.0 | **最后更新**: 2026-01-12
