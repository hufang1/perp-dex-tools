# 功能规范：价差套利磨损修复

**特性分支**: `001-fix-spread-loss`
**创建日期**: 2026-01-10
**状态**: 草稿
**输入**: 用户需求：修复价差套利磨损问题，确保程序能盈利并最大化交易量（卡着最低价差跑）

## 问题分析摘要

根据运行1小时的交易日志分析（`/Users/hufang/Desktop/trade.log`），发现以下关键问题：

### 当前状况
- **总交易量**: 23,519.49 USDT
- **总损耗**: 3.03 USDT（约万1.2磨损）
- **配置的开仓价差阈值**: 0.05%

### 核心问题发现

1. **套利逻辑根本性错误**（`calculator.py:62-91, 93-122`）
   - **做多机会（第62-91行）**: 使用`lighter_bid`（买一价）作为Lighter的卖出价格
     - 当前代码: `lighter_price = lighter_bid`
     - 正确逻辑: Lighter卖出应该用`lighter_ask`（卖一价）
   - **做空机会（第93-122行）**: 使用`lighter_ask`（卖一价）作为Lighter的买入价格
     - 当前代码: `lighter_price = lighter_ask`
     - 正确逻辑: Lighter买入应该用`lighter_bid`（买一价）
   - **这是致命错误**：程序用买卖一价当作卖出价，用卖一价当作买入价！
   - 导致开仓条件判断完全错误，在应该盈利的价差时不交易，在不该交易时亏损开仓

2. **错误的价差率计算分母**
   - 做多机会（第66行）: `spread_rate = spread / extended_bid` ✅ 正确
   - 做空机会（第97行）: `spread_rate = spread / lighter_ask` ❌ 错误
     - 应该使用`extended_ask`作为分母
     - 当前计算不反映真实的价差率

3. **Extended下单方式确认**
   - `exchanges/extended.py:259`: `post_only = False`
   - 意味着订单可以立即成交成为taker
   - 实际手续费可能是：maker费用（如果有）或taker费用0.0225%
   - **需要根据实际成交情况确认手续费率**

4. **滑点损耗需要重新评估**
   - 当前0.075%是估算值，缺乏实际数据支持
   - 需要收集实际交易数据来计算真实滑点

## 用户场景与测试

### 用户故事 1 - 修复套利逻辑根本性错误 (优先级: P1)

修复calculator.py中的致命bug：Lighter交易所使用了错误的价格方向（买入用卖一价，卖出用买一价）。

**为什么是P1**: 这是导致所有亏损的根本原因 - 程序用买一价当作卖出价格，导致盈利判断完全错误。

**独立测试**: 可以通过单元测试验证套利机会识别的准确性，构造测试用例验证价差计算。

**验收场景**:

1. **Given** Extended买一$3100，卖一$3105，Lighter买一$3095，卖一$3098，**When** 计算做多机会，**Then** 系统检查Extended买一($3100) < Lighter卖一($3098)，条件不满足，不开仓

2. **Given** Extended买一$3090，卖一$3095，Lighter买一$3098，卖一$3103，**When** 计算做多机会，**Then** 系统检查Extended买一($3090) < Lighter卖一($3103)，条件满足，价差=$3103-$3090=$13，使用lighter_ask($3103)作为Lighter卖出价

3. **Given** Extended买一$3095，卖一$3105，Lighter买一$3090，卖一$3098，**When** 计算做空机会，**Then** 系统检查Extended卖一($3105) > Lighter买一($3090)，条件满足，使用lighter_bid($3090)作为Lighter买入价

---

### 用户故事 2 - 实现Maker/Taker混合下单策略 (优先级: P1)

Extended使用maker挂单节省手续费，Lighter使用taker立即对冲，最大化利润。

**为什么是P1**: 如果Extended maker费率低于taker，这个优化可以显著提升每笔交易的净利润。

**独立测试**: 通过模拟市场环境测试maker单的超时机制和taker成交可靠性。

**验收场景**:

1. **Given** Extended maker费率 < taker费率，**When** 执行开仓，**Then** Extended在买一/卖一挂post_only maker单，等待成交

2. **Given** Extended maker单未成交，**When** 超过设定时间（如5秒），**Then** 取消maker单或转为taker立即成交

3. **Given** Extended maker单成交后，**When** 立即执行Lighter对冲，**Then** Lighter使用taker方式（使用对手价）确保成交

