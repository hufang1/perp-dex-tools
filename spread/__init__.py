"""
Spread Arbitrage Module
Lighter-Extended 单向价差收敛套利系统
"""

# 导入必须在添加项目根目录到 sys.path 后才能工作
# 这个模块应该作为包使用：python -m spread.spread_arb_bot

__version__ = "1.0.0"
__author__ = "Hufangperp"
__description__ = "Lighter-Extended 单向价差收敛套利系统"

# 版本信息
__all__ = ["__version__", "__author__", "__description__"]

# 初始化日志配置 (016-spread-optimize)
from logger_config import setup_logging
import logging

setup_logging(level=logging.INFO, compact=True)

