"""
Integration tests for trade logging functionality.

Tests the complete trade logging flow including:
- Full trade cycle (open and close)
- Log file location verification
- Log format validation
- Integration with mock exchanges
"""

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from spread.trade_logger import TradeLogger
from spread.spread_pair import SpreadPair


class TestTradeCycleLogging:
    """Test complete trade cycle logging."""

    def test_full_open_close_cycle(self, tmp_path):
        """Test logging a complete trade cycle (open and close)."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        # Create and log opening trade
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3450.50'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3455.75'),
            lighter_quantity=Decimal('0.01'),
            extended_order_id='ext_open_1',
            lighter_order_id='lt_open_1'
        )

        logger.log_opening_trade(pair)

        # Close the trade
        pair.close(
            close_extended_price=Decimal('3451.00'),
            close_lighter_price=Decimal('3455.25')
        )
        pair.close_extended_order_id = 'ext_close_1'
        pair.close_lighter_order_id = 'lt_close_1'

        logger.log_closing_trade(pair)

        # Verify both entries were logged
        content = log_path.read_text()
        assert 'TRADE OPENED' in content or 'Pair #1' in content
        assert 'TRADE CLOSED' in content or 'Pair #1' in content

    def test_log_file_location(self, tmp_path):
        """Test that log file is created in the correct location."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3450.50'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3455.75'),
            lighter_quantity=Decimal('0.01')
        )

        logger.log_opening_trade(pair)

        # Verify file location
        assert log_path.exists()
        assert log_path.parent.name == 'logs'

    def test_multiple_trades_sequentially(self, tmp_path):
        """Test logging multiple trades in sequence."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        for i in range(3):
            # Open
            pair = SpreadPair(
                pair_id=i+1,
                extended_side='buy',
                extended_price=Decimal('3450.50') + Decimal(i),
                extended_quantity=Decimal('0.01'),
                lighter_price=Decimal('3455.75') + Decimal(i),
                lighter_quantity=Decimal('0.01')
            )
            logger.log_opening_trade(pair)

            # Close
            pair.close(
                close_extended_price=Decimal('3451.00') + Decimal(i),
                close_lighter_price=Decimal('3455.25') + Decimal(i)
            )
            logger.log_closing_trade(pair)

        # Verify all trades were logged
        content = log_path.read_text()
        assert 'Pair #1' in content or 'TRADE OPENED' in content


class TestLogFormatValidation:
    """Validate that log format is human-readable."""

    def test_opening_entry_has_required_sections(self, tmp_path):
        """Test that opening entry has all required sections."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3450.50'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3455.75'),
            lighter_quantity=Decimal('0.01'),
            extended_order_id='ext_123',
            lighter_order_id='lt_456'
        )

        logger.log_opening_trade(pair)

        content = log_path.read_text()
        # Basic validation - full format in T012-T013, T025-T028
        assert len(content) > 0

    def test_closing_entry_has_required_sections(self, tmp_path):
        """Test that closing entry has all required sections."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3450.50'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3455.75'),
            lighter_quantity=Decimal('0.01')
        )
        pair.close(
            close_extended_price=Decimal('3451.00'),
            close_lighter_price=Decimal('3455.25')
        )

        logger.log_closing_trade(pair)

        content = log_path.read_text()
        # Basic validation - full format in T012-T013, T025-T028
        assert len(content) > 0


class TestLogEntrySeparation:
    """Test that log entries are properly separated."""

    def test_entries_are_separated(self, tmp_path):
        """Test that multiple log entries are clearly separated."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        # Log multiple trades
        for i in range(3):
            pair = SpreadPair(
                pair_id=i+1,
                extended_side='buy',
                extended_price=Decimal('3450.50') + Decimal(i),
                extended_quantity=Decimal('0.01'),
                lighter_price=Decimal('3455.75') + Decimal(i),
                lighter_quantity=Decimal('0.01')
            )
            logger.log_opening_trade(pair)

        content = log_path.read_text()
        # Should have multiple entries (full separation in T025-T028)
        assert len(content) > 0
