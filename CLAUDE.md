# hufangperp Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-01-07

## Active Technologies
- Python 3.10+ (001-fix-lighter-api)
- N/A (状态在内存中，日志写入文件) (001-fix-lighter-api)

- **Python 3.11+**: 主要编程语言
- **asyncio**: 异步编程框架
- **websockets**: WebSocket客户端库
- **decimal.Decimal**: 精确的金融数值计算
- **pytest**: 单元测试框架

## Project Structure

```text
spread/                    # 价差套利模块
├── order_manager.py       # 订单管理器（扩展交易所）
├── hedge_manager.py       # 对冲管理器（Lighter交易所）
├── bot.py                 # 套利机器人主逻辑
├── calculator.py          # 价差计算器
└── spread_pair.py         # 套利对数据模型

exchanges/                 # 交易所客户端
├── extended.py           # Extended交易所客户端
└── lighter_custom_websocket.py  # Lighter WebSocket客户端

tests/                     # 测试文件
└── test_order_manager.py  # 订单管理器单元测试
```

## Commands

```bash
# 运行单元测试
pytest tests/test_order_manager.py -v

# 运行价差套利机器人
python spread/bot.py --ticker ETH --size 35 --max-pairs 3

# 运行对冲模式
python hedge/hedge_mode.py --exchange extended --ticker ETH --size 0.01 --iter 20
```

## Code Style

- **异步函数**: 所有I/O操作使用async/await
- **日志**: 使用logging模块，debug级别记录详细信息，info级别记录关键事件
- **数值计算**: 使用Decimal进行所有金融计算，避免浮点数精度问题
- **错误处理**: 不抛出异常，通过返回值传递错误信息

## Recent Changes
- 001-fix-lighter-api: Added Python 3.10+

- **003-fix-order-status-race**: 添加订单状态缓存机制，修复竞态条件bug
  - 修改文件: `spread/order_manager.py`
  - 新增缓存: `_pending_updates: Dict[str, List[Dict]]`
  - 新增并发控制: `_update_lock: asyncio.Lock`
  - 新增方法: `_apply_pending_updates()`, `_cleanup_cache()`

<!-- MANUAL ADDITIONS START -->
## 重要注意事项

1. **WebSocket竞态条件**: Extended WebSocket回调可能在订单ID设置前到达，必须缓存更新
2. **Lighter连接**: HTTP 400错误是CloudFront CDN问题，不是代码bug，在服务器上运行正常
3. **订单类型区分**: OPEN类型订单用于开仓，CLOSE类型订单用于平仓，不能混淆
4. **数值精度**: 所有价格和数量必须使用Decimal类型，避免浮点数误差

<!-- MANUAL ADDITIONS END -->
