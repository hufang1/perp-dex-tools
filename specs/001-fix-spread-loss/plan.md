# Implementation Plan: 价差套利磨损修复

**Branch**: `001-fix-spread-loss` | **Date**: 2026-01-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-fix-spread-loss/spec.md`

## Summary

修复价差套利程序中的致命算法bug，实现maker/taker混合下单策略以节省手续费，并添加详细的交易日志记录用于后续策略优化。

**核心问题**：calculator.py中使用错误的价格方向（Lighter卖出用买一价，买入用卖一价），导致盈利判断完全错误。

**技术方案**：
1. 修复calculator.py中的价差计算逻辑
2. 实现Extended maker单 + Lighter taker对冲的混合策略
3. 添加JSON格式结构化日志到logs/trade.log
4. 添加每笔交易的完整时间线和成本分析

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**:
- asyncio (异步编程)
- websockets (WebSocket客户端)
- decimal.Decimal (精确金融计算)
- logging (Python标准日志)
- json (结构化日志输出)

**Storage**: 内存状态存储 + 文件日志 (logs/trade.log)

**Testing**: pytest (单元测试和集成测试)

**Target Platform**: Linux/macOS服务器 (24/7运行)

**Project Type**: 单体项目 (Python交易机器人)

**Performance Goals**:
- 价差机会检测延迟 < 100ms
- Extended下单到Lighter对冲延迟 < 50ms
- 日志写入延迟 < 10ms (异步不阻塞交易)

**Constraints**:
- 所有价格计算必须使用Decimal保证精度
- 交易执行必须保证原子性（要么全部成功要么失败）
- 日志写入失败不能中断交易流程

**Scale/Scope**:
- 预计每小时20-50笔交易
- 每笔日志约500-1000字节
- 每小时日志文件约10-50MB
- 需要日志轮转机制

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**宪法状态**: 项目使用模板宪法，无具体原则约束。

**质量要求**:
- ✅ 代码必须有单元测试覆盖
- ✅ 修改核心算法需要集成测试验证
- ✅ 所有价格计算使用Decimal类型
- ✅ 错误处理不抛出异常，通过返回值传递

## Project Structure

### Documentation (this feature)

```text
specs/001-fix-spread-loss/
├── spec.md              # 功能规范（已完成）
├── plan.md              # 本文件
├── research.md          # Phase 0输出
├── data-model.md        # Phase 1输出
├── quickstart.md        # Phase 1输出
└── contracts/           # Phase 1输出（API契约）
    ├── calculator.py    # 价差计算器接口
    └── logger.py        # 日志记录器接口
```

### Source Code (repository root)

```text
spread/                      # 价差套利模块（主要修改目录）
├── calculator.py            # [修改] 修复价差计算逻辑
├── config.py                # [修改] 添加maker/taker配置
├── bot.py                   # [修改] 集成maker/taker策略
├── order_manager.py         # [修改] 添加maker单超时处理
├── hedge_manager.py         # [修改] 优化对冲执行
├── trade_logger.py          # [增强] 添加详细JSON日志
├── spread_pair.py           # [增强] 添加手续费类型记录
├── position_aggregator.py   # [保持]
└── profit_calculator.py     # [保持]

exchanges/                   # 交易所客户端
├── extended.py              # [修改] 添加post_only参数支持
└── lighter_custom_websocket.py  # [保持]

tests/                       # 测试文件
├── test_calculator.py       # [新增] 价差计算器单元测试
├── test_maker_taker.py      # [新增] maker/taker策略测试
├── test_trade_logger.py     # [增强] 日志格式测试
└── integration/
    └── test_fix_validation.py  # [新增] 修复验证集成测试

