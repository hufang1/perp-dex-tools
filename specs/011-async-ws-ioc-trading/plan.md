# 实施计划：高频价差套利系统异步重构

**分支**: `011-async-ws-ioc-trading` | **日期**: 2026-01-11 | **规格**: [spec.md](./spec.md)
**输入**: 来自 `/specs/011-async-ws-ioc-trading/spec.md` 的功能规格

## 摘要

将现有价差套利系统从"同步轮询"架构升级为"异步事件驱动"架构，解决12秒延迟和数据过期问题。

**核心需求**:
- WebSocket实时行情接入（替代HTTP轮询）
- 双腿并发交易执行（Extended + Lighter同时下单）
- IOC限价单机制（Immediate or Cancel）
- 数据时效性与滑点风控
- 增强日志与可观测性

**技术方法**:
- 使用Python asyncio实现异步架构
- WebSocket订阅BookTicker/Depth频道
- 并发下单（asyncio.gather）确保时间差 < 5ms
- 结构化调试输出用于后续调优

## 技术上下文

**语言/版本**: Python 3.11+
**主要依赖**: asyncio, websockets, decimal.Decimal, logging, pytest, dataclasses, csv
**存储**: 内存状态存储 + 文件日志（logs/）+ CSV导出（data/）
**测试**: pytest（单元测试 + 集成测试）
**目标平台**: Linux/macOS服务器
**项目类型**: 单一Python项目
**性能目标**:
- 行情处理延迟 < 10ms
- 并发发送间隔 < 5ms
- 执行延迟 < 300ms
- 数据新鲜度 < 100ms

**约束**:
- 时间戳精确到毫秒级
- 所有数值使用Decimal避免浮点误差
- 简体中文输出
- 35U小资金环境

**规模/范围**:
- 现有约20个Python模块
- 主要修改spread/目录（bot.py, config.py等）
- 新增调试输出模块

## Constitution Check

*门控：Phase 0研究前必须通过。Phase 1设计后重新检查。*

### I. 简单优先
- ✅ 使用现有项目结构（单一Python项目）
- ✅ 复用现有模块（calculator.py, trade_logger.py等）
- ⚠️ 异步架构复杂度：需研究asyncio最佳实践

### II. 测试优先
- ✅ 每个新模块必须有单元测试
- ✅ 集成测试验证端到端流程
- ⚠️ 需研究asyncio测试模式

### III. 可观测性
- ✅ 详细的调试输出需求已明确
- ✅ CSV导出用于后续分析
- ✅ 性能监控统计

### IV. 配置化
- ✅ 所有数值参数可配置
- ✅ 环境变量支持

## 项目结构

### 文档（本功能）

```text
specs/011-async-ws-ioc-trading/
├── plan.md              # 本文件（/speckit.plan命令输出）
├── research.md          # Phase 0输出（/speckit.plan命令）
├── data-model.md        # Phase 1输出（/speckit.plan命令）
├── quickstart.md        # Phase 1输出（/speckit.plan命令）
├── contracts/           # Phase 1输出（/speckit.plan命令）
│   └── performance_monitor_api.md
└── tasks.md             # Phase 2输出（/speckit.tasks命令 - 非本命令创建）
```

### 源代码（仓库根）

