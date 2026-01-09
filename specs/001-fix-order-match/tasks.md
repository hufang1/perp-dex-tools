# 任务列表: 修复Extended成交但Lighter未成交的对冲失败问题

**输入**: `/specs/001-fix-order-match/` 中的设计文档
**前提条件**: plan.md, spec.md (必需), research.md, data-model.md, contracts/

**测试**: 本功能规格说明中未明确要求TDD方法，但包含验收场景可用于验证

**组织方式**: 任务按用户故事分组，以支持每个故事的独立实现和测试

## 格式说明: `[ID] [P?] [Story] 描述`

- **[P]**: 可并行执行（不同文件，无依赖关系）
- **[Story]**: 任务所属的用户故事（US1, US2, US3）
- 描述中包含精确的文件路径

## 路径约定

- **单一项目**: 仓库根目录下的 `spread/`, `exchanges/`, `tests/`
- 本项目使用单一项目结构，修改集中在现有文件中

---

## Phase 1: 设置（共享基础设施）

**目的**: 项目初始化和基本结构准备

- [x] T001 验证开发环境配置（Python 3.11+, pytest, asyncio）
- [x] T002 备份当前分支代码以准备修改
- [x] T003 [P] 创建测试目录结构 tests/integration/
- [x] T004 [P] 验证日志目录 logs/ 存在且可写

---

## Phase 2: 基础（阻塞性前提条件）

**目的**: 核心基础设施，必须在任何用户故事实现之前完成

**⚠️ 关键**: 在此阶段完成前，不能开始任何用户故事工作

- [x] T005 验证现有缓存机制在 spread/order_manager.py 中正常工作
- [x] T006 验证WebSocket回调链在 exchanges/extended.py 和 spread/bot.py 中连通
- [x] T007 [P] 确认 logging 配置支持调试级别日志输出
- [x] T008 确认 trade_logger 支持警告和错误日志记录

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: 用户故事1 - 防止竞态条件导致对冲失败（优先级: P1）🎯 MVP

**目标**: 修复WebSocket成交通知在订单ID设置前到达导致的竞态条件，确保对冲订单正确触发

**独立测试**: 模拟WebSocket消息在订单ID设置前到达的场景，验证对冲订单是否正确执行

### 用户故事1实现

- [x] T009 [US1] 在 spread/order_manager.py 的 _apply_pending_updates() 方法中添加详细日志：缓存检查开始、找到/未找到、应用详情
- [x] T010 [US1] 在 spread/order_manager.py 的 update_order_status() 方法中添加竞态条件检测日志（当 current_order_id=None 时）
- [x] T011 [US1] 在 spread/order_manager.py 的 wait_for_fill() 方法开始时添加 await self._apply_pending_updates(order_id) 调用
- [x] T012 [US1] 在 spread/order_manager.py 的 _apply_pending_updates() 方法中添加缓存统计日志（命中率、命中数、未命中数）
- [x] T013 [US1] 在 spread/bot.py 的 _handle_extended_order_update() 方法中添加日志，区分"直接处理"和"缓存处理"两种路径
- [x] T014 [US1] 在 spread/bot.py 中验证订单提交后立即调用 _apply_pending_updates() 的逻辑存在
- [x] T015 [US1] 在 exchanges/extended.py 的 handle_account() 方法中添加订单更新到达时间戳日志
- [x] T016 [US1] 在 spread/order_manager.py 中验证 _update_lock 正确保护 _pending_updates 的并发访问
- [x] T017 [US1] 在 spread/order_manager.py 的 _cleanup_cache() 方法中添加缓存清理日志（清理原因、清理数量）

### 用户故事1测试

- [ ] T018 [P] [US1] 编写单元测试 test_race_condition_cache() 在 tests/test_order_manager.py，验证WebSocket消息在订单ID设置前到达时的缓存机制
- [ ] T019 [P] [US1] 编写单元测试 test_cache_application() 在 tests/test_order_manager.py，验证缓存在订单ID设置后被正确应用
- [ ] T020 [P] [US1] 编写单元测试 test_cache_ttl_cleanup() 在 tests/test_order_manager.py，验证TTL过期缓存被正确清理
- [ ] T021 [US1] 编写集成测试 test_websocket_race_condition() 在 tests/integration/test_race_condition_fix.py，模拟完整的竞态条件场景

