"""
安全监控模块测试

测试SafetyMonitor的功能：
- 对冲失败率追踪
- 仓位失衡率计算
- 熔断器触发逻辑
"""

import asyncio
import logging
from decimal import Decimal

import pytest

from spread.config import SpreadArbConfig
from spread.safety_monitor import SafetyMonitor, CircuitBreakerError


@pytest.fixture
def safety_monitor():
    """创建SafetyMonitor测试实例"""
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    return SafetyMonitor(config, logger)


class TestSafetyMonitor:
    """测试SafetyMonitor核心功能"""

    @pytest.mark.asyncio
    async def test_record_hedge_attempt_success(self, safety_monitor):
        """测试记录成功的对冲尝试"""
        initial_attempts = safety_monitor.state.total_hedge_attempts

        await safety_monitor.record_hedge_attempt(success=True)

        assert safety_monitor.state.total_hedge_attempts == initial_attempts + 1
        assert safety_monitor.state.total_hedge_failures == 0
        assert safety_monitor.get_hedge_failure_rate() == Decimal('0')

    @pytest.mark.asyncio
    async def test_record_hedge_attempt_failure(self, safety_monitor):
        """测试记录失败的对冲尝试"""
        await safety_monitor.record_hedge_attempt(success=False, failure_reason="liquidity_insufficient")

        assert safety_monitor.state.total_hedge_attempts == 1
        assert safety_monitor.state.total_hedge_failures == 1
        assert safety_monitor.get_hedge_failure_rate() == Decimal('1')

    @pytest.mark.asyncio
    async def test_hedge_failure_rate_calculation(self, safety_monitor):
        """测试对冲失败率计算"""
        # 记录7次成功，3次失败
        for _ in range(7):
            await safety_monitor.record_hedge_attempt(success=True)
        for _ in range(3):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        assert safety_monitor.state.total_hedge_attempts == 10
        assert safety_monitor.get_hedge_failure_rate() == Decimal('0.3')

    @pytest.mark.asyncio
    async def test_sliding_window(self, safety_monitor):
        """测试滑动窗口机制"""
        # 设置窗口大小为10
        assert safety_monitor.config.hedge_failure_window == 10

        # 记录15次（5次成功，10次失败）
        for _ in range(5):
            await safety_monitor.record_hedge_attempt(success=True)
        for _ in range(10):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        # 窗口应该只保留最近10次（都是失败）
        assert safety_monitor.get_hedge_failure_rate() == Decimal('1')

        # 再记录10次成功
        for _ in range(10):
            await safety_monitor.record_hedge_attempt(success=True)

        # 窗口应该包含最近10次（都是成功）
        assert safety_monitor.get_hedge_failure_rate() == Decimal('0')

    def test_circuit_breaker_trigger(self, safety_monitor):
        """测试熔断器触发（同步方法）"""
        # 熔断器检查是同步的，不需要await
        level, reason = safety_monitor.check_circuit_breaker()
        assert level == 0  # 初始状态应该正常

    @pytest.mark.asyncio
    async def test_circuit_breaker_levels(self, safety_monitor):
        """测试熔断器不同级别"""
        # 级别0: 正常
        level, reason = safety_monitor.check_circuit_breaker()
        assert level == 0

        # 级别1: 警告（失败率>20%）- 需要5次成功，2次失败 = 28.6%
        for _ in range(5):
            await safety_monitor.record_hedge_attempt(success=True)
        for _ in range(2):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        level, reason = safety_monitor.check_circuit_breaker()
        assert level == 1
        assert "警告" in reason

        # 级别2: 禁止开仓（失败率>30%）- 再增加1次失败 = 37.5%
        await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        level, reason = safety_monitor.check_circuit_breaker()
        assert level >= 2

        # 级别3: 完全暂停（失败率>50%）- 再增加3次失败 = 55.6%
        for _ in range(3):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        level, reason = safety_monitor.check_circuit_breaker()
        assert level == 3
        assert "严重" in reason

    @pytest.mark.asyncio
    async def test_should_pause_opening(self, safety_monitor):
        """测试开仓暂停判断"""
        # 初始状态不应该暂停
        assert not safety_monitor.should_pause_opening()

        # 触发级别2熔断（需要4次成功，2次失败 = 33.3%）
        for _ in range(4):
            await safety_monitor.record_hedge_attempt(success=True)
        for _ in range(2):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        assert safety_monitor.should_pause_opening()

    @pytest.mark.asyncio
    async def test_should_force_close(self, safety_monitor):
        """测试强制平仓判断"""
        # 初始状态不应该强制平仓
        assert not safety_monitor.should_force_close()

        # 触发级别3熔断（需要4次成功，5次失败 = 55.6%）
        for _ in range(4):
            await safety_monitor.record_hedge_attempt(success=True)
        for _ in range(5):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        assert safety_monitor.should_force_close()

    def test_position_imbalance_calculation(self, safety_monitor):
        """测试仓位失衡率计算"""
        # Extended 0.21, Lighter 0.02
        safety_monitor.update_position_imbalance(
            extended_qty=Decimal('0.21'),
            lighter_qty=Decimal('0.02')
        )

        imbalance_rate = safety_monitor.get_position_imbalance_rate()
        # 失衡率应该约为82.6%
        assert imbalance_rate > Decimal('0.8')
        assert imbalance_rate < Decimal('0.9')

    def test_position_imbalance_with_negative(self, safety_monitor):
        """测试负数仓位的失衡率计算"""
        # Extended空头-0.10，Lighter多头0.08（部分对冲）
        safety_monitor.update_position_imbalance(
            extended_qty=Decimal('-0.10'),
            lighter_qty=Decimal('0.08')
        )

        # 总暴露度: 0.18, 差异: 0.02, 失衡率: 11.1%
        imbalance_rate = safety_monitor.get_position_imbalance_rate()
        assert imbalance_rate > Decimal('0.1')
        assert imbalance_rate < Decimal('0.2')

    @pytest.mark.asyncio
    async def test_circuit_breaker_reset(self, safety_monitor):
        """测试熔断器重置"""
        # 触发熔断（4次成功，5次失败 = 55.6%，触发级别3）
        for _ in range(4):
            await safety_monitor.record_hedge_attempt(success=True)
        for _ in range(5):
            await safety_monitor.record_hedge_attempt(success=False, failure_reason="test")

        assert safety_monitor.state.circuit_breaker_level >= 2

        # 重置熔断器
        safety_monitor.reset_circuit_breaker()

        assert safety_monitor.state.circuit_breaker_level == 0
        assert not safety_monitor.state.is_paused
        assert safety_monitor.state.pause_reason == ""
        # 注意：重置后失败率仍然很高，should_pause_opening可能仍然返回True
        # 这是正确的行为：用户需要清除问题后失败率才会下降

    def test_get_safety_state(self, safety_monitor):
        """测试获取安全状态快照"""
        state = safety_monitor.get_safety_state()

        assert state is not None
        assert hasattr(state, 'is_paused')
        assert hasattr(state, 'hedge_failure_rate')
        assert hasattr(state, 'position_imbalance_rate')
        assert hasattr(state, 'circuit_breaker_level')

    @pytest.mark.asyncio
    async def test_validation_error_on_success_with_reason(self, safety_monitor):
        """测试成功时提供失败原因应该抛出异常"""
        with pytest.raises(ValueError, match="成功时不应提供failure_reason"):
            await safety_monitor.record_hedge_attempt(
                success=True,
                failure_reason="不应该有这个参数"
            )
