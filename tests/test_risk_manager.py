"""
风控管理器测试

测试用户故事3：风险控制与异常处理
- 余额检查测试
- 深度验证测试
- 极端价差过滤测试
- 单边成交超时测试
"""

import pytest
from decimal import Decimal
from datetime import datetime

from models import (
    OrderBook,
    SpreadInfo,
    Position,
    PositionState,
    BotConfig,
)
from risk_manager import RiskManager, ValidationResult
from exceptions import (
    BalanceInsufficientError,
    InsufficientDepthError,
    ExtremeSpreadError,
)


# ============================================================================
# T038: 余额检查测试
# ============================================================================

class TestBalanceCheck:
    """测试余额检查"""

    @pytest.fixture
    def mock_risk_manager(self):
        """创建模拟风控管理器"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            max_spread=Decimal("0.05"),
        )

        class MockClient:
            async def get_balance(self):
                return {"available": Decimal("10000")}  # $10,000

        return RiskManager(MockClient(), MockClient(), config)

    @pytest.mark.asyncio
    async def test_check_balance_sufficient(self, mock_risk_manager):
        """测试余额充足"""
        # 检查 $1,000 的交易，余额 $10,000 足够
        result = await mock_risk_manager.check_balance(
            "lighter",
            Decimal("0.01"),
            Decimal("100000")
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_balance_insufficient(self, mock_risk_manager):
        """测试余额不足"""
        # 检查 $20,000 的交易，余额 $10,000 不足
        result = await mock_risk_manager.check_balance(
            "lighter",
            Decimal("0.2"),
            Decimal("100000")
        )

        assert result is False


# ============================================================================
# T039: 深度验证测试
# ============================================================================

class TestDepthValidation:
    """测试深度验证"""

    @pytest.mark.asyncio
    async def test_validate_open_position_sufficient_depth(self):
        """测试订单簿深度充足"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            max_spread=Decimal("0.05"),
        )

        class MockClient:
            async def get_balance(self):
                return {"available": Decimal("10000")}

        risk_manager = RiskManager(MockClient(), MockClient(), config)

        class MockOrderBookManager:
            def get_order_book(self, exchange):
                return OrderBook(
                    exchange=exchange,
                    symbol="BTC-USD",
                    bids={Decimal("100000"): Decimal("1.0")},  # 深度充足
                    asks={Decimal("100010"): Decimal("1.0")},
                    is_valid=True
                )

        spread_info = SpreadInfo(
            open_spread=Decimal("0.002"),
            lighter_bid_vwap=Decimal("100000"),
            extended_ask_vwap=Decimal("99900"),
            is_reasonable=True
        )

        result = await risk_manager.validate_open_position(
            MockOrderBookManager(),
            Decimal("0.01"),
            spread_info
        )

        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_validate_open_position_insufficient_depth(self):
        """测试订单簿深度不足"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("1.0"),  # 需要 1 BTC
            max_spread=Decimal("0.05"),
        )

        class MockClient:
            async def get_balance(self):
                return {"available": Decimal("100000")}

        risk_manager = RiskManager(MockClient(), MockClient(), config)

        class MockOrderBookManager:
            def get_order_book(self, exchange):
                return OrderBook(
                    exchange=exchange,
                    symbol="BTC-USD",
                    bids={Decimal("100000"): Decimal("0.01")},  # 深度不足
                    asks={Decimal("100010"): Decimal("0.01")},
                    is_valid=True
                )

        spread_info = SpreadInfo(
            open_spread=Decimal("0.002"),
            lighter_bid_vwap=Decimal("100000"),
            extended_ask_vwap=Decimal("99900"),
            is_reasonable=True
        )

        result = await risk_manager.validate_open_position(
            MockOrderBookManager(),
            Decimal("1.0"),
            spread_info
        )

        assert result.is_valid is False
        assert "深度不足" in result.reason


# ============================================================================
# T040: 极端价差过滤测试
# ============================================================================

class TestExtremeSpreadFilter:
    """测试极端价差过滤"""

    def test_is_spread_reasonable_normal(self):
        """测试正常价差"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            max_spread=Decimal("0.05"),  # 5%
        )

        class MockClient:
            async def get_balance(self):
                return {"available": Decimal("10000")}

        risk_manager = RiskManager(MockClient(), MockClient(), config)

        # 2% 的价差应该正常
        assert risk_manager.is_spread_reasonable(Decimal("0.02")) is True

        # 0.5% 的价差应该正常
        assert risk_manager.is_spread_reasonable(Decimal("0.005")) is True

    def test_is_spread_reasonable_extreme(self):
        """测试极端价差"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            max_spread=Decimal("0.05"),  # 5%
        )

        class MockClient:
            async def get_balance(self):
                return {"available": Decimal("10000")}

        risk_manager = RiskManager(MockClient(), MockClient(), config)

        # 6% 的价差应该被拒绝
        assert risk_manager.is_spread_reasonable(Decimal("0.06")) is False

        # 10% 的价差应该被拒绝
        assert risk_manager.is_spread_reasonable(Decimal("0.10")) is False

    def test_is_spread_reasonable_negative(self):
        """测试负价差"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            max_spread=Decimal("0.05"),
        )

        class MockClient:
            async def get_balance(self):
                return {"available": Decimal("10000")}

        risk_manager = RiskManager(MockClient(), MockClient(), config)

        # 负价差应该被拒绝
        assert risk_manager.is_spread_reasonable(Decimal("-0.01")) is False


