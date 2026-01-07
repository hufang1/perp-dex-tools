#!/usr/bin/env python3
"""
价差套利策略运行入口

Extended-Lighter 跨交易所价差套利
"""

import asyncio
import argparse
import logging
import sys
import os
from pathlib import Path
from decimal import Decimal
import dotenv

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spread.config import SpreadArbConfig
from spread.bot import SpreadArbitrageBot
from exchanges.extended import ExtendedClient
from exchanges.lighter import LighterClient


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Extended-Lighter 价差套利策略',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 使用默认参数运行 ETH
    python run_spread_arb.py --ticker ETH
    
    # 自定义参数
    python run_spread_arb.py --ticker ETH --quantity 200 --min-spread 0.0008
    
    # 使用自定义环境变量文件
    python run_spread_arb.py --ticker BTC --env-file .env.account1
        """
    )
    
    # 基础参数
    parser.add_argument('--ticker', type=str, default='ETH',
                        help='交易对符号 (default: ETH)')
    parser.add_argument('--env-file', type=str, default='.env',
                        help='环境变量文件 (default: .env)')
    
    # 下单参数
    parser.add_argument('--quantity', type=float, default=35,
                        help='单次下单金额 USDT (default: 35)')
    
    # 价差参数
    parser.add_argument('--min-spread', type=float, default=0.0002,
                        help='最小价差率 (default: 0.0002 = 0.02%%)')
    parser.add_argument('--latency-buffer', type=float, default=0.0001,
                        help='延迟缓冲 (default: 0.0001 = 0.01%%)')
    
    # 持仓管理
    parser.add_argument('--max-pairs', type=int, default=3,
                        help='最大同时持有套利对数 (default: 3)')
    parser.add_argument('--max-holding-time', type=int, default=1800,
                        help='最大持仓时间秒数 (default: 1800 = 30分钟)')
    
    # 风险控制
    parser.add_argument('--stop-loss', type=float, default=5,
                        help='止损金额 USDT (default: 5)')
    parser.add_argument('--slippage-tolerance', type=float, default=0.001,
                        help='最大可接受滑点 (default: 0.001 = 0.1%%)')
    
    # 其他
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='日志级别 (default: INFO)')
    parser.add_argument('--no-prioritize-closing', action='store_true',
                        help='不优先平仓 (default: 优先平仓)')
    
    return parser.parse_args()


def setup_logging(log_level: str):
    """配置日志系统"""
    # 创建日志目录
    log_dir = Path("logs/spread")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 配置根日志
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_dir / f"spread_arb_{args.ticker.lower()}.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # 抑制第三方库日志
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)


class Config:
    """配置包装类 (用于兼容 Extended 客户端)"""
    def __init__(self, config_dict):
        for key, value in config_dict.items():
            setattr(self, key, value)


async def main():
    """主函数"""
    global args
    args = parse_arguments()
    
    # 设置日志
    setup_logging(args.log_level)
    logger = logging.getLogger("Main")
    
    # 检查环境变量文件
    env_path = Path(args.env_file)
    if not env_path.exists():
        logger.error(f"环境变量文件不存在: {env_path.resolve()}")
        sys.exit(1)
    
    # 加载环境变量
    dotenv.load_dotenv(args.env_file)
    logger.info(f"已加载环境变量: {args.env_file}")
    
    # 创建配置
    config = SpreadArbConfig(
        ticker=args.ticker.upper(),
        order_quantity_usdt=Decimal(str(args.quantity)),
        min_spread_rate=Decimal(str(args.min_spread)),
        latency_buffer=Decimal(str(args.latency_buffer)),
        max_open_pairs=args.max_pairs,
        max_holding_time=args.max_holding_time,
        stop_loss_usdt=Decimal(str(args.stop_loss)),
        slippage_tolerance=Decimal(str(args.slippage_tolerance)),
        log_level=args.log_level,
        prioritize_closing=not args.no_prioritize_closing
    )
    
    logger.info("="*60)
    logger.info("初始化 Extended 客户端...")
    
    # 初始化 Extended 客户端
    extended_config_dict = {
        'ticker': config.ticker,
        'contract_id': '',
        'quantity': config.order_quantity_usdt / Decimal('3000'),  # 临时值
        'tick_size': Decimal('0.001'),
        'close_order_side': 'sell'
    }
    extended_config = Config(extended_config_dict)
    extended_client = ExtendedClient(extended_config)
    
    logger.info("初始化 Lighter 客户端...")
    
    # 初始化 Lighter 客户端
    lighter_config_dict = {
        'ticker': config.ticker,
        'contract_id': '',
        'quantity': config.order_quantity_usdt / Decimal('3000'),
        'tick_size': Decimal('0.001'),
        'close_order_side': 'sell'
    }
    lighter_config = Config(lighter_config_dict)
    lighter_client = LighterClient(lighter_config)

    # 🔍 DEBUG: 验证客户端创建成功
    logger.info(f"✅ LighterClient已创建, config.contract_id='{lighter_client.config.contract_id}'")

    # 获取合约信息 (必须在连接 WebSocket 之前获取，因为订阅需要 Contract ID)
    logger.info("获取合约信息...")

    # 🔍 DEBUG: 开始获取Extended合约信息
    logger.info("📍 [1/4] 开始获取Extended合约属性...")
    try:
        extended_contract_id, extended_tick_size = await extended_client.get_contract_attributes()
        logger.info(f"✅ Extended合约属性: contract_id={extended_contract_id}")
    except Exception as e:
        logger.error(f"❌ 获取Extended合约信息失败: {e}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        raise

    # 🔍 DEBUG: 开始获取Lighter合约信息
    logger.info("📍 [2/4] 开始获取Lighter合约属性...")
    try:
        lighter_contract_id, lighter_tick_size = await lighter_client.get_contract_attributes()
        logger.info(f"✅ Lighter合约属性: contract_id={lighter_contract_id}")
    except Exception as e:
        logger.error(f"❌ 获取Lighter合约信息失败: {e}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        raise
    
    extended_client.contract_id = extended_contract_id
    extended_client.config.tick_size = extended_tick_size
    extended_client.config.contract_id = extended_contract_id
    lighter_client.contract_id = lighter_contract_id
    lighter_client.config.tick_size = lighter_tick_size
    lighter_client.config.contract_id = lighter_contract_id

    # 🔍 DEBUG: 验证设置是否成功
    logger.info(f"📍 [3/4] 验证config设置:")
    logger.info(f"  Extended: contract_id={extended_client.config.contract_id}")
    logger.info(f"  Lighter: contract_id={lighter_client.config.contract_id}")
    logger.info(f"  lighter_client.contract_id={lighter_client.contract_id}")

    # 再次验证（确保不是空字符串，注意 0 是合法的 market_id）
    if lighter_client.config.contract_id == '' or lighter_client.config.contract_id is None:
        logger.error("❌ 错误: lighter_client.config.contract_id 仍为空!")
        raise ValueError("lighter_client.config.contract_id 未被正确设置")

    logger.info(f"✅ contract_id 验证通过: {lighter_client.config.contract_id}")

    logger.info(f"Extended 合约: {extended_contract_id}, Tick Size: {extended_tick_size}")
    logger.info(f"Lighter 合约: {lighter_contract_id}, Tick Size: {lighter_tick_size}")

    # 更新 Lighter WS Manager 的配置
    if hasattr(lighter_client, 'ws_manager') and lighter_client.ws_manager:
        lighter_client.ws_manager.market_index = lighter_contract_id
        logger.info(f"已更新 Lighter WS Manager Market Index: {lighter_contract_id}")

    # 连接交易所
    logger.info("📍 [4/4] 连接到交易所...")
    logger.info(f"  连接前 lighter_client.config.contract_id={lighter_client.config.contract_id}")

    logger.info("  连接Extended...")
    await extended_client.connect()
    logger.info("  Extended连接完成")

    logger.info("  连接Lighter...")
    await lighter_client.connect()
    logger.info("  Lighter连接完成")
    
    # 等待 WebSocket 连接稳定
    logger.info("等待 WebSocket 连接稳定...")
    await asyncio.sleep(3)
    
    # 创建并运行套利机器人
    logger.info("创建套利机器人...")
    bot = SpreadArbitrageBot(
        config=config,
        extended_client=extended_client,
        lighter_client=lighter_client
    )
    
    # 启动订单簿同步任务
    async def sync_orderbooks():
        """持续同步订单簿数据"""
        logger.info("启动订单簿同步任务...")
        while True:
            try:
                # 同步 Extended 订单簿
                # ExtendedClient 的属性是 'orderbook'，不是 'extended_order_book'
                if hasattr(extended_client, 'orderbook') and extended_client.orderbook:
                    ex_raw = extended_client.orderbook
                    
                    # 转换 Extended 数据格式: {'bid': [{'p': '...', 'q': '...'}], ...} -> {'bids': {price: size}, ...}
                    formatted_book = {'bids': {}, 'asks': {}}
                    
                    # 处理买单
                    if ex_raw.get('bid'):
                        for item in ex_raw['bid']:
                            try:
                                p = Decimal(str(item['p']))
                                q = Decimal(str(item['q']))
                                if q > 0:
                                    formatted_book['bids'][p] = q
                            except:
                                pass
                                
                    # 处理卖单
                    if ex_raw.get('ask'):
                        for item in ex_raw['ask']:
                            try:
                                p = Decimal(str(item['p']))
                                q = Decimal(str(item['q']))
                                if q > 0:
                                    formatted_book['asks'][p] = q
                            except:
                                pass
                    
                    # 只有当有数据时才更新
                    if formatted_book['bids'] or formatted_book['asks']:
                         bot.update_extended_orderbook(formatted_book)
                else:
                    # 某些时刻可能还没准备好，不属于错误，但可以记录 debug 日志
                    pass
                
                # 同步 Lighter 订单簿
                if hasattr(lighter_client, 'ws_manager') and hasattr(lighter_client.ws_manager, 'order_book'):
                    li_book = lighter_client.ws_manager.order_book
                    if li_book:
                        # 转换 Lighter 数据格式 (float -> Decimal)
                        formatted_li_book = {'bids': {}, 'asks': {}}
                        
                        # 处理买单
                        if li_book.get('bids'):
                            for p, q in li_book['bids'].items():
                                try:
                                    formatted_li_book['bids'][Decimal(str(p))] = Decimal(str(q))
                                except:
                                    pass
                        
                        # 处理卖单
                        if li_book.get('asks'):
                            for p, q in li_book['asks'].items():
                                try:
                                    formatted_li_book['asks'][Decimal(str(p))] = Decimal(str(q))
                                except:
                                    pass

                        bot.update_lighter_orderbook(formatted_li_book)
                
                await asyncio.sleep(0.1)  # 每 100ms 同步一次
            except Exception as e:
                logger.error(f"订单簿同步错误: {e}")
                # import traceback
                # logger.error(traceback.format_exc())
                await asyncio.sleep(1)
    
    # 启动同步任务
    sync_task = asyncio.create_task(sync_orderbooks())
    
    logger.info("="*60)
    logger.info("启动套利机器人...")
    logger.info("="*60)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("\n用户中断")
    except Exception as e:
        logger.error(f"运行错误: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # 断开连接
        logger.info("断开连接...")
        await extended_client.disconnect()
        await lighter_client.disconnect()
        logger.info("程序退出")


if __name__ == "__main__":
    asyncio.run(main())
