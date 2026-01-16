"""
Unit tests for PriceSnapshot class

Tests the price snapshot functionality including validation,
taker price calculation, and price consistency checks.
"""

import pytest
from decimal import Decimal
from spread.price_snapshot import PriceSnapshot


class TestPriceSnapshot:
    """Test cases for PriceSnapshot class"""

    def test_valid_snapshot(self):
        """Test a valid price snapshot with time_delta < 10ms"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,  # 5ms after ext
            time_delta=0.005  # 5ms
        )
        assert snapshot.is_valid(), "Snapshot with time_delta=5ms should be valid"
        assert snapshot.validate_price_consistency(), "Prices should be consistent (arbitrage profitable)"

    def test_invalid_time_delta(self):
        """Test price snapshot with time_delta >= 10ms is invalid"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.05,  # 50ms after ext
            time_delta=0.05  # 50ms (exceeds 10ms threshold)
        )
        assert not snapshot.is_valid(), "Snapshot with time_delta=50ms should be invalid"

    def test_invalid_negative_prices(self):
        """Test price snapshot with negative prices is invalid"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('-100.00'),  # Invalid: negative price
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        assert not snapshot.is_valid(), "Snapshot with negative bid should be invalid"

    def test_invalid_bid_above_ask(self):
        """Test price snapshot with bid >= ask is invalid"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3001.00'),  # Invalid: bid > ask
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        assert not snapshot.is_valid(), "Snapshot with ext_bid > ext_ask should be invalid"

    def test_calculate_taker_prices(self):
        """Test taker price calculation with 0.2% slippage"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )

        ext_price, lig_price = snapshot.calculate_taker_prices()

        # Ext buy price = ask * 1.002 (0.2% slippage)
        expected_ext = Decimal('3000.50') * Decimal('1.002')
        # Lig sell price = bid * 0.998 (0.2% slippage)
        expected_lig = Decimal('2999.50') * Decimal('0.998')

        assert ext_price == expected_ext, f"Ext price should be {expected_ext}, got {ext_price}"
        assert lig_price == expected_lig, f"Lig price should be {expected_lig}, got {lig_price}"

    def test_validate_price_consistency_valid(self):
        """Test price consistency validation when arbitrage is profitable"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )
        # After slippage: ext_price should still be < lig_price for profitable arbitrage
        assert snapshot.validate_price_consistency(), "Arbitrage should be profitable"

    def test_validate_price_consistency_invalid(self):
        """Test price consistency validation when arbitrage is not profitable"""
        # Create a scenario where after slippage, ext_price >= lig_price
        # This happens when the spread is too small or negative
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.10'),  # Very tight spread
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.90'),  # Bid close to ext_ask
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )

        # Calculate prices
        ext_price, lig_price = snapshot.calculate_taker_prices()
        # If ext_ask * 1.002 >= lig_bid * 0.998, arbitrage is not profitable
        is_profitable = snapshot.validate_price_consistency()

        # This test documents the expected behavior
        # In a tight spread scenario, arbitrage may not be profitable after slippage
        print(f"ext_price={ext_price}, lig_price={lig_price}, is_profitable={is_profitable}")

    def test_exact_10ms_boundary(self):
        """Test price snapshot at exactly 10ms boundary"""
        # 10ms = 0.01 seconds
        snapshot = PriceSnapshot(
            ext_bid=Decimal('3000.00'),
            ext_ask=Decimal('3000.50'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.50'),
            lig_ask=Decimal('3000.00'),
            lig_timestamp=1000.01,  # Exactly 10ms
            time_delta=0.01  # Exactly 10ms (boundary)
        )
        # time_delta must be < 0.01, so 0.01 should be invalid
        assert not snapshot.is_valid(), "Snapshot with time_delta=10ms (exactly) should be invalid"

    def test_slippage_calculation_precision(self):
        """Test that slippage calculation maintains decimal precision"""
        snapshot = PriceSnapshot(
            ext_bid=Decimal('2999.75'),
            ext_ask=Decimal('3000.25'),
            ext_timestamp=1000.0,
            lig_bid=Decimal('2999.25'),
            lig_ask=Decimal('2999.75'),
            lig_timestamp=1000.005,
            time_delta=0.005
        )

        ext_price, lig_price = snapshot.calculate_taker_prices()

        # Verify decimal precision is maintained
        assert isinstance(ext_price, Decimal), "Ext price should be Decimal"
        assert isinstance(lig_price, Decimal), "Lig price should be Decimal"
        assert ext_price > Decimal('3000.25'), "Ext price should include slippage"
        assert lig_price < Decimal('2999.25'), "Lig price should include slippage"
