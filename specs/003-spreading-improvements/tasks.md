# Tasks: 价差套利系统改进

**Input**: Design documents from `/specs/003-spreading-improvements/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 包含测试任务以确保代码质量

**Organization**: 任务按用户故事分组，支持独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 任务所属用户故事（US1, US2, US3, US4）
- 包含精确文件路径

## Path Conventions

- **单项目**: `spread/`, `tests/` 位于仓库根目录
- **修改现有文件**: 扩展现有模块
- **新增文件**: 创建新模块

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基础结构

- [X] T001 确认现有 spread/ 模块结构完整
- [X] T002 [P] 创建测试目录结构 tests/unit/ 和 tests/integration/
- [X] T003 [P] 配置 pytest 和 pytest-asyncio 测试环境
- [X] T004 [P] 备份现有状态文件 logs/spread_arb_state.json

---

## Phase 2: Foundational (阻塞前提条件)

**目的**: 所有用户故事依赖的核心基础设施

**⚠️ 关键**: 完成此阶段前不能开始任何用户故事的实现

- [X] T005 在 spread/models.py 中添加 CancelOrderResult 数据类
- [X] T006 在 spread/models.py 中添加 TieredOpeningState 数据类
- [X] T007 在 spread/models.py 中添加 CloseModeDecision 数据类
- [X] T008 在 spread/models.py 中扩展 BotState 枚举，添加 CLOSING_MARKET 和 CLOSING_LIMIT
- [X] T009 在 spread/models.py 中扩展 BotConfig，添加阶梯开仓配置字段
- [X] T010 在 spread/models.py 中扩展 BotConfig，添加双模式平仓配置字段
- [X] T011 在 spread/models.py 中更新 StateManager.STATE_NAMES_CN，添加新状态中文映射
- [X] T012 在 spread/state_manager.py 中更新状态转换验证逻辑，支持新状态
- [X] T013 在 spread/state_manager.py 中扩展 load_state() 方法，处理旧状态兼容
- [X] T014 在 spread/state_manager.py 中扩展 save_state() 方法，保存配置状态

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 修复重复挂单Bug (优先级：P1) 🎯 MVP

**目标**: 确保修改挂单价格时先取消旧订单再创建新订单，避免多个挂单同时存在

**独立测试**: 模拟修改挂单价格场景，验证系统能正确取消旧订单后再创建新订单

### 测试 for User Story 1

- [X] T015 [P] [US1] 编写取消订单验证单元测试 in tests/unit/test_cancel_verification.py
- [X] T016 [P] [US1] 编写修改挂单价格集成测试 in tests/integration/test_order_management.py

### 实现 for User Story 1

- [X] T017 [P] [US1] 在 spread/trade_executor.py 中实现 cancel_maker_order_with_verification() 方法
- [X] T018 [US1] 在 spread/trade_executor.py 中实现 _verify_order_cancellation() 私有方法
- [X] T019 [US1] 在 spread/maker_order_monitor.py 中添加取消订单监控支持
- [X] T020 [US1] 在 spread/spread_arb_bot.py 中集成取消验证机制到修改挂单流程
- [X] T021 [US1] 添加取消订单操作的详细日志记录
- [X] T022 [US1] 添加取消失败时的错误处理和安全状态转换

**检查点**: 此时用户故事1应完整功能且可独立测试

---

## Phase 4: User Story 2 - 阶梯价差开仓 (优先级：P1)

**目标**: 实现递增式开仓阈值策略，第N次开仓使用阈值 = 初始价差 + (N-1) × 步长

**独立测试**: 模拟价差波动场景，验证系统能按照阶梯阈值正确触发开仓

### 测试 for User Story 2

- [ ] T023 [P] [US2] 编写阶梯阈值计算单元测试 in tests/unit/test_tiered_opening.py
- [ ] T024 [P] [US2] 编写阶梯开仓流程集成测试 in tests/integration/test_tiered_opening_flow.py

### 实现 for User Story 2

- [X] T025 [P] [US2] 在 spread/arithmetic_open_strategy.py 中修改 should_open() 方法，使用 config.current_open_threshold
- [X] T026 [P] [US2] 在 spread/arithmetic_open_strategy.py 中实现 on_position_opened() 回调方法
- [X] T027 [P] [US2] 在 spread/arithmetic_open_strategy.py 中实现 on_all_positions_closed() 回调方法
- [X] T028 [P] [US2] 在 spread/arithmetic_open_strategy.py 中实现 get_current_tier_state() 方法
- [X] T029 [US2] 在 spread/spread_arb_bot.py 中集成开仓成功回调，增加 opening_count
- [X] T030 [US2] 在 spread/spread_arb_bot.py 中集成平仓成功回调，重置 opening_count
- [X] T031 [US2] 在 spread/state_manager.py 中持久化 opening_count 到状态文件
- [X] T032 [US2] 添加阶梯开仓状态的详细日志记录

**检查点**: 此时用户故事1和2都应独立工作

---

## Phase 5: User Story 3 - 双模式平仓逻辑 (优先级：P2)

**目标**: 根据利润水平选择限价平仓或市价平仓

**独立测试**: 模拟不同价差场景，验证系统能根据利润大小选择正确的平仓方式

### 测试 for User Story 3

- [ ] T033 [P] [US3] 编写双模式平仓决策单元测试 in tests/unit/test_dual_mode_close.py
- [ ] T034 [P] [US3] 编写市价平仓流程集成测试 in tests/integration/test_market_close.py
- [ ] T035 [P] [US3] 编写限价平仓流程集成测试 in tests/integration/test_limit_close.py

### 实现 for User Story 3

- [X] T036 [P] [US3] 在 spread/smart_close_strategy.py 中修改 should_close() 方法，返回三元组 (should_close, reason, use_market)
- [X] T037 [P] [US3] 在 spread/smart_close_strategy.py 中实现 get_total_position_spread() 方法
- [X] T038 [P] [US3] 在 spread/smart_close_strategy.py 中实现 _fetch_exchange_avg_prices() 方法
- [X] T039 [P] [US3] 在 spread/smart_close_strategy.py 中实现降级策略，使用本地加权平均
- [X] T040 [US3] 在 spread/spread_arb_bot.py 中实现 _execute_market_close() 方法
- [X] T041 [US3] 在 spread/spread_arb_bot.py 中实现 _execute_limit_close() 方法
- [X] T042 [US3] 在 spread/spread_arb_bot.py 中修改 _check_close_signal() 方法，根据 use_market 选择状态
- [X] T043 [US3] 添加双模式平仓决策的详细日志记录

**检查点**: 所有用户故事现在都应独立功能

---

## Phase 6: User Story 4 - 可用仓位检测系统 (优先级：P3)

**目标**: 开仓前检查两个交易所余额，防止单边持仓风险

**独立测试**: 模拟不同余额状态，验证系统能正确判断并拒绝余额不足的开仓请求

### 测试 for User Story 4

- [ ] T044 [P] [US4] 编写余额检测单元测试 in tests/unit/test_balance_checker.py
- [ ] T045 [P] [US4] 编写余额充足场景集成测试 in tests/integration/test_balance_sufficient.py
- [ ] T046 [P] [US4] 编写余额不足场景集成测试 in tests/integration/test_balance_insufficient.py

### 实现 for User Story 4

- [X] T047 [P] [US4] 创建 spread/balance_checker.py 模块，实现 BalanceAvailabilityChecker 类 (renamed to avoid conflict with PositionBalanceChecker)
- [X] T048 [P] [US4] 在 spread/balance_checker.py 中实现 check_before_opening() 方法
- [X] T049 [P] [US4] 在 spread/balance_checker.py 中实现 _get_extended_balance() 私有方法
- [X] T050 [P] [US4] 在 spread/balance_checker.py 中实现 _get_lighter_balance() 私有方法
- [X] T051 [P] [US4] 在 spread/balance_checker.py 中实现 _calculate_required_amount() 私有方法
- [X] T052 [US4] 在 spread/spread_arb_bot.py 中初始化 BalanceAvailabilityChecker 实例 (as self.funds_checker to avoid conflict)
- [X] T053 [US4] 在 spread/spread_arb_bot.py 中的 _check_open_signal() 方法里集成余额检测
- [X] T054 [US4] 添加余额检测结果的详细日志记录
- [X] T055 [US4] 添加余额检测失败时的优雅降级处理

**检查点**: 所有用户故事都应独立功能

---

## Phase 7: Polish & 跨领域关注点

**目的**: 影响多个用户故事的改进

- [X] T056 [P] 更新 CLAUDE.md 文档，记录新功能和配置
- [ ] T057 [P] 代码清理和重构，确保代码质量
- [ ] T058 运行所有测试套件验证功能完整性
- [ ] T059 性能优化：验证价差检测响应时间 < 200ms
- [ ] T060 性能优化：验证市价平仓执行时间 < 500ms
- [ ] T061 端到端集成测试：完整套利流程验证
- [ ] T062 验证 quickstart.md 中的所有示例可正常运行
- [ ] T063 安全审查：确保没有新的安全漏洞
- [ ] T064 更新日志格式，确保所有新功能都有清晰日志

---

## 依赖关系 & 执行顺序

### 阶段依赖

- **Setup (Phase 1)**: 无依赖 - 可立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成 - 阻塞所有用户故事
- **User Stories (Phase 3-6)**: 都依赖 Foundational 阶段完成
  - 用户故事可以并行进行（如果有足够人力）
  - 或按优先级顺序执行（P1 → P2 → P3 → P4）
- **Polish (Phase 7)**: 依赖所有期望的用户故事完成

### 用户故事依赖

- **User Story 1 (P1)**: Foundational 完成后可开始 - 无其他故事依赖
- **User Story 2 (P1)**: Foundational 完成后可开始 - 可与 US1 并行
- **User Story 3 (P2)**: Foundational 完成后可开始 - 依赖 Portfolio 模型（已在 016 中实现）
- **User Story 4 (P3)**: Foundational 完成后可开始 - 无其他故事依赖

### 每个用户故事内

- 测试 MUST 在实现前编写并失败
- 模型修改 before 策略修改
- 核心实现 before 集成
- 故事完成 before 进入下一优先级

### 并行机会

- Setup 阶段所有标记 [P] 的任务可并行
- Foundational 阶段所有标记 [P] 的任务可并行（T005-T010）
- Foundational 完成后，所有用户故事可并行开始
- 每个用户故事内所有标记 [P] 的测试可并行
- 每个用户故事内标记 [P] 的实现任务可并行
- 不同用户故事可由不同团队成员并行开发

---

## 并行示例: User Story 1

```bash
# 一起启动 User Story 1 的所有测试:
Task T015: "编写取消订单验证单元测试"
Task T016: "编写修改挂单价格集成测试"

