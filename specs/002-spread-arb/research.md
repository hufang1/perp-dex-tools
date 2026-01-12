# 研究文档：Lighter-Extended 单向价差收敛套利系统

**功能**: 002-spread-arb | **日期**: 2026-01-12

## 研究概述

本文档记录了为 Lighter-Extended 单向价差收敛套利系统进行的技术研究和最佳实践分析。

## 技术选型决策

### 1. 编程语言与版本

**决策**: Python 3.10+

**理由**:
- 现有代码库完全基于 Python
- 已有所有必需的交易所 SDK（Lighter SDK、Extended SDK）
- Python 的异步编程支持（asyncio）非常适合处理并发 WebSocket 连接
- 现有的 `exchanges/` 和 `hedge/` 模块提供了可直接复用的基础设施

**考虑的替代方案**:
- Go: 性能更好，但需要重写所有交易所集成
- Rust: 内存安全和高性能，但开发周期长，与现有代码不兼容

### 2. 主要依赖库

**决策**: 基于现有代码栈，新增以下核心库

| 库名 | 版本 | 用途 |
|------|------|------|
| lighter-sdk | 0.1.4 | Lighter 交易所 API 集成（已存在） |
| x10-python-trading-starknet | 0.0.10 | Extended 交易所 API 集成（已存在） |
| websockets | 12.0+ | WebSocket 连接管理（已存在） |
| aiohttp | 3.8+ | 异步 HTTP 客户端（已存在） |
| tenacity | 9.1.2+ | 重试逻辑（已存在） |
| python-dotenv | 1.0.0+ | 环境变量管理（已存在） |

**理由**: 所有依赖已通过验证，无需引入新的外部依赖，降低系统复杂度。

### 3. 存储方案

**决策**: 文件系统 + 内存状态

**理由**:
- 持仓状态和交易日志可以持久化为 JSON/CSV 文件
- 订单簿数据仅存在于内存中，WebSocket 断线重连后重建
- 不需要复杂的数据库系统，保持系统简单

**数据文件**:
- `logs/spread_arb_trades.csv`: 交易历史记录
- `logs/spread_arb_state.json`: 系统状态快照（用于重启恢复）

### 4. 测试框架

**决策**: pytest + pytest-asyncio

**理由**:
- Python 生态中标准的异步测试框架
- 支持 fixture 和参数化测试
- 可以模拟 WebSocket 消息和交易所响应

**测试类型**:
- 单元测试: VWAP 计算、价差计算、风控逻辑
- 集成测试: WebSocket 连接、订单流程
- 模拟测试: 使用模拟数据验证套利逻辑

### 5. 目标平台

**决策**: Linux 服务器（云基础设施）

**理由**:
- 交易系统需要 24/7 运行
- 需要稳定的网络连接和低延迟
- 可部署为容器或虚拟机

### 6. 项目类型

**决策**: 单项目架构（Python 应用程序）

**理由**:
- 套利机器人是独立的应用程序
- 无需前后端分离
- 可以作为命令行工具运行

### 7. 性能目标

**决策**:
- 延迟: 价差检测 < 100ms，订单发送 < 1s
- 并发: 同时处理 2 个 WebSocket 连接
- 内存: < 500MB
- CPU: 单核足够（异步 I/O 密集型）

**理由**: 基于规格说明中的成功标准（SC-001, SC-002, SC-003, SC-004）

### 8. 约束条件

**决策**:
- 网络延迟: < 500ms（正常条件）
- 订单簿深度: 至少支持目标交易数量
- 单边成交超时: 3 秒
- 极端价差阈值: 5%
- WebSocket 重连: 自动重连，指数退避

**理由**: 基于规格说明中的假设和需求

### 9. 规模与范围

**决策**:
- 交易所数量: 2 个（Lighter + Extended）
- 交易对: 单一交易对（可配置，如 BTC-USD）
- 并发套利: 1 个活跃套利循环
- 代码规模: 预计 2000-3000 行

**理由**: 单向套利策略，专注单一场景，保持系统简单

## 架构设计研究

### 系统架构模式

**决策**: 事件驱动架构（Event-Driven Architecture）

