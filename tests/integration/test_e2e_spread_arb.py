"""
端到端套利流程测试

测试完整的开仓-平仓循环，验证所有组件协同工作
"""

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from models import (
    BotState,
    Position,
    PositionState,
    BotConfig,
    BotStats,
    OrderBook,
    SpreadInfo,
)
from spread_calculator import SpreadCalculator
from state_manager import StateManager
from order_book_manager import OrderBookManager
from exceptions import SpreadArbError


# ============================================================================
# T054: 端到端套利流程测试
# ============================================================================

class TestE2ESpreadArbFlow:
    """测试端到端套利流程"""

    @pytest.fixture
    def config(self):
        """测试配置"""
        return BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("0.002"),
            slippage_buffer=Decimal("0.0005"),
            min_profit=Decimal("0.001"),
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

    @pytest.fixture
    def order_book_manager(self):
        """创建订单簿管理器"""
        manager = OrderBookManager("BTC")

        # 设置初始订单簿 - Lighter 价格更高（有套利机会）
        manager.update_lighter_order_book(
            bids={Decimal("100000"): Decimal("1.0"), Decimal("99990"): Decimal("2.0")},
            asks={Decimal("100010"): Decimal("1.0"), Decimal("100020"): Decimal("2.0")},
            sequence=1,
            is_snapshot=True
        )

        # Extended 价格更低
        manager.update_extended_order_book(
            bids={Decimal("99700"): Decimal("1.0"), Decimal("99690"): Decimal("2.0")},
            asks={Decimal("99710"): Decimal("1.0"), Decimal("99720"): Decimal("2.0")},
            sequence=1,
            is_snapshot=True
        )

        return manager

    @pytest.fixture
    def state_manager(self, tmp_path):
        """创建状态管理器"""
        state_file = tmp_path / "test_state.json"
        return StateManager(state_file)

    def test_full_arbitrage_cycle_simulation(self, config, order_book_manager, state_manager):
        """测试完整套利循环模拟"""
        # 1. 初始化状态
        assert state_manager.get_state() == BotState.IDLE
        assert state_manager.get_position() is None

        # 2. 创建价差计算器
        calculator = SpreadCalculator(
            open_threshold=config.min_spread_threshold,
            slippage_buffer=config.slippage_buffer,
            min_profit=config.min_profit,
            max_spread=config.max_spread,
        )

        # 3. 计算开仓价差
        spread_info = asyncio.run(calculator.calculate_open_spread(
            order_book_manager,
            config.target_quantity
        ))

        assert spread_info is not None
        assert spread_info.open_spread > config.min_spread_threshold

        # 4. 验证开仓条件
        should_open = calculator.should_open(spread_info.open_spread)
        assert should_open is True

        # 5. 模拟开仓
        position = Position(
            state=PositionState.LONG,
            extended_entry_price=Decimal("99710"),
            lighter_entry_price=Decimal("100000"),
            entry_spread=spread_info.open_spread,
            entry_time=datetime.now(),
            extended_quantity=config.target_quantity,
            lighter_quantity=-config.target_quantity,
            extended_order_id="ext_open_123",
            lighter_order_id="lt_open_123",
        )

        state_manager.update_position(position)
        state_manager.set_state(BotState.HOLDING)

        assert state_manager.get_state() == BotState.HOLDING
        assert state_manager.get_position().is_open() is True

        # 6. 模拟价差收敛
        # 更新订单簿使价差收敛
        order_book_manager.update_lighter_order_book(
            bids={Decimal("99900"): Decimal("1.0")},
            asks={Decimal("99910"): Decimal("1.0")},
            sequence=2,
            is_snapshot=True
        )

        order_book_manager.update_extended_order_book(
            bids={Decimal("99800"): Decimal("1.0")},
            asks={Decimal("99810"): Decimal("1.0")},
            sequence=2,
            is_snapshot=True
        )

        # 7. 计算平仓价差
        close_spread_info = asyncio.run(calculator.calculate_close_spread(
            order_book_manager,
            config.target_quantity
        ))

        assert close_spread_info is not None

        # 8. 验证平仓条件
        should_close = calculator.should_close(
            position.entry_spread,
            close_spread_info.close_spread,
            position
        )

        # 9. 模拟平仓
        if should_close:
            # 计算利润
            profit = calculator.calculate_profit_potential(
                position.entry_spread,
                config.target_quantity,
                position.extended_entry_price
            )

            # 更新统计
            stats = state_manager.get_stats()
            stats.total_trades += 1
            stats.total_profit += profit
            if profit > 0:
                stats.profitable_trades += 1
            stats.last_trade_time = datetime.now()
            state_manager.update_stats(stats)

            # 清除持仓
            state_manager.update_position(None)
            state_manager.set_state(BotState.IDLE)

            assert state_manager.get_state() == BotState.IDLE
            assert state_manager.get_position() is None
            assert stats.total_trades == 1

    def test_state_persistence(self, state_manager):
        """测试状态持久化"""
        # 创建测试持仓
        position = Position(
            state=PositionState.LONG,
            extended_entry_price=Decimal("100000"),
            lighter_entry_price=Decimal("100500"),
            entry_spread=Decimal("0.005"),
            entry_time=datetime.now(),
            extended_quantity=Decimal("0.1"),
            lighter_quantity=Decimal("-0.1"),
        )

        stats = BotStats(
            total_trades=5,
            profitable_trades=3,
            total_profit=Decimal("100.50"),
            total_fees=Decimal("10.00"),
            start_time=datetime.now(),
        )

        # 保存状态
        asyncio.run(state_manager.save_state(
            BotState.HOLDING,
            position,
            stats
        ))

        # 验证状态
        assert state_manager.get_state() == BotState.HOLDING
        assert state_manager.get_position().is_open() is True
        assert state_manager.get_stats().total_trades == 5

    def test_config_validation_comprehensive(self):
        """测试全面配置验证"""
        # 有效配置
        valid_config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("0.002"),
            slippage_buffer=Decimal("0.0005"),
            min_profit=Decimal("0.001"),
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

        assert valid_config.validate() is True

        # 无效配置（利润阈值太小）
        invalid_config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("0.002"),
            slippage_buffer=Decimal("0.0005"),
            min_profit=Decimal("0.0001"),  # 太小
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

        assert invalid_config.validate() is False

    def test_order_book_validation_comprehensive(self):
        """测试全面订单簿验证"""
        # 有效订单簿
        valid_book = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("99990"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        assert valid_book.validate() is True

        # 买价高于卖价
        invalid_book1 = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("100020"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        assert invalid_book1.validate() is False

        # 零价格
        invalid_book2 = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("0"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        assert invalid_book2.validate() is False

        # 负数量
        invalid_book3 = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("99990"): Decimal("-1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        assert invalid_book3.validate() is False

    def test_spread_info_validation(self):
        """测试价差信息验证"""
        # 有效的价差信息
        spread_info = SpreadInfo(
            open_spread=Decimal("0.003"),
            lighter_bid_vwap=Decimal("100000"),
            extended_ask_vwap=Decimal("99700"),
            timestamp=datetime.now(),
            is_reasonable=True
        )

        assert spread_info.open_spread == Decimal("0.003")
        assert spread_info.is_reasonable is True

    def test_position_lifecycle(self):
        """测试持仓生命周期"""
        position = Position()

        # 初始状态
        assert position.state == PositionState.NONE
        assert position.is_open() is False
        assert position.validate() is True

        # 开仓
        position.state = PositionState.LONG
        position.extended_entry_price = Decimal("100000")
        position.lighter_entry_price = Decimal("100500")
        position.entry_spread = Decimal("0.005")
        position.entry_time = datetime.now()
        position.extended_quantity = Decimal("0.1")
        position.lighter_quantity = Decimal("-0.1")

        assert position.is_open() is True
        assert position.validate() is True

        # 平仓
        position.state = PositionState.NONE
        position.extended_quantity = Decimal("0")
        position.lighter_quantity = Decimal("0")

        assert position.is_open() is False
        assert position.validate() is True

    def test_error_handling(self):
        """测试错误处理"""
        from exceptions import (
            OrderBookNotReadyError,
            InsufficientDepthError,
            ExtremeSpreadError,
        )

        # 测试订单簿未就绪异常
        with pytest.raises(OrderBookNotReadyError):
            raise OrderBookNotReadyError("测试异常")

        # 测试深度不足异常
        error = InsufficientDepthError("test", 1.0, 0.5)
        assert str(error) == "test 订单簿深度不足：需要 1.0，可用 0.5"

        # 测试极端价差异常
        error = ExtremeSpreadError(Decimal("0.06"), Decimal("0.05"))
        assert "极端价差" in str(error)
