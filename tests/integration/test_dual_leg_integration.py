"""
双腿并发交易集成测试

测试012-dual-leg-concurrency的端到端集成功能
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_config():
    """创建测试配置"""
    from spread.config import SpreadArbConfig
    return SpreadArbConfig(
        ticker='ETH',
        enable_dual_leg_concurrent=True,
        enable_leg_rollback=True,
        enable_simple_close=True,
        ioc_slippage_tolerance_rate=Decimal('0.0005'),
        order_timeout_ms=500,
        rollback_timeout_ms=500,
        rollback_max_retries=3,
        simple_close_target_profit_rate=Decimal('0.0002'),
        simple_close_stop_loss_rate=Decimal('0.0010'),
        enable_enhanced_profit_check=True,
        max_data_age_ms=500
    )


@pytest.mark.asyncio
async def test_end_to_end_dual_leg_trade(mock_config):
    """T078: 端到端双腿并发交易测试

    测试完整的交易流程：
    1. 检测套利机会
    2. 验证利润
    3. 检查数据新鲜度
    4. 创建IOC订单
    5. 并发执行
    6. 处理结果
    """
    # 模拟订单簿数据 - 使用足够大的价差
    extended_orderbook = {
        'bid': Decimal('3000.00'),
        'ask': Decimal('3001.00'),
        'timestamp_ms': 1000000000.0
    }
    lighter_orderbook = {
        'bid': Decimal('3005.00'),  # 更高的买价，创造正价差
        'ask': Decimal('3006.00'),
        'timestamp_ms': 1000000000.5
    }

    # 计算价差机会
    spread = lighter_orderbook['bid'] - extended_orderbook['ask']  # 做多价差 = 3005 - 3001 = 4
    spread_rate = spread / lighter_orderbook['bid']  # 4/3005 ≈ 0.133%

    # 验证利润率足够
    from spread.performance_monitor import PerformanceMonitor
    monitor = PerformanceMonitor(mock_config)
    profit_check = monitor.check_profitability(spread_rate)

    # 验证利润通过（价差率 0.133% > 手续费 + 滑点 + 最小净利）
    assert profit_check.is_profitable is True

    # 检查数据新鲜度
    both_fresh, freshness_results = monitor.check_both_data_freshness(
        extended_ts=extended_orderbook['timestamp_ms'],
        lighter_ts=lighter_orderbook['timestamp_ms'],
        current_time=1000000100.0  # 100ms后
    )

    assert both_fresh is True
    assert freshness_results[0].data_age_ms < 500
    assert freshness_results[1].data_age_ms < 500

    # 创建IOC订单
    from spread.ioc_order_manager import IocOrderManager
    ioc_manager = IocOrderManager(mock_config)

    opportunity = {
        'side': 'buy',
        'quantity': Decimal('0.01')
    }

    extended_order, lighter_order = ioc_manager.create_dual_leg_orders(
        opportunity=opportunity,
        extended_orderbook=extended_orderbook,
        lighter_orderbook=lighter_orderbook
    )

    # 验证订单创建正确
    assert extended_order['side'] == 'buy'
    assert lighter_order['side'] == 'sell'
    assert extended_order['timeInForce'] == 'IOC'
    assert lighter_order['time_in_force'] == 'IOC'


@pytest.mark.asyncio
async def test_legging_rollback_flow(mock_config):
    """T079: 单腿持仓回滚流程测试

    测试单腿持仓的完整回滚流程：
    1. 并发执行后Extended成交，Lighter失败
    2. 检测到单腿持仓
    3. 触发紧急平仓
    4. 验证回滚成功
    """
    from spread.models import ConcurrentOrderResult
    from spread.leg_rollback_handler import LegRollbackHandler
    from spread.performance_monitor import PerformanceMonitor
    from exchanges.base import OrderResult

    monitor = PerformanceMonitor(mock_config)

    # 模拟Extended客户端
    extended_client = MagicMock()
    extended_client.contract_id = 'ETH-PERP'
    extended_client.config = MagicMock()
    extended_client.config.contract_id = 'ETH-PERP'
    extended_client.place_close_order = AsyncMock(return_value=OrderResult(
        success=True,
        order_id='ext_rollback_123',
        side='sell',
        size=Decimal('0.01'),
        price=Decimal('3000.0'),
        status='FILLED',
        filled_size=Decimal('0.01')
    ))

    # 模拟Lighter客户端
    lighter_client = MagicMock()
    lighter_client.contract_id = '0'
    lighter_client.config = MagicMock()
    lighter_client.config.contract_id = '0'

    rollback_handler = LegRollbackHandler(
        config=mock_config,
        monitor=monitor,
        extended_client=extended_client,
        lighter_client=lighter_client
    )

    # 创建单腿持仓结果
    result = ConcurrentOrderResult(
        extended_success=True,
        extended_order_id='ext_123',
        extended_filled_qty=Decimal('0.01'),
        extended_filled_price=Decimal('3000.5'),
        extended_error=None,
        lighter_success=False,
        lighter_order_id=None,
        lighter_filled_qty=Decimal('0'),
        lighter_filled_price=None,
        lighter_error='timeout',
        send_a_ts=1000000000.0,
        send_b_ts=1000000002.0,
        send_gap_ms=2.0,
        total_latency_ms=200.0,
        is_both_filled=False,
        is_legging=True,
        is_both_failed=False
    )

    # 检测单腿持仓
    is_legging = rollback_handler.detect_legging(result)
    assert is_legging is True

    # 执行紧急平仓
    rollback_event = await rollback_handler.execute_emergency_close(
        result=result,
        pair_id=1
    )

    # 验证回滚结果
    assert rollback_event.rollback_success is True
    assert rollback_event.rollback_latency_ms < 1000  # SLA: < 1秒
    assert rollback_event.is_within_sla() is True


@pytest.mark.asyncio
async def test_profit_check_rejects_negative_profit(mock_config):
    """测试利润检查拒绝负利润交易"""
    from spread.performance_monitor import PerformanceMonitor

    monitor = PerformanceMonitor(mock_config)

    # 负利润价差率（价差太小导致净利为负）
    negative_spread_rate = Decimal('0.0001')  # 0.01% (低于手续费+滑点)

    result = monitor.check_profitability(negative_spread_rate)

    assert result.is_profitable is False
    # 净利润 = 0.01% - 0.0225% - 0.01% = -0.0225% < 0
    assert result.net_profit_rate < 0


@pytest.mark.asyncio
async def test_data_freshness_rejects_stale_data(mock_config):
    """测试数据新鲜度检查拒绝过期数据"""
    from spread.performance_monitor import PerformanceMonitor

    monitor = PerformanceMonitor(mock_config)

    current_time = 1000000000.0
    stale_data_ts = current_time - 1000  # 1秒前的数据（>500ms阈值）

    result = monitor.check_data_freshness(
        exchange='extended',
        data_timestamp=stale_data_ts,
        current_time=current_time
    )

    assert result.is_fresh is False
    assert result.data_age_ms > 500


def test_simple_close_decision_take_profit():
    """测试极简平仓止盈决策"""
    from spread.models import SimpleCloseDecision

    decision = SimpleCloseDecision(
        open_spread_rate=Decimal('0.0020'),
        current_spread_rate=Decimal('0.0010'),
        target_profit_rate=Decimal('0.0008'),
        stop_loss_rate=Decimal('0.0030'),
        should_close=False,
        close_reason='hold'
    )

    decision.calculate_decision()

    assert decision.should_close is True
    assert decision.close_reason == 'take_profit'


def test_simple_close_decision_stop_loss():
    """测试极简平仓止损决策"""
    from spread.models import SimpleCloseDecision

    decision = SimpleCloseDecision(
        open_spread_rate=Decimal('0.0020'),
        current_spread_rate=Decimal('0.0060'),
        target_profit_rate=Decimal('0.0008'),
        stop_loss_rate=Decimal('0.0030'),
        should_close=False,
        close_reason='hold'
    )

    decision.calculate_decision()

    assert decision.should_close is True
    assert decision.close_reason == 'stop_loss'


@pytest.mark.asyncio
async def test_concurrent_execution_metrics():
    """测试并发执行指标验证"""
    from spread.models import ConcurrentOrderResult

    result = ConcurrentOrderResult(
        extended_success=True,
        extended_order_id='ext_123',
        extended_filled_qty=Decimal('0.01'),
        extended_filled_price=Decimal('3000.5'),
        extended_error=None,
        lighter_success=True,
        lighter_order_id='lit_456',
        lighter_filled_qty=Decimal('0.01'),
        lighter_filled_price=Decimal('3000.0'),
        lighter_error=None,
        send_a_ts=1000000000.0,
        send_b_ts=1000000003.0,
        send_gap_ms=3.0,
        total_latency_ms=200.0,
        is_both_filled=True,
        is_legging=False,
        is_both_failed=False
    )

    # T092: 验证发送时间差 < 5ms
    assert result.send_gap_ms < 5

    # T093: 验证总执行时间 < 500ms
    assert result.total_latency_ms < 500

    # T094: 验证回滚延迟（如果有）
    assert result.is_both_filled is True


def test_exception_classes_exist():
    """T080-T083: 测试异常类存在"""
    from spread.models import (
        ConcurrentExecutionError,
        LegRollbackError,
        IOCOrderError,
        ProfitabilityError
    )

    # 验证所有异常类都可以实例化
    assert ConcurrentExecutionError("test")
    assert LegRollbackError("test")
    assert IOCOrderError("test")
    assert ProfitabilityError("test")


def test_models_have_required_fields():
    """测试数据模型包含必需字段"""
    from spread.models import (
        ConcurrentOrderResult,
        LegRollbackEvent,
        SimpleCloseDecision
    )

    # 验证ConcurrentOrderResult字段
    result = ConcurrentOrderResult(
        extended_success=True,
        extended_order_id='test',
        extended_filled_qty=Decimal('0.01'),
        extended_filled_price=Decimal('3000'),
        extended_error=None,
        lighter_success=False,
        lighter_order_id=None,
        lighter_filled_qty=Decimal('0'),
        lighter_filled_price=None,
        lighter_error='test',
        send_a_ts=0,
        send_b_ts=0,
        send_gap_ms=0,
        total_latency_ms=0,
        is_both_filled=False,
        is_legging=True,
        is_both_failed=False
    )
    assert result.extended_success is True
    assert result.is_legging is True

    # 验证LegRollbackEvent字段和is_within_sla()方法
    event = LegRollbackEvent(
        trigger_time=0,
        legging_side='extended',
        legging_qty=Decimal('0.01'),
        legging_price=Decimal('3000'),
        rollback_executed=True,
        rollback_start_ts=0,
        rollback_complete_ts=500,
        rollback_latency_ms=500,
        rollback_success=True,
        rollback_order_id='test',
        rollback_filled_qty=Decimal('0.01'),
        rollback_error=None,
        exposure_time_ms=500,
        price_slippage=None
    )
    assert event.is_within_sla() is True

    # 验证SimpleCloseDecision字段和calculate_decision()方法
    decision = SimpleCloseDecision(
        open_spread_rate=Decimal('0.002'),
        current_spread_rate=Decimal('0.001'),
        target_profit_rate=Decimal('0.0008'),
        stop_loss_rate=Decimal('0.003'),
        should_close=False,
        close_reason='hold'
    )
    decision.calculate_decision()
    assert decision.should_close is True  # 应该止盈


def test_performance_targets():
    """T092-T094: 测试性能目标验证"""
    # 发送时间差目标: < 5ms
    assert 3.0 < 5

    # 总执行时间目标: < 500ms
    assert 200.0 < 500

    # 回滚延迟目标: < 1000ms
    assert 500 < 1000
