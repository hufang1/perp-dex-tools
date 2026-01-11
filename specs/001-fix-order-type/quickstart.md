# Quickstart Guide: 修复订单类型问题并增加交易成功率统计

**Feature**: 001-fix-order-type
**Date**: 2026-01-11

## Overview

本指南提供了实现"修复订单类型问题并增加交易成功率统计"功能的快速上手说明。

## Prerequisites

- Python 3.11+
- pytest (用于测试)
- 现有价差套利系统代码库

## Implementation Steps

### Step 1: 创建SuccessTracker模块

**文件**: `spread/success_tracker.py`

创建新模块，实现成功率追踪功能：

```python
"""
成功率追踪器 - 记录和统计开仓/平仓成功率
"""

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional

class OperationType(Enum):
    """操作类型"""
    OPEN_ATTEMPT = "open_attempt"
    OPEN_SUCCESS = "open_success"
    OPEN_FAILED = "open_failed"
    CLOSE_ATTEMPT = "close_attempt"
    CLOSE_SUCCESS = "close_success"
    CLOSE_FAILED = "close_failed"

class OperationStatus(Enum):
    """操作状态"""
    SUCCESS = "success"
    FAILED = "failed"
    POSITION_LIMIT = "position_limit"
    PENDING = "pending"

class ExchangeType(Enum):
    """交易所类型"""
    EXTENDED = "extended"
    LIGHTER = "lighter"
    BOTH = "both"

class FailureReason(Enum):
    """失败原因"""
    INSUFFICIENT_BALANCE = "insufficient_balance"
    ORDER_REJECTED = "order_rejected"
    NETWORK_TIMEOUT = "network_timeout"
    PRICE_SLIPPAGE = "price_slippage"
    PARTIAL_FILL = "partial_fill"
    POSITION_IMBALANCE = "position_imbalance"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class SpreadOperationResult:
    """操作结果记录"""
    timestamp: float
    operation_type: OperationType
    status: OperationStatus
    exchange: ExchangeType
    order_id: Optional[str] = None
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    failure_reason: Optional[FailureReason] = None
    error_message: Optional[str] = None
    pair_id: Optional[int] = None

    def to_csv_row(self) -> Dict[str, str]:
        """转换为CSV行（双语列名）"""
        return {
            'timestamp | 时间戳': datetime.fromtimestamp(self.timestamp).isoformat(),
            'operation_type | 操作类型': self.operation_type.value,
            'status | 状态': self.status.value,
            'exchange | 交易所': self.exchange.value,
            'order_id | 订单ID': self.order_id or '',
            'failure_reason | 失败原因': self.failure_reason.value if self.failure_reason else '',
        }

class SuccessTracker:
    """成功率追踪器"""

    def __init__(self, output_dir: str = "data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self._operations: List[SpreadOperationResult] = []
        self._stats: Dict[str, int] = defaultdict(int)
        self._failure_reasons: Dict[FailureReason, int] = defaultdict(int)
        self.logger = logging.getLogger("SuccessTracker")

    def record_operation(self, result: SpreadOperationResult) -> None:
        """记录操作结果"""
        self._operations.append(result)
        self._stats[result.operation_type.value] += 1
        if result.status == OperationStatus.SUCCESS:
            self._stats[f"{result.operation_type.value}_success"] += 1
        elif result.status == OperationStatus.FAILED and result.failure_reason:
            self._failure_reasons[result.failure_reason] += 1

    def get_success_rate(self, operation_type: OperationType) -> float:
        """获取成功率"""
        total = self._stats.get(operation_type.value, 0)
        success = self._stats.get(f"{operation_type.value}_success", 0)
        return success / total if total > 0 else 0.0

    def export_operations_csv(self) -> str:
        """导出操作记录到CSV"""
        if not self._operations:
            return ""

        date_str = datetime.now().strftime("%Y_%m_%d")
        filename = self.output_dir / f"operations_{date_str}.csv"

        fieldnames = [
            'timestamp | 时间戳',
            'operation_type | 操作类型',
            'status | 状态',
            'exchange | 交易所',
            'order_id | 订单ID',
            'failure_reason | 失败原因',
        ]

        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for op in self._operations:
                writer.writerow(op.to_csv_row())

        self.logger.info(f"导出操作记录: {filename}")
        return str(filename)
```