4. **Given** Lighter订单簿深度不足，**When** taker订单可能无法完全成交，**Then** 拒绝开仓或减小交易量

---

### 用户故事 3 - 修复价差率计算分母错误 (优先级: P1)

修复做空机会的价差率计算分母错误，确保计算的价差率反映真实情况。

**为什么是P1**: 分母错误导致价差率计算不准确，影响开仓决策。

**独立测试**: 通过单元测试验证价差率计算的数学正确性。

**验收场景**:

1. **Given** Extended卖一$3105，Lighter买一$3090，**When** 计算做空价差率，**Then** 价差率 = ($3105 - $3090) / $3105 = 0.483%（分母是extended_ask，不是lighter_ask）

2. **Given** 任何市场条件，**When** 计算做空机会，**Then** 价差率分母必须使用extended_ask（Extended卖一价）

---

### 用户故事 4 - 收集实际交易数据确定成本结构 (优先级: P2)

运行程序收集实际交易数据，确认Extended的真实手续费率（maker vs taker比例）和实际滑点。

**为什么是P2**: 在修复算法bug后，需要准确的数据来优化阈值策略。

**独立测试**: 分析交易日志，统计实际手续费和滑点。

**验收场景**:

1. **Given** 修复后的程序运行，**When** 执行100笔交易，**Then** 日志清晰显示每笔交易的手续费明细

2. **Given** 交易日志数据，**When** 分析实际成交价格与预期价格，**Then** 计算出真实的平均滑点

---

### 用户故事 5 - 实现详细交易日志记录 (优先级: P1)

在开仓、平仓、对冲等所有关键环节记录详细数据，统一输出到`logs/trade.log`，用于后续策略优化。

**为什么是P1**: 没有详细的日志数据，无法准确评估策略表现和优化参数。这些数据是分析手续费、滑点、成交率的关键依据。

**独立测试**: 运行程序并检查`logs/trade.log`文件格式和内容完整性。

**验收场景**:

1. **Given** 程序启动，**When** 初始化完成，**Then** 日志记录启动时间、配置参数（手续费率、阈值、超时设置等）

2. **Given** 检测到价差机会，**When** 计算套利可行性，**Then** 日志记录：
   - 时间戳（精确到毫秒）
   - Extended价格（bid/ask/mid）
   - Lighter价格（bid/ask/mid）
   - 价差计算详情（绝对价差、价差率）
   - 预期利润率
   - Lighter深度检查结果（前3档深度、总深度）
   - 决策结果（开仓/拒绝及原因）

3. **Given** 执行开仓，**When** Extended下单，**Then** 日志记录：
   - 订单类型（maker/taker）
   - 挂单价格
   - 挂单时间
   - 等待成交过程（每秒检查一次状态）
   - 成交时间（如有）
   - 成交价格
   - 成交数量
   - 等待时长
   - 订单ID

4. **Given** Extended成交后，**When** 执行Lighter对冲，**Then** 日志记录：
   - 对冲方向（buy/sell）
   - 预期成交价格（对手价）
   - 实际下单时间
   - 实际成交价格
   - 实际成交数量
   - 对冲延迟（Extended成交到Lighter下单的时间差）
   - Lighter订单ID
   - 滑点 = 预期价格 - 实际价格

5. **Given** 开仓完成，**When** 创建套利对，**Then** 日志记录：
   - 套利对ID
   - 开仓方向（long/short）
   - Extended成交详情（价格、数量、时间、订单类型、手续费预估）
   - Lighter成交详情（价格、数量、时间、订单类型、手续费预估）
   - 开仓时价差
   - 预期盈亏（如果立即平仓）
   - 总成本预估（手续费+滑点）

6. **Given** 检测到平仓机会，**When** 计算平仓，**Then** 日志记录：
   - 当前持仓时间
   - 当前Extended价格
   - 当前Lighter价格
   - 当前未实现盈亏
   - 平仓触发原因（盈利目标/时间/止损）
   - 预期平仓价格
   - 预期平仓盈亏

7. **Given** 执行平仓，**When** Extended和Lighter平仓，**Then** 日志记录类似开仓的详细信息（价格、时间、滑点、手续费）

