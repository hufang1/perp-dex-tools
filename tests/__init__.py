"""
Tests for Spread Arbitrage Module
"""
import pytest
import asyncio
from decimal import Decimal

# pytest asyncio configuration
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_order_book_data():
    """Sample order book data for testing."""
    return {
        "exchange": "test",
        "symbol": "BTC-USD",
        "bids": {
            Decimal("99990.0"): Decimal("1.0"),
            Decimal("99980.0"): Decimal("2.0"),
            Decimal("99970.0"): Decimal("3.0"),
        },
        "asks": {
            Decimal("100010.0"): Decimal("1.0"),
            Decimal("100020.0"): Decimal("2.0"),
            Decimal("100030.0"): Decimal("3.0"),
        },
    }


@pytest.fixture
def sample_config():
    """Sample bot configuration for testing."""
    from models import BotConfig
    return BotConfig(
        symbol="BTC",
        target_quantity=Decimal("0.01"),
        min_spread_threshold=Decimal("0.002"),
        slippage_buffer=Decimal("0.0005"),
        min_profit=Decimal("0.001"),
        max_spread=Decimal("0.05"),
        single_side_timeout=3.0,
    )
