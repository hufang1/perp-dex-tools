"""
强制平仓集成测试（用户故事1 - 006-fix-lighter-close）

测试完整的强制平仓流程，验证CLOSE订单能被正确处理
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, AsyncMock

from spread.order_manager import SpreadOrderManager
from spread.spread_pair import SpreadPair


class MockConfig:
    def __init__(self):
        self.ticker = 'ETH'
        self.order_quantity_usdt = Decimal('35')
        self.extended_fill_timeout = 10
        self.enable_partial_fill = True


@pytest.fixture
def config():
    return MockConfig()


@pytest.fixture
def mock_extended_client():
    client = Mock()
    client.contract_id = 'ETH-USD'
    return client


@pytest.fixture
def order_manager(config, mock_extended_client):
    return SpreadOrderManager(config, mock_extended_client)


class TestForceCloseIntegration:
    """测试强制平仓集成流程"""

    @pytest.mark.asyncio
    async def test_close_order_flow_from_websocket_to_wait_for_fill(self, order_manager):
        """
        集成测试：完整平仓流程

        场景：
        1. 模拟提交CLOSE订单
        2. 模拟WebSocket推送CLOSE订单FILLED更新
        3. 验证wait_for_fill正确返回成交结果
        4. 验证filled_quantity不是0（修复前的问题）
        """
        order_id = "2009608496505368576"

        # 模拟下单
        order_manager.current_order_id = order_id
        order_manager.current_order_status = None
        order_manager.filled_quantity = Decimal('0')
        order_manager.filled_price = Decimal('0')

        # 模拟WebSocket推送CLOSE订单FILLED更新
        # 这是修复的关键：CLOSE订单更新不再被忽略
        close_order_update = {
            'order_id': order_id,
            'status': 'FILLED',
            'side': 'sell',
            'order_type': 'CLOSE',  # 关键：CLOSE类型
            'size': '0.01',
            'price': '3082.8',
            'contract_id': 'ETH-USD',
            'filled_size': '0.010'
        }

        # 应用订单更新
        order_manager.update_order_status(close_order_update)

        # 验证状态已更新（修复前会被忽略）
        assert order_manager.current_order_status == 'FILLED'
        assert order_manager.filled_quantity == Decimal('0.010')
        assert order_manager.filled_price == Decimal('3082.8')

        # 验证wait_for_fill会立即返回FILLED（不会超时）
        # 在修复前，这里会超时并返回filled_quantity=0
        result = await order_manager.wait_for_fill(
            order_id=order_id,
            timeout=5,
            allow_partial=False
        )

        # 验证结果
        assert result['status'] == 'FILLED'
        assert result['filled_quantity'] == Decimal('0.010')
        assert result['filled_price'] == Decimal('3082.8')
        # 关键验证：filled_quantity不是0（修复前的问题）
        assert result['filled_quantity'] > 0

    @pytest.mark.asyncio
    async def test_race_condition_close_order_update_before_order_id(self, order_manager):
        """
        集成测试：CLOSE订单更新在order_id设置前到达（竞态条件）

        场景：
        1. WebSocket推送CLOSE订单FILLED更新
        2. 此时current_order_id还是None
        3. 然后设置current_order_id
        4. 验证缓存机制正确处理CLOSE订单
        """
        order_id = "2009608496505368576"

        # 1. CLOSE订单更新在order_id设置前到达
        close_order_update = {
            'order_id': order_id,
            'status': 'FILLED',
            'order_type': 'CLOSE',
            'filled_size': '0.010',
            'price': '3082.8'
        }

        # current_order_id为None，应该被缓存
        order_manager.update_order_status(close_order_update)

        # 验证更新被缓存
        assert order_id in order_manager._pending_updates
        assert order_manager.current_order_status is None

        # 2. 设置order_id（模拟下单返回）
        order_manager.current_order_id = order_id

        # 3. 应用缓存更新
        await order_manager._apply_pending_updates(order_id)

        # 4. 验证CLOSE订单被正确处理
        assert order_manager.current_order_status == 'FILLED'
        assert order_manager.filled_quantity == Decimal('0.010')

        # 5. 验证wait_for_fill正常工作
        result = await order_manager.wait_for_fill(
            order_id=order_id,
            timeout=5,
            allow_partial=False
        )

        assert result['status'] == 'FILLED'
        assert result['filled_quantity'] == Decimal('0.010')

    @pytest.mark.asyncio
    async def test_multiple_close_orders_independent_tracking(self, order_manager):
        """
        集成测试：多个CLOSE订单的独立跟踪

        场景：
        1. 两个套利对同时平仓
        2. 验证每个套利对的CLOSE订单被独立跟踪
        3. 验证状态不会混淆
        """
        order1_id = "2009608496505368576"
        order2_id = "2009608541413720064"

        # 套利对1的CLOSE订单更新
        order1_update = {
            'order_id': order1_id,
            'status': 'FILLED',
            'order_type': 'CLOSE',
            'filled_size': '0.010',
            'price': '3082.8'
        }

        # 套利对2的CLOSE订单更新
        order2_update = {
            'order_id': order2_id,
            'status': 'FILLED',
            'order_type': 'CLOSE',
            'filled_size': '0.015',
            'price': '3083.0'
        }

        # 两个更新都到达
        order_manager.update_order_status(order1_update)
        order_manager.update_order_status(order2_update)

        # 验证两个订单都被缓存
        assert order1_id in order_manager._pending_updates
        assert order2_id in order_manager._pending_updates

        # 处理订单1
        order_manager.current_order_id = order1_id
        await order_manager._apply_pending_updates(order1_id)
        assert order_manager.filled_quantity == Decimal('0.010')

        # 验证订单2的缓存还在
        assert order2_id in order_manager._pending_updates

        # 处理订单2（重置状态模拟新的下单）
        order_manager.current_order_id = order2_id
        order_manager.current_order_status = None
        order_manager.filled_quantity = Decimal('0')
        await order_manager._apply_pending_updates(order2_id)

        # 验证订单2的状态正确
        assert order_manager.filled_quantity == Decimal('0.015')

    @pytest.mark.asyncio
    async def test_close_order_timeout_before_fix_scenario(self, order_manager):
        """
        集成测试：验证修复前的超时场景不再发生

        这个测试验证修复前的问题不会再次出现：
        - CLOSE订单更新被忽略
        - wait_for_fill超时
        - 返回filled_quantity=0
        """
        order_id = "2009608496505368576"

        # 设置初始状态
        order_manager.current_order_id = order_id
        order_manager.current_order_status = None
        order_manager.filled_quantity = Decimal('0')
        order_manager.filled_price = Decimal('0')

        # 发送CLOSE订单更新
        close_order_update = {
            'order_id': order_id,
            'status': 'FILLED',
            'order_type': 'CLOSE',
            'filled_size': '0.010',
            'price': '3082.8'
        }

        order_manager.update_order_status(close_order_update)

        # 关键验证：CLOSE订单被处理，状态已更新
        # 修复前这里会是None
        assert order_manager.current_order_status == 'FILLED'

        # 验证wait_for_fill不会超时
        result = await order_manager.wait_for_fill(
            order_id=order_id,
            timeout=5,
            allow_partial=False
        )

        # 关键验证：不会返回TIMEOUT和filled_quantity=0
        assert result['status'] == 'FILLED', f"Expected FILLED but got {result['status']}"
        assert result['filled_quantity'] == Decimal('0.010'), \
            f"Expected 0.010 but got {result['filled_quantity']}"

        # 确保不是超时返回（修复前会返回0）
        assert result['filled_quantity'] > 0, "filled_quantity should not be 0"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
