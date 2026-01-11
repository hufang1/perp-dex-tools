# Research Document: 修复订单类型问题并增加交易成功率统计

**Feature**: 001-fix-order-type
**Date**: 2026-01-11
**Status**: Complete

## Overview

本文档记录了对价差套利交易系统中订单类型和成功率统计功能的技术研究，为实现计划提供技术决策依据。

## Research Findings

### 1. 当前订单类型实现分析

**发现**: 系统已经具备maker/taker订单切换能力，但配置为默认使用maker订单可能导致挂单未成交问题。

**代码位置**:
- `spread/config.py:91`: `use_maker_orders: bool = False` (当前已设置为False)
- `spread/calculator.py:402-437`: `should_use_maker()` 决策逻辑
- `spread/bot.py:877-912`: 开仓时的maker/taker订单选择逻辑
- `spread/order_manager.py:54-100`: `place_spread_maker_order()` 支持post_only参数

**当前行为**:
1. 系统根据`use_maker_orders`配置和期望收益率决定是否使用maker订单
2. Maker订单使用`post_only=True`参数，taker订单使用`post_only=False`
3. 如果maker订单超时未成交，会尝试转换为taker订单（`convert_to_taker()`）
4. 转换过程中可能出现重复下单或仓位不一致问题

**问题根因**:
- Maker订单可能被拒绝（`convert_to_taker`错误）或超时未成交
- 转换为taker过程中，Lighter可能已经成交，导致仓位数量不一致
- 配置文件中`use_maker_orders=False`，但代码中仍有条件判断可能使用maker

### 2. 仓位一致性验证机制

**发现**: 系统已有仓位聚合器，但未在开仓后进行一致性验证。

**代码位置**:
- `spread/position_aggregator.py`: 仓位聚合和差异计算
- `spread/models.py`: `PositionBalance` 数据模型
- 010-fix-position-imbalance功能已修复仓位平衡计算（使用绝对值）

**当前行为**:
- 系统定期监控仓位状态（每5秒）
- 仓位平衡计算：`diff_qty = abs(extended_qty - lighter_qty)`
- 差异率计算：`imbalance_rate = diff_qty / total_exposure * 100`

**缺失功能**:
- 开仓完成后立即验证仓位一致性
- 检测到不一致时的告警机制
- 失败原因记录和统计

### 3. CSV导出和成功率统计

**发现**: 系统已有CSV导出功能，但未记录成功率相关字段。

**代码位置**:
- `spread/data_collector.py`: CSV导出模块
- `spread/trade_logger.py`: 交易日志记录

**当前CSV格式** (`trades_YYYY_MM_DD.csv`):
```csv
pair_id,open_time,close_time,holding_time_seconds,direction,extended_side,
extended_entry_price,extended_exit_price,extended_quantity,
lighter_entry_price,lighter_exit_price,lighter_quantity,
open_spread,close_spread,realized_pnl,close_reason,close_priority,
order_type,real_spread
```

**缺失字段**:
- 开仓成功/失败状态
- 平仓成功/失败状态
- 失败原因分类
- 仓位上限标识
- 订单类型确认（maker/taker）

### 4. 失败原因分类

**需要定义的失败原因枚举**:
- `INSUFFICIENT_BALANCE`: 余额不足
- `ORDER_REJECTED`: 订单被交易所拒绝
- `NETWORK_TIMEOUT`: 网络超时
- `POSITION_LIMIT`: 仓位上限
- `PRICE_SLIPPAGE`: 价格滑点过大
- `PARTIAL_FILL`: 部分成交
- `MAKER_TIMEOUT`: Maker订单超时
- `UNKNOWN`: 未知错误

## Technical Decisions

### Decision 1: 强制使用Taker订单

**选择**: 开仓时强制使用taker订单，禁用maker订单逻辑

**理由**:
1. Maker订单超时转换流程复杂，容易导致仓位不一致
2. Taker订单立即成交，确保对冲同步
3. 用户明确要求所有开仓使用taker

**实施方法**:
1. 修改`bot.py:877-912`，移除`should_use_maker()`调用
2. 强制`use_maker=False`，`post_only=False`
3. 保留配置项`use_maker_orders`但不使用（向后兼容）

