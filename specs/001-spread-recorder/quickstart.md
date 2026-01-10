# Quickstart Guide: 价差实时记录器

**Feature**: 价差实时记录器 (001-spread-recorder)
**Date**: 2026-01-10

## Overview

本指南帮助你快速开始使用价差实时记录器功能。

## Prerequisites

- Python 3.11+
- 已有价差套利机器人运行环境
- 已安装项目依赖（无新增依赖）

## Installation

价差记录器是价差套利机器人的内置功能，无需额外安装。

### 1. 更新代码

```bash
# 切换到功能分支
git checkout 001-spread-recorder

# 拉取最新代码
git pull origin 001-spread-recorder
```

### 2. 配置

编辑配置文件 `.env` 或代码中的 `SpreadArbConfig`:

```python
# 在 spread/config.py 中或通过环境变量
enable_spread_recorder = True              # 启用记录器
spread_recorder_interval = 5               # 每5秒记录一次
spread_recorder_output_dir = "data"        # CSV输出目录
spread_recorder_buffer_size = 100          # 缓冲100条后写入
spread_recorder_log_level = "INFO"         # 日志级别
```

## Usage

### 启动机器人（带记录器）

```bash
# 使用现有命令启动
python spread/bot.py --ticker ETH --size 35 --max-pairs 3

# 记录器会自动启动（如果 enable_spread_recorder=True）
```

### 输出示例

#### 终端日志输出

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

#### CSV文件内容

```csv
timestamp,extended_bid,extended_ask,lighter_bid,lighter_ask,long_spread,long_spread_rate,short_spread,short_spread_rate,extended_spread_cost,lighter_spread_cost,total_cost_rate,status
2026-01-10 12:34:56.789,3087.50,3087.60,3089.30,3089.42,-1.70,-0.000550,-1.92,-0.000622,0.000032,0.000039,0.000071,VALID
2026-01-10 12:35:01.234,3087.55,3087.65,3089.35,3089.45,-1.70,-0.000550,-1.90,-0.000616,0.000032,0.000039,0.000071,VALID
```

## Data Analysis

### 使用pandas分析

```python
import pandas as pd
import matplotlib.pyplot as plt

# 读取CSV
df = pd.read_csv('data/spreads_2026_01_10.csv')

# 基本统计
print("价差统计:")
print(df['long_spread_rate'].describe())

# 价差超过0.1%的次数
count = len(df[df['long_spread_rate'] > 0.001])
print(f"价差超过0.1%的次数: {count}")

# 绘制价差分布图
plt.figure(figsize=(12, 6))
plt.hist(df['long_spread_rate'] * 100, bins=50, edgecolor='black')
plt.xlabel('价差率 (%)')
plt.ylabel('频数')
plt.title('价差分布 (2026-01-10)')
plt.grid(True)
plt.show()
```

### 使用Excel分析

1. 打开CSV文件（UTF-8编码）
2. 使用数据透视表分析价差分布
3. 创建图表可视化

## File Management

### 文件位置

默认输出目录: `data/spreads_YYYY_MM_DD.csv`

### 文件轮换

- 每天00:00 UTC自动创建新文件
- 旧文件自动保留
- 不会自动删除（需手动管理）

### 查看文件列表

```bash
# 列出所有价差记录CSV文件
ls -lh data/spreads_*.csv

# 查看文件大小
du -sh data/spreads_*.csv
```

## Configuration Options

### 采样间隔 (spread_recorder_interval)

**默认**: `5` 秒

**调整**:
- 更小值（如1秒）: 更详细数据，但文件更大
- 更大值（如10秒）: 文件更小，但数据粒度更粗

**建议**: 根据分析需求调整，5秒是较好的平衡点。

### 缓冲区大小 (spread_recorder_buffer_size)

**默认**: `100` 条

**调整**:
- 更大值（如500）: 减少IO次数，但程序崩溃可能丢失更多数据
- 更小值（如50）: 数据更安全，但IO更频繁

**建议**: 保持默认值100，平衡性能和数据安全。

### 输出目录 (spread_recorder_output_dir)

**默认**: `"data"`

**调整**:
```python
spread_recorder_output_dir = "/path/to/spread/data"
```

**注意**: 确保目录存在或程序有权限创建。

### 日志级别 (spread_recorder_log_level)

**默认**: `"INFO"`

**选项**:
- `DEBUG`: 显示详细计算过程（调试用）
- `INFO`: 显示价差记录摘要（推荐）
- `WARNING`: 仅显示警告和错误
- `ERROR`: 仅显示错误

## Troubleshooting

### CSV文件未创建

**检查**:
1. 配置是否启用: `enable_spread_recorder = True`
2. 输出目录是否存在且有写权限
3. 查看日志是否有错误信息

### 记录中有大量INVALID

**原因**: 订单簿数据异常

**检查**:
1. 交易所连接是否正常
2. WebSocket是否断开
3. 查看日志中的具体错误

### 文件过大

**解决方案**:
1. 增加采样间隔: `spread_recorder_interval = 10`
2. 实施文件清理策略（手动或脚本）

```bash
# 删除30天前的文件
find data/ -name "spreads_*.csv" -mtime +30 -delete
```

### 程序崩溃后数据丢失

**原因**: 数据仍在缓冲区，未写入文件

**解决方案**:
1. 减小缓冲区: `spread_recorder_buffer_size = 50`
2. 减小刷新间隔: `spread_recorder_flush_interval = 30`

## Advanced Usage

### 禁用记录器

```python
# 在配置中设置
enable_spread_recorder = False
```

### 自定义日志格式

修改 `spread/spread_recorder.py` 中的 `_format_log_message` 方法。

### 仅记录有效数据

修改 `spread/spread_recorder.py` 中的 `record_loop` 方法，跳过INVALID记录。

### 数据导出到其他格式

```python
import pandas as pd

# CSV转Parquet（更紧凑）
df = pd.read_csv('data/spreads_2026_01_10.csv')
df.to_parquet('data/spreads_2026_01_10.parquet')

# CSV转Excel（带格式）
df = pd.read_csv('data/spreads_2026_01_10.csv')
df.to_excel('data/spreads_2026_01_10.xlsx', index=False)
```

## Testing

### 单元测试

```bash
# 运行记录器单元测试
pytest tests/test_spread_recorder.py -v
```

### 手动测试

```python
# 测试记录器独立运行
from spread.spread_recorder import SpreadRecorder
from spread.config import SpreadArbConfig

config = SpreadArbConfig()
recorder = SpreadRecorder(config)

# 模拟记录
await recorder.record_loop()
```

## Performance Tips

1. **使用SSD**: CSV写入性能显著提升
2. **分离磁盘**: 将CSV文件放在单独的磁盘上
3. **调整缓冲区**: 根据内存大小调整
4. **定期清理**: 避免磁盘空间不足

## Next Steps

- 查看 [data-model.md](./data-model.md) 了解数据结构
- 查看 [research.md](./research.md) 了解设计决策
- 运行测试验证功能: `pytest tests/test_spread_recorder.py`

## Support

如有问题，请检查：
1. 日志文件 (`logs/trade.log`)
2. 终端输出
3. 配置文件 (`spread/config.py`)
