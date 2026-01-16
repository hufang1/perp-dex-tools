"""
Unit tests for TradeExecutor slippage protection and price synchronization

Tests the taker order slippage protection logic and price synchronization.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from spread.trade_executor import TradeExecutor
from spread.price_snapshot import PriceSnapshot


class TestTradeExecutorSlippage:
    """Test cases for TradeExecutor slippage protection"""

    @pytest.mark.asyncio
    async def test_extended_slippage_protection_buy(self):
        """Test that Extended buy orders include 0.2% slippage protection"""
        # Create mock clients
        mock_extended_client = MagicMock()
        mock_lighter_client = MagicMock()
        mock_risk_manager = MagicMock()

        # Mock fetch_bbo_prices to return specific values
        mock_extended_client.fetch_bbo_prices = AsyncMock(return_value=(Decimal('3000.00'), Decimal('3000.50')))
        mock_extended_client.config.contract_id = "ETH-USD"

        # Mock place_taker_order
        mock_extended_client.place_taker_order = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.order_id = "ext_order_123"
        mock_result.price = None
        mock_extended_client.place_taker_order.return_value = mock_result

        # Create TradeExecutor
        executor = TradeExecutor(
            lighter_client=mock_lighter_client,
            extended_client=mock_extended_client,
            risk_manager=mock_risk_manager,
            timeout=3.0
        )

        # Call _place_extended_order_taker with price=None (should auto-calculate with slippage)
        result = await executor._place_extended_order_taker("buy", Decimal('0.21'), None)

        # Verify place_taker_order was called
        assert mock_extended_client.place_taker_order.called, "place_taker_order should be called"

        # Get the price argument from the call
        call_args = mock_extended_client.place_taker_order.call_args
        price_arg = call_args[1]['price']  # keyword argument

        # Expected price = ask * 1.002
        expected_price = Decimal('3000.50') * Decimal('1.002')

        assert price_arg == expected_price, f"Price should include 0.2% slippage: expected {expected_price}, got {price_arg}"

    @pytest.mark.asyncio
    async def test_extended_slippage_protection_sell(self):
        """Test that Extended sell orders include 0.2% slippage protection"""
        # Create mock clients
        mock_extended_client = MagicMock()
        mock_lighter_client = MagicMock()
        mock_risk_manager = MagicMock()

        # Mock fetch_bbo_prices to return specific values
        mock_extended_client.fetch_bbo_prices = AsyncMock(return_value=(Decimal('2999.50'), Decimal('3000.00')))
        mock_extended_client.config.contract_id = "ETH-USD"

        # Mock place_taker_order
        mock_extended_client.place_taker_order = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.order_id = "ext_order_123"
        mock_result.price = None
        mock_extended_client.place_taker_order.return_value = mock_result

        # Create TradeExecutor
        executor = TradeExecutor(
            lighter_client=mock_lighter_client,
            extended_client=mock_extended_client,
            risk_manager=mock_risk_manager,
            timeout=3.0
        )

        # Call _place_extended_order_taker with price=None (should auto-calculate with slippage)
        result = await executor._place_extended_order_taker("sell", Decimal('0.21'), None)

        # Verify place_taker_order was called
        assert mock_extended_client.place_taker_order.called, "place_taker_order should be called"

        # Get the price argument from the call
        call_args = mock_extended_client.place_taker_order.call_args
        price_arg = call_args[1]['price']

        # Expected price = bid * 0.998
        expected_price = Decimal('2999.50') * Decimal('0.998')

        assert price_arg == expected_price, f"Price should include 0.2% slippage: expected {expected_price}, got {price_arg}"

    @pytest.mark.asyncio
    async def test_extended_uses_explicit_price(self):
        """Test that Extended uses explicit price when provided (no auto-calculation)"""
        # Create mock clients
        mock_extended_client = MagicMock()
        mock_lighter_client = MagicMock()
        mock_risk_manager = MagicMock()

        # Mock place_taker_order
        mock_extended_client.place_taker_order = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.order_id = "ext_order_123"
        mock_result.price = Decimal('3005.00')
        mock_extended_client.place_taker_order.return_value = mock_result

        # Create TradeExecutor
        executor = TradeExecutor(
            lighter_client=mock_lighter_client,
            extended_client=mock_extended_client,
            risk_manager=mock_risk_manager,
            timeout=3.0
        )

        # Call with explicit price
        explicit_price = Decimal('3005.00')
        result = await executor._place_extended_order_taker("buy", Decimal('0.21'), explicit_price)

        # Verify fetch_bbo_prices was NOT called (price was provided)
        assert not mock_extended_client.fetch_bbo_prices.called, "fetch_bbo_prices should not be called when price is provided"

        # Verify place_taker_order was called with the explicit price
        call_args = mock_extended_client.place_taker_order.call_args
        price_arg = call_args[1]['price']

        assert price_arg == explicit_price, f"Should use explicit price: expected {explicit_price}, got {price_arg}"


class TestPriceSync:
    """Test cases for price synchronization logic"""

    def test_price_snapshot_creation(self):
        """Test creating a price snapshot from BBO data"""
        ext_bid = Decimal('3000.00')
        ext_ask = Decimal('3000.50')
        ext_timestamp = 1640000000.000

        lig_bid = Decimal('2999.50')
        lig_ask = Decimal('3000.00')
        lig_timestamp = 1640000000.005

        time_delta = abs(lig_timestamp - ext_timestamp)

        snapshot = PriceSnapshot(
            ext_bid=ext_bid,
            ext_ask=ext_ask,
            ext_timestamp=ext_timestamp,
            lig_bid=lig_bid,
            lig_ask=lig_ask,
            lig_timestamp=lig_timestamp,
            time_delta=time_delta
        )

        assert snapshot.ext_bid == ext_bid
        assert snapshot.ext_ask == ext_ask
        assert snapshot.lig_bid == lig_bid
        assert snapshot.lig_ask == lig_ask
        assert snapshot.time_delta == time_delta

    def test_price_snapshot_validation(self):
        """Test price snapshot validation logic"""
        # Valid snapshot
        valid_snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005  # 5ms < 10ms threshold
        )

        assert valid_snapshot.is_valid(), "Valid snapshot should pass validation"

        # Invalid snapshot (time_delta too large)
        invalid_snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.05,  # 50ms
            time_delta=0.05  # 50ms > 10ms threshold
        )

        assert not invalid_snapshot.is_valid(), "Snapshot with large time_delta should fail validation"
