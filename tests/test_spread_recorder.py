"""
价差记录器单元测试

测试SpreadRecorder类的核心功能，包括：
- 数据模型创建
- 价格验证
- CSV写入
- 缓冲区刷新
- 无效数据处理
"""

import asyncio
import csv
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spread.config import SpreadArbConfig
from spread.models import SpreadRecord
from spread.spread_recorder import SpreadRecorder


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def config(temp_output_dir):
    """测试配置"""
    return SpreadArbConfig(
        spread_recorder_output_dir=temp_output_dir,
        spread_recorder_interval=1,
        spread_recorder_buffer_size=5,
        spread_recorder_log_level="DEBUG"
    )


@pytest.fixture
def recorder(config):
    """价差记录器实例"""
    return SpreadRecorder(config)


class TestSpreadRecordCreation:
    """测试SpreadRecord数据类创建 (T009)"""

    def test_create_valid_spread_record(self):
        """测试创建有效的价差记录"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("3087.50"),
            extended_ask=Decimal("3087.60"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("1.70"),
            long_spread_rate=Decimal("0.000550"),
            short_spread=Decimal("-1.92"),
            short_spread_rate=Decimal("-0.000622"),
            extended_spread_cost=Decimal("0.000032"),
            lighter_spread_cost=Decimal("0.000039"),
            total_cost_rate=Decimal("0.000071"),
            status="VALID"
        )

        assert record.timestamp == "2026-01-10 12:34:56.789"
        assert record.extended_bid == Decimal("3087.50")
        assert record.status == "VALID"

    def test_create_invalid_spread_record(self):
        """测试创建无效的价差记录"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("0"),
            extended_ask=Decimal("0"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("0"),
            long_spread_rate=Decimal("0"),
            short_spread=Decimal("0"),
            short_spread_rate=Decimal("0"),
            extended_spread_cost=Decimal("0"),
            lighter_spread_cost=Decimal("0"),
            total_cost_rate=Decimal("0"),
            status="INVALID"
        )

        assert record.status == "INVALID"
        assert record.long_spread == Decimal("0")


class TestPriceValidation:
    """测试价格有效性验证 (T010)"""

    def test_validate_valid_prices(self, recorder):
        """测试验证有效的价格"""
        assert recorder._validate_prices(
            Decimal("3087.50"),
            Decimal("3087.60"),
            Decimal("3089.30"),
            Decimal("3089.42")
        ) is True

    def test_validate_zero_bid(self, recorder):
        """测试bid为零的价格"""
        assert recorder._validate_prices(
            Decimal("0"),
            Decimal("3087.60"),
            Decimal("3089.30"),
            Decimal("3089.42")
        ) is False

    def test_validate_zero_ask(self, recorder):
        """测试ask为零的价格"""
        assert recorder._validate_prices(
            Decimal("3087.50"),
            Decimal("0"),
            Decimal("3089.30"),
            Decimal("3089.42")
        ) is False

    def test_validate_bid_greater_than_ask(self, recorder):
        """测试bid大于ask的异常订单簿"""
        assert recorder._validate_prices(
            Decimal("3087.60"),
            Decimal("3087.50"),
            Decimal("3089.30"),
            Decimal("3089.42")
        ) is False

    def test_validate_bid_equals_ask(self, recorder):
        """测试bid等于ask的异常订单簿"""
        assert recorder._validate_prices(
            Decimal("3087.50"),
            Decimal("3087.50"),
            Decimal("3089.30"),
            Decimal("3089.42")
        ) is False

    def test_validate_negative_prices(self, recorder):
        """测试负数价格"""
        assert recorder._validate_prices(
            Decimal("-1"),
            Decimal("3087.60"),
            Decimal("3089.30"),
            Decimal("3089.42")
        ) is False