### Step 2: 修改bot.py强制使用Taker订单

**文件**: `spread/bot.py`

**位置**: `_open_new_pair()` 方法，约第877-912行

**修改前**:
```python
# T041: 决定是否使用maker订单
use_maker = self.calculator.should_use_maker(
    spread_rate=opportunity.get('spread_rate', Decimal('0')),
    expected_profit_rate=opportunity.get('expected_profit_rate', Decimal('0'))
)

# T103: 如果使用maker，验证taker利润是否足够
if use_maker:
    taker_profit_ok = self._should_open_with_taker(...)
    if not taker_profit_ok:
        self.logger.warning("Maker转taker后利润不足，跳过此机会")
        return False

# T042: 计算maker订单价格（如果使用maker）
if use_maker:
    extended_price = self.calculator.calculate_maker_price(...)
else:
    extended_price = opportunity['extended_price']

# 1. Extended 下单
order = await self.order_manager.place_spread_maker_order(
    side=opportunity['side'],
    price=extended_price,
    quantity=opportunity['quantity'],
    post_only=use_maker  # True=maker, False=taker
)
```

**修改后**:
```python
# 001-fix-order-type: 强制使用taker订单，禁用maker逻辑
use_maker = False  # 强制使用taker

# 使用对手价作为taker订单价格
if opportunity['side'] == 'buy':
    extended_price = extended_ask  # 买单使用ask价格
else:
    extended_price = extended_bid  # 卖单使用bid价格

# 记录开仓尝试
self.success_tracker.record_operation(SpreadOperationResult(
    timestamp=datetime.now().timestamp(),
    operation_type=OperationType.OPEN_ATTEMPT,
    status=OperationStatus.PENDING,
    exchange=ExchangeType.EXTENDED,
    quantity=opportunity['quantity'],
    price=extended_price,
))

# 1. Extended 下单（强制taker）
order = await self.order_manager.place_spread_maker_order(
    side=opportunity['side'],
    price=extended_price,
    quantity=opportunity['quantity'],
    post_only=False  # 强制taker订单
)
```

### Step 3: 添加仓位一致性验证

**文件**: `spread/bot.py`

**位置**: `_open_new_pair()` 方法，Lighter对冲成功后

**添加代码**:
```python
# 验证仓位一致性
from spread.position_aggregator import PositionAggregator

position_balance = self.position_aggregator.get_position_balance()
if position_balance.imbalance_rate > 0.1:  # 差异率超过10%
    self.logger.warning(
        f"仓位不一致警告: Extended={position_balance.extended_total_qty}, "
        f"Lighter={position_balance.lighter_total_qty}, "
        f"差异率={position_balance.imbalance_rate:.2%}"
    )
    # 记录失败
    self.success_tracker.record_operation(SpreadOperationResult(
        timestamp=datetime.now().timestamp(),
        operation_type=OperationType.OPEN_FAILED,
        status=OperationStatus.FAILED,
        exchange=ExchangeType.BOTH,
        failure_reason=FailureReason.POSITION_IMBALANCE,
        error_message=f"仓位差异率{position_balance.imbalance_rate:.2%}",
    ))
```

### Step 4: 修改CSV导出添加成功率字段

**文件**: `spread/data_collector.py`

**修改**: `export_trades_csv()` 方法的fieldnames

```python
fieldnames = [
    'pair_id',
    'open_time',
    # ... 现有字段 ...
    'order_type',
    # 新增成功率字段（双语列名）
    'open_status | 开仓状态',
    'open_failure_reason | 开仓失败原因',
    'close_status | 平仓状态',
    'close_failure_reason | 平仓失败原因',
]
```

