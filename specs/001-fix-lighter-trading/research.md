# Phase 0: 研究与决策

**功能**: 修复Lighter交易所下单失败和日志混乱问题
**日期**: 2026-01-12

## 研究任务

### 问题1: Lighter SDK AttributeError根本原因

**问题描述**: 日志显示 `AttributeError: 'NoneType' object has no attribute 'code'`

**代码分析**:
```python
# exchanges/lighter.py:548
result = await self.lighter_client.place_open_order(
    contract_id=contract_id,
    quantity=quantity,
    direction=direction
)
```

**根因分析**:
1. 错误发生在`lighter_client.place_open_order()`内部
2. 可能是`api_client.rest_client`为None
3. 代理配置可能在ApiClient创建后未正确应用到rest_client

**决策**: 修复`_initialize_lighter_client()`方法，确保在SignerClient创建后立即设置rest_client.proxy

**实现方案**:
```python
# 在SignerClient创建后立即设置代理
if proxy_url and hasattr(self.lighter_client, 'api_client'):
    if hasattr(self.lighter_client.api_client, 'rest_client'):
        self.lighter_client.api_client.rest_client.proxy = proxy_url
    else:
        # 如果rest_client尚未创建，延迟设置
        await asyncio.sleep(0.1)
        self.lighter_client.api_client.rest_client.proxy = proxy_url
```

**替代方案**: 完全移除代理配置（不推荐，因为可能在某些环境需要）

---

### 问题2: 日志标识混乱

**问题描述**: 无法快速区分Extended和Lighter的日志

**当前状态**:
- `TradingLogger.log()`方法添加`[EXTENDED_ETH]`或`[LIGHTER_ETH]`前缀
- 但某些日志直接使用logging模块，绕过了TradingLogger

**决策**: 在`TradingLogger`中增强日志标识，确保所有日志都包含清晰的交易所标识

**实现方案**:
1. 在`TradingLogger.log()`中使用大写交易所名称：`[EXTENDED]`和`[LIGHTER]`
2. 添加ticker作为次要标识：`[EXTENDED] ETH`
3. 为错误日志添加特殊标识：`[EXTENDED] ERROR`

**替代方案**: 使用结构化日志（如structlog）- 过度设计，当前需求不需要

---

### 问题3: 紧急平仓订单类型

**问题描述**: 当前紧急平仓可能使用maker订单，导致延迟成交

**代码位置**: `spread/concurrent_executor.py:emergency_close_position()`

**当前实现**:
```python
# 没有指定post_only参数，默认可能使用maker订单
result = await self._place_order_extended(order)
```

**决策**: 修改`emergency_close_position()`和相关的平仓方法，强制使用taker订单

**实现方案**:
1. 在`_place_order_extended()`和`_place_order_lighter()`中检测order_type='CLOSE'
2. 当检测到CLOSE类型时，强制设置post_only=False
3. 添加日志明确记录"使用taker订单进行紧急平仓"

**替代方案**: 创建专门的紧急平仓API端点 - 不必要，现有API已支持

---

## 技术选型

### 代理配置策略

**选项1**: 使用环境变量（当前方案）
- ✅ 灵活，不需要修改代码
- ✅ 符合12-factor应用原则
- ❌ 需要手动设置环境变量

**选项2**: 使用配置文件
- ✅ 可以版本控制
- ❌ 敏感信息（代理地址）不应提交
- ❌ 需要重启应用才能生效

**决策**: **选项1 - 使用环境变量**

### 日志标识格式

**选项1**: `[EXTENDED] message`
- ✅ 简洁
- ✅ 易于grep
- ❌ 不包含ticker信息

**选项2**: `[EXTENDED_ETH] message`（当前）
- ✅ 包含ticker
- ❌ 与日志文件名重复

**选项3**: `[EXTENDED] ETH message`
- ✅ 清晰分离交易所和ticker
- ✅ 可以只过滤交易所：`grep "\[EXTENDED\]"`
- ✅ 可以过滤特定交易对：`grep "\[EXTENDED\] ETH"`

**决策**: **选项3 - `[EXTENDED] ETH message`**

### 错误处理策略

**选项1**: 抛出异常
- ❌ 违反项目规范（不抛出异常）
- ❌ 会导致程序崩溃

**选项2**: 返回OrderResult(success=False, error_message=...)
- ✅ 符合项目规范
- ✅ 调用者可以决定如何处理
- ✅ 可以记录详细错误信息

**决策**: **选项2 - 返回OrderResult**

## 测试策略

### 单元测试

1. **test_lighter_proxy_configuration**: 测试代理配置是否正确应用
2. **test_logger_identifiers**: 测试日志标识格式
3. **test_emergency_close_uses_taker**: 测试紧急平仓使用taker订单

### 集成测试

1. **test_concurrent_orders_both_success**: 测试并发下单两个交易所都成功
2. **test_legging_detection**: 测试单腿持仓检测
3. **test_emergency_close_order_type**: 测试紧急平仓订单类型

## 未解决的问题

**无** - 所有关键技术决策已完成

## 参考资源

- Lighter SDK文档: https://github.com/Lighter-Dex/lighter-sdk
- Extended API文档: https://api.starknet.extended.exchange
- Python logging最佳实践: https://docs.python.org/3/howto/logging.html
