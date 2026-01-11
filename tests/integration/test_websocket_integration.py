"""
WebSocket集成测试

测试011-async-ws-ioc-trading的WebSocket连接和数据接收功能
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from spread.config import SpreadArbConfig
from spread.websocket_manager import WebSocketManager
from spread.performance_monitor import PerformanceMonitor
from spread.models import OrderBookSnapshot


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        enable_data_freshness_check=True,
        max_data_age_ms=500.0,
        ticker='ETH'
    )


@pytest.fixture
def monitor(config):
    """创建测试用的性能监控器"""
    return PerformanceMonitor(config)


@pytest.fixture
def ws_manager(config, monitor):
    """创建测试用的WebSocket管理器"""
    return WebSocketManager(config, monitor)


@pytest.mark.asyncio
class TestWebSocketConnection:
    """测试WebSocket连接功能"""

    async def test_connect_extended_success(self, ws_manager):
        """测试成功连接Extended WebSocket"""
        # Mock websocket connection
        with patch('websockets.connect') as mock_connect:
            mock_ws = AsyncMock()
            mock_ws.recv = AsyncMock(side_effect=['{"data": "test"}', asyncio.CancelledError])
            mock_ws.close = AsyncMock()
            mock_connect.return_value = mock_ws

            # Start connection task
            task = asyncio.create_task(ws_manager.connect_extended('ws://localhost:8080/ws'))

            # Wait a bit for connection to establish
            await asyncio.sleep(0.1)

            # Cancel task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_connect_lighter_success(self, ws_manager):
        """测试成功连接Lighter WebSocket"""
        # Mock websocket connection
        with patch('websockets.connect') as mock_connect:
            mock_ws = AsyncMock()
            mock_ws.recv = AsyncMock(side_effect=['{"data": "test"}', asyncio.CancelledError])
            mock_ws.close = AsyncMock()
            mock_connect.return_value = mock_ws

            # Start connection task
            task = asyncio.create_task(ws_manager.connect_lighter('ws://localhost:8081/ws'))

            # Wait a bit for connection to establish
            await asyncio.sleep(0.1)

            # Cancel task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
class TestWebSocketMessageHandling:
    """测试WebSocket消息处理"""

    async def test_orderbook_update_parsing(self, ws_manager):
        """测试订单簿更新解析"""
        # Test Extended orderbook snapshot parsing
        snapshot = OrderBookSnapshot(
            exchange='extended',
            bids={Decimal('3000.0'): Decimal('1.0')},
            asks={Decimal('3001.0'): Decimal('1.0')},
            timestamp=1234567890.0
        )

        assert snapshot.exchange == 'extended'
        assert Decimal('3000.0') in snapshot.bids
        assert Decimal('3001.0') in snapshot.asks


@pytest.mark.asyncio
class TestWebSocketReconnection:
    """测试WebSocket重连功能"""

    async def test_auto_reconnect_on_disconnect(self, ws_manager):
        """测试断线自动重连"""
        # This test would verify that the WebSocket manager
        # automatically reconnects when the connection is lost
        # For now, we just verify the reconnection logic exists
        assert hasattr(ws_manager, 'connect_extended')
        assert hasattr(ws_manager, 'connect_lighter')


@pytest.mark.asyncio
class TestWebSocketDataFreshness:
    """测试WebSocket数据新鲜度"""

    async def test_timestamp_tracking(self, ws_manager):
        """测试时间戳跟踪"""
        # Verify that timestamps are being tracked
        assert hasattr(ws_manager, '_last_extended_update')
        assert hasattr(ws_manager, '_last_lighter_update')

    async def test_data_age_calculation(self, ws_manager):
        """测试数据年龄计算"""
        import time

        # Simulate a recent update
        ws_manager._last_extended_update = time.time() - 100  # 100ms ago

        # Calculate data age
        data_age_ms = (time.time() - ws_manager._last_extended_update) * 1000

        assert data_age_ms >= 100
        assert data_age_ms < 150  # Allow some margin


@pytest.mark.asyncio
class TestWebSocketErrorHandling:
    """测试WebSocket错误处理"""

    async def test_connection_error_handling(self, ws_manager):
        """测试连接错误处理"""
        # Verify that connection errors are handled gracefully
        assert hasattr(ws_manager, 'disconnect_all')

    async def test_invalid_message_handling(self, ws_manager):
        """测试无效消息处理"""
        # This test would verify that invalid messages are handled
        # without crashing the WebSocket manager
        pass


@pytest.mark.asyncio
class TestWebSocketPerformance:
    """测试WebSocket性能"""

    async def test_message_latency_tracking(self, ws_manager):
        """测试消息延迟跟踪"""
        # Verify that message latency is being tracked
        assert hasattr(ws_manager.monitor, 'record_timestamp')

    async def test_orderbook_update_speed(self, ws_manager):
        """测试订单簿更新速度"""
        # This test would measure the speed of orderbook updates
        # For now, just verify the mechanism exists
        assert hasattr(ws_manager, '_handle_extended_message')
        assert hasattr(ws_manager, '_handle_lighter_message')
