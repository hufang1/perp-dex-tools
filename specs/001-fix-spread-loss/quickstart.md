# Quickstart: 价差套利磨损修复

**Feature**: 001-fix-spread-loss
**Date**: 2026-01-10

## 快速开始

本指南帮助您快速验证价差套利磨损修复功能。

## 前置条件

- Python 3.10+
- 已配置的.env文件（Extended和Lighter API凭证）
- 虚拟环境已激活

## 1. 环境准备

### 安装依赖

```bash
cd /Users/hufang/Desktop/web3\ project/perp/hufangperp
pip install -r requirements.txt
```

### 验证环境

```bash
python -c "import asyncio, websockets, decimal; print('✅ 依赖检查通过')"
```

## 2. 配置修改

### 更新spread/config.py

添加以下配置项：

```python
# Maker/Taker配置
extended_maker_fee_rate: Decimal = Decimal('0.0001')   # 假设值
extended_taker_fee_rate: Decimal = Decimal('0.000225')  # 确认值
maker_timeout_seconds: int = 5                          # Maker单超时
maker_timeout_action: str = "convert_to_taker"           # 转taker或取消
use_maker_orders: bool = True                            # 是否使用maker单
```

### 更新.env文件（可选）

```bash
# 如果需要覆盖默认值
EXTENDED_MAKER_FEE_RATE=0.0001
EXTENDED_TAKER_FEE_RATE=0.000225
MAKER_TIMEOUT_SECONDS=5
USE_MAKER_ORDERS=true
```

## 3. 运行测试

### 单元测试

```bash
# 价差计算器测试
pytest tests/test_calculator.py -v

# Maker/Taker策略测试
pytest tests/test_maker_taker.py -v

# 日志格式测试
pytest tests/test_trade_logger.py -v
```

**预期输出**：
```
tests/test_calculator.py::test_long_opportunity_correct_prices PASSED
tests/test_calculator.py::test_short_opportunity_correct_prices PASSED
tests/test_maker_taker.py::test_maker_timeout_handling PASSED
tests/test_trade_logger.py::test_log_format_valid_json PASSED
...
===================== 15 passed in 2.34s =====================
```

### 集成测试

```bash
# 修复验证测试
pytest tests/integration/test_fix_validation.py -v
```

**预期输出**：
```
tests/integration/test_fix_validation.py::test_only_opens_on_valid_spread PASSED
tests/integration/test_fix_validation.py::test_log_completeness PASSED
tests/integration/test_fix_validation.py::test_positive_pnl_after_fix PASSED
...
===================== 5 passed in 45.67s =====================
```

## 4. 运行程序

### 启动价差套利机器人

```bash
python spread/run_spread_arb.py --ticker ETH --size 35 --max-pairs 3
```

**预期输出**：
```
============================================================
价差套利机器人启动
============================================================
初始化中...
等待订单簿数据...
✅ Extended订单簿就绪
✅ Lighter订单簿就绪
✅ 初始化完成
------------------------------------------------------------
配置参数:
  交易对: ETH
  单次下单金额: $35
  最小价差率: 0.0500% (有效阈值: 0.0600% 含延迟缓冲)
  延迟缓冲: 0.0100%
  Maker单超时: 5秒
  Extended maker费率: 0.0100%
  Extended taker费率: 0.0225%
------------------------------------------------------------
策略循环启动
...
```

### 观察日志

实时查看交易日志：
```bash
tail -f logs/trade.log | jq
```

**预期日志格式**：
```json
{"timestamp": "2026-01-10T05:00:00.000Z", "level": "INFO", "event_type": "SYSTEM_START", ...}
{"timestamp": "2026-01-10T05:01:23.456Z", "level": "INFO", "event_type": "EXTENDED_ORDER_PLACED", ...}
```

## 5. 验证修复效果

### 检查价差条件验证

解析日志，确认只在正确条件下开仓：

```bash
cat logs/trade.log | jq 'select(.event_type == "SPREAD_OPPORTUNITY" and .data.decision == "OPEN")' | head -5
```

**预期结果**：
- 做多开仓：extended_bid < lighter_ask
- 做空开仓：extended_ask > lighter_bid

### 检查Maker单使用情况

```bash
cat logs/trade.log | jq 'select(.event_type == "EXTENDED_ORDER_PLACED") | .data.order_type' | sort | uniq -c
```

**预期结果**：
```
  25 "MAKER"
   3 "TAKER"  # 超时转taker
```

### 检查盈亏情况

运行1小时后：

```bash
cat logs/trade.log | jq 'select(.event_type == "POSITION_CLOSED") | .data.net_pnl' | awk '{sum+=$1} END {print sum}'
```

**预期结果**: 正值（之前为-3.03 USDT）

## 6. 解析日志数据

### 提取手续费数据

```python
import json

fees = {'maker': [], 'taker': []}

with open('logs/trade.log') as f:
    for line in f:
        entry = json.loads(line)
        if entry['event_type'] == 'EXTENDED_FILLED':
            fee_type = entry['data']['fee_type']
            fee_amount = float(entry['data']['estimated_fee'])
            fees[fee_type].append(fee_amount)

print(f"Maker手续费平均: {sum(fees['maker'])/len(fees['maker']):.6f}")
print(f"Taker手续费平均: {sum(fees['taker'])/len(fees['taker']):.6f}")
```

### 提取滑点数据

```python
import json

slippages = []

with open('logs/trade.log') as f:
    for line in f:
        entry = json.loads(line)
        if entry['event_type'] == 'LIGHTER_HEDGE':
            slippage = float(entry['data']['slippage_usdt'])
            slippages.append(slippage)

print(f"平均滑点: {sum(slippages)/len(slippages):.6f} USDT")
print(f"最大滑点: {max(slippages):.6f} USDT")
```

### 每小时统计摘要

```bash
cat logs/trade.log | jq 'select(.event_type == "HOURLY_STATISTICS")' | tail -1 | jq '.data'
```

## 7. 故障排查

### 问题：Maker单从不成交

**症状**：日志显示大量`EXTENDED_MAKER_TIMEOUT`

**解决方案**：
1. 增加`maker_timeout_seconds`到10秒
2. 或者设置`use_maker_orders=false`禁用maker单

### 问题：日志文件过大

**症状**：logs/trade.log超过100MB

**解决方案**：使用日志轮转
```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler('logs/trade.log', maxBytes=100*1024*1024, backupCount=5)
```

### 问题：仍然亏损

**检查清单**：
1. ✅ 验证价差计算修复是否生效（查看SPREAD_OPPORTUNITY日志）
2. ✅ 确认只在正确条件下开仓
3. ✅ 计算实际手续费和滑点
4. ✅ 检查maker单成交率

## 8. 下一步

修复验证通过后：

1. **数据收集阶段**（1周）
   - 运行程序收集实际交易数据
   - 记录maker单成交率
   - 计算真实成本结构

2. **策略优化阶段**
   - 基于数据调整maker超时时间
   - 优化开仓阈值
   - 调整maker使用频率

3. **高级功能**（可选）
   - 动态阈值调整
   - 日志分析工具
   - 自动化策略优化

---

**快速开始状态**: 已完成，可以开始实施。
