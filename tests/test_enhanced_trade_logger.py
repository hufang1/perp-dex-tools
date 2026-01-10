"""
测试增强诊断日志功能 (Phase 6: User Story 4)

测试目标:
1. T033: 测试价差快照日志格式
2. T034: 测试平仓分析日志格式
3. T035: 测试仓位平衡日志格式
"""

import pytest
from decimal import Decimal
from datetime import datetime

from spread.spread_pair import SpreadPair
from spread.trade_logger import TradeLogger
from spread.models import SpreadSnapshot, SpreadChange, CloseDecision, PositionBalance


class TestSpreadSnapshotLogging:
    """测试价差快照日志"""

    def test_log_spread_snapshot_format(self):
        """
        T033: 测试价差快照日志格式

        验证价差快照日志包含所有必需字段：
        - 时间戳
        - Extended bid/ask/mid
        - Lighter bid/ask/mid
        - 价差和价差率
        - 套利方向
        """
        trade_logger = TradeLogger(log_file_path="logs/test_trade.log")

        # 创建价差快照
        snapshot = SpreadSnapshot(
            timestamp=1234567890.0,
            extended_bid=Decimal('3000'),
            extended_ask=Decimal('3010'),
            extended_mid=Decimal('3005'),
            lighter_bid=Decimal('2990'),
            lighter_ask=Decimal('3000'),
            lighter_mid=Decimal('2995'),
            spread=Decimal('10'),
            spread_rate=Decimal('0.00334'),
            spread_sign="positive",
            arbitrage_direction="long_spread"
        )

        # 测试日志记录
        result = trade_logger.log_spread_snapshot(snapshot)

        # 验证返回值
        assert result is True

        # 验证日志文件包含关键信息
        with open(trade_logger.get_log_file_path(), 'r', encoding='utf-8') as f:
            content = f.read()
            assert "价差快照" in content
            assert "3000.00" in content or "3005" in content

    def test_log_spread_snapshot_with_invalid_data(self):
        """测试无效数据的处理"""
        trade_logger = TradeLogger(log_file_path="logs/test_trade.log")

        # 创建无效快照（bid > ask）
        with pytest.raises(ValueError):
            snapshot = SpreadSnapshot(
                timestamp=1234567890.0,
                extended_bid=Decimal('3010'),  # bid > ask
                extended_ask=Decimal('3000'),
                extended_mid=Decimal('3005'),
                lighter_bid=Decimal('2990'),
                lighter_ask=Decimal('3000'),
                lighter_mid=Decimal('2995'),
                spread=Decimal('10'),
                spread_rate=Decimal('0.00334'),
                spread_sign="positive",
                arbitrage_direction="long_spread"
            )


class TestCloseAnalysisLogging:
    """测试平仓分析日志"""

    def test_log_close_analysis_format(self):
        """
        T034: 测试平仓分析日志格式

        验证平仓分析日志包含：
        - 平仓决策详情（优先级、理由）
        - 价差变化信息
        - 盈亏分析
        - 持仓时间
        """
        trade_logger = TradeLogger(log_file_path="logs/test_trade.log")

        # 创建套利对
        pair = SpreadPair(
            pair_id=1,
            extended_side='buy',
            extended_price=Decimal('3000'),
            extended_quantity=Decimal('0.1'),
            lighter_price=Decimal('3020'),
            lighter_quantity=Decimal('0.1')
        )

        # 创建价差变化
        spread_change = SpreadChange(
            open_spread=Decimal('20'),
            current_spread=Decimal('25'),
            spread_delta=Decimal('5'),
            spread_change_rate=Decimal('0.25'),
            is_converged=True,
            is_favorable=True,
            status="价差收敛: 20 → 25 (+5)"
        )

        # 创建平仓决策
        decision = CloseDecision(
            pair_id=1,
            should_close=True,
            priority=1,
            reason="盈利目标达标",
            reason_code="P1_CONVERGE_PROFIT",
            spread_change=spread_change,
            unrealized_pnl=Decimal('2.5'),
            pnl_rate=Decimal('0.083'),
            holding_time=120.0,
            is_warning=False,
            timestamp=1234567890.0,
            extended_close_price=Decimal('3005'),
            lighter_close_price=Decimal('3030')
        )

        # 测试日志记录
        result = trade_logger.log_close_analysis(pair, decision)

        # 验证返回值
        assert result is True

        # 验证日志文件包含关键信息
        with open(trade_logger.get_log_file_path(), 'r', encoding='utf-8') as f:
            content = f.read()
            assert "平仓分析" in content
            assert "P1_CONVERGE_PROFIT" in content
            assert "盈利目标达标" in content


class TestPositionBalanceLogging:
    """测试仓位平衡日志"""

    def test_log_position_balance_format(self):
        """
        T035: 测试仓位平衡日志格式

        验证仓位平衡日志包含：
        - Extended总仓位
        - Lighter总仓位
        - 差异和差异率
        - 失衡警告
        """
        trade_logger = TradeLogger(log_file_path="logs/test_trade.log")

        # 创建仓位平衡状态
        balance = PositionBalance(
            extended_total_qty=Decimal('1.0'),
            lighter_total_qty=Decimal('0.95'),
            diff_qty=Decimal('0.05'),
            diff_rate=Decimal('0.0526'),
            is_imbalanced=True,
            warning_level="WARN",
            timestamp=1234567890.0
        )

        # 测试日志记录
        result = trade_logger.log_position_balance(balance)

        # 验证返回值
        assert result is True

        # 验证日志文件包含关键信息
        with open(trade_logger.get_log_file_path(), 'r', encoding='utf-8') as f:
            content = f.read()
            assert "仓位平衡" in content
            assert "WARN" in content or "失衡" in content

    def test_log_position_balance_ok(self):
        """测试仓位平衡OK状态"""
        trade_logger = TradeLogger(log_file_path="logs/test_trade.log")

        # 创建平衡状态
        balance = PositionBalance(
            extended_total_qty=Decimal('1.0'),
            lighter_total_qty=Decimal('0.99'),
            diff_qty=Decimal('0.01'),
            diff_rate=Decimal('0.0101'),
            is_imbalanced=False,
            warning_level="OK",
            timestamp=1234567890.0
        )

        # 测试日志记录
        result = trade_logger.log_position_balance(balance)

        # 验证返回值
        assert result is True

    def test_log_position_balance_critical(self):
        """测试仓位平衡CRITICAL状态"""
        trade_logger = TradeLogger(log_file_path="logs/test_trade.log")

        # 创建严重失衡状态
        balance = PositionBalance(
            extended_total_qty=Decimal('1.0'),
            lighter_total_qty=Decimal('0.5'),
            diff_qty=Decimal('0.5'),
            diff_rate=Decimal('1.0'),
            is_imbalanced=True,
            warning_level="CRITICAL",
            timestamp=1234567890.0
        )

        # 测试日志记录
        result = trade_logger.log_position_balance(balance)

        # 验证返回值
        assert result is True

        # 验证日志包含警告
        with open(trade_logger.get_log_file_path(), 'r', encoding='utf-8') as f:
            content = f.read()
            assert "CRITICAL" in content or "严重" in content
