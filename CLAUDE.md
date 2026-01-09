# hufangperp Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-09

## Active Technologies
- Python 3.10+ (001-fix-lighter-api)
- N/A (状态在内存中，日志写入文件) (001-fix-lighter-api)
- Python 3.11+ (asyncio) + websockets, decimal.Decimal, logging, pytes (002-optimize-spread-arb)
- 状态在内存中,日志写入文件 (N/A数据库) (002-optimize-spread-arb)
- Python 3.11+ logging, decimal.Decimal, pathlib, datetime (001-trade-log)

- **Python 3.11+**: 主要编程语言
- **asyncio**: 异步编程框架
- **websockets**: WebSocket客户端库
- **decimal.Decimal**: 精确的金融数值计算
- **pytest**: 单元测试框架
- **logging**: Python标准日志库（用于交易日志）

## Project Structure

```text
spread/                    # 价差套利模块
├── order_manager.py       # 订单管理器（扩展交易所）
├── hedge_manager.py       # 对冲管理器（Lighter交易所）
├── bot.py                 # 套利机器人主逻辑
├── calculator.py          # 价差计算器
├── spread_pair.py         # 套利对数据模型
└── trade_logger.py        # 交易日志记录器（新增）

exchanges/                 # 交易所客户端
├── extended.py           # Extended交易所客户端
└── lighter_custom_websocket.py  # Lighter WebSocket客户端

tests/                     # 测试文件
├── test_order_manager.py  # 订单管理器单元测试
├── test_trade_logger.py  # 交易日志单元测试（新增）
└── integration/
    └── test_trade_logging.py  # 交易日志集成测试（新增）

logs/                      # 交易日志目录（新增）
└── trade.log             # 交易日志文件（自动创建）
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

### 001-trade-log: 交易日志功能（2026-01-09）
**新增功能**: 详细的交易日志记录，用于验证计算收益与实际交易所仓位的一致性

- **新增文件**:
  - `spread/trade_logger.py`: TradeLogger交易日志记录器
  - `tests/test_trade_logger.py`: 交易日志单元测试（15个测试用例）
  - `tests/integration/test_trade_logging.py`: 交易日志集成测试
  - `logs/trade.log`: 交易日志文件（自动创建）

- **修改文件**:
  - `spread/bot.py`: 集成TradeLogger到开仓和平仓流程

- **核心功能**:
  - 自动记录所有开仓交易（时间戳、套利对ID、方向、交易所详情、价差）
  - 自动记录所有平仓交易（开仓价格参考、平仓价格、持仓时间、盈亏计算）
  - 逐步展示盈亏计算过程（Extended盈亏 + Lighter盈亏 = 总盈亏）
  - 未对冲仓位警告日志（Extended成交但Lighter失败时）
  - 中文输出格式，便于人工审核
  - 线程安全的原子写入
  - 优雅的错误处理（日志失败不中断交易）

- **日志格式**:
  - 开仓日志: `=== 交易开仓 ===`
  - 平仓日志: `=== 交易平仓 ===`
  - 警告日志: `=== 警告: 未对冲仓位 ===`

- **使用方法**:
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

<!-- MANUAL ADDITIONS END -->
