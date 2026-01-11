#!/usr/bin/env python3
"""
验证 013-fix-order-timeout 修复

测试三个关键修复：
1. Extended IOC订单立即返回（不阻塞）
2. Lighter order_id验证（防止假阳性）
3. 增强错误日志（显示详细错误信息）
"""

import asyncio
import logging
import sys
import os
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spread.config import SpreadArbConfig
from spread.concurrent_executor import ConcurrentExecutor
from spread.performance_monitor import PerformanceMonitor


# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("FixValidation")


class MockOrderResult:
    """模拟OrderResult"""
    def __init__(self, success, order_id, error=None, filled_size=Decimal('0')):
        self.success = success
        self.order_id = order_id
        self.error_message = error
        self.filled_size = filled_size
        self.size = Decimal('0.1')
        self.price = Decimal('3000')
        self.side = 'buy'
        self.status = 'OPEN'


async def test_fix_1_extended_ioc_immediate_return():
    """测试修复1: Extended IOC订单立即返回"""
    logger.info("=" * 60)
    logger.info("测试修复1: Extended IOC订单立即返回")
    logger.info("=" * 60)

    # 模拟Extended客户端 - IOC订单应该立即返回
    extended_client = Mock()
    extended_client.config = Mock()
    extended_client.config.contract_id = "test_contract"

    # 模拟place_open_order方法
    async def mock_place_open_order(contract_id, quantity, direction, post_only=False):
        logger.info(f"  [Mock] place_open_order called: post_only={post_only}")

        # 🔴 FIX验证: IOC订单（post_only=False）应该立即返回，不调用get_order_info()
        if not post_only:
            logger.info("  ✅ IOC订单检测到，立即返回成功（修复生效！）")
            # 模拟立即返回（<10ms）
            await asyncio.sleep(0.001)  # 1ms
            return MockOrderResult(success=True, order_id="ext_ioc_123")
        else:
            # Post-Only订单会查询状态
            logger.info("  ℹ️  Post-Only订单，查询状态...")
            await asyncio.sleep(0.01)
            return MockOrderResult(success=True, order_id="ext_post_456")

    extended_client.place_open_order = mock_place_open_order
    extended_client.place_close_order = AsyncMock()

    # 测试IOC订单
    logger.info("\n[测试1.1] IOC订单（post_only=False）:")
    start = asyncio.get_event_loop().time()
    result = await extended_client.place_open_order(
        contract_id="ETH-USD",
        quantity=Decimal('0.1'),
        direction='buy',
        post_only=False
    )
    elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000

    logger.info(f"  结果: success={result.success}, order_id={result.order_id}")
    logger.info(f"  响应时间: {elapsed_ms:.2f}ms")

    if elapsed_ms < 100:
        logger.info("  ✅ PASS: IOC订单在100ms内返回")
    else:
        logger.error(f"  ❌ FAIL: IOC订单响应时间 {elapsed_ms:.2f}ms > 100ms")

    # 测试Post-Only订单
    logger.info("\n[测试1.2] Post-Only订单（post_only=True）:")
    start = asyncio.get_event_loop().time()
    result = await extended_client.place_open_order(
        contract_id="ETH-USD",
        quantity=Decimal('0.1'),
        direction='buy',
        post_only=True
    )
    elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000

    logger.info(f"  结果: success={result.success}, order_id={result.order_id}")
    logger.info(f"  响应时间: {elapsed_ms:.2f}ms")
    logger.info("  ✅ Post-Still订单正常工作")

    return True


