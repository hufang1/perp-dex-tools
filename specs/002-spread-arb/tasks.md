# 任务列表：Lighter-Extended 单向价差收敛套利系统

**输入**: 来自 `/specs/002-spread-arb/` 的设计文档
**前置条件**: plan.md（必需）, spec.md（用户故事）, research.md, data-model.md, contracts/

**测试**: 规格说明建议补充完整的测试覆盖，因此包含测试任务。

**组织方式**: 任务按用户故事分组，以实现每个故事的独立实施和测试。

## 格式：`[ID] [P?] [Story] 描述`

- **[P]**: 可并行运行（不同文件，无依赖）
- **[Story]**: 任务所属的用户故事（US1, US2, US3）
- 描述中包含确切的文件路径

## 路径约定

- **单项目**: 仓库根目录下的 `spread/`, `tests/`
- 复用现有模块: `exchanges/`, `helpers/`

---

## 阶段 1：设置（共享基础设施）

**目的**: 项目初始化和基础结构

- [x] T001 创建 spread 模块目录结构
- [x] T002 创建 tests 目录结构（unit/, integration/）
- [x] T003 [P] 创建 logs 目录（用于日志和状态持久化）
- [x] T004 [P] 在 spread/__init__.py 中导出核心类
- [x] T005 [P] 创建 tests/__init__.py 测试配置文件

---

## 阶段 2：基础（阻塞性前置条件）

**目的**: 所有用户故事实施前必须完成的核心基础设施

**⚠️ 关键**: 此阶段完成前，不得开始任何用户故事的实施

- [x] T006 在 spread/models.py 中定义基础数据类（OrderBook, SpreadInfo, Position, BotStats, BotConfig）
- [x] T007 在 spread/exceptions.py 中定义自定义异常类
- [x] T008 [P] 在 spread/utils.py 中实现通用工具函数（VWAP 计算、价格验证等）
- [x] T009 配置日志系统在 helpers/logger.py 中（复用现有 TradingLogger）

**检查点**: 基础就绪 - 用户故事实施现在可以并行开始

---

## 阶段 3：用户故事 1 - 自动价差监控与开仓（优先级：P1）🎯 MVP

**目标**: 实现价差监控、VWAP 计算和自动开仓功能

**独立测试**: 通过模拟两个交易所的价格数据，验证系统能否正确计算价差并在满足条件时触发开仓订单

### 用户故事 1 的测试

> **注意：先编写这些测试，确保它们在实现前失败**

- [x] T010 [P] [US1] 在 tests/test_spread_calculator.py 中编写 VWAP 计算测试
- [ ] T011 [P] [US1] 在 tests/test_spread_calculator.py 中编写价差计算测试（开仓价差公式）
- [ ] T012 [P] [US1] 在 tests/test_spread_calculator.py 中编写开仓阈值判断测试
- [ ] T013 [P] [US1] 在 tests/integration/test_open_position_flow.py 中编写完整开仓流程集成测试

### 用户故事 1 的实现

- [x] T014 [P] [US1] 在 spread/order_book_manager.py 中实现 OrderBook 类（订单簿数据结构和验证）
- [x] T015 [P] [US1] 在 spread/order_book_manager.py 中实现 OrderBook.calculate_vwap() 方法
- [x] T016 [US1] 在 spread/order_book_manager.py 中实现 OrderBookManager 类（管理两个交易所订单簿）
- [x] T017 [US1] 在 spread/order_book_manager.py 中实现 OrderBookManager.start() WebSocket 连接方法（复用现有 lighter.py 和 extended.py）
- [x] T018 [P] [US1] 在 spread/spread_calculator.py 中实现 SpreadCalculator 类
- [x] T019 [US1] 在 spread/spread_calculator.py 中实现 SpreadCalculator.calculate_open_spread() 方法（依赖 T016）
- [x] T020 [US1] 在 spread/spread_calculator.py 中实现 SpreadCalculator.should_open() 判断方法
- [x] T021 [P] [US1] 在 spread/trade_executor.py 中实现 TradeExecutor 类
- [x] T022 [US1] 在 spread/trade_executor.py 中实现 TradeExecutor.execute_open_position() 方法（并发发送订单）
- [x] T023 [US1] 在 spread/trade_executor.py 中实现 TradeExecutor.wait_for_execution() 方法（超时保护）
- [x] T024 [US1] 在 spread/state_manager.py 中实现 StateManager 类（状态持久化）
- [x] T025 [US1] 在 spread/spread_arb_bot.py 中实现 SpreadArbBot 主控制器类
- [x] T026 [US1] 在 spread/spread_arb_bot.py 中实现 SpreadArbBot.run_trading_loop() 主交易循环（价差监控逻辑）
- [x] T027 [US1] 在 spread/spread_arb_bot.py 中添加开仓流程的日志记录

