# hufangperp Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-11

## Active Technologies
- Python 3.10+ (001-fix-lighter-api)
- N/A (状态在内存中，日志写入文件) (001-fix-lighter-api)
- Python 3.11+ (asyncio) + websockets, decimal.Decimal, logging, pytes (002-optimize-spread-arb)
- 状态在内存中,日志写入文件 (N/A数据库) (002-optimize-spread-arb)
- Python 3.11+ logging, decimal.Decimal, pathlib, datetime (001-trade-log)
- Python 3.11+ (asyncio) + websockets, decimal.Decimal, logging (Python标准库) (001-optimize-monitor)
- Python 3.10+ + asyncio, websockets, decimal.Decimal, logging, python-dotenv, pydantic, pytes (004-unify-config)
- In-memory configuration from Python config.py files; .env files for credentials (004-unify-config)
- Python 3.11+ + asyncio, websockets, decimal.Decimal, logging (Python标准库) (005-unify-position-monitor)
- 内存状态存储，日志写入文件 (005-unify-position-monitor)
- 内存状态存储（无数据库） (006-fix-lighter-close)
- 内存状态存储 + 文件日志 (logs/trade.log) (001-fix-spread-loss)
- Python 3.10+ + dataclasses (用于数据模型) (Phase 4-7: 平仓逻辑修复)
- **Python 3.11+ + dataclasses + csv** (009-fix-spread-loss-fees: 核心修复)
- Python 3.11+ + asyncio, websockets, decimal.Decimal, logging, csv (Python标准库) (001-spread-recorder)
- 本地CSV文件系统存储 (001-spread-recorder)
- Python 3.10.19 + websockets 12.0+, x10-python-trading-starknet 0.0.10, lighter-sdk 0.1.4, pytest, decimal.Decimal (010-fix-position-imbalance)
- 内存状态存储 + 文件日志（logs/trade.log） + CSV导出（data/） (010-fix-position-imbalance)
- Python 3.11+ + asyncio, websockets, decimal.Decimal, logging, pytest, dataclasses, csv (001-fix-order-type)
- Python 3.10+ (primarily using 3.11+ features) (011-fix-lighter-hedge)

- **Python 3.11+**: 主要编程语言
- **asyncio**: 异步编程框架
- **websockets**: WebSocket客户端库
- **decimal.Decimal**: 精确的金融数值计算
- **pytest**: 单元测试框架
- **logging**: Python标准日志库（用于交易日志）
- **dataclasses**: 数据类（用于SpreadSnapshot, SpreadChange, CloseDecision, PositionBalance, TradeCostBreakdown）
- **csv**: CSV数据导出（用于交易分析）

## Project Structure

```text
spread/                    # 价差套利模块
├── order_manager.py       # 订单管理器（扩展交易所）
├── hedge_manager.py       # 对冲管理器（Lighter交易所）
├── bot.py                 # 套利机器人主逻辑
├── calculator.py          # 价差计算器
├── real_spread_calculator.py  # 真实价差计算器（对手价）
├── cost_calculator.py     # 成本分解计算器
├── spread_pair.py         # 套利对数据模型
├── trade_logger.py        # 交易日志记录器
├── spread_recorder.py     # 价差实时记录器（001-spread-recorder）
├── config.py              # 配置类
├── models.py              # 数据模型
├── position_aggregator.py # 持仓聚合器
├── profit_calculator.py   # 收益计算器
├── data_collector.py      # 数据收集器（CSV导出）
├── trade_analyzer.py      # 交易分析器
├── safety_monitor.py      # [NEW] 安全监控器（010-fix-position-imbalance）
├── adaptive_threshold_manager.py # [NEW] 动态阈值管理器（010-fix-position-imbalance）
└── success_tracker.py     # [NEW] 成功率追踪器（001-fix-order-type）

exchanges/                 # 交易所客户端
├── extended.py           # Extended交易所客户端
└── lighter_custom_websocket.py  # Lighter WebSocket客户端

tests/                     # 测试文件
├── test_order_manager.py  # 订单管理器单元测试
├── test_trade_logger.py  # 交易日志单元测试
├── test_spread_recorder.py  # 价差记录器单元测试（001-spread-recorder）
├── test_closing_logic.py         # 平仓价格选择逻辑测试（Phase 4）
├── test_spread_convergence.py    # 价差收敛检查测试（Phase 5）
├── test_enhanced_trade_logger.py # 增强诊断日志测试（Phase 6）
├── test_real_spread_calculator.py  # 对手价计算测试
├── test_cost_calculator.py         # 成本分解测试
├── test_position_balance_fix.py    # [NEW] 仓位平衡计算修复测试（010-fix-position-imbalance）
├── test_safety_monitor.py          # [NEW] 安全监控测试（010-fix-position-imbalance）
├── test_adaptive_threshold_manager.py # [NEW] 动态阈值测试（010-fix-position-imbalance）
└── integration/
    ├── test_trade_logging.py  # 交易日志集成测试
    ├── test_spread_recorder_integration.py  # 价差记录器集成测试（001-spread-recorder）
    └── test_circuit_breaker_integration.py  # [NEW] 熔断机制集成测试（010-fix-position-imbalance）

logs/                      # 交易日志目录
└── trade.log             # 交易日志文件（自动创建）

data/                      # 数据导出目录
├── trades_YYYY_MM_DD.csv  # 交易记录导出（自动创建）
├── orders_YYYY_MM_DD.csv  # 订单记录导出（自动创建）
└── spreads_YYYY_MM_DD.csv # 价差记录导出（001-spread-recorder，自动创建）
```

