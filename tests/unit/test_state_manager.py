"""
状态管理器单元测试

测试Portfolio持久化和向后兼容性
"""

import json
import tempfile
import pytest
from pathlib import Path
from decimal import Decimal
from datetime import datetime

from spread.state_manager import StateManager
from spread.models import (
    BotState,
    Position,
    PositionState,
    BotStats,
    Portfolio,
    OpenPosition,
)


@pytest.mark.asyncio
async def test_load_old_state_without_portfolio():
    """测试加载旧的状态文件（没有portfolio字段）并转换为新格式"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"

        # 创建旧格式的状态文件（只有position，没有portfolio）
        old_state = {
            "state": "HOLDING",
            "position": {
                "state": "LONG",
                "extended_entry_price": "3325.5",
                "lighter_entry_price": "3320.0",
                "entry_spread": "0.0015",
                "entry_time": "2026-01-13T12:00:00",
                "extended_quantity": "0.01",
                "lighter_quantity": "-0.01",
                "extended_order_id": "ext_123",
                "lighter_order_id": "lig_456",
            },
            "stats": {
                "total_trades": 5,
                "profitable_trades": 3,
                "total_profit": "0.001",
                "total_fees": "0.0002",
                "start_time": "2026-01-13T10:00:00",
                "last_trade_time": "2026-01-13T12:00:00",
            },
            "last_save_time": "2026-01-13T12:00:00",
        }

        # 写入旧状态文件
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(old_state, f)

        # 加载状态
        manager = StateManager(state_file)
        state = await manager.load_state()

        # 验证状态（使用.value进行比较以避免模块导入问题）
        assert state.value == BotState.HOLDING.value
        assert manager.get_state().value == BotState.HOLDING.value

        # 验证旧的Position仍然存在
        old_position = manager.get_position()
        assert old_position is not None
        assert old_position.state.value == PositionState.LONG.value
        assert old_position.extended_entry_price == Decimal("3325.5")
        assert old_position.lighter_entry_price == Decimal("3320.0")

        # 验证Portfolio已从旧Position转换
        portfolio = manager.get_portfolio()
        assert portfolio is not None
        assert len(portfolio.get_active_positions()) == 1

        converted_position = portfolio.get_active_positions()[0]
        assert converted_position.ext_price == Decimal("3325.5")
        assert converted_position.lig_price == Decimal("3320.0")
        assert converted_position.quantity == Decimal("0.01")
        assert converted_position.is_active is True
        assert converted_position.position_id.startswith("legacy_")


@pytest.mark.asyncio
async def test_load_new_state_with_portfolio():
    """测试加载新格式的状态文件（包含portfolio字段）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"

        # 创建新格式的状态文件（包含portfolio）
        new_state = {
            "state": "HOLDING",
            "position": None,  # 新格式可能没有旧的position
            "portfolio": {
                "positions": [
                    {
                        "position_id": "pos_001",
                        "open_time": 1736755200.123,
                        "ext_price": "3325.5",
                        "lig_price": "3320.0",
                        "open_spread": "0.0015",
                        "quantity": "0.01",
                        "ext_order_id": "ext_123",
                        "lig_order_id": "lig_456",
                        "is_active": True,
                    },
                    {
                        "position_id": "pos_002",
                        "open_time": 1736755300.456,
                        "ext_price": "3326.0",
                        "lig_price": "3321.5",
                        "open_spread": "0.0013",
                        "quantity": "0.01",
                        "ext_order_id": "ext_789",
                        "lig_order_id": "lig_012",
                        "is_active": True,
                    },
                ],
                "total_quantity": "0.02",
                "weighted_avg_entry_spread": "0.0014",
                "first_open_time": 1736755200.123,
                "last_open_time": 1736755300.456,
            },
            "stats": {
                "total_trades": 10,
                "profitable_trades": 7,
                "total_profit": "0.003",
                "total_fees": "0.0005",
                "start_time": "2026-01-13T10:00:00",
                "last_trade_time": "2026-01-13T12:30:00",
            },
            "last_save_time": "2026-01-13T12:30:00",
        }

        # 写入新状态文件
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(new_state, f)

        # 加载状态
        manager = StateManager(state_file)
        state = await manager.load_state()

        # 验证状态（使用.value进行比较以避免模块导入问题）
        assert state.value == BotState.HOLDING.value

        # 验证Portfolio正确加载
        portfolio = manager.get_portfolio()
        assert portfolio is not None
        assert len(portfolio.get_active_positions()) == 2
        assert portfolio.total_quantity == Decimal("0.02")
        assert portfolio.weighted_avg_entry_spread == Decimal("0.0014")

        # 验证第一个仓位
        pos1 = portfolio.get_active_positions()[0]
        assert pos1.position_id == "pos_001"
        assert pos1.ext_price == Decimal("3325.5")
        assert pos1.quantity == Decimal("0.01")

        # 验证第二个仓位
        pos2 = portfolio.get_active_positions()[1]
        assert pos2.position_id == "pos_002"
        assert pos2.ext_price == Decimal("3326.0")


@pytest.mark.asyncio
async def test_save_and_load_portfolio():
    """测试保存和加载Portfolio"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"

        # 创建StateManager
        manager = StateManager(state_file)
        await manager.load_state()  # 初始化为空状态

        # 创建Portfolio并添加仓位
        portfolio = Portfolio()
        position1 = OpenPosition(
            position_id="pos_001",
            open_time=1736755200.123,
            ext_price=Decimal("3325.5"),
            lig_price=Decimal("3320.0"),
            open_spread=Decimal("0.0015"),
            quantity=Decimal("0.01"),
            ext_order_id="ext_123",
            lig_order_id="lig_456",
            is_active=True,
        )
        position2 = OpenPosition(
            position_id="pos_002",
            open_time=1736755300.456,
            ext_price=Decimal("3326.0"),
            lig_price=Decimal("3321.5"),
            open_spread=Decimal("0.0013"),
            quantity=Decimal("0.01"),
            ext_order_id="ext_789",
            lig_order_id="lig_012",
            is_active=True,
        )
        portfolio.add_position(position1)
        portfolio.add_position(position2)

        # 保存状态
        manager.set_state(BotState.HOLDING)
        manager.update_portfolio(portfolio)
        await manager.save_state()

        # 验证文件存在
        assert state_file.exists()

        # 创建新的StateManager并加载
        manager2 = StateManager(state_file)
        await manager2.load_state()

        # 验证Portfolio正确加载
        loaded_portfolio = manager2.get_portfolio()
        assert len(loaded_portfolio.get_active_positions()) == 2
        assert loaded_portfolio.total_quantity == Decimal("0.02")
        assert abs(loaded_portfolio.weighted_avg_entry_spread - Decimal("0.0014")) < Decimal("0.0001")


@pytest.mark.asyncio
async def test_empty_state_initialization():
    """测试空状态文件初始化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"

        # 状态文件不存在时初始化
        manager = StateManager(state_file)
        state = await manager.load_state()

        # 验证默认状态（使用.value进行比较以避免模块导入问题）
        assert state.value == BotState.IDLE.value
        assert manager.get_state().value == BotState.IDLE.value
        assert manager.get_position() is None

        # 验证Portfolio为空
        portfolio = manager.get_portfolio()
        assert portfolio is not None
        assert len(portfolio.get_active_positions()) == 0
        assert portfolio.total_quantity == Decimal("0")
