# Implementation Plan: 修复订单执行超时和假阳性成交问题

**Branch**: `013-fix-order-timeout` | **Date**: 2026-01-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/013-fix-order-timeout/spec.md`

---

## Summary

修复两个导致订单执行失败的关键bug：

1. **Extended订单500ms超时**：`place_open_order()`在提交订单后调用阻塞的`get_order_info()`方法（最多25秒），导致并发执行器超时
2. **Lighter假阳性成交**：当`current_order.order_id`为`None`时仍然返回`success=True`，导致系统误判为单腿持仓

**技术方案**：
- Extended IOC订单在SDK返回成功后立即返回，跳过`get_order_info()`调用
- Lighter只有当`order_id`存在时才返回成功，否则查询API验证
- 增强错误日志显示具体失败原因

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, logging, pytest, dataclasses
**Storage**: 内存状态存储 + 文件日志（logs/trade.log）
**Testing**: pytest（单元测试 + 集成测试）
**Target Platform**: Linux/macOS 服务器
**Project Type**: 单项目（交易机器人）
**Performance Goals**:
  - Extended订单响应时间 < 100ms
  - 并发执行超时阈值 500ms
  - 订单执行成功率 > 90%
**Constraints**:
  - 必须使用asyncio异步执行
  - 金融计算必须使用Decimal保证精度
  - 不修改Extended订单类型（保持GTT）
  - 不修改并发执行器超时阈值（保持500ms）
**Scale/Scope**:
  - 2个交易所（Extended, Lighter）
  - 现有代码库约30个Python模块
  - 修改范围：exchanges/extended.py, exchanges/lighter.py, spread/concurrent_executor.py

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: ✅ PASSED - No constitution file defined, following project conventions

### Code Quality Standards

- ✅ 遵循现有代码风格（dataclasses, Decimal, asyncio）
- ✅ 不添加新依赖（使用现有库）
- ✅ 保持向后兼容（不修改API接口）
- ✅ 测试驱动（修改前后都有单元测试）

### Technical Constraints

- ✅ 不修改订单类型（Extended保持GTT）
- ✅ 不修改超时阈值（保持500ms）
- ✅ 不实现Extended WebSocket（仍使用REST API）
- ✅ 不修改回滚逻辑（只确保正确触发）

---

## Project Structure

### Documentation (this feature)

```text
specs/013-fix-order-timeout/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (not applicable - no new APIs)
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
exchanges/
├── extended.py          # 修改: place_open_order() - IOC订单立即返回
├── lighter.py           # 修改: place_open_order() - 验证order_id
└── base.py              # 不修改: OrderResult, OrderInfo

spread/
├── concurrent_executor.py  # 修改: 错误日志增强
├── models.py             # 不修改: ConcurrentOrderResult
└── bot.py                # 不修改: 使用现有接口

tests/
├── test_extended_fix.py       # NEW: Extended修复单元测试
├── test_lighter_fix.py        # NEW: Lighter修复单元测试
└── integration/
    └── test_order_timeout_fix_integration.py  # NEW: 集成测试
```

**Structure Decision**: 单项目结构。修改范围限定在3个核心文件，新增3个测试文件。

---

## Complexity Tracking

> **No violations** - This is a targeted bug fix with minimal scope

| N/A | N/A | N/A |
|-----|-----|------|

---

## Phase 0: Research & Analysis

### Research Tasks

1. **Extended `get_order_info()` 阻塞问题**
   - Task: 分析`get_order_info()`的重试逻辑和性能影响
   - Outcome: 确认最坏情况25秒阻塞，决定跳过此调用

2. **Extended IOC订单行为验证**
   - Task: 确认GTT订单使用对手价是否立即成交
   - Outcome: 验证IOC（post_only=False）使用对手价会立即成交

3. **Lighter WebSocket竞态条件**
   - Task: 分析`current_order.order_id`为`None`的场景
   - Outcome: 确认需要在返回前验证`order_id`存在性

4. **`get_inactive_orders()`可用性**
   - Task: 验证`get_inactive_orders()`是否能正确查询订单状态
   - Outcome: 确认可以查询已成交/已取消订单

---

## Phase 1: Design

### Data Model (data-model.md)

核心数据结构保持不变，修改现有类的行为：

**OrderResult** (exchanges/base.py)
```python
@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    side: str
    size: Decimal
    price: Decimal
    status: Optional[str] = None
    filled_size: Optional[Decimal] = None
    error_message: Optional[str] = None
