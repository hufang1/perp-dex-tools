# 实现计划: 修复Extended成交但Lighter未成交的对冲失败问题

**分支**: `001-fix-order-match` | **日期**: 2026-01-09 | **规格**: [spec.md](./spec.md)

**注意**: 本文档由 `/speckit.plan` 命令生成。参见 `.specify/templates/commands/plan.md` 了解执行工作流程。

---

## 摘要

**主要需求**: 修复Extended交易所WebSocket成交通知在订单ID设置前到达导致的竞态条件问题。

**技术方法**: 根据研究结果，当前代码已实现基本的缓存机制，但需要增强日志输出和修复缓存应用时机。关键问题在于 `_apply_pending_updates()` 可能没有被正确调用，或者缓存中的更新没有被正确应用。

**核心修改**:
1. 增强日志输出，区分"通过pending_orders找到订单"和"通过WebSocket缓存处理订单"两种路径
2. 在 `wait_for_fill()` 开始时检查并应用缓存
3. 修复bot的回调处理逻辑，确保缓存更新被正确触发

---

## 技术上下文

**语言/版本**: Python 3.11+
**主要依赖**: asyncio, websockets, decimal.Decimal, logging (Python标准库)
**存储**: 内存状态存储（无数据库）
**测试**: pytest
**目标平台**: Linux服务器
**项目类型**: single (单一项目)
**性能目标**: 缓存应用延迟 < 50ms，熔断触发延迟 < 100ms
**约束**: 日志写入延迟不影响交易执行（< 10ms）
**规模/范围**: 单一功能修复，修改约3个文件，新增约2个测试文件

---

## 宪法检查

*关卡: 必须在Phase 0研究前通过。Phase 1设计后重新检查。*

**结果**: ✅ 通过

当前项目没有配置宪法文件（`.specify/memory/constitution.md` 是模板），因此没有需要检查的关卡。

---

## 项目结构

### 文档（本功能）

```text
specs/001-fix-order-match/
├── plan.md              # 本文件 (/speckit.plan 命令输出)
├── research.md          # Phase 0 输出 - 研究文档
├── data-model.md        # Phase 1 输出 - 数据模型
├── quickstart.md        # Phase 1 输出 - 快速开始指南
├── contracts/           # Phase 1 输出 - API契约
│   └── order-cache-api.md
└── tasks.md             # Phase 2 输出 - 任务列表 (/speckit.tasks 命令 - 非 /speckit.plan 创建)
```

### 源代码（仓库根目录）

```text
spread/                      # 价差套利模块
├── order_manager.py        # 订单管理器 - 【修改】增强日志和缓存逻辑
├── bot.py                  # 套利机器人主逻辑 - 【修改】改进回调处理
└── trade_logger.py         # 交易日志记录器 - 【可能修改】增加熔断日志

exchanges/                  # 交易所客户端
└── extended.py            # Extended交易所客户端 - 【可能修改】优化WebSocket处理

tests/                      # 测试文件
├── test_order_manager.py  # 订单管理器单元测试 - 【新增】
└── integration/
    └── test_race_condition_fix.py  # 竞态条件修复集成测试 - 【新增】

logs/                       # 交易日志目录
└── trade.log             # 交易日志文件（自动创建）
```

**结构决策**: 单一项目结构，所有修改集中在价差套利模块内。不需要新的子模块或独立组件。

---

## 复杂度追踪

> **仅当宪法检查有必须证明合理的违规时填写**

无违规，本部分留空。

---

## Phase 0: 研究阶段

### 研究任务

| 任务 | 状态 | 输出 |
|------|------|------|
| 分析日志，识别问题根因 | ✅ 完成 | research.md |
| 探索代码库，理解现有实现 | ✅ 完成 | research.md |
| 评估替代方案 | ✅ 完成 | research.md |
| 研究最佳实践 | ✅ 完成 | research.md |

### 关键发现

1. **现有代码已实现竞态条件修复**: `spread/order_manager.py` 已经实现了完整的缓存机制
2. **真正的问题**: 日志显示 `current_order_id=None`，说明缓存机制可能没有被正确触发
3. **可能的原因**:
   - `_apply_pending_updates()` 没有被调用
   - 缓存中的更新没有被正确应用
   - bot层面的回调处理有问题

### 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 日志追踪 | 增强日志输出 | 需要追踪缓存的应用过程 |
| 缓存应用时机 | 在多个位置检查 | 只在一个位置检查可能不够 |
| 直接触发对冲 | 使用WebSocket消息直接触发 | 不依赖 `current_order_id` 的设置 |

---

## Phase 1: 设计阶段

### 数据模型

**文件**: [data-model.md](./data-model.md)

**核心实体**:
1. **OrderUpdateCache**: 订单更新缓存条目
2. **PendingUpdateQueue**: 待处理队列
3. **CircuitBreakerState**: 熔断状态

**关系**: `SpreadOrderManager` 包含 `PendingUpdateQueue` 和 `CircuitBreakerState`

### API契约

**文件**: [contracts/order-cache-api.md](./contracts/order-cache-api.md)

**关键接口**:
1. `OrderManager.update_order_status()` - 处理WebSocket订单更新
2. `OrderManager._apply_pending_updates()` - 应用缓存更新
3. `OrderManager._add_pending_update()` - 添加到缓存
4. `OrderManager._cleanup_cache()` - 清理过期缓存
5. `CircuitBreaker.trigger()` - 触发熔断
6. `CircuitBreaker.reset()` - 重置熔断

### 快速开始指南

**文件**: [quickstart.md](./quickstart.md)

**内容**:
- 问题回顾
- 修复方案概览
- 修改文件清单
- 关键修改点
- 测试方法
- 部署步骤
- 验收标准
- 回滚计划
- 常见问题

---

## 下一步行动

### Phase 2: 任务生成

使用 `/speckit.tasks` 命令生成详细的任务列表。

**预期输出**: `specs/001-fix-order-match/tasks.md`

**任务类型**:
1. 代码修改任务（增强日志、修复缓存逻辑）
2. 测试编写任务（单元测试、集成测试）
3. 部署任务（部署到测试环境、监控）
4. 验证任务（验收测试、性能测试）

### 验证清单

- [ ] 所有功能需求都有对应的实现任务
- [ ] 所有测试都有对应的测试任务
- [ ] 所有文档都已更新
- [ ] 所有性能指标都已定义
- [ ] 回滚计划已制定

---

## 参考资料

### 相关文档

- [功能规格说明](./spec.md)
- [研究文档](./research.md)
- [数据模型](./data-model.md)
- [快速开始](./quickstart.md)
- [API契约](./contracts/order-cache-api.md)

### 代码文件

- `spread/order_manager.py` - 订单管理器
- `spread/bot.py` - 套利机器人主逻辑
- `exchanges/extended.py` - Extended交易所客户端
- `spread/hedge_manager.py` - 对冲管理器

### 外部资源

- Python asyncio文档: https://docs.python.org/3/library/asyncio.html
- WebSocket RFC: https://tools.ietf.org/html/rfc6455
- decimal模块文档: https://docs.python.org/3/library/decimal.html

---

**版本**: 1.0 | **创建**: 2026-01-09 | **最后更新**: 2026-01-09