8. **Given** 平仓完成，**When** 计算最终盈亏，**Then** 日志记录：
   - 开仓到平仓的完整时间线
   - Extended盈亏（价格变化）
   - Lighter盈亏（价格变化）
   - 总手续费明细（开仓Extended、平仓Extended及类型）
   - 总滑点明细
   - 净利润
   - 收益率
   - 盈亏原因分析（价差变化、手续费、滑点各自的影响）

9. **Given** Maker单超时，**When** 转为taker或取消，**Then** 日志记录：
   - Maker单挂单时长
   - 超时原因
   - 处理方式（转taker/取消）
   - 如果转taker：新的成交价格、额外手续费成本

10. **Given** 程序运行中，**When** 每小时，**Then** 日志记录统计摘要：
    - 总交易次数
    - 开仓次数（按方向分类）
    - 平仓次数
    - 当前持仓数
    - 总交易量
    - 总盈亏
    - 平均单笔盈亏
    - Maker单成交率
    - 平均手续费（分别统计maker和taker）
    - 平均滑点
    - Extended下单到成交平均延迟
    - Extended成交到Lighter对冲平均延迟
    - 最小/最大/平均持仓时间
    - 胜率（盈利交易数/总平仓数）

---

### 用户故事 6 - 增强交易监控日志 (优先级: P2)

添加详细的盈亏追踪日志，帮助实时验证算法是否按预期工作。

**为什么是P2**: 对问题排查和性能监控非常重要，但不影响核心功能。

**独立测试**: 运行程序并检查日志输出格式和内容。

**验收场景**:

1. **Given** 程序运行中，**When** 执行开仓，**Then** 日志显示：开仓价差、预期盈亏、手续费预估、净利润预估

2. **Given** 程序运行中，**When** 执行平仓，**Then** 日志显示：实际盈亏、手续费明细、与预期对比

3. **Given** 定期统计报告，**When** 每小时输出，**Then** 显示：总交易量、总盈亏、胜率、平均持仓时间

---

### 用户故事 7 - 实现动态价差阈值 (优先级: P3)

根据市场波动性和历史滑点数据，动态调整最小开仓阈值，在确保盈利的前提下最大化交易量。

**为什么是P3**: 优化功能，可以进一步提升收益，但不是修复核心bug所必需。

**独立测试**: 通过模拟市场环境测试阈值动态调整逻辑。

**验收场景**:

1. **Given** 市场波动性高，**When** 滑点增大，**Then** 阈值自动上调以保护利润

2. **Given** 市场稳定流动性好，**When** 滑点减小，**Then** 阈值自动下调以增加交易频率

---

### 边界情况

- **价格快速波动**: 当价差在开仓决策瞬间大幅变化，系统如何处理？日志如何记录这种变化？
- **部分成交**: 当Extended订单部分成交，对冲是否按实际成交数量执行？日志记录实际成交数量？
- **对冲失败**: 当Lighter对冲失败，未对冲仓位如何处理？日志是否记录失败原因和后续处理？
- **订单簿深度不足**: 当Lighter深度不足以完成对冲，是否拒绝开仓？日志记录深度检查详情？
- **负价差持续**: 当市场长时间出现负价差（不适合套利），程序是否自动暂停？日志记录暂停原因和时长？
- **日志写入失败**: 当日志文件写入失败（磁盘满、权限问题等），程序是否继续运行？是否有备用日志机制？
- **日志文件过大**: 当`logs/trade.log`文件超过一定大小（如100MB），是否自动归档或分割？
- **时间戳同步**: 当系统时间不准确或调整，时间戳如何处理？是否使用NTP同步？
- **并发写入**: 当多个交易同时需要写入日志，如何保证日志顺序和完整性？
- **日志解析**: 后续如何解析日志进行数据分析？是否需要提供日志解析工具？

## 需求

### 功能需求

- **FR-001**: 系统必须使用正确的价格进行套利判断 - 做多机会检查Extended买一 < Lighter卖一，使用lighter_ask作为Lighter卖出价；做空机会检查Extended卖一 > Lighter买一，使用lighter_bid作为Lighter买入价
- **FR-002**: 系统必须正确计算价差率 - 做多机会使用Extended买一作为分母，做空机会使用Extended卖一作为分母
- **FR-003**: 系统必须实现maker/taker混合下单策略：
  - Extended使用post_only maker单挂单，等待成交以节省手续费
  - 设置maker单超时机制（如5秒），超时后取消或转为taker
  - Extended成交后立即使用taker方式在Lighter对冲