**理由**:
- WebSocket 消息是自然的事件源
- 订单更新、价格更新都是异步事件
- 便于解耦和扩展

**组件划分**:
1. **WebSocket 管理器**: 处理两个交易所的连接和消息
2. **订单簿管理器**: 维护订单簿状态，计算 VWAP
3. **价差监控器**: 计算价差，触发开仓/平仓
4. **交易执行器**: 发送订单，处理订单更新
5. **风控管理器**: 检测异常，执行保护措施
6. **状态管理器**: 维护持仓状态，持久化状态

### 并发模型

**决策**: asyncio 协程并发

**理由**:
- Python 的原生异步支持
- 单线程事件循环，避免 GIL 问题
- 非常适合 I/O 密集型的交易系统

**并发模式**:
- 2 个 WebSocket 连接并发运行
- 订单发送使用 `asyncio.gather()` 确保原子性
- 超时保护使用 `asyncio.wait_for()`

### 错误处理策略

**决策**: 分层错误处理 + 重试机制

**层级**:
1. **网络层**: WebSocket 断线 → 自动重连（指数退避）
2. **API 层**: API 调用失败 → 使用 tenacity 重试（最多 3 次）
3. **业务层**: 单边成交 → 强平保护
4. **数据层**: 订单簿不一致 → 重新获取快照

## 现有代码复用分析

### 可复用的模块

1. **exchanges/base.py**: 基础交易所客户端接口
2. **exchanges/lighter.py**: Lighter 交易所客户端（完整实现）
3. **exchanges/extended.py**: Extended 交易所客户端（完整实现）
4. **exchanges/lighter_custom_websocket.py**: 自定义 Lighter WebSocket 实现
5. **helpers/logger.py**: 交易日志记录器
6. **hedge/hedge_mode_ext.py**: 对冲模式参考实现

### 需要新建的模块

1. **spread_arb/spread_arb_bot.py**: 主套利机器人
2. **spread_arb/order_book_manager.py**: 订单簿管理器
3. **spread_arb/spread_calculator.py**: 价差计算器
4. **spread_arb/risk_manager.py**: 风控管理器
5. **spread_arb/state_manager.py**: 状态管理器

## 安全性考虑

### API 密钥管理

**决策**: 环境变量 + .env 文件（不提交到版本控制）

**必需的环境变量**:
```bash
API_KEY_PRIVATE_KEY=...
LIGHTER_ACCOUNT_INDEX=0
LIGHTER_API_KEY_INDEX=0
EXTENDED_VAULT=...
EXTENDED_STARK_KEY_PRIVATE=...
EXTENDED_STARK_KEY_PUBLIC=...
EXTENDED_API_KEY=...
```

### 限价保护

**决策**: 下单时附加限价保护

- Extended 买入: 不超过 Ask_1 × 1.005
- Lighter 卖出: 不低于 Bid_1 × 0.995
- 防止滑点过大导致不利成交

## 监控与日志

### 日志策略

**决策**: 结构化日志 + CSV 交易记录

**日志级别**:
- DEBUG: 订单簿更新详情
- INFO: 交易事件、状态变更
- WARNING: 网络问题、重试
- ERROR: 交易失败、异常情况

**交易日志格式** (CSV):
```csv
timestamp,exchange,side,price,quantity,spread,profit
```

### 监控指标

**决策**: 实时输出关键指标

- 当前价差
- 持仓状态
- 已完成套利次数
- 累计利润
- 订单簿深度

## 最佳实践总结

1. **使用现有的交易所客户端**: 不要重新实现与交易所的集成
2. **异步优先**: 所有 I/O 操作都使用 asyncio
3. **状态持久化**: 定期保存系统状态，支持重启恢复
4. **风控优先**: 任何异常情况优先保护资金安全
5. **简单架构**: 避免过度设计，保持代码可维护
6. **充分测试**: 使用模拟数据验证所有关键逻辑
7. **日志完整**: 记录所有交易事件，便于事后分析
8. **配置外部化**: 所有参数通过环境变量或配置文件管理

## 未解决的问题

无 - 所有技术决策已明确。