**替代方案考虑**:
- 保留maker订单但增加验证：无法解决根本问题，复杂度更高
- 完全移除maker代码：破坏向后兼容性，不可取

### Decision 2: 仓位一致性验证

**选择**: 在开仓完成后立即验证仓位一致性，不一致时记录警告

**理由**:
1. 扩展现有`position_aggregator.py`功能
2. 在`bot.py`的开仓流程后添加验证调用
3. 使用现有的`PositionBalance`模型

**实施方法**:
1. 在`bot.py`的`_open_new_pair()`方法结尾添加仓位验证
2. 调用`position_aggregator.get_position_balance()`
3. 如果`imbalance_rate > threshold`，记录警告日志和失败原因

**阈值设置**:
- 差异数量阈值：`> 0.001 ETH`（约1美元）
- 差异率阈值：`> 10%`

### Decision 3: 成功率统计模块

**选择**: 创建新模块`success_tracker.py`记录和统计交易成功率

**理由**:
1. 独立模块，职责单一
2. 可复用于其他交易操作
3. 易于测试和维护

**实施方法**:
1. 创建`SpreadOperationResult`数据类
2. 创建`SuccessTracker`类管理统计数据
3. 在bot.py中集成tracker调用

**数据结构**:
```python
@dataclass
class SpreadOperationResult:
    timestamp: float
    operation_type: str  # 'open', 'close', 'open_attempt', 'close_attempt'
    status: str  # 'success', 'failed', 'position_limit'
    exchange: str  # 'extended', 'lighter', 'both'
    failure_reason: Optional[str]
    order_id: Optional[str]
    quantity: Decimal
    price: Decimal
```

### Decision 4: CSV双语列名

**选择**: CSV列名使用"英文名 | 中文名"格式

**理由**:
1. 用户明确要求双语标识
2. Excel兼容性好（UTF-8 with BOM）
3. 便于数据分析和中文用户理解

**实施方法**:
1. 修改`data_collector.py`的fieldnames
2. 例如：`'operation_status | 操作状态'`

**示例**:
```csv
timestamp | 时间戳,operation_type | 操作类型,status | 状态,
exchange | 交易所,failure_reason | 失败原因,order_id | 订单ID
```

## Integration Points

### 1. 修改bot.py开仓流程

**位置**: `spread/bot.py:877-1000`

**修改内容**:
1. 移除maker订单决策逻辑（第877-906行）
2. 强制使用taker订单（`post_only=False`）
3. 添加仓位一致性验证
4. 添加成功率记录调用

### 2. 扩展data_collector.py

**位置**: `spread/data_collector.py:34-120`

**修改内容**:
1. 添加新字段到CSV导出
2. 支持双语列名
3. 添加成功率统计汇总文件

### 3. 创建success_tracker.py

**位置**: `spread/success_tracker.py` (新建)

**内容**:
1. `SpreadOperationResult` 数据类
2. `SuccessTracker` 类
3. CSV导出功能

## Testing Strategy

### 单元测试
1. 测试taker订单强制逻辑
2. 测试仓位一致性验证
3. 测试成功率统计记录

### 集成测试
1. 测试完整开仓流程（仓位一致性）
2. 测试CSV导出格式
3. 测试失败原因分类

### 手动验证
1. 运行机器人1小时
2. 检查CSV文件格式
3. 验证无maker订单挂单
4. 验证仓位数量一致

## Performance Considerations

1. **成功率统计开销**: 内存操作 + 异步CSV写入，预计 < 5ms/次
2. **仓位验证开销**: 调用现有聚合器，预计 < 10ms/次
3. **CSV写入开销**: 缓冲写入，批量刷新，不影响主循环

## Risks and Mitigations

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Taker手续费增加 | 收益略降 | 可接受，确保成交优先 |
| CSV写入失败 | 数据丢失 | 异常处理，日志记录 |
| 仓位验证误报 | 干扰运行 | 合理阈值，减少误报 |

## Open Questions

无。所有技术决策已明确。