## Commands

```bash
# 运行单元测试
pytest tests/test_order_manager.py -v

# 运行交易日志测试
pytest tests/test_trade_logger.py -v

# 运行价差记录器测试
pytest tests/test_spread_recorder.py -v
pytest tests/integration/test_spread_recorder_integration.py -v

# 运行P0/P1安全监控测试（010-fix-position-imbalance）
pytest tests/test_position_balance_fix.py -v
pytest tests/test_safety_monitor.py -v
pytest tests/test_adaptive_threshold_manager.py -v
pytest tests/integration/test_circuit_breaker_integration.py -v

# 运行所有测试
pytest tests/ -v

# 运行价差套利机器人
python spread/bot.py --ticker ETH --size 35 --max-pairs 3

# 运行对冲模式
python hedge/hedge_mode.py --exchange extended --ticker ETH --size 0.01 --iter 20

# 查看交易日志
cat logs/trade.log

# 查看价差记录CSV
cat data/spreads_YYYY_MM_DD.csv
```

## Code Style

- **异步函数**: 所有I/O操作使用async/await
- **日志**: 使用logging模块，debug级别记录详细信息，info级别记录关键事件
- **数值计算**: 使用Decimal进行所有金融计算，避免浮点数精度问题
- **错误处理**: 不抛出异常，通过返回值传递错误信息

## Recent Changes
- 013-fix-order-timeout: Added Python 3.11+ + asyncio, websockets, decimal.Decimal, logging, pytest, dataclasses
- 011-fix-lighter-hedge: Added Python 3.10+ (primarily using 3.11+ features)
- 001-fix-order-type: Added Python 3.11+ + asyncio, websockets, decimal.Decimal, logging, pytest, dataclasses, csv

### 001-fix-order-type: 订单类型修复和成功率统计（2026-01-11）
**核心修复**: 强制使用taker订单，移除maker订单逻辑，实现成功率统计和仓位一致性验证

**User Story 1 - 强制Taker订单**:
1. **订单类型强制** (spread/bot.py)
   - 开仓强制使用taker订单（post_only=False）
   - 使用对手价：买单用ask，卖单用bid
   - 移除maker订单超时等待和convert_to_taker逻辑

2. **配置更新** (spread/config.py)
   - use_maker_orders=False（确认默认值）
   - 保留maker相关配置但不再使用

3. **日志记录** (spread/trade_logger.py)
   - 记录订单类型（order_type, post_only, is_rejected）
   - 记录"使用taker订单"日志

**User Story 2 - 仓位一致性验证**:
1. **PositionConsistencyCheck模型** (spread/models.py)
   - 验证开仓后Extended和Lighter仓位数量一致性
   - 计算差异数量（绝对值）和差异率
   - 支持可配置阈值（默认0.001 ETH，10%）