- **FR-004**: 系统必须验证Lighter taker成交的可靠性：
  - 开仓前检查Lighter订单簿深度是否足够
  - 使用对手价计算预期成交价格
  - 如果深度不足，拒绝开仓或减小交易量
- **FR-005**: 系统必须记录详细的交易日志到`logs/trade.log`，包括以下内容：
  - **启动日志**: 启动时间、完整配置参数（手续费率、阈值、超时、数量等）
  - **价差机会检测**: 时间戳、双方完整价格、价差计算过程、深度检查结果、决策结果
  - **Extended下单**: 订单类型、挂单价格、挂单时间、成交时间、成交价格、等待时长、订单ID
  - **Lighter对冲**: 对冲方向、预期价格、实际价格、对冲延迟、滑点、订单ID
  - **开仓完成**: 套利对ID、双方成交详情、价差、预期盈亏、成本预估
  - **平仓检测**: 持仓时间、当前价格、未实现盈亏、触发原因、预期平仓盈亏
  - **平仓执行**: 类似开仓的详细信息
  - **平仓完成**: 完整时间线、双方盈亏、手续费明细、滑点明细、净利润、盈亏分析
  - **Maker单超时**: 挂单时长、处理方式、额外成本（如转taker）
  - **每小时统计**: 所有关键指标的汇总（交易量、盈亏、胜率、手续费、滑点、延迟、持仓时间等）
- **FR-006**: 日志格式要求：
  - 使用统一的日志格式，便于后续解析和分析
  - 所有时间戳精确到毫秒
  - 所有价格和数量使用Decimal类型，保持精度
  - 使用结构化格式（如JSON或清晰的键值对），便于程序化分析
  - 每条日志包含日志级别和事件类型标签
- **FR-007**: 系统必须提供实时统计信息，包括总交易量、净盈亏、胜率、平均手续费（分maker/taker）、平均滑点、maker成交率等指标
- **FR-008**: [待收集实际数据后确定] 系统必须将最小开仓阈值设置为覆盖所有实际成本的值

### 关键实体

- **价差机会**: 包含方向（买入/卖出）、价差率、预期利润率、执行价格、数量等属性
- **套利对**: 包含开仓和平仓的完整交易记录，用于追踪实际盈亏
- **交易统计**: 聚合所有交易的盈亏数据，用于评估策略效果
- **日志条目**: 包含时间戳、事件类型、事件详情、相关数据等字段

### 日志格式示例

以下是`logs/trade.log`中应记录的日志格式示例（使用JSON格式便于解析）：

#### 启动日志
```json
{
  "timestamp": "2026-01-10T05:00:00.000Z",
  "level": "INFO",
  "event_type": "SYSTEM_START",
  "data": {
    "config": {
      "ticker": "ETH",
      "order_quantity_usdt": "35",
      "min_spread_rate": "0.0005",
      "latency_buffer": "0.0001",
      "max_open_pairs": 3,
      "extended_maker_fee_rate": "0.0001",
      "extended_taker_fee_rate": "0.000225",
      "lighter_fee_rate": "0.0",
      "maker_timeout_seconds": 5
    }
  }
}
```

#### 价差机会检测
```json
{
  "timestamp": "2026-01-10T05:01:23.456Z",
  "level": "DEBUG",
  "event_type": "SPREAD_OPPORTUNITY",
  "data": {
    "extended_bid": "3090.00",
    "extended_ask": "3095.00",
    "lighter_bid": "3098.00",
    "lighter_ask": "3103.00",
    "opportunity_type": "long",
    "spread": "13.00",
    "spread_rate": "0.00421",
    "expected_profit_rate": "0.00321",
    "lighter_depth_check": {
      "side": "ask",
      "total_depth_usdt": "5000.00",
      "first_3_levels": [
        {"price": "3103.00", "quantity": "1.5"},
        {"price": "3103.50", "quantity": "2.0"},
        {"price": "3104.00", "quantity": "1.8"}
      ]
    },
    "decision": "OPEN",
    "decision_reason": "价差率0.421%大于阈值0.05%"
  }
}
```

