# Implementation Plan: 价差套利平仓逻辑修复与磨损优化

**Branch**: `008-fix-spread-close` | **Date**: 2026-01-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-fix-spread-close/spec.md`

**Note**: 用户要求同时实现所有四个方案。

---

## Summary

修复价差套利策略的平仓逻辑，解决当前策略持续亏损(-2%)和Extended仓位累积问题。同时实现以下4个方案：

1. **方案1**: 修复价差计算和开仓逻辑 - 使用中间价计算价差，根据价差符号决定正确方向
2. **方案2**: 修复平仓价格选择 - 移除机会平仓逻辑，所有平仓使用当前市价
3. **方案3**: 增加价差收敛检查 - 优先在价差收敛时平仓，扩大时延迟
4. **方案4**: 增强诊断日志 - 记录完整的价差快照和对比分析

---

## Technical Context

**语言/版本**: Python 3.11+
**主要依赖**:
- asyncio (异步编程)
- websockets (WebSocket客户端)
- decimal.Decimal (精确金融计算)
- logging (Python标准库)
- pytest (单元测试)

**存储**: 内存状态存储 + 文件日志 (logs/trade.log)
**测试**: pytest + pytest-asyncio
**目标平台**: Linux/macOS服务器
**项目类型**: 单一Python项目 (价差套利交易机器人)

**性能目标**:
- 订单处理延迟: <100ms (价差计算+决策)
- 日志写入延迟: <10ms (异步写入)
- WebSocket消息处理: <50ms

**约束条件**:
- 价格计算必须使用Decimal避免浮点误差
- 平仓价格必须使用订单簿对手价
- 不能引入数据库，状态保持在内存
- 日志输出必须使用简体中文

**规模/范围**:
- 代码修改: ~5个文件 (calculator.py, bot.py, spread_pair.py, trade_logger.py, config.py)
- 新增功能: 价差收敛检查函数、诊断日志模块
- 测试用例: ~20个新增测试

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

根据 `.specify/memory/constitution.md` 检查：

| 原则 | 状态 | 说明 |
|-----|------|------|
| 使用Python标准库 | ✅ PASS | 仅使用asyncio、logging、decimal等标准库 |
| 避免外部依赖 | ✅ PASS | websockets是现有依赖，不新增 |
| 使用Decimal进行金融计算 | ✅ PASS | 所有价格和数量计算使用Decimal |
| 日志写入文件 | ✅ PASS | 继续使用logs/trate.log |
| 内存状态存储 | ✅ PASS | 不引入数据库 |
| 简体中文日志 | ✅ PASS | 所有新增日志使用简体中文 |

**结论**: ✅ **所有检查通过，可以继续Phase 0研究**

---

## Project Structure

### Documentation (this feature)

```text
specs/008-fix-spread-close/
├── plan.md              # 本文件
├── research.md          # Phase 0输出
├── data-model.md        # Phase 1输出
├── quickstart.md        # Phase 1输出
├── contracts/           # Phase 1输出（函数签名契约）
└── tasks.md             # Phase 2输出 (由/speckit.tasks生成)
```

### Source Code (repository root)

```text
spread/                           # 价差套利模块
├── calculator.py                 # 修改: 价差计算逻辑
├── bot.py                        # 修改: 平仓逻辑和触发条件
├── spread_pair.py                # 修改: 增加价差收敛检查
├── trade_logger.py               # 修改: 增强诊断日志
├── config.py                     # 修改: 新增配置参数
├── order_manager.py              # 保持不变
├── hedge_manager.py              # 保持不变
└── position_aggregator.py        # 保持不变

tests/                            # 测试文件
├── test_calculator_fix.py        # 新增: 价差计算测试
├── test_spread_convergence.py    # 新增: 价差收敛检查测试
└── integration/
    └── test_closing_logic.py     # 新增: 平仓逻辑集成测试