2. **验证方法** (spread/position_aggregator.py)
   - get_position_balance_for_pair方法
   - 返回一致性检查结果（is_consistent, difference, difference_rate）

3. **Bot集成** (spread/bot.py)
   - 开仓后自动验证仓位一致性
   - 记录仓位一致性状态到日志

**User Story 3 - 成功率统计**:
1. **SuccessTracker模块** (spread/success_tracker.py)
   - 记录每次操作结果（OPEN_ATTEMPT/SUCCESS/FAILED, CLOSE_ATTEMPT/SUCCESS/FAILED）
   - 统计成功率和失败原因分布
   - 导出双语CSV（operations_YYYY_MM_DD.csv, success_stats_YYYY_MM_DD.csv）

2. **操作类型枚举** (spread/models.py)
   - OperationType: OPEN_ATTEMPT, OPEN_SUCCESS, OPEN_FAILED, CLOSE_ATTEMPT, CLOSE_SUCCESS, CLOSE_FAILED
   - OperationStatus: PENDING, SUCCESS, FAILED, POSITION_LIMIT
   - ExchangeType: EXTENDED, LIGHTER, BOTH
   - FailureReason: NETWORK_TIMEOUT, INSUFFICIENT_BALANCE, ORDER_REJECTED, POSITION_IMBALANCE, UNKNOWN_ERROR

3. **Bot集成** (spread/bot.py)
   - 开仓/平仓时记录操作结果
   - 统计报告中显示成功率
   - 清理时导出CSV数据

**测试覆盖**:

**配置项** (spread/config.py):

### 010-fix-position-imbalance: 修复仓位失衡和优化开仓标准（2026-01-11）
**重大修复**: 修复Extended 0.21 ETH vs Lighter 0.02 ETH的严重仓位失衡问题，实现安全监控和动态阈值

**P0 - 关键安全修复**:
1. **仓位平衡计算修复** (spread/models.py)
   - 修复PositionBalance.__post_init__: 使用绝对值计算总暴露度和实际差异
   - 完全对冲仓位(0.01 vs -0.01)现在正确显示0%差异率
   - 实际失衡(0.21 vs 0.02)现在正确显示82.6%差异率

2. **SafetyMonitor模块** (spread/safety_monitor.py)
   - 对冲失败率监控（滑动窗口，保留最近10次）
   - 仓位失衡率计算
   - 多级熔断器机制（0=正常, 1=警告, 2=禁止开仓, 3=完全暂停）
   - 手动重置功能

3. **Bot集成** (spread/bot.py)
   - 初始化SafetyMonitor
   - 开仓前安全检查（禁止熔断时开仓）
   - 对冲结果记录
   - 仓位失衡率更新
   - 统计报告中显示安全状态

4. **配置增强** (spread/config.py)
   - safety_enabled: 启用安全监控
   - safety_hedge_failure_threshold: 对冲失败率阈值(30%)
   - safety_position_imbalance_threshold: 仓位失衡率阈值(50%)

**P1 - 动态阈值调整**:
1. **AdaptiveThresholdManager模块** (spread/adaptive_threshold_manager.py)
   - 根据对冲成功率动态调整开仓阈值
   - 高成功率(>90%)时使用降低阈值0.06%
   - 低成功率时使用安全阈值0.15%
   - 支持中间值插值

2. **配置项** (spread/config.py)
   - adaptive_threshold_enabled: 启用动态阈值(默认False)
   - reduced_min_spread_rate: 0.06%
   - reduced_profit_target_rate: 0.02%

**P2 - 优化平仓策略**:

**测试覆盖**:

### 001-spread-recorder: 价差实时记录器（2026-01-10）
**新功能**: 定期采样价差数据并记录到CSV文件，支持数据分析和透明度

1. **核心功能** (spread/spread_recorder.py)
   - 定期采样（默认5秒间隔，可配置）
   - 使用RealSpreadCalculator计算真实价差（对手价）
   - 同时输出到CSV文件和终端日志
   - 按日期自动创建和管理CSV文件（spreads_YYYY_MM_DD.csv）

