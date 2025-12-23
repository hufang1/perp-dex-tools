# Extended-Lighter 价差套利策略

## 📖 简介

这是一个基于 Extended 和 Lighter 两个交易所的价差套利策略。通过在两个交易所之间捕捉价差机会，利用 0% 手续费实现低风险套利。

## 🎯 策略原理

### 核心逻辑

1. **Extended (Maker 池)**: 挂单获取价格优势，享受 0% Maker 费率
2. **Lighter (Taker 池)**: 对冲执行，享受 0% Taker 费率

### 套利流程

```
发现价差机会 → Extended 挂 Maker 单 → 等待成交 → Lighter 对冲 → 建立套利对
  ↓
监听反向价差 → Extended 反向挂单 → 等待成交 → Lighter 反向对冲 → 平仓获利
```

### 盈利公式

```
Profit = Price_Spread - Slippage - Gas_Cost
```

由于两端手续费为 0，只要价差 > (滑点 + Gas)，即可盈利。

## 📂 代码结构

```
spread/
├── __init__.py           # 模块初始化
├── config.py             # 配置类
├── spread_pair.py        # 套利对类
├── calculator.py         # 价差计算器
├── order_manager.py      # Extended 订单管理
├── hedge_manager.py      # Lighter 对冲管理
├── bot.py                # 主引擎
├── run_spread_arb.py     # 运行入口
└── README.md             # 本文档
```

##⚙️ 配置参数

### 基础配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ticker` | 'ETH' | 交易对符号 |
| `order_quantity_usdt` | 100 | 单次下单金额 (USDT) |

### 价差配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_spread_rate` | 0.05% | 最小价差率 |
| `latency_buffer` | 0.01% | 延迟缓冲 |

### 持仓管理

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_open_pairs` | 3 | 最大同时持有套利对数 |
| `max_holding_time` | 1800秒 | 最大持仓时间 (30分钟) |

### 风险控制

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `stop_loss_usdt` | $5 | 单个套利对止损金额 |
| `slippage_tolerance` | 0.1% | 最大可接受滑点 |
| `max_lighter_depth_ratio` | 50% | Lighter 深度使用比例 |

## 🚀 快速开始

### 1. 环境配置

```bash
# 复制环境变量模板
cp env_example.txt .env

# 编辑 .env 文件，填写 API 密钥
# - EXTENDED_API_KEY
# - EXTENDED_STARK_KEY_PRIVATE
# - EXTENDED_STARK_KEY_PUBLIC
# - EXTENDED_VAULT
# - API_KEY_PRIVATE_KEY (Lighter)
# - LIGHTER_ACCOUNT_INDEX
# - LIGHTERAPI_KEY_INDEX
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行策略

```bash
# 使用默认参数运行 ETH
python spread/run_spread_arb.py --ticker ETH

# 自定义参数
python spread/run_spread_arb.py \
  --ticker ETH \
  --quantity 200 \
  --min-spread 0.0008 \
  --max-pairs 5
```

### 4. 命令行参数

```bash
python spread/run_spread_arb.py --help

选项:
  --ticker TICKER              交易对符号 (default: ETH)
  --quantity QUANTITY          单次下单金额 USDT (default: 100)
  --min-spread MIN_SPREAD      最小价差率 (default: 0.0005)
  --max-pairs MAX_PAIRS        最大套利对数 (default: 3)
  --max-holding-time SECONDS   最大持仓时间 (default: 1800)
  --stop-loss USDT             止损金额 (default: 5)
  --log-level LEVEL            日志级别 (default: INFO)
  --env-file FILE              环境变量文件 (default: .env)
```

## 📊 运行示例

### 输出示例

