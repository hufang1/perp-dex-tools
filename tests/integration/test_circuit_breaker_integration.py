"""
熔断机制集成测试

测试SafetyMonitor与Bot的集成
"""

import asyncio
import logging
from decimal import Decimal

import pytest

from spread.config import SpreadArbConfig
from spread.safety_monitor import SafetyMonitor


@pytest.mark.asyncio
async def test_hedge_failure_triggers_pause():
    """测试对冲失败触发暂停"""
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    monitor = SafetyMonitor(config, logger)

    # 记录足够的失败以触发级别2（4次成功，2次失败 = 33.3%）
    for _ in range(4):
        await monitor.record_hedge_attempt(success=True)
    for _ in range(2):
        await monitor.record_hedge_attempt(success=False, failure_reason="test")

    # 应该触发级别2熔断
    level, reason = monitor.check_circuit_breaker()
    assert level >= 2
    assert monitor.should_pause_opening()


@pytest.mark.asyncio
async def test_position_imbalance_triggers_force_close():
    """测试仓位失衡触发强制平仓"""
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    monitor = SafetyMonitor(config, logger)

    # 设置严重的仓位失衡
    monitor.update_position_imbalance(
        extended_qty=Decimal('0.21'),
        lighter_qty=Decimal('0.02')
    )

    # 失衡率>50%应该触发级别3熔断
    level, reason = monitor.check_circuit_breaker()
    assert level == 3
    assert monitor.should_force_close()


@pytest.mark.asyncio
async def test_circuit_breaker_recovery():
    """测试熔断器恢复流程"""
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    monitor = SafetyMonitor(config, logger)

    # 触发熔断（4次成功，5次失败 = 55.6%）
    for _ in range(4):
        await monitor.record_hedge_attempt(success=True)
    for _ in range(5):
        await monitor.record_hedge_attempt(success=False, failure_reason="test")

    assert monitor.state.circuit_breaker_level >= 2

    # 重置熔断器
    monitor.reset_circuit_breaker()

    # 验证状态已重置
    assert monitor.state.circuit_breaker_level == 0
    assert not monitor.state.is_paused
    # 注意：失败率仍然很高，should_pause_opening可能仍返回True


@pytest.mark.asyncio
async def test_safety_monitor_state_persistence():
    """测试安全监控器状态持久化"""
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    monitor = SafetyMonitor(config, logger)

    # 记录一些对冲尝试
    for _ in range(5):
        await monitor.record_hedge_attempt(success=True)
    for _ in range(2):
        await monitor.record_hedge_attempt(success=False, failure_reason="test")

    # 获取状态快照
    state = monitor.get_safety_state()

    assert state.total_hedge_attempts == 7
    assert state.total_hedge_failures == 2
    assert state.hedge_failure_rate == Decimal('2') / Decimal('7')


@pytest.mark.asyncio
async def test_gradual_failure_rate_increase():
    """测试失败率逐渐增加时的熔断器行为"""
    config = SpreadArbConfig()
    logger = logging.getLogger("test")
    monitor = SafetyMonitor(config, logger)

    # 初始状态
    assert monitor.check_circuit_breaker()[0] == 0

    # 逐渐增加失败率
    # 10%失败率（9次成功，1次失败）- 应该仍然正常
    for _ in range(9):
        await monitor.record_hedge_attempt(success=True)
    await monitor.record_hedge_attempt(success=False, failure_reason="test")
    assert monitor.check_circuit_breaker()[0] == 0

    # 30%失败率（再增加2次失败）- 30%刚好触发级别1警告
    for _ in range(2):
        await monitor.record_hedge_attempt(success=False, failure_reason="test")
    assert monitor.check_circuit_breaker()[0] == 1  # 警告级别

    # 40%失败率（再增加1次失败）- 应该触发级别2（禁止开仓）
    await monitor.record_hedge_attempt(success=False, failure_reason="test")
    assert monitor.check_circuit_breaker()[0] >= 2
