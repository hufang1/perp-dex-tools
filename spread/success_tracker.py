"""
成功率追踪器 - 记录和统计开仓/平仓成功率

功能:
- 记录每次开仓/平仓操作的结果
- 统计成功率和失败原因分布
- 导出CSV数据（双语列名）
"""

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional

from .models import OperationType, OperationStatus, ExchangeType, FailureReason


logger = logging.getLogger("SuccessTracker")


@dataclass
class SpreadOperationResult:
    """
    价差套利操作结果记录

    用于追踪开仓/平仓操作的成功率和失败原因
    """
    # 基础信息
    timestamp: float                    # 操作时间戳（Unix时间）
    operation_type: OperationType       # 操作类型（枚举）
    status: OperationStatus             # 操作状态（枚举）
    exchange: ExchangeType              # 涉及的交易所（枚举）

    # 订单信息
    order_id: Optional[str] = None      # 订单ID（如果成功）
    quantity: Optional[Decimal] = None  # 交易数量
    price: Optional[Decimal] = None     # 交易价格

    # 失败信息
    failure_reason: Optional[FailureReason] = None  # 失败原因（枚举，如果失败）
    error_message: Optional[str] = None  # 错误详情（如果有）

    # 上下文信息
    pair_id: Optional[int] = None       # 关联的套利对ID（如果适用）
    spread_rate: Optional[Decimal] = None  # 价差率（如果适用）
    expected_profit: Optional[Decimal] = None  # 期望收益（如果适用）

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典

        Returns:
            包含所有字段的字典
        """
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'operation_type': self.operation_type.value,
            'status': self.status.value,
            'exchange': self.exchange.value,
            'order_id': self.order_id,
            'quantity': float(self.quantity) if self.quantity else None,
            'price': float(self.price) if self.price else None,
            'failure_reason': self.failure_reason.value if self.failure_reason else None,
            'error_message': self.error_message,
            'pair_id': self.pair_id,
            'spread_rate': float(self.spread_rate) if self.spread_rate else None,
            'expected_profit': float(self.expected_profit) if self.expected_profit else None,
        }

    def to_csv_row(self) -> Dict[str, str]:
        """
        转换为CSV行（双语列名）

        Returns:
            使用双语列名的字典
        """
        return {
            'timestamp | 时间戳': datetime.fromtimestamp(self.timestamp).isoformat(),
            'operation_type | 操作类型': self.operation_type.value,
            'status | 状态': self.status.value,
            'exchange | 交易所': self.exchange.value,
            'order_id | 订单ID': self.order_id or '',
            'quantity | 数量': str(float(self.quantity)) if self.quantity else '',
            'price | 价格': str(float(self.price)) if self.price else '',
            'failure_reason | 失败原因': self.failure_reason.value if self.failure_reason else '',
            'error_message | 错误详情': self.error_message or '',
            'pair_id | 套利对ID': str(self.pair_id) if self.pair_id else '',
            'spread_rate | 价差率': str(float(self.spread_rate)) if self.spread_rate else '',
            'expected_profit | 期望收益': str(float(self.expected_profit)) if self.expected_profit else '',
        }


class SuccessTracker:
    """
    成功率追踪器

    负责记录、统计和导出交易操作的成功率数据
    """

    def __init__(self, output_dir: str = "data"):
        """
        初始化追踪器

        Args:
            output_dir: CSV输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # 操作记录列表（内存缓存）
        self._operations: List[SpreadOperationResult] = []

        # 统计计数器
        self._stats: Dict[str, int] = defaultdict(int)

        # 失败原因计数
        self._failure_reasons: Dict[FailureReason, int] = defaultdict(int)

        self.logger = logging.getLogger("SuccessTracker")

    def record_operation(self, result: SpreadOperationResult) -> None:
        """
        记录一次操作结果

        Args:
            result: 操作结果对象
        """
        self._operations.append(result)
        self._stats[result.operation_type.value] += 1

        if result.status == OperationStatus.SUCCESS:
            self._stats[f"{result.operation_type.value}_success"] += 1
        elif result.status == OperationStatus.FAILED and result.failure_reason:
            self._failure_reasons[result.failure_reason] += 1

        self.logger.debug(
            f"记录操作: {result.operation_type.value} - {result.status.value}"
        )

    def get_success_rate(self, operation_type: OperationType) -> float:
        """
        获取指定操作类型的成功率

        Args:
            operation_type: 操作类型（如OPEN_SUCCESS, CLOSE_SUCCESS等）

        Returns:
            成功率（0.0-1.0）
        """
        # 获取对应的基础类型（OPEN_ATTEMPT/OPEN_SUCCESS/OPEN_FAILED 或 CLOSE_ATTEMPT/CLOSE_SUCCESS/CLOSE_FAILED）
        op_value = operation_type.value

        # 统计该类型的所有操作（ATTEMPT + SUCCESS + FAILED）
        if 'open' in op_value.lower():
            total = (
                self._stats.get('open_attempt', 0) +
                self._stats.get('open_success', 0) +
                self._stats.get('open_failed', 0)
            )
            success = self._stats.get('open_success', 0)
        elif 'close' in op_value.lower():
            total = (
                self._stats.get('close_attempt', 0) +
                self._stats.get('close_success', 0) +
                self._stats.get('close_failed', 0)
            )
            success = self._stats.get('close_success', 0)
        else:
            total = self._stats.get(op_value, 0)
            success = self._stats.get(f"{op_value}_success", 0)

        return success / total if total > 0 else 0.0

    def get_failure_reason_distribution(self) -> Dict[FailureReason, int]:
        """
        获取失败原因分布

        Returns:
            失败原因及其出现次数
        """
        return dict(self._failure_reasons)

    def export_operations_csv(self) -> str:
        """
        导出操作记录到CSV（双语列名）

        Returns:
            导出的文件路径
        """
        if not self._operations:
            self.logger.warning("没有操作记录可导出")
            return ""

        date_str = datetime.now().strftime("%Y_%m_%d")
        filename = self.output_dir / f"operations_{date_str}.csv"

        fieldnames = [
            'timestamp | 时间戳',
            'operation_type | 操作类型',
            'status | 状态',
            'exchange | 交易所',
            'order_id | 订单ID',
            'quantity | 数量',
            'price | 价格',
            'failure_reason | 失败原因',
            'error_message | 错误详情',
            'pair_id | 套利对ID',
            'spread_rate | 价差率',
            'expected_profit | 期望收益',
        ]

        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for op in self._operations:
                    writer.writerow(op.to_csv_row())

            self.logger.info(f"导出操作记录: {filename}")
            return str(filename)
        except Exception as e:
            self.logger.error(f"导出操作记录失败: {e}")
            return ""

    def export_summary_csv(self) -> str:
        """
        导出成功率统计汇总到CSV（双语列名）

        Returns:
            导出的文件路径
        """
        date_str = datetime.now().strftime("%Y_%m_%d")
        filename = self.output_dir / f"success_stats_{date_str}.csv"

        fieldnames = [
            'date | 日期',
            'operation_type | 操作类型',
            'total_attempts | 总尝试次数',
            'success_count | 成功次数',
            'failed_count | 失败次数',
            'success_rate | 成功率',
        ]

        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                # 开仓统计
                open_attempts = self._stats.get(OperationType.OPEN_ATTEMPT.value, 0)
                open_success = self._stats.get(OperationType.OPEN_SUCCESS.value, 0)
                open_failed = open_attempts - open_success
                open_rate = open_success / open_attempts if open_attempts > 0 else 0.0

                writer.writerow({
                    'date | 日期': date_str,
                    'operation_type | 操作类型': 'open',
                    'total_attempts | 总尝试次数': open_attempts,
                    'success_count | 成功次数': open_success,
                    'failed_count | 失败次数': open_failed,
                    'success_rate | 成功率': f"{open_rate:.2%}",
                })

                # 平仓统计
                close_attempts = self._stats.get(OperationType.CLOSE_ATTEMPT.value, 0)
                close_success = self._stats.get(OperationType.CLOSE_SUCCESS.value, 0)
                close_failed = close_attempts - close_success
                close_rate = close_success / close_attempts if close_attempts > 0 else 0.0

                writer.writerow({
                    'date | 日期': date_str,
                    'operation_type | 操作类型': 'close',
                    'total_attempts | 总尝试次数': close_attempts,
                    'success_count | 成功次数': close_success,
                    'failed_count | 失败次数': close_failed,
                    'success_rate | 成功率': f"{close_rate:.2%}",
                })

            self.logger.info(f"导出成功率汇总: {filename}")
            return str(filename)
        except Exception as e:
            self.logger.error(f"导出成功率汇总失败: {e}")
            return ""

    def get_stats_summary(self) -> Dict[str, Any]:
        """
        获取统计摘要

        Returns:
            包含所有统计数据的字典
        """
        # 统计开仓：包括ATTEMPT、SUCCESS、FAILED
        open_attempts = (
            self._stats.get(OperationType.OPEN_ATTEMPT.value, 0) +
            self._stats.get(OperationType.OPEN_SUCCESS.value, 0) +
            self._stats.get(OperationType.OPEN_FAILED.value, 0)
        )
        open_success = self._stats.get(OperationType.OPEN_SUCCESS.value, 0)
        open_failed = self._stats.get(OperationType.OPEN_FAILED.value, 0)
        open_rate = open_success / open_attempts if open_attempts > 0 else 0.0

        # 统计平仓：包括ATTEMPT、SUCCESS、FAILED
        close_attempts = (
            self._stats.get(OperationType.CLOSE_ATTEMPT.value, 0) +
            self._stats.get(OperationType.CLOSE_SUCCESS.value, 0) +
            self._stats.get(OperationType.CLOSE_FAILED.value, 0)
        )
        close_success = self._stats.get(OperationType.CLOSE_SUCCESS.value, 0)
        close_failed = self._stats.get(OperationType.CLOSE_FAILED.value, 0)
        close_rate = close_success / close_attempts if close_attempts > 0 else 0.0

        return {
            'open_attempts': open_attempts,
            'open_successes': open_success,
            'open_failed': open_failed,
            'open_success_rate': open_rate,
            'close_attempts': close_attempts,
            'close_successes': close_success,
            'close_failed': close_failed,
            'close_success_rate': close_rate,
            'failure_reasons': dict(self._failure_reasons),
        }

    def clear_old_records(self, keep_last_n: int = 10000) -> None:
        """
        清理旧记录，保留最近的N条

        Args:
            keep_last_n: 保留的记录数量
        """
        if len(self._operations) > keep_last_n:
            removed = len(self._operations) - keep_last_n
            self._operations = self._operations[-keep_last_n:]
            self.logger.info(f"清理了 {removed} 条旧记录，保留最近 {keep_last_n} 条")
