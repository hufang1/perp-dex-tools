# Lighter-Extended 单向价差收敛套利系统

## 快速开始

### 1. 配置环境变量

创建 `.env` 文件（参考 `.env.example`）：

```bash
# Lighter 交易所配置
API_KEY_PRIVATE_KEY=your_private_key_here
LIGHTER_ACCOUNT_INDEX=0
LIGHTER_API_KEY_INDEX=0

# Extended 交易所配置
EXTENDED_VAULT=your_vault_address
EXTENDED_STARK_KEY_PRIVATE=your_stark_private_key
EXTENDED_STARK_KEY_PUBLIC=your_stark_public_key
EXTENDED_API_KEY=your_extended_api_key

# 可选：Telegram 通知
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 2. 运行机器人

**方式一：使用模块方式运行（推荐）**
```bash
# 在项目根目录运行
python -m spread.spread_arb_bot --symbol BTC --size 0.01
```

**方式二：使用启动脚本**
```bash
# 在项目根目录运行
python run_bot.py --symbol BTC --size 0.01
```

**方式三：直接运行（需要先设置 PYTHONPATH）**
```bash
export PYTHONPATH=/Users/hufang/Desktop/web3\ project/perp/hufangperp:$PYTHONPATH
python spread/spread_arb_bot.py --symbol BTC --size 0.01
```

### 3. 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--symbol` | 交易对 | BTC |
| `--size` | 交易数量 | 0.01 |
| `--spread-threshold` | 最小价差阈值（0.2%） | 0.002 |
| `--slippage-buffer` | 滑点保护（0.05%） | 0.0005 |
| `--min-profit` | 最小目标利润（0.1%） | 0.001 |
| `--max-spread` | 极端价差阈值（5%） | 0.05 |
| `--timeout` | 单边成交超时（秒） | 3.0 |
| `--dry-run` | 模拟运行模式 | - |
| `--verbose` | 详细日志模式 | - |

### 4. 后台运行

```bash
# 使用 nohup
nohup python -m spread.spread_arb_bot --symbol BTC --size 0.01 > logs/bot_output.log 2>&1 &

# 或使用 screen/tmux
screen -S spread_arb
python -m spread.spread_arb_bot --symbol BTC --size 0.01
# Ctrl+A+D 分离会话
```

### 5. 查看日志

```bash
# 查看实时日志
tail -f logs/spread_arb_$(date +%Y%m%d).log

# 查看交易记录
cat logs/spread_arb_trades.csv

# 查看系统状态
cat logs/spread_arb_state.json
```

## 运行测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_spread_calculator.py -v

# 查看测试覆盖率
python -m pytest tests/ --cov=spread --cov-report=html
```

## 项目结构

```
spread/                          # 套利模块
├── __init__.py                  # 模块入口
├── models.py                    # 数据模型
├── exceptions.py                # 自定义异常
├── utils.py                     # 工具函数
├── order_book_manager.py        # 订单簿管理器
├── spread_calculator.py         # 价差计算器
├── trade_executor.py            # 交易执行器
├── state_manager.py             # 状态管理器
├── risk_manager.py              # 风控管理器
├── spread_arb_bot.py            # 主控制器
└── env_validator.py             # 环境变量验证

tests/                           # 测试目录
├── __init__.py                  # 测试配置
├── test_spread_calculator.py    # 价差计算测试
├── test_risk_manager.py         # 风控测试
└── integration/                 # 集成测试
    ├── test_risk_scenarios.py   # 风控场景测试
    └── test_e2e_spread_arb.py   # 端到端测试

logs/                            # 运行时目录
├── spread_arb_YYYYMMDD.log     # 每日日志
├── spread_arb_trades.csv       # 交易记录
└── spread_arb_state.json       # 状态快照

run_bot.py                      # 启动脚本
```

## 故障排除

### 问题：ModuleNotFoundError: No module named 'spread'

**解决方案**：使用模块方式运行
```bash
python -m spread.spread_arb_bot --symbol BTC
```

### 问题：缺少必需的环境变量

**解决方案**：检查 `.env` 文件是否存在并包含所有必需的配置

### 问题：WebSocket 连接失败

**解决方案**：
1. 检查网络连接
2. 验证 API 密钥是否正确
3. 检查防火墙设置

## 免责声明

加密货币交易存在风险。本软件按"原样"提供，不提供任何形式的保证。使用本软件的风险由您自行承担。
