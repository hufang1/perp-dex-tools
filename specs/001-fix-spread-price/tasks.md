# Tasks: 修复Spread套利脚本价格同步问题

**Feature**: 001-fix-spread-price
**Branch**: `001-fix-spread-price`
**Date**: 2026-01-16
**Status**: Ready for Implementation

---

## Task Summary

- **Total Tasks**: 28
- **Setup Phase**: 3 tasks
- **Foundational Phase**: 2 tasks
- **User Story 1 (P1)**: 10 tasks
- **User Story 2 (P2)**: 5 tasks
- **User Story 3 (P3)**: 4 tasks
- **Polish Phase**: 4 tasks
- **Parallel Opportunities**: 8 task pairs can be executed in parallel

---

## Phase 1: Setup (项目初始化)

**目标**: 创建必要的目录结构和测试环境

- [X] T001 [P] 创建tests目录结构 `tests/unit/` 和 `tests/integration/`
- [X] T002 [P] 创建 `spread/price_snapshot.py` 文件（定义PriceSnapshot类框架）
- [X] T003 [P] 备份核心文件 `spread/trade_executor.py` 和 `exchanges/extended.py` 到 `.specify/backups/001-fix-spread-price/`

**验证**:
- 目录创建成功
- 备份文件存在

---

## Phase 2: Foundational (基础组件)

**目标**: 实现核心数据模型和工具函数

- [X] T004 [US1] 实现 `spread/price_snapshot.py` 中的 `PriceSnapshot` 类
  - 定义所有字段：ext_bid, ext_ask, ext_timestamp, lig_bid, lig_ask, lig_timestamp, time_delta
  - 实现 `is_valid()` 方法：验证time_delta<10ms，价格>0，bid<ask
  - 实现 `calculate_taker_prices()` 方法：ext_price=ext_ask*1.002, lig_price=lig_bid*0.998
  - 实现 `validate_price_consistency()` 方法：验证ext_price < lig_price
- [X] T005 [US1] 在 `spread/price_snapshot.py` 顶部添加必要的导入语句
  - `from dataclasses import dataclass`
  - `from decimal import Decimal`
  - `from typing import Tuple`

**验证**:
- 可以成功导入PriceSnapshot类
- 所有方法单元测试通过

---

## Phase 3: User Story 1 - 同步价格获取并确保滑点保护 (P1)

**目标**: 修复核心问题 - 统一价格获取+Ext加入滑点保护

### Story 1.1: 价格同步功能

- [X] T006 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中实现统一价格获取逻辑
  - 删除从spread参数获取价格的代码（Line 108-117）
  - 添加并发获取两个交易所BBO价格的代码（使用asyncio.gather）
  - 为每个价格获取记录时间戳
  - 计算time_delta = abs(lig_timestamp - ext_timestamp)
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

- [X] T007 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中创建PriceSnapshot实例
  - 使用从两个交易所获取的bid/ask价格和时间戳
  - 调用PriceSnapshot构造函数创建实例
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

- [X] T008 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中添加价格快照验证
  - 调用 `price_snapshot.is_valid()` 验证价格快照有效性
  - 如果验证失败（time_delta>=10ms），记录警告日志并返回失败的ExecutionResult
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

- [X] T009 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中计算taker价格
  - 调用 `price_snapshot.calculate_taker_prices()` 计算ext_price和lig_price
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

- [X] T010 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中添加价格一致性验证
  - 调用 `price_snapshot.validate_price_consistency()` 验证ext_price < lig_price
  - 如果验证失败，记录错误日志并返回失败的ExecutionResult
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

- [X] T011 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中添加价格同步日志
  - 记录ext_bid, ext_ask, lig_bid, lig_ask, time_delta, ext_price, lig_price, spread
  - 格式：`[价格同步] ext=XXX, lig=YYY, time_delta=ZZZms, spread=PP%`
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

### Story 1.2: Ext滑点保护

- [X] T012 [US1] 在 `spread/trade_executor.py` 的 `_place_extended_order_taker()` 方法中添加0.2%滑点保护
  - 修改price=None时的逻辑：买入使用 `best_ask * Decimal('1.002')`
  - 修改price=None时的逻辑：卖出使用 `best_bid * Decimal('0.998')`
  - 文件：`spread/trade_executor.py`，方法：`_place_extended_order_taker()`

