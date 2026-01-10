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
- T036-T042: Enhanced logging with spread snapshots, close analysis, and position balance
- T096: Cost breakdown formatting for detailed profit attribution
"""

import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from .spread_pair import SpreadPair
from .models import SpreadSnapshot, SpreadChange, CloseDecision, PositionBalance

# TYPE_CHECKING导入避免循环依赖
if TYPE_CHECKING:
    from .cost_calculator import TradeCostBreakdown


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

    def log_spread_snapshot(self, snapshot: SpreadSnapshot) -> bool:
        """
        T036: 记录价差快照

        记录某一时刻的价差状态，包括订单簿价格和套利方向。

        Args:
            snapshot: SpreadSnapshot对象

        Returns:
            True if logging succeeded, False otherwise
        """
        if self.logger is None:
            return False

        try:
            entry = self._format_spread_snapshot(snapshot)
            self.logger.info(entry)
            return True
        except Exception as e:
            logging.error(f"Failed to log spread snapshot: {e}")
            return False

    def log_close_analysis(
        self,
        pair: SpreadPair,
        decision: CloseDecision
    ) -> bool:
        """
        T037: 记录平仓分析

        记录平仓决策的详细分析，包括优先级、理由、价差变化和盈亏。

        Args:
            pair: SpreadPair对象
            decision: CloseDecision对象

        Returns:
            True if logging succeeded, False otherwise
        """
        if self.logger is None:
            return False

        try:
            entry = self._format_close_analysis(pair, decision)
            self.logger.info(entry)
            return True
        except Exception as e:
            logging.error(f"Failed to log close analysis: {e}")
            return False

    def log_position_balance(self, balance: PositionBalance) -> bool:
        """
        T038: 记录仓位平衡状态

        记录两个交易所的仓位平衡情况，包括差异和警告级别。

        Args:
            balance: PositionBalance对象

        Returns:
            True if logging succeeded, False otherwise
        """
        if self.logger is None:
            return False

        try:
            entry = self._format_position_balance(balance)
            # 根据警告级别选择日志级别
            if balance.warning_level == "CRITICAL":
                self.logger.error(entry)
            elif balance.warning_level == "WARN":
                self.logger.warning(entry)
            else:
                self.logger.info(entry)
            return True
        except Exception as e:
            logging.error(f"Failed to log position balance: {e}")
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
        T031-T032: 添加 real_spread 和 spread_cost_breakdown 字段
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
        ]

        # T050-T052: 添加 order_type, post_only, is_rejected 字段
        if hasattr(pair, 'order_type') and pair.order_type is not None:
            lines.append(f"  订单类型: {pair.order_type}")  # 'maker' 或 'taker'
        if hasattr(pair, 'post_only') and pair.post_only is not None:
            lines.append(f"  Post-Only: {'是' if pair.post_only else '否'}")
        if hasattr(pair, 'is_rejected') and pair.is_rejected is not None:
            lines.append(f"  被拒绝: {'是' if pair.is_rejected else '否'}")

        lines.extend([
            "",
            "Lighter 交易所:",
            f"  订单ID: {pair.open_lighter_order_id or 'N/A'}",
            f"  价格: ${float(pair.lighter_price):.2f}",
            f"  数量: {float(pair.lighter_quantity):.4f}",
            "",
            "价差信息:",
            f"  绝对价差: ${float(spread_absolute):.2f}",
            f"  价差率: {float(spread_rate):.4%}",
        ])

        # T031: 添加 real_spread 字段
        if hasattr(pair, 'real_spread') and pair.real_spread is not None:
            lines.extend([
                "",
                "真实价差计算:",
                f"  计算方式: {'对手价' if pair.real_spread else '中间价'}",
            ])

        # T032: 添加 spread_cost_breakdown 字段
        if hasattr(pair, 'spread_cost_breakdown') and pair.spread_cost_breakdown is not None:
            costs = pair.spread_cost_breakdown
            lines.extend([
                "",
                "成本分解:",
                f"  Extended点差成本: {float(costs.extended_cost):.4%}",
                f"  Lighter点差成本: {float(costs.lighter_cost):.4%}",
                f"  总成本率: {float(costs.total_cost_rate):.4%}",
            ])

        lines.append("=====================")

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
        ]

        # T077-T078: 添加 close_reason 和 close_priority 字段
        if hasattr(pair, 'close_reason') and pair.close_reason is not None:
            lines.append(f"平仓原因: {pair.close_reason}")
        if hasattr(pair, 'close_priority') and pair.close_priority is not None:
            lines.append(f"平仓优先级: P{pair.close_priority}")

        lines.extend([
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
        ])

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

    def _format_spread_snapshot(self, snapshot: SpreadSnapshot) -> str:
        """
        T039: 格式化价差快照日志

        包含时间戳、订单簿价格、价差和套利方向。
        """
        timestamp = datetime.fromtimestamp(snapshot.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        direction_display = {
            "long_spread": "做多价差 (Extended买, Lighter卖)",
            "short_spread": "做空价差 (Extended卖, Lighter买)"
        }.get(snapshot.arbitrage_direction, "未知")

        lines = [
            "=== 价差快照 ===",
            f"时间戳: {timestamp}",
            "",
            "Extended 订单簿:",
            f"  买一价: ${float(snapshot.extended_bid):.2f}",
            f"  卖一价: ${float(snapshot.extended_ask):.2f}",
            f"  中间价: ${float(snapshot.extended_mid):.2f}",
            "",
            "Lighter 订单簿:",
            f"  买一价: ${float(snapshot.lighter_bid):.2f}",
            f"  卖一价: ${float(snapshot.lighter_ask):.2f}",
            f"  中间价: ${float(snapshot.lighter_mid):.2f}",
            "",
            "价差信息:",
            f"  绝对价差: ${float(snapshot.spread):.2f}",
            f"  价差率: {float(snapshot.spread_rate):.4%}",
            f"  价差符号: {snapshot.spread_sign}",
            f"  套利方向: {direction_display}",
            "==================="
        ]

        return '\n'.join(lines)

    def _format_close_analysis(
        self,
        pair: SpreadPair,
        decision: CloseDecision
    ) -> str:
        """
        T040: 格式化平仓分析日志

        包含平仓决策详情、价差变化、盈亏分析和持仓时间。
        """
        timestamp = datetime.fromtimestamp(decision.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        direction = "做多" if pair.extended_side == 'buy' else "做空"

        lines = [
            "=== 平仓分析 ===",
            f"时间戳: {timestamp}",
            f"套利对ID: {pair.pair_id}",
            f"方向: {direction}",
            "",
            "平仓决策:",
            f"  优先级: P{decision.priority}",
            f"  理由代码: {decision.reason_code}",
            f"  理由: {decision.reason}",
            f"  警告级别: {'是' if decision.is_warning else '否'}",
            "",
            "价差变化:",
            f"  开仓价差: ${float(decision.spread_change.open_spread):.2f}",
            f"  当前价差: ${float(decision.spread_change.current_spread):.2f}",
            f"  价差变化: ${float(decision.spread_change.spread_delta):.2f} ({float(decision.spread_change.spread_change_rate):.2%})",
            f"  状态: {decision.spread_change.status}",
            "",
            "盈亏分析:",
            f"  未实现盈亏: ${float(decision.unrealized_pnl):.4f}",
            f"  盈亏率: {float(decision.pnl_rate):.4%}",
            f"  持仓时间: {decision.holding_time:.1f} 秒",
            "",
            "平仓价格:",
            f"  Extended: ${float(decision.extended_close_price):.2f}" if decision.extended_close_price else "  Extended: N/A",
            f"  Lighter: ${float(decision.lighter_close_price):.2f}" if decision.lighter_close_price else "  Lighter: N/A",
            "==================="
        ]

        return '\n'.join(lines)

    def _format_position_balance(self, balance: PositionBalance) -> str:
        """
        T041: 格式化仓位平衡日志

        包含两个交易所的总仓位、差异和警告级别。
        """
        timestamp = datetime.fromtimestamp(balance.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        warning_display = {
            "OK": "✅ 平衡",
            "WARN": "⚠️ 失衡",
            "CRITICAL": "🚨 严重失衡"
        }.get(balance.warning_level, balance.warning_level)

        lines = [
            "=== 仓位平衡状态 ===",
            f"时间戳: {timestamp}",
            "",
            "仓位总览:",
            f"  Extended总仓位: {float(balance.extended_total_qty):.4f}",
            f"  Lighter总仓位: {float(balance.lighter_total_qty):.4f}",
            f"  差异: {float(balance.diff_qty):.4f}",
            f"  差异率: {float(balance.diff_rate):.2%}",
            "",
            f"状态: {warning_display}",
            f"失衡: {'是' if balance.is_imbalanced else '否'}",
            "==================="
        ]

        return '\n'.join(lines)

    # ==================== T096: 成本分解格式化方法 ====================

    def _format_cost_breakdown(self, cost_breakdown: 'TradeCostBreakdown') -> str:
        """
        T096: 格式化成本分解信息

        Args:
            cost_breakdown: TradeCostBreakdown对象

        Returns:
            格式化的成本分解字符串
        """
        lines = [
            "=== 成本分解 ===",
            "",
            "开仓成本:",
            f"  Extended手续费: ${float(cost_breakdown.entry_extended_fee):.4f}",
            f"  Lighter手续费: ${float(cost_breakdown.entry_lighter_fee):.4f}",
            f"  Extended点差成本: ${float(cost_breakdown.entry_extended_spread_cost):.4f}",
            f"  Lighter点差成本: ${float(cost_breakdown.entry_lighter_spread_cost):.4f}",
            f"  开仓滑点: ${float(cost_breakdown.entry_slippage_cost):.4f}",
            f"  开仓总成本: ${float(cost_breakdown.total_entry_cost):.4f}",
            "",
            "平仓成本:",
            f"  Extended手续费: ${float(cost_breakdown.exit_extended_fee):.4f}",
            f"  Lighter手续费: ${float(cost_breakdown.exit_lighter_fee):.4f}",
            f"  Extended点差成本: ${float(cost_breakdown.exit_extended_spread_cost):.4f}",
            f"  Lighter点差成本: ${float(cost_breakdown.exit_lighter_spread_cost):.4f}",
            f"  平仓滑点: ${float(cost_breakdown.exit_slippage_cost):.4f}",
            f"  平仓总成本: ${float(cost_breakdown.total_exit_cost):.4f}",
            "",
            "总成本:",
            f"  总手续费: ${float(cost_breakdown.total_fees):.4f}",
            f"  总点差成本: ${float(cost_breakdown.total_spread_cost):.4f}",
            f"  总滑点: ${float(cost_breakdown.total_slippage_cost):.4f}",
            f"  总成本: ${float(cost_breakdown.total_cost):.4f}",
            "",
            "收益:",
            f"  毛收益: ${float(cost_breakdown.gross_profit):.4f}",
            f"  净收益: ${float(cost_breakdown.net_profit):.4f}",
            f"  收益率: {float(cost_breakdown.profit_rate):.4%}",
            "==============="
        ]

        return '\n'.join(lines)
