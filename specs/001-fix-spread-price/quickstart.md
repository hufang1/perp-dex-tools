# Quickstart Guide: 修复Spread套利脚本价格同步问题

**Feature**: 001-fix-spread-price
**Date**: 2026-01-16
**Branch**: `001-fix-spread-price`

---

## 概述

本指南提供了快速实施修复spread套利脚本价格同步问题的步骤。修复分为三个主要部分：
1. 在execute_open_position层面统一获取价格
2. 为Extended加入0.2%滑点保护
3. 清理/弃用Maker模式代码

---

## 前置条件

### 环境要求

- Python 3.10.19+
- asyncio, aiohttp, websockets
- lighter-sdk
- x10-python-trading-starknet

### 当前分支

```bash
git checkout 001-fix-spread-price
```

---

## 快速开始

### 步骤1：创建价格快照类（30分钟）

创建新文件 `spread/price_snapshot.py`：

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

@dataclass
class PriceSnapshot:
    """价格快照：记录某一时刻两个交易所的BBO价格"""
    ext_bid: Decimal
    ext_ask: Decimal
    ext_timestamp: float
    lig_bid: Decimal
    lig_ask: Decimal
    lig_timestamp: float
    time_delta: float

    def is_valid(self) -> bool:
        """验证价格快照是否有效"""
        return (
            self.ext_bid > 0 and self.ext_ask > 0 and
            self.lig_bid > 0 and self.lig_ask > 0 and
            self.ext_bid < self.ext_ask and
            self.lig_bid < self.lig_ask and
            self.time_delta < 0.01  # <10ms
        )

    def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]:
        """计算taker订单价格（加入0.2%滑点保护）"""
        ext_price = self.ext_ask * Decimal('1.002')
        lig_price = self.lig_bid * Decimal('0.998')
        return ext_price, lig_price

    def validate_price_consistency(self) -> bool:
        """验证价格一致性（ext买入价 < lig卖出价）"""
        ext_price, lig_price = self.calculate_taker_prices()
        return ext_price < lig_price
```

**验证**：
```bash
python -c "from spread.price_snapshot import PriceSnapshot; print('OK')"
```

---

### 步骤2：修改execute_open_position统一获取价格（1小时）

编辑 `spread/trade_executor.py` 的 `execute_open_position` 方法：

```python
async def execute_open_position(
    self,
    quantity: Decimal,
    spread: Union[RealTimeSpreadInfo, SpreadInfo]
) -> ExecutionResult:
    """
    执行开仓（P0优化：统一价格获取+滑点保护）
    """
    import time
    from spread.price_snapshot import PriceSnapshot

    start_time = time.time()

    # Step 1: 并发获取两个交易所的价格
    ext_bbo_future = self.extended_client.fetch_bbo_prices(
        self.extended_client.config.contract_id
    )
    lig_bbo_future = self.lighter_client.fetch_bbo_prices(
        self.lighter_client.config.contract_id
    )

    # 获取Ext价格并记录时间戳
    ext_fetch_start = time.time()
    ext_bid, ext_ask = await ext_bbo_future
    ext_fetch_time = time.time()

    # 获取Lig价格并记录时间戳
    lig_fetch_start = time.time()
    lig_bid, lig_ask = await lig_bbo_future
    lig_fetch_time = time.time()

    # 计算时间差
    time_delta = abs(lig_fetch_time - ext_fetch_time)

    # Step 2: 创建价格快照
    price_snapshot = PriceSnapshot(
        ext_bid=ext_bid,
        ext_ask=ext_ask,
        ext_timestamp=ext_fetch_time,
        lig_bid=lig_bid,
        lig_ask=lig_ask,
        lig_timestamp=lig_fetch_time,
        time_delta=time_delta
    )

    # Step 3: 验证价格快照
    if not price_snapshot.is_valid():
        logger.warning(
            f"价格快照无效: time_delta={time_delta*1000:.1f}ms, "
            f"跳过此次开仓"
        )
        return ExecutionResult(
            success=False,
            error_message=f"价格快照无效: time_delta={time_delta*1000:.1f}ms",
            execution_time=time.time() - start_time
        )

    # Step 4: 计算taker价格（0.2%滑点）
    ext_price, lig_price = price_snapshot.calculate_taker_prices()

    # Step 5: 验证价格一致性
    if not price_snapshot.validate_price_consistency():
        logger.error(
            f"价差异常: ext买入={ext_price} >= lig卖出={lig_price}, "
            f"跳过此次开仓"
        )
        return ExecutionResult(
            success=False,
            error_message=f"价差异常: ext={ext_price} >= lig={lig_price}",
            execution_time=time.time() - start_time
        )

    logger.info(
        f"[价格同步] "
        f"ext={ext_price:.2f}, lig={lig_price:.2f}, "
        f"time_delta={time_delta*1000:.1f}ms, "
        f"spread={spread.spread_pct:.2%}"
    )

    # Step 6: 并发发送订单（使用计算好的价格）
    results = await asyncio.gather(
        self._place_extended_order_taker("buy", quantity, ext_price),
        self._place_lighter_order_taker("sell", quantity, lig_price),
        return_exceptions=True
    )

    # ... 后续逻辑保持不变 ...
