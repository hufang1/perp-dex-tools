# Research: 价差实时记录器

**Feature**: 价差实时记录器 (001-spread-recorder)
**Date**: 2026-01-10
**Status**: Complete

## Overview

本文档记录价差实时记录器的设计研究，包括技术选择、架构决策和与现有系统的集成方式。

## Decision 1: CSV文件格式

**Selected**: 使用Python标准库`csv`模块，逗号分隔值格式

**Rationale**:
- 与pandas、Excel完全兼容，满足需求
- Python标准库，无额外依赖
- 人类可读，便于调试
- 文件压缩后存储效率高

**Alternatives Considered**:
- **JSON**: 优点是结构化，缺点是文件更大、pandas读取稍慢、不便于Excel直接打开
- **SQLite**: 优点是支持复杂查询，缺点是增加依赖、过度设计（需求只是简单记录）
- **MessagePack/Parquet**: 优点是压缩率高，缺点是失去人类可读性、需要额外依赖

**CSV Schema**:
```csv
timestamp,extended_bid,extended_ask,lighter_bid,lighter_ask,long_spread,long_spread_rate,short_spread,short_spread_rate,extended_spread_cost,lighter_spread_cost,total_cost_rate
2026-01-10 12:34:56.789,3087.50,3087.60,3089.30,3089.42,-2.10,-0.000680,1.90,0.000615,0.000032,0.000039,0.000071
```

## Decision 2: 异步任务架构

**Selected**: 使用`asyncio.create_task()`创建独立的异步任务，与现有bot.py的异步架构一致

**Rationale**:
- 现有代码库已经使用asyncio（`_strategy_loop`, `_monitor_pairs`, `_stats_reporter`都是异步任务）
- 不需要引入线程或进程，避免锁的复杂性
- 可以优雅地与主循环一起启动和停止

**Alternatives Considered**:
- **Thread**: 优点是与同步代码兼容，缺点是需要锁保护共享资源、与asyncio事件循环集成复杂
- **Process**: 优点是真正的并行，缺点是进程间通信复杂、内存开销大
- **同步定时器**: 优点是简单，缺点是阻塞主循环、违反性能要求

**Implementation Pattern**:
```python
# In bot.py __init__:
self.spread_recorder = SpreadRecorder(config, data_dir="data")

# In bot.py run():
tasks = [
    asyncio.create_task(self._strategy_loop()),
    asyncio.create_task(self._monitor_pairs()),
    asyncio.create_task(self.spread_recorder.record_loop(orderbook_getter)),
]
```

## Decision 3: CSV写入策略

**Selected**: 使用缓冲写入+定时刷新（每N条记录或N秒刷新一次）

**Rationale**:
- 减少磁盘IO次数，提高性能
- 即使程序崩溃，最多丢失N条记录（可接受的权衡）
- 避免频繁打开/关闭文件

**Alternatives Considered**:
- **每次写入立即flush**: 优点是数据最安全，缺点是IO频繁、性能差
- **内存缓冲+程序退出写入**: 优点是性能最好，缺点是程序崩溃丢失所有数据

**Implementation**:
```python
class SpreadRecorder:
    def __init__(self, buffer_size=100):
        self.buffer = []
        self.buffer_size = buffer_size
        self.last_flush = time.time()

    async def _write_record(self, record):
        self.buffer.append(record)
        if len(self.buffer) >= self.buffer_size:
            await self._flush_buffer()

    async def _flush_buffer(self):
        # 批量写入CSV
        # ...
```

## Decision 4: 无效数据处理

**Selected**: 记录为"INVALID"字符串，并在日志中输出WARNING

**Rationale**:
- 保持CSV结构完整（每行都有相同数量的列）
- 便于数据分析时过滤（`df[df.status != 'INVALID']`）
- 日志警告帮助识别问题

**Alternatives Considered**:
- **跳过无效记录**: 优点是CSV干净，缺点是丢失时间信息、难以诊断问题
- **使用NaN值**: 优点是pandas友好，缺点是CSV中显示为空、不够明确

**Invalid Conditions**:
- extended_bid <= 0 或 extended_ask <= 0
- lighter_bid <= 0 或 lighter_ask <= 0
- bid >= ask（订单簿异常）
- 网络超时获取数据

## Decision 5: 按日期分割文件

**Selected**: 每天UTC午夜创建新文件，文件名格式`spreads_YYYY_MM_DD.csv`

**Rationale**:
- 简单的归档策略
- 便于按日期查询和管理
- 文件大小可控（约2-3MB/天）

**Alternatives Considered**:
- **按小时分割**: 优点是文件更小，缺点是文件数量多、管理复杂
- **按大小分割**: 优点是文件大小均匀，缺点是不便于日期查询
- **单文件追加**: 优点是最简单，缺点是文件过大、难以归档

**File Rotation Logic**:
```python
def _get_csv_filename(self):
    date_str = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    return f"spreads_{date_str}.csv"

def _check_date_change(self):
    current_file = self._get_csv_filename()
    if current_file != self.current_csv_file:
        self._flush_buffer()  # 刷新旧文件
        self.current_csv_file = current_file
        self._write_csv_header()  # 写入新文件标题
```

## Decision 6: 配置管理

