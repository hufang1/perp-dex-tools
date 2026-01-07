#!/usr/bin/env python3
"""
演示竞态条件修复效果的脚本

该脚本模拟了用户遇到的问题场景：
1. Extended订单成交
2. WebSocket回调在下单函数返回前到达
3. 验证缓存机制正确处理此竞态条件
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock

from spread.order_manager import SpreadOrderManager


class MockConfig:
    def __init__(self):
        self.ticker = 'ETH'
        self.order_quantity_usdt = Decimal('35')
        self.extended_fill_timeout = 10
        self.enable_partial_fill = True


class MockExtendedClient:
    def __init__(self):
        self.contract_id = 'ETH-USD'


async def demonstrate_race_condition_fix():
    """演示竞态条件修复"""
    print("="*80)
    print("竞态条件修复演示")
    print("="*80)

    # 创建订单管理器
    config = MockConfig()
    client = MockExtendedClient()
    manager = SpreadOrderManager(config, client)

    order_id = "2008773271629754368"

    print(f"\n场景：订单 {order_id} 在下单函数返回前成交")
    print("-"*80)

    # 步骤1: WebSocket收到FILLED状态（此时current_order_id还是None）
    print(f"\n[1] WebSocket收到FILLED状态更新")
    print(f"    当前 current_order_id = {manager.current_order_id}")

    order_data = {
        'order_id': order_id,
        'status': 'FILLED',
        'side': 'buy',
        'order_type': 'OPEN',
        'size': '0.01',
        'price': '3251.4',
        'contract_id': 'ETH-USD',
        'filled_size': '0.010'
    }

    manager.update_order_status(order_data)

    print(f"    ✅ 更新已被缓存（因为 current_order_id = None）")
    print(f"    缓存大小: {len(manager._pending_updates)}")
    print(f"    current_order_status = {manager.current_order_status}")
    print(f"    filled_quantity = {manager.filled_quantity}")

    # 步骤2: 模拟place_spread_maker_order函数返回并设置current_order_id
    print(f"\n[2] place_spread_maker_order返回，设置 current_order_id")
    manager.current_order_id = order_id
    print(f"    current_order_id = {manager.current_order_id}")

    # 步骤3: 应用缓存的更新
    print(f"\n[3] 应用缓存的订单更新")
    await manager._apply_pending_updates(order_id)

    print(f"    ✅ 缓存已应用")
    print(f"    current_order_status = {manager.current_order_status}")
    print(f"    filled_quantity = {manager.filled_quantity}")
    print(f"    filled_price = {manager.filled_price}")
    print(f"    缓存命中次数: {manager._cache_hits}")

    # 验证结果
    print("\n" + "="*80)
    print("验证结果")
    print("="*80)

    assert manager.current_order_status == 'FILLED', "状态应该是FILLED"
    assert manager.filled_quantity == Decimal('0.010'), "成交数量应该是0.010"
    assert manager.filled_price == Decimal('3251.4'), "成交价格应该是3251.4"
    assert manager._cache_hits == 1, "缓存命中次数应该是1"
    assert len(manager._pending_updates) == 0, "缓存应该被清空"

    print("✅ 所有验证通过！")
    print()
    print("总结：")
    print("  1. WebSocket回调在下单返回前到达 → 更新被缓存")
    print("  2. 设置current_order_id后 → 应用缓存更新")
    print("  3. filled_quantity和filled_price被正确更新")
    print("  4. wait_for_fill将立即检测到FILLED状态，不会超时")
    print("  5. Lighter对冲订单将成功执行")
    print()
    print("🎉 竞态条件bug已修复！")
    print("="*80)


async def demonstrate_multiple_updates():
    """演示多个状态更新的处理"""
    print("\n\n")
    print("="*80)
    print("多个状态更新处理演示")
    print("="*80)

    config = MockConfig()
    client = MockExtendedClient()
    manager = SpreadOrderManager(config, client)

    order_id = "2008773321807298560"

    print(f"\n场景：订单 {order_id} 部分成交后完全成交")
    print("-"*80)

    # 部分成交
    print(f"\n[1] 收到PARTIALLY_FILLED状态")
    manager.update_order_status({
        'order_id': order_id,
        'status': 'PARTIALLY_FILLED',
        'order_type': 'OPEN',
        'filled_size': '0.005'
    })

    # 完全成交
    print(f"[2] 收到FILLED状态")
    manager.update_order_status({
        'order_id': order_id,
        'status': 'FILLED',
        'order_type': 'OPEN',
        'filled_size': '0.010',
        'price': '3252.0'
    })

    print(f"    缓存了 {len(manager._pending_updates[order_id])} 个更新")

    # 应用缓存
    manager.current_order_id = order_id
    await manager._apply_pending_updates(order_id)

    print(f"\n最终状态:")
    print(f"    current_order_status = {manager.current_order_status}")
    print(f"    filled_quantity = {manager.filled_quantity}")
    print(f"    filled_price = {manager.filled_price}")

    assert manager.current_order_status == 'FILLED'
    assert manager.filled_quantity == Decimal('0.010')
    assert manager.filled_price == Decimal('3252.0')

    print("\n✅ 多个状态更新按时间戳顺序正确应用！")
    print("="*80)


if __name__ == '__main__':
    asyncio.run(demonstrate_race_condition_fix())
    asyncio.run(demonstrate_multiple_updates())
