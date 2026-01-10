"""
数据收集器 - 导出交易和订单数据用于分析

功能:
- 导出交易记录到CSV
- 导出订单记录到CSV
- 收集订单执行详情
"""

import csv
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional

from .spread_pair import SpreadPair


class DataCollector:
    """数据收集器 - 用于导出和分析交易数据"""

    def __init__(self, output_dir: str = "data"):
        """
        初始化数据收集器

        Args:
            output_dir: 输出目录路径
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger("DataCollector")

    def export_trades_csv(self, pairs: List[SpreadPair]) -> str:
        """
        T111: 导出交易记录到CSV

        Args:
            pairs: SpreadPair列表

        Returns:
            导出的文件路径
        """
        if not pairs:
            self.logger.warning("没有交易记录可导出")
            return ""

        # 生成文件名（按日期）
        date_str = datetime.now().strftime("%Y_%m_%d")
        filename = self.output_dir / f"trades_{date_str}.csv"

        # 准备CSV数据
        fieldnames = [
            'pair_id',
            'open_time',
            'close_time',
            'holding_time_seconds',
            'direction',
            'extended_side',
            'extended_entry_price',
            'extended_exit_price',
            'extended_quantity',
            'lighter_entry_price',
            'lighter_exit_price',
            'lighter_quantity',
            'open_spread',
            'close_spread',
            'realized_pnl',
            'close_reason',
            'close_priority',
            'order_type',
            'real_spread'
        ]

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for pair in pairs:
                    # 只导出已平仓的交易
                    if not pair.is_closed:
                        continue

                    row = {
                        'pair_id': pair.pair_id,
                        'open_time': datetime.fromtimestamp(pair.open_time).isoformat(),
                        'close_time': datetime.fromtimestamp(pair.close_time).isoformat() if pair.close_time else '',
                        'holding_time_seconds': pair.holding_time,
                        'direction': 'long' if pair.extended_side == 'buy' else 'short',
                        'extended_side': pair.extended_side,
                        'extended_entry_price': float(pair.extended_price),
                        'extended_exit_price': float(pair.close_extended_price) if pair.close_extended_price else 0,
                        'extended_quantity': float(pair.extended_quantity),
                        'lighter_entry_price': float(pair.lighter_price),
                        'lighter_exit_price': float(pair.close_lighter_price) if pair.close_lighter_price else 0,
                        'lighter_quantity': float(pair.lighter_quantity),
                        'open_spread': float(pair.open_spread),
                        'close_spread': float(pair.close_spread) if hasattr(pair, 'close_spread') else 0,
                        'realized_pnl': float(pair.realized_pnl) if pair.realized_pnl else 0,
                        'close_reason': getattr(pair, 'close_reason', ''),
                        'close_priority': getattr(pair, 'close_priority', ''),
                        'order_type': getattr(pair, 'order_type', ''),
                        'real_spread': getattr(pair, 'real_spread', '')
                    }

                    writer.writerow(row)

            self.logger.info(f"✅ 交易记录已导出到: {filename}")
            return str(filename)

        except Exception as e:
            self.logger.error(f"导出交易记录失败: {e}")
            return ""

    def export_orders_csv(self, orders: List[Dict[str, Any]]) -> str:
        """
        T112: 导出订单记录到CSV

        Args:
            orders: 订单字典列表

        Returns:
            导出的文件路径
        """
        if not orders:
            self.logger.warning("没有订单记录可导出")
            return ""

        # 生成文件名（按日期）
        date_str = datetime.now().strftime("%Y_%m_%d")
        filename = self.output_dir / f"orders_{date_str}.csv"

        # 准备CSV字段
        fieldnames = [
            'order_id',
            'timestamp',
            'exchange',
            'side',
            'order_type',  # 'maker' or 'taker'
            'post_only',
            'price',
            'quantity',
            'filled_quantity',
            'filled_price',
            'status',
            'fee',
            'is_rejected',
            'pair_id'
        ]

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                for order in orders:
                    row = {
                        'order_id': order.get('order_id', ''),
                        'timestamp': order.get('timestamp', ''),
                        'exchange': order.get('exchange', ''),
                        'side': order.get('side', ''),
                        'order_type': order.get('order_type', ''),
                        'post_only': order.get('post_only', ''),
                        'price': float(order.get('price', 0)),
                        'quantity': float(order.get('quantity', 0)),
                        'filled_quantity': float(order.get('filled_quantity', 0)),
                        'filled_price': float(order.get('filled_price', 0)),
                        'status': order.get('status', ''),
                        'fee': float(order.get('fee', 0)),
                        'is_rejected': order.get('is_rejected', ''),
                        'pair_id': order.get('pair_id', '')
                    }

                    writer.writerow(row)

            self.logger.info(f"✅ 订单记录已导出到: {filename}")
            return str(filename)

        except Exception as e:
            self.logger.error(f"导出订单记录失败: {e}")
            return ""

    def collect_order_execution(
        self,
        order_id: str,
        exchange: str,
        side: str,
        order_type: str,
        post_only: bool,
        price: Decimal,
        quantity: Decimal,
        filled_quantity: Decimal,
        filled_price: Optional[Decimal],
        status: str,
        fee: Decimal,
        pair_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        T113: 收集订单执行详情

        Args:
            order_id: 订单ID
            exchange: 交易所 ('extended' or 'lighter')
            side: 方向 ('buy' or 'sell')
            order_type: 订单类型 ('maker' or 'taker')
            post_only: 是否post_only
            price: 订单价格
            quantity: 订单数量
            filled_quantity: 成交数量
            filled_price: 成交价格
            status: 订单状态
            fee: 手续费
            pair_id: 关联的套利对ID

        Returns:
            Dict: 订单执行详情
        """
        return {
            'order_id': order_id,
            'timestamp': datetime.now().isoformat(),
            'exchange': exchange,
            'side': side,
            'order_type': order_type,
            'post_only': post_only,
            'price': price,
            'quantity': quantity,
            'filled_quantity': filled_quantity,
            'filled_price': filled_price,
            'status': status,
            'fee': fee,
            'is_rejected': (status == 'rejected'),
            'pair_id': pair_id
        }