```text
hufangperp/
├── spread/                    # 核心套利逻辑模块
│   ├── bot.py                 # [修改] 添加异步支持、性能监控集成
│   ├── config.py              # [修改] 添加011配置参数
│   ├── performance_monitor.py # [新增] 性能监控模块
│   ├── websocket_manager.py   # [新增] WebSocket连接管理
│   ├── concurrent_executor.py # [新增] 并发执行器
│   ├── ioc_order_manager.py   # [新增] IOC订单管理
│   ├── risk_validator.py      # [新增] 风控验证器
│   ├── calculator.py          # [保留] 现有计算器
│   ├── real_spread_calculator.py  # [保留] 真实价差计算
│   ├── trade_logger.py        # [扩展] 添加时间戳字段
│   ├── models.py              # [扩展] 添加调试数据模型
│   └── ...
├── exchanges/                 # 交易所客户端
│   ├── extended.py            # [修改] 添加WebSocket支持
│   ├── lighter.py             # [修改] 添加WebSocket支持
│   └── ...
├── tests/                     # 测试
│   ├── test_performance_monitor.py    # [新增] 性能监控测试
│   ├── test_websocket_manager.py     # [新增] WebSocket测试
│   ├── test_concurrent_executor.py    # [新增] 并发执行测试
│   ├── test_ioc_order_manager.py      # [新增] IOC订单测试
│   ├── test_risk_validator.py         # [新增] 风控测试
│   └── integration/
│       └── test_async_trading_flow.py # [新增] 异步交易流程测试
├── logs/                      # 日志输出
│   ├── trade.log              # 交易日志
│   └── performance.log        # [新增] 性能监控日志
└── data/                      # 数据导出
    ├── operations_YYYY_MM_DD.csv     # [新增] 操作记录
    └── performance_YYYY_MM_DD.csv    # [新增] 性能数据
```

**结构决策**: 单一Python项目，在现有spread/目录基础上扩展。新增模块专注于异步重构和性能监控。

## Complexity Tracking

> 仅当Constitution检查有必须证明的违规时填写

| 违规 | 为什么需要 | 拒绝更简单替代方案的原因 |
|------|------------|------------------------|
| 异步架构复杂度 | 需要并发下单实现<5ms间隔 | 同步方案无法满足性能目标 |
| 多模块新增 | 分离关注点便于测试和调试 | 单一模块会过于复杂难以维护 |

## Phase 0: 研究与探索

### 需要澄清的技术问题

#### T001: Python asyncio最佳实践
**问题**: 在高频交易场景中，如何正确使用asyncio实现并发下单？
**研究任务**:
- asyncio.gather并发模式
- 任务超时和取消处理
- 异步上下文管理器模式
- 与现有同步代码的集成方式

#### T002: WebSocket连接管理
**问题**: 如何实现稳定的WebSocket连接，处理断线重连和数据同步？
**研究任务**:
- websockets库的最佳实践
- 心跳保活机制
- 断线检测和自动重连
- 订单簿数据同步策略

#### T003: IOC订单实现
**问题**: Extended和Lighter交易所如何支持IOC订单类型？
**研究任务**:
- 交易所API文档中IOC订单参数
- 部分成交处理逻辑
- 订单状态回调处理

#### T004: 精确时间戳记录
**问题**: 如何确保毫秒级时间戳记录不影响性能？
**研究任务**:
- time.time() vs time.perf_counter()
- 时间戳记录开销测量
- 异步环境下的时间戳准确性

#### T005: 测试策略
**问题**: 如何测试异步交易流程？
**研究任务**:
- pytest-asyncio使用模式
- Mock WebSocket和交易所API
- 并发执行测试方法

### 研究输出

研究结果将整理到 `research.md`，包含：
- 每个问题的决策和理由
- 替代方案评估
- 代码示例和模式

## Phase 1: 设计与合约

### 前提条件: `research.md` 完成

### 数据模型 (data-model.md)

从功能规格提取的实体：

**OrderBookSnapshot**
```python
@dataclass
class OrderBookSnapshot:
    """订单簿快照"""
    exchange: str                    # 'extended' or 'lighter'
    timestamp_ms: float              # 数据生成时间戳（毫秒）
    bid_price: Decimal
    ask_price: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    is_stale: bool = False           # 数据过期标记
```

**TimingRecord**
```python
@dataclass
class TimingRecord:
    """时间戳记录"""
    name: str                        # 记录名称
    timestamp_ms: float              # 时间戳（毫秒）
    metadata: Dict[str, Any]         # 附加元数据
```

**DataFreshnessResult**
```python
@dataclass
class DataFreshnessResult:
    """数据新鲜度检查结果"""
    is_fresh: bool
    data_age_ms: float
    threshold_ms: float
    exchange: str
```

**SlippageCheckResult**
```python
@dataclass
class SlippageCheckResult:
    """滑点检查结果"""
    is_acceptable: bool
    expected_price: Decimal
    current_price: Decimal
    slippage_rate: Decimal
    threshold_rate: Decimal
    side: str
```

