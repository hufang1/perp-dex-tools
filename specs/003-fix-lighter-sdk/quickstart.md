# Quick Start: 验证Lighter SDK修复

**Feature**: 003-fix-lighter-sdk
**Date**: 2026-01-12

## 概述

本文档提供快速验证Lighter SDK修复效果的步骤，确保下单成功率从0%提升到90%以上。

## 前置条件

- ✅ Python 3.10.19环境
- ✅ 已安装lighter-sdk 0.1.4
- ✅ 配置了环境变量：`API_KEY_PRIVATE_KEY`, `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX`
- ✅ 网络连接可以访问Lighter交易所API

## 验证步骤

### Step 1: 运行单元测试

验证SDK健康检查和对象验证功能。

```bash
cd /Users/hufang/Desktop/web3\ project/perp/hufangperp

# 运行SDK健康检查测试
pytest tests/test_lighter_sdk_health.py -v

# 预期输出：所有测试通过
# tests/test_lighter_sdk_health.py::test_validate_sdk_objects_all_present PASSED
# tests/test_lighter_sdk_health.py::test_validate_sdk_objects_missing_client PASSED
# tests/test_lighter_sdk_health.py::test_validate_sdk_objects_missing_api_client PASSED
# tests/test_lighter_sdk_health.py::test_check_sdk_health_success PASSED
# tests/test_lighter_sdk_health.py::test_check_sdk_health_failed PASSED
```

### Step 2: 运行集成测试

验证完整的下单流程。

```bash
# 运行集成测试
pytest tests/integration/test_lighter_order_fix_integration.py -v -s

# 预期输出：集成测试通过
# tests/integration/test_lighter_order_fix_integration.py::test_concurrent_orders_both_success PASSED
# tests/integration/test_lighter_order_fix_integration.py::test_legging_detection PASSED
```

### Step 3: 启动机器人并观察日志

运行套利机器人，观察Lighter下单是否成功。

```bash
cd /Users/hufang/Desktop/web3\ project/perp/hufangperp

# 启动机器人
python spread/bot.py --ticker ETH --size 35 --max-pairs 3

# 观察日志输出，查找以下关键信息：
```

**成功标志**：
```
✅ [双腿成交] Extended: order_id_xxx, Lighter: order_id_yyy
```

**失败标志**（不应该出现）：
```
❌ [双边失败] Lighter: success=False, error=AttributeError
⚠️ [单腿持仓] Extended: 成交, Lighter: 失败
```

### Step 4: 验证SDK健康检查

检查健康检查日志是否正常输出。

```bash
# 查看日志文件
tail -f logs/trade.log | grep -E "SDK|健康|Health"

# 预期输出：
# [LIGHTER] SDK validation passed: all objects initialized
# [LIGHTER] CheckClient passed: SDK initialized successfully
```

### Step 5: 统计下单成功率

运行10次套利机会，统计Lighter下单成功率。

```bash
# 从日志中提取下单结果
grep "双腿成交\|单腿持仓" logs/trade.log | tail -20

# 计算成功率：
# 成功率 = ("双腿成交"次数 / 总次数) * 100%
# 目标：>= 90%
```

## 验证检查清单

### SDK初始化验证

- [ ] 启动时没有`AttributeError`异常
- [ ] 日志显示`SDK validation passed`
- [ ] 日志显示`CheckClient passed`
- [ ] 所有对象状态为`exists=True`

### 下单功能验证

- [ ] Extended下单成功（order_id不为None）
- [ ] Lighter下单成功（order_id不为None）
- [ ] 日志显示"双腿成交"
- [ ] 并发发送时间差<5ms

### 错误处理验证

- [ ] SDK初始化失败时，日志明确指出哪个对象为None
- [ ] 健康检查失败时，拒绝下单
- [ ] 错误日志包含完整的SDK状态快照
- [ ] 不会触发单腿持仓回滚（除非真的下单失败）

### 性能验证

- [ ] SDK初始化时间<5秒
- [ ] 健康检查耗时<100ms
- [ ] 总执行时间<500ms（目标）
- [ ] 不会因为健康检查而显著降低性能

## 常见问题排查

### 问题1: SDK初始化仍然失败

**症状**：启动时出现`AttributeError: 'NoneType' object has no attribute 'code'`

**排查步骤**：
1. 检查环境变量是否正确设置
2. 检查网络连接是否正常
3. 检查代理配置是否正确
4. 查看日志中的SDK状态快照

**解决方案**：
```bash
# 检查环境变量
echo $API_KEY_PRIVATE_KEY
echo $LIGHTER_ACCOUNT_INDEX
echo $LIGHTER_API_KEY_INDEX

# 测试网络连接
curl -I https://mainnet.zklighter.elliot.ai

# 如果使用代理，测试代理连接
curl -I -x $https_proxy https://mainnet.zklighter.elliot.ai
```

### 问题2: 健康检查超时

**症状**：下单前健康检查耗时>1秒

**排查步骤**：
1. 检查网络延迟
2. 检查`check_client()`调用时间
3. 查看是否有代理配置问题

**解决方案**：
- 如果网络延迟高，考虑增加健康检查超时时间
- 如果代理配置有问题，考虑禁用代理或修正配置

### 问题3: 单腿持仓仍然发生

**症状**：Extended成交但Lighter失败

**排查步骤**：
1. 检查Lighter下单失败的具体原因
2. 查看错误日志中的SDK状态快照
3. 检查是否有网络中断

**解决方案**：
- 如果是SDK对象缺失，检查初始化逻辑
- 如果是API调用失败，检查网络和代理
- 如果是订单被拒绝，检查订单参数

## 性能基准

### SDK初始化性能

| 指标 | 目标 | 当前 | 状态 |
|------|------|------|------|
| 初始化时间 | <5秒 | TBD | ⏳ |
| 对象验证 | <1ms | TBD | ⏳ |
| 健康检查 | <100ms | TBD | ⏳ |

### 下单性能

| 指标 | 目标 | 当前 | 状态 |
|------|------|------|------|
| 并发发送延迟 | <5ms | 0.04ms | ✅ |
| 总执行时间 | <500ms | 627ms | ⚠️ |
| Lighter成功率 | >=90% | 0% | ❌ |

## 回归测试清单

在部署到生产环境前，确认以下测试全部通过：

### 单元测试
- [ ] `test_validate_sdk_objects_all_present`
- [ ] `test_validate_sdk_objects_missing_client`
- [ ] `test_validate_sdk_objects_missing_api_client`
- [ ] `test_check_sdk_health_success`
- [ ] `test_check_sdk_health_failed`
- [ ] `test_get_sdk_state_snapshot`
- [ ] `test_log_sdk_state_snapshot`

### 集成测试
- [ ] `test_concurrent_orders_both_success`
- [ ] `test_legging_detection`
- [ ] `test_emergency_close_uses_taker_order`

### 端到端测试
- [ ] 启动机器人后SDK初始化成功
- [ ] 触发套利机会后下单成功
- [ ] 10次机会中至少9次双腿成交
- [ ] 没有出现单腿持仓导致的紧急平仓

## 下一步

验证通过后：

1. **部署到生产环境**
2. **监控下单成功率**
3. **收集性能指标**
4. **根据实际情况调整参数**

如果验证失败，参考[research.md](./research.md)和[data-model.md](./data-model.md)进行调试。
