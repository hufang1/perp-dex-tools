# Feature Specification: 价差实时记录器

**Feature Branch**: `001-spread-recorder`
**Created**: 2026-01-10
**Status**: Draft
**Input**: User description: "我想在加一个功能点 现在不是有一个开仓价差嘛（现在是0.1%），我想加一个功能模块，记录下程序运行时实时的价差数据，以及对应的计算公式，不用每一次都记录，每几s记录一下。可以存放在csv中后续可以获取到每日价差分布的数据，也可以打印到终端的log中

过程中的输出都使用简体中文"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 实时价差数据采集和记录 (Priority: P1)

作为交易员，我需要系统自动定期记录价差数据到CSV文件和终端日志，以便分析价差的历史分布和波动规律。

**Why this priority**: 这是核心功能，提供价差数据的持久化存储，是后续数据分析的基础。没有这个功能，无法进行任何价差分布分析。

**Independent Test**: 可以独立测试价差记录功能 - 运行程序一段时间后，检查CSV文件是否正确创建，数据是否完整，终端日志是否正确输出。

**Acceptance Scenarios**:

1. **Given** 程序启动并连接到两个交易所，**When** 每隔N秒（可配置），**Then** 系统记录当前价差数据到CSV文件和终端日志
2. **Given** CSV文件已存在，**When** 程序运行一天后，**Then** 可以通过CSV文件分析当天的价差分布（最小值、最大值、平均值、中位数）
3. **Given** 程序正在运行，**When** 查看终端日志，**Then** 可以看到定期输出的价差数据和计算公式

---

### User Story 2 - 计算公式透明化展示 (Priority: P2)

作为交易员，我需要每次记录时显示详细的价差计算公式和中间值，以便理解价差是如何计算的，以及验证计算逻辑的正确性。

**Why this priority**: 这个功能增强了系统的透明度和可调试性，帮助用户理解系统的工作原理。虽然不影响核心交易功能，但对于调试和验证非常重要。

**Independent Test**: 可以独立测试公式展示 - 在终端日志中检查是否显示完整的计算公式、输入参数、中间计算步骤和最终结果。

**Acceptance Scenarios**:

1. **Given** 系统记录价差数据，**When** 输出到终端日志，**Then** 显示完整的价差计算公式（包括买入价、卖出价、价差值、价差率）
2. **Given** 计算做多价差，**When** 输出日志，**Then** 显示公式：`做多价差 = lighter_bid - extended_ask` 和具体数值
3. **Given** 计算做空价差，**When** 输出日志，**Then** 显示公式：`做空价差 = extended_bid - lighter_ask` 和具体数值

---

### User Story 3 - 数据文件管理和归档 (Priority: P3)

作为交易员，我需要系统自动按日期创建CSV文件，并支持数据归档，以便管理历史数据并进行跨日期分析。

**Why this priority**: 这个功能改善了数据管理的便利性，但不是核心功能。即使每天只生成一个文件，也能满足基本需求。

**Independent Test**: 可以独立测试文件管理 - 运行程序跨越午夜时，检查是否创建新日期的文件，旧文件是否正确保留。

**Acceptance Scenarios**:

1. **Given** 程序在2026-01-10运行，**When** 2026-01-11 00:00:00到达，**Then** 系统创建新的CSV文件 `spreads_2026_01_11.csv`
2. **Given** 程序运行7天，**When** 检查数据目录，**Then** 存在7个CSV文件，每天一个文件
3. **Given** CSV文件已存在，**When** 程序重启，**Then** 新数据追加到现有文件而不是覆盖

---

### Edge Cases

- 当订单簿数据无效（价格为0或负数）时，系统应该如何处理记录？
- 当网络中断导致无法获取某个交易所的价格时，应该如何记录？
- 当CSV文件写入失败（磁盘满、权限问题）时，系统应该如何处理？
- 当配置的采样间隔过小（如0.1秒）导致性能问题时，系统应该如何处理？

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须每隔可配置的时间间隔（默认5秒）记录一次价差数据
- **FR-002**: 系统必须将价差数据同时输出到CSV文件和终端日志
- **FR-003**: 系统必须记录每次采样的时间戳（精确到毫秒）
- **FR-004**: 系统必须记录完整的订单簿价格数据（extended_bid, extended_ask, lighter_bid, lighter_ask）
- **FR-005**: 系统必须记录做多价差和做空价差的计算结果（包括价差值和价差率）
- **FR-006**: 系统必须在终端日志中显示价差计算公式和具体的计算步骤
- **FR-007**: 系统必须按日期自动创建CSV文件，文件名格式为 `spreads_YYYY_MM_DD.csv`
- **FR-008**: 系统必须在程序重启后追加数据到现有CSV文件，而不是覆盖
- **FR-009**: 系统必须在CSV文件中包含列标题，以便数据分析工具（如Excel、pandas）正确读取
- **FR-010**: 系统必须处理无效数据（价格为0或负数），在CSV中标记为"INVALID"并在日志中输出警告
- **FR-011**: 系统必须使用简体中文输出所有日志信息
- **FR-012**: 系统必须记录点差成本（extended_spread, lighter_spread）和总成本率

### Key Entities

- **价差记录（SpreadRecord）**: 表示单次价差采样的完整数据
  - 时间戳（timestamp）: 采样时间，精确到毫秒
  - Extended订单簿价格（extended_bid, extended_ask）: Extended交易所的买一价和卖一价
  - Lighter订单簿价格（lighter_bid, lighter_ask）: Lighter交易所的买一价和卖一价
  - 做多价差（long_spread, long_spread_rate）: 做多方向的价差值和价差率
  - 做空价差（short_spread, short_spread_rate）: 做空方向的价差值和价差率
  - 点差成本（spread_costs）: 点差成本分解（extended_cost, lighter_cost, total_cost_rate）

- **配置参数（SpreadRecorderConfig）**: 控制价差记录行为的配置
  - 采样间隔（sample_interval_seconds）: 两次记录之间的时间间隔（秒）
  - CSV存储目录（csv_output_dir）: CSV文件存储的目录路径
  - 日志级别（log_level）: 终端日志的详细程度

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 交易员可以通过CSV文件使用pandas/Excel分析任意一天的价差分布数据
- **SC-002**: 终端日志中每次记录都显示清晰的计算公式，新用户能理解价差计算逻辑
- **SC-003**: 系统运行24小时后，CSV文件包含约17,280条记录（24小时 × 60分钟 × 60秒 / 5秒间隔）
- **SC-004**: 记录功能对交易性能的影响小于1%（记录操作耗时 < 50毫秒/次）
- **SC-005**: 当网络中断或数据无效时，系统继续运行并在日志中明确标记问题数据
- **SC-006**: 交易员可以通过查看CSV文件快速回答"今天价差超过0.1%的次数是多少？"
- **SC-007**: CSV文件格式与数据分析工具兼容，可以直接使用pandas.read_csv()读取

## Assumptions

1. 系统已经有获取两个交易所订单簿价格的功能（从 `real_spread_calculator.py` 复用）
2. CSV文件存储在本地文件系统，不需要云存储或远程数据库
3. 采样间隔默认为5秒，用户可以通过配置调整
4. 系统使用简体中文输出所有日志，符合用户要求
5. CSV文件不需要加密或特殊权限控制
6. 价差计算使用现有的 `RealSpreadCalculator` 逻辑（对手价计算）
7. 记录功能不应该阻塞主交易循环
8. 单个CSV文件的大小不会超过可用磁盘空间（假设每天约几MB）