**ProfitabilityCheckResult**
```python
@dataclass
class ProfitabilityCheckResult:
    """利润率检查结果"""
    is_profitable: bool
    spread_rate: Decimal
    total_fees: Decimal
    expected_slippage: Decimal
    min_net_profit: Decimal
    net_profit_rate: Decimal
    decision: str
```

**TradeOperationRecord**
```python
@dataclass
class TradeOperationRecord:
    """交易操作记录"""
    timestamp: float
    operation_type: str              # 'OPEN', 'CLOSE'
    signal_ts: float                 # 信号触发时间
    data_ts_A: float                 # Extended数据时间
    data_ts_B: float                 # Lighter数据时间
    send_A_ts: float                 # Extended发送时间
    send_B_ts: float                 # Lighter发送时间
    ack_A_ts: float                  # Extended ACK时间
    ack_B_ts: float                  # Lighter ACK时间
    spread_rate: Decimal
    slippage_rate: Decimal
    profit_rate: Decimal
    decision: str
    status: str                      # 'SUCCESS', 'FAILED'
```

### API合约 (contracts/)

#### PerformanceMonitor API

```python
class PerformanceMonitor:
    """性能监控器接口"""

    # 时间戳记录
    def record_timestamp(name: str, metadata: Dict[str, Any]) -> None
    def get_latency(start_name: str, end_name: str) -> Optional[float]

    # 延迟监控
    def record_tick_to_trade_latency(signal_ts: float, send_ts: float) -> None
    def record_execution_latency(send_ts: float, ack_ts: float) -> None
    def record_concurrent_send_gap(first_ts: float, second_ts: float) -> None

    # 数据新鲜度检查
    def check_data_freshness(exchange: str, data_ts: float,
                           current_time: Optional[float] = None) -> DataFreshnessResult
    def check_both_data_freshness(extended_ts: float, lighter_ts: float,
                                current_time: Optional[float] = None) -> tuple[bool, List[DataFreshnessResult]]

    # 滑点检查
    def check_slippage(expected_price: Decimal, current_price: Decimal,
                      side: str, threshold: Optional[Decimal] = None) -> SlippageCheckResult

    # 利润率检查
    def check_profitability(spread_rate: Decimal,
                          extended_fee: Optional[Decimal] = None,
                          lighter_fee: Optional[Decimal] = None,
                          expected_slippage: Optional[Decimal] = None) -> ProfitabilityCheckResult

    # 决策记录
    def log_opening_decision(opportunity: Dict[str, Any],
                           data_freshness: List[DataFreshnessResult],
                           slippage_check: Optional[SlippageCheckResult] = None,
                           profitability_check: Optional[ProfitabilityCheckResult] = None,
                           final_decision: str = "PENDING") -> None

    # 统计导出
    def get_stats_summary() -> Dict[str, Any]
    def log_stats_summary() -> None
```

#### WebSocketManager API

```python
class WebSocketManager:
    """WebSocket连接管理器接口"""

    # 连接管理
    async def connect_extended() -> None
    async def connect_lighter() -> None
    async def disconnect_all() -> None
    def is_connected(exchange: str) -> bool

    # 订阅管理
    async def subscribe_orderbook(exchange: str, symbol: str) -> None
    def unsubscribe_all() -> None

    # 数据获取
    def get_orderbook(exchange: str) -> Dict[str, Dict[Decimal, Decimal]]
    def get_orderbook_timestamp(exchange: str) -> Optional[float]

    # 回调设置
    def set_orderbook_callback(callback: Callable[[str, Dict], None]) -> None

    # 连接状态
    def get_connection_stats() -> Dict[str, Any]
```

#### ConcurrentExecutor API

```python
class ConcurrentExecutor:
    """并发执行器接口"""

    # 并发下单
    async def execute_concurrent_orders(
        extended_order: Dict[str, Any],
        lighter_order: Dict[str, Any],
        timeout_ms: int = 500
    ) -> tuple[Dict, Dict, float]:  # (extended_result, lighter_result, send_gap_ms)

    # 并发平仓
    async def execute_concurrent_close(
        extended_order: Dict[str, Any],
        lighter_order: Dict[str, Any],
        timeout_ms: int = 500
    ) -> tuple[Dict, Dict, float]

    # 紧急平仓（单腿）
    async def emergency_close_position(
        exchange: str,
        side: str,
        quantity: Decimal,
        timeout_ms: int = 1000
    ) -> Dict
```

