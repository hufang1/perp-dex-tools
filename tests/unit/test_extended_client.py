"""
Unit tests for Extended client retry logic

Tests the retry mechanism with original price caching.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from exchanges.extended import ExtendedClient


class TestExtendedRetry:
    """Test cases for Extended client retry logic"""

    @pytest.mark.asyncio
    async def test_retry_uses_original_price(self):
        """Test that retry uses the original price, not a newly fetched price"""
        # Create mock config
        mock_config = MagicMock()
        mock_config.contract_id = "ETH-USD"
        mock_config.private_key = "0x1234567890abcdef"
        mock_config.api_key = "test_api_key"
        mock_config.ticker = "ETH-USD"
        mock_config.tick_size = Decimal('0.5')
        mock_config.min_order_size = Decimal('0.001')

        # Create Extended client (we'll mock the perpetual_trading_client)
        with patch('exchanges.extended.PerpetualTradingClient'):
            client = ExtendedClient(mock_config)
            client.perpetual_trading_client = MagicMock()

            # Mock the place_order method to fail first time, succeed second time
            mock_response_1 = MagicMock()
            mock_response_1.status = 'ERROR'  # First attempt fails

            mock_response_2 = MagicMock()
            mock_response_2.status = 'OK'
            mock_response_2.data = MagicMock()
            mock_response_2.data.id = "order_123"

            client.perpetual_trading_client.place_order = AsyncMock(
                side_effect=[mock_response_1, mock_response_2]
            )

            # Mock get_order_info to return FILLED status
            mock_order_info = MagicMock()
            mock_order_info.status = 'FILLED'
            mock_order_info.filled_size = Decimal('0.21')
            mock_order_info.price = Decimal('3005.00')

            client.get_order_info = AsyncMock(return_value=mock_order_info)

            # Call place_taker_order with max_retries=1 (should retry once)
            original_price = Decimal('3005.00')
            result = await client.place_taker_order(
                contract_id="ETH-USD",
                quantity=Decimal('0.21'),
                side="buy",
                price=original_price,
                max_retries=1
            )

            # Verify place_order was called twice (initial + 1 retry)
            assert client.perpetual_trading_client.place_order.call_count == 2

            # Verify both calls used the SAME price (original price)
            first_call_price = client.perpetual_trading_client.place_order.call_args_list[0][1]['price']
            second_call_price = client.perpetual_trading_client.place_order.call_args_list[1][1]['price']

            # Both should use the original_price (rounded), not different prices
            assert first_call_price == second_call_price, "Retry should use the same price as initial attempt"

    @pytest.mark.asyncio
    async def test_retry_limited_to_1(self):
        """Test that retry is limited to 1 attempt (max 2 total attempts)"""
        # Create mock config
        mock_config = MagicMock()
        mock_config.contract_id = "ETH-USD"
        mock_config.private_key = "0x1234567890abcdef"
        mock_config.api_key = "test_api_key"
        mock_config.ticker = "ETH-USD"
        mock_config.tick_size = Decimal('0.5')
        mock_config.min_order_size = Decimal('0.001')

        # Create Extended client
        with patch('exchanges.extended.PerpetualTradingClient'):
            client = ExtendedClient(mock_config)
            client.perpetual_trading_client = MagicMock()

            # Mock place_order to always fail
            mock_response = MagicMock()
            mock_response.status = 'ERROR'

            client.perpetual_trading_client.place_order = AsyncMock(return_value=mock_response)

            # Call place_taker_order with max_retries=1 (default)
            result = await client.place_taker_order(
                contract_id="ETH-USD",
                quantity=Decimal('0.21'),
                side="buy",
                price=Decimal('3005.00'),
                max_retries=1  # Only 1 retry allowed
            )

            # Verify place_order was called exactly 2 times (1 initial + 1 retry)
            assert client.perpetual_trading_client.place_order.call_count == 2, \
                f"Expected 2 calls (1 initial + 1 retry), got {client.perpetual_trading_client.place_order.call_count}"

            # Verify result indicates failure
            assert not result.success, "Order should fail after max retries"

    @pytest.mark.asyncio
    async def test_custom_max_retries(self):
        """Test that custom max_retries parameter is respected"""
        # Create mock config
        mock_config = MagicMock()
        mock_config.contract_id = "ETH-USD"
        mock_config.private_key = "0x1234567890abcdef"
        mock_config.api_key = "test_api_key"
        mock_config.ticker = "ETH-USD"
        mock_config.tick_size = Decimal('0.5')
        mock_config.min_order_size = Decimal('0.001')

        # Create Extended client
        with patch('exchanges.extended.PerpetualTradingClient'):
            client = ExtendedClient(mock_config)
            client.perpetual_trading_client = MagicMock()

            # Mock place_order to always fail
            mock_response = MagicMock()
            mock_response.status = 'ERROR'

            client.perpetual_trading_client.place_order = AsyncMock(return_value=mock_response)

            # Call place_taker_order with max_retries=2
            result = await client.place_taker_order(
                contract_id="ETH-USD",
                quantity=Decimal('0.21'),
                side="buy",
                price=Decimal('3005.00'),
                max_retries=2  # Allow 2 retries
            )

            # Verify place_order was called exactly 3 times (1 initial + 2 retries)
            assert client.perpetual_trading_client.place_order.call_count == 3, \
                f"Expected 3 calls (1 initial + 2 retries), got {client.perpetual_trading_client.place_order.call_count}"

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        """Test that no retry occurs when order succeeds on first attempt"""
        # Create mock config
        mock_config = MagicMock()
        mock_config.contract_id = "ETH-USD"
        mock_config.private_key = "0x1234567890abcdef"
        mock_config.api_key = "test_api_key"
        mock_config.ticker = "ETH-USD"
        mock_config.tick_size = Decimal('0.5')
        mock_config.min_order_size = Decimal('0.001')

        # Create Extended client
        with patch('exchanges.extended.PerpetualTradingClient'):
            client = ExtendedClient(mock_config)
            client.perpetual_trading_client = MagicMock()

            # Mock place_order to succeed immediately
            mock_response = MagicMock()
            mock_response.status = 'OK'
            mock_response.data = MagicMock()
            mock_response.data.id = "order_123"

            client.perpetual_trading_client.place_order = AsyncMock(return_value=mock_response)

            # Mock get_order_info to return FILLED status
            mock_order_info = MagicMock()
            mock_order_info.status = 'FILLED'
            mock_order_info.filled_size = Decimal('0.21')
            mock_order_info.price = Decimal('3005.00')

            client.get_order_info = AsyncMock(return_value=mock_order_info)

            # Call place_taker_order
            result = await client.place_taker_order(
                contract_id="ETH-USD",
                quantity=Decimal('0.21'),
                side="buy",
                price=Decimal('3005.00'),
                max_retries=1
            )

            # Verify place_order was called only once (no retries)
            assert client.perpetual_trading_client.place_order.call_count == 1, \
                "Order should not retry on success"

            # Verify result indicates success
            assert result.success, "Order should succeed"