logs/
└── trade.log                     # 交易日志（已存在）
```

**结构决策**: 使用现有的单一Python项目结构，仅修改spread/目录下的必要文件，不改变项目架构。

---

## Complexity Tracking

> 本功能没有违反Constitution，无需填写此部分

---

## Phase 0: Research & Decisions

### 研究任务

| 任务 | 描述 | 输出 |
|-----|------|------|
| R001 | 价差计算公式验证 | 确认中间价计算是最佳实践 |
| R002 | 价差收敛判断算法 | 确定如何判断价差是否收敛 |
| R003 | 平仓触发优先级 | 确定合理的平仓条件优先级 |
| R004 | 诊断日志格式 | 确定trade.log中的日志格式 |

### 研究结果

#### R001: 价差计算公式验证

**决策**: 使用中间价计算价差

```python
# 中间价计算
extended_mid = (extended_bid + extended_ask) / 2
lighter_mid = (lighter_bid + lighter_ask) / 2
spread = extended_mid - lighter_mid
```

**理由**:
- 中间价反映真实市场价值中心
- 避免使用单一买一或卖一的极端值
- 与行业最佳实践一致

**替代方案**:
- 使用买一价: 容易受到单边订单影响
- 使用卖一价: 同上

#### R002: 价差收敛判断算法

**决策**: 基于持仓方向判断收敛

```python
def is_spread_converged(pair, current_spread):
    """判断价差是否收敛"""
    spread_change = current_spread - pair.open_spread

    if pair.extended_side == 'buy':
        # 做多价差：期待价差变大（向正方向）
        return spread_change > 0
    else:
        # 做空价差：期待价差变小（向负方向）
        return spread_change < 0
```

**理由**:
- 做多价差（Extended买/Lighter卖）：盈利时价差应向正方向变化
- 做空价差（Extended卖/Lighter买）：盈利时价差应向负方向变化
- 逻辑简单明确，易于验证

#### R003: 平仓触发优先级

**决策**: 5级优先级系统

| 优先级 | 触发条件 | 操作 |
|-------|---------|------|
| P1 | 价差收敛 + 盈利目标达标 | 立即平仓 |
| P2 | 价差收敛 + 任意盈利 | 立即平仓 |
| P3 | 时间到(60秒) + 价差未扩大 | 平仓 |
| P4 | 时间到(60秒) + 小亏损(<1%) | 平仓 |
| P5 | 时间到(60秒) + 大亏损(>=1%) | 延迟平仓，等待反转 |

**理由**:
- 优先锁定利润
- 在价差有利时优先平仓
- 亏损大时延迟平仓，避免确认损失
- 最大持仓时间(180秒)作为最后保障

#### R004: 诊断日志格式

**决策**: 结构化日志格式

```python
# 开仓日志
=== 价差快照 ===
时间戳: 2026-01-10 10:20:22
Extended: bid=$3094.20, ask=$3094.30, mid=$3094.25
Lighter: bid=$3066.10, ask=$3066.55, mid=$3066.32
中间价差: $27.93 (0.9024%)
价差符号: 正 (+)
套利方向: 做空价差 (卖出Extended，买入Lighter)
预期: 价差向负方向收敛时盈利
=================

# 平仓日志
=== 平仓价差分析 ===
套利对ID: 1
开仓时价差: +$27.93 (0.9024%)
当前价差: +$10.50 (0.3393%)
价差变化: -$17.43 (收敛)
价差状态: 收敛 (有利于当前持仓)
平仓原因: P2-价差收敛+小额盈利
未实现盈亏: +$0.05 (0.16%)
===================
```

**理由**:
- 清晰的结构便于解析和分析
- 包含所有关键诊断信息
- 简体中文输出，便于人工审核

---

## Phase 1: Design

### Data Model (data-model.md)

```python
# 价差快照
@dataclass
class SpreadSnapshot:
    timestamp: float
    extended_bid: Decimal
    extended_ask: Decimal
    extended_mid: Decimal
    lighter_bid: Decimal
    lighter_ask: Decimal
    lighter_mid: Decimal
    spread: Decimal              # 中间价差
    spread_rate: Decimal         # 价差率
    spread_sign: str             # "positive" | "negative"
    arbitrage_direction: str     # "long_spread" | "short_spread"