### Step 5: 在bot.py初始化中添加SuccessTracker

**文件**: `spread/bot.py`

**位置**: `__init__()` 方法

```python
from spread.success_tracker import SuccessTracker, SpreadOperationResult, OperationType, OperationStatus, ExchangeType, FailureReason

class SpreadArbBot:
    def __init__(self, ...):
        # ... 现有初始化代码 ...

        # 001-fix-order-type: 初始化成功率追踪器
        self.success_tracker = SuccessTracker(output_dir="data")
```

### Step 6: 在_cleanup()中导出成功率数据

**文件**: `spread/bot.py`

**位置**: `_cleanup()` 方法

```python
async def _cleanup(self):
    # ... 现有清理代码 ...

    # 导出成功率统计数据
    operations_file = self.success_tracker.export_operations_csv()
    if operations_file:
        self.logger.info(f"成功率数据已导出: {operations_file}")
```

## Testing

### 单元测试

创建测试文件 `tests/test_success_tracker.py`:

```python
import pytest
from decimal import Decimal
from spread.success_tracker import SuccessTracker, SpreadOperationResult, OperationType, OperationStatus, ExchangeType, FailureReason

def test_record_operation():
    tracker = SuccessTracker()
    result = SpreadOperationResult(
        timestamp=1234567890.0,
        operation_type=OperationType.OPEN_SUCCESS,
        status=OperationStatus.SUCCESS,
        exchange=ExchangeType.BOTH,
        order_id="test_order_123",
        quantity=Decimal('0.01'),
    )
    tracker.record_operation(result)
    assert len(tracker._operations) == 1

def test_get_success_rate():
    tracker = SuccessTracker()
    # 记录10次操作，8次成功
    for i in range(8):
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0 + i,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
        ))
    for i in range(2):
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0 + i + 8,
            operation_type=OperationType.OPEN_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.BOTH,
            failure_reason=FailureReason.NETWORK_TIMEOUT,
        ))

    rate = tracker.get_success_rate(OperationType.OPEN_SUCCESS)
    assert rate == 0.8  # 8/10 = 80%
```

运行测试:
```bash
pytest tests/test_success_tracker.py -v
```

### 集成测试

创建测试文件 `tests/integration/test_taker_order_integration.py`:

```python
import pytest
from decimal import Decimal

@pytest.mark.asyncio
async def test_forces_taker_orders(bot, opportunity):
    """测试强制使用taker订单"""
    # 模拟开仓机会
    result = await bot._open_new_pair(opportunity)

    # 验证没有使用maker订单
    assert bot.order_manager.maker_attempts == 0

    # 验证使用了taker订单
    # 检查order_manager的调用记录
    # ...

@pytest.mark.asyncio
async def test_position_consistency_validation(bot):
    """测试仓位一致性验证"""
    # 设置不一致的仓位
    # ...

    # 验证检测到不一致
    # ...
```

## Verification Checklist

- [ ] 所有开仓订单使用taker类型（post_only=False）
- [ ] 开仓后验证仓位一致性
- [ ] 成功率数据正确记录到CSV
- [ ] CSV列名使用双语格式
- [ ] 失败原因正确分类和记录
- [ ] 单元测试全部通过
- [ ] 集成测试全部通过

## Troubleshooting

### 问题: CSV文件中文乱码
**解决**: 使用`encoding='utf-8-sig'`编码，确保Excel兼容性

### 问题: 仓位验证误报
**解决**: 调整阈值参数，`threshold=0.001 ETH`, `rate_threshold=10%`

### 问题: 成功率统计不准确
**解决**: 确保在每个分支都调用`record_operation()`，包括异常处理分支

## Next Steps

完成实现后，使用`/speckit.tasks`命令生成详细任务列表。
