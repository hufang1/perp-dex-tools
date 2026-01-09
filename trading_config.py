"""
Trading Bot Configuration
"""

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class TradingConfig:
    """Configuration for modular trading bot

    Supports multiple exchanges via ExchangeFactory
    """

    exchange: str = 'edgex'
    ticker: str = 'ETH'
    contract_id: str = ''
    tick_size: Decimal = Decimal('0')
    quantity: Decimal = Decimal('0.1')
    take_profit: Decimal = Decimal('0.02')
    direction: str = 'buy'
    max_orders: int = 40
    wait_time: int = 450
    grid_step: Decimal = Decimal('-100')
    stop_price: Decimal = Decimal('-1')
    pause_price: Decimal = Decimal('-1')
    boost_mode: bool = False
    env_file: str = '.env'

    def __post_init__(self):
        """Validate configuration parameters"""
        # Exchange validation will be done by ExchangeFactory at runtime
        # but we can do basic validation here

        if self.quantity <= 0:
            raise ValueError("quantity must be greater than 0")

        if self.take_profit <= 0:
            raise ValueError("take_profit must be greater than 0")

        if self.direction not in ['buy', 'sell']:
            raise ValueError("direction must be 'buy' or 'sell'")

        if self.max_orders <= 0:
            raise ValueError("max_orders must be greater than 0")

        if self.wait_time <= 0:
            raise ValueError("wait_time must be greater than 0")

        if self.boost_mode and self.exchange not in ['aster', 'backpack']:
            raise ValueError(
                "boost_mode is only supported for aster and backpack exchanges"
            )

    @classmethod
    def from_env(cls) -> 'TradingConfig':
        """Create TradingConfig instance from environment variables

        Supported environment variables:
        - TRADING_EXCHANGE: Exchange name (default: edgex)
        - TRADING_TICKER: Trading pair (default: ETH)
        - TRADING_QUANTITY: Order quantity (default: 0.1)
        - TRADING_TAKE_PROFIT: Take profit amount (default: 0.02)
        - TRADING_DIRECTION: Trading direction (default: buy)
        - TRADING_MAX_ORDERS: Maximum active orders (default: 40)
        - TRADING_WAIT_TIME: Wait time between orders (default: 450)
        - TRADING_GRID_STEP: Grid step percentage (default: -100)
        - TRADING_STOP_PRICE: Stop trading price (default: -1)
        - TRADING_PAUSE_PRICE: Pause trading price (default: -1)
        - TRADING_BOOST_MODE: Enable boost mode (default: False)
        - ENV_FILE: Environment file path (default: .env)
        """
        return cls(
            exchange=os.getenv('TRADING_EXCHANGE', 'edgex'),
            ticker=os.getenv('TRADING_TICKER', 'ETH'),
            quantity=Decimal(os.getenv('TRADING_QUANTITY', '0.1')),
            take_profit=Decimal(os.getenv('TRADING_TAKE_PROFIT', '0.02')),
            direction=os.getenv('TRADING_DIRECTION', 'buy'),
            max_orders=int(os.getenv('TRADING_MAX_ORDERS', '40')),
            wait_time=int(os.getenv('TRADING_WAIT_TIME', '450')),
            grid_step=Decimal(os.getenv('TRADING_GRID_STEP', '-100')),
            stop_price=Decimal(os.getenv('TRADING_STOP_PRICE', '-1')),
            pause_price=Decimal(os.getenv('TRADING_PAUSE_PRICE', '-1')),
            boost_mode=os.getenv('TRADING_BOOST_MODE', 'False').lower() == 'true',
            env_file=os.getenv('ENV_FILE', '.env')
        )


# Default configuration instance
config = TradingConfig()
