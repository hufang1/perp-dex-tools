# 快速开始指南：价差套利系统改进

**功能**: 003-spreading-improvements | **日期**: 2026-01-19

## 概述

本指南帮助开发者快速理解和使用价差套利系统的四项改进功能：
1. 修复重复挂单Bug
2. 阶梯价差开仓
3. 双模式平仓逻辑
4. 可用仓位检测系统

---

## 前置条件

- Python 3.10+
- 现有价差套利系统已安装（002-spread-arb）
- 两个交易所的 API 密钥已配置

---

## 功能1：修复重复挂单Bug

### 问题描述

修改挂单价格时，旧订单可能未成功取消就创建了新订单，导致多个挂单同时存在。

### 解决方案

在 `TradeExecutor` 中新增 `cancel_maker_order_with_verification()` 方法，取消订单后通过 REST API 轮询验证取消成功。

### 使用方式

**自动启用**：无需额外配置，系统自动使用新的取消验证机制。

### 验证方法

查看日志中的取消订单记录：

```log
# 成功取消
订单取消成功 | ID=1234567890ab... | 尝试=1次 | 耗时=2.3秒

# 失败情况
订单取消失败 | ID=1234567890ab... | 尝试=5次 | 最终状态=OPEN | 错误=超时
```

### 配置参数

在 `BotConfig` 中可以调整（使用默认值即可）：

```python
# 取消订单配置
cancel_max_retries: int = 5          # 最大重试次数
cancel_retry_interval: float = 2.0   # 重试间隔（秒）
cancel_verify_timeout: float = 5.0   # 验证超时（秒）
```

---

## 功能2：阶梯价差开仓

### 问题描述

固定阈值开仓导致资金利用率低，希望随着开仓次数增加而递增开仓阈值。

### 解决方案

实现阶梯式价差阈值：
- 第1次开仓：初始价差（如 0.5%）
- 第2次开仓：初始价差 + 1 × 步长（如 0.5% + 0.1% = 0.6%）
- 第3次开仓：初始价差 + 2 × 步长（如 0.5% + 0.2% = 0.7%）
- 以此类推...

### 配置方式

在 `.env` 文件或命令行参数中设置：

```bash
# 阶梯开仓配置
INITIAL_OPEN_SPREAD=0.005    # 初始开仓价差 0.5%
SPREAD_STEP=0.001            # 开仓步长 0.1%
```

或在配置文件中：

```python
config = BotConfig(
    initial_open_spread=Decimal("0.005"),  # 0.5%
    spread_step=Decimal("0.001"),           # 0.1%
)
```

### 运行示例

```log
# 第1次开仓
价差 0.52% >= 阈值 0.50% (初始=0.50%, 次数=0, 步长=0.10%)
开仓成功，开仓次数: 1, 下次阈值: 0.60%

# 第2次开仓
价差 0.62% >= 阈值 0.60% (初始=0.50%, 次数=1, 步长=0.10%)
开仓成功，开仓次数: 2, 下次阈值: 0.70%

# 第3次开仓
价差 0.71% >= 阈值 0.70% (初始=0.50%, 次数=2, 步长=0.10%)
开仓成功，开仓次数: 3, 下次阈值: 0.80%
```

### 重置机制

当所有仓位平仓后，开仓次数自动重置为0：

```log
所有仓位已平仓，重置开仓次数: 3 -> 0
```

### 状态持久化

开仓次数会保存到状态文件 `logs/spread_arb_state.json`，系统重启后自动恢复：

```json
{
  "config_state": {
    "opening_count": 2,
    "initial_open_spread": "0.005",
    "spread_step": "0.001"
  }
}
```

---

## 功能3：双模式平仓逻辑

### 问题描述

希望根据利润水平选择平仓方式：
- 利润大时：市价平仓（快速兑现）
- 利润小时：限价平仓（降低成本）

### 解决方案

根据当前价差相对于总开仓仓位价差的位置，自动选择平仓模式：

```
总开仓价差 = 0.8%
市价平仓阈值 B = 0.4%
限价平仓阈值 A = 0.2%

当前价差区间：
- < 0.4% (0.8% - 0.4%): 市价平仓
- 0.4% ~ 0.6% (0.8% - 0.2%): 限价平仓
- > 0.6%: 继续持有
```

### 配置方式

在 `.env` 文件或命令行参数中设置：

```bash
# 双模式平仓配置
LIMIT_CLOSE_SPREAD_A=0.002   # 限价平仓阈值A 0.2%
MARKET_CLOSE_SPREAD_B=0.004  # 市价平仓阈值B 0.4%
```

或在配置文件中：

```python
config = BotConfig(
    limit_close_spread_a=Decimal("0.002"),  # 0.2%
    market_close_spread_b=Decimal("0.004"), # 0.4%
)
```

### 运行示例