**检查点**: 此时，用户故事1应该完全功能正常且可独立测试

---

## Phase 4: 用户故事2 - 增强订单状态追踪（优先级: P2）

**目标**: 提供完整的订单生命周期追踪日志，便于问题诊断

**独立测试**: 通过检查日志输出验证所有关键状态转换都被记录

### 用户故事2实现

- [ ] T022 [P] [US2] 在 spread/order_manager.py 的 place_spread_maker_order() 方法中添加订单提交成功日志（order_id, timestamp, price, quantity）
- [ ] T023 [P] [US2] 在 spread/order_manager.py 的 update_order_status() 方法中添加订单状态转换日志（旧状态→新状态）
- [ ] T024 [US2] 在 spread/bot.py 中添加对冲订单提交日志（提交时间、订单ID、数量、价格、结果）
- [ ] T025 [US2] 在 spread/hedge_manager.py 中添加Lighter订单状态日志（成功/失败、原因）
- [ ] T026 [US2] 验证日志输出格式包含完整上下文（时间戳、订单ID、交易所、状态、数量、价格）
- [ ] T027 [US2] 添加性能日志（缓存应用耗时、对冲订单提交耗时）

### 用户故事2测试

- [ ] T028 [P] [US2] 编写单元测试 test_order_lifecycle_logging() 在 tests/test_order_manager.py，验证完整生命周期日志
- [ ] T029 [P] [US2] 编写集成测试 test_log_path_tracing() 在 tests/integration/test_race_condition_fix.py，验证日志路径追踪

**检查点**: 此时，用户故事1和2都应该独立工作

---

## Phase 5: 用户故事3 - 熔断保护机制（优先级: P3）

**目标**: 检测未对冲仓位并触发熔断，防止进一步交易

**独立测试**: 模拟Lighter订单失败场景，验证熔断是否正确触发

### 用户故事3实现

- [ ] T030 [P] [US3] 在 spread/bot.py 中添加熔断状态字典（is_tripped, reason, trip_time, uncleared_positions）
- [ ] T031 [P] [US3] 在 spread/bot.py 中实现 _check_circuit_breaker() 方法，在处理新套利机会前检查熔断状态
- [ ] T032 [US3] 在 spread/bot.py 中实现 _trip_circuit_breaker() 方法，检测到未对冲仓位时触发熔断
- [ ] T033 [US3] 在 spread/bot.py 中实现 _reset_circuit_breaker() 方法，支持人工确认后恢复
- [ ] T034 [US3] 在 spread/trade_logger.py 中添加 log_uncleared_position() 方法，记录未对冲仓位到 trade.log
- [ ] T035 [US3] 在 spread/bot.py 中检测Lighter对冲订单失败时调用 _trip_circuit_breaker()
- [ ] T036 [US3] 在 spread/bot.py 的主循环中添加熔断检查，停止处理新的套利机会
- [ ] T037 [US3] 添加熔断状态日志（触发时间、原因、未对冲仓位详情）

### 用户故事3测试

- [ ] T038 [P] [US3] 编写单元测试 test_circuit_breaker_trigger() 在 tests/test_order_manager.py，验证熔断触发逻辑
- [ ] T039 [P] [US3] 编写单元测试 test_circuit_breaker_reset() 在 tests/test_order_manager.py，验证熔断重置逻辑
- [ ] T040 [US3] 编写集成测试 test_uncleared_position_detection() 在 tests/integration/test_race_condition_fix.py，模拟未对冲仓位场景

**检查点**: 所有用户故事现在都应该独立功能正常

---

## Phase 6: 优化与跨领域关注点

**目的**: 影响多个用户故事的改进

- [ ] T041 [P] 性能测试：验证缓存应用延迟 < 50ms
- [ ] T042 [P] 性能测试：验证熔断触发延迟 < 100ms
- [ ] T043 [P] 性能测试：验证日志写入延迟 < 10ms
- [ ] T044 运行 quickstart.md 中的验证清单
- [ ] T045 验证所有成功标准（SC-001 到 SC-006）已满足
- [ ] T046 更新 CLAUDE.md 中的 Recent Changes 部分
- [ ] T047 代码清理：移除调试日志（如果不再需要）
- [ ] T048 最终集成测试：连续运行24小时验证无单边持仓

---

## 依赖关系与执行顺序

### 阶段依赖

