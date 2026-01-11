---

# Tasks: 修复仓位失衡和优化开仓标准

**Input**: Design documents from `/specs/010-fix-position-imbalance/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 本项目遵循TDD方法，需要编写测试任务（参考spec.md中的测试要求）

**Organization**: 任务按用户故事分组，以支持每个故事的独立实现和测试

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖关系）
- **[Story]**: 任务所属用户故事（如 US0, US1, US2）
- **描述**: 包含精确文件路径的清晰操作

## Path Conventions

本项目为单项目结构（Python）：
- 核心代码: `spread/`
- 交易所客户端: `exchanges/`
- 测试: `tests/`

---

## Phase 1: Setup (准备阶段)

**Purpose**: 初始化和安全准备

**⚠️ CRITICAL**: 当前系统存在严重仓位失衡（Extended 0.21 ETH vs Lighter 0.02 ETH），建议先手动处理当前仓位

- [ ] T001 确认当前仓位状态（Extended 0.21 ETH vs Lighter 0.02 ETH）
- [ ] T002 评估手动平仓选项（考虑当前市场价和滑点）
- [ ] T003 [P] 备份当前交易日志 logs/trade.log
- [ ] T004 [P] 备份当前价差数据 data/spreads_*.csv
- [ ] T005 [P] 确认当前git分支为 010-fix-position-imbalance
- [ ] T006 创建特性分支备份点（git tag checkpoint-pre-fix）

---

## Phase 2: Foundational (基础修复 - P0关键安全)

**Purpose**: 修复仓位平衡计算和创建安全监控基础设施

**⚠️ CRITICAL**: 这些任务必须在任何新开仓之前完成

### 基础模型修复

- [ ] T007 [P] [US0] 修复 PositionBalance.__post_init__ 计算逻辑 in spread/models.py
  - 使用绝对值计算总暴露度：total_exposure = abs(extended) + abs(lighter)
  - 使用绝对值计算实际差异：diff_qty = abs(abs(extended) - abs(lighter))
  - 计算差异率：diff_rate = diff_qty / total_exposure
  - 更新 warning_level 判断逻辑：50%+ = CRITICAL, 10%+ = WARN, 其他 = OK

- [ ] T008 [P] [US0] 添加 SafetyState 数据类 in spread/models.py
  - 字段：is_paused, pause_reason, pause_since
  - 字段：hedge_failure_window, recent_hedge_attempts, hedge_failure_rate
  - 字段：position_imbalance_rate, last_imbalance_check
  - 字段：unhedged_positions, total_unhedged_value
  - 字段：circuit_breaker_level (0=正常, 1=警告, 2=禁止开仓, 3=完全暂停)

- [ ] T009 [P] [US0] 添加 HedgeFailureTracking 数据类 in spread/models.py
  - 字段：timestamp, pair_id, extended_order_id, extended_fill_qty
  - 字段：hedge_attempts, hedge_order_ids
  - 字段：failure_reason（枚举：liquidity_insufficient, api_error, network_error, timeout, unknown）
  - 字段：failure_details, is_resolved, resolved_at, resolution_method

### 安全监控模块

- [ ] T010 [US0] 创建 SafetyMonitor 类框架 in spread/safety_monitor.py
  - __init__: 接收 config 和 logger，初始化 state
  - record_hedge_attempt(): 记录对冲尝试结果
  - get_hedge_failure_rate(): 计算对冲失败率
  - check_circuit_breaker(): 检查熔断级别
  - should_pause_opening(): 判断是否暂停开仓
  - should_force_close(): 判断是否强制平仓
  - update_position_imbalance(): 更新仓位失衡率
  - get_position_imbalance_rate(): 获取仓位失衡率
  - get_safety_state(): 获取安全状态快照
  - reset_circuit_breaker(): 手动重置熔断器

- [ ] T011 [US0] 实现 SafetyMonitor.record_hedge_attempt() in spread/safety_monitor.py
  - 更新滑动窗口 recent_hedge_attempts（最多10次）
  - 更新统计 total_hedge_attempts, total_hedge_failures
  - 重新计算 hedge_failure_rate
  - 如果失败，创建 HedgeFailureTracking 记录
  - 检查熔断条件

- [ ] T012 [US0] 实现 SafetyMonitor.get_hedge_failure_rate() in spread/safety_monitor.py
  - 从 recent_hedge_attempts 计算失败率
  - 返回 Decimal（0-1之间）

- [ ] T013 [US0] 实现 SafetyMonitor.check_circuit_breaker() in spread/safety_monitor.py
  - 级别3（完全暂停）: 失败率>50% 或 失衡率>50%
  - 级别2（禁止开仓）: 失败率>30%
  - 级别1（警告）: 失败率>20%
  - 级别0（正常）: 其他情况
  - 返回 (级别, 原因描述)

- [ ] T014 [US0] 实现 SafetyMonitor.update_position_imbalance() in spread/safety_monitor.py
  - 使用绝对值计算 total_exposure = abs(extended) + abs(lighter)
  - 使用绝对值计算 diff_qty = abs(abs(extended) - abs(lighter))
  - 计算 diff_rate = diff_qty / total_exposure
  - 更新 state.position_imbalance_rate

### 配置更新

- [ ] T015 [P] [US0] 添加 P0 安全配置项 in spread/config.py
  - safety_enabled: bool = True
  - safety_hedge_failure_threshold: Decimal = Decimal('0.3')
  - safety_position_imbalance_threshold: Decimal = Decimal('0.5')
  - safety_failure_window: int = 10
  - safety_pause_duration: int = 3600

- [ ] T016 [P] [US0] 更新配置验证逻辑 in spread/config.py __post_init__
  - 验证 safety_hedge_failure_threshold 在 [0, 1] 范围内
  - 验证 safety_position_imbalance_threshold 在 [0, 1] 范围内
  - 验证 safety_failure_window > 0

**Checkpoint**: 基础安全模块完成 - 可以集成到主系统

---

## Phase 3: User Story 0 - 修复仓位失衡（Priority: P0 - 关键安全）🚨

**Goal**: 修复实际仓位失衡问题（Extended 0.21 ETH vs Lighter 0.02 ETH），实现对冲失败检测和熔断机制

**Independent Test**:
- 运行测试：pytest tests/test_position_balance_fix.py -v
- 验证完全对冲仓位显示 0% 差异率（而非 200%）
- 验证实际失衡情况（0.21 vs 0.02）显示正确的 82.6% 差异率
- 验证对冲失败率>30%时触发熔断

### Tests for User Story 0

> **NOTE: 先写测试，确保测试失败后再实现功能**

- [ ] T017 [P] [US0] 创建 test_position_balance_fix.py in tests/
  - test_fully_hedged_position(): 验证完全对冲仓位 diff_rate = 0%
  - test_imbalanced_position_82_percent(): 验证0.21 vs 0.02的失衡率计算
  - test_critical_imbalance(): 验证严重失衡触发 CRITICAL 级别
  - test_warning_level_determination(): 验证警告级别判断
  - test_edge_cases(): 测试零仓位、单边仓位等边界情况

- [ ] T018 [P] [US0] 创建 test_safety_monitor.py in tests/
  - test_record_hedge_attempt_success(): 测试记录成功的对冲尝试
  - test_record_hedge_attempt_failure(): 测试记录失败的对冲尝试
  - test_hedge_failure_rate_calculation(): 测试对冲失败率计算
  - test_circuit_breaker_trigger(): 测试熔断器触发
  - test_position_imbalance_calculation(): 测试仓位失衡率计算
  - test_should_pause_opening(): 测试开仓暂停判断
  - test_should_force_close(): 测试强制平仓判断
  - test_circuit_breaker_reset(): 测试熔断器重置

- [ ] T019 [P] [US0] 创建 test_circuit_breaker_integration.py in tests/integration/
  - test_hedge_failure_triggers_pause(): 测试对冲失败触发暂停
  - test_position_imbalance_triggers_force_close(): 测试仓位失衡触发强制平仓
  - test_safety_monitor_with_bot(): 测试SafetyMonitor与Bot的集成
  - test_circuit_breaker_recovery(): 测试熔断器恢复流程

### Implementation for User Story 0

- [ ] T020 [US0] 在 SpreadArbitrageBot.__init__ 中初始化 SafetyMonitor in spread/bot.py
  - 创建 self.safety_monitor = SafetyMonitor(self.config, self.logger)
  - 位置：在其他模块初始化之后

- [ ] T021 [US0] 在 _check_can_open_new_position 中添加安全检查 in spread/bot.py
  - 调用 self.safety_monitor.should_pause_opening()
  - 如果返回 True，返回 (False, "安全监控器暂停开仓")
  - 调用 self.safety_monitor.check_circuit_breaker()
  - 如果级别 >= 2，返回 (False, f"熔断器级别{level}: {reason}")

- [ ] T022 [US0] 在 _open_new_pair 中记录对冲结果 in spread/bot.py
  - 在 hedge_manager.execute_hedge() 之后
  - 调用 await self.safety_monitor.record_hedge_attempt(
      success=hedge_result['success'],
      failure_reason=hedge_result.get('error')
    )

- [ ] T023 [US0] 在 _monitor_pairs 中更新仓位失衡率 in spread/bot.py
  - 调用 unified_positions = self.position_aggregator.aggregate_positions(self.open_pairs)
  - 提取 extended_total 和 lighter_total
  - 调用 self.safety_monitor.update_position_imbalance(extended_total, lighter_total)

- [ ] T024 [US0] 添加仓位快照日志记录 in spread/bot.py
  - 在 _monitor_pairs 中定期调用
  - 记录：timestamp, extended_position, lighter_position, diff_rate, safety_level
  - 输出到 logs/positions.log 或追加到 trade.log

- [ ] T025 [US0] 实现熔断器手动重置功能 in spread/bot.py
  - 添加 reset_circuit_breaker() 方法
  - 调用 self.safety_monitor.reset_circuit_breaker()
  - 重置 is_paused 和 pause_until

- [ ] T026 [US0] 添加安全状态监控输出 in spread/bot.py
  - 在 _stats_reporter 中添加安全状态信息
  - 输出：对冲失败率、仓位失衡率、熔断级别

**Checkpoint**: User Story 0 完成 - 仓位失衡计算修复，安全监控和熔断机制已实现

---

## Phase 4: User Story 1 - 降低开仓阈值增加交易频率（Priority: P1）

**Goal**: 在对冲成功率>90%的前提下，降低开仓阈值（0.10%→0.06%）增加交易频率

**Prerequisites**:
- 对冲成功率必须>90%
- 仓位失衡率必须<20%
- User Story 0 所有测试通过

**Independent Test**:
- 验证对冲成功率>90%时，开仓阈值降至0.06%
- 验证对冲失败率>20%时，开仓阈值恢复到0.15%
- 验证10小时内开仓次数从2次增加到至少20次

### Tests for User Story 1

- [ ] T027 [P] [US1] 创建 test_adaptive_threshold_manager.py in tests/
  - test_get_effective_min_spread_high_success_rate(): 测试高成功率时使用降低阈值
  - test_get_effective_min_spread_low_success_rate(): 测试低成功率时使用安全阈值
  - test_should_enable_reduced_thresholds(): 测试降低阈值启用条件
  - test_threshold_transition(): 测试阈值切换逻辑

### Implementation for User Story 1

- [ ] T028 [P] [US1] 创建 AdaptiveThresholdManager 类框架 in spread/adaptive_threshold_manager.py
  - __init__: 接收 config 和 safety_monitor
  - get_effective_min_spread_rate(): 根据对冲成功率动态返回阈值
  - should_enable_reduced_thresholds(): 判断是否可以启用降低阈值
  - update_thresholds(): 定期更新阈值

- [ ] T029 [US1] 实现 AdaptiveThresholdManager.get_effective_min_spread_rate() in spread/adaptive_threshold_manager.py
  - 获取当前对冲成功率：hedge_success_rate = 1 - safety_monitor.get_hedge_failure_rate()
  - 如果成功率高>90%：返回 config.reduced_min_spread_rate (0.06%)
  - 如果成功率中等>80%：返回中间值
  - 如果成功率低<80%：返回 config.adaptive_min_spread_rate_safe (0.15%)

- [ ] T030 [US1] 实现 AdaptiveThresholdManager.should_enable_reduced_thresholds() in spread/adaptive_threshold_manager.py
  - 检查对冲成功率是否>90%
  - 检查仓位失衡率是否<20%
  - 返回 True/False

- [ ] T031 [P] [US1] 添加 P1 动态阈值配置项 in spread/config.py
  - adaptive_threshold_enabled: bool = False
  - adaptive_min_hedge_success_rate: Decimal = Decimal('0.9')
  - adaptive_min_spread_rate_safe: Decimal = Decimal('0.15')
  - adaptive_min_spread_rate_aggressive: Decimal = Decimal('0.06')
  - adaptive_adjustment_interval: int = 300

- [ ] T032 [P] [US1] 添加 P1 降低阈值配置项 in spread/config.py
  - reduced_min_spread_rate: Decimal = Decimal('0.06')
  - reduced_profit_target_rate: Decimal = Decimal('0.02')
  - reduced_min_close_profit_rate: Decimal = Decimal('0.03')

- [ ] T033 [US1] 在 SpreadArbitrageBot.__init__ 中初始化 AdaptiveThresholdManager in spread/bot.py
  - 仅当 config.adaptive_threshold_enabled = True 时
  - 创建 self.adaptive_threshold_manager = AdaptiveThresholdManager(self.config, self.safety_monitor)

- [ ] T034 [US1] 在 _strategy_loop 中使用动态阈值 in spread/bot.py
  - 替换固定的 self.config.min_spread_rate
  - 调用 min_spread = self.adaptive_threshold_manager.get_effective_min_spread_rate()

**Checkpoint**: User Story 1 完成 - 动态阈值调整已实现，在对冲成功率高时自动降低阈值

---

## Phase 5: User Story 2 - 优化平仓策略（Priority: P2）

**Goal**: 降低盈利目标和平仓阈值，加快资金周转

**Prerequisites**: User Story 0 和 User Story 1 完成

**Independent Test**:
- 验证持仓盈亏达到0.02%时触发时间小额平仓
- 验证持仓盈亏达到0.03%时触发盈利目标平仓
- 验证资金周转率提高

### Implementation for User Story 2

- [ ] T035 [P] [US2] 更新平仓配置项 in spread/config.py
  - 修改 min_close_profit_rate: Decimal = Decimal('0.03')
  - 修改 profit_target_rate: Decimal = Decimal('0.02')
  - 修改 time_close_profit_threshold: Decimal = Decimal('0.01')

- [ ] T036 [US2] 更新 _check_close_conditions 中的平仓逻辑 in spread/bot.py
  - 使用新的 profit_target_rate (0.02%)
  - 使用新的 min_close_profit_rate (0.03%)
  - 保持 P1-P5 优先级系统不变

**Checkpoint**: User Story 2 完成 - 平仓阈值已优化

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事改进和最终验证

- [ ] T037 [P] 更新 CLAUDE.md 项目文档 with new technologies (010-fix-position-imbalance)
- [ ] T038 [P] 更新 trade_logger.py 以支持安全事件日志
  - 添加 log_safety_event() 方法
  - 记录熔断触发、安全模式进入/退出
  - 输出到 logs/safety.log

- [ ] T039 [P] 更新 spread_recorder.py 以记录安全状态
  - 在价差记录中添加安全状态字段
  - 记录熔断级别、对冲失败率

- [ ] T040 [P] 创建手动平仓工具 script/manual_close.py
  - 支持强制平仓所有持仓
  - 支持指定套利对平仓
  - 确认操作提示

- [ ] T041 运行完整测试套件
  - pytest tests/test_position_balance_fix.py -v
  - pytest tests/test_safety_monitor.py -v
  - pytest tests/integration/test_circuit_breaker_integration.py -v
  - pytest tests/test_adaptive_threshold_manager.py -v (如果实现了P1)
  - pytest tests/ -v (所有测试)

- [ ] T042 验证 quickstart.md 实现指南
  - 确认所有步骤已执行
  - 确认所有检查清单已完成

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖 - 可立即开始
- **Phase 2 (Foundational - P0)**: 依赖 Phase 1 完成 - 阻止所有用户故事
- **Phase 3 (User Story 0 - P0)**: 依赖 Phase 2 完成
- **Phase 4 (User Story 1 - P1)**: 依赖 Phase 3 和对冲成功率>90%
- **Phase 5 (User Story 2 - P2)**: 依赖 Phase 3 和 Phase 4
- **Phase 6 (Polish)**: 依赖所有用户故事完成

### User Story Dependencies

- **User Story 0 (P0)**: 独立，无依赖其他用户故事
- **User Story 1 (P1)**: 依赖 User Story 0（需要安全监控数据）
- **User Story 2 (P2)**: 依赖 User Story 0 和 User Story 1

### Within Each User Story

- 测试必须先编写并确保失败
- 模型修改先于服务集成
- 核心实现先于集成
- 故事完成后才能进入下一阶段

### Parallel Opportunities

- Phase 1: T003, T004, T005, T006 可并行
- Phase 2: T007, T008, T009 可并行（不同文件）
- Phase 2: T015, T016 可并行（不同文件）
- User Story 0 测试: T017, T018, T019 可并行
- User Story 0 实现: T020-T026 部分可并行（需注意集成点）

---

## Parallel Example: User Story 0 Tests

```bash
# 同时启动所有 User Story 0 测试:
pytest tests/test_position_balance_fix.py::test_fully_hedged_position &
pytest tests/test_position_balance_fix.py::test_imbalanced_position_82_percent &
pytest tests/test_safety_monitor.py::test_hedge_failure_rate_calculation &
pytest tests/test_safety_monitor.py::test_circuit_breaker_trigger

