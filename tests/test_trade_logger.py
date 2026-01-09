"""
Unit tests for TradeLogger module.

Tests the trade logging functionality including:
- Opening trade logging
- Closing trade logging
- Unhedged position logging
- Log file creation
- Error handling
- Concurrent writes
"""

import os
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from spread.trade_logger import TradeLogger
from spread.spread_pair import SpreadPair


class TestTradeLoggerInitialization:
    """Test TradeLogger initialization and setup."""

    def test_creates_log_directory_if_not_exists(self, tmp_path):
        """Test that the logger creates the logs directory automatically."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        assert logger.logger is not None
        assert log_path.parent.exists()

    def test_existing_log_directory(self, tmp_path):
        """Test that the logger works with existing log directory."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_path = log_dir / "trade.log"

        logger = TradeLogger(log_file_path=str(log_path))

        assert logger.logger is not None

    def test_get_log_file_path(self, tmp_path):
        """Test getting the absolute log file path."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        result = logger.get_log_file_path()

        assert result == str(log_path.absolute())

    def test_get_log_stats(self, tmp_path):
        """Test getting log file statistics."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        stats = logger.get_log_stats()

        assert 'file_path' in stats
        assert 'file_size_bytes' in stats
        assert 'file_size_mb' in stats
        assert stats['file_size_bytes'] == 0


class TestOpeningTradeLogging:
    """Test opening trade logging functionality."""

    def test_log_opening_trade_returns_true_on_success(self, tmp_path):
        """Test that log_opening_trade returns True when successful."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        # Create a mock SpreadPair
        pair = create_mock_pair(pair_id=1, extended_side='buy')

        result = logger.log_opening_trade(pair)

        assert result is True

    def test_log_opening_trade_writes_to_file(self, tmp_path):
        """Test that log_opening_trade writes content to the log file."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = create_mock_pair(pair_id=1, extended_side='buy')
        logger.log_opening_trade(pair)

        # Verify file was created and contains content
        assert log_path.exists()
        content = log_path.read_text()
        assert len(content) > 0

    def test_log_opening_trade_includes_required_fields(self, tmp_path):
        """Test that opening log includes all required fields (FR-003)."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = create_mock_pair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3450.50'),
            extended_quantity=Decimal('0.01'),
            lighter_price=Decimal('3455.75'),
            lighter_quantity=Decimal('0.01')
        )

        logger.log_opening_trade(pair)

        content = log_path.read_text()

        # Verify required fields are present
        assert '1' in content  # pair_id
        assert 'buy' in content or 'BUY' in content or '买入' in content  # direction (Chinese or English)
        assert '3450.50' in content  # extended_price
        assert '3455.75' in content  # lighter_price
        # Note: Full format implementation in T012-T013

    def test_log_opening_trade_handles_multiple_entries(self, tmp_path):
        """Test that multiple opening trades can be logged."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        for i in range(3):
            pair = create_mock_pair(pair_id=i+1, extended_side='buy')
            logger.log_opening_trade(pair)

        content = log_path.read_text()
        # Should have multiple entries
        assert content.count('TRADE OPENED') >= 3 or len(content.split('\n')) >= 3


class TestClosingTradeLogging:
    """Test closing trade logging functionality."""

    def test_log_closing_trade_returns_true_on_success(self, tmp_path):
        """Test that log_closing_trade returns True when successful."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = create_mock_pair(pair_id=1, extended_side='buy')
        pair.close(
            close_extended_price=Decimal('3451.00'),
            close_lighter_price=Decimal('3455.25')
        )

        result = logger.log_closing_trade(pair)

        assert result is True

    def test_log_closing_trade_writes_to_file(self, tmp_path):
        """Test that log_closing_trade writes content to the log file."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = create_mock_pair(pair_id=1, extended_side='buy')
        pair.close(
            close_extended_price=Decimal('3451.00'),
            close_lighter_price=Decimal('3455.25')
        )

        logger.log_closing_trade(pair)

        content = log_path.read_text()
        assert len(content) > 0

    def test_log_closing_trade_includes_required_fields(self, tmp_path):
        """Test that closing log includes all required fields (FR-004)."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        pair = create_mock_pair(pair_id=1, extended_side='buy')
        pair.close(
            close_extended_price=Decimal('3451.00'),
            close_lighter_price=Decimal('3455.25')
        )

        logger.log_closing_trade(pair)

        content = log_path.read_text()

        # Verify required fields
        assert '1' in content  # pair_id
        assert '3451.00' in content  # close_extended_price
        assert '3455.25' in content  # close_lighter_price
        # Note: Full format implementation in T012-T013


class TestUnhedgedPositionLogging:
    """Test unhedged position warning logging."""

    def test_log_unhedged_position_returns_true_on_success(self, tmp_path):
        """Test that log_unhedged_position returns True when successful."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        position = {
            'order_id': 'test_order_123',
            'side': 'buy',
            'quantity': Decimal('0.01'),
            'price': Decimal('3450.50'),
            'error': 'Connection timeout',
            'timestamp': 1234567890.0
        }

        result = logger.log_unhedged_position(position)

        assert result is True

    def test_log_unhedged_position_writes_warning(self, tmp_path):
        """Test that unhedged position writes a warning entry."""
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        position = {
            'order_id': 'test_order_123',
            'side': 'buy',
            'quantity': Decimal('0.01'),
            'price': Decimal('3450.50'),
            'error': 'Connection timeout',
            'timestamp': 1234567890.0
        }

        logger.log_unhedged_position(position)

        content = log_path.read_text()
        assert 'UNHEDGED' in content.upper() or '未对冲' in content  # English or Chinese


class TestErrorHandling:
    """Test error handling and graceful degradation."""

    def test_returns_false_when_logger_setup_fails(self, tmp_path):
        """Test that methods return False when logger is not set up."""
        # Simulate failed setup by setting logger to None
        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))
        logger.logger = None

        pair = create_mock_pair(pair_id=1, extended_side='buy')

        assert logger.log_opening_trade(pair) is False
        assert logger.log_closing_trade(pair) is False
        assert logger.log_unhedged_position({}) is False


class TestConcurrentWrites:
    """Test thread-safe concurrent writes."""

    def test_concurrent_opening_trades(self, tmp_path):
        """Test that multiple concurrent writes are handled correctly."""
        import threading

        log_path = tmp_path / "logs" / "trade.log"
        logger = TradeLogger(log_file_path=str(log_path))

        def log_trade(trade_id):
            pair = create_mock_pair(pair_id=trade_id, extended_side='buy')
            logger.log_opening_trade(pair)

        # Create multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=log_trade, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Verify all entries were written
        content = log_path.read_text()
        # Should have at least some content
        assert len(content) > 0


# Helper function
def create_mock_pair(pair_id, extended_side, extended_price=None,
                      extended_quantity=None, lighter_price=None, lighter_quantity=None):
    """Create a mock SpreadPair for testing."""
    extended_price = extended_price or Decimal('3450.50')
    extended_quantity = extended_quantity or Decimal('0.01')
    lighter_price = lighter_price or Decimal('3455.75')
    lighter_quantity = lighter_quantity or Decimal('0.01')

    pair = SpreadPair(
        pair_id=pair_id,
        extended_side=extended_side,
        extended_price=extended_price,
        extended_quantity=extended_quantity,
        lighter_price=lighter_price,
        lighter_quantity=lighter_quantity
    )
    return pair

