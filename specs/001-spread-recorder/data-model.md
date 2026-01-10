# Data Model: 价差实时记录器

**Feature**: 价差实时记录器 (001-spread-recorder)
**Date**: 2026-01-10

## Overview

本文档定义价差记录器的核心数据模型，包括SpreadRecord实体、配置参数和CSV文件格式。

## Core Entities

### 1. SpreadRecord

表示单次价差采样的完整数据。

**Type**: `dataclass` or `NamedTuple`

**Fields**:

| Field Name | Type | Description | Validation |
|------------|------|-------------|------------|
| `timestamp` | `str` | 采样时间戳 (ISO 8601格式, 精确到毫秒) | Required, format: `YYYY-MM-DD HH:MM:SS.mmm` |
| `extended_bid` | `Decimal` | Extended交易所买一价 | > 0 |
| `extended_ask` | `Decimal` | Extended交易所卖一价 | > 0, > bid |
| `lighter_bid` | `Decimal` | Lighter交易所买一价 | > 0 |
| `lighter_ask` | `Decimal` | Lighter交易所卖一价 | > 0, > bid |
| `long_spread` | `Decimal` | 做多价差值 (lighter_bid - extended_ask) | Can be negative |
| `long_spread_rate` | `Decimal` | 做多价差率 (long_spread / lighter_bid) | Can be negative |
| `short_spread` | `Decimal` | 做空价差值 (extended_bid - lighter_ask) | Can be negative |
| `short_spread_rate` | `Decimal` | 做空价差率 (short_spread / extended_bid) | Can be negative |
| `extended_spread_cost` | `Decimal` | Extended点差成本率 | >= 0 |
| `lighter_spread_cost` | `Decimal` | Lighter点差成本率 | >= 0 |
| `total_cost_rate` | `Decimal` | 总成本率 (extended + lighter) | >= 0 |
| `status` | `str` | 数据状态 ("VALID" 或 "INVALID") | Required |

**Python Implementation**:
```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class SpreadRecord:
    """价差记录数据模型"""
    timestamp: str
    extended_bid: Decimal
    extended_ask: Decimal
    lighter_bid: Decimal
    lighter_ask: Decimal
    long_spread: Decimal
    long_spread_rate: Decimal
    short_spread: Decimal
    short_spread_rate: Decimal
    extended_spread_cost: Decimal
    lighter_spread_cost: Decimal
    total_cost_rate: Decimal
    status: str  # "VALID" or "INVALID"
```

**State Transitions**: None (immutable record)

### 2. SpreadRecorderConfig

控制价差记录器行为的配置参数。

**Type**: `dataclass` (merged into `SpreadArbConfig`)

**Fields**:

| Field Name | Type | Description | Default | Validation |
|------------|------|-------------|---------|------------|
| `enable_spread_recorder` | `bool` | 是否启用价差记录器 | `True` | - |
| `spread_recorder_interval` | `int` | 采样间隔（秒） | `5` | > 0, 建议 >= 1 |
| `spread_recorder_output_dir` | `str` | CSV输出目录路径 | `"data"` | Valid directory path |
| `spread_recorder_buffer_size` | `int` | 缓冲区大小（记录数） | `100` | > 0 |
| `spread_recorder_log_level` | `str` | 日志级别 | `"INFO"` | DEBUG/INFO/WARNING/ERROR |
| `spread_recorder_flush_interval` | `int` | 缓冲刷新间隔（秒） | `60` | > 0 |

**Python Implementation** (in `spread/config.py`):
```python
@dataclass
class SpreadArbConfig:
    # ... existing fields ...

    # ==================== 价差记录器配置 ====================
    enable_spread_recorder: bool = True
    spread_recorder_interval: int = 5
    spread_recorder_output_dir: str = "data"
    spread_recorder_buffer_size: int = 100
    spread_recorder_log_level: str = "INFO"
    spread_recorder_flush_interval: int = 60
```

## CSV File Format

### File Naming Convention

**Pattern**: `spreads_YYYY_MM_DD.csv`

**Examples**:
- `spreads_2026_01_10.csv`
- `spreads_2026_12_31.csv`

**Timezone**: UTC (使用`datetime.now(timezone.utc)`)

### CSV Schema

**Header** (first row):
```csv
timestamp,extended_bid,extended_ask,lighter_bid,lighter_ask,long_spread,long_spread_rate,short_spread,short_spread_rate,extended_spread_cost,lighter_spread_cost,total_cost_rate,status
```

**Data Row**:
```csv
2026-01-10 12:34:56.789,3087.50,3087.60,3089.30,3089.42,-1.70,-0.000550,-1.92,-0.000622,0.000032,0.000039,0.000071,VALID
```

**Column Descriptions**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `timestamp` | String | 采样时间戳 | `2026-01-10 12:34:56.789` |
| `extended_bid` | Decimal | Extended买一价 | `3087.50` |
| `extended_ask` | Decimal | Extended卖一价 | `3087.60` |
| `lighter_bid` | Decimal | Lighter买一价 | `3089.30` |
| `lighter_ask` | Decimal | Lighter卖一价 | `3089.42` |
| `long_spread` | Decimal | 做多价差值 | `-1.70` |
| `long_spread_rate` | Decimal | 做多价差率 | `-0.000550` |
| `short_spread` | Decimal | 做空价差值 | `-1.92` |
| `short_spread_rate` | Decimal | 做空价差率 | `-0.000622` |
| `extended_spread_cost` | Decimal | Extended点差成本率 | `0.000032` |
| `lighter_spread_cost` | Decimal | Lighter点差成本率 | `0.000039` |
| `total_cost_rate` | Decimal | 总成本率 | `0.000071` |
| `status` | String | 数据状态 | `VALID` or `INVALID` |

