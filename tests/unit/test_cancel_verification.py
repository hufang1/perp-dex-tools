"""
取消订单验证单元测试

测试范围：
- 取消订单操作的验证机制
- 重试逻辑
- 超时处理
- 错误处理

测试目标：确保修改挂单价格时先取消旧订单再创建新订单
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from datetime import datetime

from spread.models import CancelOrderResult
from spread.trade_executor import TradeExecutor
from exceptions import OrderCancellationError


class TestCancelOrderVerification:
    """测试取消订单验证机制"""

    @pytest.fixture
    def trade_executor(self):
        """创建TradeExecutor测试实例"""
        # Mock the dependencies
        mock_extended_client = AsyncMock()
        mock_lighter_client = AsyncMock()

        executor = TradeExecutor(
            extended_client=mock_extended_client,
            lighter_client=mock_lighter_client,
        )
        return executor

    @pytest.mark.asyncio
    async def test_cancel_order_success_on_first_attempt(self, trade_executor):
        """测试：首次尝试即成功取消订单"""
        # Setup
        order_id = "1234567890"
        exchange = "extended"

        # Mock successful cancellation
        trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")

        # Execute
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=order_id,
            exchange=exchange
        )

        # Verify
        assert result.canceled is True
        assert result.attempts == 1
        assert result.order_id == order_id
        assert result.final_status == "CANCELED"
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_cancel_order_success_after_retries(self, trade_executor):
        """测试：多次重试后成功取消订单"""
        # Setup
        order_id = "9876543210"
        exchange = "lighter"

        # Mock cancellation: fails twice, succeeds on third try
        call_count = 0

        async def mock_cancel(order_id):
            nonlocal call_count
            call_count += 1
            return call_count >= 3  # 前两次失败，第三次成功

        async def mock_get_status(order_id):
            return "CANCELED" if call_count >= 3 else "OPEN"

        trade_executor._lighter_client.cancel_order = mock_cancel
        trade_executor._get_order_status_lighter = mock_get_status

        # Execute
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=order_id,
            exchange=exchange,
            max_retries=5
        )

        # Verify
        assert result.canceled is True
        assert result.attempts == 3
        assert result.final_status == "CANCELED"

    @pytest.mark.asyncio
    async def test_cancel_order_failure_max_retries_exceeded(self, trade_executor):
        """测试：超过最大重试次数后取消失败"""
        # Setup
        order_id = "1111111111"
        exchange = "extended"

        # Mock persistent failure
        trade_executor._extended_client.cancel_order = AsyncMock(return_value=False)
        trade_executor._get_order_status_extended = AsyncMock(return_value="OPEN")

        # Execute & Expect exception
        with pytest.raises(OrderCancellationError) as exc_info:
            await trade_executor.cancel_maker_order_with_verification(
                order_id=order_id,
                exchange=exchange,
                max_retries=3
            )

        # Verify exception details
        assert order_id in str(exc_info.value)
        assert "3" in str(exc_info.value)  # max retries

    @pytest.mark.asyncio
    async def test_cancel_order_verification_timeout(self, trade_executor):
        """测试：验证超时处理"""
        # Setup
        order_id = "2222222222"
        exchange = "lighter"

        # Mock cancellation succeeds but status check times out
        trade_executor._lighter_client.cancel_order = AsyncMock(return_value=True)

        # Mock slow status response (simulates timeout)
        async def mock_slow_status(order_id):
            await asyncio.sleep(10)  # Longer than verify_timeout
            return "CANCELED"

        import asyncio
        trade_executor._get_order_status_lighter = mock_slow_status

        # Execute & Expect timeout behavior
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=order_id,
            exchange=exchange,
            verify_timeout=1.0,  # 1 second timeout
            max_retries=1
        )

        # Verify: Should fail due to timeout
        assert result.canceled is False
        assert "timeout" in result.error_message.lower() or "超时" in result.error_message

    @pytest.mark.asyncio
    async def test_cancel_order_already_closed(self, trade_executor):
        """测试：订单已经关闭或不存在"""
        # Setup
        order_id = "3333333333"
        exchange = "extended"

        # Mock: order not found or already closed
        trade_executor._extended_client.cancel_order = AsyncMock(
            side_effect=Exception("Order not found")
        )
        trade_executor._get_order_status_extended = AsyncMock(return_value="FILLED")

        # Execute
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=order_id,
            exchange=exchange,
            max_retries=2
        )

        # Verify: Should treat as successful (order already closed)
        assert result.canceled is True
        assert result.final_status == "FILLED"

    @pytest.mark.asyncio
    async def test_cancel_order_extended_exchange(self, trade_executor):
        """测试：Extended交易所取消订单"""
        # Setup
        order_id = 1234567890123456789  # Extended uses numeric order IDs
        exchange = "extended"

        trade_executor._extended_client.cancel_order = AsyncMock(return_value=True)
        trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")

        # Execute
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=str(order_id),
            exchange=exchange
        )

        # Verify correct API was called
        trade_executor._extended_client.cancel_order.assert_called_once()
        assert result.canceled is True

    @pytest.mark.asyncio
    async def test_cancel_order_lighter_exchange(self, trade_executor):
        """测试：Lighter交易所取消订单"""
        # Setup
        order_id = "abcdef123456"
        exchange = "lighter"

        trade_executor._lighter_client.cancel_order = AsyncMock(return_value=True)
        trade_executor._get_order_status_lighter = AsyncMock(return_value="CANCELED")

        # Execute
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=order_id,
            exchange=exchange
        )

        # Verify correct API was called
        trade_executor._lighter_client.cancel_order.assert_called_once()
        assert result.canceled is True

    @pytest.mark.asyncio
    async def test_cancel_order_timing_recording(self, trade_executor):
        """测试：记录取消操作耗时"""
        # Setup
        order_id = "4444444444"
        exchange = "extended"

        # Mock cancellation with some delay
        async def mock_cancel_with_delay(order_id):
            await asyncio.sleep(0.1)  # 100ms delay
            return True

        import asyncio
        trade_executor._extended_client.cancel_order = mock_cancel_with_delay
        trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")

        # Execute
        result = await trade_executor.cancel_maker_order_with_verification(
            order_id=order_id,
            exchange=exchange
        )

        # Verify timing was recorded
        assert result.total_time > 0
        assert result.total_time >= 0.1  # At least 100ms


class TestVerifyOrderCancellation:
    """测试私有验证方法"""

    @pytest.fixture
    def trade_executor(self):
        """创建TradeExecutor测试实例"""
        mock_extended_client = AsyncMock()
        mock_lighter_client = AsyncMock()

        executor = TradeExecutor(
            extended_client=mock_extended_client,
            lighter_client=mock_lighter_client,
        )
        return executor

    @pytest.mark.asyncio
    async def test_verify_cancellation_confirmed(self, trade_executor):
        """测试：确认订单已取消"""
        # Setup
        order_id = "5555555555"
        exchange = "extended"

        trade_executor._get_order_status_extended = AsyncMock(return_value="CANCELED")

        # Execute private method via direct call
        is_canceled = await trade_executor._verify_order_cancellation(
            order_id=order_id,
            exchange=exchange
        )

        # Verify
        assert is_canceled is True
        trade_executor._get_order_status_extended.assert_called_once_with(order_id)

    @pytest.mark.asyncio
    async def test_verify_cancellation_still_open(self, trade_executor):
        """测试：订单仍然开放"""
        # Setup
        order_id = "6666666666"
        exchange = "lighter"

        trade_executor._get_order_status_lighter = AsyncMock(return_value="OPEN")

        # Execute
        is_canceled = await trade_executor._verify_order_cancellation(
            order_id=order_id,
            exchange=exchange
        )

        # Verify
        assert is_canceled is False

    @pytest.mark.asyncio
    async def test_verify_cancellation_filled(self, trade_executor):
        """测试：订单已成交（视为已取消）"""
        # Setup
        order_id = "7777777777"
        exchange = "extended"

        trade_executor._get_order_status_extended = AsyncMock(return_value="FILLED")

        # Execute
        is_canceled = await trade_executor._verify_order_cancellation(
            order_id=order_id,
            exchange=exchange
        )

        # Verify: Filled orders should count as "no longer active"
        assert is_canceled is True

    @pytest.mark.asyncio
    async def test_verify_cancellation_partial_fill(self, trade_executor):
        """测试：订单部分成交"""
        # Setup
        order_id = "8888888888"
        exchange = "lighter"

        trade_executor._get_order_status_lighter = AsyncMock(return_value="PARTIALLY_FILLED")

        # Execute
        is_canceled = await trade_executor._verify_order_cancellation(
            order_id=order_id,
            exchange=exchange
        )

        # Verify: Partially filled should be treated as still active
        assert is_canceled is False


class TestCancelOrderResult:
    """测试CancelOrderResult数据类"""

    def test_cancel_order_result_creation(self):
        """测试：创建CancelOrderResult对象"""
        result = CancelOrderResult(
            order_id="9999999999",
            canceled=True,
            attempts=2,
            total_time=1.5,
            final_status="CANCELED",
            error_message=None
        )

        assert result.order_id == "9999999999"
        assert result.canceled is True
        assert result.attempts == 2
        assert result.total_time == 1.5
        assert result.final_status == "CANCELED"
        assert result.error_message is None

    def test_cancel_order_result_with_error(self):
        """测试：创建包含错误的CancelOrderResult对象"""
        result = CancelOrderResult(
            order_id="0000000000",
            canceled=False,
            attempts=5,
            total_time=10.0,
            final_status="OPEN",
            error_message="Max retries exceeded"
        )

        assert result.canceled is False
        assert result.error_message == "Max retries exceeded"
        assert result.final_status == "OPEN"