```

**关键改动**：
- ✅ 不再从spread参数获取价格
- ✅ 并发获取两个交易所价格
- ✅ 记录时间戳并计算time_delta
- ✅ 验证价格快照和一致性

---

### 步骤3：修改_place_extended_order_taker加入滑点保护（30分钟）

编辑 `spread/trade_executor.py` 的 `_place_extended_order_taker` 方法：

```python
async def _place_extended_order_taker(
    self,
    side: str,
    quantity: Decimal,
    price: Optional[Decimal]
) -> Dict[str, Any]:
    """
    下Extended Taker订单（P0优化：加入0.2%滑点保护）
    """
    try:
        contract_id = self.extended_client.config.contract_id

        # Taker模式：获取对手价确保即时成交
        if price is None:
            best_bid, best_ask = await self.extended_client.fetch_bbo_prices(contract_id)
            if side == "buy":
                price = best_ask * Decimal('1.002')  # ✅ 加0.2%滑点
            else:
                price = best_bid * Decimal('0.998')  # ✅ 减0.2%滑点

        # 调用 Extended 客户端的 taker 订单方法
        result = await self.extended_client.place_taker_order(
            contract_id=contract_id,
            quantity=quantity,
            side=side,
            price=price
        )

        if result.success:
            return {
                "order_id": result.order_id,
                "price": result.price if result.price else price
            }
        else:
            raise Exception(result.error_message)

    except Exception as e:
        logger.error(f"Extended Taker订单失败: {e}")
        raise
