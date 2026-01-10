# Implementation Plan: 价差套利核心问题修复

**Branch**: `009-fix-spread-loss-fees` | **Date**: 2026-01-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-fix-spread-loss-fees/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

本实施计划修复价差套利系统的三个致命问题：
1. **中间价陷阱** - 使用对手价（bid/ask）计算真实价差，替代不可交易的中间价
2. **Post-Only逻辑冲突** - 正确定价maker订单（price_tick偏移），实现真正的0手续费
3. **负期望收益** - 提高开仓阈值从0.06%到0.10%，确保每笔交易有正期望收益

**技术方法**:
- 创建新的`RealSpreadCalculator`类，统一对手价计算逻辑
- 修改maker定价策略，使用`bid - price_tick`或`ask + price_tick`
- 更新配置默认值，提高`min_spread_rate`到0.10%
- 修复仓位平衡计算（使用相减而非绝对值相加）
- 实现多级优先级平仓策略（P1-P5）

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: asyncio, websockets, decimal.Decimal, pytest
**Storage**: 内存状态 + 文件日志（logs/trade.log），暂不引入数据库
**Testing**: pytest
**Target Platform**: Linux服务器（macOS开发，Linux生产）
**Project Type**: single（单一Python项目）
**Performance Goals**:
  - 订单簿更新频率: >10Hz
  - 下单响应时间: P95 <200ms
  - Maker订单成功率: >50%
  - 仓位差异率: <1%
**Constraints**:
  - 所有金融计算使用Decimal（避免浮点误差）
  - 不抛出异常，通过返回值传递错误
  - 对冲失败率<1%
**Scale/Scope**:
  - 同时持仓套利对: 最多3个
  - 每小时开仓: 5-20次（提高阈值后）
  - 24小时数据收集用于参数优化

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

当前项目没有自定义的constitution文件，使用默认模板。检查以下核心原则：

### 代码质量
- ✅ 使用Decimal进行所有金融计算
- ✅ 异步I/O使用async/await
- ✅ 结构化日志记录
- ✅ 错误通过返回值传递，不抛出异常

### 测试
- ✅ TDD方法：先写测试，再实现功能
- ✅ 单元测试覆盖核心计算逻辑
- ✅ 集成测试验证端到端流程

### 可观测性
- ✅ 详细日志记录（DEBUG级别记录计算过程）
- ✅ 关键事件INFO级别记录
- ✅ 成本分解和盈亏归因

### 简单性
- ✅ 不引入数据库（文件+内存足够）
- ✅ 渐进式数据收集（日志→CSV→DB）
- ✅ 复用现有架构，最小化变更

**结论**: ✅ 通过所有质量门

---

## Project Structure

### Documentation (this feature)

```text
specs/009-fix-spread-loss-fees/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output: 技术研究和决策
├── data-model.md        # Phase 1 output: 数据模型定义
├── quickstart.md        # Phase 1 output: 快速开始指南
├── contracts/           # Phase 1 output: 接口契约
│   ├── real_spread_calculator.py
│   ├── maker_order_pricing.py
│   ├── position_balance.py
│   └── data_collection.py
├── checklists/
│   └── requirements.md  # 需求质量检查清单
└── spec.md              # 功能规范文档
```

### Source Code (repository root)

```text
spread/                          # 价差套利模块（主要修改）
├── real_spread_calculator.py    # [NEW] 真实价差计算器
├── cost_calculator.py           # [NEW] 成本分解计算器
├── calculator.py                # [MOD] 使用RealSpreadCalculator
├── bot.py                       # [MOD] 使用对手价、改进平仓策略
├── order_manager.py             # [MOD] 改进maker超时处理
├── config.py                    # [MOD] 更新默认阈值和配置
├── trade_logger.py              # [MOD] 添加成本分解日志
├── models.py                    # [EXT] 扩展数据模型
├── spread_pair.py               # [EXT] 添加新字段
├── position_aggregator.py       # [MOD] 修复仓位平衡计算
├── profit_calculator.py         # [MOD] 使用成本分解
├── hedge_manager.py             # [NO CHANGE]
└── run_spread_arb.py            # [NO CHANGE]

exchanges/                       # 交易所客户端（无变更）
├── extended.py                  # [NO CHANGE]
└── lighter_custom_websocket.py # [NO CHANGE]

tests/                           # 测试文件
├── test_real_spread_calculator.py   # [NEW] 对手价计算测试
├── test_cost_calculator.py          # [NEW] 成本分解测试
├── test_position_balance.py         # [NEW] 仓位平衡测试
├── test_maker_pricing.py            # [NEW] Maker定价测试
├── integration/
│   └── test_real_spread_trading.py  # [NEW] 集成测试
└── (existing test files...)

logs/                            # 日志目录
└── trade.log                   # [AUTO] 交易日志（自动创建）

data/                           # 数据导出目录
├── trades_YYYY_MM_DD.csv      # [AUTO] 交易记录导出
└── orders_YYYY_MM_DD.csv      # [AUTO] 订单记录导出
```

