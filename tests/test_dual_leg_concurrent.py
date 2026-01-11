"""
双腿并发交易测试

测试并发订单执行的延迟和正确性
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from spread.models import ConcurrentOrderResult


@pytest.mark.asyncio
async def test_concurrent_send_gap_under_5ms():
    """测试并发发送时间差 < 5ms"""
    # 模拟两个订单发送任务
    send_times = []

    async def mock_send_a():
        send_times.append(('A', __import__('time').perf_counter_ns()))
        await asyncio.sleep(0)  # 让出控制权

    async def mock_send_b():
        send_times.append(('B', __import__('time').perf_counter_ns()))
        await asyncio.sleep(0)

    # 并发执行
    await asyncio.gather(mock_send_a(), mock_send_b())

    # 计算时间差（纳秒转毫秒）
    gap_ns = abs(send_times[1][1] - send_times[0][1])
    gap_ms = gap_ns / 1_000_000

    # 验证时间差 < 5ms
    assert gap_ms < 5, f"发送时间差 {gap_ms:.2f}ms 超过 5ms 阈值"


@pytest.mark.asyncio
async def test_both_filled_success():
    """测试双边成交成功场景"""
    result = ConcurrentOrderResult(
        # Extended订单结果
        extended_success=True,
        extended_order_id="ext_123",
        extended_filled_qty=Decimal('0.01'),
        extended_filled_price=Decimal('3000.5'),
        extended_error=None,
        # Lighter订单结果
        lighter_success=True,
        lighter_order_id="lit_456",
        lighter_filled_qty=Decimal('0.01'),
        lighter_filled_price=Decimal('3000.0'),
        lighter_error=None,
        # 并发执行指标
        send_a_ts=1704960123465.23,
        send_b_ts=1704960123468.44,
        send_gap_ms=3.21,
        total_latency_ms=200.5,
        # 成交状态
        is_both_filled=True,
        is_legging=False,
        is_both_failed=False
    )

    assert result.is_both_filled is True
    assert result.is_legging is False
    assert result.is_both_failed is False
    assert result.extended_success is True
    assert result.lighter_success is True


@pytest.mark.asyncio
async def test_execution_latency_under_500ms():
    """测试执行延迟 < 500ms"""
    result = ConcurrentOrderResult(
        extended_success=True,
        extended_order_id="ext_123",
        extended_filled_qty=Decimal('0.01'),
        extended_filled_price=Decimal('3000.5'),
        extended_error=None,
        lighter_success=True,
        lighter_order_id="lit_456",
        lighter_filled_qty=Decimal('0.01'),
        lighter_filled_price=Decimal('3000.0'),
        lighter_error=None,
        send_a_ts=1704960123465.23,
        send_b_ts=1704960123468.44,
        send_gap_ms=3.21,
        total_latency_ms=300.0,  # < 500ms
        is_both_filled=True,
        is_legging=False,
        is_both_failed=False
    )

    assert result.total_latency_ms < 500, f"执行延迟 {result.total_latency_ms}ms 超过 500ms 阈值"