# ============================================================================
# T041: 单边成交超时测试
# ============================================================================

class TestExecutionTimeout:
    """测试单边成交超时"""

    def test_timeout_configuration(self):
        """测试超时配置"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            single_side_timeout=3.0,  # 3 秒超时
        )

        assert config.single_side_timeout == 3.0

    def test_timeout_validation(self):
        """测试超时验证"""
        # 测试有效的超时值
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            single_side_timeout=5.0,
        )

        assert config.validate() is True

    def test_zero_timeout_invalid(self):
        """测试零超时无效"""
        from models import BotConfig

        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            single_side_timeout=0.0,  # 无效
        )

        # 零超时应该被拒绝
        assert config.validate() is False


# ============================================================================
# T042: 风控场景集成测试
# ============================================================================

class TestRiskScenarios:
    """测试风控场景集成"""

    def test_full_validation_flow(self):
        """测试完整验证流程"""
        config = BotConfig(
            symbol="BTC",
            target_quantity=Decimal("0.01"),
            min_spread_threshold=Decimal("0.002"),
            max_spread=Decimal("0.05"),
            single_side_timeout=3.0,
        )

        # 验证配置有效
        assert config.validate() is True

    def test_position_state_validation(self):
        """测试持仓状态验证"""
        position = Position(
            state=PositionState.LONG,
            extended_entry_price=Decimal("100000"),
            lighter_entry_price=Decimal("100500"),
            entry_spread=Decimal("0.005"),
            entry_time=datetime.now(),
            extended_quantity=Decimal("0.1"),
            lighter_quantity=Decimal("-0.1"),
        )

        # 验证持仓有效
        assert position.validate() is True
        assert position.is_open() is True

    def test_order_book_validation(self):
        """测试订单簿验证"""
        order_book = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("99990"): Decimal("1.0")},
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        # 验证订单簿有效
        assert order_book.validate() is True

    def test_order_book_invalid_bid_above_ask(self):
        """测试买价高于卖价无效"""
        order_book = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("100020"): Decimal("1.0")},  # 买价高于卖价
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        # 验证应该失败
        assert order_book.validate() is False

    def test_order_book_invalid_negative_price(self):
        """测试负价格无效"""
        order_book = OrderBook(
            exchange="test",
            symbol="BTC-USD",
            bids={Decimal("-100"): Decimal("1.0")},  # 负价格
            asks={Decimal("100010"): Decimal("1.0")},
            is_valid=True
        )

        # 验证应该失败
        assert order_book.validate() is False
