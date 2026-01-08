# Data Model: 持仓对账和API错误处理

**Feature**: 001-fix-lighter-api
**Date**: 2026-01-07

---

## 实体定义

### 1. PositionReconciliationRecord (持仓对账记录)

对账循环创建的记录，用于追踪两端持仓状态。

**字段**:

| 字段名 | 类型 | 描述 | 示例 |
|--------|------|------|------|
| `timestamp` | float | Unix时间戳 | 1704600000.123 |
| `extended_position_value` | Decimal | Extended持仓价值(USDT) | Decimal('35.50') |
| `extended_quantity` | Decimal | Extended持仓数量(ETH) | Decimal('0.011') |
| `extended_side` | str | Extended持仓方向 | 'buy' 或 'sell' |
| `lighter_position_value` | Decimal | Lighter持仓价值(USDT) | Decimal('95.72') |
| `lighter_quantity` | Decimal | Lighter持仓数量(ETH) | Decimal('-0.03') |
| `lighter_side` | str | Lighter持仓方向 | 'buy' 或 'sell' |
| `net_exposure` | Decimal | 净暴露(USDT) | Decimal('-60.22') |
| `imbalance_ratio` | Decimal | 不平衡比率(%) | Decimal('0.632') |
| `is_imbalanced` | bool | 是否超过阈值 | True |
| `alert_triggered` | bool | 是否触发警报 | True |

**计算公式**:
```python
net_exposure = extended_position_value - lighter_position_value
imbalance_ratio = abs(net_exposure) / max(extended_position_value, lighter_position_value)
is_imbalanced = imbalance_ratio > 0.20  # 20%阈值
```

**状态转换**:
- 创建 → 已记录 → (可选) 已处理

---

### 2. ApiErrorRecord (API错误记录)

记录API调用失败详情，用于调试和监控。

**字段**:

| 字段名 | 类型 | 描述 | 示例 |
|--------|------|------|------|
| `timestamp` | float | Unix时间戳 | 1704600000.456 |
| `api_method` | str | 尝试调用的方法 | 'account_active_orders' |
| `expected_method` | str | 正确的方法名 | 'account_inactive_orders' |
| `error_type` | str | 错误类型 | 'AttributeError' |
| `error_message` | str | 错误消息 | "'OrderApi' object has no attribute..." |
| `retry_count` | int | 重试次数 | 3 |
| `final_status` | str | 最终状态 | 'FAILED' 或 'SUCCESS' |

**状态**:
- 记录后不可变

---

### 3. ImbalanceWarning (不平衡警告)

当检测到严重不平衡时生成的警告对象。

**字段**:

| 字段名 | 类型 | 描述 | 示例 |
|--------|------|------|------|
| `timestamp` | float | Unix时间戳 | 1704600000.789 |
| `extended_value` | Decimal | Extended持仓价值 | Decimal('35.50') |
| `lighter_value` | Decimal | Lighter持仓价值 | Decimal('95.72') |
| `imbalance_amount` | Decimal | 不平衡金额 | Decimal('60.22') |
| `imbalance_ratio` | Decimal | 不平衡比率 | Decimal('0.632') |
| `suggested_action` | str | 建议的操作 | "平仓 Lighter空头 0.03 ETH" |
| `auto_closed` | bool | 是否已自动平仓 | False |
| `close_result` | str/None | 平仓结果 | None 或 'SUCCESS'/'FAILED' |

**状态转换**:
- 生成 → (可选) 自动处理 → 已确认/已忽略

---

## 关系图

```
PositionReconciliationRecord (1) ────< (0..*) ImbalanceWarning
                                   │
                                   │ 触发
                                   ↓
                            ApiErrorRecord (0..*)
```

**说明**:
- 每次对账创建一个`PositionReconciliationRecord`
- 如果不平衡超过阈值，创建一个或多个`ImbalanceWarning`
- `ApiErrorRecord`独立记录，与对账记录无直接关联

---

## 数据流

### 持仓对账流程

```text
开始对账循环
    ↓
获取Extended持仓
    ↓
获取Lighter持仓
    ↓
计算净暴露和不平衡比率
    ↓
创建 PositionReconciliationRecord
    ↓
is_imbalanced?
    ├─ No → 记录INFO日志
    └─ Yes → 创建 ImbalanceWarning
              ↓
              触发ERROR日志
              ↓
              auto_close_unhedged?
              ├─ Yes → 执行自动平仓 → 更新ImbalanceWarning
              └─ No → 发送平仓建议 → 保持熔断
```

---

## 验证规则

### VR-1: 持仓价值计算

```python
# Extended
assert extended_position_value == abs(extended_quantity * current_price)

# Lighter
assert lighter_position_value == abs(lighter_quantity * current_price)

# 净暴露
assert net_exposure == extended_position_value - lighter_position_value
```

### VR-2: 不平衡比率

```python
# 必须在 [0, 1] 范围内
assert 0 <= imbalance_ratio <= 1

# 阈值检查
if imbalance_ratio > 0.20:
    assert is_imbalanced == True
```

### VR-3: API错误记录

```python
# 必须有错误消息
assert len(error_message) > 0

# 重试次数必须 >= 0
assert retry_count >= 0
```

---

## 持久化

**当前实现**: 数据仅在内存中，记录到日志文件

**未来扩展**: 如需持久化，可使用SQLite或PostgreSQL：

```sql
CREATE TABLE reconciliation_records (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    extended_value DECIMAL(20, 8) NOT NULL,
    lighter_value DECIMAL(20, 8) NOT NULL,
    net_exposure DECIMAL(20, 8) NOT NULL,
    imbalance_ratio DECIMAL(10, 4) NOT NULL,
    is_imbalanced BOOLEAN NOT NULL
);

CREATE INDEX idx_timestamp ON reconciliation_records(timestamp);
CREATE INDEX idx_imbalanced ON reconciliation_records(is_imbalanced);
```

---

## 配置参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `reconciliation_interval` | int | 60 | 对账间隔(秒) |
| `imbalance_threshold` | Decimal | 0.20 | 不平衡阈值(20%) |
| `auto_close_unhedged` | bool | False | 是否自动平仓 |
| `max_slippage` | Decimal | 0.01 | 最大滑点容忍度(1%) |