#### Extended下单
```json
{
  "timestamp": "2026-01-10T05:01:23.500Z",
  "level": "INFO",
  "event_type": "EXTENDED_ORDER_PLACED",
  "data": {
    "order_type": "MAKER",
    "post_only": true,
    "side": "buy",
    "price": "3090.00",
    "quantity": "0.01133",
    "order_id": "2009862027288645632",
    "placed_at": "2026-01-10T05:01:23.500Z"
  }
}
```

#### Extended成交
```json
{
  "timestamp": "2026-01-10T05:01:25.123Z",
  "level": "INFO",
  "event_type": "EXTENDED_FILLED",
  "data": {
    "order_id": "2009862027288645632",
    "filled_price": "3090.00",
    "filled_quantity": "0.01133",
    "placed_at": "2026-01-10T05:01:23.500Z",
    "filled_at": "2026-01-10T05:01:25.123Z",
    "wait_duration_ms": 1623,
    "estimated_fee": "0.00695",
    "fee_type": "MAKER"
  }
}
```

#### Lighter对冲
```json
{
  "timestamp": "2026-01-10T05:01:25.150Z",
  "level": "INFO",
  "event_type": "LIGHTER_HEDGE",
  "data": {
    "side": "sell",
    "expected_price": "3103.00",
    "expected_quantity": "0.01133",
    "hedge_delay_ms": 27,
    "order_id": "423708",
    "actual_price": "3102.80",
    "actual_quantity": "0.01133",
    "slippage_usdt": "0.00226",
    "slippage_rate": "0.00007",
    "estimated_fee": "0.0"
  }
}
```

#### 开仓完成
```json
{
  "timestamp": "2026-01-10T05:01:25.200Z",
  "level": "INFO",
  "event_type": "POSITION_OPENED",
  "data": {
    "pair_id": 1,
    "direction": "long",
    "extended": {
      "side": "buy",
      "price": "3090.00",
      "quantity": "0.01133",
      "order_id": "2009862027288645632",
      "fee_type": "MAKER",
      "estimated_fee": "0.00695"
    },
    "lighter": {
      "side": "sell",
      "price": "3102.80",
      "quantity": "0.01133",
      "order_id": "423708",
      "slippage_usdt": "0.00226"
    },
    "open_spread": "12.80",
    "open_spread_rate": "0.00414",
    "estimated_profit_if_closed_now": "-0.0069",
    "total_estimated_cost": "0.00921"
  }
}
```

#### 平仓完成
```json
{
  "timestamp": "2026-01-10T05:02:45.300Z",
  "level": "INFO",
  "event_type": "POSITION_CLOSED",
  "data": {
    "pair_id": 1,
    "direction": "long",
    "holding_time_seconds": 80.1,
    "open_extended_price": "3090.00",
    "open_lighter_price": "3102.80",
    "close_extended_price": "3095.00",
    "close_lighter_price": "3108.50",
    "extended_pnl": "0.0565",
    "lighter_pnl": "-0.0644",
    "gross_pnl": "-0.0079",
    "fees": {
      "open_extended": "0.00695",
      "open_extended_type": "MAKER",
      "close_extended": "0.00696",
      "close_extended_type": "MAKER",
      "open_lighter": "0.0",
      "close_lighter": "0.0",
      "total_fees": "0.01391"
    },
    "slippage": {
      "open_lighter": "0.00226",
      "close_lighter": "0.00340",
      "total_slippage": "0.00566"
    },
    "net_pnl": "-0.02157",
    "return_rate": "-0.00054",
    "close_reason": "TIME_PROFIT",
    "timeline": {
      "opened_at": "2026-01-10T05:01:25.200Z",
      "closed_at": "2026-01-10T05:02:45.300Z"
    }
  }
}
```

#### 每小时统计
```json
{
  "timestamp": "2026-01-10T06:00:00.000Z",
  "level": "INFO",
  "event_type": "HOURLY_STATISTICS",
  "data": {
    "period": {
      "start": "2026-01-10T05:00:00.000Z",
      "end": "2026-01-10T06:00:00.000Z"
    },
    "trading": {
      "total_opportunities": 156,
      "opens": 23,
      "opens_long": 15,
      "opens_short": 8,
      "closes": 20,
      "current_positions": 3
    },
    "volume": {
      "total_volume_usdt": "805.00",
      "avg_volume_per_trade_usdt": "35.00"
    },
    "pnl": {
      "total_pnl_usdt": "2.35",
      "avg_pnl_per_trade_usdt": "0.1175",
      "winning_trades": 15,
      "losing_trades": 5,
      "win_rate": "0.75"
    },
    "fees": {
      "total_fees_usdt": "0.82",
      "avg_maker_fee_usdt": "0.035",
      "avg_taker_fee_usdt": "0.078",
      "maker_order_count": 35,
      "taker_order_count": 8,
      "maker_fill_rate": "0.875"
    },
    "slippage": {
      "total_slippage_usdt": "0.45",
      "avg_slippage_per_trade_usdt": "0.0225",
      "avg_slippage_rate": "0.00006"
    },
    "timing": {
      "avg_extended_fill_time_ms": 1850,
      "avg_hedge_delay_ms": 35,
      "min_holding_time_sec": 45.2,
      "max_holding_time_sec": 180.5,
      "avg_holding_time_sec": 95.3
    }
  }
}
```

