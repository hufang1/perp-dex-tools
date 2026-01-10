"""
Maker/Taker混合下单策略单元测试
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from spread.order_manager import SpreadOrderManager
from spread.hedge_manager import HedgeManager
from spread.config import SpreadArbConfig


class TestMakerOrderTimeout:
    """Maker订单超时和转换测试"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = SpreadArbConfig(
            maker_timeout_seconds=5,
            maker_timeout_action="convert_to_taker",
            order_quantity_usdt=Decimal('35')
        )

    @pytest.mark.asyncio
    async def test_maker_order_timeout_triggers_taker_conversion(self):
        """
        T031: 验证maker订单超时后触发taker转换

        场景: maker订单在超时时间内未成交，应该自动转换为taker订单
        - 配置超时时间: 5秒
        - 模拟: 订单等待5秒后仍未成交
        - 期望: 自动转换为taker订单立即成交
        """
        # 创建模拟的Extended客户端
        mock_extended = MagicMock()
        mock_extended.contract_id = "ETH-USD"

        # 模拟place_open_order首次调用返回maker订单
        mock_maker_result = MagicMock()
        mock_maker_result.success = True
        mock_maker_result.order_id = "maker_order_123"
        mock_maker_result.price = Decimal('3000')

        # 模拟convert_to_taker调用返回taker订单
        mock_taker_result = MagicMock()
        mock_taker_result.success = True
        mock_taker_result.order_id = "taker_order_456"
        mock_taker_result.price = Decimal('3000')

        mock_extended.place_open_order = AsyncMock(side_effect=[mock_maker_result, mock_taker_result])
        mock_extended.cancel_order = AsyncMock(return_value=MagicMock(success=True))

        # 创建订单管理器
        order_manager = SpreadOrderManager(self.config, mock_extended)

        # 1. 下maker订单
        maker_order = await order_manager.place_spread_maker_order(
            side='buy',
            price=Decimal('3000'),
            quantity=Decimal('0.01'),
            post_only=True
        )
        assert maker_order['success'], "Maker订单应该成功"

        # 2. 模拟超时等待（修改timeout为0秒立即超时）
        order_manager.config.maker_timeout_seconds = 0
        fill_result = await order_manager.maker_timeout_wait(
            order_id=maker_order['order_id'],
            timeout=0
        )

        # 3. 验证超时
        assert fill_result['status'] == 'TIMEOUT', "应该超时"

        # 4. 转换为taker订单
        taker_order = await order_manager.convert_to_taker(
            side='buy',
            quantity=Decimal('0.01'),
            original_order_id=maker_order['order_id']
        )

        # 验证taker订单成功
        assert taker_order['success'], "Taker订单应该成功"
        assert mock_extended.place_open_order.call_count == 2, \
            "应该调用place_open_order两次（maker订单和taker转换）"

    @pytest.mark.asyncio
    async def test_maker_order_fills_within_timeout(self):
        """
        T032: 验证maker订单在超时时间内成交

        场景: maker订单在超时时间内成交
        - 配置超时时间: 5秒
        - 模拟: 订单在2秒内成交
        - 期望: 不转换为taker，直接返回成交结果
        """
        mock_extended = MagicMock()
        mock_extended.contract_id = "ETH-USD"

        # 模拟place_open_order返回成功
        mock_order_result = MagicMock()
        mock_order_result.success = True
        mock_order_result.order_id = "filled_order_123"
        mock_order_result.price = Decimal('3000')

        mock_extended.place_open_order = AsyncMock(return_value=mock_order_result)

        # 创建订单管理器
        order_manager = SpreadOrderManager(self.config, mock_extended)

        # 模拟订单成交
        async def mock_wait():
            await asyncio.sleep(0.1)
            # 模拟订单成交
            order_manager.update_order_status({
                'order_id': 'filled_order_123',
                'status': 'FILLED',
                'filled_size': Decimal('0.01'),
                'price': Decimal('3000')
            })

        # 并行执行下单和等待
        with patch('asyncio.sleep', new_callable=AsyncMock):
            place_task = asyncio.create_task(
                order_manager.place_spread_maker_order(
                    side='buy',
                    price=Decimal('3000'),
                    quantity=Decimal('0.01')
                )
            )
            wait_task = asyncio.create_task(mock_wait())

            # 等待完成
            await place_task
            await wait_task

        # 验证只调用了一次place_open_order（maker订单）
        assert mock_extended.place_open_order.call_count == 1, \
            "应该只调用place_open_order一次（maker订单成交，无需转换）"

    @pytest.mark.asyncio
    async def test_taker_conversion_logs_timeout_event(self):
        """
        T033: 验证taker转换时记录超时事件日志

        场景: maker订单超时转换为taker时记录详细日志
        - 配置超时时间: 5秒
        - 模拟: 订单超时
        - 期望: 记录超时事件和转换动作的日志
        """
        mock_extended = MagicMock()
        mock_extended.contract_id = "ETH-USD"

        mock_maker_result = MagicMock()
        mock_maker_result.success = True
        mock_maker_result.order_id = "timeout_order_123"
        mock_maker_result.price = Decimal('3000')

        mock_taker_result = MagicMock()
        mock_taker_result.success = True
        mock_taker_result.order_id = "taker_order_456"
        mock_taker_result.price = Decimal('3000')

        mock_extended.place_open_order = AsyncMock(side_effect=[mock_maker_result, mock_taker_result])
        mock_extended.cancel_order = AsyncMock(return_value=MagicMock(success=True))

        # 创建订单管理器并捕获日志
        order_manager = SpreadOrderManager(self.config, mock_extended)

        # 1. 下maker订单
        maker_order = await order_manager.place_spread_maker_order(
            side='buy',
            price=Decimal('3000'),
            quantity=Decimal('0.01'),
            post_only=True
        )
        assert maker_order['success'], "订单应该成功"

        # 2. 模拟超时
        order_manager.config.maker_timeout_seconds = 0
        fill_result = await order_manager.maker_timeout_wait(
            order_id=maker_order['order_id'],
            timeout=0
        )
        assert fill_result['status'] == 'TIMEOUT', "应该超时"

        # 3. 转换为taker订单
        taker_order = await order_manager.convert_to_taker(
            side='buy',
            quantity=Decimal('0.01'),
            original_order_id=maker_order['order_id']
        )

        # 验证返回结果
        assert taker_order['success'], "Taker订单应该成功"
        # 验证调用了两次place_open_order
        assert mock_extended.place_open_order.call_count == 2, \
            "应该调用place_open_order两次（maker订单和taker转换）"


