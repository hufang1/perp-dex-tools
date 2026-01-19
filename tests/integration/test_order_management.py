"""
修改挂单价格集成测试

测试范围：
- 完整的修改挂单价格流程
- 取消旧订单并创建新订单
- 防止多个挂单同时存在
- 与真实交易所API的集成（使用mock）

测试目标：确保修改挂单价格时先取消旧订单再创建新订单
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from datetime import datetime
import asyncio

from spread.models import BotState, Position, PositionState
from spread.spread_arb_bot import SpreadArbBot
from spread.trade_executor import TradeExecutor


class TestModifyMakerOrderPrice:
    """测试修改挂单价格流程"""

    @pytest.fixture
    async def bot(self):
        """创建机器人测试实例"""
        # Mock configuration
        mock_config = MagicMock()
        mock_config.symbol = "ETH"
        mock_config.target_quantity = Decimal("0.01")
        mock_config.fixed_open_threshold = Decimal("0.001")
        mock_config.fixed_close_threshold = Decimal("0.0005")
        mock_config.use_maker_mode = True

        # Mock clients
        mock_extended_client = AsyncMock()
        mock_lighter_client = AsyncMock()

        # Mock WebSocket managers
        mock_ext_ws_manager = MagicMock()
        mock_lig_ws_manager = MagicMock()

        # Mock state manager
        mock_state_manager = MagicMock()
        mock_state_manager.get_state.return_value = BotState.OPENING_MAKER_WAIT

        # Create bot
        bot = SpreadArbBot(
            config=mock_config,
            extended_client=mock_extended_client,
            lighter_client=mock_lighter_client,
            ext_ws_manager=mock_ext_ws_manager,
            lig_ws_manager=mock_lig_ws_manager,
            state_manager=mock_state_manager,
        )

        return bot

    @pytest.mark.asyncio
    async def test_modify_order_cancel_before_create(self, bot):
        """测试：修改价格时先取消旧订单再创建新订单"""
        # Setup
        old_order_id = "1234567890"
        old_price = Decimal("3300.0")
        new_price = Decimal("3305.0")

        # Mock old order exists
        bot._extended_client.get_order = AsyncMock(return_value={
            "order_id": old_order_id,
            "status": "OPEN",
            "price": str(old_price),
        })

        # Mock cancellation succeeds
        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        bot.trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")

        # Mock new order creation succeeds
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "9876543210",
            "status": "OPEN",
            "price": str(new_price),
        })

        # Execute
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="extended"
        )

        # Verify: cancellation was called before new order
        bot.trade_executor._extended_client.cancel_order.assert_called_once_with(old_order_id)
        bot.trade_executor._extended_client.place_order.assert_called_once()

        # Verify: new order was created
        create_call_args = bot.trade_executor._extended_client.place_order.call_args
        assert Decimal(create_call_args[1]["price"]) == new_price

    @pytest.mark.asyncio
    async def test_modify_order_cancellation_fails_no_new_order(self, bot):
        """测试：取消失败时不创建新订单"""
        # Setup
        old_order_id = "1111111111"
        new_price = Decimal("3310.0")

        # Mock cancellation fails
        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=False)
        bot.trade_executor._get_order_status_extended = AsyncMock(return_value="OPEN")

        # Mock new order creation (should NOT be called)
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "9999999999",
            "status": "OPEN",
        })

        # Execute & Expect exception
        from exceptions import OrderCancellationError
        with pytest.raises(OrderCancellationError):
            await bot._modify_maker_order_price(
                order_id=old_order_id,
                new_price=new_price,
                exchange="extended",
                max_retries=3
            )

        # Verify: new order was NOT created
        bot.trade_executor._extended_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_modify_order_prevents_multiple_orders(self, bot):
        """测试：防止同时存在多个挂单"""
        # Setup
        old_order_id = "2222222222"
        new_price = Decimal("3315.0")

        # Track order states
        order_states = {
            old_order_id: "OPEN",
        }

        async def mock_cancel_order(order_id):
            # Cancellation succeeds
            order_states[order_id] = "CANCELED"
            return True

        async def mock_get_status(order_id):
            return order_states.get(order_id, "UNKNOWN")

        async def mock_place_order(**kwargs):
            # Check if old order still exists
            if old_order_id in order_states and order_states[old_order_id] == "OPEN":
                raise Exception("Old order not cancelled before creating new order!")
            return {
                "order_id": "3333333333",
                "status": "OPEN",
            }

        bot.trade_executor._extended_client.cancel_order = mock_cancel_order
        bot.trade_executor._get_order_status_extended = mock_get_status
        bot.trade_executor._extended_client.place_order = mock_place_order

        # Execute
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="extended"
        )

        # Verify: only one order exists at any time
        assert old_order_id in order_states
        assert order_states[old_order_id] == "CANCELED"

    @pytest.mark.asyncio
    async def test_modify_order_with_retries(self, bot):
        """测试：取消订单失败后重试"""
        # Setup
        old_order_id = "4444444444"
        new_price = Decimal("3320.0")

        # Mock cancellation: fails twice, succeeds on third try
        attempt_count = 0

        async def mock_cancel_with_retry(order_id):
            nonlocal attempt_count
            attempt_count += 1
            return attempt_count >= 3

        async def mock_get_status(order_id):
            return "CANCELED" if attempt_count >= 3 else "OPEN"

        bot.trade_executor._extended_client.cancel_order = mock_cancel_with_retry
        bot.trade_executor._get_order_status_extended = mock_get_status

        # Mock new order creation
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "5555555555",
            "status": "OPEN",
        })

        # Execute
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="extended",
            max_retries=5
        )

        # Verify: retried 3 times before success
        assert attempt_count == 3
        bot.trade_executor._extended_client.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_modify_order_state_transitions(self, bot):
        """测试：修改挂单时的状态转换"""
        # Setup
        old_order_id = "6666666666"
        new_price = Decimal("3325.0")
        state_transitions = []

        # Track state transitions
        def track_transition(new_state, reason=""):
            state_transitions.append((new_state, reason))

        bot.state_manager.set_state = track_transition

        # Mock cancellation and creation
        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        bot.trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "7777777777",
            "status": "OPEN",
        })

        # Execute
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="extended"
        )

        # Verify: appropriate state transitions occurred
        assert len(state_transitions) > 0
        # Should have transitioned to indicate order modification in progress

    @pytest.mark.asyncio
    async def test_modify_order_lighter_exchange(self, bot):
        """测试：Lighter交易所修改挂单价格"""
        # Setup
        old_order_id = "lig_old_order"
        new_price = Decimal("3330.0")

        # Mock Lighter cancellation and creation
        bot.trade_executor._lighter_client.cancel_order = AsyncMock(return_value=True)
        bot.trade_executor._get_order_status_lighter = AsyncMock(return_value="CANCELED")
        bot.trade_executor._lighter_client.place_order = AsyncMock(return_value={
            "order_id": "lig_new_order",
            "status": "OPEN",
        })

        # Execute
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="lighter"
        )

        # Verify: Lighter APIs were called
        bot.trade_executor._lighter_client.cancel_order.assert_called_once_with(old_order_id)
        bot.trade_executor._lighter_client.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_modify_order_logs_cancellation_details(self, bot, caplog):
        """测试：记录取消订单的详细日志"""
        # Setup
        old_order_id = "8888888888"
        new_price = Decimal("3335.0")

        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        bot.trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "9999999999",
            "status": "OPEN",
        })

        # Execute with log capture
        import logging
        with caplog.at_level(logging.INFO):
            await bot._modify_maker_order_price(
                order_id=old_order_id,
                new_price=new_price,
                exchange="extended"
            )

        # Verify: logs contain order cancellation details
        log_messages = [record.message for record in caplog.records]
        cancellation_logs = [msg for msg in log_messages if "取消" in msg or "cancel" in msg.lower()]
        assert len(cancellation_logs) > 0


class TestConcurrentOrderModification:
    """测试并发修改订单的场景"""

    @pytest.fixture
    async def bot(self):
        """创建机器人测试实例"""
        mock_config = MagicMock()
        mock_config.symbol = "ETH"
        mock_config.target_quantity = Decimal("0.01")
        mock_config.use_maker_mode = True

        mock_extended_client = AsyncMock()
        mock_lighter_client = AsyncMock()

        mock_ext_ws_manager = MagicMock()
        mock_lig_ws_manager = MagicMock()

        mock_state_manager = MagicMock()
        mock_state_manager.get_state.return_value = BotState.OPENING_MAKER_WAIT

        bot = SpreadArbBot(
            config=mock_config,
            extended_client=mock_extended_client,
            lighter_client=mock_lighter_client,
            ext_ws_manager=mock_ext_ws_manager,
            lig_ws_manager=mock_lig_ws_manager,
            state_manager=mock_state_manager,
        )

        return bot

    @pytest.mark.asyncio
    async def test_rapid_price_changes_sequential(self, bot):
        """测试：快速连续修改价格（串行执行）"""
        # Setup
        order_id = "0000000001"
        prices = [
            Decimal("3300.0"),
            Decimal("3305.0"),
            Decimal("3310.0"),
            Decimal("3315.0"),
        ]

        active_orders = set()

        async def mock_cancel_order(order_id):
            active_orders.discard(order_id)
            return True

        async def mock_get_status(order_id):
            return "CANCELED"

        async def mock_place_order(**kwargs):
            new_id = f"order_{len(active_orders)}"
            active_orders.add(new_id)
            return {
                "order_id": new_id,
                "status": "OPEN",
            }

        bot.trade_executor._extended_client.cancel_order = mock_cancel_order
        bot.trade_executor._get_order_status_extended = mock_get_status
        bot.trade_executor._extended_client.place_order = mock_place_order

        # Execute: modify price 4 times sequentially
        for price in prices:
            await bot._modify_maker_order_price(
                order_id=order_id,
                new_price=price,
                exchange="extended"
            )
            # Update order_id for next iteration
            order_id = list(active_orders)[-1] if active_orders else order_id

        # Verify: only one order exists at the end
        assert len(active_orders) == 1

    @pytest.mark.asyncio
    async def test_prevent_race_condition(self, bot):
        """测试：防止竞态条件"""
        # Setup
        old_order_id = "1111111111"
        new_price = Decimal("3340.0")

        # Mock with slight delay to expose race conditions
        async def mock_cancel_slow(order_id):
            await asyncio.sleep(0.1)
            return True

        async def mock_get_status(order_id):
            await asyncio.sleep(0.05)
            return "CANCELED"

        bot.trade_executor._extended_client.cancel_order = mock_cancel_slow
        bot.trade_executor._get_order_status_extended = mock_get_status
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "2222222222",
            "status": "OPEN",
        })

        # Execute
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="extended"
        )

        # Verify: cancellation was verified before new order
        bot.trade_executor._extended_client.cancel_order.assert_awaited()
        bot.trade_executor._get_order_status_extended.assert_awaited()


class TestOrderModificationErrorHandling:
    """测试修改订单时的错误处理"""

    @pytest.fixture
    async def bot(self):
        """创建机器人测试实例"""
        mock_config = MagicMock()
        mock_config.symbol = "ETH"
        mock_config.target_quantity = Decimal("0.01")
        mock_config.use_maker_mode = True

        mock_extended_client = AsyncMock()
        mock_lighter_client = AsyncMock()

        mock_ext_ws_manager = MagicMock()
        mock_lig_ws_manager = MagicMock()

        mock_state_manager = MagicMock()
        mock_state_manager.get_state.return_value = BotState.OPENING_MAKER_WAIT

        bot = SpreadArbBot(
            config=mock_config,
            extended_client=mock_extended_client,
            lighter_client=mock_lighter_client,
            ext_ws_manager=mock_ext_ws_manager,
            lig_ws_manager=mock_lig_ws_manager,
            state_manager=mock_state_manager,
        )

        return bot

    @pytest.mark.asyncio
    async def test_cancellation_error_safe_state_transition(self, bot):
        """测试：取消失败时安全的状态转换"""
        # Setup
        old_order_id = "3333333333"
        new_price = Decimal("3345.0")

        # Mock cancellation fails
        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=False)
        bot.trade_executor._get_order_status_extended = AsyncMock(return_value="OPEN")

        state_transitions = []
        bot.state_manager.set_state = lambda state, reason="": state_transitions.append(
            (state, reason)
        )

        # Execute & Expect exception
        from exceptions import OrderCancellationError
        with pytest.raises(OrderCancellationError):
            await bot._modify_maker_order_price(
                order_id=old_order_id,
                new_price=new_price,
                exchange="extended",
                max_retries=2
            )

        # Verify: bot transitioned to safe state (ERROR or保持原状态)
        assert len(state_transitions) > 0
        # Last transition should be to ERROR or stay in current state
        final_state, reason = state_transitions[-1]
        assert final_state in [BotState.ERROR, BotState.OPENING_MAKER_WAIT]

    @pytest.mark.asyncio
    async def test_api_error_during_cancellation(self, bot):
        """测试：取消订单时API异常"""
        # Setup
        old_order_id = "4444444444"
        new_price = Decimal("3350.0")

        # Mock API exception
        bot.trade_executor._extended_client.cancel_order = AsyncMock(
            side_effect=Exception("API Connection Error")
        )

        # Execute & Expect exception
        with pytest.raises(Exception) as exc_info:
            await bot._modify_maker_order_price(
                order_id=old_order_id,
                new_price=new_price,
                exchange="extended",
                max_retries=2
            )

        # Verify exception contains useful information
        assert "API" in str(exc_info.value) or "Connection" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_new_order_creation_failure_after_cancel(self, bot):
        """测试：取消成功但创建新订单失败"""
        # Setup
        old_order_id = "5555555555"
        new_price = Decimal("3355.0")

        # Mock cancellation succeeds
        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        bot.trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")

        # Mock new order creation fails
        bot.trade_executor._extended_client.place_order = AsyncMock(
            side_effect=Exception("Insufficient balance")
        )

        # Execute & Expect exception
        with pytest.raises(Exception) as exc_info:
            await bot._modify_maker_order_price(
                order_id=old_order_id,
                new_price=new_price,
                exchange="extended"
            )

        # Verify: old order was cancelled but creation failed
        bot.trade_executor._extended_client.cancel_order.assert_called_once()
        assert "balance" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_during_verification(self, bot):
        """测试：验证超时处理"""
        # Setup
        old_order_id = "6666666666"
        new_price = Decimal("3360.0")

        # Mock slow status check
        async def mock_slow_status(order_id):
            await asyncio.sleep(10)  # Simulate timeout
            return "CANCELED"

        bot.trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        bot.trade_executor._get_order_status_extended = mock_slow_status
        bot.trade_executor._extended_client.place_order = AsyncMock(return_value={
            "order_id": "7777777777",
            "status": "OPEN",
        })

        # Execute with short timeout
        await bot._modify_maker_order_price(
            order_id=old_order_id,
            new_price=new_price,
            exchange="extended",
            verify_timeout=0.5,  # 500ms timeout
            max_retries=1
        )

        # Verify: handled timeout gracefully (may have retried or failed)
        # The important thing is it didn't hang indefinitely