```
2024-01-15 10:30:00 [INFO] SpreadArbBot: ============================================================
2024-01-15 10:30:00 [INFO] SpreadArbBot: 价差套利机器人启动
2024-01-15 10:30:00 [INFO] SpreadArbBot: ============================================================
2024-01-15 10:30:01 [INFO] SpreadArbBot: 配置参数:
2024-01-15 10:30:01 [INFO] SpreadArbBot:   交易对: ETH
2024-01-15 10:30:01 [INFO] SpreadArbBot:   单次下单金额: $100
2024-01-15 10:30:01 [INFO] SpreadArbBot:   最小价差率: 0.0500%
2024-01-15 10:30:01 [INFO] SpreadArbBot:   延迟缓冲: 0.0100%
2024-01-15 10:30:01 [INFO] SpreadArbBot:   最大套利对数: 3
2024-01-15 10:30:01 [INFO] SpreadArbBot: ------------------------------------------------------------
2024-01-15 10:30:05 [INFO] SpreadArbBot: 🎯 发现开仓机会: buy_extended_sell_lighter 价差率: 0.0650% 预期利润: 0.0540%
2024-01-15 10:30:05 [INFO] OrderManager: [Extended] 下 BUY Maker 单: 0.0333 @ 3000.00
2024-01-15 10:30:06 [INFO] OrderManager: ✅ 订单已提交: ORD123456 @ 3000.00
2024-01-15 10:30:08 [INFO] OrderManager: ✅ 订单完全成交: 0.0333 @ 3000.00
2024-01-15 10:30:08 [INFO] HedgeManager: [Lighter] 对冲 SELL: 0.0333 @ ~3001.50
2024-01-15 10:30:09 [INFO] HedgeManager: ✅ Lighter 对冲完成: 0.0333 @ 3001.60
2024-01-15 10:30:09 [INFO] SpreadArbBot: ✅ 开仓成功! 套利对 #1: BUY 0.0333 Extended@3000.00 Lighter@3001.60 开仓价差: $1.60 (0.0533%)
...
2024-01-15 10:35:20 [INFO] SpreadArbBot: 🎯 发现平仓机会: 套利对 #1 价差率: 0.0620%
2024-01-15 10:35:21 [INFO] SpreadArbBot: 💰 平仓成功! 套利对 #1: 盈亏 $2.15 持仓 320秒
```

### 统计报告

```
============================================================
📊 统计报告
  持仓套利对: 2
  已平仓套利对: 5
  总机会数: 23
  成功开仓: 7
  成功平仓: 5
  总盈利: $12.50
  净盈亏: $11.80
============================================================
```

## 🔍 核心功能

### 1. 价差计算

自动计算两个交易所之间的价差机会：

```python
# 买入套利: Extended 买 + Lighter 卖
if lighter_bid > extended_bid:
    spread_rate = (lighter_bid - extended_bid) / extended_bid
    if spread_rate > min_spread_rate + latency_buffer:
        # 触发套利
```

### 2. 套利对管理

**开仓**:
- Extended 下 Maker 单
- 等待成交
- Lighter 对冲
- 建立套利对记录

**平仓** (3 种触发条件):
1. **价差反转**: 反向价差机会出现 ⭐ (推荐)
2. **时间止盈**: 持仓超过 30 分钟
3. **盈利/止损**: 达到目标或触碰止损

### 3. 风险控制

- **深度保护**: 下单量不超过 Lighter 深度的 50%
- **滑点保护**: 监控实际滑点,超限告警
- **断路器**: 连续失败 3 次暂停 60 秒
- **仓位监控**: 严格控制净持仓

## ⚠️ 风险提示

### 主要风险

1. **对冲失败风险**: Extended 成交但 Lighter 对冲失败，导致单边持仓
2. **滑点风险**: Lighter 深度不足导致对冲滑点过大
3. **网络延迟**: Extended 和 Lighter 价格在延迟期间发生变化
4. **价格剧烈波动**: 极端行情下价差快速反转

### 风险缓解

- 设置合理的深度过滤阈值
- 使用延迟缓冲预留安全边际
- 启用断路器防止连续失败
- 小金额测试验证策略

## 🛠️ 故障排查

### 问题 1: 订单簿数据未就绪

**症状**: `订单簿数据超时未就绪`

**解决**:
- 检查 WebSocket 连接
- 确认网络稳定性
- 增加超时时间

### 问题 2: 对冲失败

**症状**: `❌ 对冲失败!存在未对冲风险!`

**解决**:
- 检查 Lighter 账户余额
- 检查 API 密钥权限
- 查看 Lighter 深度是否充足

### 问题 3: 未发现机会

**症状**: 长时间无套利机会

**解决**:
- 降低 `min_spread_rate` 阈值
- 检查两个交易所价格是否正常
- 确认市场波动性

## 📈 优化建议

### 参数调优

1. **小金额测试**: 先用 $10-50 测试
2. **观察价差分布**: 统计实际价差范围
3. **调整阈值**: 根据历史数据优化 `min_spread_rate`
4. **深度分析**: 分析 Lighter 深度变化规律

### 性能优化

1. **WebSocket 优化**: 减少订单簿更新延迟
2. **并发处理**: 允许多个套利对并行操作
3. **节点优化**: 使用更快的 RPC 节点

## 📝 TODO

- [ ] 集成 WebSocket 订单簿自动更新
- [ ] 实现强制市价平仓逻辑
- [ ] 添加 Telegram/Lark 通知
- [ ] 持久化套利对记录到数据库
- [ ] 添加回测功能
- [ ] 实现交易记录 CSV 导出
- [ ] 添加 Web 监控界面

## 📧 联系方式

如有问题或建议,请联系项目维护者。

---

**最后更新**: 2024-01-15