```

**关键改动**：
- ❌ 删除：`price = best_ask` / `price = best_bid`
- ✅ 新增：`price = best_ask * 1.002` / `price = best_bid * 0.998`

---

### 步骤4：修改Extended客户端限制重试（45分钟）

编辑 `exchanges/extended.py` 的 `place_taker_order` 方法：

```python
async def place_taker_order(
    self,
    contract_id: str,
    quantity: Decimal,
    side: str,
    price: Decimal,
    max_retries: int = 1  # ✅ 新增参数：限制重试次数
) -> OrderResult:
    """
    下Extended Taker订单（限制重试版本）

    Args:
        max_retries: 最大重试次数（默认1次，使用原始价格）
    """
    retry_count = 0
    original_price = price  # ✅ 缓存原始价格

    while retry_count < max_retries:
        try:
            # 转换side字符串为OrderSide枚举
            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

            # Round price to appropriate precision
            rounded_price = self.round_to_tick(original_price)  # ✅ 使用原始价格
            quantity = quantity.quantize(self.min_order_size, rounding=ROUND_HALF_UP)

            # 下单（使用原始价格）
            order_result = await self.perpetual_trading_client.place_order(
                market_name=contract_id,
                amount_of_synthetic=quantity,
                price=rounded_price,  # ✅ 使用原始价格，不重新获取
                side=order_side,
                time_in_force=TimeInForce.IOC,
                post_only=False,
                expire_time=utc_now() + timedelta(minutes=1),
            )

            # 检查结果
            if not order_result or not order_result.data or order_result.status != 'OK':
                if retry_count < max_retries - 1:
                    retry_count += 1
                    await asyncio.sleep(0.05)
                    continue
                else:
                    return OrderResult(success=False, error_message='Failed to place taker order')

            # 提取订单ID
            order_id = order_result.data.id
            if not order_id:
                return OrderResult(success=False, error_message='No order ID in response')

            # 检查订单状态
            await asyncio.sleep(0.05)
            order_info = await self.get_order_info(order_id)

            if order_info:
                if order_info.status in ['FILLED', 'PARTIALLY_FILLED']:
                    return OrderResult(
                        success=True,
                        order_id=order_id,
                        side=side,
                        size=quantity,
                        price=rounded_price,
                        status=order_info.status,
                        filled_size=order_info.filled_size
                    )
                elif order_info.status in ['CANCELED', 'REJECTED']:
                    if retry_count < max_retries - 1:
                        self.logger.log(f"Taker order not filled, retrying ({retry_count+1}/{max_retries})...")
                        retry_count += 1
                        await asyncio.sleep(0.05)
                        continue
                    else:
                        return OrderResult(success=False, error_message='Taker order not filled')
                else:
                    return OrderResult(success=False, error_message=f'Unexpected order status: {order_info.status}')
            else:
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    side=side,
                    size=quantity,
                    price=rounded_price
                )

        except Exception as e:
            if retry_count < max_retries - 1:
                retry_count += 1
                await asyncio.sleep(0.05)
                continue
            else:
                return OrderResult(success=False, error_message=str(e))

    return OrderResult(success=False, error_message='Max retries exceeded')
```

**关键改动**：
- ✅ 新增：`max_retries` 参数（默认1次）
- ✅ 新增：`original_price` 缓存
- ✅ 修改：使用 `original_price` 而非重新获取
- ✅ 修改：重试次数从10次改为1次

---

### 步骤5：弃用Maker模式代码（30分钟）

编辑 `exchanges/lighter.py`，添加弃用警告：

```python
import warnings