- [X] T013 [US1] 在 `spread/trade_executor.py` 的 `_place_extended_order_taker()` 方法中添加注释说明滑点保护
  - 在方法docstring中说明0.2%滑点保护的目的
  - 注释价格计算公式：ask*1.002或bid*0.998
  - 文件：`spread/trade_executor.py`，方法：`_place_extended_order_taker()`

### Story 1.3: Extended重试限制

- [X] T014 [US1] 在 `exchanges/extended.py` 的 `place_taker_order()` 方法中添加 `max_retries` 参数
  - 添加参数定义：`max_retries: int = 1`（默认1次重试）
  - 更新方法签名和docstring
  - 文件：`exchanges/extended.py`，方法：`place_taker_order()`

- [X] T015 [US1] 在 `exchanges/extended.py` 的 `place_taker_order()` 方法中缓存原始价格
  - 在方法开始处添加：`original_price = price`
  - 修改下单逻辑使用 `original_price` 而非重新获取BBO价格
  - 文件：`exchanges/extended.py`，方法：`place_taker_order()`

- [X] T016 [US1] 在 `exchanges/extended.py` 的 `place_taker_order()` 方法中限制重试次数为1次
  - 修改重试循环条件：`while retry_count < max_retries`（max_retries=1）
  - 修改重试日志：`"Taker order not filled, retrying ({retry_count+1}/{max_retries})..."`
  - 文件：`exchanges/extended.py`，方法：`place_taker_order()`

### Story 1.4: 开仓成功日志

- [X] T017 [US1] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中添加开仓成功日志
  - 在订单成功后记录：ext_order_id, lig_order_id, ext_price, lig_price, execution_time
  - 格式：`[开仓成功] ext_order_id=XXX, lig_order_id=YYY, ext_price=XXX, lig_price=YYY, 耗时=ZZZs`
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

### Story 1.5: Maker代码弃用

- [X] T018 [US1] 在 `exchanges/lighter.py` 的 `place_open_order()` 方法中添加DeprecationWarning
  - 在方法开头添加：`import warnings`
  - 添加 `warnings.warn(..., DeprecationWarning, stacklevel=2)`
  - 更新docstring说明弃用原因和迁移指南
  - 文件：`exchanges/lighter.py`，方法：`place_open_order()`

- [X] T019 [US1] 在 `exchanges/lighter.py` 的 `get_order_price()` 方法中添加DeprecationWarning
  - 添加 `warnings.warn(..., DeprecationWarning, stacklevel=2)`
  - 更新docstring说明Taker模式的价格计算方式
  - 文件：`exchanges/lighter.py`，方法：`get_order_price()`

---

## Phase 4: User Story 2 - 价格获取优化减少延迟 (P2)

**目标**: 监控和记录价格获取性能指标

### Story 2.1: 时间戳记录

- [ ] T020 [US2] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中记录详细的时间戳
  - 在价格获取前后记录时间戳
  - 计算并记录总耗时：execution_time
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

### Story 2.2: 性能监控

- [ ] T021 [US2] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中添加性能指标日志
  - 记录从价格获取到订单发送的耗时（目标<50ms）
  - 如果超过50ms，记录警告日志
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

---

## Phase 5: User Story 3 - 添加价格一致性监控 (P3)

**目标**: 增强日志记录以便问题诊断

### Story 3.1: 异常场景日志

- [ ] T022 [US3] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中增强价格快照无效日志
  - 当time_delta>=10ms时，记录详细的警告信息
  - 包含实际time_delta值和建议措施
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

- [ ] T023 [US3] 在 `spread/trade_executor.py` 的 `execute_open_position()` 方法中增强价差异常日志
  - 当ext_price >= lig_price时，记录详细的错误信息
  - 包含实际价格值和价差大小
  - 文件：`spread/trade_executor.py`，方法：`execute_open_position()`

### Story 3.2: CSV埋点增强

- [ ] T024 [US3] 在 `spread/spread_arb_bot.py` 的 `_log_open_to_csv()` 方法中添加价格快照字段
  - 添加ext_timestamp, lig_timestamp, time_delta字段
  - 添加ext_execution_price, lig_execution_price字段（实际成交价）
  - 文件：`spread/spread_arb_bot.py`，方法：`_log_open_to_csv()`

---

## Phase 6: Testing (测试验证)

**目标**: 确保所有改动经过充分测试

### 单元测试

- [X] T025 [P] 创建 `tests/unit/test_price_snapshot.py` 文件
  - 实现 `TestPriceSnapshot` 类，包含所有PriceSnapshot方法的单元测试
  - 测试用例：test_valid_snapshot, test_invalid_time_delta, test_calculate_taker_prices, test_validate_price_consistency
  - 文件：`tests/unit/test_price_snapshot.py`（新建）

