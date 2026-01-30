"""
Price Snapshot Module for Spread Arbitrage

This module provides the PriceSnapshot class for capturing and validating
synchronized price data from two exchanges (Extended and Lighter).

The price snapshot ensures that:
1. Both exchanges' prices are fetched within 10ms of each other
2. Taker order prices include slippage protection (configurable)
3. Price consistency is validated (ext_buy < lig_sell for arbitrage)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple


@dataclass
class PriceSnapshot:
    """Price snapshot: Records BBO prices from two exchanges at a specific moment

    This class captures the Best Bid/Offer (BBO) prices from both Extended
    and Lighter exchanges, along with timestamps to ensure synchronization.

    Attributes:
        ext_bid: Extended exchange best bid price
        ext_ask: Extended exchange best ask price
        ext_timestamp: Unix timestamp when ext prices were fetched
        lig_bid: Lighter exchange best bid price
        lig_ask: Lighter exchange best ask price
        lig_timestamp: Unix timestamp when lig prices were fetched
        time_delta: Absolute difference between the two timestamps (seconds)

    Example:
        >>> snapshot = PriceSnapshot(
        ...     ext_bid=Decimal('3000.00'),
        ...     ext_ask=Decimal('3000.50'),
        ...     ext_timestamp=1640000000.000,
        ...     lig_bid=Decimal('2999.50'),
        ...     lig_ask=Decimal('3000.00'),
        ...     lig_timestamp=1640000000.005,
        ...     time_delta=0.005
        ... )
        >>> if snapshot.is_valid():
        ...     ext_price, lig_price = snapshot.calculate_taker_prices()
    """

    ext_bid: Decimal
    ext_ask: Decimal
    ext_timestamp: float
    lig_bid: Decimal
    lig_ask: Decimal
    lig_timestamp: float
    time_delta: float
    slippage_buffer: Decimal = Decimal("0.0001")

    def is_valid(self) -> bool:
        """Validate price snapshot

        A valid snapshot must satisfy:
        - All prices are positive (> 0)
        - Bid prices are lower than ask prices (bid < ask for both exchanges)
        - Time delta between price fetches is less than 10ms (0.01 seconds)

        Returns:
            bool: True if snapshot is valid, False otherwise
        """
        return (
            self.ext_bid > 0 and self.ext_ask > 0 and
            self.lig_bid > 0 and self.lig_ask > 0 and
            self.ext_bid < self.ext_ask and
            self.lig_bid < self.lig_ask and
            self.time_delta < 0.01  # <10ms
        )

    def calculate_taker_prices(self) -> Tuple[Decimal, Decimal]:
        """Calculate taker order prices with slippage protection

        Slippage protection ensures IOC orders execute immediately:
        - Extended buy price = ext_ask * (1 + slippage_buffer)
        - Lighter sell price = lig_bid * (1 - slippage_buffer)

        Returns:
            Tuple[Decimal, Decimal]: (ext_price, lig_price)
                - ext_price: Price to use for Extended taker buy order
                - lig_price: Price to use for Lighter taker sell order
        """
        slip = self.slippage_buffer if self.slippage_buffer >= 0 else Decimal("0")
        ext_price = self.ext_ask * (Decimal("1") + slip)
        lig_price = self.lig_bid * (Decimal("1") - slip)
        return ext_price, lig_price

    def validate_price_consistency(self) -> bool:
        """Validate price consistency for arbitrage

        For a profitable arbitrage:
        - Extended buy cost must be lower than Lighter sell revenue
        - After slippage: ext_ask * (1+slip) < lig_bid * (1-slip)

        Returns:
            bool: True if prices are consistent (arbitrage profitable), False otherwise
        """
        ext_price, lig_price = self.calculate_taker_prices()
        return ext_price < lig_price