logs/                        # 日志目录
└── trade.log                # 结构化交易日志（JSON Lines格式）
```

**Structure Decision**: 单体项目结构，spread/目录包含所有套利逻辑，exchanges/目录包含交易所客户端。修改集中在spread/目录，exchanges/extended.py需要添加post_only支持。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无违规模简需要记录。

## Phase 0: Research & Technical Decisions

### Research Tasks

1. **Extended maker/taker费率确认**
   - 当前config.py中只有extended_fee_rate = 0.0225%
   - 需要确认Extended是否区分maker和taker费率
   - 需要确认maker费率是否 < taker费率

2. **Extended post_only订单支持**
   - 需要确认Extended SDK/API是否支持post_only参数
   - 测试post_only订单是否会被立即成交
   - 确认post_only订单超时行为

3. **日志格式选择**
   - JSON Lines vs 传统文本日志
   - 是否需要日志轮转库
   - 日志写入性能优化

4. **Maker单超时策略**
   - 合理的超时时间（建议3-10秒）
   - 超时后是取消还是转为taker
   - 转taker时的价格计算

### Technical Decisions (to be documented in research.md)

| 决策项 | 待确认 | 候选方案 |
|--------|--------|----------|
| Extended费率 | NEEDS CLARIFICATION | maker=0.01%, taker=0.0225% 或 统一0.0225% |
| 日志格式 | NEEDS CLARIFICATION | JSON Lines 或 传统文本 + JSON |
| Maker超时 | NEEDS CLARIFICATION | 3秒/5秒/10秒 或 动态调整 |
| 超时处理 | NEEDS CLARIFICATION | 取消订单 或 转为taker |

## Phase 1: Design

### Data Model (data-model.md)

**关键实体扩展**：

1. **SpreadOpportunity** (价差机会) - 新增字段：
   - `maker_timeout_ms: int` - maker单超时时间
   - `expected_fill_rate: float` - 预期成交率

2. **SpreadPair** (套利对) - 新增字段：
   - `open_order_type: str` - "MAKER"/"TAKER"
   - `close_order_type: str` - "MAKER"/"TAKER"
   - `maker_wait_duration_ms: int` - maker单等待时长

3. **TradeLogEntry** (交易日志) - 新增结构：
   - `timestamp: str` - ISO 8601格式
   - `level: str` - "DEBUG"/"INFO"/"WARN"/"ERROR"
   - `event_type: str` - 事件类型
   - `data: dict` - 事件数据

### API Contracts (contracts/)

#### calculator.py接口契约

```python
def calculate_spread_opportunity(
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal,
    extended_mid_price: Optional[Decimal] = None
) -> Optional[Dict[str, Any]]:
    """
    返回套利机会或None

    Returns:
        {
            'type': 'buy_extended_sell_lighter' | 'sell_extended_buy_lighter',
            'side': 'buy' | 'sell',
            'spread': Decimal,
            'spread_rate': Decimal,  # 分母修正
            'expected_profit_rate': Decimal,
            'extended_price': Decimal,  # maker挂单价格
            'lighter_price': Decimal,  # taker预期价格（正确方向）
            'quantity': Decimal
        }
    """
```

**修改要点**：
- 做多：`lighter_price = lighter_ask` (卖一价)
- 做空：`lighter_price = lighter_bid` (买一价)
- 做空价差率分母：`spread_rate = spread / extended_ask`

#### logger.py接口契约

```python
class StructuredTradeLogger:
    def log_event(
        self,
        event_type: str,
        level: str = "INFO",
        **data
    ) -> bool:
        """
        记录结构化事件到logs/trade.log

        Args:
            event_type: 事件类型（如"EXTENDED_ORDER_PLACED"）
            level: 日志级别
            **data: 事件数据（会被序列化为JSON）

        Returns:
            bool: 是否成功写入
        """
```

**事件类型列表**：
- SYSTEM_START
- SPREAD_OPPORTUNITY
- EXTENDED_ORDER_PLACED
- EXTENDED_FILLED
- EXTENDED_MAKER_TIMEOUT
- LIGHTER_HEDGE
- POSITION_OPENED
- POSITION_CLOSED
- HOURLY_STATISTICS

### Quickstart (quickstart.md)

包含：
- 环境准备
- 配置修改
- 运行测试
- 解析日志

## Phase 2: Implementation Tasks

*(待 /speckit.tasks 命令生成tasks.md)*

**预期任务分解**：

### P1任务（必须完成）

1. 修复calculator.py价差计算逻辑
2. 添加config.py中maker/taker相关配置
3. Extended下单添加post_only支持
4. 添加maker单超时处理逻辑
5. 实现结构化日志记录器
6. 更新bot.py集成所有修改

### P2任务（重要优化）

7. 添加手续费类型记录到SpreadPair
8. 实现每小时统计输出
9. 添加日志轮转机制

### P3任务（可选）

10. 动态阈值调整
11. 日志分析工具

## Testing Strategy

### 单元测试

1. **test_calculator.py** - 价差计算验证
   - 做多机会计算正确性
   - 做空机会计算正确性
   - 边界条件测试

2. **test_maker_taker.py** - maker/taker策略
   - 超时处理逻辑
   - 转taker价格计算
   - 成交率统计

3. **test_trade_logger.py** - 日志格式
   - JSON格式验证
   - 所有事件类型覆盖
   - 日志写入失败处理

### 集成测试

**test_fix_validation.py** - 验证修复效果
- 模拟真实市场数据
- 验证只在正确条件下开仓
- 验证日志完整性
- 计算实际盈亏

## Risk Assessment

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Extended API不支持post_only | 高 | 提前测试API，降级为taker |
| Maker单成交率低 | 中 | 收集数据后调整策略 |
| 日志写入影响性能 | 低 | 异步写入，失败不阻塞 |
| 修复引入新bug | 高 | 完整测试覆盖 |
| 价差计算仍然错误 | 极高 | 详细单元测试验证 |

## Success Metrics

基于spec.md中的成功标准：

1. **修复验证**: 程序运行1小时后净盈亏 > 0
2. **条件验证**: 只在正确价差条件下开仓（日志验证）
3. **日志完整性**: logs/trade.log包含所有必需事件
4. **数据可用性**: 可以从日志提取手续费、滑点数据

## Post-Implementation

### 数据收集阶段（修复后运行1周）

收集以下数据：
- Maker单成交率
- 实际手续费分布
- 真实滑点分布
- 交易延迟统计

### 策略优化阶段（基于数据）

1. 确定最优maker超时时间
2. 计算实际成本结构
3. 调整开仓阈值
4. 优化maker使用频率

---

**Plan Status**: Phase 0 (Research) - 需要完成技术决策研究