```log
# 限价平仓（利润小）
持仓监控 | 总开仓=0.80% | 当前=0.50% | 限价阈值=0.60% | 市价阈值=0.40%
平仓触发 | 限价平仓 | 价差0.50% < 限价阈值0.60% | 总开仓=0.80%
💥 持仓中 -> 限价平仓中 | 限价平仓

# 市价平仓（利润大）
持仓监控 | 总开仓=0.80% | 当前=0.30% | 限价阈值=0.60% | 市价阈值=0.40%
平仓触发 | 市价平仓 | 价差0.30% < 市价阈值0.40% | 总开仓=0.80%
💥 持仓中 -> 市价平仓中 | 市价平仓
```

### 状态转换

- **限价平仓**: `HOLDING` → `CLOSING_LIMIT` → 等待成交 → `IDLE`
- **市价平仓**: `HOLDING` → `CLOSING_MARKET` → 立即完成 → `IDLE`

### 获取平均开仓成本

系统优先从交易所 API 获取总持仓的平均开仓成本：

```python
# 优先使用交易所API
ext_avg = await extended_client.get_position(symbol).avg_entry_price
lig_avg = await lighter_client.get_position(symbol).avg_entry_price

# 如果API失败，使用本地加权平均
total_spread = portfolio.weighted_avg_entry_spread
```

降级日志：

```log
从交易所获取平均价格失败: API异常，使用本地记录
使用本地平均价差: 0.80%
```

---

## 功能4：可用仓位检测系统

### 问题描述

开仓前未检查两个交易所余额，导致 Extended 余额充足但 Lighter 余额不足时出现单边持仓风险。

### 解决方案

在开仓前（Extended 挂单和 Lighter 对冲之前）检查两个交易所的可用余额：

1. 查询 Extended 可用 USDT 余额
2. 查询 Lighter 可用代币余额
3. 计算开仓所需金额
4. 比较并决定是否跳过本次开仓

### 使用方式

**自动启用**：系统在每次开仓前自动执行余额检测。

### 配置参数

目前无需额外配置，系统使用以下默认参数：

```python
# 计算所需金额时考虑杠杆（如果有）
# Extended: 所需金额 = 数量 × 价格 / 杠杆
# Lighter: 所需数量 = 数量
```

### 运行示例

**余额充足**：

```log
余额检测通过 | Ext: 5000.00/1200.00 USDT | Lig: 2.0000/0.1000 代币
继续执行开仓流程...
```

**余额不足**：

```log
余额检测失败 | Extended 余额不足 | 缺少 200.0000 | Ext: 1000.00/1200.00 USDT | Lig: 2.0000/0.1000 代币
跳过本次开仓，状态保持不变
```

**Lighter 余额不足**：

```log
余额检测失败 | Lighter 余额不足 | 缺少 0.5000 | Ext: 5000.00/1200.00 USDT | Lig: 0.0500/0.1000 代币
跳过本次开仓，避免单边持仓风险
```

### API 依赖

余额检测依赖以下交易所 API：

```python
# Extended
GET /api/v1/balance
# 返回: { "availableUsdt": "5000.00" }

# Lighter
GET /api/v1/balances
# 返回: { "ETH": { "available": "2.0" } }
```

如果 API 调用失败，系统会：

```log
余额检测异常: Extended API 错误
跳过本次开仓，保持 IDLE 状态
```

---

## 完整配置示例

### .env 文件

```bash
# ========== 基础配置 ==========
SYMBOL=ETH
TARGET_QUANTITY=0.01
MIN_SPREAD_THRESHOLD=0.0007

# ========== 阶梯价差开仓 ==========
INITIAL_OPEN_SPREAD=0.005    # 初始开仓价差 0.5%
SPREAD_STEP=0.001            # 开仓步长 0.1%

# ========== 双模式平仓 ==========
LIMIT_CLOSE_SPREAD_A=0.002   # 限价平仓阈值A 0.2%
MARKET_CLOSE_SPREAD_B=0.004  # 市价平仓阈值B 0.4%

# ========== Maker模式 ==========
USE_MAKER_MODE=true
FIXED_OPEN_THRESHOLD=0.0009
FIXED_CLOSE_THRESHOLD=0.0006
```

### Python 配置

```python
from decimal import Decimal
from spread.models import BotConfig

config = BotConfig(
    # 基础配置
    symbol="ETH",
    target_quantity=Decimal("0.01"),
    min_spread_threshold=Decimal("0.0007"),

    # 阶梯价差开仓
    initial_open_spread=Decimal("0.005"),  # 0.5%
    spread_step=Decimal("0.001"),           # 0.1%

    # 双模式平仓
    limit_close_spread_a=Decimal("0.002"),  # 0.2%
    market_close_spread_b=Decimal("0.004"), # 0.4%

    # Maker模式
    use_maker_mode=True,
    fixed_open_threshold=Decimal("0.0009"),
    fixed_close_threshold=Decimal("0.0006"),
)
```