**检查点**: 此时，用户故事 1 应该完全功能化且可独立测试

---

## 阶段 4：用户故事 2 - 持仓监控与平仓（优先级：P2）

**目标**: 实现持仓状态管理和价差收敛时的自动平仓功能

**独立测试**: 通过模拟持仓状态下的价差变化，验证系统能否在价差收敛时正确触发平仓

### 用户故事 2 的测试

- [x] T028 [P] [US2] 在 tests/test_spread_calculator.py 中编写平仓价差计算测试
- [x] T029 [P] [US2] 在 tests/test_spread_calculator.py 中编写平仓条件判断测试（价差收敛逻辑）
- [x] T030 [P] [US2] 在 tests/integration/test_close_position_flow.py 中编写完整平仓流程集成测试

### 用户故事 2 的实现

- [x] T031 [US2] 在 spread/spread_calculator.py 中实现 SpreadCalculator.calculate_close_spread() 方法（依赖 T016）
- [x] T032 [US2] 在 spread/spread_calculator.py 中实现 SpreadCalculator.should_close() 判断方法
- [x] T033 [P] [US2] 在 spread/trade_executor.py 中实现 TradeExecutor.execute_close_position() 方法（并发发送平仓订单）
- [x] T034 [US2] 在 spread/spread_arb_bot.py 中扩展 SpreadArbBot 添加持仓监控逻辑（依赖 T024, T032）
- [x] T035 [US2] 在 spread/spread_arb_bot.py 中实现平仓流程的状态转换（HOLDING → CLOSING → IDLE）
- [x] T036 [US2] 在 spread/spread_arb_bot.py 中添加利润计算和统计更新（依赖 T006 中的 BotStats）
- [x] T037 [US2] 在 spread/spread_arb_bot.py 中添加平仓流程的日志记录

**检查点**: 此时，用户故事 1 和 2 都应该独立工作

---

## 阶段 5：用户故事 3 - 风险控制与异常处理（优先级：P3）

**目标**: 实现单边成交保护、余额检查、极端价差过滤等风控机制

**独立测试**: 通过模拟各种异常场景，验证系统能否正确识别并采取保护措施

### 用户故事 3 的测试

- [x] T038 [P] [US3] 在 tests/test_risk_manager.py 中编写余额检查测试
- [x] T039 [P] [US3] 在 tests/test_risk_manager.py 中编写深度验证测试
- [x] T040 [P] [US3] 在 tests/test_risk_manager.py 中编写极端价差过滤测试（> 5% 阈值）
- [x] T041 [P] [US3] 在 tests/test_risk_manager.py 中编写单边成交超时测试（3 秒超时）
- [x] T042 [P] [US3] 在 tests/integration/test_risk_scenarios.py 中编写风控场景集成测试

### 用户故事 3 的实现

- [x] T043 [P] [US3] 在 spread/risk_manager.py 中实现 RiskManager 类
- [x] T044 [US3] 在 spread/risk_manager.py 中实现 RiskManager.validate_open_position() 方法（余额、深度、价差合理性检查，依赖 T016）
- [x] T045 [US3] 在 spread/risk_manager.py 中实现 RiskManager.check_balance() 方法（交易所余额查询）
- [x] T046 [US3] 在 spread/risk_manager.py 中实现 RiskManager.is_spread_reasonable() 方法（极端价差检测）
- [x] T047 [US3] 在 spread/trade_executor.py 中实现 TradeExecutor.rollback_position() 强平方法（单边成交保护）
- [x] T048 [US3] 在 spread/spread_arb_bot.py 中集成 RiskManager 到开仓流程（依赖 T044, T022）
- [x] T049 [US3] 在 spread/spread_arb_bot.py 中集成 RiskManager 到平仓流程（依赖 T044, T033）
- [x] T050 [US3] 在 spread/spread_arb_bot.py 中实现单边成交检测和强平逻辑（依赖 T047）
- [x] T051 [US3] 在 spread/order_book_manager.py 中实现序列号验证逻辑（数据完整性检查，依赖 T016）
- [x] T052 [US3] 在 spread/order_book_manager.py 中实现订单簿不一致时的快照重新获取（依赖 T051）
- [x] T053 [US3] 在 spread/spread_arb_bot.py 中添加风控事件的日志记录和警告

**检查点**: 所有用户故事现在都应该独立功能化

---

## 阶段 6：完善与跨领域关注点

**目的**: 影响多个用户故事的改进