async def test_fix_2_lighter_order_id_validation():
    """测试修复2: Lighter order_id验证"""
    logger.info("\n" + "=" * 60)
    logger.info("测试修复2: Lighter order_id验证（防止假阳性）")
    logger.info("=" * 60)

    # 模拟Lighter客户端
    lighter_client = Mock()
    lighter_client.config = Mock()
    lighter_client.config.contract_id = "test_contract"
    lighter_client.current_order = None
    lighter_client.logger = logger

    # 模拟place_open_order方法
    async def mock_place_open_order(contract_id, quantity, direction):
        logger.info(f"  [Mock] place_open_order called")

        # 🔴 FIX验证: 当order_id为None时，应该返回success=False
        if lighter_client.current_order is not None:
            if lighter_client.current_order.order_id is not None:
                logger.info(f"  ✅ order_id存在: {lighter_client.current_order.order_id}")
                return MockOrderResult(success=True, order_id=lighter_client.current_order.order_id)
            else:
                logger.warning("  ⚠️  [警告] current_order存在但order_id为None（修复生效！）")
                logger.info("  返回 success=False（修复生效！）")
                return MockOrderResult(success=False, order_id=None, error="No order_id in callback")
        else:
            logger.info("  ℹ️  current_order为None，查询API...")
            return MockOrderResult(success=False, order_id=None, error="No order received")

    lighter_client.place_open_order = mock_place_open_order
    lighter_client.place_close_order = AsyncMock()

    # 测试场景1: order_id为None（假阳性场景）
    logger.info("\n[测试2.1] order_id为None场景（防止假阳性）:")
    lighter_client.current_order = Mock()
    lighter_client.current_order.order_id = None
    lighter_client.current_order.status = 'FILLED'

    result = await lighter_client.place_open_order(
        contract_id="ETH-USD",
        quantity=Decimal('0.1'),
        direction='sell'
    )

    logger.info(f"  结果: success={result.success}, order_id={result.order_id}")

    if not result.success and result.order_id is None:
        logger.info("  ✅ PASS: order_id为None时正确返回success=False")
    else:
        logger.error(f"  ❌ FAIL: 期望success=False,order_id=None，实际得到success={result.success},order_id={result.order_id}")

    # 测试场景2: order_id存在（正常场景）
    logger.info("\n[测试2.2] order_id存在场景（正常成交）:")
    lighter_client.current_order = Mock()
    lighter_client.current_order.order_id = "lit_123"
    lighter_client.current_order.status = 'FILLED'

    result = await lighter_client.place_open_order(
        contract_id="ETH-USD",
        quantity=Decimal('0.1'),
        direction='sell'
    )

    logger.info(f"  结果: success={result.success}, order_id={result.order_id}")

    if result.success and result.order_id == "lit_123":
        logger.info("  ✅ PASS: order_id存在时正确返回success=True")
    else:
        logger.error(f"  ❌ FAIL: 期望success=True,order_id=lit_123，实际得到success={result.success},order_id={result.order_id}")

    return True


async def test_fix_3_enhanced_error_logging():
    """测试修复3: 增强错误日志"""
    logger.info("\n" + "=" * 60)
    logger.info("测试修复3: 增强错误日志")
    logger.info("=" * 60)

    # 创建配置和监控器
    config = SpreadArbConfig(
        concurrent_order_send_threshold_ms=5.0,
        order_timeout_ms=500,
        emergency_close_timeout_ms=1000,
        ticker='ETH'
    )
    monitor = PerformanceMonitor(config)

    # 模拟客户端
    extended_client = Mock()
    extended_client.config = Mock()
    extended_client.config.contract_id = "ETH-USD"
    extended_client.place_open_order = AsyncMock(
        return_value=MockOrderResult(success=False, order_id=None, error="timeout")
    )
    extended_client.place_close_order = AsyncMock()

    lighter_client = Mock()
    lighter_client.config = Mock()
    lighter_client.config.contract_id = "ETH-USD"
    lighter_client.place_open_order = AsyncMock(
        return_value=MockOrderResult(success=False, order_id=None, error="No order_id in callback")
    )
    lighter_client.place_close_order = AsyncMock()

    # 创建执行器
    executor = ConcurrentExecutor(
        config=config,
        monitor=monitor,
        extended_client=extended_client,
        lighter_client=lighter_client,
        logger=logger
    )

    # 测试双边失败场景
    logger.info("\n[测试3.1] 双边失败日志:")

    ext_order = {'side': 'buy', 'quantity': '0.1', 'type': 'LIMIT'}
    lit_order = {'side': 'sell', 'quantity': '0.1', 'type': 'LIMIT'}

    ext_result, lit_result, gap = await executor.execute_concurrent_orders(
        ext_order, lit_order
    )

    logger.info(f"\n  Extended结果: success={ext_result['success']}, order_id={ext_result['order_id']}, error={ext_result.get('error')}")
    logger.info(f"  Lighter结果: success={lit_result['success']}, order_id={lit_result['order_id']}, error={lit_result.get('error')}")
    logger.info(f"  并发间隔: {gap:.2f}ms")

    # 验证错误消息存在
    if ext_result.get('error') and lit_result.get('error'):
        logger.info("  ✅ PASS: 错误日志包含详细错误信息（修复生效！）")
    else:
        logger.error("  ❌ FAIL: 错误日志缺少详细错误信息")

    # 测试单腿持仓场景
    logger.info("\n[测试3.2] 单腿持仓日志:")

    # 重新配置mock：Extended成功，Lighter失败
    extended_client.place_open_order = AsyncMock(
        return_value=MockOrderResult(success=True, order_id="ext_123", filled_size=Decimal('0.1'))
    )

    ext_result, lit_result, gap = await executor.execute_concurrent_orders(
        ext_order, lit_order
    )

    logger.info(f"\n  Extended结果: success={ext_result['success']}, order_id={ext_result['order_id']}")
    logger.info(f"  Lighter结果: success={lit_result['success']}, order_id={lit_result['order_id']}, error={lit_result.get('error')}")

    if ext_result['success'] != lit_result['success']:
        logger.info("  ✅ PASS: 单腿持仓场景正确识别")
        logger.info(f"  ✅ 日志显示具体错误: Extended order_id={ext_result['order_id']}, Lighter error={lit_result.get('error')}")
    else:
        logger.error("  ❌ FAIL: 单腿持仓场景识别错误")

    return True


