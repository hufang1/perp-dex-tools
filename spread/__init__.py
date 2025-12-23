"""
价差套利模块

Extended-Lighter 跨交易所价差套利策略
"""

from .config import SpreadArbConfig
from .spread_pair import SpreadPair
from .calculator import SpreadCalculator
from .order_manager import SpreadOrderManager
from .hedge_manager import HedgeManager
from .bot import SpreadArbitrageBot

__all__ = [
    'SpreadArbConfig',
    'SpreadPair',
    'SpreadCalculator',
    'SpreadOrderManager',
    'HedgeManager',
    'SpreadArbitrageBot',
]