- [x] T054 [P] 在 tests/integration/test_e2e_spread_arb.py 中编写端到端套利流程测试（完整开仓-平仓循环）
- [x] T055 [P] 在 spread/spread_arb_bot.py 中实现命令行参数解析（argparse，支持配置覆盖）
- [x] T056 [P] 在 spread/spread_arb_bot.py 中实现信号处理（优雅关闭 SIGINT/SIGTERM）
- [x] T057 添加环境变量验证（启动时检查必需的 API 密钥）
- [x] T058 [P] 代码清理和重构（移除重复代码，优化导入）
- [x] T059 性能优化（减少不必要的计算，优化 WebSocket 消息处理）
- [x] T060 运行 quickstart.md 验证（按照快速开始指南测试完整安装和运行流程）

---

## 依赖关系与执行顺序

### 阶段依赖关系

- **设置（阶段 1）**: 无依赖 - 可立即开始
- **基础（阶段 2）**: 依赖设置完成 - 阻塞所有用户故事
- **用户故事（阶段 3-5）**: 都依赖基础阶段完成
  - 用户故事可以并行进行（如果有人力）
  - 或按优先级顺序进行（P1 → P2 → P3）
- **完善（阶段 6）**: 依赖所有期望的用户故事完成

### 用户故事依赖关系

- **用户故事 1 (P1)**: 基础完成后可开始 - 无其他故事依赖
- **用户故事 2 (P2)**: 基础完成后可开始 - 与 US1 集成但应独立可测试
- **用户故事 3 (P3)**: 基础完成后可开始 - 与 US1/US2 集成但应独立可测试

### 各用户故事内部

- 测试（如包含）必须先编写并失败
- 模型在服务之前
- 服务在端点之前
- 核心实现在集成之前
- 故事完成后进入下一个优先级

### 并行机会

- 阶段 1 中所有标记 [P] 的任务可并行运行
- 阶段 2 中所有标记 [P] 的任务可并行运行（阶段 2 内）
- 基础阶段完成后，所有用户故事可并行开始（如果团队容量允许）
- 用户故事中所有标记 [P] 的测试可并行运行
- 故事中标记 [P] 的模型可并行运行
- 不同用户故事可由不同团队成员并行工作

---

## 并行示例：用户故事 1

```bash
# 一起启动用户故事 1 的所有测试：
Task: "在 tests/test_spread_calculator.py 中编写 VWAP 计算测试"
Task: "在 tests/test_spread_calculator.py 中编写价差计算测试（开仓价差公式）"
Task: "在 tests/test_spread_calculator.py 中编写开仓阈值判断测试"
Task: "在 tests/integration/test_open_position_flow.py 中编写完整开仓流程集成测试"

# 一起启动用户故事 1 的所有模型：
Task: "在 spread/order_book_manager.py 中实现 OrderBook 类（订单簿数据结构和验证）"
Task: "在 spread/spread_calculator.py 中实现 SpreadCalculator 类"
```

---

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：设置
2. 完成阶段 2：基础（关键 - 阻塞所有故事）
3. 完成阶段 3：用户故事 1
4. **停止并验证**: 独立测试用户故事 1
5. 如就绪则部署/演示

### 增量交付

1. 完成设置 + 基础 → 基础就绪
2. 添加用户故事 1 → 独立测试 → 部署/演示（MVP！）
3. 添加用户故事 2 → 独立测试 → 部署/演示
4. 添加用户故事 3 → 独立测试 → 部署/演示
5. 每个故事增加价值而不破坏之前的故事

### 并行团队策略

多名开发者时：

1. 团队一起完成设置 + 基础
2. 基础完成后：
   - 开发者 A：用户故事 1
   - 开发者 B：用户故事 2
   - 开发者 C：用户故事 3
3. 故事独立完成并集成

---

## 任务摘要

| 类别 | 任务数量 |
|------|---------|
| 设置 | 5 |
| 基础 | 4 |
| 用户故事 1 | 18 |
| 用户故事 2 | 10 |
| 用户故事 3 | 16 |
| 完善 | 7 |
| **总计** | **60** |

### 按用户故事分解

| 用户故事 | 任务数量 | 并行机会 |
|---------|---------|---------|
| US1 - 价差监控与开仓 | 18 | 10 个可并行 |
| US2 - 持仓监控与平仓 | 10 | 3 个可并行 |
| US3 - 风险控制 | 16 | 7 个可并行 |

### 建议的 MVP 范围

**最小可行产品（MVP）** = 阶段 1 + 阶段 2 + 阶段 3（用户故事 1）

- 包含：基础设置 + 订单簿管理 + 价差计算 + 开仓执行
- 可独立测试和演示
- 提供核心价值：自动检测价差并执行开仓
- 不依赖其他用户故事

---

## 备注

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以实现可追溯性
- 每个用户故事应独立可完成和测试
- 实施前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同文件冲突、破坏独立性的跨故事依赖