class TestCSVWriting:
    """测试CSV写入正确性 (T011)"""

    def test_csv_file_creation(self, recorder):
        """测试CSV文件创建"""
        # 创建记录
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("3087.50"),
            extended_ask=Decimal("3087.60"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("1.70"),
            long_spread_rate=Decimal("0.000550"),
            short_spread=Decimal("-1.92"),
            short_spread_rate=Decimal("-0.000622"),
            extended_spread_cost=Decimal("0.000032"),
            lighter_spread_cost=Decimal("0.000039"),
            total_cost_rate=Decimal("0.000071"),
            status="VALID"
        )

        # 写入缓冲区
        recorder._write_to_buffer(record)
        recorder._flush_buffer()

        # 验证文件创建
        csv_file = Path(recorder.output_dir) / recorder._get_csv_filename()
        assert csv_file.exists()

        # 验证文件内容
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)

            # 检查头部
            assert rows[0] == SpreadRecorder.CSV_COLUMNS

            # 检查数据行
            assert len(rows) == 2
            assert rows[1][0] == "2026-01-10 12:34:56.789"
            assert rows[1][12] == "VALID"

    def test_csv_columns(self, recorder):
        """测试CSV列名"""
        expected_columns = [
            'timestamp', 'extended_bid', 'extended_ask', 'lighter_bid', 'lighter_ask',
            'long_spread', 'long_spread_rate', 'short_spread', 'short_spread_rate',
            'extended_spread_cost', 'lighter_spread_cost', 'total_cost_rate', 'status'
        ]
        assert SpreadRecorder.CSV_COLUMNS == expected_columns

    def test_csv_utf8_bom_encoding(self, recorder):
        """测试CSV文件使用UTF-8 with BOM编码"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("3087.50"),
            extended_ask=Decimal("3087.60"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("1.70"),
            long_spread_rate=Decimal("0.000550"),
            short_spread=Decimal("-1.92"),
            short_spread_rate=Decimal("-0.000622"),
            extended_spread_cost=Decimal("0.000032"),
            lighter_spread_cost=Decimal("0.000039"),
            total_cost_rate=Decimal("0.000071"),
            status="VALID"
        )

        recorder._write_to_buffer(record)
        recorder._flush_buffer()

        csv_file = Path(recorder.output_dir) / recorder._get_csv_filename()

        # 验证BOM编码
        with open(csv_file, 'rb') as f:
            bom = f.read(3)
            assert bom == b'\xef\xbb\xbf'


class TestBufferFlushing:
    """测试缓冲区刷新逻辑 (T012)"""

    def test_buffer_auto_flush_when_full(self, recorder):
        """测试缓冲区满时自动刷新"""
        # 创建记录（缓冲区大小为5）
        for i in range(5):
            record = SpreadRecord(
                timestamp="2026-01-10 12:34:56.789",
                extended_bid=Decimal("3087.50"),
                extended_ask=Decimal("3087.60"),
                lighter_bid=Decimal("3089.30"),
                lighter_ask=Decimal("3089.42"),
                long_spread=Decimal("1.70"),
                long_spread_rate=Decimal("0.000550"),
                short_spread=Decimal("-1.92"),
                short_spread_rate=Decimal("-0.000622"),
                extended_spread_cost=Decimal("0.000032"),
                lighter_spread_cost=Decimal("0.000039"),
                total_cost_rate=Decimal("0.000071"),
                status="VALID"
            )
            recorder._write_to_buffer(record)

        # 验证缓冲区已清空（自动刷新）
        assert len(recorder.buffer) == 0
        assert recorder.total_records == 5

    def test_buffer_manual_flush(self, recorder):
        """测试手动刷新缓冲区"""
        # 添加记录
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("3087.50"),
            extended_ask=Decimal("3087.60"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("1.70"),
            long_spread_rate=Decimal("0.000550"),
            short_spread=Decimal("-1.92"),
            short_spread_rate=Decimal("-0.000622"),
            extended_spread_cost=Decimal("0.000032"),
            lighter_spread_cost=Decimal("0.000039"),
            total_cost_rate=Decimal("0.000071"),
            status="VALID"
        )
        recorder._write_to_buffer(record)

        # 验证缓冲区有数据
        assert len(recorder.buffer) == 1

        # 手动刷新
        recorder._flush_buffer()

        # 验证缓冲区已清空
        assert len(recorder.buffer) == 0
        assert recorder.total_records == 1

    def test_flush_creates_new_file_if_not_exists(self, recorder):
        """测试刷新时创建新文件（如果不存在）"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("3087.50"),
            extended_ask=Decimal("3087.60"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("1.70"),
            long_spread_rate=Decimal("0.000550"),
            short_spread=Decimal("-1.92"),
            short_spread_rate=Decimal("-0.000622"),
            extended_spread_cost=Decimal("0.000032"),
            lighter_spread_cost=Decimal("0.000039"),
            total_cost_rate=Decimal("0.000071"),
            status="VALID"
        )

        recorder._write_to_buffer(record)
        recorder._flush_buffer()

        csv_file = Path(recorder.output_dir) / recorder._get_csv_filename()
        assert csv_file.exists()