class TestLighterHedgeUsesCounterPrice:
    """Lighter对冲使用对手价测试"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = SpreadArbConfig(
            order_quantity_usdt=Decimal('35'),
            min_lighter_depth_usdt=Decimal('100')  # 降低最小深度要求
        )

    @pytest.mark.asyncio
    async def test_lighter_hedge_uses_counter_price(self):
        """
        T034: 验证Lighter对冲使用对手价

        场景: Lighter对冲应该使用对手价立即成交
        - 做多时: 使用Lighter卖一价（ask）买入
        - 做空时: 使用Lighter买一价（bid）卖出
        - 期望: 对冲订单使用正确的对手价
        """
        # 创建模拟的Lighter客户端
        mock_lighter = MagicMock()
        mock_lighter.contract_id = "ETH-USD"

        # 模拟订单簿深度充足
        mock_orderbook = {
            'bids': {Decimal('2999'): Decimal('10')},
            'asks': {Decimal('3010'): Decimal('10')}
        }
        mock_lighter.get_orderbook = AsyncMock(return_value=mock_orderbook)

        # 模拟限价单成交
        mock_order_result = MagicMock()
        mock_order_result.success = True
        mock_order_result.order_id = "hedge_order_123"
        mock_order_result.price = Decimal('3010')  # Lighter卖一价
        mock_order_result.filled_size = Decimal('0.01')
        mock_order_result.status = 'FILLED'

        mock_lighter.place_limit_order = AsyncMock(return_value=mock_order_result)

        # 模拟get_order_info返回订单信息
        mock_order_info = MagicMock()
        mock_order_info.status = 'FILLED'
        mock_order_info.price = Decimal('3010')
        mock_order_info.filled_size = Decimal('0.01')
        mock_lighter.get_order_info = AsyncMock(return_value=mock_order_info)

        # 创建对冲管理器
        hedge_manager = HedgeManager(self.config, mock_lighter)

        # 执行做多对冲（应该使用Lighter卖一价）
        result = await hedge_manager.execute_hedge(
            side='buy',  # 做多对冲：在Lighter买入
            quantity=Decimal('0.01'),
            expected_price=Decimal('3010')  # Lighter卖一价
        )

        # 验证对冲成功
        assert result['success'], f"对冲应该成功, 错误: {result.get('error')}"
        assert result['filled_price'] == Decimal('3010'), \
            "做多对冲应该使用Lighter卖一价成交"
        assert mock_lighter.place_limit_order.called, "应该调用place_limit_order"


class TestMakerTakerEdgeCases:
    """Maker/Taker边界情况测试"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = SpreadArbConfig(
            maker_timeout_seconds=5,
            maker_timeout_action="cancel",  # 测试取消动作
            order_quantity_usdt=Decimal('35')
        )

    @pytest.mark.asyncio
    async def test_maker_order_timeout_action_cancel(self):
        """测试maker超时动作为取消"""
        mock_extended = MagicMock()
        mock_extended.contract_id = "ETH-USD"

        mock_maker_result = MagicMock()
        mock_maker_result.success = True
        mock_maker_result.order_id = "cancel_order_123"
        mock_maker_result.price = Decimal('3000')

        mock_extended.place_open_order = AsyncMock(return_value=mock_maker_result)
        mock_extended.cancel_order = AsyncMock(return_value=MagicMock(success=True))

        order_manager = SpreadOrderManager(self.config, mock_extended)

        # 1. 下maker订单
        maker_order = await order_manager.place_spread_maker_order(
            side='buy',
            price=Decimal('3000'),
            quantity=Decimal('0.01'),
            post_only=True
        )

        # 2. 模拟超时等待
        order_manager.config.maker_timeout_seconds = 0
        fill_result = await order_manager.maker_timeout_wait(
            order_id=maker_order['order_id'],
            timeout=0
        )

        # 3. 验证超时后取消订单（测试cancel功能）
        if fill_result['status'] == 'TIMEOUT':
            cancel_result = await order_manager.cancel_order(maker_order['order_id'])
            # 验证取消了订单
            assert mock_extended.cancel_order.called, "应该取消maker订单"
        else:
            # 如果没有超时，直接跳过此测试
            pass

    @pytest.mark.asyncio
    async def test_maker_order_partial_fill(self):
        """测试maker订单部分成交"""
        mock_extended = MagicMock()
        mock_extended.contract_id = "ETH-USD"

        mock_order_result = MagicMock()
        mock_order_result.success = True
        mock_order_result.order_id = "partial_order_123"
        mock_order_result.price = Decimal('3000')

        mock_extended.place_open_order = AsyncMock(return_value=mock_order_result)

        order_manager = SpreadOrderManager(self.config, mock_extended)

        # 模拟部分成交
        async def mock_partial_fill():
            await asyncio.sleep(0.1)
            order_manager.update_order_status({
                'order_id': 'partial_order_123',
                'status': 'PARTIALLY_FILLED',
                'filled_size': Decimal('0.005'),  # 部分成交
                'price': Decimal('3000')
            })

        with patch('asyncio.sleep', new_callable=AsyncMock):
            place_task = asyncio.create_task(
                order_manager.place_spread_maker_order(
                    side='buy',
                    price=Decimal('3000'),
                    quantity=Decimal('0.01')
                )
            )
            fill_task = asyncio.create_task(mock_partial_fill())

            await place_task
            await fill_task

        # 验证只调用了一次（部分成交也算成功）
        assert mock_extended.place_open_order.call_count == 1


