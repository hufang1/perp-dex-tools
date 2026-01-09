"""
Hedge Mode Configuration
"""

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class HedgeConfig:
    """Configuration for hedge mode trading bots

    Supports multiple exchanges: backpack, extended, apex, grvt, edgex, nado
    """

    # Basic Configuration
    exchange: str = 'edgex'
    ticker: str = 'BTC'
    order_quantity: Decimal = Decimal('0.01')
    iterations: int = 20
    fill_timeout: int = 5
    sleep_time: int = 0
    max_position: Decimal = Decimal('0')
    env_file: str = '.env'

    def __post_init__(self):
        """Validate configuration parameters"""
        supported_exchanges = ['backpack', 'extended', 'apex', 'grvt', 'edgex', 'nado']
        if self.exchange not in supported_exchanges:
            raise ValueError(
                f"exchange must be one of {supported_exchanges}, got '{self.exchange}'"
            )

        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be greater than 0")

        if self.iterations <= 0:
            raise ValueError("iterations must be greater than 0")

        if self.fill_timeout <= 0:
            raise ValueError("fill_timeout must be greater than 0")

        if self.sleep_time < 0:
            raise ValueError("sleep_time must be non-negative")

        if self.max_position < 0:
            raise ValueError("max_position must be non-negative")

    @classmethod
    def from_env(cls) -> 'HedgeConfig':
        """Create HedgeConfig instance from environment variables

        Supported environment variables:
        - HEDGE_EXCHANGE: Exchange name (default: edgex)
        - HEDGE_TICKER: Trading pair (default: BTC)
        - HEDGE_ORDER_QUANTITY: Order size (default: 0.01)
        - HEDGE_ITERATIONS: Number of iterations (default: 20)
        - HEDGE_FILL_TIMEOUT: Fill timeout in seconds (default: 5)
        - HEDGE_SLEEP_TIME: Sleep time between iterations (default: 0)
        - HEDGE_MAX_POSITION: Maximum position size (default: 0)
        - ENV_FILE: Environment file path (default: .env)
        """
        return cls(
            exchange=os.getenv('HEDGE_EXCHANGE', 'edgex'),
            ticker=os.getenv('HEDGE_TICKER', 'BTC'),
            order_quantity=Decimal(os.getenv('HEDGE_ORDER_QUANTITY', '0.01')),
            iterations=int(os.getenv('HEDGE_ITERATIONS', '20')),
            fill_timeout=int(os.getenv('HEDGE_FILL_TIMEOUT', '5')),
            sleep_time=int(os.getenv('HEDGE_SLEEP_TIME', '0')),
            max_position=Decimal(os.getenv('HEDGE_MAX_POSITION', '0')),
            env_file=os.getenv('ENV_FILE', '.env')
        )


# Default configuration instance
config = HedgeConfig()