**Selected**: 将记录器配置添加到现有的`SpreadArbConfig`类，而不是创建单独的配置文件

**Rationale**:
- 保持配置集中管理
- 避免配置分散在多个文件
- 与现有的`from_env()`方法一致

**Configuration Fields**:
```python
@dataclass
class SpreadArbConfig:
    # ... existing fields ...

    # ==================== 价差记录器配置 ====================
    enable_spread_recorder: bool = True                 # 启用价差记录器
    spread_recorder_interval: int = 5                   # 采样间隔（秒）
    spread_recorder_output_dir: str = "data"            # CSV输出目录
    spread_recorder_buffer_size: int = 100              # 缓冲区大小
    spread_recorder_log_level: str = "INFO"             # 日志级别
```

## Decision 7: 日志输出格式

**Selected**: 使用简体中文，结构化输出计算公式

**Rationale**:
- 符合用户需求（"过程中的输出都使用简体中文"）
- 便于理解价差计算逻辑
- 与现有trade_logger.py的格式一致

**Log Format Example**:
```text
📊 [价差记录] 2026-01-10 12:34:56
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
订单簿价格:
  Extended: bid=$3087.50, ask=$3087.60
  Lighter:  bid=$3089.30, ask=$3089.42

做多价差计算:
  公式: 做多价差 = lighter_bid - extended_ask
  计算: 3089.30 - 3087.60 = $1.70
  价差率: 0.0550%
  点差成本: Extended 0.0032% + Lighter 0.0039% = 0.0071%

做空价差计算:
  公式: 做空价差 = extended_bid - lighter_ask
  计算: 3087.50 - 3089.42 = -$1.92
  价差率: -0.0622%

CSV记录: spreads_2026_01_10.csv (第1234条)
```

## Decision 8: 与RealSpreadCalculator集成

**Selected**: 复用现有的`RealSpreadCalculator`计算逻辑，而不是重新实现

**Rationale**:
- 避免代码重复
- 确保计算逻辑一致
- 利用现有的成本分解功能

**Integration**:
```python
from spread.real_spread_calculator import RealSpreadCalculator

class SpreadRecorder:
    def __init__(self, config):
        self.calculator = RealSpreadCalculator(config)

    async def _calculate_spread(self, extended_bid, extended_ask, lighter_bid, lighter_ask):
        long_result = self.calculator.calculate_long_spread(...)
        short_result = self.calculator.calculate_short_spread(...)
        return long_result, short_result
```

## Dependencies

### Python标准库
- `asyncio`: 异步任务管理
- `csv`: CSV文件写入
- `logging`: 日志输出
- `decimal.Decimal`: 金融数值计算
- `datetime`: 时间戳处理
- `pathlib`: 文件路径处理

### 项目内部依赖
- `spread.real_spread_calculator.RealSpreadCalculator`: 价差计算
- `spread.config.SpreadArbConfig`: 配置管理

### 无需新增外部依赖
- 所有功能使用Python标准库实现
- 与现有代码库技术栈一致

## Performance Considerations

### 预期负载
- **采样频率**: 每5秒一次
- **每日记录数**: 17,280条（24小时 × 720分钟 × 12次/小时）
- **文件大小**: 约2-3MB/天
- **内存占用**: < 10MB（缓冲区100条 × 每条约1KB）

### 性能优化
1. **缓冲写入**: 减少磁盘IO次数
2. **异步任务**: 不阻塞主交易循环
3. **延迟计算**: 只在需要时计算价差
4. **最小化日志**: 使用DEBUG级别减少详细输出

### 性能目标
- **记录操作耗时**: < 50毫秒/次
- **对交易性能影响**: < 1%
- **内存占用**: < 50MB

## Security Considerations

### 文件权限
- CSV文件创建使用默认权限（0644）
- 输出目录需要预先创建或自动创建（0755）

### 数据完整性
- 使用try-except捕获写入错误
- 写入失败不影响主交易循环
- 错误只记录日志，不抛出异常

## Monitoring & Observability

### 日志级别
- **INFO**: 记录价差数据（默认）
- **DEBUG**: 显示详细计算过程
- **WARNING**: 无效数据或写入失败
- **ERROR**: 严重错误（如磁盘满）

### 统计信息
- 总记录数
- 无效记录数
- 写入失败次数
- 当前CSV文件路径

## Testing Strategy

### 单元测试
- CSV写入正确性
- 日期切换逻辑
- 缓冲区刷新
- 无效数据处理

### 集成测试
- 与bot.py的异步任务集成
- 与RealSpreadCalculator的集成
- CSV文件格式验证

### 性能测试
- 记录操作耗时
- 内存占用
- 并发写入安全性

## Open Questions & Resolutions

### Q1: 缓冲区刷新频率如何选择？
**Resolution**: 默认100条记录或60秒， whichever comes first。可通过配置调整。

### Q2: CSV文件编码问题？
**Resolution**: 使用UTF-8 with BOM，确保Excel兼容。

### Q3: 如何处理程序重启时的文件追加？
**Resolution**: 检查文件是否存在，存在则追加（不写入header），不存在则创建新文件。

## Conclusion

所有技术决策已完成，设计清晰、简单、符合现有架构。Phase 0研究完成，可以进入Phase 1设计阶段。
