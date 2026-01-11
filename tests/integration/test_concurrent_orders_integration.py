"""
Concurrent Orders集成测试

测试011-async-ws-ioc-trading的并发下单功能
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from spread.config import SpreadArbConfig
from spread.concurrent_executor import ConcurrentExecutor
from spread.performance_monitor import PerformanceMonitor
from spread.ioc_order_manager import IocOrderManager


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        concurrent_order_send_threshold_ms=5.0,
        order_timeout_ms=500,
        emergency_close_timeout_ms=1000,
        ioc_slippage_tolerance_rate=Decimal('0.0005'),
        use_ioc_orders=True,
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


@pytest.fixture
def ioc_manager(config):
    """创建测试用的IOC订单管理器"""
    return IocOrderManager(config)


@pytest.fixture
def extended_client():
    """创建模拟的Extended客户端"""
    client = Mock()
    client.place_order = AsyncMock(return_value={
        'order_id': 'ext_123',
        'status': 'filled',
        'executed_qty': '0.1',
        'avg_price': '3000.50'
    })
    return client


@pytest.fixture
def lighter_client():
    """创建模拟的Lighter客户端"""
    client = Mock()
    client.place_order = AsyncMock(return_value={
        'order_id': 'lit_456',
        'status': 'filled',
        'executed_qty': '0.1',
        'avg_price': '3003.00'
    })
    return client


@pytest.fixture
def executor(config, monitor, extended_client, lighter_client):
    """创建测试用的并发执行器"""
    return ConcurrentExecutor(
        config=config,
        monitor=monitor,
        extended_client=extended_client,
        lighter_client=lighter_client
    )


@pytest.mark.asyncio
class TestConcurrentExecution:
    """测试并发执行功能"""

    async def test_concurrent_orders_both_success(self, executor):
        """测试双边下单都成功"""
        ext_order = {
            'side': 'buy',
            'quantity': '0.1',
            'type': 'LIMIT',
            'price': '3000.50'
        }
        lit_order = {
            'side': 'sell',
            'quantity': '0.1',
            'type': 'LIMIT',
            'price': '3003.00'
        }

        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order
        )

        assert ext_result['success'] is True
        assert lit_result['success'] is True
        assert gap >= 0  # 时间差应该非负

    async def test_concurrent_gap_within_threshold(self, executor):
        """测试并发间隔在阈值内"""
        # 模拟快速响应
        async def mock_ext(order):
            await asyncio.sleep(0.001)  # 1ms
            return {'order_id': 'ext_123', 'status': 'filled'}

        async def mock_lit(order):
            await asyncio.sleep(0.002)  # 2ms
            return {'order_id': 'lit_456', 'status': 'filled'}

        executor._place_order_extended = mock_ext
        executor._place_order_lighter = mock_lit

        ext_order = {'side': 'buy', 'quantity': '0.1'}
        lit_order = {'side': 'sell', 'quantity': '0.1'}

        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order
        )

        # 间隔应该很小（小于5ms阈值）
        assert gap < 5.0
        assert ext_result['success']
        assert lit_result['success']


@pytest.mark.asyncio
class TestConcurrentExecutionWithRealWorldScenario:
    """测试真实世界场景"""

    async def test_opening_spread_position(self, executor, ioc_manager):
        """测试开仓价差仓位"""
        # 创建IOC订单
        ext_order = ioc_manager.create_ioc_order(
            exchange='extended',
            side='buy',
            price=Decimal('3000.00'),
            quantity=Decimal('0.1')
        )

        lit_order = ioc_manager.create_ioc_order(
            exchange='lighter',
            side='sell',
            price=Decimal('3003.00'),
            quantity=Decimal('0.1')
        )

        # 执行并发下单
        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order
        )

        assert ext_result['success']
        assert lit_result['success']
        assert gap < executor.config.concurrent_order_send_threshold_ms * 10  # 允许一定误差

    async def test_emergency_close_position(self, executor):
        """测试紧急平仓"""
        result = await executor.emergency_close_position(
            exchange='extended',
            side='sell',
            quantity=Decimal('0.1')
        )

        assert result['success']
        assert result.get('order_id')


@pytest.mark.asyncio
class TestConcurrentExecutionErrorHandling:
    """测试并发执行错误处理"""

    async def test_one_side_fails(self, executor):
        """测试一边失败"""
        # 模拟Extended失败
        async def mock_fail(order):
            raise Exception("Network error")

        async def mock_success(order):
            return {'order_id': 'lit_456', 'status': 'filled'}

        executor._place_order_extended = mock_fail
        executor._place_order_lighter = mock_success

        ext_order = {'side': 'buy', 'quantity': '0.1'}
        lit_order = {'side': 'sell', 'quantity': '0.1'}

        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order
        )

        assert ext_result['success'] is False
        assert lit_result['success'] is True

    async def test_timeout_handling(self, executor):
        """测试超时处理"""
        # 模拟超时
        async def mock_slow(order):
            await asyncio.sleep(1)  # 超过500ms超时
            return {'order_id': 'slow', 'status': 'filled'}

        executor._place_order_extended = mock_slow
        executor._place_order_lighter = mock_slow

        ext_order = {'side': 'buy', 'quantity': '0.1'}
        lit_order = {'side': 'sell', 'quantity': '0.1'}

        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order, timeout_ms=100  # 100ms超时
        )

        # 两个订单都应该超时
        assert ext_result['success'] is False
        assert lit_result['success'] is False
        assert ext_result.get('error') == 'timeout'
        assert lit_result.get('error') == 'timeout'


@pytest.mark.asyncio
class TestConcurrentExecutionPerformance:
    """测试并发执行性能"""

    async def test_execution_latency_tracking(self, executor):
        """测试执行延迟跟踪"""
        monitor = executor.monitor

        # 执行下单
        ext_order = {'side': 'buy', 'quantity': '0.1'}
        lit_order = {'side': 'sell', 'quantity': '0.1'}

        await executor.execute_concurrent_orders(ext_order, lit_order)

        # 验证时间戳被记录
        assert 'send_A' in monitor._timestamps
        assert 'send_B' in monitor._timestamps

    async def test_concurrent_gap_statistics(self, executor):
        """测试并发间隔统计"""
        # 执行多次下单
        for _ in range(5):
            ext_order = {'side': 'buy', 'quantity': '0.1'}
            lit_order = {'side': 'sell', 'quantity': '0.1'}
            await executor.execute_concurrent_orders(ext_order, lit_order)

        # 检查统计
        stats = executor.monitor.get_stats_summary()
        # 并发间隔应该被记录
        assert len(executor.monitor._stats['concurrent_gaps']) == 5


@pytest.mark.asyncio
class TestConcurrentExecutionIntegration:
    """测试并发执行集成"""

    async def test_full_opening_workflow(self, executor, ioc_manager):
        """测试完整开仓工作流"""
        # 1. 创建IOC订单
        ext_order = ioc_manager.create_ioc_order(
            exchange='extended',
            side='buy',
            price=Decimal('3000.00'),
            quantity=Decimal('0.1')
        )

        lit_order = ioc_manager.create_ioc_order(
            exchange='lighter',
            side='sell',
            price=Decimal('3003.00'),
            quantity=Decimal('0.1')
        )

        # 2. 记录时间戳
        executor.monitor.record_timestamp('signal')

        # 3. 执行并发下单
        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order
        )

        # 4. 验证结果
        assert ext_result['success']
        assert lit_result['success']

        # 5. 记录ACK时间戳
        executor.monitor.record_timestamp('ack_A')
        executor.monitor.record_timestamp('ack_B')

        # 6. 验证时间戳
        assert 'signal' in executor.monitor._timestamps
        assert 'ack_A' in executor.monitor._timestamps
        assert 'ack_B' in executor.monitor._timestamps