- [X] T026 [P] 创建 `tests/unit/test_trade_executor.py` 文件
  - 实现 `TestTradeExecutorSlippage` 类，测试滑点保护逻辑
  - 测试用例：test_extended_slippage_protection, test_price_sync
  - 文件：`tests/unit/test_trade_executor.py`（新建）

- [X] T027 [P] 创建 `tests/unit/test_extended_client.py` 文件
  - 实现 `TestExtendedRetry` 类，测试重试逻辑
  - 测试用例：test_retry_uses_original_price, test_retry_limited_to_1
  - 文件：`tests/unit/test_extended_client.py`（新建）

### 集成测试

- [X] T028 [P] 创建 `tests/integration/test_opening_flow.py` 文件
  - 实现 `TestOpeningFlow` 类，测试完整开仓流程
  - 测试用例：test_opening_with_price_sync, test_opening_skip_on_price_inconsistency
  - 文件：`tests/integration/test_opening_flow.py`（新建）

---

## Phase 7: Polish & Cross-Cutting Concerns (收尾工作)

**目标**: 完善文档和代码质量

### 文档更新

- [X] T029 更新 `specs/001-fix-spread-price/checklists/requirements.md` 标记已完成的验证项
  - 将Phase 1-7的所有任务标记为已完成
  - 验证所有成功标准已满足
  - 文件：`specs/001-fix-spread-price/checklists/requirements.md`

- [X] T030 在 `README.md` 或项目文档中记录此次修复的改进
  - 添加改进说明：Ext加入0.2%滑点保护，统一价格获取
  - 添加监控指标说明：time_delta, IOC失败率等
  - 如果无README则创建一个简短的README.md

### 代码清理

- [X] T031 删除或回滚 `trade_executor.py` 中的 `_place_lighter_order()` 和 `_place_extended_order()` 非taker方法
  - 搜索这两个方法的使用位置，确认没有被调用
  - 如果存在且未使用，删除这两个方法
  - 如果存在且已弃用，保留DeprecationWarning
  - 文件：`spread/trade_executor.py`

- [X] T032 验证 `spread/trade_executor.py` 中所有import语句的正确性
  - 确保新导入的 `PriceSnapshot` 类路径正确
  - 删除未使用的import语句
  - 文件：`spread/trade_executor.py`

### 最终验证

- [X] T033 运行所有单元测试并确保100%通过
  - 执行：`pytest tests/unit/ -v`
  - 验证所有测试用例通过
  - 修复任何失败的测试

- [X] T034 验证Python导入无错误
  - 执行：`python -c "from spread.trade_executor import execute_open_position; from spread.price_snapshot import PriceSnapshot; print('导入成功')"`
  - 确保所有导入路径正确

- [X] T035 验证没有DeprecationWarning在spread套利脚本中出现
  - 搜索并运行spread相关脚本
  - 确认没有调用已弃用的 `place_open_order` 或 `get_order_price` 方法
  - 如果有调用，更新为taker模式

---

## Dependencies

### 任务依赖关系

```
Phase 1 (Setup)
  ├── T001 (创建目录) → T002 (创建框架)
  └── T003 (备份文件)
      └── T002 (创建框架)

Phase 2 (Foundational)
  ├── T004 (实现PriceSnapshot) → T005 (添加导入)
  │
  └── T005 (添加导入)
      └── T006-T031 (所有使用PriceSnapshot的任务)

Phase 3 (User Story 1)
  ├── T006-T011 (价格同步功能)
  │   ├── T006 (统一获取) → T007 (创建快照) → T008 (验证) → T009 (计算价格) → T010 (一致性) → T011 (日志)
  │   └─ 必须在T004完成
  │
  ├── T012-T013 (Ext滑点保护)
  │   └─ T006-T011之后可以执行
  │
  ├── T014-T016 (重试限制)
  │   └─ T006-T011之后可以执行
  │
  ├── T017 (开仓成功日志)
  │   └─ T006-T011之后可以执行
  │
  └── T018-T019 (Maker弃用)
      └─ 独立执行

Phase 4 (User Story 2)
  └── T020-T021 (监控)
      └─ T006-T017之后可以执行

Phase 5 (User Story 3)
  ├── T022-T023 (异常日志)
  │   └─ T006-T017之后可以执行
  │
  └── T024 (CSV增强)
      └─ T006-T017之后可以执行

Phase 6 (Testing)
  ├── T025 (price_snapshot单元测试)
  │   └─ 必须在T004完成后
  │
  ├── T026 (trade_executor单元测试)
  │   └─ 必须在T006-T017完成后
  │
  ├── T027 (extended_client单元测试)
  │   └── 必须在T014-T016完成后
  │
  └── T028 (opening_flow集成测试)
      └── 必须在T006-T017完成后

Phase 7 (Polish)
  ├── T029 (更新checklist)
  ├── T030 (更新README)
  ├── T031 (清理非taker方法)
  ├── T032 (验证imports)
  ├── T033 (运行测试)
  └── T034 (验证无警告)
      └── 所有实施完成后执行
```