# 一起启动 TradeExecutor 的实现:
Task T017: "实现 cancel_maker_order_with_verification() 方法"
Task T018: "实现 _verify_order_cancellation() 私有方法"
```

---

## 并行示例: User Story 2

```bash
# 一起启动 User Story 2 的所有测试:
Task T023: "编写阶梯阈值计算单元测试"
Task T024: "编写阶梯开仓流程集成测试"

# 一起启动 ArithmeticOpenStrategy 的修改:
Task T025: "修改 should_open() 方法"
Task T026: "实现 on_position_opened() 回调"
Task T027: "实现 on_all_positions_closed() 回调"
Task T028: "实现 get_current_tier_state() 方法"
```

---

## 实施策略

### MVP 优先 (仅 User Story 1 和 2)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational (关键 - 阻塞所有故事)
3. 完成 Phase 3: User Story 1 (重复挂单Bug修复)
4. 完成 Phase 4: User Story 2 (阶梯价差开仓)
5. **停止并验证**: 独立测试用户故事1和2
6. 如准备就绪则部署/演示

### 增量交付

1. 完成 Setup + Foundational → 基础就绪
2. 添加 User Story 1 → 独立测试 → 部署/演示 (修复严重Bug!)
3. 添加 User Story 2 → 独立测试 → 部署/演示 (提升盈利能力!)
4. 添加 User Story 3 → 独立测试 → 部署/演示 (优化平仓策略!)
5. 添加 User Story 4 → 独立测试 → 部署/演示 (增强风控!)
6. 每个故事都在不破坏前序故事的情况下增加价值

### 并行团队策略

有多个开发者时：

1. 团队一起完成 Setup + Foundational
2. Foundational 完成后:
   - 开发者 A: User Story 1 (修复重复挂单Bug)
   - 开发者 B: User Story 2 (阶梯价差开仓)
   - 开发者 C: User Story 3 (双模式平仓) - 需等待 Portfolio 相关代码
3. 故事独立完成并集成

---

## 任务统计

- **总任务数**: 64
- **Setup 阶段**: 4 任务
- **Foundational 阶段**: 10 任务
- **User Story 1**: 8 任务 (2 测试 + 6 实现)
- **User Story 2**: 10 任务 (2 测试 + 8 实现)
- **User Story 3**: 11 任务 (3 测试 + 8 实现)
- **User Story 4**: 12 任务 (3 测试 + 9 实现)
- **Polish 阶段**: 9 任务

### 并行机会

- **Setup 阶段**: 3 个任务可并行 (T002, T003, T004)
- **Foundational 阶段**: 6 个任务可并行 (T005-T010)
- **User Story 1**: 4 个任务可并行 (2 测试 + 2 实现)
- **User Story 2**: 6 个任务可并行 (2 测试 + 4 实现)
- **User Story 3**: 6 个任务可并行 (3 测试 + 3 实现)
- **User Story 4**: 7 个任务可并行 (3 测试 + 4 实现)
- **Polish 阶段**: 2 个任务可并行

### MVP 范围建议

**最小可行产品 (MVP)**: Phase 1 + Phase 2 + Phase 3 (User Story 1)

- 修复重复挂单Bug是关键需求，影响系统安全性
- 完成后即可验证核心修复是否有效
- 建议优先级: User Story 1 > User Story 2 > User Story 3 > User Story 4

### 格式验证

✅ 所有任务遵循检查清单格式:
- ✅ 以 `- [ ]` 开头 (复选框)
- ✅ 包含任务 ID (T001-T064)
- ✅ 并行任务标记 [P]
- ✅ 用户故事任务标记 [US1]-[US4]
- ✅ 描述包含精确文件路径

---

## Notes

- [P] 任务 = 不同文件，无依赖
- [Story] 标签将任务映射到特定用户故事以便追踪
- 每个用户故事应独立完成和可测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免: 模糊任务、同文件冲突、破坏独立性的跨故事依赖
