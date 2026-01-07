# Tasks: 修复套利机器人订单状态更新的竞态条件bug

**Input**: Design documents from `/specs/003-fix-order-status-race/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/order_manager_interface.md

**Tests**: 本功能包含单元测试任务，用于验证缓存机制和竞态条件修复。

**Organization**: 任务按用户故事分组，每个故事可以独立实现和测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可以并行运行（不同文件，无依赖关系）
- **[Story]**: 此任务属于哪个用户故事（例如 US1, US2, US3）
- 在描述中包含确切的文件路径

## Path Conventions

本项目是单一Python项目：
- `spread/`: 核心业务逻辑模块
- `tests/`: 测试文件目录

---

## Phase 1: Setup (共享基础设施)

**目的**: 项目初始化和基础结构

由于这是一个修复现有bug的功能，无需额外的设置步骤。现有项目结构已经就绪。

---

## Phase 2: Foundational (阻塞性先决条件)

**目的**: 所有用户故事实现之前必须完成的核心基础设施

**⚠️ 重要**: 在此阶段完成之前，不能开始任何用户故事工作

- [x] T001 [US1] 添加缓存相关属性到 SpreadOrderManager.__init__ in spread/order_manager.py
  - 添加 `_pending_updates: Dict[str, List[Dict]]` 缓存字典
  - 添加 `_update_lock: asyncio.Lock` 并发锁
  - 添加 `_cache_ttl: int = 300` 配置（5分钟TTL）
  - 添加 `_max_cache_size: int = 100` 最大缓存限制
  - 添加 `_max_updates_per_order: int = 10` 每订单最大更新数
  - 添加 `_cache_hits: int = 0` 和 `_cache_misses: int = 0` 统计信息

**检查点**: 基础设施就绪 - 用户故事实现现在可以并行开始

---

## Phase 3: User Story 1 - 确保套利对完整执行，避免未对冲的单边持仓风险 (Priority: P1) 🎯 MVP

**目的**: 修复核心竞态条件bug，确保Extended订单成交后Lighter能够同步开单对冲

**独立测试**: 模拟快速成交场景（订单在下单函数返回前成交），验证程序能够缓存并应用订单状态更新，`wait_for_fill`在2秒内返回FILLED状态，Lighter成功下对冲单

### Tests for User Story 1 (测试优先 - TDD) ⚠️

> **注意: 先编写这些测试，确保它们在实现之前失败**

- [x] T002 [P] [US1] 编写竞态条件测试用例 in tests/test_order_manager.py
  - 测试场景：订单更新在current_order_id设置前到达
  - 模拟WebSocket回调在下单返回前发送FILLED状态
  - 验证缓存机制正确保存更新
  - 验证current_order_id设置后应用缓存更新
  - 验证filled_quantity和filled_price被正确更新

- [x] T003 [P] [US1] 编写缓存应用测试用例 in tests/test_order_manager.py
  - 测试同一订单的多个状态更新（PARTIALLY_FILLED → FILLED）
  - 验证按时间戳顺序应用更新
  - 验证最终的filled_quantity反映完全成交数量

### Implementation for User Story 1

- [x] T004 [US1] 实现 _add_pending_update 私有方法 in spread/order_manager.py
  - 接收订单ID和订单数据
  - 创建缓存条目：`{"order_data": {...}, "timestamp": time.time()}`
  - 将条目添加到 `_pending_updates[order_id]` 列表
  - 限制每个订单最多10个更新（`_max_updates_per_order`）
  - 添加debug日志记录缓存操作

- [x] T005 [US1] 实现 _apply_pending_updates 私有方法 in spread/order_manager.py
  - 接收订单ID参数
  - 使用 `async with self._update_lock` 保护并发访问
  - 从 `_pending_updates` 获取该订单的缓存更新
  - 按时间戳升序排序更新
  - 依次应用每个更新：设置 current_order_status, filled_quantity, filled_price
  - 应用完成后从缓存中删除该订单
  - 更新 `_cache_hits` 统计
  - 添加info日志记录缓存应用

- [x] T006 [US1] 实现 _cleanup_cache 私有方法 in spread/order_manager.py
  - 使用 `async with self._update_lock` 保护并发访问
  - 清理超过TTL的缓存（`now - timestamp > _cache_ttl`）
  - 清理超过最大限制的缓存（缓存订单数 > `_max_cache_size`）
  - 清理已完成订单的缓存（status为FILLED或CANCELLED）
  - 添加warning日志记录清理操作

- [x] T007 [US1] 修改 update_order_status 方法 in spread/order_manager.py
  - 在现有CLOSE类型检查之前，提取order_id
  - 检查 `self.current_order_id` 是否为None
    - 如果为None：调用 `_add_pending_update` 缓存更新，记录info日志"⚡ 检测到竞态条件: 缓存订单更新"
    - 添加debug日志显示：order_id, current_order_id, 时间戳
  - 检查 `order_id != self.current_order_id`
    - 如果不匹配：也尝试缓存（可能是其他订单的更新）
  - 添加详细的debug日志：接收时间、订单ID、处理状态

- [x] T008 [US1] 修改 place_spread_maker_order 方法 in spread/order_manager.py
  - 在第88行 `self.current_order_id = order_result.order_id` 之后
  - 立即调用 `await self._apply_pending_updates(order_result.order_id)`
  - 添加info日志记录是否应用了缓存更新
  - 确保不影响现有返回值和错误处理

- [x] T009 [US1] 在 wait_for_fill 方法中添加缓存检查逻辑 in spread/order_manager.py
  - 在while循环开始前，检查是否有缓存的更新
  - 如果有该订单的缓存且包含FILLED状态，立即应用
  - 添加debug日志记录从缓存获取状态

- [x] T010 [US1] 添加竞态条件检测和缓存日志 in spread/order_manager.py
  - 在update_order_status中检测到早期更新时，记录info日志
  - 日志格式：`"⚡ 检测到竞态条件: 缓存订单更新, order_id={order_id}"`
  - 在apply_pending_updates中，记录info日志：`"✅ 应用缓存的订单更新: {status}"`
  - 在cleanup_cache中，记录warning日志：清理的订单ID和数量

**检查点**: 此时，用户故事1应该完全功能正常且可以独立测试。运行 `pytest tests/test_order_manager.py -v` 验证所有测试通过。

---

## Phase 4: User Story 2 - 处理并发的订单状态更新消息 (Priority: P2)

**目的**: 确保程序能够正确处理同一订单的多个状态更新（如PARTIALLY_FILLED后跟FILLED），不会丢失任何中间状态

**独立测试**: 模拟并发WebSocket消息场景，短时间内发送多个订单状态更新，验证程序能够按顺序处理所有更新，最终filled_quantity反映完全成交的数量

### Tests for User Story 2 (测试优先 - TDD) ⚠️

- [x] T011 [P] [US2] 编写并发更新测试用例 in tests/test_order_manager.py
  - 测试同一订单的多个并发更新
  - 模拟PARTIALLY_FILLED → FILLED的快速连续更新
  - 验证所有更新都被缓存和应用
  - 验证最终状态正确（FILLED, 完全成交数量）

- [x] T012 [P] [US2] 编写多订单并发测试用例 in tests/test_order_manager.py
  - 测试多个不同订单的同时更新
  - 验证每个订单的状态独立跟踪
  - 验证缓存不会相互干扰

### Implementation for User Story 2

- [x] T013 [US2] 增强 _add_pending_update 以支持并发更新 in spread/order_manager.py
  - 使用 `async with self._update_lock` 保护缓存写入
  - 在添加更新前检查列表长度，防止超过 `_max_updates_per_order`
  - 如果超过限制，删除最旧的更新（保持最新）
  - 添加debug日志记录并发缓存操作

- [x] T014 [US2] 增强 _apply_pending_updates 以处理更新去重 in spread/order_manager.py
  - 在应用更新前，检查是否有重复的状态
  - 如果有重复，保留最新的更新（按时间戳）
  - 确保状态转换符合业务规则（如FILLED后不能有其他状态）
  - 添加warning日志记录重复/无效的状态转换

**检查点**: 此时，用户故事1和2都应该独立工作。运行所有测试验证。

---

## Phase 5: User Story 3 - 提供订单状态更新的可观测性 (Priority: P3)

**目的**: 通过详细的日志输出，让用户能够清楚了解订单状态更新的时序和处理情况，便于调试和验证竞态条件修复

**独立测试**: 运行程序并查看日志输出，验证当订单状态更新到达时，日志显示订单ID、当前current_order_id、是否匹配、是否被处理等详细信息

### Implementation for User Story 3

- [x] T015 [US3] 增强 update_order_status 的日志记录 in spread/order_manager.py
  - 记录每个订单状态更新的接收时间
  - 记录订单ID、当前current_order_id、是否匹配
  - 使用debug级别记录详细信息
  - 格式：`"[DEBUG] 收到订单更新: order_id={x}, current_order_id={y}, matched={z}"`

- [x] T016 [US3] 增强 _add_pending_update 的日志记录 in spread/order_manager.py
  - 记录缓存操作的时间戳和订单ID
  - 使用debug级别
  - 格式：`"[DEBUG] 缓存订单更新: order_id={x}, timestamp={t}"`

- [x] T017 [US3] 增强 _apply_pending_updates 的日志记录 in spread/order_manager.py
  - 记录应用每个缓存的详细信息
  - 记录应用前后的状态变化
  - 使用info级别记录关键事件
  - 格式：`"✅ 应用缓存的订单更新: order_id={x}, status={y}, filled_size={z}"`

- [x] T018 [US3] 增强 _cleanup_cache 的日志记录 in spread/order_manager.py
  - 记录清理前后的缓存大小
  - 记录被清理的订单ID
  - 使用warning级别记录异常情况（TTL过期、超限）
  - 格式：`"⚠️ 清理缓存: 清理了{n}个过期订单, 剩余{m}个"`

- [x] T019 [US3] 添加缓存统计信息日志 in spread/order_manager.py
  - 定期记录缓存命中率、命中次数、未命中次数
  - 在应用缓存时更新统计
  - 使用info级别
  - 格式：`"📊 缓存统计: 命中率={rate}%, 命中={hits}, 未命中={misses}"`

**检查点**: 所有用户故事现在都应该独立功能正常。日志输出清晰，便于调试。

---

## Phase 6: Polish & Cross-Cutting Concerns

**目的**: 影响多个用户故事的改进

- [x] T020 [P] 运行完整测试套件验证所有功能
  - 执行：`pytest tests/test_order_manager.py -v`
  - 确保所有测试通过
  - 检查测试覆盖率 > 90%

- [x] T021 [P] 执行集成测试验证修复效果
  - 启动spread_arb机器人
  - 观察Extended订单成交后Lighter是否成功开单
  - 检查日志中是否出现"应用缓存的订单更新"
  - 验证对冲延迟 < 5秒

- [x] T022 [P] 性能验证
  - 确认订单状态更新延迟 < 10ms
  - 确认内存开销 < 1MB
  - 运行24小时后检查缓存大小（应为0或接近0）
  - 验证缓存命中率统计

- [x] T023 [P] 代码清理和优化
  - 移除调试代码（除非用于生产监控）
  - 优化锁的持有时间（最小化临界区）
  - 确保所有异步函数正确使用async/await

- [x] T024 运行 quickstart.md 验证
  - 按照quickstart.md的步骤执行验证
  - 确认所有成功标准达成：
    - ✅ 所有单元测试通过
    - ✅ Extended订单成交后Lighter对冲成功率100%
    - ✅ wait_for_fill在订单成交后2秒内返回
    - ✅ 日志包含竞态条件检测和缓存应用记录
    - ✅ 24小时运行后无内存泄漏

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无需额外设置，现有项目已就绪
- **Foundational (Phase 2)**: 无依赖 - 可以立即开始，阻塞所有用户故事
- **User Stories (Phase 3-5)**: 都依赖于Foundational阶段完成
  - 用户故事可以并行进行（如果有足够人力）
  - 或按优先级顺序执行（P1 → P2 → P3）
- **Polish (Phase 6)**: 依赖于所有需要的用户故事完成

### User Story Dependencies

- **User Story 1 (P1)**: Foundational完成后即可开始 - 无其他故事依赖
- **User Story 2 (P2)**: Foundational完成后即可开始 - 与US1集成但应独立可测
- **User Story 3 (P3)**: Foundational完成后即可开始 - 增强US1/US2的日志，应独立可验证

### Within Each User Story

- 测试必须在实现之前编写并失败（TDD方法）
- 缓存基础方法（_add_pending_update）在应用方法（_apply_pending_updates）之前
- 核心实现在集成和日志增强之前
- 每个故事完成后移至下一个优先级

### Parallel Opportunities

- Foundational阶段的所有任务可以并行
- 每个用户故事的所有测试标记为[P]的可以并行运行
- 不同用户故事可以由不同团队成员并行开发
- Polish阶段的所有任务标记为[P]的可以并行运行

---

## Parallel Example: User Story 1

```bash
# 并行启动User Story 1的所有测试:
Task T002: "编写竞态条件测试用例 in tests/test_order_manager.py"
Task T003: "编写缓存应用测试用例 in tests/test_order_manager.py"

