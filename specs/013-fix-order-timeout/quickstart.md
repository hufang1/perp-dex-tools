# Quickstart: 修复订单执行超时和假阳性成交问题

**Feature**: 013-fix-order-timeout
**Date**: 2026-01-11

---

## Overview

本功能修复两个导致订单执行失败的关键bug，使系统能够正常执行并发订单。

**修复内容**：
1. Extended IOC订单立即返回，不等待阻塞的`get_order_info()`
2. Lighter验证`order_id`存在性，避免假阳性成交
3. 增强错误日志，显示具体失败原因

---

## Prerequisites

### Environment

- Python 3.11+
- pytest（测试）
- 两个交易所的API访问权限（Extended, Lighter）

### Dependencies

```bash
pip install -r requirements.txt
```

---

## Installation

### 1. 切换到功能分支

```bash
cd /Users/hufang/Desktop/web3 project/perp/hufangperp
git checkout 013-fix-order-timeout
```

### 2. 验证修改

```bash
# 查看修改的文件
git status

# 应该看到以下文件（已有修改）：
# modified:   exchanges/extended.py
# modified:   exchanges/lighter.py
# modified:   spread/concurrent_executor.py
```

---

## Testing

### 运行单元测试

```bash
# Extended修复测试
pytest tests/test_extended_fix.py -v

# Lighter修复测试
pytest tests/test_lighter_fix.py -v
```

### 运行集成测试

```bash
# 完整集成测试
pytest tests/integration/test_order_timeout_fix_integration.py -v
```

### 预期结果

```
tests/test_extended_fix.py::test_ioc_order_immediate_return PASSED
tests/test_extended_fix.py::test_post_only_order_queries_status PASSED
tests/test_extended_fix.py::test_order_timeout_handling PASSED

tests/test_lighter_fix.py::test_order_id_none_returns_failure PASSED
tests/test_lighter_fix.py::test_order_id_exists_returns_success PASSED
tests/test_lighter_fix.py::test_api_fallback_verification PASSED

tests/integration/test_order_timeout_fix_integration.py::test_both_orders_succeed PASSED
tests/integration/test_order_timeout_fix_integration.py::test_both_orders_fail_no_legging PASSED
tests/integration/test_order_timeout_fix_integration.py::test_true_legging_triggers_rollback PASSED
```

---

## Development Workflow

### 本地测试

```bash
# 1. 运行套利机器人（干运行模式）
python spread/bot.py --ticker ETH --size 35 --max-pairs 3 --dry-run

# 2. 观察日志输出，应该看到：
#    - Extended订单在100ms内返回
#    - 不再有"success=True, order_id=None"的情况
#    - 失败日志显示具体错误原因

# 3. 检查交易日志
tail -f logs/trade.log
```

### 验证修复效果

**修复前**：
```
WARNING: Extended: success=False, order_id=None, error=timeout
WARNING: Lighter: success=True, order_id=None, error=None
ERROR: 单腿持仓，触发紧急回滚
```

**修复后**：
```
WARNING: Extended: success=False, order_id=None, error=timeout
WARNING: Lighter: success=False, order_id=None, error=No order_id in callback
ERROR: 双边失败，不触发回滚
```

---

## Key Changes Reference

### 1. Extended修复 (`exchanges/extended.py`)

**位置**: `place_open_order()` 方法，约第297-309行

**修改前**：
```python
# 提交订单后总是查询状态
await asyncio.sleep(0.01)
order_info = await self.get_order_info(order_id)  # 阻塞！
```

**修改后**：
```python
# IOC订单立即返回
if not post_only:
    return OrderResult(
        success=True,
        order_id=order_id,
        status='OPEN'
    )
# Post-Only订单继续查询状态
```

---

### 2. Lighter修复 (`exchanges/lighter.py`)

**位置**: `place_open_order()` 方法，约第335-352行

**修改前**：
```python
if self.current_order is not None:
    return OrderResult(
        success=(self.current_order.status == 'FILLED'),
        order_id=self.current_order.order_id,  # 可能为None！
        ...
    )
```

**修改后**：
```python
if self.current_order is not None:
    if self.current_order.order_id is not None:
        return OrderResult(
            success=(self.current_order.status == 'FILLED'),
            order_id=self.current_order.order_id,
            ...
        )
    else:
        # order_id为None，查询API验证
        self.logger.log("[警告] order_id为None", "WARNING")
```

---

### 3. 错误日志增强 (`spread/concurrent_executor.py`)

**位置**: 日志记录部分，约第300-321行

**修改前**：
```python
self.logger.warning(
    f"⚠️ [单腿持仓] {success_side}: 成交, {fail_side}: 失败"
)
```

**修改后**：
```python
self.logger.warning(
    f"⚠️ [单腿持仓] {success_side}: 成交, {fail_side}: 失败 | "
    f"Extended: success={ext_success}, order_id={ext_order_id}, error={ext_error} | "
    f"Lighter: success={lit_success}, order_id={lit_order_id}, error={lit_error}"
)
```

---

## Troubleshooting

### 问题1: Extended订单仍然超时

**症状**: 日志显示`Extended: success=False, order_id=None, error=timeout`

**可能原因**:
- Extended SDK响应时间 > 500ms（网络问题）
- 订单参数无效被拒绝

**解决方案**:
1. 检查网络连接
2. 查看Extended SDK详细日志
3. 验证订单参数（价格、数量）

---

### 问题2: Lighter返回`success=False`但实际成交了

**症状**: 日志显示`Lighter: success=False`但Lighter交易所显示订单已成交

**可能原因**:
- WebSocket回调未到达（0.5秒内）
- `get_inactive_orders()`查询延迟

**解决方案**:
1. 增加等待时间（修改0.5秒 → 1秒）
2. 检查WebSocket连接状态
3. 验证API查询逻辑

---

### 问题3: 单腿持仓误报

**症状**: 双边订单都失败但触发了单腿持仓回滚

**可能原因**:
- 代码未正确应用修复
- 日志显示的是旧版本代码

**解决方案**:
1. 确认在正确的分支（`013-fix-order-timeout`）
2. 检查修改是否正确应用
3. 重启机器人

---

## Success Metrics

修复后应该观察到：

| 指标 | 修复前 | 修复后 | 目标 |
|------|--------|--------|------|
| Extended订单响应时间 | >500ms | <100ms | <100ms |
| Lighter假阳性率 | 100% | 0% | 0% |
| 单腿持仓误报率 | 高 | 0% | 0% |
| 订单执行成功率 | 0% | >90% | >90% |

---

## Next Steps

1. ✅ 代码修改已完成
2. ⏳ 运行测试验证
3. ⏳ 本地测试1小时
4. ⏳ 提交代码审查
5. ⏳ 合并到主分支

---

## Contact

如有问题，请查看：
- 规格文档: [spec.md](./spec.md)
- 实现计划: [plan.md](./plan.md)
- 数据模型: [data-model.md](./data-model.md)
