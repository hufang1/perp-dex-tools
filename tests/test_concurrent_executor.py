"""
ConcurrentExecutor单元测试

测试011-async-ws-ioc-trading的并发执行器功能
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from spread.config import SpreadArbConfig
from spread.concurrent_executor import ConcurrentExecutor
from spread.performance_monitor import PerformanceMonitor


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        concurrent_order_send_threshold_ms=5.0,
        order_timeout_ms=500,
        emergency_close_timeout_ms=1000,
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


@pytest.fixture
def extended_client():
    """创建模拟的Extended客户端"""
    client = Mock()
    client.place_order = AsyncMock(return_value={'order_id': 'ext_123', 'status': 'filled'})
    return client


@pytest.fixture
def lighter_client():
    """创建模拟的Lighter客户端"""
    client = Mock()
    client.place_order = AsyncMock(return_value={'order_id': 'lit_456', 'status': 'filled'})
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
class TestConcurrentExecutorBasics:
    """测试并发执行器基础功能"""

    async def test_initialization(self, config, monitor, extended_client, lighter_client):
        """测试初始化"""
        executor = ConcurrentExecutor(config, monitor, extended_client, lighter_client)
        assert executor.config == config
        assert executor.monitor == monitor
        assert executor.extended_client == extended_client
        assert executor.lighter_client == lighter_client


@pytest.mark.asyncio
class TestExecuteConcurrentOrders:
    """测试并发下单"""

    async def test_concurrent_orders_both_success(self, executor):
        """测试双边下单都成功"""
        ext_order = {'side': 'buy', 'quantity': '0.1', 'type': 'LIMIT'}
        lit_order = {'side': 'sell', 'quantity': '0.1', 'type': 'LIMIT'}

        ext_result, lit_result, gap = await executor.execute_concurrent_orders(
            ext_order, lit_order
        )

        assert ext_result['success'] is True
        assert lit_result['success'] is True
        assert gap >= 0  # 时间差应该非负
        assert ext_result.get('order_id') == 'ext_123'
        assert lit_result.get('order_id') == 'lit_456'

    async def test_concurrent_orders_within_threshold(self, executor):
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

        # 间隔应该很小（1ms左右）
        assert gap < 5.0  # 应该小于5ms阈值
        assert ext_result['success']
        assert lit_result['success']

    async def test_concurrent_orders_timeout(self, executor):
        """测试订单超时"""
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

    async def test_concurrent_orders_one_fails(self, executor):
        """测试一边失败"""
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


@pytest.mark.asyncio
class TestExecuteConcurrentClose:
    """测试并发平仓"""

    async def test_concurrent_close_success(self, executor):
        """测试并发平仓成功"""
        ext_order = {'side': 'sell', 'quantity': '0.1', 'type': 'LIMIT'}
        lit_order = {'side': 'buy', 'quantity': '0.1', 'type': 'LIMIT'}

        ext_result, lit_result, gap = await executor.execute_concurrent_close(
            ext_order, lit_order
        )

        assert ext_result['success'] is True
        assert lit_result['success'] is True


@pytest.mark.asyncio
class TestEmergencyClose:
    """测试紧急平仓"""

    async def test_emergency_close_extended(self, executor):
        """测试紧急平仓Extended"""
        async def mock_close(order):
            return {
                'order_id': 'emergency_123',
                'status': 'filled',
                'executed_qty': '0.1',
                'avg_price': '3000'
            }

        executor._place_order_extended = mock_close

        result = await executor.emergency_close_position(
            exchange='extended',
            side='sell',
            quantity=Decimal('0.1')
        )

        assert result['success'] is True
        assert result['order_id'] == 'emergency_123'
        assert result['filled_qty'] == Decimal('0.1')

    async def test_emergency_close_timeout(self, executor):
        """测试紧急平仓超时"""
        async def mock_slow(order):
            await asyncio.sleep(2)  # 超过1000ms超时

        executor._place_order_extended = mock_slow

        result = await executor.emergency_close_position(
            exchange='extended',
            side='sell',
            quantity=Decimal('0.1'),
            timeout_ms=100
        )

        assert result['success'] is False
        assert result.get('error') == 'timeout'

    async def test_emergency_close_lighter(self, executor):
        """测试紧急平仓Lighter"""
        async def mock_close(order):
            return {
                'order_id': 'emergency_lit_456',
                'status': 'filled',
                'executed_qty': '0.05',  # 部分成交
                'avg_price': '3005'
            }

        executor._place_order_lighter = mock_close

        result = await executor.emergency_close_position(
            exchange='lighter',
            side='buy',
            quantity=Decimal('0.1')
        )

        assert result['success'] is True
        assert result['filled_qty'] == Decimal('0.05')

    async def test_emergency_close_exception(self, executor):
        """测试紧急平仓异常"""
        async def mock_error(order):
            raise ValueError("Invalid order")

        executor._place_order_extended = mock_error

        result = await executor.emergency_close_position(
            exchange='extended',
            side='sell',
            quantity=Decimal('0.1')
        )

        assert result['success'] is False
        assert 'Invalid order' in result.get('error', '')


@pytest.mark.asyncio
class TestTimestampRecording:
    """测试时间戳记录"""

    async def test_timestamps_recorded(self, executor):
        """测试时间戳被记录"""
        monitor = executor.monitor

        async def mock_ext(order):
            return {'order_id': 'ext_123'}

        async def mock_lit(order):
            return {'order_id': 'lit_456'}

        executor._place_order_extended = mock_ext
        executor._place_order_lighter = mock_lit

        await executor.execute_concurrent_orders(
            {'side': 'buy', 'quantity': '0.1'},
            {'side': 'sell', 'quantity': '0.1'}
        )

        # 检查时间戳被记录
        assert 'send_A' in monitor._timestamps
        assert 'send_B' in monitor._timestamps

    async def test_concurrent_gap_tracked(self, executor, caplog):
        """测试并发间隔被追踪"""
        import logging
        caplog.set_level(logging.INFO)

        await executor.execute_concurrent_orders(
            {'side': 'buy', 'quantity': '0.1'},
            {'side': 'sell', 'quantity': '0.1'}
        )

        # 检查日志包含并发间隔信息
        assert '并发发送' in caplog.text or '并发下单' in caplog.text


@pytest.mark.asyncio
class TestClientAdapters:
    """测试交易所客户端适配器"""

    async def test_place_order_extended_adapter(self, executor):
        """测试Extended下单适配器"""
        order = {
            'symbol': 'ETH-USD',
            'side': 'buy',
            'quantity': '0.1',
            'price': '3000',
            'type': 'LIMIT'
        }

        result = await executor._place_order_extended(order)

        assert 'order_id' in result or 'error' in result

    async def test_place_order_lighter_adapter(self, executor):
        """测试Lighter下单适配器"""
        order = {
            'symbol': 'ETH-USD',
            'side': 'sell',
            'quantity': '0.1',
            'price': '3005',
            'type': 'LIMIT'
        }

        result = await executor._place_order_lighter(order)

        assert 'order_id' in result or 'error' in result
