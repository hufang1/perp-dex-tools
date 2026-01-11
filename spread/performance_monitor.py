"""
性能监控与调试输出模块

本模块实现011-async-ws-ioc-trading的性能监控功能，包括:
- 时间戳记录和延迟计算
- 数据新鲜度检查
- 滑点阈值检查
- 利润率验证
- 决策过程日志
- 统计数据导出
"""

import logging
import time
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from spread.config import SpreadArbConfig
from spread.models import (
    DataFreshnessResult,
    ProfitabilityCheckResult,
    SlippageCheckResult,
    TradeOperationRecord,
)


class PerformanceMonitor:
    """
    性能监控器

    负责记录时间戳、检查数据新鲜度、验证滑点和利润率，并输出结构化调试信息。
    """

    def __init__(self, config: SpreadArbConfig, logger: Optional[logging.Logger] = None) -> None:
        """初始化性能监控器

        Args:
            config: SpreadArbConfig配置对象
            logger: 日志记录器（可选，默认创建新logger）
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # 时间戳记录
        self._timestamps: Dict[str, float] = {}

        # 统计数据
        self._stats = {
            'total_checks': 0,
            'stale_data_count': 0,
            'slippage_rejections': 0,
            'profitability_rejections': 0,
            'tick_to_trade_latencies': [],
            'execution_latencies': [],
            'concurrent_gaps': [],
            'data_ages_extended': [],
            'data_ages_lighter': [],
        }

        # T085: 交易操作记录存储 (CSV导出)
        self._decision_records: List[TradeOperationRecord] = []
        self._max_records = 10000  # 最大存储记录数，防止内存溢出

        # 性能日志输出器
        self._setup_performance_logger()

    def _setup_performance_logger(self) -> None:
        """配置性能日志输出器"""
        if not self.config.enable_enhanced_logging:
            return

        self.perf_logger = logging.getLogger('performance')
        self.perf_logger.setLevel(logging.INFO)

        # 添加文件处理器（如果还没有）
        if not any(isinstance(h, logging.FileHandler) for h in self.perf_logger.handlers):
            try:
                from pathlib import Path

                log_dir = Path('logs')
                log_dir.mkdir(exist_ok=True)

                file_handler = logging.FileHandler(log_dir / 'performance.log', encoding='utf-8')
                file_handler.setLevel(logging.INFO)
                formatter = logging.Formatter(
                    '%(asctime)s | %(levelname)s | %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                file_handler.setFormatter(formatter)
                self.perf_logger.addHandler(file_handler)
            except Exception as e:
                self.logger.warning(f"无法创建性能日志文件: {e}")

    # ========================================================================
    # 时间戳记录
    # ========================================================================

    def record_timestamp(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """记录时间戳

        Args:
            name: 记录名称，建议值: 'signal', 'calc', 'send_A', 'send_B', 'ack_A', 'ack_B'
            metadata: 附加元数据，例如 {'log': True} 强制输出日志

        Example:
            monitor.record_timestamp('signal', {'opportunity': spread_rate})
        """
        timestamp_ms = time.time() * 1000
        self._timestamps[name] = timestamp_ms

        if metadata and metadata.get('log') and self.config.log_all_timestamps:
            self.perf_logger.info(f"[时间戳] {name}: {timestamp_ms:.2f}ms")

    def get_latency(self, start_name: str, end_name: str) -> Optional[float]:
        """计算两个时间戳之间的延迟

        Args:
            start_name: 起始记录名称
            end_name: 结束记录名称

        Returns:
            延迟（毫秒），如果找不到记录返回None

        Example:
            latency = monitor.get_latency('signal', 'send_A')
            # 返回: 8.45 (毫秒)
        """
        if start_name not in self._timestamps or end_name not in self._timestamps:
            return None
        return self._timestamps[end_name] - self._timestamps[start_name]

    # ========================================================================
    # 延迟监控
    # ========================================================================

    def record_tick_to_trade_latency(self, signal_ts: float, send_ts: float) -> None:
        """记录行情到交易的延迟

        Args:
            signal_ts: 信号触发时间戳（毫秒）
            send_ts: 订单发送时间戳（毫秒）

        副作用:
            - 更新统计数据
            - 如果延迟超过max_tick_to_trade_latency_ms，输出警告
            - 如果config.log_all_timestamps=True，输出INFO日志

        Example:
            monitor.record_tick_to_trade_latency(1704960123456.78, 1704960123465.23)
            # 输出: ⏱️ [行情→交易延迟] 8.45ms | 信号: 1704960123456.78ms | 发送: 1704960123465.23ms
        """
        latency_ms = send_ts - signal_ts
        self._stats['tick_to_trade_latencies'].append(latency_ms)

        is_critical = latency_ms > self.config.max_tick_to_trade_latency_ms
        log_level = logging.WARNING if is_critical else logging.INFO

        msg = f"⏱️ [行情→交易延迟] {latency_ms:.2f}ms | 信号: {signal_ts:.2f}ms | 发送: {send_ts:.2f}ms"

        if self.config.log_all_timestamps or is_critical:
            if is_critical and self.config.enable_console_warnings:
                self.logger.warning(msg)
            else:
                self.perf_logger.info(msg)

    def record_execution_latency(self, send_ts: float, ack_ts: float) -> None:
        """记录执行延迟（发送到ACK）

        Args:
            send_ts: 发送时间戳（毫秒）
            ack_ts: ACK时间戳（毫秒）

        副作用:
            - 更新统计数据
            - 如果延迟超过max_execution_latency_ms，输出警告
        """
        latency_ms = ack_ts - send_ts
        self._stats['execution_latencies'].append(latency_ms)

        is_critical = latency_ms > self.config.max_execution_latency_ms

        msg = f"⏱️ [执行延迟] {latency_ms:.2f}ms | 发送: {send_ts:.2f}ms | ACK: {ack_ts:.2f}ms"

        if is_critical and self.config.enable_console_warnings:
            self.logger.warning(msg)
        else:
            self.perf_logger.info(msg)

    def record_concurrent_send_gap(self, first_send_ts: float, second_send_ts: float) -> None:
        """记录并发发送时间差

        Args:
            first_send_ts: 第一个订单发送时间戳（毫秒）
            second_send_ts: 第二个订单发送时间戳（毫秒）

        副作用:
            - 计算间隔并记录到stats
            - 输出INFO日志，带✅或❌标记

        Example:
            monitor.record_concurrent_send_gap(1704960123465.23, 1704960123468.44)
            # 输出: 🔄 [并发发送] Extended→Lighter间隔: 3.21ms ✅ | 阈值: 5ms
        """
        gap_ms = abs(second_send_ts - first_send_ts)
        self._stats['concurrent_gaps'].append(gap_ms)

        threshold = self.config.concurrent_order_send_threshold_ms
        is_within_threshold = gap_ms <= threshold

        status = "✅" if is_within_threshold else "❌"
        msg = f"🔄 [并发发送] Extended→Lighter间隔: {gap_ms:.2f}ms {status} | 阈值: {threshold}ms"

        if is_within_threshold or self.config.enable_console_warnings:
            self.logger.info(msg)
        self.perf_logger.info(msg)

    # ========================================================================
    # 数据新鲜度检查
    # ========================================================================

    def check_data_freshness(
        self,
        exchange: str,
        data_timestamp: float,
        current_time: Optional[float] = None
    ) -> DataFreshnessResult:
        """检查数据新鲜度

        Args:
            exchange: 交易所名称 ('extended' 或 'lighter')
            data_timestamp: 数据时间戳（毫秒）
            current_time: 当前时间戳（毫秒），默认为系统时间

        Returns:
            DataFreshnessResult: 检查结果

        Raises:
            ValueError: exchange不是'extended'或'lighter'

        副作用:
            - 更新stale_data_count统计
            - 如果数据过期，输出ERROR日志

        Example:
            result = monitor.check_data_freshness('extended', 1704960123411.23)
            # 返回: DataFreshnessResult(is_fresh=True, data_age_ms=45.2, ...)
        """
        if exchange not in ('extended', 'lighter'):
            raise ValueError(f"无效的exchange: {exchange}")

        if current_time is None:
            current_time = time.time() * 1000

        data_age_ms = current_time - data_timestamp
        threshold_ms = self.config.max_data_age_ms

        is_fresh = data_age_ms <= threshold_ms

        result = DataFreshnessResult(
            is_fresh=is_fresh,
            data_age_ms=data_age_ms,
            threshold_ms=threshold_ms,
            exchange=exchange,
            data_timestamp=data_timestamp,
            check_timestamp=current_time
        )

        # 更新统计
        self._stats['total_checks'] += 1
        if exchange == 'extended':
            self._stats['data_ages_extended'].append(data_age_ms)
        else:
            self._stats['data_ages_lighter'].append(data_age_ms)

        # 输出日志
        if is_fresh:
            msg = f"📡 [数据新鲜度] {result}"
            self.logger.info(msg)
        else:
            self._stats['stale_data_count'] += 1
            msg = f"🚨 [数据过期] {result}"
            self.logger.error(msg)

        self.perf_logger.info(f"[数据新鲜度] {exchange}: {data_age_ms:.1f}ms (阈值: {threshold_ms:.1f}ms, {'新鲜' if is_fresh else '过期'})")

        return result

    def check_both_data_freshness(
        self,
        extended_ts: float,
        lighter_ts: float,
        current_time: Optional[float] = None
    ) -> Tuple[bool, List[DataFreshnessResult]]:
        """检查两个交易所的数据新鲜度

        Args:
            extended_ts: Extended数据时间戳（毫秒）
            lighter_ts: Lighter数据时间戳（毫秒）
            current_time: 当前时间戳（毫秒），默认为系统时间

        Returns:
            (是否都新鲜, [extended_result, lighter_result])

        副作用:
            - 如果任一数据过期，输出WARNING日志
        """
        ext_result = self.check_data_freshness('extended', extended_ts, current_time)
        lit_result = self.check_data_freshness('lighter', lighter_ts, current_time)

        both_fresh = ext_result.is_fresh and lit_result.is_fresh

        if not both_fresh:
            msg = (
                f"⚠️ [数据新鲜度] 双边数据不新鲜，禁止交易 | "
                f"Extended: {ext_result.data_age_ms:.1f}ms, Lighter: {lit_result.data_age_ms:.1f}ms"
            )
            self.logger.warning(msg)

        return both_fresh, [ext_result, lit_result]

    # ========================================================================
    # 滑点检查
    # ========================================================================

    def check_slippage(
        self,
        expected_price: Decimal,
        current_price: Decimal,
        side: str,
        threshold: Optional[Decimal] = None
    ) -> SlippageCheckResult:
        """检查滑点是否可接受

        Args:
            expected_price: 预期成交价
            current_price: 当前盘口价
            side: 方向 ('buy' 或 'sell')
            threshold: 滑点阈值，默认从config读取ioc_slippage_tolerance_rate

        Returns:
            SlippageCheckResult: 检查结果

        Raises:
            ValueError: side不是'buy'或'sell'

        副作用:
            - 如果滑点超限，输出ERROR日志
            - 如果滑点超过max_slippage_warning_rate，输出红色高亮警告

        Example:
            result = monitor.check_slippage(
                expected_price=Decimal('3000.00'),
                current_price=Decimal('3001.50'),
                side='buy'
            )
            # 返回: SlippageCheckResult(is_acceptable=True, slippage_rate=Decimal('0.0005'), ...)
        """
        if side not in ('buy', 'sell'):
            raise ValueError(f"无效的side: {side}")

        if threshold is None:
            threshold = self.config.ioc_slippage_tolerance_rate

        # 计算滑点率
        if side == 'buy':
            # 买入：当前价越高越不利
            slippage_rate = (current_price - expected_price) / expected_price
        else:
            # 卖出：当前价越低越不利
            slippage_rate = (expected_price - current_price) / expected_price

        # 取绝对值
        slippage_rate = abs(slippage_rate)

        is_acceptable = slippage_rate <= threshold

        result = SlippageCheckResult(
            is_acceptable=is_acceptable,
            expected_price=expected_price,
            current_price=current_price,
            slippage_rate=slippage_rate,
            threshold_rate=threshold,
            side=side
        )

        # 输出日志
        if is_acceptable:
            msg = f"📊 [滑点检查] {result}"
            self.logger.info(msg)
        else:
            self._stats['slippage_rejections'] += 1
            msg = f"🚨 [滑点超限] {result}"
            self.logger.error(msg)

            # 检查是否严重滑点
            if slippage_rate > self.config.max_slippage_warning_rate:
                self._log_severe_slippage_warning(result)

        self.perf_logger.info(f"[滑点检查] {side}: {slippage_rate:.4%} (阈值: {threshold:.4%}, {'可接受' if is_acceptable else '超限'})")

        return result

    def _log_severe_slippage_warning(self, result: SlippageCheckResult) -> None:
        """记录严重滑点警告（红色高亮）"""
        warning = (
            "🔴🔴🔴 [严重滑点警告] 🔴🔴🔴\n"
            f"   实际成交价与预期价格偏差过大!\n"
            f"   {result}\n"
            f"   当前滑点: {result.slippage_rate:.2%} > 警告阈值: {self.config.max_slippage_warning_rate:.2%}\n"
            "   🔴🔴🔴"
        )
        self.logger.error(warning)

    # ========================================================================
    # 利润率检查
    # ========================================================================

    def check_profitability(
        self,
        spread_rate: Decimal,
        extended_fee: Optional[Decimal] = None,
        lighter_fee: Optional[Decimal] = None,
        expected_slippage: Optional[Decimal] = None
    ) -> ProfitabilityCheckResult:
        """检查利润率是否足够

        Args:
            spread_rate: 价差率
            extended_fee: Extended手续费率，默认从config读取
            lighter_fee: Lighter手续费率，默认从config读取
            expected_slippage: 预期滑点成本，默认从config读取

        Returns:
            ProfitabilityCheckResult: 检查结果

        副作用:
            - 如果利润不足，更新profitability_rejections统计
            - 如果双边费率之和>0.06%，输出WARNING
            - 输出INFO或WARNING日志

        Example:
            result = monitor.check_profitability(Decimal('0.0010'))
            # 返回: ProfitabilityCheckResult(is_profitable=True, net_profit_rate=Decimal('0.0005'), ...)
        """
        # 从config获取默认值
        if extended_fee is None:
            extended_fee = self.config.extended_taker_fee_rate
        if lighter_fee is None:
            lighter_fee = self.config.lighter_fee_rate
        if expected_slippage is None:
            expected_slippage = self.config.expected_slippage_cost_rate

        total_fees = extended_fee + lighter_fee
        net_profit_rate = spread_rate - total_fees - expected_slippage
        min_net_profit = self.config.min_net_profit_rate

        is_profitable = net_profit_rate >= min_net_profit

        if is_profitable:
            decision = "允许开仓"
        else:
            decision = "拒绝开仓（利润不足）"
            self._stats['profitability_rejections'] += 1

        result = ProfitabilityCheckResult(
            is_profitable=is_profitable,
            spread_rate=spread_rate,
            total_fees=total_fees,
            expected_slippage=expected_slippage,
            min_net_profit=min_net_profit,
            net_profit_rate=net_profit_rate,
            decision=decision
        )

        # 费率警告
        if total_fees > Decimal('0.0006'):
            self.logger.warning(f"⚠️ [费率警告] 双边手续费总和过高: {total_fees:.4%} > 0.06%")

        # 输出日志
        if is_profitable:
            msg = f"💰 [利润检查] {result}"
            self.logger.info(msg)
        else:
            msg = f"⚠️ [利润不足] ❌ 不足利润 | 价差率: {spread_rate:.4%} | 净利: {net_profit_rate:.4%}"
            self.logger.warning(msg)

        self.perf_logger.info(
            f"[利润检查] 价差率: {spread_rate:.4%}, 净利: {net_profit_rate:.4%} "
            f"(手续费: {total_fees:.4%}, 预期滑点: {expected_slippage:.4%}), "
            f"决策: {decision}"
        )

        return result

    # ========================================================================
    # 决策记录
    # ========================================================================

    def log_opening_decision(
        self,
        opportunity: Dict[str, Any],
        data_freshness: List[DataFreshnessResult],
        slippage_check: Optional[SlippageCheckResult] = None,
        profitability_check: Optional[ProfitabilityCheckResult] = None,
        final_decision: str = "PENDING"
    ) -> None:
        """记录开仓决策过程

        Args:
            opportunity: 套利机会字典，包含:
                - 'type': str (如 '做多价差')
                - 'side': str ('buy' or 'sell')
                - 'spread_rate': Decimal
                - 'extended_price': Decimal
                - 'lighter_price': Decimal
            data_freshness: 数据新鲜度检查结果列表
            slippage_check: 滑点检查结果（可选）
            profitability_check: 利润率检查结果（可选）
            final_decision: 最终决策 ('允许开仓', '拒绝开仓')

        副作用:
            - 输出格式化决策日志到INFO级别

        Example:
            monitor.log_opening_decision(
                opportunity={
                    'type': '做多价差',
                    'side': 'buy',
                    'spread_rate': Decimal('0.0010'),
                    'extended_price': Decimal('3000.00'),
                    'lighter_price': Decimal('3003.00')
                },
                data_freshness=[ext_result, lit_result],
                slippage_check=slippage_result,
                profitability_check=profit_result,
                final_decision='允许开仓'
            )
        """
        lines = [
            "======================================================================",
            "📋 [开仓决策详情]",
            "----------------------------------------------------------------------",
        ]

        # 套利机会
        lines.append("🎯 套利机会:")
        for key, value in opportunity.items():
            if isinstance(value, Decimal):
                lines.append(f"   {key}: {value:.4f}")
            else:
                lines.append(f"   {key}: {value}")

        # 数据新鲜度
        lines.append("\n📡 数据新鲜度检查:")
        for result in data_freshness:
            lines.append(f"   {result}")

        # 滑点检查
        if slippage_check:
            lines.append(f"\n📊 滑点检查:\n   {slippage_check}")

        # 利润率检查
        if profitability_check:
            lines.append(f"\n💰 利润率检查:\n   {profitability_check}")

        # 最终决策
        status_icon = "✅" if final_decision == "允许开仓" else "❌"
        lines.append(f"\n🎯 {status_icon} 最终决策: {final_decision}")
        lines.append("======================================================================")

        decision_log = "\n".join(lines)
        self.logger.info(decision_log)
        self.perf_logger.info(f"[开仓决策] {final_decision}")

    # ========================================================================
    # 统计导出
    # ========================================================================

    def get_stats_summary(self) -> Dict[str, Any]:
        """获取统计摘要

        Returns:
            包含以下字段的字典:
            - 'total_checks': int
            - 'stale_data_count': int
            - 'stale_data_rate': float
            - 'slippage_rejections': int
            - 'profitability_rejections': int
            - 'avg_tick_to_trade_latency_ms': float
            - 'max_tick_to_trade_latency_ms': float
            - 'avg_execution_latency_ms': float
            - 'max_execution_latency_ms': float
            - 'concurrent_order_send_gap_ms': float
        """
        stats = self._stats.copy()

        # 计算平均值和最大值
        if stats['tick_to_trade_latencies']:
            stats['avg_tick_to_trade_latency_ms'] = sum(stats['tick_to_trade_latencies']) / len(stats['tick_to_trade_latencies'])
            stats['max_tick_to_trade_latency_ms'] = max(stats['tick_to_trade_latencies'])

        if stats['execution_latencies']:
            stats['avg_execution_latency_ms'] = sum(stats['execution_latencies']) / len(stats['execution_latencies'])
            stats['max_execution_latency_ms'] = max(stats['execution_latencies'])

        if stats['concurrent_gaps']:
            stats['concurrent_order_send_gap_ms'] = sum(stats['concurrent_gaps']) / len(stats['concurrent_gaps'])

        # 计算数据过期率
        if stats['total_checks'] > 0:
            stats['stale_data_rate'] = stats['stale_data_count'] / stats['total_checks']
        else:
            stats['stale_data_rate'] = 0.0

        # 计算平均数据年龄
        if stats['data_ages_extended']:
            stats['avg_data_age_extended_ms'] = sum(stats['data_ages_extended']) / len(stats['data_ages_extended'])

        if stats['data_ages_lighter']:
            stats['avg_data_age_lighter_ms'] = sum(stats['data_ages_lighter']) / len(stats['data_ages_lighter'])

        return stats

    def log_stats_summary(self) -> None:
        """记录统计摘要到日志

        副作用:
            - 输出格式化统计报告到INFO级别
        """
        stats = self.get_stats_summary()

        lines = [
            "======================================================================",
            "📊 [性能监控统计]",
            "----------------------------------------------------------------------",
        ]

        # 数据新鲜度检查
        lines.append("数据新鲜度检查:")
        lines.append(f"   总检查次数: {stats.get('total_checks', 0)}")
        lines.append(f"   过期数据次数: {stats.get('stale_data_count', 0)}")
        if stats.get('total_checks', 0) > 0:
            lines.append(f"   过期率: {stats.get('stale_data_rate', 0):.2%}")

        # 延迟统计
        lines.append("\n延迟统计:")
        if 'avg_tick_to_trade_latency_ms' in stats:
            lines.append(f"   平均行情→交易延迟: {stats['avg_tick_to_trade_latency_ms']:.2f}ms")
            lines.append(f"   最大行情→交易延迟: {stats['max_tick_to_trade_latency_ms']:.2f}ms")
        if 'avg_execution_latency_ms' in stats:
            lines.append(f"   平均执行延迟: {stats['avg_execution_latency_ms']:.2f}ms")
            lines.append(f"   最大执行延迟: {stats['max_execution_latency_ms']:.2f}ms")
        if 'concurrent_order_send_gap_ms' in stats:
            lines.append(f"   并发发送间隔: {stats['concurrent_order_send_gap_ms']:.2f}ms")

        # 拒绝统计
        lines.append("\n拒绝统计:")
        lines.append(f"   滑点拒绝: {stats.get('slippage_rejections', 0)} 次")
        lines.append(f"   利润不足拒绝: {stats.get('profitability_rejections', 0)} 次")
        lines.append(f"   数据过期拒绝: {stats.get('stale_data_count', 0)} 次")

        lines.append("======================================================================")

        summary = "\n".join(lines)
        self.logger.info(summary)
        self.perf_logger.info("[统计摘要] " + summary.replace('\n', ' | '))

    # ========================================================================
    # T085: 交易操作记录 (CSV导出)
    # ========================================================================

    def record_decision(self, record: TradeOperationRecord) -> None:
        """记录交易决策

        Args:
            record: TradeOperationRecord对象
        """
        self._decision_records.append(record)

        # 限制记录数量，防止内存溢出
        if len(self._decision_records) > self._max_records:
            self._decision_records = self._decision_records[-self._max_records:]

        # 更新统计
        self._stats['total_checks'] += 1
        decision = record.decision or ''
        reason = record.reason or ''
        if '滑点超限' in decision or '滑点过大' in reason:
            self._stats['slippage_rejections'] += 1
        if '利润不足' in decision or '净利润不足' in reason:
            self._stats['profitability_rejections'] += 1

    def get_decision_records(
        self,
        last_n_minutes: Optional[int] = None
    ) -> List[TradeOperationRecord]:
        """获取决策记录

        Args:
            last_n_minutes: 获取最近N分钟的记录，None表示全部

        Returns:
            TradeOperationRecord列表
        """
        if last_n_minutes is None:
            return self._decision_records.copy()

        cutoff_time = time.time() - (last_n_minutes * 60)
        return [
            r for r in self._decision_records
            if r.timestamp >= cutoff_time
        ]

    # ========================================================================
    # CSV数据导出 (T079-T086)
    # ========================================================================

    def export_performance_data(
        self,
        last_n_minutes: Optional[int] = None,
        output_file: Optional[str] = None
    ) -> Optional[str]:
        """导出性能数据到CSV

        Args:
            last_n_minutes: 导出最近N分钟的数据，None表示全部
            output_file: 输出文件路径，None表示自动生成

        Returns:
            导出的文件路径，如果失败返回None
        """
        from pathlib import Path
        import csv

        try:
            # 生成文件名
            if output_file is None:
                output_dir = Path('data')
                output_dir.mkdir(exist_ok=True)
                from datetime import datetime
                output_file = output_dir / f"performance_{datetime.now().strftime('%Y_%m_%d')}.csv"

            # 准备数据
            stats = self.get_stats_summary()
            data = []

            # 从统计数据生成CSV行
            if self._stats['tick_to_trade_latencies']:
                for i, latency in enumerate(self._stats['tick_to_trade_latencies']):
                    data.append({
                        'timestamp': int(time.time()),
                        'metric': 'tick_to_trade_latency_ms',
                        'value': f"{latency:.2f}",
                        'index': i
                    })

            if self._stats['execution_latencies']:
                for i, latency in enumerate(self._stats['execution_latencies']):
                    data.append({
                        'timestamp': int(time.time()),
                        'metric': 'execution_latency_ms',
                        'value': f"{latency:.2f}",
                        'index': i
                    })

            if self._stats['concurrent_gaps']:
                for i, gap in enumerate(self._stats['concurrent_gaps']):
                    data.append({
                        'timestamp': int(time.time()),
                        'metric': 'concurrent_gap_ms',
                        'value': f"{gap:.2f}",
                        'index': i
                    })

            # 写入CSV
            if data:
                with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=['timestamp', 'metric', 'value', 'index'])
                    writer.writeheader()
                    writer.writerows(data)

                self.logger.info(f"✅ 性能数据已导出: {output_file}")
                return str(output_file)
            else:
                self.logger.warning("⚠️ 没有性能数据可导出")
                return None

        except Exception as e:
            self.logger.error(f"❌ 导出性能数据失败: {e}")
            return None

    def export_decision_records(
        self,
        last_n_minutes: Optional[int] = None,
        output_file: Optional[str] = None
    ) -> Optional[str]:
        """导出决策记录到CSV

        Args:
            last_n_minutes: 导出最近N分钟的数据，None表示全部
            output_file: 输出文件路径，None表示自动生成

        Returns:
            导出的文件路径，如果失败返回None
        """
        from pathlib import Path
        import csv
        from datetime import datetime

        try:
            # 生成文件名
            if output_file is None:
                output_dir = Path('data')
                output_dir.mkdir(exist_ok=True)
                output_file = output_dir / f"operations_{datetime.now().strftime('%Y_%m_%d')}.csv"

            # 获取决策记录
            records = self.get_decision_records(last_n_minutes)

            if not records:
                self.logger.warning("⚠️ 没有决策记录可导出")
                return None

            # 写入CSV
            fieldnames = [
                'timestamp', 'operation_type', 'exchange',
                'signal_ts', 'data_ts_A', 'data_ts_B', 'calc_ts',
                'send_A_ts', 'send_B_ts', 'ack_A_ts', 'ack_B_ts',
                'spread_rate', 'slippage_rate', 'profit_rate',
                'decision', 'status', 'reason', 'send_gap_ms',
                'tick_to_trade_latency_ms', 'execution_latency_ms'
            ]

            with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for record in records:
                    row = {
                        'timestamp': record.timestamp,
                        'operation_type': record.operation_type,
                        'exchange': record.exchange,
                        'signal_ts': record.signal_ts or '',
                        'data_ts_A': record.data_ts_A or '',
                        'data_ts_B': record.data_ts_B or '',
                        'calc_ts': record.calc_ts or '',
                        'send_A_ts': record.send_A_ts or '',
                        'send_B_ts': record.send_B_ts or '',
                        'ack_A_ts': record.ack_A_ts or '',
                        'ack_B_ts': record.ack_B_ts or '',
                        'spread_rate': str(record.spread_rate) if record.spread_rate else '',
                        'slippage_rate': str(record.slippage_rate) if record.slippage_rate else '',
                        'profit_rate': str(record.profit_rate) if record.profit_rate else '',
                        'decision': record.decision,
                        'status': record.status,
                        'reason': record.reason or '',
                        'send_gap_ms': record.send_gap_ms or '',
                        'tick_to_trade_latency_ms': record.tick_to_trade_latency_ms or '',
                        'execution_latency_ms': record.execution_latency_ms or '',
                    }
                    writer.writerow(row)

            self.logger.info(f"✅ 决策记录已导出: {output_file} ({len(records)} 条记录)")
            return str(output_file)

        except Exception as e:
            self.logger.error(f"❌ 导出决策记录失败: {e}")
            return None

    def export_latency_distribution(
        self,
        last_n_minutes: int = 60,
        output_file: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """导出延迟分布数据

        Args:
            last_n_minutes: 分析最近N分钟的数据
            output_file: 输出文件路径

        Returns:
            延迟分布统计字典
        """
        import statistics

        latencies = self._stats['tick_to_trade_latencies']

        if not latencies:
            return None

        distribution = {
            'count': len(latencies),
            'min': float(min(latencies)) if latencies else 0,
            'max': float(max(latencies)) if latencies else 0,
            'mean': float(statistics.mean(latencies)) if latencies else 0,
            'median': float(statistics.median(latencies)) if latencies else 0,
            'stdev': float(statistics.stdev(latencies)) if len(latencies) > 1 else 0,
        }

        self.logger.info(
            f"📊 延迟分布: "
            f"平均={distribution['mean']:.2f}ms, "
            f"中位数={distribution['median']:.2f}ms, "
            f"最大={distribution['max']:.2f}ms"
        )

        return distribution

    def export_slippage_analysis(
        self,
        last_n_minutes: int = 60
    ) -> Optional[Dict[str, Any]]:
        """导出滑点分析数据

        Args:
            last_n_minutes: 分析最近N分钟的数据

        Returns:
            滑点分析统计字典
        """
        # TODO: 实现滑点数据记录和分析
        analysis = {
            'total_checks': self._stats.get('slippage_rejections', 0),
            'rejections': self._stats.get('slippage_rejections', 0),
        }

        return analysis

    def export_profitability_analysis(
        self,
        last_n_minutes: int = 60
    ) -> Optional[Dict[str, Any]]:
        """导出利润率分析数据

        Args:
            last_n_minutes: 分析最近N分钟的数据

        Returns:
            利润率分析统计字典
        """
        # TODO: 实现利润率数据记录和分析
        analysis = {
            'total_checks': self._stats.get('profitability_rejections', 0),
            'rejections': self._stats.get('profitability_rejections', 0),
        }

        return analysis