# 价差变化
@dataclass
class SpreadChange:
    open_spread: Decimal
    current_spread: Decimal
    spread_delta: Decimal        # current - open
    spread_change_rate: Decimal  # delta / open
    is_converged: bool           # 是否收敛
    is_favorable: bool           # 是否有利

# 平仓决策
@dataclass
class CloseDecision:
    pair_id: int
    should_close: bool
    priority: int                # 1-5
    reason: str
    spread_change: SpreadChange
    unrealized_pnl: Decimal
    is_warning: bool             # 是否为警告平仓
```

### Contracts (contracts/)

#### calculator.py 契约

```python
def calculate_spread_opportunity_mid(
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal,
    min_spread_rate: Decimal
) -> Optional[Dict[str, Any]]:
    """
    使用中间价计算价差机会

    Returns:
        {
            'spread_mid': Decimal,      # 中间价差
            'spread_rate': Decimal,     # 价差率
            'direction': str,           # 'long_spread' | 'short_spread'
            'extended_side': str,       # 'buy' | 'sell'
            'expected_profit': Decimal  # 预期利润
        }
    """
```

#### spread_pair.py 契约

```python
def is_spread_converged(
    self,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal
) -> Tuple[bool, str]:
    """
    检查价差是否收敛

    Returns:
        (is_converged, status_message)
    """
```

#### bot.py 契约

```python
def _check_close_conditions(
    self,
    pair: SpreadPair,
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal
) -> CloseDecision:
    """
    检查平仓条件（新的5级优先级系统）

    Returns:
        CloseDecision对象
    """
```

#### trade_logger.py 契约

```python
def log_spread_snapshot(
    self,
    snapshot: SpreadSnapshot
) -> bool:
    """记录价差快照"""

def log_close_analysis(
    self,
    decision: CloseDecision
) -> bool:
    """记录平仓分析"""
```

---

## Phase 2: Implementation Tasks

> 由 `/speckit.tasks` 命令生成，此处列出预期的任务结构

### 任务分组

1. **价差计算修复** (calculator.py)
2. **价差收敛检查** (spread_pair.py)
3. **平仓逻辑重构** (bot.py)
4. **诊断日志增强** (trade_logger.py)
5. **配置更新** (config.py)
6. **测试编写** (tests/)

### 依赖关系

```
calculator.py (价差计算)
    ↓
spread_pair.py (收敛检查)
    ↓
bot.py (平仓逻辑)
    ↓
trade_logger.py (日志)
    ↓
tests/ (验证)
```

---

## Success Metrics

| 指标 | 当前值 | 目标值 | 验证方法 |
|-----|-------|-------|---------|
| 策略盈亏率 | -2.0% | +0.3% | 运行1小时后统计 |
| 价差收敛平仓比例 | 未知 | >80% | 分析trade.log |
| Extended/Lighter仓位差异 | >50% | <10% | 实时监控 |
| 平仓决策日志覆盖率 | 0% | 100% | 检查trade.log |

---

## Notes

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| 价差计算错误导致持续亏损 | 高 | 充分测试，用历史数据回测 |
| 平仓逻辑复杂化引入bug | 中 | 保持代码简洁，添加单元测试 |
| 日志输出过多影响性能 | 低 | 使用异步日志，限制详细输出频率 |

### 测试策略

1. **单元测试**: 每个新增函数
2. **集成测试**: 完整的开仓-持仓-平仓流程
3. **回测**: 使用历史价格数据验证方向正确性
4. **模拟测试**: 模拟各种价差变化场景

### 部署计划

1. 先在测试环境运行30分钟
2. 验证价差计算正确性
3. 验证平仓时机合理性
4. 确认无亏损后部署到生产环境
