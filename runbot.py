#!/usr/bin/env python3
"""
Modular Trading Bot - Supports multiple exchanges

Configuration is loaded from trading_config.py - no command-line arguments needed
"""

import asyncio
import logging
from pathlib import Path
import sys
import dotenv
from decimal import Decimal
from trading_bot import TradingBot
from exchanges import ExchangeFactory


def setup_logging(log_level: str):
    """Setup global logging configuration."""
    # Convert string level to logging constant
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Clear any existing handlers to prevent duplicates
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure root logger WITHOUT adding a console handler
    # This prevents duplicate logs when TradingLogger adds its own console handler
    root_logger.setLevel(level)

    # Suppress websockets debug logs unless DEBUG level is explicitly requested
    if log_level.upper() != 'DEBUG':
        logging.getLogger('websockets').setLevel(logging.WARNING)

    # Suppress other noisy loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)

    # Suppress Lighter SDK debug logs
    logging.getLogger('lighter').setLevel(logging.WARNING)
    # Also suppress any root logger DEBUG messages that might be coming from Lighter
    if log_level.upper() != 'DEBUG':
        # Set root logger to WARNING to suppress DEBUG messages from Lighter SDK
        root_logger.setLevel(logging.WARNING)


async def main():
    """Main entry point."""
    # Import config from trading_config.py
    from trading_config import config

    # Setup logging first
    setup_logging("WARNING")

    # Validate boost-mode can only be used with aster and backpack exchange
    if config.boost_mode and config.exchange.lower() not in ['aster', 'backpack']:
        print(f"Error: boost_mode can only be used when exchange is 'aster' or 'backpack'. "
              f"Current exchange: {config.exchange}")
        sys.exit(1)

    env_path = Path(config.env_file)
    if not env_path.exists():
        print(f"Env file not found: {env_path.resolve()}")
        sys.exit(1)
    dotenv.load_dotenv(config.env_file)

    print(f"Starting trading bot on {config.exchange} exchange...")
    print(f"Ticker: {config.ticker}, Quantity: {config.quantity}")
    print(f"Direction: {config.direction}, Take Profit: {config.take_profit}")
    print("-" * 50)

    # Create and run the bot
    bot = TradingBot(config)
    try:
        await bot.run()
    except Exception as e:
        print(f"Bot execution failed: {e}")
        # The bot's run method already handles graceful shutdown
        return


if __name__ == "__main__":
    asyncio.run(main())