## 成功标准

### 可衡量的结果

- **SC-001**: 修复后程序运行1小时，净盈亏必须为正（之前为-3.03USDT）
- **SC-002**: 程序能够正确识别套利机会 - 只有当Extended买一 < Lighter卖一（做多）或Extended卖一 > Lighter买一（做空）时才开仓
- **SC-003**: `logs/trade.log`记录所有关键事件的详细数据，格式统一且便于解析
- **SC-004**: 每条交易记录包含完整的时间线、价格明细、手续费、滑点数据
- **SC-005**: 每小时统计输出包含所有关键指标（交易量、盈亏、胜率、手续费、滑点、延迟等）
- **SC-006**: [待收集数据后更新] 每笔交易的平均净利润率必须 > 0（扣除所有实际成本后）
- **SC-007**: [待收集数据后更新] 在确保盈利的前提下，最大化交易量

## 待确认事项

以下事项需要在修复算法bug后，通过实际运行程序来确认：

1. **Extended手续费率结构确认**
   - 当前配置只设置了extended_fee_rate = 0.0225%，需要确认这是taker还是maker费率
   - Extended通常有不同的maker和taker费率，需要获取完整费率表
   - 如果maker费率 < taker费率，maker/taker混合策略能显著提升利润
   - 需要统计实际交易中maker单的成交率

2. **Maker单成交率评估**
   - 需要测试Extended maker单的实际成交情况
   - 统计maker单平均成交时间
   - 评估超时设置（建议5秒）是否合理
   - 如果成交率太低，可能需要调整策略或降低使用maker单的频率

3. **Lighter taker成交可靠性**
   - 需要验证Lighter使用taker方式（对手价）是否能稳定成交
   - 测试订单簿深度检查的准确性
   - 确认是否有滑点过大的情况

4. **实际滑点测量**
   - 从交易日志中提取：预期价格 vs 实际成交价格
   - 分别统计maker单和taker单的滑点
   - 计算真实滑点分布和平均值

5. **最优开仓阈值确定**
   - 在收集实际成本数据后重新计算
   - 阈值 = (Extended平均手续费 × 2) + 实际滑点 + 安全边际
   - 考虑maker单成交率对平均手续费的影响
   - 目标是"卡着最低盈利要求跑"

6. **日志数据收集验证**
   - 运行程序后检查`logs/trade.log`是否包含所有必需的数据字段
   - 验证日志格式是否便于后续解析和分析
   - 确认没有遗漏关键事件（如maker单超时、对冲失败等）
   - 测试日志文件在大数据量下的性能表现

## 已知技术约束

1. **手续费结构（待完整确认）**:
   - Extended: 配置中0.0225%，待确认maker和taker的分别费率
   - Lighter: 0%（maker和taker都免费）
   - 每次完整交易包含2次Extended操作 + 2次Lighter操作

2. **Maker单风险**:
   - 挂单可能长时间不成交，浪费机会
   - 需要设置合理的超时机制
   - 需要在价差足够大时才使用maker单（留出时间成本）

3. **Lighter成交风险**:
   - taker方式依赖订单簿深度
   - 深度不足可能导致滑点过大或无法成交
   - 需要严格的事前深度检查

4. **执行延迟**:
   - WebSocket连接延迟
   - 订单执行延迟
   - Maker单等待成交的时间成本
   - 这些延迟可能影响实际成交价格

5. **市场条件**:
   - 套利机会出现频率取决于两个交易所的价差分布
   - 订单簿深度可能限制最大可执行交易量
   - 价差可能快速消失，影响maker单成交
