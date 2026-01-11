"""
Success Tracker Module Contract

成功率追踪器模块接口定义
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime


class OperationType(Enum):
    """操作类型枚举"""
    OPEN_ATTEMPT = "open_attempt"           # 开仓尝试（识别到机会）
    OPEN_SUCCESS = "open_success"           # 开仓成功
    OPEN_FAILED = "open_failed"             # 开仓失败
    CLOSE_ATTEMPT = "close_attempt"         # 平仓尝试
    CLOSE_SUCCESS = "close_success"         # 平仓成功
    CLOSE_FAILED = "close_failed"           # 平仓失败


class OperationStatus(Enum):
    """操作状态枚举"""
    SUCCESS = "success"                     # 成功
    FAILED = "failed"                       # 失败
    POSITION_LIMIT = "position_limit"       # 仓位上限（特殊标识）
    PENDING = "pending"                     # 进行中


class ExchangeType(Enum):
    """交易所类型枚举"""
    EXTENDED = "extended"
    LIGHTER = "lighter"
    BOTH = "both"


class FailureReason(Enum):
    """失败原因枚举"""
    INSUFFICIENT_BALANCE = "insufficient_balance"       # 余额不足
    ORDER_REJECTED = "order_rejected"                   # 订单被拒绝
    NETWORK_TIMEOUT = "network_timeout"                 # 网络超时
    PRICE_SLIPPAGE = "price_slippage"                   # 价格滑点过大
    PARTIAL_FILL = "partial_fill"                       # 部分成交
    MAKER_TIMEOUT = "maker_timeout"                     # Maker订单超时
    POSITION_IMBALANCE = "position_imbalance"           # 仓位不一致
    UNKNOWN_ERROR = "unknown_error"                     # 未知错误


@dataclass
class SpreadOperationResult:
    """
    价差套利操作结果记录

    Attributes:
        timestamp: 操作时间戳（Unix时间）
        operation_type: 操作类型
        status: 操作状态
        exchange: 涉及的交易所
        order_id: 订单ID（如果成功）
        quantity: 交易数量
        price: 交易价格
        failure_reason: 失败原因（如果失败）
        error_message: 错误详情（如果有）
        pair_id: 关联的套利对ID（如果适用）
        spread_rate: 价差率（如果适用）
        expected_profit: 期望收益（如果适用）
    """
    timestamp: float
    operation_type: OperationType
    status: OperationStatus
    exchange: ExchangeType
    order_id: Optional[str] = None
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    failure_reason: Optional[FailureReason] = None
    error_message: Optional[str] = None
    pair_id: Optional[int] = None
    spread_rate: Optional[Decimal] = None
    expected_profit: Optional[Decimal] = None

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


class ISuccessTracker(ABC):
    """
    成功率追踪器接口

    负责记录、统计和导出交易操作的成功率数据
    """

    @abstractmethod
    def record_operation(self, result: SpreadOperationResult) -> None:
        """
        记录一次操作结果

        Args:
            result: 操作结果对象
        """
        pass

    @abstractmethod
    def get_success_rate(self, operation_type: OperationType) -> float:
        """
        获取指定操作类型的成功率

        Args:
            operation_type: 操作类型

        Returns:
            成功率（0.0-1.0）
        """
        pass

    @abstractmethod
    def get_failure_reason_distribution(self) -> Dict[FailureReason, int]:
        """
        获取失败原因分布

        Returns:
            失败原因及其出现次数
        """
        pass

    @abstractmethod
    def export_operations_csv(self) -> str:
        """
        导出操作记录到CSV（双语列名）

        Returns:
            导出的文件路径
        """
        pass

    @abstractmethod
    def export_summary_csv(self) -> str:
        """
        导出成功率统计汇总到CSV（双语列名）

        Returns:
            导出的文件路径
        """
        pass

    @abstractmethod
    def get_stats_summary(self) -> Dict[str, Any]:
        """
        获取统计摘要

        Returns:
            包含所有统计数据的字典，格式：
            {
                'open_attempts': int,
                'open_successes': int,
                'open_failed': int,
                'open_success_rate': float,
                'close_attempts': int,
                'close_successes': int,
                'close_failed': int,
                'close_success_rate': float,
                'failure_reasons': {FailureReason: int}
            }
        """
        pass

    @abstractmethod
    def clear_old_records(self, keep_last_n: int = 10000) -> None:
        """
        清理旧记录，保留最近的N条

        Args:
            keep_last_n: 保留的记录数量
        """
        pass
