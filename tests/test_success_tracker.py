"""
成功率追踪器单元测试

测试SuccessTracker的记录、统计和导出功能
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


class TestSpreadOperationResult:
    """测试SpreadOperationResult数据类"""

    def test_create_operation_result(self):
        """
        测试：创建操作结果对象

        场景：
        1. 创建成功的开仓操作结果
        2. 验证所有字段正确设置
        """
        result = SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            order_id="test_order_123",
            quantity=Decimal('0.01'),
            price=Decimal('3000'),
            pair_id=1,
            spread_rate=Decimal('0.001'),
            expected_profit=Decimal('0.5')
        )

        assert result.timestamp == 1234567890.0
        assert result.operation_type == OperationType.OPEN_SUCCESS
        assert result.status == OperationStatus.SUCCESS
        assert result.exchange == ExchangeType.BOTH
        assert result.order_id == "test_order_123"
        assert result.quantity == Decimal('0.01')
        assert result.price == Decimal('3000')

    def test_to_dict_conversion(self):
        """
        测试：转换为字典格式

        场景：
        1. 创建操作结果对象
        2. 调用to_dict方法
        3. 验证字典格式正确
        """
        result = SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            quantity=Decimal('0.01')
        )

        result_dict = result.to_dict()

        assert result_dict['timestamp'] == 1234567890.0
        assert result_dict['operation_type'] == 'open_success'
        assert result_dict['status'] == 'success'
        assert result_dict['exchange'] == 'both'
        assert result_dict['quantity'] == 0.01

    def test_to_csv_row_bilingual(self):
        """
        测试：转换为CSV行（双语列名）

        场景：
        1. 创建操作结果对象
        2. 调用to_csv_row方法
        3. 验证双语列名格式正确
        """
        result = SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.EXTENDED,
            failure_reason=FailureReason.NETWORK_TIMEOUT
        )

        csv_row = result.to_csv_row()

        # 验证双语列名
        assert 'timestamp | 时间戳' in csv_row
        assert 'operation_type | 操作类型' in csv_row
        assert 'status | 状态' in csv_row
        assert 'exchange | 交易所' in csv_row
        assert 'failure_reason | 失败原因' in csv_row


class TestSuccessTrackerRecord:
    """测试SuccessTracker记录功能"""

    def test_record_successful_operation(self, tracker):
        """
        测试：记录成功的操作

        场景：
        1. 记录一次成功的开仓操作
        2. 验证操作被添加到列表
        3. 验证计数器正确更新
        """
        result = SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            quantity=Decimal('0.01')
        )

        tracker.record_operation(result)

        assert len(tracker._operations) == 1
        assert tracker._stats['open_success'] == 1

    def test_record_failed_operation(self, tracker):
        """
        测试：记录失败的操作

        场景：
        1. 记录一次失败的开仓操作
        2. 验证失败原因被记录
        3. 验证失败原因计数器正确
        """
        result = SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_FAILED,
            status=OperationStatus.FAILED,
            exchange=ExchangeType.EXTENDED,
            failure_reason=FailureReason.INSUFFICIENT_BALANCE
        )

        tracker.record_operation(result)

        assert len(tracker._operations) == 1
        assert tracker._failure_reasons[FailureReason.INSUFFICIENT_BALANCE] == 1

    def test_record_multiple_operations(self, tracker):
        """
        测试：记录多次操作

        场景：
        1. 记录多次不同类型的操作
        2. 验证所有操作都被记录
        3. 验证计数器正确累加
        """
        # 记录8次成功
        for i in range(8):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        # 记录2次失败
        for i in range(2):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i + 8,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.BOTH,
                failure_reason=FailureReason.NETWORK_TIMEOUT
            )
            tracker.record_operation(result)

        assert len(tracker._operations) == 10
        assert tracker._stats['open_success'] == 8
        assert tracker._failure_reasons[FailureReason.NETWORK_TIMEOUT] == 2


class TestSuccessTrackerStats:
    """测试SuccessTracker统计功能"""

    def test_get_success_rate_all_success(self, tracker):
        """
        测试：计算成功率（全部成功）

        场景：
        1. 记录10次操作，全部成功
        2. 获取成功率
        3. 验证成功率为100%
        """
        for i in range(10):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        rate = tracker.get_success_rate(OperationType.OPEN_SUCCESS)
        assert rate == 1.0

    def test_get_success_rate_partial_failure(self, tracker):
        """
        测试：计算成功率（部分失败）

        场景：
        1. 记录10次操作，8次成功，2次失败
        2. 获取成功率
        3. 验证成功率为80%
        """
        # 8次成功
        for i in range(8):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        # 2次失败
        for i in range(2):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i + 8,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.BOTH,
                failure_reason=FailureReason.NETWORK_TIMEOUT
            )
            tracker.record_operation(result)

        rate = tracker.get_success_rate(OperationType.OPEN_SUCCESS)
        assert rate == 0.8

    def test_get_success_rate_no_operations(self, tracker):
        """
        测试：计算成功率（无操作记录）

        场景：
        1. 没有记录任何操作
        2. 获取成功率
        3. 验证返回0
        """
        rate = tracker.get_success_rate(OperationType.OPEN_SUCCESS)
        assert rate == 0.0

    def test_get_failure_reason_distribution(self, tracker):
        """
        测试：获取失败原因分布

        场景：
        1. 记录不同失败原因的操作
        2. 获取失败原因分布
        3. 验证分布统计正确
        """
        # 3次余额不足
        for _ in range(3):
            result = SpreadOperationResult(
                timestamp=1234567890.0,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.EXTENDED,
                failure_reason=FailureReason.INSUFFICIENT_BALANCE
            )
            tracker.record_operation(result)

        # 2次网络超时
        for _ in range(2):
            result = SpreadOperationResult(
                timestamp=1234567890.0,
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.EXTENDED,
                failure_reason=FailureReason.NETWORK_TIMEOUT
            )
            tracker.record_operation(result)

        distribution = tracker.get_failure_reason_distribution()

        assert distribution[FailureReason.INSUFFICIENT_BALANCE] == 3
        assert distribution[FailureReason.NETWORK_TIMEOUT] == 2


class TestSuccessTrackerExport:
    """测试SuccessTracker导出功能"""

    def test_export_operations_csv(self, tracker):
        """
        测试：导出操作记录CSV

        场景：
        1. 记录几次操作
        2. 导出CSV
        3. 验证文件存在且格式正确
        """
        # 记录操作
        result = SpreadOperationResult(
            timestamp=1234567890.0,
            operation_type=OperationType.OPEN_SUCCESS,
            status=OperationStatus.SUCCESS,
            exchange=ExchangeType.BOTH,
            order_id="test_123"
        )
        tracker.record_operation(result)

        # 导出CSV
        csv_path = tracker.export_operations_csv()

        assert csv_path != ""
        assert Path(csv_path).exists()

        # 验证文件内容包含双语列名
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            assert 'timestamp | 时间戳' in content
            assert 'operation_type | 操作类型' in content

    def test_export_summary_csv(self, tracker):
        """
        测试：导出成功率汇总CSV

        场景：
        1. 记录几次操作
        2. 导出汇总CSV
        3. 验证文件包含正确的汇总数据
        """
        # 记录操作
        for i in range(8):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        # 导出汇总
        csv_path = tracker.export_summary_csv()

        assert csv_path != ""
        assert Path(csv_path).exists()

        # 验证文件内容
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            assert 'date | 日期' in content
            assert 'operation_type | 操作类型' in content
            assert 'success_rate | 成功率' in content

    def test_export_empty_operations(self, tracker):
        """
        测试：导出空操作记录

        场景：
        1. 没有记录任何操作
        2. 尝试导出
        3. 验证返回空字符串
        """
        csv_path = tracker.export_operations_csv()
        assert csv_path == ""

    def test_get_stats_summary(self, tracker):
        """
        测试：获取统计摘要

        场景：
        1. 记录开仓和平仓操作
        2. 获取统计摘要
        3. 验证摘要包含所有必要字段
        """
        # 记录开仓操作
        for i in range(10):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        # 记录平仓操作
        for i in range(5):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i + 10,
                operation_type=OperationType.CLOSE_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        summary = tracker.get_stats_summary()

        assert summary['open_successes'] == 10
        assert summary['close_successes'] == 5
        assert summary['open_success_rate'] == 1.0
        assert summary['close_success_rate'] == 1.0


class TestSuccessTrackerCleanup:
    """测试SuccessTracker清理功能"""

    def test_clear_old_records(self, tracker):
        """
        测试：清理旧记录

        场景：
        1. 记录超过限制数量的操作
        2. 调用清理方法
        3. 验证只保留最近N条
        """
        # 记录15条
        for i in range(15):
            result = SpreadOperationResult(
                timestamp=1234567890.0 + i,
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH
            )
            tracker.record_operation(result)

        assert len(tracker._operations) == 15

        # 清理，保留最近10条
        tracker.clear_old_records(keep_last_n=10)

        assert len(tracker._operations) == 10


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
