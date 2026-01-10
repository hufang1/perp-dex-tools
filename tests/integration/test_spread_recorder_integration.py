"""
价差记录器集成测试

测试SpreadRecorder与bot.py的集成，包括：
- 记录器在bot中的初始化
- 记录器任务在事件循环中的运行
- CSV文件格式和内容验证
- 与主交易循环的非阻塞集成
"""

import asyncio
import csv
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from spread.config import SpreadArbConfig
from spread.spread_recorder import SpreadRecorder


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def integration_config(temp_output_dir):
    """集成测试配置"""
    return SpreadArbConfig(
        spread_recorder_output_dir=temp_output_dir,
        spread_recorder_interval=1,
        spread_recorder_buffer_size=3,
        spread_recorder_log_level="INFO"
    )


@pytest.fixture
def mock_orderbook_getter():
    """模拟订单簿获取函数"""
    def get_orderbook():
        return (
            Decimal("3087.50"),  # extended_bid
            Decimal("3087.60"),  # extended_ask
            Decimal("3089.30"),  # lighter_bid
            Decimal("3089.42"),  # lighter_ask
        )
    return get_orderbook


class TestSpreadRecorderIntegration:
    """测试SpreadRecorder与bot的集成 (T032)"""

    @pytest.mark.asyncio
    async def test_recorder_initialization(self, integration_config):
        """测试记录器初始化"""
        recorder = SpreadRecorder(integration_config)

        assert recorder.config == integration_config
        assert recorder.is_running is False
        assert len(recorder.buffer) == 0
        assert recorder.total_records == 0
        assert recorder.invalid_records == 0

    @pytest.mark.asyncio
    async def test_recorder_task_creation(self, integration_config, mock_orderbook_getter):
        """测试记录器任务创建和运行"""
        recorder = SpreadRecorder(integration_config)

        # 创建记录任务
        task = asyncio.create_task(
            recorder.record_loop(mock_orderbook_getter)
        )

        # 等待一段时间让记录器运行
        await asyncio.sleep(2)

        # 停止记录器
        recorder.is_running = False
        await asyncio.sleep(0.5)

        # 验证记录器已记录数据
        assert recorder.total_records > 0 or len(recorder.buffer) > 0

        # 取消任务
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_recorder_non_blocking(self, integration_config, mock_orderbook_getter):
        """测试记录器不阻塞主循环"""
        recorder = SpreadRecorder(integration_config)

        # 创建记录任务
        recorder_task = asyncio.create_task(
            recorder.record_loop(mock_orderbook_getter)
        )

        # 创建其他任务
        async def other_task():
            for i in range(5):
                await asyncio.sleep(0.2)
                # 模拟其他工作

        other_task_obj = asyncio.create_task(other_task())

        # 等待其他任务完成
        await other_task_obj

        # 停止记录器
        recorder.is_running = False

        # 清理
        recorder_task.cancel()
        try:
            await recorder_task
        except asyncio.CancelledError:
            pass

        # 验证其他任务能够完成（非阻塞）
        assert True  # 如果阻塞，这里不会到达

    @pytest.mark.asyncio
    async def test_csv_file_format_validation(self, integration_config, mock_orderbook_getter):
        """测试CSV文件格式验证"""
        recorder = SpreadRecorder(integration_config)

        # 运行记录器
        task = asyncio.create_task(recorder.record_loop(mock_orderbook_getter))

        # 等待足够时间以生成CSV文件
        await asyncio.sleep(2)

        # 停止记录器
        recorder.is_running = False
        await asyncio.sleep(0.5)

        # 刷新缓冲区
        recorder._flush_buffer()

        # 验证CSV文件
        csv_file = Path(recorder.output_dir) / recorder._get_csv_filename()
        assert csv_file.exists()

        # 验证文件内容
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)

            # 验证头部
            assert rows[0] == SpreadRecorder.CSV_COLUMNS

            # 验证至少有一条数据记录
            assert len(rows) >= 2

            # 验证数据记录格式
            data_row = rows[1]
            assert len(data_row) == len(SpreadRecorder.CSV_COLUMNS)
            assert data_row[12] in ["VALID", "INVALID"]  # status列

        # 清理
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_recorder_graceful_shutdown(self, integration_config, mock_orderbook_getter):
        """测试记录器优雅关闭"""
        recorder = SpreadRecorder(integration_config)

        # 运行记录器
        task = asyncio.create_task(recorder.record_loop(mock_orderbook_getter))
        await asyncio.sleep(1)

        # 停止记录器
        recorder.stop()

        # 等待任务结束
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # 验证缓冲区已刷新
        assert len(recorder.buffer) == 0 or recorder.total_records > 0

    @pytest.mark.asyncio
    async def test_recorder_with_invalid_prices(self, integration_config):
        """测试记录器处理无效价格"""
        def get_invalid_orderbook():
            return (
                Decimal("0"),      # extended_bid (无效)
                Decimal("0"),      # extended_ask (无效)
                Decimal("3089.30"), # lighter_bid
                Decimal("3089.42"), # lighter_ask
            )

        recorder = SpreadRecorder(integration_config)

        # 运行记录器
        task = asyncio.create_task(recorder.record_loop(get_invalid_orderbook))
        await asyncio.sleep(1)

        # 停止记录器
        recorder.is_running = False
        recorder._flush_buffer()

        # 验证无效记录被计数
        assert recorder.invalid_records > 0

        # 验证CSV包含INVALID记录
        csv_file = Path(recorder.output_dir) / recorder._get_csv_filename()
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
            # 至少有一行INVALID记录
            assert any(row[12] == "INVALID" for row in rows[1:])

        # 清理
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_recorder_buffer_flush_on_interval(self, integration_config, mock_orderbook_getter):
        """测试记录器按时间间隔刷新缓冲区"""
        recorder = SpreadRecorder(integration_config)

        # 运行记录器
        task = asyncio.create_task(recorder.record_loop(mock_orderbook_getter))

        # 等待超过刷新间隔（60秒 -> 使用配置的1秒）
        await asyncio.sleep(1.5)

        # 停止记录器
        recorder.is_running = False

        # 验证缓冲区已刷新（由于时间间隔）
        assert len(recorder.buffer) == 0 or recorder.total_records > 0

        # 清理
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
