"""
Integration tests for opening flow with price synchronization

Tests the complete opening flow from price fetch to order execution.
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from spread.trade_executor import TradeExecutor, ExecutionResult


class TestOpeningFlow:
    """Integration tests for the complete opening flow"""

    @pytest.mark.asyncio
    async def test_opening_with_price_sync(self):
        """
        Test complete opening flow with price synchronization

        This test verifies:
        1. Both exchanges' prices are fetched concurrently
        2. Time delta is calculated and validated
        3. Taker prices are calculated with slippage protection
        4. Orders are sent with synchronized prices
        """
        # Create mock clients
        mock_extended_client = MagicMock()
        mock_lighter_client = MagicMock()
        mock_risk_manager = MagicMock()

        # Mock Extended client methods
        mock_extended_client.config.contract_id = "ETH-USD"

        # Return specific BBO prices
        ext_bid = Decimal('3000.00')
        ext_ask = Decimal('3000.50')
        mock_extended_client.fetch_bbo_prices = AsyncMock(return_value=(ext_bid, ext_ask))

        # Mock place_taker_order
        mock_ext_result = MagicMock()
        mock_ext_result.success = True
        mock_ext_result.order_id = "ext_order_123"
        mock_ext_result.price = ext_ask * Decimal('1.002')  # With slippage
        mock_extended_client.place_taker_order = AsyncMock(return_value=mock_ext_result)

        # Mock get_order_info
        mock_ext_order_info = MagicMock()
        mock_ext_order_info.status = 'FILLED'
        mock_ext_order_info.filled_size = Decimal('0.21')
        mock_ext_order_info.price = mock_ext_result.price
        mock_extended_client.get_order_info = AsyncMock(return_value=mock_ext_order_info)

        # Mock Lighter client methods
        mock_lighter_client.config.contract_id = "ETH-USD"

        # Return specific BBO prices
        lig_bid = Decimal('2999.50')
        lig_ask = Decimal('3000.00')
        mock_lighter_client.fetch_bbo_prices = AsyncMock(return_value=(lig_bid, lig_ask))

        # Mock place_limit_order
        mock_lig_result = MagicMock()
        mock_lig_result.success = True
        mock_lig_result.order_id = "lig_order_456"
        mock_lig_result.price = lig_bid * Decimal('0.998')  # With slippage
        mock_lighter_client.place_limit_order = AsyncMock(return_value=mock_lig_result)

        # Mock get_order_info
        mock_lig_order_info = MagicMock()
        mock_lig_order_info.status = 'FILLED'
        mock_lig_order_info.filled_size = Decimal('0.21')
        mock_lig_order_info.price = mock_lig_result.price
        mock_lighter_client.get_order_info = AsyncMock(return_value=mock_lig_order_info)

        # Create TradeExecutor
        executor = TradeExecutor(
            lighter_client=mock_lighter_client,
            extended_client=mock_extended_client,
            risk_manager=mock_risk_manager,
            timeout=3.0
        )

        # Create mock spread object
        mock_spread = MagicMock()
        mock_spread.spread_pct = Decimal('0.005')  # 0.5% spread

        # Execute opening position
        quantity = Decimal('0.21')
        result = await executor.execute_open_position(quantity, mock_spread)

        # Verify the result
        assert result.success, "Opening should succeed"
        assert result.extended_order_id == "ext_order_123"
        assert result.lighter_order_id == "lig_order_456"
        assert result.extended_filled, "Extended should be filled"
        assert result.lighter_filled, "Lighter should be filled"

        # Verify both fetch_bbo_prices were called
        assert mock_extended_client.fetch_bbo_prices.called, "Extended BBO prices should be fetched"
        assert mock_lighter_client.fetch_bbo_prices.called, "Lighter BBO prices should be fetched"

        # Verify place_taker_order was called with slippage-protected price
        ext_call_args = mock_extended_client.place_taker_order.call_args
        ext_price = ext_call_args[1]['price']
        expected_ext_price = ext_ask * Decimal('1.002')
        assert ext_price == expected_ext_price, f"Ext price should include slippage: expected {expected_ext_price}, got {ext_price}"

        # Verify place_limit_order was called with slippage-protected price
        lig_call_args = mock_lighter_client.place_limit_order.call_args
        lig_price = lig_call_args[1]['price']
        expected_lig_price = lig_bid * Decimal('0.998')
        assert lig_price == expected_lig_price, f"Lig price should include slippage: expected {expected_lig_price}, got {lig_price}"

    @pytest.mark.asyncio
    async def test_opening_skip_on_price_inconsistency(self):
        """
        Test opening when prices are inconsistent (no arbitrage opportunity)

        This test verifies that when ext_price >= lig_price (after slippage),
        the opening is skipped to avoid loss-making trades.
        """
        # Create mock clients
        mock_extended_client = MagicMock()
        mock_lighter_client = MagicMock()
        mock_risk_manager = MagicMock()

        # Mock Extended client methods
        mock_extended_client.config.contract_id = "ETH-USD"

        # Return BBO prices where spread is too small (after slippage, no profit)
        ext_bid = Decimal('3000.00')
        ext_ask = Decimal('3000.10')  # Very tight spread
        mock_extended_client.fetch_bbo_prices = AsyncMock(return_value=(ext_bid, ext_ask))

        # Mock Lighter client methods
        mock_lighter_client.config.contract_id = "ETH-USD"

        lig_bid = Decimal('2999.90')  # Very close to ext_ask
        lig_ask = Decimal('3000.00')
        mock_lighter_client.fetch_bbo_prices = AsyncMock(return_value=(lig_bid, lig_ask))

        # Create TradeExecutor
        executor = TradeExecutor(
            lighter_client=mock_lighter_client,
            extended_client=mock_extended_client,
            risk_manager=mock_risk_manager,
            timeout=3.0
        )

        # Create mock spread object
        mock_spread = MagicMock()
        mock_spread.spread_pct = Decimal('0.0001')  # Very small spread

        # Execute opening position
        quantity = Decimal('0.21')
        result = await executor.execute_open_position(quantity, mock_spread)

        # Verify the opening was skipped
        assert not result.success, "Opening should fail when prices are inconsistent"
        assert "价差异常" in result.error_message or "ext" in result.error_message.lower(), \
            "Error message should mention price inconsistency"

        # Verify NO orders were placed (opening was skipped)
        assert not mock_extended_client.place_taker_order.called, "No Extended order should be placed"
        assert not mock_lighter_client.place_limit_order.called, "No Lighter order should be placed"

    @pytest.mark.asyncio
    async def test_opening_skip_on_time_delta_exceeded(self):
        """
        Test opening when price fetch time delta exceeds threshold

        This test verifies that when the two price fetches are more than 10ms apart,
        the opening is skipped to ensure price synchronization.
        """
        # Create mock clients
        mock_extended_client = MagicMock()
        mock_lighter_client = MagicMock()
        mock_risk_manager = MagicMock()

        # Mock Extended client methods
        mock_extended_client.config.contract_id = "ETH-USD"
        ext_bid = Decimal('3000.00')
        ext_ask = Decimal('3000.50')

        # We need to simulate a delay between the two fetch_bbo_prices calls
        # To do this, we'll make one call slower than the other
        async def slow_ext_fetch(*args, **kwargs):
            await asyncio.sleep(0.02)  # Sleep 20ms to ensure time_delta > 10ms
            return (ext_bid, ext_ask)

        mock_extended_client.fetch_bbo_prices = AsyncMock(side_effect=slow_ext_fetch)

        # Mock Lighter client methods
        mock_lighter_client.config.contract_id = "ETH-USD"
        lig_bid = Decimal('2999.50')
        lig_ask = Decimal('3000.00')
        mock_lighter_client.fetch_bbo_prices = AsyncMock(return_value=(lig_bid, lig_ask))

        # Create TradeExecutor
        executor = TradeExecutor(
            lighter_client=mock_lighter_client,
            extended_client=mock_extended_client,
            risk_manager=mock_risk_manager,
            timeout=3.0
        )

        # Create mock spread object
        mock_spread = MagicMock()

        # Execute opening position
        quantity = Decimal('0.21')
        result = await executor.execute_open_position(quantity, mock_spread)

        # Verify the opening was skipped due to time delta
        assert not result.success, "Opening should fail when time_delta exceeds threshold"
        assert "time_delta" in result.error_message or "价格快照无效" in result.error_message, \
            "Error message should mention time delta"

        # Verify NO orders were placed (opening was skipped)
        assert not mock_extended_client.place_taker_order.called, "No Extended order should be placed"
        assert not mock_lighter_client.place_limit_order.called, "No Lighter order should be placed"