- **设置（Phase 1）**: 无依赖 - 可立即开始
- **基础（Phase 2）**: 依赖设置完成 - 阻塞所有用户故事
- **用户故事（Phase 3-5）**: 都依赖基础阶段完成
  - 用户故事可以并行进行（如果有足够人力）
  - 或按优先级顺序执行（P1 → P2 → P3）
- **优化（Phase 6）**: 依赖所有期望的用户故事完成

### 用户故事依赖

- **用户故事1（P1）**: 基础完成后可开始 - 不依赖其他故事
- **用户故事2（P2）**: 基础完成后可开始 - 与US1独立但可集成
- **用户故事3（P3）**: 基础完成后可开始 - 与US1/US2独立但可集成

### 各用户故事内部

- 日志增强可在各文件中并行进行（标记为[P]的任务）
- 核心修复在用户故事1中必须顺序完成
- 用户故事2和3中的测试可以并行编写

### 并行机会

- 所有设置阶段标记为[P]的任务可以并行运行
- 基础阶段标记为[P]的任务可以并行运行
- 基础阶段完成后，所有用户故事可以并行开始（如果团队容量允许）
- 用户故事1中的测试任务（T018-T020）可以并行运行
- 用户故事2中的测试任务（T028-T029）可以并行运行
- 用户故事3中的测试任务（T038-T039）可以并行运行
- 不同用户故事可以由不同团队成员并行处理

---

## 并行示例: 用户故事1

```bash
# 一起启动用户故事1的所有测试：
Task T018: "编写单元测试 test_race_condition_cache() 在 tests/test_order_manager.py"
Task T019: "编写单元测试 test_cache_application() 在 tests/test_order_manager.py"
Task T020: "编写单元测试 test_cache_ttl_cleanup() 在 tests/test_order_manager.py"

# 一起启动用户故事2的日志增强：
Task T022: "在 spread/order_manager.py 的 place_spread_maker_order() 方法中添加订单提交成功日志"
Task T023: "在 spread/order_manager.py 的 update_order_status() 方法中添加订单状态转换日志"

# 不同团队成员并行处理不同用户故事：
Developer A: 用户故事1（T009-T021）
Developer B: 用户故事2（T022-T029）
Developer C: 用户故事3（T030-T040）
```

---

## 实现策略

### MVP优先（仅用户故事1）

1. 完成 Phase 1: 设置
2. 完成 Phase 2: 基础（关键 - 阻塞所有故事）
3. 完成 Phase 3: 用户故事1
4. **停止并验证**: 独立测试用户故事1
5. 如果就绪则部署/演示

### 增量交付

1. 完成设置 + 基础 → 基础就绪
2. 添加用户故事1 → 独立测试 → 部署/演示（MVP！）
3. 添加用户故事2 → 独立测试 → 部署/演示
4. 添加用户故事3 → 独立测试 → 部署/演示
5. 每个故事都在不破坏前一个故事的情况下增加价值

### 并行团队策略

有多个开发者时：

1. 团队一起完成设置 + 基础
2. 基础完成后：
   - 开发者A: 用户故事1
   - 开发者B: 用户故事2
   - 开发者C: 用户故事3
3. 故事独立完成和集成

---

## 任务统计

- **总任务数**: 48
- **设置阶段**: 4
- **基础阶段**: 4
- **用户故事1**: 13（包括4个测试）
- **用户故事2**: 8（包括2个测试）
- **用户故事3**: 11（包括3个测试）
- **优化阶段**: 8

### 按用户故事

- 用户故事1（P1）: 13任务 - 核心竞态条件修复
- 用户故事2（P2）: 8任务 - 增强日志追踪
- 用户故事3（P3）: 11任务 - 熔断保护机制

### 并行机会

- 设置阶段: 3个并行任务（T003, T004）
- 基础阶段: 2个并行任务（T007, T008）
- 用户故事1测试: 3个并行任务（T018, T019, T020）
- 用户故事2测试: 2个并行任务（T028, T029）
- 用户故事3测试: 2个并行任务（T038, T039）
- 用户故事3实现: 2个并行任务（T030, T031）
- 优化阶段: 3个并行任务（T041, T042, T043）

---

## 备注

- [P] 任务 = 不同文件，无依赖关系
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应该可独立完成和测试
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同一文件冲突、破坏独立性的跨故事依赖