---

## 运行测试

### 单元测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定功能测试
pytest tests/test_balance_checker.py -v
pytest tests/test_tiered_opening.py -v
pytest tests/test_dual_mode_close.py -v

# 查看覆盖率
pytest tests/ --cov=spread --cov-report=html
```

### 集成测试

```bash
# 测试开仓流程（含余额检测）
pytest tests/integration/test_opening_with_balance.py -v

# 测试挂单修改（含取消验证）
pytest tests/integration/test_order_management.py -v

# 测试双模式平仓
pytest tests/integration/test_dual_mode_close.py -v
```

### 模拟运行

```bash
# 使用 --dry-run 参数模拟运行
python -m spread.spread_arb_bot \
    --symbol ETH \
    --target-quantity 0.01 \
    --initial-open-spread 0.005 \
    --spread-step 0.001 \
    --limit-close-spread-a 0.002 \
    --market-close-spread-b 0.004 \
    --dry-run \
    --verbose
```

---

## 监控和日志

### 关键日志

**阶梯开仓**：

```log
阶梯开仓 | 次数=2 | 当前阈值=0.60% | 下次阈值=0.70% | 初始=0.50% | 步长=0.10%
```

**双模式平仓**：

```log
平仓触发 | 市价平仓 | 利润大 | 价差0.30% < 市价阈值0.40% | 总开仓=0.80%
```

**余额检测**：

```log
余额检测通过 | Ext: 5000.00/1200.00 USDT | Lig: 2.0000/0.1000 代币
```

**取消订单验证**：

```log
订单取消成功 | ID=1234567890ab... | 尝试=1次 | 耗时=2.3秒
```

### 状态监控

查看当前状态：

```bash
# 查看状态文件
cat logs/spread_arb_state.json | jq

# 查看实时日志
tail -f logs/spread_arb_$(date +%Y%m%d).log
```

---

## 故障排查

### 问题1：余额检测总是失败

**原因**：交易所 API 密钥配置错误或 API 限流

**解决**：
1. 检查 `.env` 文件中的 API 密钥
2. 确认 API 密钥有查询余额的权限
3. 检查网络连接

### 问题2：阶梯开仓次数不递增

**原因**：状态文件未正确保存或加载

**解决**：
1. 检查 `logs/spread_arb_state.json` 文件权限
2. 查看日志中的状态保存/加载记录
3. 手动重置：删除状态文件重启

### 问题3：双模式平仓总是使用限价模式

**原因**：市价阈值设置过高，很少触发

**解决**：
1. 检查 `MARKET_CLOSE_SPREAD_B` 配置
2. 查看日志中的价差计算过程
3. 调整阈值使市价平仓更容易触发

### 问题4：取消订单验证超时

**原因**：交易所 API 响应慢或订单状态更新延迟

**解决**：
1. 增加 `CANCEL_VERIFY_TIMEOUT` 配置
2. 检查网络延迟
3. 联系交易所确认 API 状态

---

## 性能优化建议

### 余额查询缓存

余额查询可能较慢，可以考虑缓存（但要注意及时更新）：

```python
# 在 BalanceChecker 中添加缓存
@lru_cache(maxsize=1)
async def _get_cached_balance(self, exchange: str) -> Decimal:
    # 缓存5秒
    pass
```

### 并发 API 调用

使用 `asyncio.gather()` 并发调用两个交易所的 API：

```python
ext_balance, lig_balance = await asyncio.gather(
    self._get_extended_balance(),
    self._get_lighter_balance(symbol),
)
```

---

## 升级指南

### 从 002-spread-arb 升级

1. **备份现有配置和状态**

```bash
cp .env .env.backup
cp logs/spread_arb_state.json logs/spread_arb_state.json.backup
```

2. **更新代码**

```bash
git pull origin main
```

3. **安装新依赖**

```bash
pip install -r requirements.txt
```

4. **更新配置**

在 `.env` 文件中添加新配置：

```bash
# 阶梯开仓
INITIAL_OPEN_SPREAD=0.005
SPREAD_STEP=0.001

# 双模式平仓
LIMIT_CLOSE_SPREAD_A=0.002
MARKET_CLOSE_SPREAD_B=0.004
```

5. **验证配置**

```bash
python -m spread.spread_arb_bot --validate-config
```

6. **启动系统**

```bash
python -m spread.spread_arb_bot
```

---

## 下一步

- 阅读 [data-model.md](data-model.md) 了解数据模型
- 阅读 [contracts/internal-api-contract.md](contracts/internal-api-contract.md) 了解接口契约
- 运行 `/speckit.tasks` 查看详细实施任务

---

**文档版本**: 1.0 | **最后更新**: 2026-01-19
