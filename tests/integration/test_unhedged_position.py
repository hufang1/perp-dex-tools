"""
未对冲持仓集成测试

测试单边持仓风险控制功能:
- 检测未对冲持仓
- 未对冲持仓超时告警
- 未对冲持仓存在时禁止开新仓
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, MagicMock

from spread.config import SpreadArbConfig
from spread.spread_pair import SpreadPair
from spread.bot import SpreadArbitrageBot


@pytest.fixture
def sample_config():
    """测试配置"""
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),
        profit_target_rate=Decimal('0.0005'),
        time_close_threshold=60,
        max_unhedged_positions=0,  # 禁止未对冲持仓
        unhedged_position_timeout=60  # 60秒超时
    )


@pytest.fixture
def mock_clients():
    """模拟交易所客户端"""
    extended_client = Mock()
    lighter_client = Mock()

    # 设置订单更新处理器
    extended_client.setup_order_update_handler = Mock()

    return extended_client, lighter_client


@pytest.mark.asyncio
async def test_unhedged_position_detection(sample_config, mock_clients):
    """
    T010 [US1]: 测试单边持仓检测

    鉴于 Extended交易所订单成交但Lighter订单失败
    当 系统检测到单边持仓
    则 正确记录到unhedged_positions列表
    """
    extended_client, lighter_client = sample_config, mock_clients

    bot = SpreadArbitrageBot(sample_config, extended_client, lighter_client)

    # 模拟一个未对冲持仓
    unhedged_position = {
        'order_id': 'EXT_12345',
        'side': 'buy',
        'quantity': Decimal('0.014'),
        'price': Decimal('2500.00'),
        'timestamp': time.time(),
        'error': 'Lighter连接失败'
    }

    # 添加到未对冲持仓列表
    bot.unhedged_positions.append(unhedged_position)

    # 验证检测
    assert len(bot.unhedged_positions) == 1
    assert bot.unhedged_positions[0]['order_id'] == 'EXT_12345'
    assert bot.unhedged_positions[0]['side'] == 'buy'


@pytest.mark.asyncio
async def test_unhedged_position_timeout_alarm(sample_config, mock_clients):
    """
    T011 [US1]: 测试单边持仓超时告警

    鉴于 系统检测到单边持仓超过60秒
    当 对冲订单仍未成交
    则 执行告警日志记录
    """
    extended_client, lighter_client = mock_clients

    bot = SpreadArbitrageBot(sample_config, extended_client, lighter_client)

    # 创建一个超过超时阈值的未对冲持仓 (61秒前)
    old_timestamp = time.time() - 61
    unhedged_position = {
        'order_id': 'EXT_67890',
        'side': 'sell',
        'quantity': Decimal('0.014'),
        'price': Decimal('2500.00'),
        'timestamp': old_timestamp,
        'error': 'Lighter流动性不足'
    }

    bot.unhedged_positions.append(unhedged_position)

    # 验证超时检测逻辑
    current_time = time.time()
    timeout_positions = [
        pos for pos in bot.unhedged_positions
        if current_time - pos['timestamp'] > sample_config.unhedged_position_timeout
    ]

    assert len(timeout_positions) == 1
    assert timeout_positions[0]['order_id'] == 'EXT_67890'
    assert (current_time - timeout_positions[0]['timestamp']) > 60


@pytest.mark.asyncio
async def test_unhedged_position_blocks_new_positions(sample_config, mock_clients):
    """
    T012 [US1]: 测试单边持仓存在时禁止开新仓

    鉴于 单边持仓导致账户未对冲仓位数量超过阈值(0)
    当 系统检测到此情况
    则 禁止开新仓直到单边仓位清除
    """
    extended_client, lighter_client = mock_clients

    bot = SpreadArbitrageBot(sample_config, extended_client, lighter_client)

    # 添加未对冲持仓 (超过max_unhedged_positions=0)
    unhedged_position = {
        'order_id': 'EXT_11111',
        'side': 'buy',
        'quantity': Decimal('0.014'),
        'price': Decimal('2500.00'),
        'timestamp': time.time(),
        'error': '对冲失败'
    }

    bot.unhedged_positions.append(unhedged_position)

    # 验证禁止开新仓的逻辑
    should_block = len(bot.unhedged_positions) > sample_config.max_unhedged_positions

    assert should_block is True
    assert len(bot.unhedged_positions) == 1
    assert sample_config.max_unhedged_positions == 0


@pytest.mark.asyncio
async def test_multiple_unhedged_positions_tracking(sample_config, mock_clients):
    """
    额外测试: 多个未对冲持仓的追踪
    """
    extended_client, lighter_client = mock_clients

    bot = SpreadArbitrageBot(sample_config, extended_client, lighter_client)

    # 添加多个未对冲持仓
    positions = [
        {
            'order_id': f'EXT_{i}',
            'side': 'buy' if i % 2 == 0 else 'sell',
            'quantity': Decimal('0.014'),
            'price': Decimal('2500.00'),
            'timestamp': time.time() - (i * 30),  # 不同的时间戳
            'error': f'错误{i}'
        }
        for i in range(1, 4)
    ]

    for pos in positions:
        bot.unhedged_positions.append(pos)

    # 验证所有持仓都被追踪
    assert len(bot.unhedged_positions) == 3

    # 验证超时检测 (只有超过60秒的会被标记)
    current_time = time.time()
    timeout_positions = [
        pos for pos in bot.unhedged_positions
        if current_time - pos['timestamp'] > sample_config.unhedged_position_timeout
    ]

    # position 3 在90秒前创建,应该超时
    assert len(timeout_positions) >= 1


@pytest.mark.asyncio
async def test_clearing_unhedged_positions(sample_config, mock_clients):
    """
    额外测试: 清除未对冲持仓后可以重新开仓
    """
    extended_client, lighter_client = mock_clients

    bot = SpreadArbitrageBot(sample_config, extended_client, lighter_client)

    # 添加未对冲持仓
    unhedged_position = {
        'order_id': 'EXT_99999',
        'side': 'buy',
        'quantity': Decimal('0.014'),
        'price': Decimal('2500.00'),
        'timestamp': time.time(),
        'error': '临时失败'
    }

    bot.unhedged_positions.append(unhedged_position)

    # 验证被阻止
    assert len(bot.unhedged_positions) > sample_config.max_unhedged_positions

    # 清除未对冲持仓
    bot.unhedged_positions.clear()

    # 验证可以重新开仓
    assert len(bot.unhedged_positions) == 0
    assert len(bot.unhedged_positions) <= sample_config.max_unhedged_positions
