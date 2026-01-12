# Implementation Plan: 修复Lighter SDK初始化错误导致下单失败

**Branch**: `003-fix-lighter-sdk` | **Date**: 2026-01-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-fix-lighter-sdk/spec.md`

## Summary

修复Lighter SDK初始化时的`AttributeError: 'NoneType' object has no attribute 'code'`错误，该错误导致下单失败率100%，单腿持仓率100%，熔断器触发系统完全暂停。

**技术方案**：
1. 在SDK初始化后添加完整的对象状态验证
2. 增强错误日志，记录SDK对象状态快照
3. 添加SDK健康检查机制
4. 提供fallback机制处理代理配置失败

## Technical Context

**Language/Version**: Python 3.10.19 (asyncio)
**Primary Dependencies**:
- lighter-sdk 0.1.4 (官方Lighter DEX SDK)
- asyncio (异步编程框架)
- decimal.Decimal (精确数值计算)
- logging (日志记录)

**Storage**: 内存状态存储 + 文件日志（logs/trade.log）
**Testing**: pytest (单元测试和集成测试)
**Target Platform**: Linux/macOS服务器
**Project Type**: 单项目（Python单代码库）
**Performance Goals**:
- Lighter下单成功率 >= 90%
- SDK初始化时间 < 5秒
- 健康检查耗时 < 100ms
- 错误诊断时间 < 5分钟

**Constraints**:
- 不能修改Lighter SDK源码
- 必须保持与Extended交易所并发下单的<5ms延迟
- 必须向后兼容现有配置
- 不能引入额外的外部依赖

**Scale/Scope**:
- 修改文件：`exchanges/lighter.py`, `spread/concurrent_executor.py`
- 新增测试：`tests/test_lighter_sdk_health.py`
- 日志增强：现有日志系统

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Core Principles Validation

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Simplicity | ✅ PASS | 最小化修改，只添加验证和日志，不改变核心逻辑 |
| II. Testability | ✅ PASS | 所有修改都有对应的单元测试 |
| III. Observability | ✅ PASS | 增强日志记录SDK状态，便于诊断 |
| IV. Backward Compatibility | ✅ PASS | 保持现有API不变，只添加内部检查 |

### Technical Debt & Complexity

| Item | Impact | Mitigation |
|------|--------|------------|
| SDK黑盒依赖 | 中等 | 通过健康检查和状态验证降低风险 |
| 错误处理复杂度 | 低 | 只添加验证层，不改变现有流程 |

**Status**: ✅ ALL GATES PASSED - 可以继续进行研究和设计

## Project Structure

### Documentation (this feature)

```text
specs/003-fix-lighter-sdk/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A for this feature)
└── tasks.md             # Phase 2 output (NOT created yet)
```

### Source Code (repository root)

```text
exchanges/
├── lighter.py           # 主要修改：添加SDK初始化验证和健康检查
└── lighter_custom_websocket.py  # 无需修改

spread/
└── concurrent_executor.py  # 添加健康检查调用

tests/
├── test_lighter_sdk_health.py  # 新增：SDK健康检查测试
└── integration/
    └── test_lighter_order_fix_integration.py  # 已存在，更新测试用例