# 等待所有测试完成并验证失败
```

---

## Implementation Strategy

### Critical Path First (User Story 0 Only - P0安全修复)

1. **立即执行**: 手动处理当前 0.21 ETH vs 0.02 ETH 的严重失衡
2. Phase 1: Setup（备份和确认）
3. Phase 2: Foundational（修复计算逻辑和安全监控）
4. Phase 3: User Story 0（集成和测试）
5. **验证**: 运行测试，确保熔断机制工作
6. **STOP**: 验证 P0 完成后再考虑 P1/P2

### Incremental Delivery (如果继续 P1 和 P2)

1. P0 完成 → 修复了仓位失衡和安全问题 → **立即部署保护**
2. 监控对冲成功率 → 如果>90% 且稳定 → 继续 P1
3. P1 完成 → 降低阈值，增加交易频率 → **测试并部署**
4. P2 完成 → 优化平仓策略 → **最终部署**

### Parallel Team Strategy

单个开发者的顺序执行策略：

1. **时间段 1**: Phase 1 + Phase 2 (约2-3小时)
   - 修复 PositionBalance 计算
   - 创建 SafetyMonitor 模块
   - 更新配置

2. **时间段 2**: Phase 3 (约2-3小时)
   - 集成到 Bot
   - 编写和运行测试
   - 验证熔断机制

3. **时间段 3**: 验证和调整 (约1小时)
   - 运行完整测试套件
   - 修复发现的问题
   - 准备部署

---

## Notes

- **P0 是关键路径**: 当前系统有 0.21 ETH 未对冲仓位，必须先修复
- **TDD 强制**: 所有测试必须先编写并确保失败
- **验证清单**: 每个完成后都要运行相关测试
- **Git 提交**: 每个任务或逻辑组完成后提交
- **停止点**: 可以在任何 checkpoint 停止并验证
- **避免**: 模糊的任务、同一文件冲突、破坏故事独立性的依赖关系

---

## Summary

- **Total Tasks**: 42 个任务
- **P0 Tasks**: 27 个任务（Setup + Foundational + User Story 0）
- **P1 Tasks**: 7 个任务（User Story 1）
- **P2 Tasks**: 2 个任务（User Story 2）
- **Polish Tasks**: 6 个任务

**Suggested MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 0 - P0安全修复)

**Estimated Effort**:
- P0 (关键安全修复): 约6小时
- P1 (降低阈值): 约2小时（在对冲成功率>90%前提下）
- P2 (优化平仓): 约1小时

**Critical Path**:
1. 手动处理当前仓位 → 2. Phase 1 (Setup) → 3. Phase 2 (Foundational) → 4. Phase 3 (User Story 0) → 5. **验证并部署P0**

**Parallel Opportunities**: 已在上面标注 [P] 标记的任务
