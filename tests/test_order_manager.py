"""
订单管理器单元测试

测试SpreadOrderManager的缓存机制和竞态条件修复
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, MagicMock, AsyncMock
from collections import namedtuple

from spread.order_manager import SpreadOrderManager
from spread.config import SpreadArbConfig


# 模拟配置对象
class MockConfig:
    def __init__(self):
        self.ticker = 'ETH'
        self.order_quantity_usdt = Decimal('35')
        self.extended_fill_timeout = 10
        self.enable_partial_fill = True


@pytest.fixture
def config():
    """创建测试配置"""
    return MockConfig()


@pytest.fixture
def mock_extended_client():
    """模拟Extended客户端"""
    client = Mock()
    client.contract_id = 'ETH-USD'
    return client


@pytest.fixture
def order_manager(config, mock_extended_client):
    """创建订单管理器实例"""
    return SpreadOrderManager(config, mock_extended_client)


class TestCloseOrderHandling:
    """测试CLOSE订单处理（用户故事1 - 006-fix-lighter-close）"""

    def test_close_order_updates_are_processed(self, order_manager):
        """
        测试：CLOSE类型订单更新应该被处理，而不是被忽略

        场景：
        1. CLOSE订单WebSocket更新到达
        2. 验证更新没有被忽略
        3. 验证订单状态被正确更新
        4. 验证filled_quantity和filled_price被正确设置

        这是006-fix-lighter-close的核心修复：CLOSE订单不再被忽略
        """
        order_id = "2009608496505368576"
        order_data = {
            'order_id': order_id,
            'status': 'FILLED',
            'side': 'sell',
            'order_type': 'CLOSE',  # 关键：CLOSE类型订单
            'size': '0.01',
            'price': '3082.8',
            'contract_id': 'ETH-USD',
            'filled_size': '0.010'
        }

        # 设置current_order_id
        order_manager.current_order_id = order_id

        # 发送CLOSE订单更新
        order_manager.update_order_status(order_data)

        # 验证CLOSE订单被处理（没有在旧代码中被忽略）
        assert order_manager.current_order_status == 'FILLED'
        assert order_manager.filled_quantity == Decimal('0.010')
        assert order_manager.filled_price == Decimal('3082.8')

    def test_close_order_cached_when_order_id_not_set(self, order_manager):
        """
        测试：CLOSE订单更新在current_order_id设置前到达时应该被缓存

        场景：
        1. CLOSE订单更新到达时current_order_id为None
        2. 验证更新被缓存
        3. 验证设置order_id后缓存被应用
        """
        order_id = "2009608496505368576"
        order_data = {
            'order_id': order_id,
            'status': 'FILLED',
            'order_type': 'CLOSE',
            'filled_size': '0.010',
            'price': '3082.8'
        }

        # current_order_id未设置时发送CLOSE订单更新
        assert order_manager.current_order_id is None
        order_manager.update_order_status(order_data)

        # 验证更新被缓存
        assert order_id in order_manager._pending_updates
        assert len(order_manager._pending_updates[order_id]) == 1

        # 设置order_id并应用缓存
        order_manager.current_order_id = order_id

        # 需要异步应用
        async def apply_cache():
            await order_manager._apply_pending_updates(order_id)
            assert order_manager.current_order_status == 'FILLED'
            assert order_manager.filled_quantity == Decimal('0.010')

        # 运行异步函数
        asyncio.run(apply_cache())

    def test_close_order_with_zero_filled_size(self, order_manager):
        """
        测试：CLOSE订单更新时filled_size为0的处理

        场景：
        1. CLOSE订单更新到达但filled_size为"0"
        2. 验证filled_quantity不会被0覆盖
        """
        order_id = "2009608496505368576"

        # 先设置一个成交数量
        order_manager.current_order_id = order_id
        order_manager.current_order_status = 'PARTIALLY_FILLED'
        order_manager.filled_quantity = Decimal('0.005')
        order_manager.filled_price = Decimal('3082.5')

        # 发送filled_size为0的更新
        order_data = {
            'order_id': order_id,
            'status': 'FILLED',
            'order_type': 'CLOSE',
            'filled_size': '0',  # 关键：filled_size为0
            'price': '3082.8'
        }
        order_manager.update_order_status(order_data)

        # 验证filled_quantity没有被0覆盖
        assert order_manager.filled_quantity == Decimal('0.005')
        # 验证状态被更新
        assert order_manager.current_order_status == 'FILLED'


class TestRaceConditionFix:
    """测试竞态条件修复（用户故事1）"""

    @pytest.mark.asyncio
    async def test_order_update_before_order_id_set(self, order_manager):
        """
        测试：订单更新在current_order_id设置前到达（竞态条件场景）

        场景：
        1. WebSocket回调收到FILLED状态更新
        2. 此时current_order_id还是None
        3. 验证缓存机制正确保存更新
        4. 验证current_order_id设置后应用缓存更新
        5. 验证filled_quantity和filled_price被正确更新
        """
        order_id = "2008773271629754368"
        order_data = {
            'order_id': order_id,
            'status': 'FILLED',
            'side': 'buy',
            'order_type': 'OPEN',
            'size': '0.01',
            'price': '3251.4',
            'contract_id': 'ETH-USD',
            'filled_size': '0.010'
        }

        # 1. 在current_order_id为None时接收订单更新（模拟WebSocket回调）
        assert order_manager.current_order_id is None
        order_manager.update_order_status(order_data)

        # 2. 验证更新被缓存
        assert order_id in order_manager._pending_updates
        assert len(order_manager._pending_updates[order_id]) == 1
        assert order_manager._pending_updates[order_id][0]['order_data']['status'] == 'FILLED'

        # 3. 验证当前状态未更新（因为被缓存了）
        assert order_manager.current_order_status is None
        assert order_manager.filled_quantity == Decimal('0')

        # 4. 设置current_order_id（模拟place_spread_maker_order返回）
        order_manager.current_order_id = order_id

        # 5. 应用缓存更新
        await order_manager._apply_pending_updates(order_id)

        # 6. 验证状态已更新
        assert order_manager.current_order_status == 'FILLED'
        assert order_manager.filled_quantity == Decimal('0.010')
        assert order_manager.filled_price == Decimal('3251.4')

        # 7. 验证缓存已清理
        assert order_id not in order_manager._pending_updates

        # 8. 验证缓存统计
        assert order_manager._cache_hits == 1
        assert order_manager._cache_misses == 0

    @pytest.mark.asyncio
    async def test_multiple_status_updates_in_cache(self, order_manager):
        """
        测试：同一订单的多个状态更新（PARTIALLY_FILLED → FILLED）

        场景：
        1. 订单部分成交（PARTIALLY_FILLED）
        2. 订单完全成交（FILLED）
        3. 验证按时间戳顺序应用更新
        4. 验证最终的filled_quantity反映完全成交数量
        """
        order_id = "2008773271629754368"

        # 1. 部分成交更新
        partial_data = {
            'order_id': order_id,
            'status': 'PARTIALLY_FILLED',
            'side': 'buy',
            'order_type': 'OPEN',
            'size': '0.01',
            'price': '3251.4',
            'contract_id': 'ETH-USD',
            'filled_size': '0.005'
        }
        order_manager.update_order_status(partial_data)
        time.sleep(0.01)  # 确保时间戳不同

        # 2. 完全成交更新
        filled_data = {
            'order_id': order_id,
            'status': 'FILLED',
            'side': 'buy',
            'order_type': 'OPEN',
            'size': '0.01',
            'price': '3251.5',
            'contract_id': 'ETH-USD',
            'filled_size': '0.010'
        }
        order_manager.update_order_status(filled_data)

        # 3. 验证两个更新都被缓存
        assert len(order_manager._pending_updates[order_id]) == 2

        # 4. 设置order_id并应用缓存
        order_manager.current_order_id = order_id
        await order_manager._apply_pending_updates(order_id)

        # 5. 验证最终状态是FILLED
        assert order_manager.current_order_status == 'FILLED'

        # 6. 验证最终filled_quantity是完全成交数量
        assert order_manager.filled_quantity == Decimal('0.010')

        # 7. 验证价格是最后更新的价格
        assert order_manager.filled_price == Decimal('3251.5')


class TestConcurrentUpdates:
    """测试并发更新处理（用户故事2）"""

    @pytest.mark.asyncio
    async def test_concurrent_updates_same_order(self, order_manager):
        """
        测试：同一订单的多个并发更新

        场景：
        1. 快速连续发送多个状态更新
        2. 验证所有更新都被缓存和应用
        3. 验证最终状态正确
        """
        order_id = "2008773271629754368"

        # 快速连续发送更新
        updates = [
            {
                'order_id': order_id,
                'status': 'OPEN',
                'order_type': 'OPEN',
                'filled_size': '0.000'
            },
            {
                'order_id': order_id,
                'status': 'PARTIALLY_FILLED',
                'order_type': 'OPEN',
                'filled_size': '0.005'
            },
            {
                'order_id': order_id,
                'status': 'FILLED',
                'order_type': 'OPEN',
                'filled_size': '0.010'
            }
        ]

        # 模拟并发更新（虽然update_order_status是同步的）
        for update in updates:
            order_manager.update_order_status(update)

        # 验证所有更新都被缓存
        assert len(order_manager._pending_updates[order_id]) == 3

        # 应用缓存
        order_manager.current_order_id = order_id
        await order_manager._apply_pending_updates(order_id)

        # 验证最终状态正确
        assert order_manager.current_order_status == 'FILLED'
        assert order_manager.filled_quantity == Decimal('0.010')

    @pytest.mark.asyncio
    async def test_multiple_orders_concurrent_updates(self, order_manager):
        """
        测试：多个不同订单的同时更新

        场景：
        1. 多个订单同时存在
        2. 验证每个订单的状态独立跟踪
        3. 验证缓存不会相互干扰
        """
        order1_id = "2008773271629754368"
        order2_id = "2008773321807298560"

        # 订单1的更新
        order1_update = {
            'order_id': order1_id,
            'status': 'FILLED',
            'order_type': 'OPEN',
            'filled_size': '0.010'
        }

        # 订单2的更新
        order2_update = {
            'order_id': order2_id,
            'status': 'FILLED',
            'order_type': 'OPEN',
            'filled_size': '0.015'
        }

        # 两个订单的更新都到达（current_order_id都是None）
        order_manager.update_order_status(order1_update)
        order_manager.update_order_status(order2_update)

        # 验证两个订单的更新都被独立缓存
        assert order1_id in order_manager._pending_updates
        assert order2_id in order_manager._pending_updates
        assert len(order_manager._pending_updates) == 2

        # 应用订单1的缓存
        order_manager.current_order_id = order1_id
        await order_manager._apply_pending_updates(order1_id)

        # 验证订单1的状态正确
        assert order_manager.current_order_status == 'FILLED'
        assert order_manager.filled_quantity == Decimal('0.010')

        # 验证订单2的缓存还在
        assert order2_id in order_manager._pending_updates


class TestCacheCleanup:
    """测试缓存清理机制"""

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, order_manager):
        """测试：TTL过期清理"""
        order_id = "2008773271629754368"

        # 添加一个更新并手动设置旧时间戳
        order_manager._pending_updates[order_id] = [{
            'order_data': {
                'order_id': order_id,
                'status': 'FILLED',
                'order_type': 'OPEN',
                'filled_size': '0.010'
            },
            'timestamp': time.time() - 400  # 400秒前（超过300秒TTL）
        }]

        # 执行清理
        await order_manager._cleanup_cache()

        # 验证缓存被清理
        assert order_id not in order_manager._pending_updates

    @pytest.mark.asyncio
    async def test_cache_max_size_limit(self, order_manager):
        """测试：最大缓存限制"""
        # 设置较小的限制进行测试
        order_manager._max_cache_size = 5

        # 添加6个订单的缓存
        for i in range(6):
            order_id = f"order_{i}"
            order_manager._pending_updates[order_id] = [{
                'order_data': {
                    'order_id': order_id,
                    'status': 'OPEN',
                    'order_type': 'OPEN'
                },
                'timestamp': time.time() - i  # 不同的时间戳
            }]

        # 执行清理
        await order_manager._cleanup_cache()

        # 验证缓存被限制在最大值
        assert len(order_manager._pending_updates) <= 5

    @pytest.mark.asyncio
    async def test_completed_order_cleanup(self, order_manager):
        """测试：已完成订单的缓存清理"""
        order_id = "2008773271629754368"

        # 添加已完成订单的缓存
        order_manager._pending_updates[order_id] = [{
            'order_data': {
                'order_id': order_id,
                'status': 'FILLED',  # 已完成
                'order_type': 'OPEN'
            },
            'timestamp': time.time()
        }]

        # 执行清理
        await order_manager._cleanup_cache()

        # 验证已完成订单的缓存被清理
        assert order_id not in order_manager._pending_updates


class TestCacheMaxUpdatesPerOrder:
    """测试每订单最大更新数限制"""

    def test_max_updates_per_order_limit(self, order_manager):
        """测试：每订单最大更新数限制"""
        order_id = "2008773271629754368"

        # 设置较小的限制进行测试
        order_manager._max_updates_per_order = 3

        # 添加5个更新
        for i in range(5):
            order_manager._add_pending_update(order_id, {
                'order_id': order_id,
                'status': f'STATUS_{i}',
                'order_type': 'OPEN'
            })

        # 验证只保留最新的3个更新
        assert len(order_manager._pending_updates[order_id]) == 3

        # 验证保留的是最新的更新
        statuses = [u['order_data']['status'] for u in order_manager._pending_updates[order_id]]
        assert statuses == ['STATUS_2', 'STATUS_3', 'STATUS_4']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
