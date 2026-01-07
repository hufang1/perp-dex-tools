# 实现计划：修复套利机器人订单状态更新的竞态条件bug

**分支**: `003-fix-order-status-race` | **日期**: 2026-01-07 | **规格**: [spec.md](spec.md)
**输入**: 来自 `/specs/003-fix-order-status-race/spec.md` 的功能规格

## 摘要

修复 `SpreadOrderManager` 中的竞态条件bug，该bug导致Extended订单成交后Lighter无法同步开单对冲。

**核心问题**: WebSocket回调在 `place_spread_maker_order()` 函数返回前接收到订单的FILLED状态更新，此时 `current_order_id` 仍为 `None`，导致 `update_order_status()` 忽略该更新，最终 `wait_for_fill()` 超时，Lighter对冲订单未执行。

**技术方案**: 实现**订单状态缓存机制**，缓存提前到达的订单更新，在 `current_order_id` 设置后应用缓存。

## 技术上下文

**语言/版本**: Python 3.11+
**主要依赖**:
- `asyncio`: 异步编程框架
- `decimal.Decimal`: 精确的金融数值计算
- `websockets`: WebSocket客户端连接
- `logging`: 标准日志库

**存储**: 内存缓存（字典）
**测试**: pytest
**目标平台**: Linux服务器（交易机器人后台运行）
**项目类型**: 单一Python项目
**性能目标**:
- 订单状态更新延迟 < 10ms
- 内存开销 < 1MB（缓存）
- 不影响现有交易性能

**约束**:
- 必须向后兼容现有代码
- 不能改变外部接口（`place_spread_maker_order`, `wait_for_fill`, `update_order_status`）
- 必须线程安全（asyncio并发）
- 日志必须包含调试信息

**规模/范围**:
- 修改文件: 1个（`spread/order_manager.py`）
- 新增代码行: ~80行
- 测试用例: 3-5个

## 宪法检查

*关卡：必须在Phase 0研究前通过。Phase 1设计后重新检查。*

**项目宪法状态**: 本项目尚未定义自定义宪法（`constitution.md`为模板）。

默认原则检查：
- ✅ **简单性**: 最小化修改，仅添加缓存机制，不重构现有逻辑
- ✅ **可观测性**: 添加详细的调试日志，记录竞态条件检测
- ✅ **向后兼容**: 不改变公共接口，内部实现修改

**通过**: 无宪法违规，可以继续。

## 项目结构

### 文档（本功能）

```text
specs/003-fix-order-status-race/
├── plan.md              # 本文件（/speckit.plan命令输出）
├── research.md          # Phase 0 输出（/speckit.plan命令）
├── data-model.md        # Phase 1 输出（/speckit.plan命令）
├── quickstart.md        # Phase 1 输出（/speckit.plan命令）
├── contracts/           # Phase 1 输出（/speckit.plan命令）
│   └── order_manager_interface.md
└── tasks.md             # Phase 2 输出（/speckit.tasks命令 - 非/speckit.plan创建）
```

### 源代码（仓库根目录）

```text
spread/
├── __init__.py
├── config.py            # 配置类（无修改）
├── order_manager.py     # 🔧 修改：添加订单状态缓存机制
├── hedge_manager.py     # 对冲管理器（无修改）
├── bot.py               # 主机器人（无修改）
├── calculator.py        # 计算器（无修改）
└── spread_pair.py       # 套利对数据模型（无修改）

tests/
├── __init__.py
└── test_order_manager.py  # 🆕 新增：订单管理器单元测试
```

**结构决策**: 单一Python项目，修改集中在 `spread/order_manager.py`，添加独立的测试文件。

## Phase 0: 研究与技术选型

### 研究任务

1. **Python asyncio并发控制最佳实践**
   - 任务: 确保缓存的读写操作在asyncio环境中安全
   - 决策: 使用 `asyncio.Lock` 保护临界区
   - 理由: asyncio中的标准同步原语，避免数据竞争

