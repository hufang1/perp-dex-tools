"""
价差实时记录器 - 定期采样价差数据并记录到CSV文件

功能：
1. 定期采样两个交易所（Extended和Lighter）的订单簿价格
2. 计算真实价差（使用对手价，复用RealSpreadCalculator）
3. 同时输出到CSV文件和终端日志
4. 按日期自动创建和管理CSV文件
5. 使用缓冲写入提高性能
"""

import asyncio
import csv
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .config import SpreadArbConfig
from .models import SpreadRecord
from .real_spread_calculator import RealSpreadCalculator


class SpreadRecorder:
    """价差实时记录器

    定期采样价差数据并记录到CSV文件，同时输出到终端日志。
    使用异步任务避免阻塞主交易循环。
    """

    # CSV列名
    CSV_COLUMNS = [
        'timestamp',
        'extended_bid',
        'extended_ask',
        'lighter_bid',
        'lighter_ask',
        'long_spread',
        'long_spread_rate',
        'short_spread',
        'short_spread_rate',
        'extended_spread_cost',
        'lighter_spread_cost',
        'total_cost_rate',
        'status'
    ]

    def __init__(self, config: SpreadArbConfig):
        """初始化价差记录器

        Args:
            config: 价差套利配置对象
        """
        self.config = config
        self.calculator = RealSpreadCalculator(config)

        # 设置日志
        self.logger = logging.getLogger("SpreadRecorder")
        self.logger.setLevel(getattr(logging, config.spread_recorder_log_level))

        # 缓冲区
        self.buffer: list[SpreadRecord] = []
        self.last_flush_time = time.time()

        # 文件管理
        self.output_dir = Path(config.spread_recorder_output_dir)
        self.current_csv_file: Optional[str] = None
        self.current_csv_handle: Optional[csv.writer] = None
        self.current_file_handle: Optional[object] = None

        # 统计信息
        self.total_records = 0
        self.invalid_records = 0
        self.write_failures = 0

        # 运行状态
        self.is_running = False

        # 创建输出目录
        self._ensure_output_dir()

    def _ensure_output_dir(self):
        """确保输出目录存在"""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"价差记录器输出目录: {self.output_dir.absolute()}")
        except Exception as e:
            self.logger.error(f"创建输出目录失败: {e}")

    def _validate_prices(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> bool:
        """验证价格数据有效性

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            bool: 价格是否有效
        """
        # 检查价格为正数
        if extended_bid <= 0 or extended_ask <= 0:
            return False

        if lighter_bid <= 0 or lighter_ask <= 0:
            return False

        # 检查订单簿正常（bid < ask）
        if extended_bid >= extended_ask:
            return False

        if lighter_bid >= lighter_ask:
            return False

        return True

    def _get_csv_filename(self) -> str:
        """生成CSV文件名（UTC日期）

        Returns:
            str: CSV文件名，格式为 spreads_YYYY_MM_DD.csv
        """
        date_str = datetime.now(timezone.utc).strftime("%Y_%m_%d")
        return f"spreads_{date_str}.csv"

    def _check_existing_file(self, filename: str) -> bool:
        """检查文件是否已存在

        Args:
            filename: 文件名

        Returns:
            bool: 文件是否存在
        """
        file_path = self.output_dir / filename
        return file_path.exists()

    def _write_csv_header(self, file_handle):
        """写入CSV头部

        Args:
            file_handle: 文件句柄
        """
        writer = csv.writer(file_handle)
        writer.writerow(self.CSV_COLUMNS)
        file_handle.flush()

    def _flush_buffer(self):
        """刷新缓冲区到CSV文件（异步写入）

        将缓冲区中的所有记录写入CSV文件，并清空缓冲区。
        使用UTF-8 with BOM编码确保Excel兼容性。
        """
        if not self.buffer:
            return

        try:
            # 获取当前CSV文件名
            csv_filename = self._get_csv_filename()
            csv_path = self.output_dir / csv_filename

            # 检查是否需要切换文件
            if csv_filename != self.current_csv_file:
                # 关闭旧文件
                if self.current_file_handle:
                    self.current_file_handle.close()

                # 打开新文件
                file_exists = self._check_existing_file(csv_filename)
                mode = 'a' if file_exists else 'w'
                self.current_file_handle = open(csv_path, mode, newline='', encoding='utf-8-sig')
                self.current_csv_file = csv_filename

                # 写入头部（仅新文件）
                if not file_exists:
                    self._write_csv_header(self.current_file_handle)

            # 写入缓冲区数据
            writer = csv.writer(self.current_file_handle)
            for record in self.buffer:
                row = [
                    record.timestamp,
                    str(record.extended_bid),
                    str(record.extended_ask),
                    str(record.lighter_bid),
                    str(record.lighter_ask),
                    str(record.long_spread),
                    str(record.long_spread_rate),
                    str(record.short_spread),
                    str(record.short_spread_rate),
                    str(record.extended_spread_cost),
                    str(record.lighter_spread_cost),
                    str(record.total_cost_rate),
                    record.status
                ]
                writer.writerow(row)

            # 刷新到磁盘
            self.current_file_handle.flush()

            # 更新统计
            self.total_records += len(self.buffer)
            self.last_flush_time = time.time()

            self.logger.debug(f"刷新缓冲区: {len(self.buffer)} 条记录 -> {csv_filename}")

            # 清空缓冲区
            self.buffer.clear()

        except Exception as e:
            self.write_failures += len(self.buffer)
            self.logger.error(f"写入CSV失败: {e}")
            # 保留缓冲区数据，下次重试

    def _check_date_change(self) -> bool:
        """检测日期是否已切换

        Returns:
            bool: 如果日期已切换返回True
        """
        current_filename = self._get_csv_filename()
        return current_filename != self.current_csv_file

    def _handle_date_rotation(self):
        """处理日期切换时的文件轮换

        刷新旧文件缓冲，关闭旧文件，准备新文件。
        """
        if self._check_date_change():
            self.logger.info(f"日期切换: {self.current_csv_file} -> {self._get_csv_filename()}")
            self._flush_buffer()

            if self.current_file_handle:
                self.current_file_handle.close()
                self.current_file_handle = None
                self.current_csv_file = None

    async def record_loop(self, orderbook_getter: Awaitable[Callable]):
        """主记录循环（异步任务）

        定期采样价差数据并记录。此方法应该在asyncio事件循环中作为独立任务运行。

        Args:
            orderbook_getter: 获取订单簿的异步函数，返回 (extended_bid, extended_ask, lighter_bid, lighter_ask)
        """
        self.is_running = True
        self.logger.info("价差记录器已启动")

        try:
            while self.is_running:
                start_time = time.time()

                try:
                    # 获取订单簿数据
                    # 支持两种接口：
                    # 1. orderbook_getter 是一个可调用对象，直接调用获取价格
                    # 2. orderbook_getter 是一个awaitable，返回一个可调用对象
                    if asyncio.iscoroutinefunction(orderbook_getter):
                        # 如果是协程函数，调用它
                        orderbook_func = await orderbook_getter()
                        if orderbook_func:
                            extended_bid, extended_ask, lighter_bid, lighter_ask = orderbook_func()
                        else:
                            continue
                    elif callable(orderbook_getter):
                        # 如果是普通可调用对象，直接调用
                        extended_bid, extended_ask, lighter_bid, lighter_ask = orderbook_getter()
                    else:
                        # 未知类型
                        self.logger.warning("无法识别的orderbook_getter类型")
                        await asyncio.sleep(self.config.spread_recorder_interval)
                        continue

                    # 创建价差记录
                    record = await self._create_spread_record(
                        extended_bid, extended_ask, lighter_bid, lighter_ask
                    )

                    # 写入缓冲区
                    self._write_to_buffer(record)

                    # 输出终端日志
                    log_message = self._format_log_message(record)
                    self.logger.info(log_message)

                    # 性能日志
                    elapsed = (time.time() - start_time) * 1000
                    self.logger.debug(f"记录操作耗时: {elapsed:.2f}ms")

                    # 检查日期切换
                    self._handle_date_rotation()

                    # 检查缓冲区是否需要刷新
                    should_flush = (
                        len(self.buffer) >= self.config.spread_recorder_buffer_size or
                        (time.time() - self.last_flush_time) >= self.config.spread_recorder_flush_interval
                    )

                    if should_flush:
                        self._flush_buffer()

                except Exception as e:
                    self.logger.error(f"记录循环错误: {e}")
                    self.invalid_records += 1

                # 等待下次采样
                await asyncio.sleep(self.config.spread_recorder_interval)

        except asyncio.CancelledError:
            self.logger.info("价差记录器任务被取消")
        finally:
            # 清理：刷新缓冲区并关闭文件
            self._flush_buffer()
            if self.current_file_handle:
                self.current_file_handle.close()
                self.is_running = False
            self.logger.info(f"价差记录器已停止 (总记录: {self.total_records}, 无效: {self.invalid_records}, 写入失败: {self.write_failures})")

    async def _create_spread_record(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> SpreadRecord:
        """创建价差记录

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            SpreadRecord: 价差记录对象
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # 验证价格
        is_valid = self._validate_prices(extended_bid, extended_ask, lighter_bid, lighter_ask)

        if not is_valid:
            self.invalid_records += 1
            return SpreadRecord(
                timestamp=timestamp,
                extended_bid=extended_bid,
                extended_ask=extended_ask,
                lighter_bid=lighter_bid,
                lighter_ask=lighter_ask,
                long_spread=Decimal('0'),
                long_spread_rate=Decimal('0'),
                short_spread=Decimal('0'),
                short_spread_rate=Decimal('0'),
                extended_spread_cost=Decimal('0'),
                lighter_spread_cost=Decimal('0'),
                total_cost_rate=Decimal('0'),
                status="INVALID"
            )

        # 计算价差（使用RealSpreadCalculator）
        long_result = self.calculator.calculate_long_spread(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )
        short_result = self.calculator.calculate_short_spread(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 计算点差成本
        costs = self.calculator.calculate_spread_costs(
            extended_bid, extended_ask, lighter_bid, lighter_ask, 'long_spread'
        )

        return SpreadRecord(
            timestamp=timestamp,
            extended_bid=extended_bid,
            extended_ask=extended_ask,
            lighter_bid=lighter_bid,
            lighter_ask=lighter_ask,
            long_spread=long_result.spread,
            long_spread_rate=long_result.spread_rate,
            short_spread=short_result.spread,
            short_spread_rate=short_result.spread_rate,
            extended_spread_cost=costs.extended_cost,
            lighter_spread_cost=costs.lighter_cost,
            total_cost_rate=costs.total_cost_rate,
            status="VALID"
        )

    def _write_to_buffer(self, record: SpreadRecord):
        """将记录添加到缓冲区

        Args:
            record: 价差记录对象
        """
        self.buffer.append(record)

        # 自动刷新（如果缓冲区满）
        if len(self.buffer) >= self.config.spread_recorder_buffer_size:
            self._flush_buffer()

    def _format_log_message(self, record: SpreadRecord) -> str:
        """格式化终端日志输出（简体中文）

        Args:
            record: 价差记录对象

        Returns:
            str: 格式化的日志消息
        """
        if record.status == "INVALID":
            return (
                f"📊 [价差记录] {record.timestamp} - ❌ 无效数据\n"
                f"  Extended: bid=${record.extended_bid}, ask=${record.extended_ask}\n"
                f"  Lighter:  bid=${record.lighter_bid}, ask=${record.lighter_ask}\n"
            )

        # 格式化价差率（百分比）
        long_rate_pct = float(record.long_spread_rate) * 100
        short_rate_pct = float(record.short_spread_rate) * 100
        cost_pct = float(record.total_cost_rate) * 100

        return (
            f"📊 [价差记录] {record.timestamp}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"订单簿价格:\n"
            f"  Extended: bid=${record.extended_bid}, ask=${record.extended_ask}\n"
            f"  Lighter:  bid=${record.lighter_bid}, ask=${record.lighter_ask}\n"
            f"\n"
            f"做多价差: ${record.long_spread} ({long_rate_pct:+.4f}%)\n"
            f"做空价差: ${record.short_spread} ({short_rate_pct:+.4f}%)\n"
            f"点差成本: {cost_pct:.4f}%\n"
            f"\n"
            f"不开仓理由: {self._format_rejection_reason(record)}\n"
        )

    def _format_rejection_reason(self, record: SpreadRecord) -> str:
        """格式化不开仓理由（包含数学公式说明）

        Args:
            record: 价差记录对象

        Returns:
            str: 格式化的拒绝理由
        """
        # 获取配置的阈值
        min_spread_rate = float(self.config.min_spread_rate)
        min_spread_pct = min_spread_rate * 100

        # 获取价差率
        long_rate = float(record.long_spread_rate)
        short_rate = float(record.short_spread_rate)
        cost_rate = float(record.total_cost_rate)

        # 判断哪个方向的价差更大
        if abs(long_rate) >= abs(short_rate):
            direction = "做多"
            spread_rate = long_rate
            spread_value = record.long_spread
            formula = f"做多价差 = lighter_bid - extended_ask = {record.lighter_bid} - {record.extended_ask}"
        else:
            direction = "做空"
            spread_rate = short_rate
            spread_value = record.short_spread
            formula = f"做空价差 = extended_bid - lighter_ask = {record.extended_bid} - {record.lighter_ask}"

        spread_pct = abs(spread_rate) * 100

        # 构建拒绝理由
        if record.status == "INVALID":
            return "❌ 数据无效（价格缺失或异常）"

        if spread_pct <= 0:
            return f"❌ 价差为负（{direction}价差=${spread_value:.4f}），无套利空间"

        # 检查是否低于阈值
        if spread_pct < min_spread_pct:
            return (
                f"❌ 价差率不足: {direction}\n"
                f"   公式: {formula}\n"
                f"   当前价差率: {spread_pct:.4f}% < 阈值: {min_spread_pct:.4f}%\n"
                f"   净收益率 = {spread_pct:.4f}% - {cost_rate:.4f}% (成本) = {spread_pct - cost_rate:.4f}% < 0\n"
                f"   结论: 扣除点差成本后为负收益，不开仓"
            )

        # 检查扣除成本后是否为正
        net_return = spread_pct - cost_rate
        if net_return <= 0:
            return (
                f"❌ 扣除成本后无利润: {direction}\n"
                f"   公式: {formula}\n"
                f"   价差率: {spread_pct:.4f}%\n"
                f"   点差成本: {cost_rate:.4f}%\n"
                f"   净收益率 = {spread_pct:.4f}% - {cost_rate:.4f}% = {net_return:.4f}% ≤ 0\n"
                f"   结论: 扣除点差成本后无利润或亏损，不开仓"
            )

        return f"✅ 价差满足开仓条件: {direction} {spread_pct:.4f}% ≥ {min_spread_pct:.4f}%"

    def _format_long_spread_formula(self, record: SpreadRecord) -> str:
        """格式化做多价差计算公式

        Args:
            record: 价差记录对象

        Returns:
            str: 格式化的计算公式
        """
        return (
            f"做多价差计算:\n"
            f"  公式: 做多价差 = lighter_bid - extended_ask\n"
            f"  计算: {record.lighter_bid} - {record.extended_ask} = ${record.long_spread}\n"
            f"  价差率: {float(record.long_spread_rate) * 100:+.4f}%\n"
            f"  点差成本: {float(record.extended_spread_cost) * 100:.4f}% + {float(record.lighter_spread_cost) * 100:.4f}% = {float(record.total_cost_rate) * 100:.4f}%\n"
        )

    def _format_short_spread_formula(self, record: SpreadRecord) -> str:
        """格式化做空价差计算公式

        Args:
            record: 价差记录对象

        Returns:
            str: 格式化的计算公式
        """
        return (
            f"做空价差计算:\n"
            f"  公式: 做空价差 = extended_bid - lighter_ask\n"
            f"  计算: {record.extended_bid} - {record.lighter_ask} = ${record.short_spread}\n"
            f"  价差率: {float(record.short_spread_rate) * 100:+.4f}%\n"
        )

    def _format_cost_breakdown(self, record: SpreadRecord) -> str:
        """格式化点差成本分解

        Args:
            record: 价差记录对象

        Returns:
            str: 格式化的成本分解
        """
        return (
            f"点差成本分解:\n"
            f"  Extended: {float(record.extended_spread_cost) * 100:.4f}%\n"
            f"  Lighter:  {float(record.lighter_spread_cost) * 100:.4f}%\n"
            f"  总成本:   {float(record.total_cost_rate) * 100:.4f}%\n"
        )

    def stop(self):
        """停止记录器（优雅关闭）"""
        self.is_running = False
        self._flush_buffer()
        if self.current_file_handle:
            self.current_file_handle.close()
            self.current_file_handle = None
