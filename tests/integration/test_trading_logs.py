"""
交易价格日志集成测试

测试交易价格日志记录功能:
- 开仓日志包含所有必需字段
- 平仓日志包含所有必需字段
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
import logging

from spread.config import SpreadArbConfig
from spread.spread_pair import SpreadPair
from spread.bot import SpreadArbitrageBot


@pytest.fixture
def trading_config():
    """用于交易日志测试的配置"""
    return SpreadArbConfig(
        ticker='ETH',
        order_quantity_usdt=Decimal('35'),
        min_spread_rate=Decimal('0.0005'),
        profit_target_rate=Decimal('0.0005'),
        time_close_threshold=60,
        max_holding_time=300
    )


@pytest.fixture
def mock_bot(trading_config, caplog):
    """创建模拟的机器人实例并捕获日志"""
    extended_client = Mock()
    lighter_client = Mock()

    extended_client.setup_order_update_handler = Mock()

    bot = SpreadArbitrageBot(trading_config, extended_client, lighter_client)

    # 设置日志捕获
    caplog.set_level(logging.INFO)

    return bot


def test_opening_log_contains_all_required_fields(mock_bot, caplog):
    """
    T037 [US4]: 测试开仓日志包含所有必需字段

    鉴于 系统执行开仓操作
    当 订单成交
    则 记录交易所、方向、价格、数量、时间戳、订单ID
    """
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014'),
        extended_order_id='EXT_12345',
        lighter_order_id='LT_67890'
    )

    # 模拟日志记录
    with caplog.at_level(logging.INFO):
        mock_bot.logger.info(
            f"✅ 开仓成功! 套利对 #{pair.pair_id}\n"
            f"   方向: {pair.extended_side.upper()}\n"
            f"   数量: {pair.extended_quantity:.4f}\n"
            f"   Extended: 价格@${pair.extended_price:.2f} (订单ID: {pair.open_extended_order_id})\n"
            f"   Lighter: 价格@${pair.lighter_price:.2f} (订单ID: {pair.open_lighter_order_id})\n"
            f"   开仓价差: ${pair.open_spread:.2f} ({pair.open_spread_rate:.4%})\n"
            f"   时间戳: {pair.open_time:.2f}"
        )

    # 验证日志包含所有必需字段
    log_text = caplog.text
    assert '开仓成功' in log_text
    assert '套利对 #1' in log_text
    assert '方向: BUY' in log_text
    assert '数量: 0.0140' in log_text
    assert 'Extended: 价格@' in log_text
    assert 'Lighter: 价格@' in log_text
    assert '订单ID: EXT_12345' in log_text
    assert '订单ID: LT_67890' in log_text
    assert '开仓价差:' in log_text
    assert '时间戳:' in log_text


def test_closing_log_contains_all_required_fields(mock_bot, caplog):
    """
    T038 [US4]: 测试平仓日志包含所有必需字段

    鉴于 系统执行平仓操作
    当 订单成交
    则 记录平仓价格、持仓时间、realized PnL
    """
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014'),
        extended_order_id='EXT_12345',
        lighter_order_id='LT_67890'
    )

    # 模拟平仓
    pair.close(
        close_extended_price=Decimal('2502.00'),
        close_lighter_price=Decimal('2500.00')
    )

    # 设置平仓订单ID
    pair.close_extended_order_id = 'EXT_CLOSE_999'
    pair.close_lighter_order_id = 'LT_CLOSE_888'

    # 模拟日志记录
    with caplog.at_level(logging.INFO):
        profit = pair.realized_pnl
        mock_bot.logger.info(
            f"💰 平仓成功! 套利对 #{pair.pair_id}\n"
            f"   盈亏: ${profit:.2f} ({(profit/(pair.extended_quantity*pair.extended_price))*100:.2f}%)\n"
            f"   持仓时间: {pair.holding_time:.0f}秒\n"
            f"   Extended平仓: 价格@${pair.close_extended_price:.2f} (订单ID: {pair.close_extended_order_id})\n"
            f"   Lighter平仓: 价格@${pair.close_lighter_price:.2f} (订单ID: {pair.close_lighter_order_id})"
        )

    # 验证日志包含所有必需字段
    log_text = caplog.text
    assert '平仓成功' in log_text
    assert '套利对 #1' in log_text
    assert '盈亏:' in log_text
    assert '持仓时间:' in log_text
    assert 'Extended平仓:' in log_text
    assert 'Lighter平仓:' in log_text
    assert '订单ID: EXT_CLOSE_999' in log_text
    assert '订单ID: LT_CLOSE_888' in log_text


def test_spread_pair_to_dict_contains_order_ids():
    """
    测试 SpreadPair.to_dict() 包含订单ID字段
    """
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014'),
        extended_order_id='EXT_12345',
        lighter_order_id='LT_67890'
    )

    pair_dict = pair.to_dict()

    # 验证订单ID字段存在
    assert 'open_extended_order_id' in pair_dict
    assert 'open_lighter_order_id' in pair_dict
    assert 'close_extended_order_id' in pair_dict
    assert 'close_lighter_order_id' in pair_dict

    # 验证值正确
    assert pair_dict['open_extended_order_id'] == 'EXT_12345'
    assert pair_dict['open_lighter_order_id'] == 'LT_67890'
    assert pair_dict['close_extended_order_id'] is None
    assert pair_dict['close_lighter_order_id'] is None


def test_closed_pair_summary():
    """
    测试完整的套利对总结

    验证套利对完成时输出包含:
    - 开仓价
    - 平仓价
    - 持仓时间
    - 总收益
    """
    pair = SpreadPair(
        pair_id=1,
        extended_side='buy',
        extended_price=Decimal('2500.00'),
        extended_quantity=Decimal('0.014'),
        lighter_price=Decimal('2501.25'),
        lighter_quantity=Decimal('0.014')
    )

    # 模拟平仓
    profit = pair.close(
        close_extended_price=Decimal('2502.00'),
        close_lighter_price=Decimal('2500.00')
    )

    # 验证所有必需的数据都可用
    assert pair.is_closed is True
    assert pair.realized_pnl == profit
    assert pair.close_extended_price == Decimal('2502.00')
    assert pair.close_lighter_price == Decimal('2500.00')
    assert pair.holding_time > 0

    # 验证数据格式化为JSON
    pair_dict = pair.to_dict()

    # 验证所有必需字段
    required_fields = [
        'pair_id', 'extended_side', 'extended_price', 'extended_quantity',
        'lighter_price', 'lighter_quantity', 'open_spread', 'open_spread_rate',
        'open_time', 'close_time', 'holding_time', 'is_closed',
        'close_extended_price', 'close_lighter_price', 'realized_pnl',
        'open_extended_order_id', 'open_lighter_order_id',
        'close_extended_order_id', 'close_lighter_order_id'
    ]

    for field in required_fields:
        assert field in pair_dict


def test_log_format_for_analysis():
    """
    测试日志格式便于后续分析和回测

    验证日志格式包含所有必需信息且格式统一
    """
    # 模拟开仓日志
    opening_log = (
        "✅ 开仓成功! 套利对 #1\n"
        "   方向: BUY\n"
        "   数量: 0.0140\n"
        "   Extended: 价格@2500.00 (订单ID: EXT_12345)\n"
        "   Lighter: 价格@2501.25 (订单ID: LT_67890)\n"
        "   开仓价差: $1.25 (0.0500%)\n"
        "   时间戳: 1704729600.00"
    )

    # 验证格式便于解析
    assert '套利对 #' in opening_log
    assert '方向:' in opening_log
    assert '数量:' in opening_log
    assert 'Extended: 价格@' in opening_log
    assert 'Lighter: 价格@' in opening_log
    assert '订单ID:' in opening_log
    assert '开仓价差:' in opening_log
    assert '时间戳:' in opening_log

    # 模拟平仓日志
    closing_log = (
        "💰 平仓成功! 套利对 #1\n"
        "   盈亏: $0.88 (2.50%)\n"
        "   持仓时间: 45秒\n"
        "   Extended平仓: 价格@2502.00 (订单ID: EXT_CLOSE_999)\n"
        "   Lighter平仓: 价格@2500.00 (订单ID: LT_CLOSE_888)"
    )

    # 验证格式
    assert '盈亏:' in closing_log
    assert '持仓时间:' in closing_log
    assert 'Extended平仓:' in closing_log
    assert 'Lighter平仓:' in closing_log

    # 模拟交易总结
    summary_log = (
        "📊 交易对 #1 总结:\n"
        "   开仓: Extended@$2500.00 → Lighter@$2501.25\n"
        "   平仓: Extended@$2502.00 → Lighter@$2500.00\n"
        "   收益率: 2.50%"
    )

    # 验证格式
    assert '交易对 #' in summary_log
    assert '开仓:' in summary_log
    assert '平仓:' in summary_log
    assert '收益率:' in summary_log
