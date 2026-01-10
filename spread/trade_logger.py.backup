"""
Trade Logger Module for Spread Arbitrage

This module provides detailed logging of spread arbitrage trades for verification
against actual exchange positions. It enables operators to detect discrepancies
between calculated profits and real exchange balances.

Features:
- Automatic logging of opening and closing trades
- Step-by-step PnL calculation breakdown
- Human-readable format for manual verification
- Thread-safe atomic writes
- Graceful error handling (never blocks trading)
"""

import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from .spread_pair import SpreadPair


class TradeLogger:
    """
    Handles detailed logging of spread arbitrage trades for verification purposes.

    This logger creates human-readable log entries that enable operators to
    verify calculated profits against actual exchange positions. All logging
    failures are handled gracefully to ensure trading continues uninterrupted.
    """

    def __init__(self, log_file_path: str = "logs/trade.log"):
        """
        Initialize the trade logger.

        Args:
            log_file_path: Path to the trade log file (default: logs/trade.log)

        Raises:
            OSError: If log directory cannot be created
        """
        self.log_file_path = log_file_path
        self.logger = None
        self._setup_logger()

    def _setup_logger(self):
        """
        Setup the file logger with directory creation and error handling.

        Creates the logs directory if it doesn't exist and configures a
        file handler for atomic, thread-safe writes.
        """
        try:
            # Create logs directory if it doesn't exist
            log_path = Path(self.log_file_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Create logger
            self.logger = logging.getLogger("TradeLogger")
            self.logger.setLevel(logging.INFO)

            # Remove existing handlers to avoid duplicates
            self.logger.handlers.clear()

            # Create file handler with append mode
            file_handler = logging.FileHandler(
                self.log_file_path,
                mode='a',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)

            # Create formatter (plain text for human readability)
            formatter = logging.Formatter('%(message)s')
            file_handler.setFormatter(formatter)

            # Add handler to logger
            self.logger.addHandler(file_handler)

            # Prevent propagation to avoid duplicate logs
            self.logger.propagate = False

        except OSError as e:
            # Log the error but don't raise - we'll handle gracefully in methods
            logging.error(f"Failed to setup trade logger: {e}")
            self.logger = None

    def log_opening_trade(self, pair: SpreadPair) -> bool:
        """
        Log a successfully opened spread pair position.

        Args:
            pair: The SpreadPair object containing opening trade details

        Returns:
            True if logging succeeded, False otherwise
        """
        if self.logger is None:
            return False

        try:
            # Build opening log entry
            entry = self._format_opening_entry(pair)
            self.logger.info(entry)
            return True
        except Exception as e:
            logging.error(f"Failed to log opening trade for pair #{pair.pair_id}: {e}")
            return False

    def log_closing_trade(self, pair: SpreadPair) -> bool:
        """
        Log a successfully closed spread pair position with PnL calculation.

        Args:
            pair: The SpreadPair object containing closing trade details

        Returns:
            True if logging succeeded, False otherwise
        """
        if self.logger is None:
            return False

        try:
            # Build closing log entry
            entry = self._format_closing_entry(pair)
            self.logger.info(entry)
            return True
        except Exception as e:
            logging.error(f"Failed to log closing trade for pair #{pair.pair_id}: {e}")
            return False

    def log_unhedged_position(self, position: Dict) -> bool:
        """
        Log a warning for an unhedged position (Extended filled, Lighter failed).

        Args:
            position: Dictionary containing unhedged position details

        Returns:
            True if logging succeeded, False otherwise
        """
        if self.logger is None:
            return False

        try:
            # Build unhedged position warning entry
            entry = self._format_unhedged_entry(position)
            self.logger.warning(entry)
            return True
        except Exception as e:
            logging.error(f"Failed to log unhedged position: {e}")
            return False

    def get_log_file_path(self) -> str:
        """
        Get the current log file path.

        Returns:
            Absolute path to the trade log file
        """
        return str(Path(self.log_file_path).absolute())

    def get_log_stats(self) -> Dict:
        """
        Get statistics about the log file.

        Returns:
            Dictionary with file statistics
        """
        try:
            log_path = Path(self.log_file_path)
            if not log_path.exists():
                return {
                    'file_path': self.get_log_file_path(),
                    'file_size_bytes': 0,
                    'file_size_mb': 0.0,
                    'entry_count': 0,
                    'last_modified': None
                }

            stat = log_path.stat()
            return {
                'file_path': self.get_log_file_path(),
                'file_size_bytes': stat.st_size,
                'file_size_mb': round(stat.st_size / (1024 * 1024), 2),
                'entry_count': 0,  # Not easily determinable without parsing
                'last_modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
        except Exception as e:
            logging.error(f"Failed to get log stats: {e}")
            return {
                'file_path': self.get_log_file_path(),
                'file_size_bytes': 0,
                'file_size_mb': 0.0,
                'entry_count': 0,
                'last_modified': None
            }

    def _format_opening_entry(self, pair: SpreadPair) -> str:
        """
        Format an opening trade log entry with all required fields (FR-003).

        Includes timestamp, pair ID, direction, exchange details (price, quantity,
        order ID), and spread calculation in a human-readable format.
        """
        # Calculate spread
        spread_absolute = pair.open_spread
        spread_rate = pair.open_spread_rate

        # Format timestamp
        timestamp = datetime.fromtimestamp(pair.open_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # Determine direction
        direction = "做多" if pair.extended_side == 'buy' else "做空"
        extended_display = "买入" if pair.extended_side == 'buy' else "卖出"
        lighter_display = "卖出" if pair.extended_side == 'buy' else "买入"

        # Build entry with Chinese labels
        lines = [
            "=== 交易开仓 ===",
            f"时间戳: {timestamp}",
            f"套利对ID: {pair.pair_id}",
            f"方向: {direction} (Extended {extended_display}, Lighter {lighter_display})",
            "",
            "Extended 交易所:",
            f"  订单ID: {pair.open_extended_order_id or 'N/A'}",
            f"  价格: ${float(pair.extended_price):.2f}",
            f"  数量: {float(pair.extended_quantity):.4f}",
            "",
            "Lighter 交易所:",
            f"  订单ID: {pair.open_lighter_order_id or 'N/A'}",
            f"  价格: ${float(pair.lighter_price):.2f}",
            f"  数量: {float(pair.lighter_quantity):.4f}",
            "",
            "价差信息:",
            f"  绝对价差: ${float(spread_absolute):.2f}",
            f"  价差率: {float(spread_rate):.4%}",
            "====================="
        ]

        return '\n'.join(lines)

    def _format_closing_entry(self, pair: SpreadPair) -> str:
        """
        Format a closing trade log entry with all required fields (FR-004).

        Includes timestamp, pair ID, opening prices (reference), closing prices,
        holding time, and PnL calculation breakdown.
        """
        # Calculate PnL components
        if pair.extended_side == 'buy':
            extended_pnl = (pair.close_extended_price - pair.extended_price) * pair.extended_quantity
            lighter_pnl = (pair.lighter_price - pair.close_lighter_price) * pair.lighter_quantity
        else:
            extended_pnl = (pair.extended_price - pair.close_extended_price) * pair.extended_quantity
            lighter_pnl = (pair.close_lighter_price - pair.lighter_price) * pair.lighter_quantity

        total_pnl = extended_pnl + lighter_pnl
        holding_time = pair.holding_time
        return_rate = total_pnl / (pair.extended_quantity * pair.extended_price)

        # Format timestamp
        timestamp = datetime.fromtimestamp(pair.close_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # Determine direction
        direction = "做多" if pair.extended_side == 'buy' else "做空"

        # Format PnL formulas
        if pair.extended_side == 'buy':
            extended_formula = f"(${float(pair.close_extended_price):.2f} - ${float(pair.extended_price):.2f}) × {float(pair.extended_quantity):.4f}"
        else:
            extended_formula = f"(${float(pair.extended_price):.2f} - ${float(pair.close_extended_price):.2f}) × {float(pair.extended_quantity):.4f}"

        if pair.extended_side == 'buy':
            lighter_formula = f"(${float(pair.lighter_price):.2f} - ${float(pair.close_lighter_price):.2f}) × {float(pair.lighter_quantity):.4f}"
        else:
            lighter_formula = f"(${float(pair.close_lighter_price):.2f} - ${float(pair.lighter_price):.2f}) × {float(pair.lighter_quantity):.4f}"

        # Build entry with Chinese labels
        lines = [
            "=== 交易平仓 ===",
            f"时间戳: {timestamp}",
            f"套利对ID: {pair.pair_id}",
            f"方向: {direction}",
            f"持仓时间: {holding_time:.1f} 秒",
            "",
            "开仓价格 (参考):",
            f"  Extended: ${float(pair.extended_price):.2f}",
            f"  Lighter: ${float(pair.lighter_price):.2f}",
            "",
            "平仓价格:",
            f"  Extended 订单ID: {pair.close_extended_order_id or 'N/A'}",
            f"  Extended 价格: ${float(pair.close_extended_price):.2f}",
            f"  Extended 数量: {float(pair.extended_quantity):.4f}",
            f"  Lighter 订单ID: {pair.close_lighter_order_id or 'N/A'}",
            f"  Lighter 价格: ${float(pair.close_lighter_price):.2f}",
            f"  Lighter 数量: {float(pair.lighter_quantity):.4f}",
            "",
            "盈亏计算:",
            f"  Extended 盈亏: {extended_formula} = ${float(extended_pnl):.4f}",
            f"  Lighter 盈亏: {lighter_formula} = ${float(lighter_pnl):.4f}",
            f"  总盈亏: ${float(extended_pnl):.4f} + ${float(lighter_pnl):.4f} = ${float(total_pnl):.4f}",
            f"  收益率: {float(return_rate):.4%}",
            "====================="
        ]

        return '\n'.join(lines)

    def _format_unhedged_entry(self, position: Dict) -> str:
        """
        Format an unhedged position warning entry with all required details.

        Logs when Extended fills but Lighter fails, requiring manual review.
        """
        timestamp = datetime.fromtimestamp(position.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        side = position.get('side', 'unknown')
        side_display = "买入" if side == 'buy' else "卖出"

        # Build warning entry with Chinese labels
        lines = [
            "=== 警告: 未对冲仓位 ===",
            f"时间戳: {timestamp}",
            f"套利对ID: {position.get('pair_id', 'N/A')} (开仓未完成)",
            "",
            "Extended 已成交:",
            f"  订单ID: {position.get('order_id', 'N/A')}",
            f"  方向: {side_display}",
            f"  价格: ${float(position.get('price', 0)):.2f}",
            f"  数量: {float(position.get('quantity', 0)):.4f}",
            "",
            "Lighter 失败:",
            f"  错误: {position.get('error', 'Unknown error')}",
            f"  预期方向: {'卖出' if side == 'buy' else '买入'}",
            f"  预期价格: ${float(position.get('expected_price', 0)):.2f}",
            "",
            "⚠️  未对冲仓位 - 需要人工审核",
            "========================================="
        ]

        return '\n'.join(lines)
