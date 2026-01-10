"""
交易分析器 - 分析交易表现和生成报告

功能:
- 计算胜率、盈亏比等指标
- 生成每日交易报告
- 提供策略优化建议
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Any, Optional

from .spread_pair import SpreadPair
from .data_collector import DataCollector


class TradeAnalyzer:
    """交易分析器 - 分析交易表现"""

    def __init__(self, data_collector: Optional[DataCollector] = None):
        """
        初始化交易分析器

        Args:
            data_collector: 数据收集器实例
        """
        self.data_collector = data_collector or DataCollector()
        self.logger = logging.getLogger("TradeAnalyzer")

    def calculate_win_rate(self, pairs: List[SpreadPair]) -> Dict[str, Any]:
        """
        T115: 计算胜率和相关指标

        Args:
            pairs: SpreadPair列表

        Returns:
            Dict: 包含胜率、盈亏比等指标的字典
        """
        if not pairs:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_count': 0,
                'loss_count': 0,
                'avg_profit': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0
            }

        # 只分析已平仓的交易
        closed_pairs = [p for p in pairs if p.is_closed and p.realized_pnl is not None]

        if not closed_pairs:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_count': 0,
                'loss_count': 0,
                'avg_profit': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0
            }

        total_trades = len(closed_pairs)
        profit_trades = [p for p in closed_pairs if p.realized_pnl > 0]
        loss_trades = [p for p in closed_pairs if p.realized_pnl <= 0]

        profit_count = len(profit_trades)
        loss_count = len(loss_trades)

        # 计算胜率
        win_rate = profit_count / total_trades if total_trades > 0 else 0.0

        # 计算平均盈利和亏损
        avg_profit = sum(p.realized_pnl for p in profit_trades) / profit_count if profit_count > 0 else 0.0
        avg_loss = sum(p.realized_pnl for p in loss_trades) / loss_count if loss_count > 0 else 0.0

        # 计算盈亏比（profit factor）
        total_profit = sum(p.realized_pnl for p in profit_trades)
        total_loss = abs(sum(p.realized_pnl for p in loss_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0.0

        # 最大盈利和亏损
        largest_win = max((p.realized_pnl for p in profit_trades), default=0.0)
        largest_loss = min((p.realized_pnl for p in loss_trades), default=0.0)

        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_count': profit_count,
            'loss_count': loss_count,
            'avg_profit': float(avg_profit),
            'avg_loss': float(avg_loss),
            'profit_factor': float(profit_factor),
            'largest_win': float(largest_win),
            'largest_loss': float(largest_loss),
            'total_profit': float(total_profit),
            'total_loss': float(total_loss),
            'net_profit': float(total_profit + total_loss)
        }

    def generate_daily_report(self, pairs: List[SpreadPair]) -> Dict[str, Any]:
        """
        T116: 生成每日交易报告

        Args:
            pairs: SpreadPair列表

        Returns:
            Dict: 每日报告数据
        """
        # 只分析已平仓的交易
        closed_pairs = [p for p in pairs if p.is_closed]

        if not closed_pairs:
            return {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'total_trades': 0,
                'metrics': self.calculate_win_rate(pairs),
                'by_hour': {},
                'by_direction': {},
                'by_close_reason': {}
            }

        # 按小时统计
        by_hour = {}
        # 按方向统计
        by_direction = {'long': [], 'short': []}
        # 按平仓原因统计
        by_close_reason = {}

        for pair in closed_pairs:
            if pair.realized_pnl is None:
                continue

            # 按小时
            close_time = datetime.fromtimestamp(pair.close_time) if pair.close_time else datetime.now()
            hour = close_time.hour
            if hour not in by_hour:
                by_hour[hour] = []
            by_hour[hour].append(pair.realized_pnl)

            # 按方向
            direction = 'long' if pair.extended_side == 'buy' else 'short'
            by_direction[direction].append(pair.realized_pnl)

            # 按平仓原因
            reason = getattr(pair, 'close_reason', 'unknown')
            if reason not in by_close_reason:
                by_close_reason[reason] = {'count': 0, 'pnl': 0.0}
            by_close_reason[reason]['count'] += 1
            by_close_reason[reason]['pnl'] += float(pair.realized_pnl)

        # 计算每小时的盈亏
        hourly_pnl = {}
        for hour, pnls in by_hour.items():
            hourly_pnl[hour] = {
                'trades': len(pnls),
                'pnl': sum(float(p) for p in pnls),
                'avg': sum(float(p) for p in pnls) / len(pnls)
            }

        # 计算按方向的盈亏
        direction_pnl = {}
        for direction, pnls in by_direction.items():
            direction_pnl[direction] = {
                'trades': len(pnls),
                'pnl': sum(float(p) for p in pnls),
                'avg': sum(float(p) for p in pnls) / len(pnls) if pnls else 0.0
            }

        # 基础指标
        metrics = self.calculate_win_rate(pairs)

        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_trades': len(closed_pairs),
            'metrics': metrics,
            'by_hour': hourly_pnl,
            'by_direction': direction_pnl,
            'by_close_reason': by_close_reason
        }

    def format_daily_report(self, report: Dict[str, Any]) -> str:
        """
        格式化每日报告为可读文本

        Args:
            report: 每日报告数据

        Returns:
            格式化的报告字符串
        """
        lines = [
            "=" * 60,
            f"每日交易报告 - {report['date']}",
            "=" * 60,
            "",
            "总体统计:",
            f"  总交易数: {report['total_trades']}",
        ]

        metrics = report.get('metrics', {})
        if metrics.get('total_trades', 0) > 0:
            lines.extend([
                f"  胜率: {metrics['win_rate']:.2%}",
                f"  盈利交易: {metrics['profit_count']}",
                f"  亏损交易: {metrics['loss_count']}",
                f"  平均盈利: ${metrics['avg_profit']:.2f}",
                f"  平均亏损: ${metrics['avg_loss']:.2f}",
                f"  盈亏比: {metrics['profit_factor']:.2f}",
                f"  最大盈利: ${metrics['largest_win']:.2f}",
                f"  最大亏损: ${metrics['largest_loss']:.2f}",
                f"  净盈亏: ${metrics['net_profit']:.2f}",
            ])

        # 按方向统计
        if report.get('by_direction'):
            lines.extend([
                "",
                "按方向统计:"
            ])
            for direction, data in report['by_direction'].items():
                direction_label = "做多" if direction == 'long' else "做空"
                lines.append(
                    f"  {direction_label}: {data['trades']}笔, "
                    f"盈亏=${data['pnl']:.2f}, "
                    f"平均=${data['avg']:.2f}"
                )

        # 按平仓原因统计
        if report.get('by_close_reason'):
            lines.extend([
                "",
                "按平仓原因统计:"
            ])
            for reason, data in report['by_close_reason'].items():
                lines.append(
                    f"  {reason}: {data['count']}笔, "
                    f"盈亏=${data['pnl']:.2f}"
                )

        lines.append("=" * 60)

        return '\n'.join(lines)
