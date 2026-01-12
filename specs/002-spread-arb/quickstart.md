# 快速开始指南：Lighter-Extended 单向价差收敛套利系统

**功能**: 002-spread-arb | **日期**: 2026-01-12

## 概述

本指南将帮助您快速设置和运行 Lighter-Extended 单向价差收敛套利机器人。这是一个基于 Python 的自动化交易系统，利用两个交易所之间的价差进行套利。

## 前置要求

### 系统要求

- Python 3.10 或更高版本
- Linux/macOS 操作系统（推荐）
- 稳定的网络连接（延迟 < 500ms）
- 至少 2GB 可用内存

### 交易所账户

1. **Lighter 交易所**
   - 注册账户并完成 KYC
   - 获取 API 密钥私钥
   - 记录账户索引和 API 密钥索引

2. **Extended 交易所**
   - 注册账户并完成 KYC
   - 获取 Vault、Stark 密钥对、API 密钥

### 资金准备

- Extended 账户：足够的 USDT 余额
- Lighter 账户：足够的代币余额（BTC、ETH 等）

## 安装步骤

### 1. 克隆代码库

```bash
cd /path/to/hufangperp
git checkout 002-spread-arb
```

### 2. 创建虚拟环境

```bash
python3 -m venv env
source env/bin/activate  # Linux/macOS
# 或
env\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

创建 `.env` 文件：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入您的 API 密钥：

```bash
# Lighter 交易所配置
API_KEY_PRIVATE_KEY=your_lighter_private_key
LIGHTER_ACCOUNT_INDEX=0
LIGHTER_API_KEY_INDEX=0

# Extended 交易所配置
EXTENDED_VAULT=your_extended_vault
EXTENDED_STARK_KEY_PRIVATE=your_extended_stark_private_key
EXTENDED_STARK_KEY_PUBLIC=your_extended_stark_public_key
EXTENDED_API_KEY=your_extended_api_key
```

**重要**: 不要将 `.env` 文件提交到版本控制系统！

### 5. 创建日志目录

```bash
mkdir -p logs
```

## 配置参数

### 命令行参数

```bash
python spread_arb/spread_arb_bot.py \
  --symbol BTC \
  --size 0.01 \
  --spread-threshold 0.002 \
  --slippage-buffer 0.0005 \
  --min-profit 0.001 \
  --max-spread 0.05 \
  --timeout 3.0
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--symbol` | 交易对（BTC、ETH 等） | BTC |
| `--size` | 交易数量 | 0.01 |
| `--spread-threshold` | 最小价差阈值（0.2%） | 0.002 |
| `--slippage-buffer` | 滑点保护（0.05%） | 0.0005 |
| `--min-profit` | 最小目标利润（0.1%） | 0.001 |
| `--max-spread` | 极端价差阈值（5%） | 0.05 |
| `--timeout` | 单边成交超时（秒） | 3.0 |

### 推荐配置

**保守配置**（适合新手）：
```bash
--spread-threshold 0.003  # 0.3% 更高阈值
--min-profit 0.002        # 0.2% 更高利润
--max-spread 0.03         # 3% 更严格限制
```

**激进配置**（适合经验丰富的交易者）：
```bash
--spread-threshold 0.0015  # 0.15% 更低阈值
--min-profit 0.0005        # 0.05% 更低利润
--max-spread 0.08          # 8% 更宽松限制
```

## 运行机器人

### 测试模式

首先在测试模式下运行，验证配置：

```bash
python spread_arb/spread_arb_bot.py \
  --symbol BTC \
  --size 0.01 \
  --dry-run
```

`--dry-run` 参数会模拟交易，不发送真实订单。

### 实盘模式

确认配置无误后，运行实盘：

```bash
python spread_arb/spread_arb_bot.py \
  --symbol BTC \
  --size 0.01
```

### 后台运行

使用 nohup 在后台运行：

```bash
nohup python spread_arb/spread_arb_bot.py \
  --symbol BTC \
  --size 0.01 \
  > logs/spread_arb_output.log 2>&1 &