**Structure Decision**: 单一Python项目结构，所有代码在`spread/`模块中。新增文件添加核心功能，现有文件修改最小化以保持兼容性。

---

## Complexity Tracking

> 本功能不违反任何简化原则，无需justify。

本修复遵循以下简化原则：
1. **不引入新依赖** - 使用Python标准库
2. **不引入数据库** - 文件+内存足够
3. **复用现有架构** - 最小化变更
4. **渐进式实现** - 分三个阶段逐步添加功能

---

## Implementation Phases

### Phase 0: Research (已完成)

**输出**: `research.md`

研究内容包括：
1. Extended交易所价格精度（price_tick = 0.01）
2. 数据收集策略（渐进式：日志→CSV→DB）
3. 对手价价差计算标准化
4. Maker订单超时和转换策略
5. 最小价差率阈值确定（0.10%→动态调整）
6. 平仓价格选择验证（价格正确，时机改进）

**关键决策**:
- price_tick = 0.01美元
- 分阶段提高阈值（0.10%开始）
- 条件转换maker超时（检查利润）
- 多级优先级平仓策略

---

### Phase 1: Design (已完成)

**输出**: `data-model.md`, `quickstart.md`, `contracts/*.py`

#### 数据模型
- `RealSpreadOpportunity` - 真实价差机会
- `OrderExecutionDetails` - 订单执行详情
- `TradeCostBreakdown` - 交易成本分解
- `PositionBalance` - 仓位平衡（修复版）

#### 接口契约
- `IRealSpreadCalculator` - 对手价计算接口
- `IMakerPricingStrategy` - Maker定价接口
- `IPositionBalanceCalculator` - 仓位平衡接口
- `IDataCollector` - 数据收集接口
- `ITradeAnalyzer` - 交易分析接口

#### 快速开始
- 配置更新指南
- 核心修复说明
- 数据收集方法
- 故障排除

---

### Phase 2: Implementation (下一步)

**输出**: `tasks.md` (通过 `/speckit.tasks` 命令生成)

主要任务：
1. 创建 `RealSpreadCalculator` 类
2. 创建 `CostCalculator` 类
3. 更新 `calculator.py` 使用新计算器
4. 更新 `config.py` 默认值
5. 修复 `bot.py` 中的仓位平衡计算
6. 改进 `bot.py` 中的平仓策略
7. 更新 `order_manager.py` maker超时处理
8. 扩展 `trade_logger.py` 添加成本字段
9. 编写单元测试
10. 编写集成测试

---

## Dependencies

### 内部依赖
- `spread/config.py` - 配置类
- `spread/models.py` - 现有数据模型
- `spread/spread_pair.py` - 套利对类
- `exchanges/extended.py` - Extended客户端
- `exchanges/lighter_custom_websocket.py` - Lighter客户端

### 外部依赖
- Python 3.11+ (asyncio, decimal)
- pytest (测试)

### 无需新增依赖
- ✅ 不使用pandas（第一、二阶段）
- ✅ 不使用数据库（第一、二阶段）
- ✅ 不引入新的Web框架

---

## Risk Assessment

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| maker定价策略仍然失败 | 中 | 高 | 监控拒绝率，动态调整price_tick |
| 阈值过高导致无交易 | 低 | 中 | 收集数据后动态调整 |
| 价差计算错误回归 | 低 | 高 | 完整单元测试覆盖 |
| 性能下降 | 低 | 低 | 计算复杂度未增加 |
| 仓位不平衡加剧 | 低 | 中 | 实时监控和警报 |

---

## Success Metrics

### 核心指标
- ✅ 使用真实价差计算，只有正期望才开仓
- ✅ Maker订单成功率 >50%
- ✅ 仓位差异率 <1%
- ✅ 净收益为正（当前负值）

### 改进目标
- ✅ 平均成本率 <0.08%
- ✅ 胜率 >60%
- ✅ 最大回撤 <5%

---

## Next Steps

1. ✅ 完成Phase 0研究
2. ✅ 完成Phase 1设计
3. ⏭️ 运行 `/speckit.tasks` 生成tasks.md
4. ⏭️ 实施核心修复（P0优先级）
5. ⏭️ 测试和验证
6. ⏭️ 部署到测试环境
7. ⏭️ 收集数据并优化