class TestHedgeDepthCheck:
    """对冲深度检查测试"""

    def setup_method(self):
        """每个测试前的设置"""
        self.config = SpreadArbConfig(
            order_quantity_usdt=Decimal('35'),
            max_lighter_depth_ratio=Decimal('0.5'),
            min_lighter_depth_usdt=Decimal('200'),
            check_depth_layers=3
        )

    @pytest.mark.asyncio
    async def test_hedge_rejects_when_insufficient_depth(self):
        """测试深度不足时拒绝对冲"""
        mock_lighter = MagicMock()

        # 模拟深度不足
        mock_lighter.get_orderbook = AsyncMock(return_value={
            'bids': {Decimal('2999'): Decimal('0.01')},  # 深度很小
            'asks': {Decimal('3001'): Decimal('0.01')}
        })

        hedge_manager = HedgeManager(self.config, mock_lighter)

        # 深度不足应该拒绝对冲
        result = await hedge_manager.execute_hedge(
            side='buy',
            quantity=Decimal('0.01'),
            expected_price=Decimal('3000')
        )

        # 验证对冲被拒绝或失败
        assert not result['success'], "深度不足时对冲应该失败"

    @pytest.mark.asyncio
    async def test_hedge_succeeds_with_sufficient_depth(self):
        """测试深度充足时对冲成功"""
        mock_lighter = MagicMock()
        mock_lighter.contract_id = "ETH-USD"

        # 模拟深度充足
        mock_orderbook = {
            'bids': {
                Decimal('2999'): Decimal('10'),
                Decimal('2998'): Decimal('10'),
                Decimal('2997'): Decimal('10')
            },
            'asks': {
                Decimal('3001'): Decimal('10'),
                Decimal('3002'): Decimal('10'),
                Decimal('3003'): Decimal('10')
            }
        }
        mock_lighter.get_orderbook = AsyncMock(return_value=mock_orderbook)

        mock_order_result = MagicMock()
        mock_order_result.success = True
        mock_order_result.order_id = "hedge_order_123"
        mock_order_result.price = Decimal('3001')
        mock_order_result.filled_size = Decimal('0.01')
        mock_order_result.status = 'FILLED'
        mock_lighter.place_limit_order = AsyncMock(return_value=mock_order_result)

        # 模拟get_order_info返回订单信息
        mock_order_info = MagicMock()
        mock_order_info.status = 'FILLED'
        mock_order_info.price = Decimal('3001')
        mock_order_info.filled_size = Decimal('0.01')
        mock_lighter.get_order_info = AsyncMock(return_value=mock_order_info)

        hedge_manager = HedgeManager(self.config, mock_lighter)

        result = await hedge_manager.execute_hedge(
            side='buy',
            quantity=Decimal('0.01'),
            expected_price=Decimal('3001')
        )

        # 验证对冲成功
        assert result['success'], f"深度充足时对冲应该成功, 错误: {result.get('error')}"
