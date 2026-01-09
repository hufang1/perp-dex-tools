#!/usr/bin/env python3
"""
Hedge Mode Entry Point

This script serves as the main entry point for hedge mode trading.
It imports and runs the appropriate hedge mode implementation based on the exchange parameter.

Usage:
    python hedge_mode.py --exchange <exchange> [--v2]

Configuration is loaded from hedge/config.py - only --exchange argument is required

Supported exchanges:
    - backpack: Uses HedgeBot from hedge_mode_bp.py (Backpack + Lighter)
    - extended: Uses HedgeBot from hedge_mode_ext.py (Extended + Lighter)
    - apex: Uses HedgeBot from hedge_mode_apex.py (Apex + Lighter)
    - grvt: Uses HedgeBot from hedge_mode_grvt.py (GRVT + Lighter)
      Use --v2 flag to use hedge_mode_grvt_v2.py instead
    - edgex: Uses HedgeBot from hedge_mode_edgex.py (edgeX + Lighter)
    - nado: Uses HedgeBot from hedge_mode_nado.py (Nado + Lighter)

Cross-platform compatibility:
    - Works on Linux, macOS, and Windows
    - Direct imports instead of subprocess calls for better performance
"""

import asyncio
import sys
import argparse
from decimal import Decimal
from pathlib import Path
import dotenv


def parse_arguments():
    """Parse command line arguments - only --exchange and --v2 are needed."""
    parser = argparse.ArgumentParser(
        description='Hedge Mode Trading Bot Entry Point',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python hedge_mode.py --exchange edgex
    python hedge_mode.py --exchange backpack
    python hedge_mode.py --exchange grvt --v2

Configuration is loaded from hedge/config.py - modify that file to change:
    - ticker (default: BTC)
    - order_quantity (default: 0.01)
    - iterations (default: 20)
    - fill_timeout (default: 5)
    - sleep_time (default: 0)
    - max_position (default: 0)
    - env_file (default: .env)
        """
    )

    parser.add_argument('--exchange', type=str, required=True,
                        help='Exchange to use (backpack, extended, apex, grvt, edgex, nado)')
    parser.add_argument('--v2', action='store_true',
                        help='Use v2 implementation (currently only supported for grvt exchange)')

    return parser.parse_args()


def validate_exchange(exchange):
    """Validate that the exchange is supported."""
    supported_exchanges = ['backpack', 'extended', 'apex', 'grvt', 'edgex', 'nado']
    if exchange.lower() not in supported_exchanges:
        print(f"Error: Unsupported exchange '{exchange}'")
        print(f"Supported exchanges: {', '.join(supported_exchanges)}")
        sys.exit(1)


def get_hedge_bot_class(exchange, v2=False):
    """Import and return the appropriate HedgeBot class."""
    try:
        if exchange.lower() == 'backpack':
            from hedge.hedge_mode_bp import HedgeBot
            return HedgeBot
        elif exchange.lower() == 'extended':
            from hedge.hedge_mode_ext import HedgeBot
            return HedgeBot
        elif exchange.lower() == 'apex':
            from hedge.hedge_mode_apex import HedgeBot
            return HedgeBot
        elif exchange.lower() == 'grvt':
            if v2:
                from hedge.hedge_mode_grvt_v2 import HedgeBot
            else:
                from hedge.hedge_mode_grvt import HedgeBot
            return HedgeBot
        elif exchange.lower() == 'edgex':
            from hedge.hedge_mode_edgex import HedgeBot
            return HedgeBot
        elif exchange.lower() == 'nado':
            from hedge.hedge_mode_nado import HedgeBot
            return HedgeBot
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
    except ImportError as e:
        print(f"Error importing hedge mode implementation: {e}")
        sys.exit(1)


async def main():
    """Main entry point that creates and runs the appropriate hedge bot."""
    args = parse_arguments()

    # Import config from hedge/config.py
    from hedge.config import config

    env_path = Path(config.env_file)
    if not env_path.exists():
        print(f"Env file not found: {env_path.resolve()}")
        sys.exit(1)
    dotenv.load_dotenv(config.env_file)

    # Override exchange from command line
    exchange = args.exchange.lower()

    # Validate exchange
    validate_exchange(exchange)

    # Validate v2 flag usage
    if args.v2 and exchange != 'grvt':
        print(f"Error: --v2 flag is only supported for grvt exchange")
        sys.exit(1)

    # Get the appropriate HedgeBot class
    try:
        HedgeBotClass = get_hedge_bot_class(exchange, v2=args.v2)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    version_str = " v2" if args.v2 else ""
    print(f"Starting hedge mode for {exchange} exchange{version_str}...")
    print(f"Ticker: {config.ticker}, Size: {config.order_quantity}, Iterations: {config.iterations}")
    print(f"Fill Timeout: {config.fill_timeout}s, Sleep Time: {config.sleep_time}s")
    print("-" * 50)

    try:
        # v2 bot has different constructor signature (no iterations/sleep_time)
        if args.v2 and exchange == 'grvt':
            bot = HedgeBotClass(
                ticker=config.ticker.upper(),
                order_quantity=config.order_quantity,
                fill_timeout=config.fill_timeout,
                max_position=config.max_position
            )
        elif exchange in ['backpack', 'edgex', 'nado', 'grvt']:
            bot = HedgeBotClass(
                ticker=config.ticker.upper(),
                order_quantity=config.order_quantity,
                fill_timeout=config.fill_timeout,
                iterations=config.iterations,
                sleep_time=config.sleep_time,
                max_position=config.max_position
            )
        else:
            bot = HedgeBotClass(
                ticker=config.ticker.upper(),
                order_quantity=config.order_quantity,
                fill_timeout=config.fill_timeout,
                iterations=config.iterations,
                sleep_time=config.sleep_time
            )

        # Run the bot
        await bot.run()

    except KeyboardInterrupt:
        print("\nHedge mode interrupted by user")
        return 1
    except Exception as e:
        print(f"Error running hedge mode: {e}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
