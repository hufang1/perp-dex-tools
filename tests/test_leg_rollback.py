"""
单腿回滚测试

测试012-dual-leg-concurrency的单腿回滚功能
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from spread.models import ConcurrentOrderResult, LegRollbackEvent


@pytest.fixture
def config():
    """创建测试配置"""
    from spread.config import SpreadArbConfig
    return SpreadArbConfig(
        enable_leg_rollback=True,
        rollback_timeout_ms=500.0,
        rollback_max_retries=3,
        ticker='ETH'
    )


@pytest.fixture
def mock_extended_client():
    """模拟Extended客户端"""
    from exchanges.base import OrderResult
    client = MagicMock()
    client.contract_id = 'ETH-PERP'
    client.config = MagicMock()
    client.config.contract_id = 'ETH-PERP'
    # Mock place_close_order (用于紧急平仓)
    client.place_close_order = AsyncMock(return_value=OrderResult(
        success=True,
        order_id='ext_rollback_123',
        side='sell',
        size=Decimal('0.01'),
        price=Decimal('3000.0'),
        status='FILLED',
        filled_size=Decimal('0.01')
    ))
    return client


@pytest.fixture
def mock_lighter_client():
    """模拟Lighter客户端"""
    from exchanges.base import OrderResult
    client = MagicMock()
    client.contract_id = '0'
    client.config = MagicMock()
    client.config.contract_id = '0'
    # Mock place_close_order (用于紧急平仓)
    client.place_close_order = AsyncMock(return_value=OrderResult(
        success=True,
        order_id='lit_rollback_456',
        side='buy',
        size=Decimal('0.01'),
        price=Decimal('2998.0'),
        status='FILLED',
        filled_size=Decimal('0.01')
    ))
    return client


@pytest.fixture
def leg_rollback_handler(config, mock_extended_client, mock_lighter_client):
    """创建测试用的单腿回滚处理器"""
    from spread.leg_rollback_handler import LegRollbackHandler
    from spread.performance_monitor import PerformanceMonitor

    monitor = PerformanceMonitor(config)

    return LegRollbackHandler(
        config=config,
        monitor=monitor,
        extended_client=mock_extended_client,
        lighter_client=mock_lighter_client
    )


# ========================================================================
# T035-T036: 单腿持仓检测测试
# ========================================================================

class TestDetectLegging:
    """测试单腿持仓检测（T035-T036）"""

    def test_detect_legging_extended_filled(self, leg_rollback_handler):
        """T035: 检测Extended单腿成交"""
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
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=False,
            is_legging=True,
            is_both_failed=False
        )

        is_legging = leg_rollback_handler.detect_legging(result)

        assert is_legging is True
        assert result.extended_success != result.lighter_success

    def test_detect_legging_lighter_filled(self, leg_rollback_handler):
        """T036: 检测Lighter单腿成交"""
        result = ConcurrentOrderResult(
            extended_success=False,
            extended_order_id=None,
            extended_filled_qty=Decimal('0'),
            extended_filled_price=None,
            extended_error='timeout',
            lighter_success=True,
            lighter_order_id='lit_456',
            lighter_filled_qty=Decimal('0.01'),
            lighter_filled_price=Decimal('3000.0'),
            lighter_error=None,
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=False,
            is_legging=True,
            is_both_failed=False
        )

        is_legging = leg_rollback_handler.detect_legging(result)

        assert is_legging is True
        assert result.extended_success != result.lighter_success

    def test_detect_no_legging_both_filled(self, leg_rollback_handler):
        """测试双腿成交 - 不触发回滚"""
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
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=True,
            is_legging=False,
            is_both_failed=False
        )

        is_legging = leg_rollback_handler.detect_legging(result)

        assert is_legging is False

    def test_detect_no_legging_both_failed(self, leg_rollback_handler):
        """测试双边失败 - 不触发回滚"""
        result = ConcurrentOrderResult(
            extended_success=False,
            extended_order_id=None,
            extended_filled_qty=Decimal('0'),
            extended_filled_price=None,
            extended_error='timeout',
            lighter_success=False,
            lighter_order_id=None,
            lighter_filled_qty=Decimal('0'),
            lighter_filled_price=None,
            lighter_error='timeout',
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=False,
            is_legging=False,
            is_both_failed=True
        )

        is_legging = leg_rollback_handler.detect_legging(result)

        assert is_legging is False


# ========================================================================
# T037-T039: 紧急平仓执行测试
# ========================================================================

class TestEmergencyClose:
    """测试紧急平仓执行（T037-T039）"""

    @pytest.mark.asyncio
    async def test_rollback_under_1s(self, leg_rollback_handler):
        """T037: 测试回滚在1秒内完成"""
        # Extended成交了，需要平仓
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
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=False,
            is_legging=True,
            is_both_failed=False
        )

        rollback_event = await leg_rollback_handler.execute_emergency_close(
            result=result,
            pair_id=1
        )

        # T037: 验证回滚延迟 < 1秒
        assert rollback_event.rollback_latency_ms < 1000
        # T044: 验证SLA检查
        assert rollback_event.is_within_sla() is True
        assert rollback_event.rollback_success is True

    @pytest.mark.asyncio
    async def test_rollback_retry_on_failure(self, leg_rollback_handler, mock_extended_client):
        """T038: 测试失败重试机制"""
        from exchanges.base import OrderResult
        # 模拟前两次失败，第三次成功
        call_count = 0

        async def failing_place_order(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return OrderResult(
                    success=False,
                    error_message='temporary_error'
                )
            return OrderResult(
                success=True,
                order_id='ext_rollback_123',
                side='sell',
                size=Decimal('0.01'),
                price=Decimal('3000.0'),
                status='FILLED',
                filled_size=Decimal('0.01')
            )

        mock_extended_client.place_close_order = AsyncMock(side_effect=failing_place_order)

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
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=False,
            is_legging=True,
            is_both_failed=False
        )

        rollback_event = await leg_rollback_handler.execute_emergency_close(
            result=result,
            pair_id=1
        )

        # T038: 验证重试后成功
        assert call_count == 3  # 重试了3次
        assert rollback_event.rollback_success is True

    @pytest.mark.asyncio
    async def test_rollback_logs_critical_marker(self, leg_rollback_handler, caplog):
        """T039: 测试记录关键日志标记"""
        import logging
        caplog.set_level(logging.ERROR)

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
            send_a_ts=1704960123465.23,
            send_b_ts=1704960123468.44,
            send_gap_ms=3.21,
            total_latency_ms=200.5,
            is_both_filled=False,
            is_legging=True,
            is_both_failed=False
        )

        await leg_rollback_handler.execute_emergency_close(
            result=result,
            pair_id=1
        )

        # T039: 验证关键日志标记存在
        assert '[CRITICAL] Legging detected, rolling back position' in caplog.text