#### IocOrderManager API

```python
class IocOrderManager:
    """IOC订单管理器接口"""

    # 创建IOC订单
    def create_ioc_order(
        exchange: str,
        side: str,              # 'buy' or 'sell'
        price: Decimal,
        quantity: Decimal,
        slippage_tolerance: Decimal
    ) -> Dict[str, Any]

    # 计算IOC订单价格
    def calculate_ioc_price(
        base_price: Decimal,    # bid or ask
        side: str,
        slippage_tolerance: Decimal
    ) -> Decimal

    # 处理部分成交
    def handle_partial_fill(
        order_result: Dict,
        expected_quantity: Decimal
    ) -> Dict[str, Any]
```

#### RiskValidator API

```python
class RiskValidator:
    """风控验证器接口"""

    # 开仓前验证
    def validate_opening(
        opportunity: Dict[str, Any],
        extended_ts: float,
        lighter_ts: float
    ) -> tuple[bool, str]:  # (is_valid, reason)

    # 数据新鲜度验证
    def validate_data_freshness(
        extended_ts: float,
        lighter_ts: float
    ) -> tuple[bool, List[DataFreshnessResult]]

    # 滑点验证
    def validate_slippage(
        expected_price: Decimal,
        current_price: Decimal,
        side: str
    ) -> SlippageCheckResult

    # 利润率验证
    def validate_profitability(
        spread_rate: Decimal
    ) -> ProfitabilityCheckResult

    # 单腿持仓检测
    def check_leg_risk(
        extended_filled: bool,
        lighter_filled: bool
    ) -> tuple[bool, str]  # (has_risk, action)
```

### 快速开始 (quickstart.md)

```markdown
# 快速开始：异步重构调试输出

## 1. 配置参数

在 `spread/config.py` 中已添加新的配置参数：

```python
# 性能相关
max_tick_to_trade_latency_ms = 10.0
max_execution_latency_ms = 300.0
max_data_age_ms = 500.0
concurrent_order_send_threshold_ms = 5.0

# 订单相关
use_ioc_orders = True
ioc_slippage_tolerance_rate = Decimal('0.0005')

# 日志相关
enable_enhanced_logging = True
log_all_timestamps = True
```

## 2. 查看调试输出

### 控制台输出
```
⏱️ [行情→交易延迟] 8.45ms | 信号: 1704960123456.78ms | 发送: 1704960123465.23ms
📡 [数据新鲜度] ✅ 新鲜 | extended | 数据年龄: 45.2ms | 阈值: 500ms
📊 [滑点检查] ✅ 可接受 | buy | 预期价: $3000.00 | 当前价: $3001.50
💰 [利润检查] ✅ 可交易 | 价差率: 0.10% | 净利: 0.05%
```

### CSV导出
```bash
# 操作记录
cat data/operations_2026_01_11.csv

# 性能数据
cat data/performance_2026_01_11.csv
```

## 3. 测试

```bash
# 运行单元测试
pytest tests/test_performance_monitor.py -v
pytest tests/test_risk_validator.py -v

# 运行集成测试
pytest tests/integration/test_async_trading_flow.py -v
```

## 4. 性能调优

将调试输出（CSV或日志）提供给AI，分析：
- 延迟分布
- 滑点分析
- 利润率分析
- 拒绝原因统计
```

## 实施阶段

### Phase 0: 研究（本文档）
- ✅ 创建research.md

### Phase 1: 设计（本节）
- ✅ 创建data-model.md
- ✅ 创建contracts/performance_monitor_api.md
- ✅ 创建quickstart.md

### Phase 2: 任务分解（下一步）
- ⏭️ 执行 `/speckit.tasks` 生成tasks.md

## 下一步

1. 完成研究并生成 `research.md`
2. 运行 `.specify/scripts/bash/update-agent-context.sh claude`
3. 执行 `/speckit.tasks` 生成任务清单
