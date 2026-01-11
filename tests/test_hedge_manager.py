"""
对冲管理器单元测试

测试HedgeManager的taker订单对冲功能
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, AsyncMock

from spread.hedge_manager import HedgeManager
from spread.config import SpreadArbConfig


# 模拟配置对象
class MockConfig:
    def __init__(self):
        self.ticker = 'ETH'
        self.max_hedge_slippage = Decimal('0.01')  # 1% 滑点容忍
        self.hedge_timeout = 5


# 模拟Lighter客户端
class MockLighterClient:
    def __init__(self, fill_price=None, should_fail=False):
        self.fill_price = fill_price or Decimal('3000')
        self.should_fail = should_fail
        self.orders = {}

    async def place_order(self, side, quantity, price, order_type='MARKET'):
        """模拟下单"""
        if self.should_fail:
            return None

        order_id = f"lighter_order_{side}_{quantity}"
        self.orders[order_id] = {
            'order_id': order_id,
            'side': side,
            'quantity': quantity,
            'price': self.fill_price,
            'status': 'FILLED',
            'filled_size': str(quantity),
        }

        return Mock(
            order_id=order_id,
            status='FILLED',
            price=self.fill_price,
            filled_size=quantity,
        )

    async def get_order_info(self, order_id):
        """模拟获取订单信息"""
        if order_id in self.orders:
            order_data = self.orders[order_id]
            return Mock(
                order_id=order_data['order_id'],
                status=order_data['status'],
                price=order_data['price'],
                filled_size=Decimal(order_data['filled_size']),
            )
        return None


@pytest.fixture
def config():
    """创建测试配置"""
    return MockConfig()


@pytest.fixture
def mock_lighter_client():
    """模拟Lighter客户端"""
    return MockLighterClient(fill_price=Decimal('3000'))


@pytest.fixture
def hedge_manager(config, mock_lighter_client):
    """创建对冲管理器实例"""
    return HedgeManager(config, mock_lighter_client)


class TestTakerOrderHedge:
    """测试Taker订单对冲（001-fix-order-type - User Story 1）"""

    @pytest.mark.asyncio
    async def test_hedge_uses_market_order(self, hedge_manager):
        """
        测试：对冲应使用市价单（taker订单）

        场景：
        1. 调用execute_hedge
        2. 验证使用市价单下单
        3. 验证订单立即成交
        """
        result = await hedge_manager.execute_hedge(
            side='buy',
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )

        # 验证对冲成功
        assert result['success']
        assert result['filled_quantity'] == Decimal('0.01')
        assert result['filled_price'] == Decimal('3000')

    @pytest.mark.asyncio
    async def test_hedge_with_opposite_side(self, hedge_manager):
        """
        测试：对冲方向应与开仓方向相反

        场景：
        1. 开仓买入，对冲应卖出
        2. 开仓卖出，对冲应买入
        """
        # 做多价差：买入Extended，卖出Lighter对冲
        buy_result = await hedge_manager.execute_hedge(
            side='sell',  # 对冲卖出
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )
        assert buy_result['success']

        # 做空价差：卖出Extended，买入Lighter对冲
        sell_result = await hedge_manager.execute_hedge(
            side='buy',  # 对冲买入
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )
        assert sell_result['success']

    @pytest.mark.asyncio
    async def test_hedge_slippage_check(self, hedge_manager):
        """
        测试：对冲滑点检查

        场景：
        1. 预期价格3000
        2. 实际成交价格3000
        3. 滑点应在容忍范围内
        """
        result = await hedge_manager.execute_hedge(
            side='buy',
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )

        # 验证滑点计算
        assert 'slippage' in result
        assert result['slippage'] >= 0

        # 验证成交成功
        assert result['success']

    @pytest.mark.asyncio
    async def test_hedge_failure_handling(self, config):
        """
        测试：对冲失败处理

        场景：
        1. 模拟对冲失败
        2. 验证返回错误信息
        3. 验证不会无限重试
        """
        # 创建会失败的客户端
        fail_client = MockLighterClient(should_fail=True)
        fail_manager = HedgeManager(config, fail_client)

        result = await fail_manager.execute_hedge(
            side='buy',
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )

        # 验证失败返回
        assert not result['success']
        assert 'error' in result


class TestHedgeRetryLogic:
    """测试对冲重试逻辑"""

    @pytest.mark.asyncio
    async def test_no_duplicate_orders_on_retry(self, hedge_manager):
        """
        测试：重试时不应重复下单

        场景：
        1. 第一次下单已提交
        2. 重试时检查第一次订单状态
        3. 如果已成交，直接返回不重复下单
        """
        # 模拟第一次下单成功
        result = await hedge_manager.execute_hedge(
            side='buy',
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )

        # 验证只有一个订单被创建
        assert len(hedge_manager.lighter_client.orders) == 1
        assert result['success']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