**File Encoding**: UTF-8 with BOM (for Excel compatibility)

**Line Ending**: LF (`\n`) for cross-platform compatibility

## Data Flow

### 1. Data Collection

```
订单簿WebSocket → bot.py → SpreadRecorder.record_loop()
                                ↓
                        _get_current_prices()
                                ↓
                        RealSpreadCalculator.calculate_*_spread()
                                ↓
                        SpreadRecord created
                                ↓
                        _write_to_buffer()
```

### 2. Buffer Management

```
SpreadRecord → buffer[]
                          ↓
                    buffer size >= 100?
                          ↓
              ┌───────────┴───────────┐
              Yes                     No
              ↓                       ↓
        _flush_buffer()          Continue
              ↓
        Write to CSV file
```

### 3. File Rotation

```
Check date every record
        ↓
Date changed?
        ↓
┌───────┴────────┐
Yes               No
↓                 ↓
Flush buffer    Continue
Close old file
Create new file
Write header
```

## Validation Rules

### Input Validation (Prices)

```python
def _validate_prices(bid: Decimal, ask: Decimal) -> bool:
    """验证价格数据有效性"""
    if bid <= 0 or ask <= 0:
        return False
    if bid >= ask:  # 订单簿异常
        return False
    return True
```

### Output Validation (CSV)

```python
def _validate_record(record: SpreadRecord) -> bool:
    """验证记录完整性"""
    # 必填字段
    if not record.timestamp:
        return False
    if record.status not in ["VALID", "INVALID"]:
        return False

    # 如果status是VALID，价格必须有效
    if record.status == "VALID":
        if record.extended_bid <= 0:
            return False
        # ... other validations

    return True
```

## Error States

### 1. Invalid Price Data

**Condition**: `bid <= 0` or `ask <= 0` or `bid >= ask`

**Action**:
- Set `status = "INVALID"`
- Set all spread/cost fields to `Decimal('0')`
- Log WARNING with details
- Still write to CSV (for debugging)

**Example Row**:
```csv
2026-01-10 12:35:01.123,0.00,0.00,3089.30,3089.42,0.00,0.000000,0.00,0.000000,0.000000,0.000000,0.000000,INVALID
```

### 2. CSV Write Failure

**Condition**: Disk full, permission denied, etc.

**Action**:
- Log ERROR with exception details
- Keep data in buffer (retry next flush)
- DO NOT raise exception (don't interrupt trading)

### 3. Buffer Overflow

**Condition**: Buffer size exceeds maximum (shouldn't happen with proper flushing)

**Action**:
- Force flush immediately
- Log WARNING

## Relationships

```
SpreadArbConfig
       │
       ├── contains ───> SpreadRecorderConfig (merged into main config)
       │
       └── used by ────> SpreadRecorder
                            │
                            ├── uses ────> RealSpreadCalculator
                            ├── creates ──> SpreadRecord
                            └── writes ───> CSV File (spreads_YYYY_MM_DD.csv)
```

## Indexes & Queries

### Pandas Usage Example

```python
import pandas as pd

# 读取CSV
df = pd.read_csv('data/spreads_2026_01_10.csv')

# 查询：价差超过0.1%的次数
count = len(df[df['long_spread_rate'] > 0.001])

# 查询：价差分布统计
stats = df['long_spread_rate'].describe()

# 查询：无效记录数
invalid_count = len(df[df['status'] == 'INVALID'])

# 查询：特定时间段
morning = df[df['timestamp'].between('2026-01-10 00:00:00', '2026-01-10 12:00:00')]
```

## Memory Footprint

### SpreadRecord
- Size: ~200 bytes per instance (Decimal objects are heavy)
- Buffer (100 records): ~20KB
- Acceptable memory overhead

### CSV File
- 17,280 records/day
- ~200 bytes/record
- ~3.5MB/day
- ~100MB/month (with 30 days retention)

## Data Retention

**Recommendation**: Implement a cleanup policy to manage disk space.

**Options**:
1. **Time-based**: Delete files older than N days
2. **Count-based**: Keep only last N files
3. **Size-based**: Delete oldest when total size exceeds limit

**Implementation** (optional):
```python
def cleanup_old_csv_files(output_dir: str, keep_days: int = 30):
    """删除超过指定天数的CSV文件"""
    cutoff_date = datetime.now() - timedelta(days=keep_days)
    for filename in os.listdir(output_dir):
        if filename.startswith('spreads_') and filename.endswith('.csv'):
            file_date = datetime.strptime(filename.split('_')[1].replace('.csv', ''), '%Y_%m_%d')
            if file_date < cutoff_date:
                os.remove(os.path.join(output_dir, filename))
```

## Migration Path

### Phase 1: Initial Implementation
- Create `SpreadRecord` dataclass
- Implement `SpreadRecorder` with basic CSV writing
- Add configuration to `SpreadArbConfig`

### Phase 2: Integration
- Integrate `SpreadRecorder` into `bot.py`
- Add async task for recording loop
- Test with live data

### Phase 3: Enhancement (Future)
- Add compression for old files
- Implement data retention policy
- Add visualization/statistics generation