async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
    """
    ⚠️ DEPRECATED: 此方法使用Maker模式（中间价+GTT+等待循环）

    此方法将于未来版本移除。

    请使用以下Taker模式替代：
    - spread套利：使用 trade_executor._place_lighter_order_taker()
    - 直接调用：使用 place_limit_order(..., time_in_force=0)

    Migration Guide:
    - 旧代码：await client.place_open_order(contract_id, qty, direction)
    - 新代码：await client.place_limit_order(contract_id, qty, ask*1.002 or bid*0.998, direction, time_in_force=0)

    Args:
        contract_id: 合约ID
        quantity: 数量
        direction: 方向 ('buy' or 'sell')

    Returns:
        OrderResult: 订单结果
    """
    warnings.warn(
        "place_open_order is DEPRECATED and uses Maker mode. "
        "Use Taker mode with time_in_force=0 instead. "
        "This method will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )

    # ... 原有实现保持不变 ...
```

```python
async def get_order_price(self, side: str = '') -> Decimal:
    """
    ⚠️ DEPRECATED: 此方法使用中间价计算，不适合Taker模式

    此方法将于未来版本移除。

    Migration Guide:
    - Taker买入价：best_ask * 1.002
    - Taker卖出价：best_bid * 0.998

    Args:
        side: 方向

    Returns:
        Decimal: 订单价格（中间价）
    """
    warnings.warn(
        "get_order_price is DEPRECATED. "
        "For Taker mode, use: ask*1.002 (buy) or bid*0.998 (sell). "
        "This method will be removed in a future version.",
        DeprecationWarning,
        stacklevel=2
    )

    # ... 原有实现保持不变 ...
```

---

## 测试验证

### 单元测试

创建 `tests/unit/test_price_snapshot.py`：

```python
import pytest
from decimal import Decimal
from spread.price_snapshot import PriceSnapshot

class TestPriceSnapshot:
    """价格快照测试"""

    def test_valid_snapshot(self):
        """测试有效的价格快照"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        assert snapshot.is_valid()
        assert snapshot.validate_price_consistency()

    def test_invalid_time_delta(self):
        """测试时间差过大"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.05,  # 50ms
            time_delta=0.05
        )
        assert not snapshot.is_valid()

    def test_taker_price_calculation(self):
        """测试taker价格计算"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        ext_price, lig_price = snapshot.calculate_taker_prices()

        # 验证0.2%滑点
        expected_ext = Decimal('3000.50') * Decimal('1.002')
        expected_lig = Decimal('2999.50') * Decimal('0.998')

        assert ext_price == expected_ext
        assert lig_price == expected_lig
```

**运行测试**：
```bash
pytest tests/unit/test_price_snapshot.py -v
```

---

## 部署检查清单

### 部署前

- [ ] 所有单元测试通过
- [ ] 价格快照导入测试通过
- [ ] 代码审查完成

### 部署时

- [ ] 切换到 `001-fix-spread-price` 分支
- [ ] 备份当前版本的 `trade_executor.py` 和 `extended.py`
- [ ] 部署到测试环境

### 部署后验证

- [ ] 观察日志中的"价格同步"输出
- [ ] 验证 time_delta <10ms
- [ ] 验证 "Order not found" 日志减少80%+
- [ ] 验证 Ext成本 < Lig 成本
- [ ] 确认没有DeprecationWarning（spread脚本）

---

## 故障排查

### 问题1：价格获取失败

**症状**：日志显示"价格快照无效: time_delta=XXXms"

**原因**：两个交易所价格获取时间差超过10ms

**解决**：
- 检查网络延迟
- 检查交易所API响应时间
- 考虑增加time_delta阈值到20ms

### 问题2：价差异常

**症状**：日志显示"价差异常: ext买入 >= lig卖出"

**原因**：价差不够大或市场价格波动

**解决**：
- 检查价差阈值设置
- 等待更好的套利机会
- 正常现象，系统正确跳过

### 问题3：仍然频繁重试

**症状**："Order not found"日志没有明显减少

**原因**：
1. 滑点保护可能不够（考虑增加到0.3%）
2. 交易所流动性问题
3. 代码未正确部署

**解决**：
- 验证代码是否正确部署
- 检查日志中的滑点价格是否正确
- 考虑调整滑点大小

---

## 日志示例

### 正常开仓日志

```
2026-01-16 10:00:00.123 - INFO - [价格同步] ext_bid=3000.00, ext_ask=3000.50, lig_bid=2999.50, lig_ask=3000.00, time_delta=5.2ms, ext_price=3006.50, lig_price=2993.01, spread=0.45%
2026-01-16 10:00:00.150 - INFO - Lig Taker订单: sell 0.21 @ 2993.01
2026-01-16 10:00:00.160 - INFO - Ext Taker订单: buy 0.21 @ 3006.50
2026-01-16 10:00:00.450 - INFO - 开仓成功: ext_order_id=ext_123, lig_order_id=lig_456, 耗时=0.327s
```

### 价差异常跳过日志

```
2026-01-16 10:01:00.123 - ERROR - 价差异常: ext买入=3006.50 >= lig卖出=3006.00, 跳过此次开仓
```

### 价格快照无效日志

```
2026-01-16 10:02:00.123 - WARNING - 价格快照无效: time_delta=15.2ms, 跳过此次开仓
```

---

## 回滚步骤

如果需要回滚到旧版本：

```bash
# 1. 切换回主分支
git checkout main

# 2. 或者恢复单个文件
git checkout main -- spread/trade_executor.py
git checkout main -- exchanges/extended.py

# 3. 重启脚本
# 使用旧版本启动
```

---

## 下一步

完成快速开始后，建议：

1. **运行单元测试**：确保所有测试通过
2. **测试环境验证**：模拟开仓流程
3. **小仓位试运行**：0.01 ETH仓位测试24小时
4. **全量发布**：确认后移除仓位限制

---

**版本**: 1.0
**最后更新**: 2026-01-16
**预计实施时间**: 约8小时开发 + 1-2天验证