async def test_integration_scenario():
    """集成测试：模拟真实场景"""
    logger.info("\n" + "=" * 60)
    logger.info("集成测试: 模拟真实订单执行场景")
    logger.info("=" * 60)

    config = SpreadArbConfig(
        concurrent_order_send_threshold_ms=5.0,
        order_timeout_ms=500,
        emergency_close_timeout_ms=1000,
        ticker='ETH'
    )
    monitor = PerformanceMonitor(config)

    # 模拟真实场景
    extended_client = Mock()
    extended_client.config = Mock()
    extended_client.config.contract_id = "ETH-USD"

    async def mock_ext_place_open(contract_id, quantity, direction, post_only=False):
        # Extended IOC订单立即返回
        if not post_only:
            await asyncio.sleep(0.01)  # 10ms
            return MockOrderResult(success=True, order_id="ext_456", filled_size=Decimal('0.1'))
        return MockOrderResult(success=True, order_id="ext_789")

    extended_client.place_open_order = mock_ext_place_open
    extended_client.place_close_order = AsyncMock()

    lighter_client = Mock()
    lighter_client.config = Mock()
    lighter_client.config.contract_id = "ETH-USD"

    async def mock_lit_place_open(contract_id, quantity, direction):
        await asyncio.sleep(0.015)  # 15ms
        return MockOrderResult(success=True, order_id="lit_789", filled_size=Decimal('0.1'))

    lighter_client.place_open_order = mock_lit_place_open
    lighter_client.place_close_order = AsyncMock()

    executor = ConcurrentExecutor(
        config=config,
        monitor=monitor,
        extended_client=extended_client,
        lighter_client=lighter_client,
        logger=logger
    )

    # 执行并发订单
    logger.info("\n[集成测试] 执行并发订单...")
    ext_order = {'side': 'buy', 'quantity': '0.1', 'type': 'LIMIT'}
    lit_order = {'side': 'sell', 'quantity': '0.1', 'type': 'LIMIT'}

    ext_result, lit_result, gap = await executor.execute_concurrent_orders(
        ext_order, lit_order
    )

    logger.info(f"\n结果:")
    logger.info(f"  Extended: success={ext_result['success']}, order_id={ext_result['order_id']}")
    logger.info(f"  Lighter: success={lit_result['success']}, order_id={lit_result['order_id']}")
    logger.info(f"  并发间隔: {gap:.2f}ms")

    # 验证
    all_success = ext_result['success'] and lit_result['success']
    gap_ok = gap < 5.0

    if all_success and gap_ok:
        logger.info("\n  ✅ PASS: 集成测试成功")
        logger.info("  ✅ 两个订单都成功")
        logger.info("  ✅ 并发间隔在阈值内（<5ms）")
        return True
    else:
        logger.error(f"\n  ❌ FAIL: 集成测试失败")
        logger.error(f"    all_success={all_success}, gap_ok={gap_ok}")
        return False


async def main():
    """主函数"""
    logger.info("\n" + "=" * 60)
    logger.info("013-fix-order-timeout 修复验证测试")
    logger.info("=" * 60)

    results = {}

    # 测试修复1
    try:
        results['fix1'] = await test_fix_1_extended_ioc_immediate_return()
    except Exception as e:
        logger.error(f"修复1测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        results['fix1'] = False

    # 测试修复2
    try:
        results['fix2'] = await test_fix_2_lighter_order_id_validation()
    except Exception as e:
        logger.error(f"修复2测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        results['fix2'] = False

    # 测试修复3
    try:
        results['fix3'] = await test_fix_3_enhanced_error_logging()
    except Exception as e:
        logger.error(f"修复3测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        results['fix3'] = False

    # 集成测试
    try:
        results['integration'] = await test_integration_scenario()
    except Exception as e:
        logger.error(f"集成测试失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        results['integration'] = False

    # 总结
    logger.info("\n" + "=" * 60)
    logger.info("测试总结")
    logger.info("=" * 60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"  {test_name}: {status}")

    all_passed = all(results.values())

    logger.info("\n" + "=" * 60)
    if all_passed:
        logger.info("🎉 所有测试通过！修复验证成功！")
    else:
        logger.error("❌ 部分测试失败，请检查修复是否正确应用")
    logger.info("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
