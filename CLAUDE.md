# hufangperp Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-10

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
├── real_spread_calculator.py  # [NEW] 真实价差计算器（对手价）
├── cost_calculator.py     # [NEW] 成本分解计算器
├── spread_pair.py         # 套利对数据模型
├── trade_logger.py        # 交易日志记录器
├── config.py              # 配置类
├── models.py              # 数据模型（SpreadSnapshot, SpreadChange, CloseDecision, PositionBalance）
├── position_aggregator.py # 持仓聚合器
├── profit_calculator.py   # 收益计算器
├── data_collector.py      # [NEW] 数据收集器（CSV导出）
└── trade_analyzer.py      # [NEW] 交易分析器

exchanges/                 # 交易所客户端
├── extended.py           # Extended交易所客户端
└── lighter_custom_websocket.py  # Lighter WebSocket客户端

tests/                     # 测试文件
├── test_order_manager.py  # 订单管理器单元测试
├── test_trade_logger.py  # 交易日志单元测试
├── test_closing_logic.py         # 平仓价格选择逻辑测试（Phase 4）
├── test_spread_convergence.py    # 价差收敛检查测试（Phase 5）
├── test_enhanced_trade_logger.py # 增强诊断日志测试（Phase 6）
├── test_real_spread_calculator.py  # [NEW] 对手价计算测试
├── test_cost_calculator.py         # [NEW] 成本分解测试
└── integration/
    └── test_trade_logging.py  # 交易日志集成测试

logs/                      # 交易日志目录
└── trade.log             # 交易日志文件（自动创建）

data/                      # [NEW] 数据导出目录
├── trades_YYYY_MM_DD.csv  # 交易记录导出（自动创建）
└── orders_YYYY_MM_DD.csv  # 订单记录导出（自动创建）
```

## Commands

```bash
# 运行单元测试
pytest tests/test_order_manager.py -v

# 运行交易日志测试
pytest tests/test_trade_logger.py -v

# 运行价差套利机器人
python spread/bot.py --ticker ETH --size 35 --max-pairs 3

# 运行对冲模式
python hedge/hedge_mode.py --exchange extended --ticker ETH --size 0.01 --iter 20

# 查看交易日志
cat logs/trade.log
```

## Code Style

- **异步函数**: 所有I/O操作使用async/await
- **日志**: 使用logging模块，debug级别记录详细信息，info级别记录关键事件
- **数值计算**: 使用Decimal进行所有金融计算，避免浮点数精度问题
- **错误处理**: 不抛出异常，通过返回值传递错误信息

## Recent Changes

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

- 001-fix-spread-close: Added 市价平仓逻辑
- 001-fix-spread-loss: Added Python 3.10+

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
