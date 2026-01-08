"""
Shared test fixtures for spread arbitrage tests

This module provides common fixtures used across multiple test files.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from spread.config import SpreadArbConfig
from spread.spread_pair import SpreadPair
from spread.bot import SpreadArbitrageBot
from spread.calculator import SpreadCalculator


@pytest.fixture
def default_config():
    """
    Default test configuration

    Provides a standard SpreadArbConfig with typical test values.
    """
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),
        profit_target_rate=Decimal('0.0005'),
        time_close_threshold=60,
        max_holding_time=300
    )


@pytest.fixture
def sample_config():
    """
    Sample configuration for threshold tests

    Similar to default_config but with explicit latency_buffer.
    """
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),
        latency_buffer=Decimal('0.0001')
    )


@pytest.fixture
def closing_config():
    """
    Configuration for closing strategy tests

    Includes all closing strategy parameters.
    """
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),
        profit_target_rate=Decimal('0.0005'),
        time_close_threshold=60,
        max_holding_time=300,
        enable_profit_target=True,
        enable_time_close=True,
        enable_stop_loss=True,
        stop_loss_usdt=Decimal('5')
    )


@pytest.fixture
def calculator(sample_config):
    """
    Calculator instance for spread opportunity tests
    """
    return SpreadCalculator(sample_config)


@pytest.fixture
def mock_bot(default_config):
    """
    Mocked bot instance for integration tests

    Creates a SpreadArbitrageBot with mocked exchange clients.
    """
    extended_client = Mock()
    lighter_client = Mock()

    extended_client.setup_order_update_handler = Mock()

    bot = SpreadArbitrageBot(default_config, extended_client, lighter_client)
    return bot


@pytest.fixture
def sample_spread_pair():
    """
    Sample spread pair for testing

    Creates a typical SpreadPair with test data.
    """
    return SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014'),
        extended_order_id='EXT_12345',
        lighter_order_id='LT_67890'
    )


@pytest.fixture
def closed_spread_pair():
    """
    Closed spread pair for testing

    Creates a SpreadPair that has been closed with PnL data.
    """
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014'),
        extended_order_id='EXT_12345',
        lighter_order_id='LT_67890'
    )

    pair.close(
        close_extended_price=Decimal('2502.00'),
        close_lighter_price=Decimal('2500.00')
    )

    pair.close_extended_order_id = 'EXT_CLOSE_999'
    pair.close_lighter_order_id = 'LT_CLOSE_888'

    return pair