```

或使用 systemd（推荐生产环境）：

```bash
sudo cp scripts/spread-arb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start spread-arb
sudo systemctl enable spread-arb  # 开机自启
```

## 监控和日志

### 查看实时日志

```bash
tail -f logs/spread_arb_$(date +%Y%m%d).log
```

### 查看交易记录

```bash
cat logs/spread_arb_trades.csv
```

### 查看系统状态

```bash
cat logs/spread_arb_state.json
```

### 关键日志指标

日志中会显示以下关键信息：

- `[INFO] Current spread: 0.35%` - 当前价差
- `[INFO] Opening position...` - 开仓中
- `[INFO] Closing position...` - 平仓中
- `[INFO] Trade completed: Profit = $12.50` - 交易完成及利润
- `[WARNING] Order book sequence gap detected` - 订单簿数据缺失
- `[ERROR] Single-side execution detected, rolling back` - 单边成交

## 故障排除

### 常见问题

#### 1. WebSocket 连接失败

**错误**: `Failed to connect to Lighter websocket`

**解决方案**:
- 检查网络连接
- 确认 API 密钥正确
- 检查防火墙设置
- 等待几分钟后自动重连

#### 2. 余额不足

**错误**: `Balance insufficient for trade`

**解决方案**:
- 检查账户余额
- 减少交易数量（`--size`）
- 确保两个交易所都有足够余额

#### 3. 订单簿深度不足

**错误**: `Insufficient order book depth`

**解决方案**:
- 减少交易数量
- 等待市场深度改善
- 选择流动性更好的交易对

#### 4. 单边成交

**错误**: `Single-side execution detected`

**解决方案**:
- 系统会自动强平
- 检查网络连接稳定性
- 考虑增加超时时间（`--timeout`）

#### 5. 价差异常

**错误**: `Abnormal spread detected, rejecting trade`

**解决方案**:
- 这是正常的风控行为
- 可能是市场异常或数据错误
- 系统会继续监控下一个机会

### 调试模式

启用详细日志：

```bash
python spread_arb/spread_arb_bot.py \
  --symbol BTC \
  --size 0.01 \
  --verbose
```

### 重置状态

如果状态文件损坏，可以重置：

```bash
rm logs/spread_arb_state.json
```

## 安全最佳实践

### 1. API 密钥安全

- 使用只读或交易权限的 API 密钥
- 不要使用提现权限的 API 密钥
- 定期轮换 API 密钥
- 不要将 `.env` 文件提交到版本控制

### 2. 资金管理

- 只投入您能承受损失的资金
- 从小额开始测试
- 设置合理的交易数量
- 定期提取利润

### 3. 监控和告警

- 定期检查日志文件
- 设置交易金额限制
- 配置 Telegram 通知（可选）
- 监控账户余额变化

### 4. 风险控制

- 使用保守的价差阈值
- 设置极端价差保护
- 启用单边成交保护
- 定期备份状态文件

## 高级功能

### Telegram 通知

配置 Telegram 机器人接收交易通知：

1. 创建 Telegram Bot（通过 @BotFather）
2. 获取 Chat ID
3. 在 `.env` 中添加：
   ```bash
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```
4. 运行时添加 `--telegram` 参数

### 多交易对

运行多个机器人实例（不同交易对）：

```bash
# BTC 套利
python spread_arb/spread_arb_bot.py --symbol BTC --size 0.01 &

# ETH 套利
python spread_arb/spread_arb_bot.py --symbol ETH --size 0.1 &
```

### 自定义策略

修改 `spread_arb/spread_arb_bot.py` 中的参数：

```python
# 在 BotConfig 中修改默认值
@dataclass
class BotConfig:
    min_spread_threshold: Decimal = Decimal("0.0025")  # 自定义阈值
    # ...
```

## 性能优化

### 网络优化

- 使用低延迟的服务器（靠近交易所服务器）
- 使用有线网络连接
- 关闭不必要的网络应用

### 系统优化

- 增加文件描述符限制
- 调整 TCP 参数
- 使用 SSD 存储

### 监控性能

```bash
# 检查 CPU 和内存使用
top -p $(pgrep -f spread_arb_bot.py)

# 检查网络延迟
ping -c 10 api.starknet.extended.exchange
ping -c 10 mainnet.zklighter.elliot.ai
```

## 下一步

1. **阅读完整文档**:
   - [规格说明](spec.md) - 功能需求
   - [数据模型](data-model.md) - 数据结构
   - [API 契约](contracts/api-contract.md) - 接口定义

2. **测试策略**:
   - 在测试模式下运行至少 24 小时
   - 验证所有功能正常
   - 监控性能指标

3. **小资金试运行**:
   - 使用最小交易数量
   - 运行 1-2 周
   - 分析交易记录和利润

4. **逐步扩大规模**:
   - 根据表现调整参数
   - 增加交易数量
   - 添加更多交易对

## 支持与反馈

如有问题或建议，请通过以下方式联系：

- GitHub Issues: [项目地址]
- Telegram: [联系方式]
- Email: [联系方式]

---

**免责声明**: 加密货币交易存在风险。本软件按"原样"提供，不提供任何形式的保证。使用本软件的风险由您自行承担。