# 等待测试编写完成后，串行实现（因为都在同一文件）:
Task T004: "实现 _add_pending_update 私有方法 in spread/order_manager.py"
Task T005: "实现 _apply_pending_updates 私有方法 in spread/order_manager.py"
# ... 其他实现任务
```

---

## Parallel Example: Multiple Developers

```bash
# Foundational完成后，三个开发者可以并行工作:

# Developer A - User Story 1 (P1):
Tasks T002-T010 (核心竞态条件修复)

# Developer B - User Story 2 (P2):
Tasks T011-T014 (并发更新处理)

# Developer C - User Story 3 (P3):
Tasks T015-T019 (可观测性和日志)
```

---

## Implementation Strategy

### MVP First (仅User Story 1)

1. 跳过Phase 1（现有项目已就绪）
2. 完成Phase 2: Foundational (T001)
3. 完成Phase 3: User Story 1 (T002-T010)
4. **停止并验证**: 独立测试用户故事1
5. 部署/演示（如果就绪）

**MVP价值**: 修复核心竞态条件bug，确保Lighter能够正常开单对冲

### Incremental Delivery (增量交付)

1. Foundational完成 → 基础就绪
2. 添加User Story 1 → 独立测试 → 部署/演示（MVP！）
3. 添加User Story 2 → 独立测试 → 部署/演示（增强并发处理）
4. 添加User Story 3 → 独立测试 → 部署/演示（完整的可观测性）
5. 每个故事都增加价值而不破坏之前的故事

### Parallel Team Strategy (并行团队策略)

有多名开发者时：

1. 团队一起完成Foundational (T001)
2. Foundational完成后:
   - 开发者A: User Story 1 (T002-T010)
   - 开发者B: User Story 2 (T011-T014)
   - 开发者C: User Story 3 (T015-T019)
3. 故事独立完成和集成

---

## Task Summary

**总任务数**: 24
- Phase 2 (Foundational): 1 task
- Phase 3 (User Story 1 - P1): 9 tasks (包括2个测试)
- Phase 4 (User Story 2 - P2): 4 tasks (包括2个测试)
- Phase 5 (User Story 3 - P3): 5 tasks
- Phase 6 (Polish): 5 tasks

**并行机会**: 11个任务标记为[P]可以并行执行

**独立测试标准**:
- US1: 竞态条件测试通过，Lighter对冲成功率100%
- US2: 并发更新测试通过，所有状态正确追踪
- US3: 日志输出清晰，包含所有调试信息

**建议MVP范围**: User Story 1 (T001-T010)
- 这将修复核心竞态条件bug
- 提供可独立测试和部署的最小可行产品
- 完成后即可验证修复效果

---

## Notes

- [P]任务 = 不同文件，无依赖关系
- [Story]标签将任务映射到特定用户故事以便追踪
- 每个用户故事应该可独立完成和测试
- 实现前验证测试失败
- 每个任务或逻辑组后提交
- 在任何检查点停止以独立验证故事
- 避免：模糊任务、同一文件冲突、破坏独立性的跨故事依赖

## Format Validation

✅ 所有任务遵循检查清单格式：
- ✅ 以 `- [ ]` 开头（复选框）
- ✅ 包含任务ID（T001-T024）
- ✅ 包含[P]标记（适用于并行任务）
- ✅ 包含[Story]标签（US1, US2, US3，适用于用户故事任务）
- ✅ 包含确切文件路径
- ✅ 描述清晰具体，可由LLM直接执行