```

**ConcurrentOrderResult** (spread/models.py)
```python
@dataclass
class ConcurrentOrderResult:
    extended_success: bool
    extended_order_id: Optional[str]
    extended_error: Optional[str]
    lighter_success: bool
    lighter_order_id: Optional[str]
    lighter_error: Optional[str]
    is_both_filled: bool
    is_legging: bool
    is_both_failed: bool
```

### API Contracts (contracts/)

本功能不涉及新API，修改现有接口行为：

**Extended.place_open_order() 修改**
- 输入：不变（contract_id, quantity, direction, post_only）
- 输出：OrderResult
- 行为变更：IOC订单（post_only=False）立即返回，不调用`get_order_info()`

**Lighter.place_open_order() 修改**
- 输入：不变（contract_id, quantity, direction）
- 输出：OrderResult
- 行为变更：只有当`order_id`不为`None`时才返回`success=True`

**并发执行器日志增强**
- 格式：`{Exchange}: success={bool}, order_id={str}, error={str}`
- 目的：显示具体失败原因

---

## Phase 2: Implementation Tasks

### P0 Tasks (核心修复)

1. **修复Extended订单超时** (exchanges/extended.py)
   - 修改`place_open_order()`方法
   - IOC订单（post_only=False）在SDK返回成功后立即返回
   - 添加日志：`[DEBUG] IOC订单已提交，立即返回成功`

2. **修复Lighter假阳性** (exchanges/lighter.py)
   - 修改`place_open_order()`方法
   - 验证`current_order.order_id`存在性
   - 添加警告日志当`order_id`为`None`

3. **增强错误日志** (spread/concurrent_executor.py)
   - 修改单腿持仓日志格式
   - 修改双边失败日志格式
   - 显示`error`字段内容

### P1 Tasks (测试)

4. **Extended修复单元测试**
   - 测试IOC订单立即返回
   - 测试Post-Only订单仍查询状态
   - 测试超时场景

5. **Lighter修复单元测试**
   - 测试`order_id=None`时返回失败
   - 测试`order_id`存在时返回成功
   - 测试API验证逻辑

6. **集成测试**
   - 测试双边订单成功场景
   - 测试双边订单失败场景（不应触发单腿持仓）
   - 测试真实单腿持仓场景

---

## Success Metrics

### Development Complete

- [ ] Extended IOC订单在100ms内返回
- [ ] Lighter不再返回`success=True, order_id=None`
- [ ] 所有失败日志显示具体错误原因
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试全部通过

### Production Ready

- [ ] 本地测试运行1小时无超时错误
- [ ] 订单执行成功率 > 90%
- [ ] 单腿持仓误报率 = 0%

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Extended订单实际未成交但返回成功 | 高 | 添加监控日志，验证WebSocket成交确认 |
| Lighter API查询失败导致误判 | 中 | 添加重试逻辑和详细错误日志 |
| 性能回归（新的API查询） | 低 | `get_inactive_orders()`在现有代码中已使用 |

---

## Dependencies

### Code Dependencies
- `exchanges/extended.py` - `place_open_order()`方法
- `exchanges/lighter.py` - `place_open_order()`, `get_inactive_orders()`方法
- `spread/concurrent_executor.py` - 日志输出逻辑
- `spread/models.py` - `OrderResult`, `ConcurrentOrderResult`类

### Feature Dependencies
- 011-fix-lighter-hedge: WebSocket OrderCache机制
- 010-fix-position-imbalance: 安全监控器

---

## Rollback Plan

如果修复引入问题：

1. **Extended**: 恢复`get_order_info()`调用，但添加1秒超时
2. **Lighter**: 恢复原有逻辑，但添加`order_id`验证日志
3. **日志**: 保留增强的错误日志（向后兼容）

---

## Next Steps

1. 运行 `/speckit.tasks` 生成具体任务列表
2. 实现P0任务（核心修复）
3. 实现P1任务（测试）
4. 本地测试验证
5. 提交代码审查