---

## Parallel Execution Opportunities

以下任务对可以在不同文件上并行执行：

**Pair 1** (可并行):
- T002 [P]: 创建 `spread/price_snapshot.py` 框架
- T003 [P]: 备份核心文件

**Pair 2** (可并行):
- T018 [US1]: 添加place_open_order弃用警告
- T019 [US1]: 添加get_order_price弃用警告

**Pair 3** (可并行):
- T025 [P]: 创建test_price_snapshot.py
- T026 [P]: 创建test_trade_executor.py

**Pair 4** (可并行):
- T027 [P]: 创建test_extended_client.py
- T028 [P]: 创建test_opening_flow.py

---

## Implementation Strategy

### MVP Scope (最小可验证版本)

**建议MVP范围**: 只包含User Story 1（P1）的核心任务

**MVP任务列表**:
- T001-T003 (Setup)
- T004-T005 (PriceSnapshot实现)
- T006-T011 (价格同步功能)
- T012-T013 (Ext滑点保护)
- T014-T016 (重试限制)
- T017 (开仓成功日志)
- T018-T019 (Maker弃用)
- T025-T026 (基础单元测试)

**MVP验证标准**:
- price_snapshot可以正确创建和验证
- 价格获取时间差<10ms
- Ext使用0.2%滑点保护
- 开仓成功时Ext成本<Lig成本

### 增量交付计划

**第1周**:
- 完成Phase 1-2 (Setup + Foundational)
- 完成User Story 1 (P1) 的所有任务
- 完成基础单元测试

**第2周**:
- 完成User Story 2 (P2) 和 User Story 3 (P3)
- 完成集成测试
- 小仓位试运行

---

## Risk Mitigation

### 关键风险

| 风险 | 缓解措施 |
|------|----------|
| 破坏现有功能 | 充分测试 + 特性开关 + 分阶段发布 |
| 延迟增加 | 并发获取 + 只在开仓时同步 |
| 滑点成本 | 0.2%已验证可行，可通过配置调整 |
| 影响其他脚本 | 只添加弃用标记，保持兼容 |

### 回滚触发条件

- IOC订单失败率>10%（超过目标<5%）
- Ext成本>Lig成本的情况仍有发生
- "Order not found"日志没有减少80%+

### 回滚步骤

1. 立即停止脚本
2. 恢复备份文件：
   ```bash
   cp .specify/backups/001-fix-spread-price/trade_executor.py spread/trade_executor.py
   cp .specify/backups/001-fix-spread-price/extended.py exchanges/extended.py
   ```
3. 重启脚本验证回滚成功

---

## Success Criteria

### 验收标准

| 标准 | 测量方法 | 目标值 |
|------|----------|--------|
| 价格获取时间差 | 日志分析 | <10ms (100%) |
| Ext IOC失败率 | 日志统计 | <5% |
| Ext成本>Lig成本 | 仓位分析 | 0次 |
| "Order not found"减少 | 日志对比 | 减少80%+ |
| 开仓成功率 | 功能测试 | >95% |
| 单元测试通过率 | pytest | 100% |

### 完成定义

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 测试环境验证通过
- [ ] 小仓位试运行成功（24小时无异常）
- [ ] Ext成本<Lig成本（100笔开仓样本）
- [ ] "Order not found"日志减少80%+
- [ ] Maker代码已添加弃用标记
- [ ] 文档已更新
- [ ] 无DeprecationWarning在spread脚本中

---

**任务版本**: 1.0
**生成时间**: 2026-01-16
**状态**: Ready for Implementation
**预计总工时**: 约8小时开发 + 1-2天验证

**下一步**: 执行任务T001开始实施，或使用 `/speckit.implement` 自动执行任务。

**注意**: 按照用户要求，改动点不要立即commit。所有修改完成后一起commit。