```

**Structure Decision**: 单项目结构，Python异步代码库
- 主要修改在`exchanges/lighter.py`（Lighter客户端）
- 次要修改在`spread/concurrent_executor.py`（调用健康检查）
- 新增测试文件验证修复效果

## Phase 0: Research & Investigation

### Research Tasks

1. **研究Lighter SDK初始化流程**
   - 目标：理解`SignerClient`、`ApiClient`、`rest_client`的初始化顺序
   - 方法：阅读SDK源码和官方文档
   - 输出：初始化流程图和关键依赖关系

2. **研究AttributeError的根本原因**
   - 目标：确定哪个对象为None导致`'NoneType' object has no attribute 'code'`
   - 方法：分析错误堆栈和SDK源码
   - 输出：根本原因分析报告

3. **研究SDK健康检查最佳实践**
   - 目标：确定如何验证SDK对象完整性
   - 方法：参考其他交易所客户端的健康检查实现
   - 输出：健康检查方案设计

4. **研究代理配置对SDK的影响**
   - 目标：理解代理失败如何影响SDK初始化
   - 方法：测试不同代理配置场景
   - 输出：代理配置fallback方案

### Research Output

详见 [research.md](./research.md)

## Phase 1: Design

### Data Model

详见 [data-model.md](./data-model.md)

**核心实体**：
- `SDKHealthStatus`: SDK健康状态（包含所有关键对象状态）
- `SDKObjectState`: 单个SDK对象的状态（类型、是否为None、可用性）

### API Contracts

详见 [contracts/](./contracts/) 目录

**新增接口**：
- `LighterClient.check_sdk_health() -> SDKHealthStatus`
- `LighterClient.get_sdk_state_snapshot() -> Dict[str, Any]`

**修改接口**（内部实现）：
- `LighterClient._initialize_lighter_client()`: 添加验证逻辑
- `ConcurrentExecutor._place_order_lighter()`: 添加健康检查

### Quick Start Guide

详见 [quickstart.md](./quickstart.md)

## Implementation Phases

### Phase 1: User Story 1 - 修复SDK初始化验证 (P1)

**目标**: 确保SDK初始化时所有关键对象不为None

**任务**：
1. 在`_initialize_lighter_client()`中添加对象状态验证
2. 添加详细的错误日志，指出哪个对象为None
3. 修改初始化失败时的错误处理逻辑

**文件修改**：
- `exchanges/lighter.py`:
  - `_initialize_lighter_client()`: 添加`_validate_sdk_objects()`调用
  - 新增`_validate_sdk_objects()`: 验证lighter_client、api_client、rest_client
  - 新增`_get_sdk_object_state()`: 获取对象状态快照

**验收标准**：
- ✅ SDK初始化失败时，日志明确指出哪个对象为None
- ✅ 初始化成功时，所有关键对象不为None
- ✅ 单元测试覆盖所有对象状态组合

### Phase 2: User Story 2 - 增强诊断日志 (P2)

**目标**: 提供SDK对象状态快照，便于诊断问题

**任务**：
1. 在捕获AttributeError时记录SDK状态
2. 添加SDK对象状态日志
3. 格式化状态快照输出

**文件修改**：
- `exchanges/lighter.py`:
  - `_submit_order_with_retry()`: 添加状态快照日志
  - 新增`_log_sdk_state_snapshot()`: 记录对象状态

**验收标准**：
- ✅ 错误日志包含所有SDK对象状态
- ✅ 状态快照格式清晰易读
- ✅ 单元测试验证日志内容

### Phase 3: User Story 3 - 添加健康检查机制 (P3)

**目标**: 在下单前检查SDK健康状态

**任务**：
1. 实现`check_sdk_health()`方法
2. 在`concurrent_executor.py`中调用健康检查
3. 健康检查失败时拒绝下单

**文件修改**：
- `exchanges/lighter.py`:
  - 新增`check_sdk_health() -> SDKHealthStatus`
  - 新增`_check_api_client_health()`: 检查api_client状态
  - 新增`_check_rest_client_health()`: 检查rest_client状态
- `spread/concurrent_executor.py`:
  - `_place_order_lighter()`: 添加健康检查调用

**验收标准**：
- ✅ 健康检查耗时 < 100ms
- ✅ 健康检查失败时返回明确错误
- ✅ 单元测试覆盖所有健康检查场景

### Phase 4: Testing & Validation

**目标**: 验证修复效果

**任务**：
1. 编写单元测试
2. 编写集成测试
3. 运行端到端测试
4. 验证成功标准

**测试文件**：
- `tests/test_lighter_sdk_health.py`: 新增单元测试
- `tests/integration/test_lighter_order_fix_integration.py`: 更新集成测试

**验收标准**：
- ✅ 所有单元测试通过
- ✅ Lighter下单成功率 >= 90%
- ✅ 单腿持仓率 < 10%
- ✅ 熔断器不再因Lighter失败而触发

## Risk Assessment

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| SDK内部API变更 | 高 | 低 | 通过健康检查检测并提示 |
| 代理配置失败 | 中 | 中 | 提供fallback机制 |
| 初始化延迟增加 | 低 | 低 | 健康检查异步执行 |
| 日志过多影响性能 | 低 | 低 | 只在错误时记录详细状态 |

## Dependencies & Blockers

### 外部依赖
- ✅ Lighter SDK 0.1.4已安装
- ✅ Python 3.10.19环境可用
- ❓ 网络连接到Lighter API（需要测试验证）

### 内部依赖
- ✅ `exchanges/base.py`: BaseExchangeClient已存在
- ✅ `helpers/logger.py`: TradingLogger已存在
- ✅ `spread/models.py`: OrderCache已存在

### Blockers
无已知阻塞因素

## Success Metrics

根据 [spec.md](./spec.md) 的成功标准：

- **SC-001**: Lighter下单成功率 >= 90% (当前0%)
- **SC-002**: 单腿持仓率 < 10% (当前100%)
- **SC-003**: 错误诊断时间 < 5分钟
- **SC-004**: SDK初始化失败在启动阶段检测
- **SC-005**: 并发下单延迟 < 5ms
- **SC-006**: 熔断器不再触发完全暂停

## Post-Implementation

### Monitoring
- 监控Lighter下单成功率（按小时统计）
- 监控SDK健康检查失败率
- 监控单腿持仓事件

### Documentation
- 更新CLAUDE.md记录SDK初始化验证逻辑
- 添加故障排查指南到README

### Future Improvements
- 考虑添加SDK自动重连机制
- 考虑添加SDK性能监控
- 考虑实现SDK降级策略
