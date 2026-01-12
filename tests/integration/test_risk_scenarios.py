"""
风控场景集成测试

测试用户故事3：风险控制与异常处理
完整的风控场景测试，包括异常情况的处理
"""

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from models import (
    OrderBook,
    SpreadInfo,
    Position,
    PositionState,
    BotConfig,
    BotState,
)
from risk_manager import RiskManager, ValidationResult
from order_book_manager import OrderBookManager
from spread_calculator import SpreadCalculator
from exceptions import (
    InsufficientDepthError,
    ExtremeSpreadError,
    OrderBookSequenceError,
)


# ============================================================================
# T042: 风控场景集成测试
# ============================================================================

class TestRiskScenariosIntegration:
    """测试风控场景集成"""

    @pytest.fixture
    def config(self):
        """测试配置"""
        return BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("0.002"),
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

    @pytest.fixture
    def order_book_manager(self):
        """创建订单簿管理器"""
        manager = OrderBookManager("BTC")

        # 设置初始订单簿
        manager.update_lighter_order_book(
            bids={Decimal("100000"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            sequence=1,
            is_snapshot=True
        )

        manager.update_extended_order_book(
            bids={Decimal("99900"): Decimal("1.0")},
            asks={Decimal("99910"): Decimal("1.0")},
            sequence=1,
            is_snapshot=True
        )

        return manager

    def test_scenario_extreme_spread_rejection(self, config, order_book_manager):
        """测试场景：极端价差被拒绝"""
        calculator = SpreadCalculator(
            open_threshold=Decimal("0.002"),
            max_spread=Decimal("0.05")  # 5% 阈值
        )

        # 6% 的价差应该被拒绝
        assert calculator.is_spread_reasonable(Decimal("0.06")) is False

    def test_scenario_insufficient_depth(self, order_book_manager):
        """测试场景：订单簿深度不足"""
        # 尝试交易 2 BTC，但只有 1 BTC 可用
        order_book = order_book_manager.get_order_book("lighter")

        # 深度应该不足
        assert order_book.check_depth(Decimal("2.0")) is False

    def test_scenario_sequence_gap_detection(self):
        """测试场景：序列号缺失检测"""
        from utils import validate_order_book_integrity

        # 序列号跳跃
        is_valid, error = validate_order_book_integrity(
            current_sequence=10,
            last_sequence=5,
            exchange="test"
        )

        assert is_valid is False
        assert "序列号缺失" in error

    def test_scenario_sequence_non_increasing(self):
        """测试场景：序列号未递增"""
        from utils import validate_order_book_integrity

        # 序列号未递增
        is_valid, error = validate_order_book_integrity(
            current_sequence=5,
            last_sequence=5,
            exchange="test"
        )

        assert is_valid is False
        assert "未递增" in error

    def test_scenario_position_validation(self):
        """测试场景：持仓验证"""
        # 有效的多头持仓
        position = Position(
            state=PositionState.LONG,
            extended_entry_price=Decimal("100000"),
            lighter_entry_price=Decimal("100500"),
            entry_spread=Decimal("0.005"),
            entry_time=datetime.now(),
            extended_quantity=Decimal("0.1"),
            lighter_quantity=Decimal("-0.1"),
        )

        assert position.validate() is True

    def test_scenario_invalid_position_mismatched_quantities(self):
        """测试场景：无效持仓（数量不匹配）"""
        # 多头持仓，但数量不匹配
        position = Position(
            state=PositionState.LONG,
            extended_entry_price=Decimal("100000"),
            lighter_entry_price=Decimal("100500"),
            entry_spread=Decimal("0.005"),
            entry_time=datetime.now(),
            extended_quantity=Decimal("0.1"),
            lighter_quantity=Decimal("-0.2"),  # 数量不匹配
        )

        assert position.validate() is False

    def test_scenario_spread_convergence_detection(self):
        """测试场景：价差收敛检测"""
        calculator = SpreadCalculator(min_profit=Decimal("0.001"))

        position = Position(
            state=PositionState.LONG,
            entry_spread=Decimal("0.005")  # 开仓 0.5%
        )

        # 平仓价差 0.2%，收敛 0.3% > 0.1% 最小利润
        close_spread = Decimal("0.002")

        assert calculator.should_close(
            position.entry_spread,
            close_spread,
            position
        ) is True

    def test_scenario_spread_divergence_no_close(self):
        """测试场景：价差发散，不满足平仓条件"""
        calculator = SpreadCalculator(min_profit=Decimal("0.001"))

        position = Position(
            state=PositionState.LONG,
            entry_spread=Decimal("0.003")  # 开仓 0.3%
        )

        # 平仓价差 0.4%，价差扩大
        close_spread = Decimal("0.004")

        assert calculator.should_close(
            position.entry_spread,
            close_spread,
            position
        ) is False

    @pytest.mark.asyncio
    async def test_scenario_order_book_update_with_validation(self):
        """测试场景：订单簿更新与验证"""
        manager = OrderBookManager("BTC")

        # 第一次更新（快照）
        manager.update_lighter_order_book(
            bids={Decimal("100000"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            sequence=1,
            is_snapshot=True
        )

        assert manager.lighter_order_book is not None
        assert manager.lighter_order_book.sequence == 1

        # 第二次更新（增量）
        manager.update_lighter_order_book(
            bids={Decimal("100001"): Decimal("0.5")},
            asks={},
            sequence=2,
            is_snapshot=False
        )

        assert manager.lighter_order_book.sequence == 2

    @pytest.mark.asyncio
    async def test_scenario_order_book_sequence_error_recovery(self):
        """测试场景：订单簿序列号错误恢复"""
        manager = OrderBookManager("BTC")

        # 第一次更新
        manager.update_lighter_order_book(
            bids={Decimal("100000"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            sequence=1,
            is_snapshot=True
        )

        # 序列号跳跃（应该请求快照）
        manager.update_lighter_order_book(
            bids={Decimal("100001"): Decimal("0.5")},
            asks={},
            sequence=10,  # 跳跃
            is_snapshot=False
        )

        # 订单簿应该被标记为无效
        assert manager.lighter_order_book.is_valid is False

    def test_scenario_config_validation(self):
        """测试场景：配置验证"""
        # 有效配置
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("0.002"),
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

        assert config.validate() is True

    def test_scenario_invalid_config(self):
        """测试场景：无效配置"""
        # 无效配置（负价差阈值）
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("-0.001"),  # 负值无效
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

        assert config.validate() is False

    def test_scenario_vwap_depth_calculation(self):
        """测试场景：VWAP 深度计算"""
        from utils import calculate_vwap

        order_book = {
            Decimal("100000"): Decimal("0.5"),
            Decimal("100010"): Decimal("0.3"),
            Decimal("100020"): Decimal("0.2"),
        }

        # 计算 0.8 的 VWAP
        vwap = calculate_vwap(order_book, Decimal("0.8"), "buy")

        assert vwap is not None
        # 应该接近第一个价格
        assert vwap >= Decimal("100000")
        assert vwap <= Decimal("100010")