2. **Python字典缓存模式**
   - 任务: 选择合适的缓存数据结构
   - 决策: 使用 `Dict[str, List[Dict]]` 存储订单更新
   - 理由:
     - Key为订单ID（字符串）
     - Value为更新列表（处理同一订单的多个更新）
     - 每个更新包含数据和接收时间戳

3. **内存泄漏防护策略**
   - 任务: 防止缓存无限增长
   - 决策: 实现TTL（Time-To-Live）机制和最大缓存限制
   - 理由:
     - TTL: 5分钟后自动清理旧缓存
     - 最大缓存: 100个订单
     - 订单完成后立即清理

4. **日志最佳实践（Python logging模块）**
   - 任务: 确保日志包含足够调试信息但不影响性能
   - 决策: 使用 `logger.debug()` 记录详细信息，`logger.info()` 记录关键事件
   - 理由: debug级别可在生产环境关闭，info级别记录竞态条件检测

## Phase 1: 数据模型设计

### 数据模型

参见 [`data-model.md`](data-model.md)

### 合约/接口

参见 [`contracts/order_manager_interface.md`](contracts/order_manager_interface.md)

## Phase 2: 实现任务分解

**注意**: 本节由 `/speckit.tasks` 命令生成，不在 `/speckit.plan` 中创建。

### 实现任务列表

1. **修改 `SpreadOrderManager.__init__`**
   - 添加 `_pending_updates: Dict[str, List[Dict]]` 缓存字典
   - 添加 `_update_lock: asyncio.Lock` 并发锁
   - 添加 `_cache_ttl: int = 300` 配置（5分钟TTL）

2. **修改 `update_order_status()` 方法**
   - 添加早期订单ID检查
   - 如果 `current_order_id` 为 `None`，缓存更新
   - 如果 `current_order_id` 已设置但与接收的ID不匹配，也尝试缓存
   - 添加详细的调试日志

3. **修改 `place_spread_maker_order()` 方法**
   - 在设置 `current_order_id` 后立即检查缓存
   - 如果有该订单的缓存更新，立即应用

4. **添加 `_apply_pending_updates()` 私有方法**
   - 应用指定订单ID的所有缓存更新
   - 验证订单ID匹配
   - 按时间戳顺序处理更新
   - 清理已应用的缓存

5. **添加 `_cleanup_cache()` 私有方法**
   - 清理超过TTL的缓存
   - 清理已完成订单的缓存
   - 防止缓存超过最大限制

6. **添加单元测试 `tests/test_order_manager.py`**
   - 测试竞态条件场景（订单更新早于订单ID设置）
   - 测试并发更新场景
   - 测试缓存清理机制
   - 测试TTL过期

## 修复验证

### 验证步骤

1. **运行单元测试**
   ```bash
   pytest tests/test_order_manager.py -v
   ```

2. **运行集成测试**
   - 启动spread_arb机器人
   - 观察Extended订单成交后Lighter是否成功开单
   - 检查日志中是否出现"应用缓存的订单更新"

3. **性能验证**
   - 确保订单状态更新延迟 < 10ms
   - 确保内存开销 < 1MB
   - 运行24小时后检查缓存大小（应为0或接近0）

### 成功标准

- ✅ 所有单元测试通过
- ✅ Extended订单成交后Lighter对冲成功率100%
- ✅ `wait_for_fill` 在订单成交后2秒内返回
- ✅ 日志包含竞态条件检测和缓存应用记录
- ✅ 24小时运行后无内存泄漏

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 缓存机制引入新bug | 高 | 完善的单元测试，逐步部署 |
| 性能下降 | 中 | 使用异步锁，最小化锁持有时间 |
| 内存泄漏 | 中 | TTL机制，定期清理，监控 |
| 并发问题 | 高 | 使用asyncio.Lock保护所有共享状态 |

## 复杂度追踪

> **仅在宪法检查有违规必须辩护时填写**

无宪法违规，无需辩护。
