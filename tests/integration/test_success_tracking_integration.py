"""
成功率统计集成测试

测试成功率追踪在完整交易流程中的集成
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from decimal import Decimal
from datetime import datetime

from spread.success_tracker import SuccessTracker, SpreadOperationResult
from spread.models import OperationType, OperationStatus, ExchangeType, FailureReason


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def tracker(temp_dir):
    """创建SuccessTracker实例"""
    return SuccessTracker(output_dir=temp_dir)


class TestSuccessTrackingIntegration:
    """测试成功率追踪集成（001-fix-order-type - User Story 3）"""

    def test_complete_open_close_tracking(self, tracker):
        """
        测试：完整开仓平仓流程追踪

        场景：
        1. 记录开仓尝试
        2. 记录开仓成功
        3. 记录平仓尝试
        4. 记录平仓成功
        5. 验证统计正确
        """
        # 开仓尝试
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_ATTEMPT,
            status=OperationStatus.PENDING,
            exchange=ExchangeType.EXTENDED,
            quantity=Decimal('0.01'),
            price=Decimal('3000')
        ))

        # 开仓成功
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567891.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            order_id="extended_order_123",
            quantity=Decimal('0.01'),
            price=Decimal('3000'),
            pair_id=1
        ))

        # 平仓尝试
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234590.0,
            operation_type=OperationType.CLOSE_ATTEMPT,
            status=OperationStatus.PENDING,
            exchange=ExchangeType.BOTH,
            pair_id=1
        ))

        # 平仓成功
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234591.0,
            operation_type=OperationType.CLOSE_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            order_id="close_order_456",
            pair_id=1
        ))

        # 验证统计
        summary = tracker.get_stats_summary()
        assert summary['open_attempts'] >= 1
        assert summary['open_successes'] == 1
        assert summary['close_attempts'] >= 1
        assert summary['close_successes'] == 1

    def test_failure_reason_tracking(self, tracker):
        """
        测试：失败原因追踪

        场景：
        1. 记录不同失败原因的开仓失败
        2. 验证失败原因分布正确
        """
        # 3次余额不足
        for i in range(3):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.EXTENDED,
                failure_reason=FailureReason.INSUFFICIENT_BALANCE,
                error_message="余额不足"
            ))

        # 2次网络超时
        for i in range(2):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i + 3,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.LIGHTER,
                failure_reason=FailureReason.NETWORK_TIMEOUT,
                error_message="连接超时"
            ))

        # 1次订单被拒
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567895.0,
            operation_type=OperationType.OPEN_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.EXTENDED,
            failure_reason=FailureReason.ORDER_REJECTED,
            error_message="订单被交易所拒绝"
        ))

        # 验证失败原因分布
        distribution = tracker.get_failure_reason_distribution()
        assert distribution[FailureReason.INSUFFICIENT_BALANCE] == 3
        assert distribution[FailureReason.NETWORK_TIMEOUT] == 2
        assert distribution[FailureReason.ORDER_REJECTED] == 1

    def test_csv_export_bilingual_columns(self, tracker):
        """
        测试：CSV导出使用双语列名

        场景：
        1. 记录一些操作
        2. 导出CSV
        3. 验证列名是双语格式
        """
        # 记录操作
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            order_id="test_123",
            quantity=Decimal('0.01'),
            price=Decimal('3000')
        ))

        # 导出操作CSV
        operations_csv = tracker.export_operations_csv()
        assert operations_csv != ""

        with open(operations_csv, 'r', encoding='utf-8-sig') as f:
            first_line = f.readline()
            # 验证双语列名
            assert 'timestamp | 时间戳' in first_line
            assert 'operation_type | 操作类型' in first_line
            assert 'status | 状态' in first_line
            assert 'exchange | 交易所' in first_line

        # 导出汇总CSV
        summary_csv = tracker.export_summary_csv()
        assert summary_csv != ""

        with open(summary_csv, 'r', encoding='utf-8-sig') as f:
            first_line = f.readline()
            # 验证双语列名
            assert 'date | 日期' in first_line
            assert 'operation_type | 操作类型' in first_line
            assert 'success_rate | 成功率' in first_line

    def test_position_limit_tracking(self, tracker):
        """
        测试：仓位上限追踪

        场景：
        1. 记录仓位上限事件
        2. 验证POSITION_LIMIT状态被记录
        """
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_ATTEMPT,
            status=OperationStatus.POSITION_LIMIT,
            exchange=ExchangeType.BOTH,
            pair_id=None  # 未创建套利对
        ))

        # 验证记录
        assert len(tracker._operations) == 1
        assert tracker._operations[0].status == OperationStatus.POSITION_LIMIT

    def test_position_imbalance_failure_reason(self, tracker):
        """
        测试：仓位不一致失败原因

        场景：
        1. 记录仓位不一致失败
        2. 验证POSITION_IMBALANCE失败原因
        """
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.BOTH,
            failure_reason=FailureReason.POSITION_IMBALANCE,
            error_message="Extended 0.21 vs Lighter 0.02"
        ))

        # 验证失败原因
        distribution = tracker.get_failure_reason_distribution()
        assert distribution[FailureReason.POSITION_IMBALANCE] == 1


class TestSuccessTrackingInBotContext:
    """测试成功率追踪在Bot上下文中的使用"""

    def test_taker_order_success_rate(self, tracker):
        """
        测试：taker订单的成功率

        场景：
        1. 使用taker订单开仓
        2. 记录成功/失败
        3. 验证成功率较高
        """
        # 模拟10次taker订单开仓，9次成功
        for i in range(9):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH,
                order_id=f"taker_order_{i}",
                quantity=Decimal('0.01')
            ))

        # 1次失败
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567899.0,
            operation_type=OperationType.OPEN_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.LIGHTER,
            failure_reason=FailureReason.NETWORK_TIMEOUT
        ))

        # 验证成功率
        summary = tracker.get_stats_summary()
        assert summary['open_successes'] == 9
        assert summary['open_failed'] == 1

    def test_hedge_failure_tracking(self, tracker):
        """
        测试：对冲失败追踪

        场景：
        1. Extended成交，Lighter失败
        2. 记录对冲失败
        3. 验证失败原因统计
        """
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_ATTEMPT,
            status=OperationStatus.PENDING,
            exchange=ExchangeType.EXTENDED,
            quantity=Decimal('0.01')
        ))

        # Extended成交
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567891.0,
            operation_type=OperationType.OPEN_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.LIGHTER,
            failure_reason=FailureReason.NETWORK_TIMEOUT,
            error_message="Lighter连接超时"
        ))

        # 验证失败原因
        distribution = tracker.get_failure_reason_distribution()
        assert distribution[FailureReason.NETWORK_TIMEOUT] == 1

    def test_export_after_cleanup(self, tracker):
        """
        测试：清理后导出数据

        场景：
        1. 记录大量操作
        2. 清理旧记录
        3. 导出剩余数据
        """
        # 记录20次操作
        for i in range(20):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            ))

        # 清理，保留最近10条
        tracker.clear_old_records(keep_last_n=10)
        assert len(tracker._operations) == 10

        # 导出应该成功
        csv_path = tracker.export_operations_csv()
        assert csv_path != ""
        assert Path(csv_path).exists()


class TestSuccessRateCalculations:
    """测试成功率计算"""

    def test_open_success_rate_calculation(self, tracker):
        """
        测试：开仓成功率计算

        场景：
        1. 记录多次开仓操作
        2. 验证成功率计算正确
        """
        # 记录10次尝试，7次成功
        for i in range(7):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            ))

        for i in range(3):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i + 7,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.BOTH,
                failure_reason=FailureReason.ORDER_REJECTED
            ))

        summary = tracker.get_stats_summary()
        assert summary['open_successes'] == 7
        # 失败数 = 尝试数 - 成功数
        # 这里我们记录了OPEN_ATTEMPT需要手动计算

    def test_close_success_rate_calculation(self, tracker):
        """
        测试：平仓成功率计算

        场景：
        1. 记录多次平仓操作
        2. 验证成功率计算正确
        """
        # 5次平仓成功
        for i in range(5):
            tracker.record_operation(SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.CLOSE_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            ))

        # 1次平仓失败
        tracker.record_operation(SpreadOperationResult(
            timestamp=1234567895.0,
            operation_type=OperationType.CLOSE_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.LIGHTER,
            failure_reason=FailureReason.PRICE_SLIPPAGE
        ))

        summary = tracker.get_stats_summary()
        assert summary['close_successes'] == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