2. **数据模型** (spread/models.py)
   - SpreadRecord: 包含时间戳、订单簿价格、价差值、价差率、成本分解
   - 支持 VALID 和 INVALID 状态标记

3. **配置管理** (spread/config.py)
   - enable_spread_recorder: 启用/禁用记录器
   - spread_recorder_interval: 采样间隔（秒）
   - spread_recorder_output_dir: CSV输出目录
   - spread_recorder_buffer_size: 缓冲区大小
   - spread_recorder_flush_interval: 刷新间隔

4. **集成到主循环** (spread/bot.py)
   - 在__init__中初始化SpreadRecorder
   - 在run方法中添加记录器任务（asyncio.create_task）
   - 在_cleanup中停止记录器（优雅关闭）

5. **测试覆盖**
   - 25个单元测试（tests/test_spread_recorder.py）
   - 7个集成测试（tests/integration/test_spread_recorder_integration.py）
   - 所有测试通过

6. **CSV文件格式**
   - UTF-8 with BOM编码（Excel兼容）
   - 包含13列：时间戳、价格、价差、成本、状态
   - 支持pandas.read_csv()直接读取

7. **性能优化**
   - 缓冲写入（减少磁盘IO）
   - 异步任务（不阻塞主循环）
   - 记录操作耗时 < 50ms

### 009-fix-spread-loss-fees: 价差套利核心问题修复（2026-01-10）
**重大修复**: 修复导致负收益的三个致命问题

1. **真实价差计算** (spread/real_spread_calculator.py)
   - 使用对手价（bid/ask）替代中间价计算
   - 做多价差 = lighter_bid - extended_ask
   - 做空价差 = extended_bid - lighter_ask

2. **Maker订单定价修复** (spread/calculator.py)
   - price_tick偏移定价：买单 = bid - 0.01, 卖单 = ask + 0.01
   - Taker利润验证：防止maker被拒后转taker亏损

3. **阈值调整确保正收益** (spread/config.py)
   - min_spread_rate从0.05%提高到0.10%
   - 添加effective_min_spread = min_spread_rate + latency_buffer

4. **仓位平衡计算修复** (spread/position_aggregator.py)
   - 使用相减：diff_qty = abs(extended - lighter)
   - 修复前错误：diff_qty = abs(extended) + abs(lighter)

5. **五级优先级平仓系统** (spread/bot.py)
   - P1: 盈利目标 | P2: 时间小额 | P3: 回本止损 | P4: 强制平仓 | P5: 延迟平仓

6. **成本分解和交易分析** (spread/cost_calculator.py, spread/data_collector.py)
   - TradeCostBreakdown: 开仓/平仓手续费、点差、滑点分解
   - CSV导出：trades_YYYY_MM_DD.csv, orders_YYYY_MM_DD.csv
   - TradeAnalyzer: 胜率、盈亏比、每日报告


### Phase 4-7: 价差套利平仓逻辑全面修复（2026-01-10）
**重大改进**: 实现完整的市价平仓、价差收敛检查和增强诊断日志

#### Phase 4: User Story 2 - 修复平仓价格选择逻辑 (T017-T023)
**核心修复**: 使用正确的对手价进行平仓，避免价格选择错误

  - `tests/test_closing_logic.py`: 平仓价格选择逻辑测试（6个测试用例）
  - `spread/bot.py`: 实现 `_close_pair_with_market_price` 方法
    - 做多仓位平仓：Extended用bid，Lighter用ask
    - 做空仓位平仓：Extended用ask，Lighter用bid
  - 移除 `_find_opposite_pair` 机会平仓逻辑（标记为废弃）
  - 修改 `_strategy_loop`：只关注开新仓，平仓由监控循环处理
  - 修改 `_monitor_pairs`：使用 `_close_pair_with_market_price` 替代 `_close_pair`