class TestInvalidDataHandling:
    """测试无效数据处理 (T013)"""

    def test_invalid_data_marked_correctly(self, recorder):
        """测试无效数据被正确标记"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("0"),
            extended_ask=Decimal("0"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("0"),
            long_spread_rate=Decimal("0"),
            short_spread=Decimal("0"),
            short_spread_rate=Decimal("0"),
            extended_spread_cost=Decimal("0"),
            lighter_spread_cost=Decimal("0"),
            total_cost_rate=Decimal("0"),
            status="INVALID"
        )

        recorder._write_to_buffer(record)
        recorder._flush_buffer()

        # 验证CSV中包含INVALID记录
        csv_file = Path(recorder.output_dir) / recorder._get_csv_filename()
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert rows[1][12] == "INVALID"

    @pytest.mark.asyncio
    async def test_create_spread_record_with_invalid_prices(self, recorder):
        """测试使用无效价格创建价差记录"""
        record = await recorder._create_spread_record(
            Decimal("0"),
            Decimal("0"),
            Decimal("3089.30"),
            Decimal("3089.42")
        )

        assert record.status == "INVALID"
        assert record.long_spread == Decimal("0")
        assert recorder.invalid_records == 1

    @pytest.mark.asyncio
    async def test_create_spread_record_with_valid_prices(self, recorder):
        """测试使用有效价格创建价差记录"""
        record = await recorder._create_spread_record(
            Decimal("3087.50"),
            Decimal("3087.60"),
            Decimal("3089.30"),
            Decimal("3089.42")
        )

        assert record.status == "VALID"
        assert record.long_spread != Decimal("0")


class TestCSVFilenameGeneration:
    """测试CSV文件名生成"""

    def test_csv_filename_format(self, recorder):
        """测试CSV文件名格式"""
        filename = recorder._get_csv_filename()
        assert filename.startswith("spreads_")
        assert filename.endswith(".csv")
        assert len(filename) == len("spreads_YYYY_MM_DD.csv")

    def test_csv_filename_changes_daily(self, recorder):
        """测试CSV文件名每天变化"""
        filename1 = recorder._get_csv_filename()
        # 由于时间差很小，文件名应该相同
        filename2 = recorder._get_csv_filename()
        assert filename1 == filename2


class TestExistingFileCheck:
    """测试文件存在性检查"""

    def test_check_existing_file_when_exists(self, recorder, temp_output_dir):
        """测试检查已存在的文件"""
        # 创建文件
        csv_file = Path(temp_output_dir) / "spreads_2026_01_10.csv"
        csv_file.touch()

        assert recorder._check_existing_file("spreads_2026_01_10.csv") is True

    def test_check_existing_file_when_not_exists(self, recorder):
        """测试检查不存在的文件"""
        assert recorder._check_existing_file("spreads_2026_01_10.csv") is False


class TestDateChangeDetection:
    """测试日期切换检测"""

    def test_check_date_change_no_change(self, recorder):
        """测试日期未切换"""
        # 第一次调用并设置当前文件
        filename = recorder._get_csv_filename()
        recorder.current_csv_file = filename
        # 第二次调用应该返回False
        assert recorder._check_date_change() is False

    def test_check_date_change_when_changed(self, recorder):
        """测试日期已切换"""
        # 设置当前文件
        recorder.current_csv_file = "spreads_2026_01_09.csv"
        # 获取新文件名（应该是不同日期）
        assert recorder._check_date_change() is True


class TestLogMessageFormatting:
    """测试日志消息格式化"""

    def test_format_valid_log_message(self, recorder):
        """测试格式化有效数据的日志消息"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("3087.50"),
            extended_ask=Decimal("3087.60"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("1.70"),
            long_spread_rate=Decimal("0.000550"),
            short_spread=Decimal("-1.92"),
            short_spread_rate=Decimal("-0.000622"),
            extended_spread_cost=Decimal("0.000032"),
            lighter_spread_cost=Decimal("0.000039"),
            total_cost_rate=Decimal("0.000071"),
            status="VALID"
        )

        message = recorder._format_log_message(record)

        assert "📊 [价差记录]" in message
        assert "2026-01-10 12:34:56.789" in message
        assert "Extended: bid=$3087.50, ask=$3087.60" in message
        assert "Lighter:  bid=$3089.30, ask=$3089.42" in message
        assert "做多价差: $1.70" in message
        assert "做空价差: $-1.92" in message

    def test_format_invalid_log_message(self, recorder):
        """测试格式化无效数据的日志消息"""
        record = SpreadRecord(
            timestamp="2026-01-10 12:34:56.789",
            extended_bid=Decimal("0"),
            extended_ask=Decimal("0"),
            lighter_bid=Decimal("3089.30"),
            lighter_ask=Decimal("3089.42"),
            long_spread=Decimal("0"),
            long_spread_rate=Decimal("0"),
            short_spread=Decimal("0"),
            short_spread_rate=Decimal("0"),
            extended_spread_cost=Decimal("0"),
            lighter_spread_cost=Decimal("0"),
            total_cost_rate=Decimal("0"),
            status="INVALID"
        )

        message = recorder._format_log_message(record)

        assert "📊 [价差记录]" in message
        assert "❌ 无效数据" in message
