# Data Model: CLOSE订单处理修复

**Feature**: 006-fix-lighter-close
**Date**: 2026-01-09
**Status**: Final

## 概述

本功能不引入新的数据实体，主要是修复现有订单管理器对CLOSE类型订单的处理逻辑。以下是对现有数据模型的验证和说明。

## 实体定义

### 1. SpreadPair（套利对）

**位置**: `spread/spread_pair.py`

**描述**: 表示一个价差套利对，包含Extended和Lighter两个交易所的仓位信息

**字段**:

| 字段名 | 类型 | 描述 | 验证规则 |
|--------|------|------|----------|
| `pair_id` | int | 套利对唯一标识符 | > 0, 自动递增 |
| `extended_side` | str | Extended交易所的仓位方向 | 'buy' 或 'sell' |
| `extended_quantity` | Decimal | Extended仓位数量 | > 0 |
| `extended_price` | Decimal | Extended开仓价格 | > 0 |
| `lighter_quantity` | Decimal | Lighter仓位数量 | > 0 |
| `lighter_price` | Decimal | Lighter开仓价格 | > 0 |
| `open_time` | float | 开仓时间戳（Unix时间） | > 0 |
| `close_extended_price` | Decimal | Extended平仓价格 | 可选，平仓时设置 |
| `close_lighter_price` | Decimal | Lighter平仓价格 | 可选，平仓时设置 |
| `is_closing` | bool | 是否正在平仓中 | 防止重复平仓 |
| `close_extended_order_id` | str | Extended平仓订单ID | 可选，平仓时设置 |
| `close_lighter_order_id` | str | Lighter平仓订单ID | 可选，平仓时设置 |

**状态转换**:

```
OPEN (开仓中)
  ↓ (开仓成功)
OPENED (已开仓/持仓中)
  ↓ (触发平仓)
CLOSING (平仓中) [is_closing=True]
  ↓ (平仓成功)
CLOSED (已平仓)
```

**关键方法**:
- `close(close_extended_price, close_lighter_price) -> Decimal`: 计算并记录平仓盈亏
- `holding_time -> float`: 计算持仓时长（秒）

---

### 2. OrderUpdate（订单状态更新）

**位置**: WebSocket消息结构

**描述**: Extended交易所通过WebSocket推送的订单状态更新消息

**字段**:

| 字段名 | 类型 | 描述 | 示例值 |
|--------|------|------|--------|
| `order_id` | str | 订单唯一标识符 | "2009608496505368576" |
| `status` | str | 订单状态 | "FILLED", "OPEN", "CANCELLED" |
| `filled_size` | str | 已成交数量（字符串格式） | "0.010" |
| `price` | str | 成交价格（字符串格式） | "3082.8" |
| `order_type` | str | 订单类型 | "OPEN" 或 "CLOSE" |
| `side` | str | 订单方向 | "buy" 或 "sell" |
| `contract_id` | str | 合约标识符 | "ETH-USD" |

**验证规则**:
- `order_id`: 非空字符串
- `status`: 必须是有效状态值之一
- `filled_size`: 必须能转换为Decimal，值 ≥ 0
- `price`: 必须能转换为Decimal，值 > 0
- `order_type`: "OPEN" 或 "CLOSE"（本功能修复点：CLOSE不再被忽略）

---

### 3. SpreadOrderManager State（订单管理器状态）

**位置**: `spread/order_manager.py`

**描述**: `SpreadOrderManager`实例维护的当前订单状态

**字段**:

| 字段名 | 类型 | 描述 | 初始值 |
|--------|------|------|--------|
| `current_order_id` | Optional[str] | 当前订单ID | None |
| `current_order_status` | Optional[str] | 当前订单状态 | None |
| `filled_quantity` | Decimal | 已成交数量 | Decimal('0') |
| `filled_price` | Decimal | 成交价格 | Decimal('0') |
| `_pending_updates` | Dict[str, list] | 待应用的订单更新缓存 | {} |

**状态生命周期**:

```
下单前重置:
  current_order_id = None
  current_order_status = None
  filled_quantity = Decimal('0')
  filled_price = Decimal('0')

↓ place_spread_maker_order()

下单后设置:
  current_order_id = order_id
  (立即应用缓存更新)

↓ WebSocket订单更新到达

update_order_status():
  if order_id == current_order_id:
    current_order_status = order_data['status']
    filled_quantity = Decimal(order_data['filled_size'])
    filled_price = Decimal(order_data['price'])

↓ wait_for_fill()

等待成交:
  if current_order_status == 'FILLED':
    return {status: 'FILLED', filled_quantity: ..., ...}
```

**关键行为变更**（本功能修复）：
- **修复前**: `order_type == 'CLOSE'`时直接返回，不更新状态
- **修复后**: CLOSE订单更新与OPEN订单更新同样处理，更新状态

---

### 4. CloseOrder（平仓订单概念）

**位置**: 概念实体，通过`SpreadOrderManager`处理

**描述**: 平仓订单是CLOSE类型的订单，与OPEN订单使用相同的状态管理机制

**属性**:

| 属性 | 类型 | 描述 |
|------|------|------|
| `order_id` | str | 订单ID |
| `exchange` | str | 交易所标识（"Extended" 或 "Lighter"） |
| `order_type` | str | 固定为 "CLOSE" |
| `side` | str | 平仓方向（与开仓相反） |
| `status` | str | 订单状态 |
| `filled_size` | Decimal | 成交数量 |
| `filled_price` | Decimal | 成交价格 |

**关键点**：
- Extended平仓订单通过`SpreadOrderManager`处理（本功能修复范围）
- Lighter平仓订单通过`HedgeManager`处理（不需要修改）

---

## 数据流

### 平仓流程数据流

```
1. 触发平仓 (_force_close_pair)
   ↓
2. 构造opportunity字典
   {
     'side': 'sell' (如果做多),
     'extended_price': extended_bid,
     'lighter_price': lighter_ask
   }
   ↓
3. 调用_close_pair(pair, opportunity)
   ↓
4. Extended平仓 (order_manager.place_spread_maker_order)
   - 重置状态
   - 提交CLOSE订单
   - 设置current_order_id
   - 应用缓存更新
   ↓
5. WebSocket收到CLOSE订单更新 [本功能修复点]
   - 修复前: 被忽略
   - 修复后: 正常处理
   ↓
6. wait_for_fill等待成交
   - 检查current_order_status
   - 返回成交结果
   ↓
7. Lighter平仓 (hedge_manager.execute_hedge)
   - 提交市价单
   - 等待成交
   ↓
8. 更新SpreadPair状态
   - 设置close_extended_price
   - 设置close_lighter_price
   - 设置订单ID
   ↓
9. 从open_pairs移除，添加到closed_pairs
```

---

## 边界情况

### 1. 竞态条件：订单更新在订单ID设置前到达

**场景**: WebSocket推送CLOSE订单更新时，`current_order_id`尚未设置

**处理**:
- 订单更新被缓存到`_pending_updates`
- 在`place_spread_maker_order`设置`current_order_id`后立即应用缓存
- 按时间戳升序应用，保证状态更新顺序

### 2. 多个套利对同时平仓

**场景**: 多个套利对同时触发强制平仓

**处理**:
- 每个`SpreadPair`独立处理
- `SpreadOrderManager`状态在每次下单前重置
- 订单ID匹配确保更新应用到正确的订单

### 3. CLOSE订单更新filled_size为0

**场景**: WebSocket消息中`filled_size`字段为"0"或缺失

**处理**:
```python
filled_size = Decimal(str(order_data.get('filled_size', 0)))
if filled_size > 0:
    self.filled_quantity = filled_size
```
- 只在`filled_size > 0`时更新
- 避免用0覆盖已有成交数量

---

## 验证规则总结

### 必须验证的规则

1. **CLOSE订单必须被处理**:
   - 接收CLOSE类型订单更新
   - 更新`current_order_status`
   - 更新`filled_quantity`和`filled_price`

2. **订单ID匹配**:
   - 只应用匹配`current_order_id`的订单更新
   - 不匹配的更新被缓存或忽略

3. **状态重置**:
   - 每次下单前重置状态
   - 防止不同订单的状态混淆

4. **数值精度**:
   - 所有价格和数量使用Decimal类型
   - 避免浮点数精度问题

### 测试覆盖要求

- 单元测试：验证CLOSE订单处理逻辑
- 集成测试：验证完整平仓流程
- 边界测试：验证竞态条件处理