#### Phase 5: User Story 3 - 增加价差收敛检查 (T024-T032)
**新增功能**: 五级优先级平仓系统，智能决策平仓时机

  - `tests/test_spread_convergence.py`: 价差收敛检查测试（10个测试用例）
  - `spread/bot.py`: 实现 `_check_close_conditions` 方法
    - P1: 盈利目标平仓 - 未实现盈亏达到目标收益率
    - P2: 时间小额平仓 - 持仓超时且有小额利润
    - P3: 回本止损 - 持仓超时且亏损，等待回本后平仓
    - P4: 强制平仓 - 持仓超过最大时间
    - P5: 价差扩大延迟平仓 - 价差扩大时的延迟处理
  - `spread/bot.py`: 实现 `_create_close_decision` 辅助函数
  - `spread/config.py`: 添加 `enable_delay_on_divergence` 配置项

#### Phase 6: User Story 4 - 增强诊断日志 (T033-T043)
**新增功能**: 详细的价差快照、平仓分析和仓位平衡日志

  - `tests/test_enhanced_trade_logger.py`: 增强诊断日志测试（6个测试用例）
  - `spread/trade_logger.py`: 新增三个日志方法
    - `log_spread_snapshot`: 记录价差快照（订单簿价格、价差、套利方向）
    - `log_close_analysis`: 记录平仓分析（优先级、理由、价差变化、盈亏）
    - `log_position_balance`: 记录仓位平衡状态（差异、警告级别）
  - `spread/trade_logger.py`: 新增三个格式化辅助函数
    - `_format_spread_snapshot`: 格式化价差快照
    - `_format_close_analysis`: 格式化平仓分析
    - `_format_position_balance`: 格式化仓位平衡
  - `spread/bot.py`: 集成增强日志
    - `_open_new_pair`: 记录开仓时的价差快照
    - `_close_pair_with_market_price`: 记录平仓分析
    - `_monitor_pairs`: 记录仓位平衡状态

#### Phase 7: Polish - 代码清理和文档更新 (T044-T048)
**优化改进**: 更新文档、清理代码、确保质量

  - `CLAUDE.md`: 更新项目结构和技术栈
  - 新增22个单元测试，全部通过
  - 代码注释完善，包含中英文说明
  - 遵循现有代码风格和结构

### 003-close-position-debug: 平仓逻辑修复与持仓监控调试（2026-01-09）
**修复核心Bug**: 实现强制平仓逻辑，修复持仓无法平仓的问题

  - `spread/spread_pair.py`: 添加 `is_closing` 属性防止重复平仓
  - `spread/bot.py`: 实现完整的 `_force_close_pair` 方法，使用对手价模拟市价单

  - `_force_close_pair`: 完整实现强制平仓流程
    - 检查 is_closing 标志，防止重复平仓
    - 获取订单簿对手价（extended_bid/ask, lighter_bid/ask）
    - 构造 opportunity 字典，复用现有 _close_pair 逻辑
    - 异常处理和错误日志记录
    - 失败时重置 is_closing 标志允许重试
  - `_log_position_status`: 实时持仓状态监控输出
    - 持仓时间与剩余时间
    - Extended和Lighter仓位详情（数量、开仓价格、当前价格）
    - 未实现盈亏计算
    - 距离盈利目标差距
    - 简体中文格式化输出


  ```
  📊 持仓监控 #1 (做多):
     持仓时间: 123秒 (剩余 1677秒)
     Extended仓位: 0.35 @ $2450.00
     当前价格: $2448.50
     Lighter仓位: 0.35 @ $2460.00
     当前价格: $2461.20
     未实现盈亏: $1.23
     距离盈利目标: $8.77
  ```

### 001-trade-log: 交易日志功能（2026-01-09）
**新增功能**: 详细的交易日志记录，用于验证计算收益与实际交易所仓位的一致性

  - `spread/trade_logger.py`: TradeLogger交易日志记录器
  - `tests/test_trade_logger.py`: 交易日志单元测试（15个测试用例）
  - `tests/integration/test_trade_logging.py`: 交易日志集成测试
  - `logs/trade.log`: 交易日志文件（自动创建）

  - `spread/bot.py`: 集成TradeLogger到开仓和平仓流程

  - 自动记录所有开仓交易（时间戳、套利对ID、方向、交易所详情、价差）
  - 自动记录所有平仓交易（开仓价格参考、平仓价格、持仓时间、盈亏计算）
  - 逐步展示盈亏计算过程（Extended盈亏 + Lighter盈亏 = 总盈亏）
  - 未对冲仓位警告日志（Extended成交但Lighter失败时）
  - 中文输出格式，便于人工审核
  - 线程安全的原子写入
  - 优雅的错误处理（日志失败不中断交易）

  - 开仓日志: `=== 交易开仓 ===`
  - 平仓日志: `=== 交易平仓 ===`
  - 警告日志: `=== 警告: 未对冲仓位 ===`

  ```bash
  # 启动机器人（自动记录日志）
  python spread/bot.py --ticker ETH --size 35 --max-pairs 3

  # 查看交易日志
  cat logs/trade.log
  ```

