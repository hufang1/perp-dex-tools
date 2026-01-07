#!/usr/bin/env python3
"""
测试 Lighter WebSocket 连接

用于诊断 HTTP 400 错误问题
"""

import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

async def test_lighter_ws():
    """测试 Lighter WebSocket 连接"""
    ws_url = "wss://mainnet.zklighter.elliot.ai/stream"
    market_index = 0  # ETH 的 market_index
    account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
    api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))

    print("=" * 60)
    print("Lighter WebSocket 连接测试")
    print("=" * 60)
    print(f"WebSocket URL: {ws_url}")
    print(f"Market Index: {market_index}")
    print(f"Account Index: {account_index}")
    print(f"API Key Index: {api_key_index}")
    print("-" * 60)

    try:
        print("🔍 尝试连接...")
        async with websockets.connect(ws_url) as ws:
            print("✅ TCP连接成功!")

            # 尝试订阅订单簿
            order_book_channel = f"order_book/{market_index}"
            subscribe_msg = {
                "type": "subscribe",
                "channel": order_book_channel
            }

            print(f"📤 发送订阅消息: {subscribe_msg}")
            await ws.send(json.dumps(subscribe_msg))
            print("✅ 订阅消息已发送")

            # 等待响应
            print("⏳ 等待服务器响应...")
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=10)
                print(f"📥 收到响应: {response[:200]}...")  # 只显示前200个字符

                data = json.loads(response)
                print(f"📊 响应类型: {data.get('type')}")
                print(f"📊 响应数据: {json.dumps(data, indent=2)[:500]}...")

                if data.get("type") == "subscribed/order_book":
                    print("✅ 订单簿订阅成功!")
                    order_book = data.get("order_book", {})
                    print(f"   Bids数量: {len(order_book.get('bids', []))}")
                    print(f"   Asks数量: {len(order_book.get('asks', []))}")

            except asyncio.TimeoutError:
                print("⏱️ 10秒内未收到响应")

            print("\n✅ 测试完成!")

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ HTTP状态码错误: {e}")
        print(f"   状态码: {e.status_code}")
        print(f"   响应头: {e.headers}")
        print("\n🔍 诊断:")
        print("   HTTP 400 通常表示:")
        print("   1. WebSocket握手失败")
        print("   2. 协议版本不匹配")
        print("   3. 服务器暂时不可用")
        print("   4. 速率限制")
        print("\n   建议:")
        print("   1. 检查网络连接")
        print("   2. 稍后重试（可能是服务器临时问题）")
        print("   3. 如果持续出现，请联系Lighter支持")

    except Exception as e:
        print(f"❌ 连接错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_lighter_ws())