### 002-optimize-spread-arb: Added Python 3.11+ (asyncio) + websockets, decimal.Decimal, logging, pytes
### 001-fix-lighter-api: Added Python 3.10+

<!-- MANUAL ADDITIONS START -->
## 重要注意事项

1. **WebSocket竞态条件**: Extended WebSocket回调可能在订单ID设置前到达，必须缓存更新
2. **Lighter连接**: HTTP 400错误是CloudFront CDN问题，不是代码bug，在服务器上运行正常
3. **订单类型区分**: OPEN类型订单用于开仓，CLOSE类型订单用于平仓，不能混淆
4. **数值精度**: 所有价格和数量必须使用Decimal类型，避免浮点数误差
5. **交易日志验证**: 每次交易后应查看`logs/trade.log`，验证计算收益与实际交易所仓位是否一致
6. **日志文件大小**: 交易日志会持续增长，建议定期归档（当文件超过100MB时）
7. **未对冲仓位**: 如果Extended成交但Lighter失败，会触发紧急熔断并记录警告日志，需人工审核

8. **平仓价格选择** (Phase 4):
   - 做多仓位平仓：Extended卖出用bid价格，Lighter买入用ask价格
   - 做空仓位平仓：Extended买入用ask价格，Lighter卖出用bid价格
   - 必须使用对手价，避免滑点导致的额外损失

9. **价差收敛判断** (Phase 5):
   - 做多价差：spread_delta > 0 表示收敛（价差变大有利）
   - 做空价差：spread_delta < 0 表示收敛（价差变小有利）
   - 使用五级优先级系统智能决策平仓时机

10. **诊断日志** (Phase 6):
    - 价差快照记录开仓时的市场状态
    - 平仓分析记录决策过程和理由
    - 仓位平衡监控两个交易所的仓位一致性

11. **真实价差计算** (009-fix-spread-loss-fees):
    - **致命错误**: 使用中间价(mid price)计算的价差是"买不到也卖不出"的虚假价格
    - **正确做法**: 必须使用对手价(bid/ask)计算可交易的价差
    - 做多价差 = lighter_bid - extended_ask（Extended买入支付ask，Lighter卖出获得bid）
    - 做空价差 = extended_bid - lighter_ask（Extended卖出获得bid，Lighter买入支付ask）

12. **Maker订单定价** (009-fix-spread-loss-fees):
    - **Post-Only冲突**: 使用bid/ask价格下单会被立即成交，失去maker资格
    - **正确做法**: price_tick偏移定价（price = bid - 0.01 或 ask + 0.01）
    - 这样确保订单不会立即成交，保持maker身份节省手续费

13. **最小价差率阈值** (009-fix-spread-loss-fees):
    - **负期望问题**: 0.05%阈值减去0.045%手续费 = -0.015%期望收益
    - **修复后**: 0.10%阈值减去0.045%手续费 = 0.055%正期望
    - effective_min_spread = min_spread_rate + latency_buffer (默认0.10% + 0.01% = 0.11%)

14. **仓位平衡计算** (009-fix-spread-loss-fees):
    - **错误公式**: diff_qty = abs(extended_qty) + abs(lighter_qty) (会显示200%失衡)
    - **正确公式**: diff_qty = abs(extended_qty - lighter_qty) (正确显示实际差异)
    - Extended做多=正数，Lighter做空=负数（对冲关系）

<!-- MANUAL ADDITIONS END -->
