"""
套利机器人主控制器：Lighter-Extended 单向价差收敛套利系统

负责：
1. 协调所有组件
2. 执行主交易循环
3. 处理订单簿更新
4. 状态管理和持久化
5. 信号处理（优雅关闭）
"""

import asyncio
import signal
import sys
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
import argparse
import os

from models import (
    BotState,
    BotConfig,
    Position,
    PositionState,
    BotStats,
    Trade,
    SpreadInfo,
)
from order_book_manager import OrderBookManager
from spread_calculator import SpreadCalculator
from risk_manager import RiskManager
from trade_executor import TradeExecutor, ExecutionResult
from state_manager import StateManager
from exceptions import SpreadArbError, SingleSideExecutionError

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class SpreadArbBot:
    """
    套利机器人主控制器

    协调所有组件，执行价差套利策略
    """

    def __init__(self, config: BotConfig):
        """
        初始化机器人

        Args:
            config: 配置对象
        """
        self.config = config

        # 组件初始化（稍后在 start 方法中完成）
        self.order_book_manager: Optional[OrderBookManager] = None
        self.spread_calculator: Optional[SpreadCalculator] = None
        self.risk_manager: Optional[RiskManager] = None
        self.trade_executor: Optional[TradeExecutor] = None
        self.state_manager: Optional[StateManager] = None
        self.lighter_client = None
        self.extended_client = None

        # 运行状态
        self._running = False
        self._stop_event = asyncio.Event()

        # 统计信息
        self.start_time: Optional[datetime] = None

        logger.info("套利机器人初始化完成")
        logger.info(f"配置: 交易对={config.symbol}, "
                   f"数量={config.target_quantity}, "
                   f"开仓阈值={config.min_spread_threshold:.2%}, "
                   f"最小利润={config.min_profit:.2%}")

    async def start(self) -> None:
        """启动机器人"""
        logger.info("=" * 50)
        logger.info("启动机器人...")
        logger.info("=" * 50)

        try:
            self.start_time = datetime.now()

            # 1. 初始化交易所客户端
            await self._init_clients()

            # 2. 初始化组件
            await self._init_components()

            # 3. 加载状态
            await self._load_state()

            # 4. 启动订单簿连接
            await self.order_book_manager.start()

            # 5. 启动自动保存
            await self.state_manager.start_auto_save()

            # 6. 设置信号处理
            self._setup_signal_handlers()

            # 7. 运行主交易循环
            self._running = True
            await self.run_trading_loop()

        except Exception as e:
            logger.error(f"启动失败: {e}", exc_info=True)
            await self.stop()
            raise

    async def stop(self) -> None:
        """停止机器人"""
        if not self._running:
            return

        logger.info("正在停止机器人...")
        self._running = False
        self._stop_event.set()

        try:
            # 停止自动保存
            if self.state_manager:
                await self.state_manager.stop_auto_save()

            # 保存最终状态
            if self.state_manager:
                await self.state_manager.save_state()

            # 停止订单簿连接
            if self.order_book_manager:
                await self.order_book_manager.stop()

            # 打印统计信息
            self._print_stats()

            logger.info("机器人已停止")

        except Exception as e:
            logger.error(f"停止时出错: {e}", exc_info=True)

    async def run_trading_loop(self) -> None:
        """运行主交易循环"""
        logger.info("主交易循环已启动")

        check_interval = 1.0  # 每秒检查一次

        while not self._stop_event.is_set():
            try:
                # 获取当前状态
                state = self.state_manager.get_state()

                if state == BotState.IDLE:
                    await self._process_idle_state()

                elif state == BotState.HOLDING:
                    await self._process_holding_state()

                elif state == BotState.OPENING:
                    await self._process_opening_state()

                elif state == BotState.CLOSING:
                    await self._process_closing_state()

                elif state == BotState.ERROR:
                    logger.error("处于错误状态，停止交易")
                    break

                # 等待下一次检查
                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                logger.info("交易循环被取消")
                break
            except Exception as e:
                logger.error(f"交易循环异常: {e}", exc_info=True)
                # 继续运行，不要因为单次错误而停止

    async def _process_idle_state(self) -> None:
        """处理 IDLE 状态：监控价差，寻找开仓机会"""
        if not self.order_book_manager.is_ready():
            logger.debug("订单簿未就绪，等待中...")
            return

        # 计算开仓价差
        spread_info = await self.spread_calculator.calculate_open_spread(
            self.order_book_manager,
            self.config.target_quantity
        )

        if spread_info is None:
            return

        # 检查是否满足开仓条件
        if self.spread_calculator.should_open(spread_info.open_spread):
            logger.info(
                f"发现套利机会: 价差={spread_info.open_spread:.2%}"
            )

            # 风控验证
            validation = await self.risk_manager.validate_open_position(
                self.order_book_manager,
                self.config.target_quantity,
                spread_info
            )

            if not validation.is_valid:
                logger.warning(f"开仓风控失败: {validation.reason}")
                return

            # 切换到开仓状态
            self.state_manager.set_state(BotState.OPENING)
            await self.state_manager.save_state()

    async def _process_opening_state(self) -> None:
        """处理 OPENING 状态：执行开仓"""
        logger.info("执行开仓...")

        # 计算价差
        spread_info = await self.spread_calculator.calculate_open_spread(
            self.order_book_manager,
            self.config.target_quantity
        )

        if spread_info is None:
            logger.warning("无法获取价差信息，取消开仓")
            self.state_manager.set_state(BotState.IDLE)
            await self.state_manager.save_state()
            return

        # 执行开仓
        result = await self.trade_executor.execute_open_position(
            self.config.target_quantity,
            spread_info
        )

        if result.success:
            # 开仓成功，创建持仓
            position = Position(
                state=PositionState.LONG,
                extended_entry_price=result.extended_price,
                lighter_entry_price=result.lighter_price,
                entry_spread=spread_info.open_spread,
                entry_time=datetime.now(),
                extended_quantity=self.config.target_quantity,
                lighter_quantity=-self.config.target_quantity,
                extended_order_id=result.extended_order_id,
                lighter_order_id=result.lighter_order_id,
            )

            self.state_manager.update_position(position)
            self.state_manager.set_state(BotState.HOLDING)
            await self.state_manager.save_state()

            logger.info(
                f"开仓成功: Extended={result.extended_price}, "
                f"Lighter={result.lighter_price}, "
                f"价差={spread_info.open_spread:.2%}"
            )

        else:
            # 开仓失败
            logger.error(f"开仓失败: {result.error_message}")

            # 检查是否单边成交
            if result.extended_filled != result.lighter_filled:
                await self._handle_single_side_execution(result)

            self.state_manager.set_state(BotState.IDLE)
            await self.state_manager.save_state()

    async def _process_holding_state(self) -> None:
        """处理 HOLDING 状态：监控价差，寻找平仓机会"""
        position = self.state_manager.get_position()

        if position is None:
            logger.warning("持仓信息丢失，返回 IDLE 状态")
            self.state_manager.set_state(BotState.IDLE)
            await self.state_manager.save_state()
            return

        # 计算平仓价差
        spread_info = await self.spread_calculator.calculate_close_spread(
            self.order_book_manager,
            abs(position.extended_quantity)
        )

        if spread_info is None or spread_info.close_spread is None:
            return

        # 检查是否满足平仓条件
        if self.spread_calculator.should_close(
            position.entry_spread,
            spread_info.close_spread,
            position
        ):
            logger.info(
                f"价差收敛: 开仓={position.entry_spread:.2%}, "
                f"平仓={spread_info.close_spread:.2%}"
            )

            # 切换到平仓状态
            self.state_manager.set_state(BotState.CLOSING)
            await self.state_manager.save_state()

    async def _process_closing_state(self) -> None:
        """处理 CLOSING 状态：执行平仓"""
        logger.info("执行平仓...")

        position = self.state_manager.get_position()
        if position is None:
            logger.warning("持仓信息丢失")
            self.state_manager.set_state(BotState.IDLE)
            await self.state_manager.save_state()
            return

        # 执行平仓
        result = await self.trade_executor.execute_close_position(
            position,
            abs(position.extended_quantity)
        )

        if result.success:
            # 平仓成功，计算利润
            entry_spread = position.entry_spread
            close_spread = await self._calculate_close_spread_from_result(result)
            profit = self._calculate_profit(position, result)

            # 更新统计
            stats = self.state_manager.get_stats()
            stats.total_trades += 1
            if profit > 0:
                stats.profitable_trades += 1
            stats.total_profit += profit
            stats.total_fees += self._calculate_fees(position)
            stats.last_trade_time = datetime.now()
            self.state_manager.update_stats(stats)

            # 清除持仓
            self.state_manager.update_position(None)
            self.state_manager.set_state(BotState.IDLE)
            await self.state_manager.save_state()

            logger.info(
                f"平仓成功: 利润=${profit:.2f}, "
                f"价差收敛={entry_spread - close_spread:.2%}"
            )

        else:
            # 平仓失败
            logger.error(f"平仓失败: {result.error_message}")
            # 保持 HOLDING 状态，等待下一次机会
            self.state_manager.set_state(BotState.HOLDING)
            await self.state_manager.save_state()

    async def _handle_single_side_execution(self, result: ExecutionResult) -> None:
        """处理单边成交"""
        logger.error("检测到单边成交，执行紧急强平")

        if result.extended_filled and not result.lighter_filled:
            # Extended 成交，Lighter 未成交
            # 需要在 Extended 卖出
            await self.trade_executor.rollback_position(
                "extended",
                self.config.target_quantity,
                "sell"
            )

        elif result.lighter_filled and not result.extended_filled:
            # Lighter 成交，Extended 未成交
            # 需要在 Lighter 买入
            await self.trade_executor.rollback_position(
                "lighter",
                self.config.target_quantity,
                "buy"
            )

    def get_stats(self) -> BotStats:
        """获取统计信息"""
        return self.state_manager.get_stats()

    def get_status(self) -> Dict:
        """
        获取机器人状态

        Returns:
            状态信息字典
        """
        position = self.state_manager.get_position()
        stats = self.state_manager.get_stats()

        return {
            "state": self.state_manager.get_state().value,
            "position": {
                "state": position.state.value if position else None,
                "entry_spread": float(position.entry_spread) if position else None,
                "entry_time": position.entry_time.isoformat() if position and position.entry_time else None,
            } if position else None,
            "stats": {
                "total_trades": stats.total_trades,
                "profitable_trades": stats.profitable_trades,
                "total_profit": float(stats.total_profit),
                "win_rate": stats.win_rate,
            },
            "uptime": str(datetime.now() - self.start_time) if self.start_time else None,
        }

    # ========================================================================
    # 私有方法：初始化
    # ========================================================================

    async def _init_clients(self) -> None:
        """初始化交易所客户端"""
        logger.info("初始化交易所客户端...")

        # 添加项目根目录到 sys.path 以便导入 exchanges 模块
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.absolute()
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        # 导入交易所客户端
        from exchanges.lighter import LighterClient
        from exchanges.extended import ExtendedClient

        # 简单的 Config 类来包装字典（支持属性访问）
        class Config:
            def __init__(self, config_dict):
                for key, value in config_dict.items():
                    setattr(self, key, value)

        # 创建配置字典
        lighter_config_dict = {
            'ticker': self.config.symbol,
            'contract_id': '',  # 将在获取合约信息时设置
            'quantity': self.config.target_quantity,
            'tick_size': Decimal('0.01'),  # 将在获取合约信息时更新
            'close_order_side': 'sell'
        }

        extended_config_dict = {
            'ticker': self.config.symbol,
            'contract_id': '',  # 将在获取合约信息时设置
            'quantity': self.config.target_quantity,
            'tick_size': Decimal('0.01'),  # 将在获取合约信息时更新
            'close_order_side': 'sell'
        }

        # 使用 Config 类包装
        lighter_config = Config(lighter_config_dict)
        extended_config = Config(extended_config_dict)

        self.lighter_client = LighterClient(lighter_config)
        self.extended_client = ExtendedClient(extended_config)

        logger.info("交易所客户端初始化完成")

    async def _init_components(self) -> None:
        """初始化组件"""
        logger.info("初始化组件...")

        # 订单簿管理器
        self.order_book_manager = OrderBookManager(self.config.symbol)

        # 价差计算器
        self.spread_calculator = SpreadCalculator(
            open_threshold=self.config.min_spread_threshold,
            slippage_buffer=self.config.slippage_buffer,
            min_profit=self.config.min_profit,
            max_spread=self.config.max_spread
        )

        # 风控管理器
        self.risk_manager = RiskManager(
            self.lighter_client,
            self.extended_client,
            self.config
        )

        # 交易执行器
        self.trade_executor = TradeExecutor(
            self.lighter_client,
            self.extended_client,
            self.risk_manager,
            timeout=self.config.single_side_timeout
        )

        # 状态管理器
        state_file = Path("logs") / "spread_arb_state.json"
        self.state_manager = StateManager(state_file)

        logger.info("组件初始化完成")

    async def _load_state(self) -> None:
        """加载状态"""
        logger.info("加载状态...")

        state = await self.state_manager.load_state()
        logger.info(f"当前状态: {state.value}")

        position = self.state_manager.get_position()
        if position:
            logger.info(f"持仓: {position.state.value}, "
                       f"数量={abs(position.extended_quantity)}, "
                       f"开仓价差={position.entry_spread:.2%}")

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        def signal_handler(signum, frame):
            logger.info(f"收到信号 {signum}，准备关闭...")
            self._stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    # ========================================================================
    # 私有方法：辅助
    # ========================================================================

    def _print_stats(self) -> None:
        """打印统计信息"""
        stats = self.get_stats()

        logger.info("=" * 50)
        logger.info("运行统计:")
        logger.info(f"  总交易次数: {stats.total_trades}")
        logger.info(f"  盈利次数: {stats.profitable_trades}")
        logger.info(f"  胜率: {stats.win_rate:.1%}")
        logger.info(f"  总利润: ${stats.total_profit:.2f}")
        logger.info(f"  总手续费: ${stats.total_fees:.2f}")
        logger.info(f"  净利润: ${stats.net_profit:.2f}")

        if stats.start_time:
            uptime = datetime.now() - stats.start_time
            logger.info(f"  运行时间: {uptime}")

        logger.info("=" * 50)

    async def _calculate_close_spread_from_result(self, result: ExecutionResult) -> Decimal:
        """从执行结果计算平仓价差"""
        # 简化处理
        return Decimal("0.001")

    def _calculate_profit(self, position: Position, result: ExecutionResult) -> Decimal:
        """计算利润"""
        # 简化计算
        return self.config.target_quantity * position.entry_spread * position.extended_entry_price * Decimal("0.5")

    def _calculate_fees(self, position: Position) -> Decimal:
        """计算手续费"""
        # Extended 0.025% 双向 = 0.05%
        return self.config.target_quantity * position.extended_entry_price * Decimal("0.0005")


# ========================================================================
# 命令行接口
# ============================================================================

def parse_arguments() -> BotConfig:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Lighter-Extended 单向价差收敛套利系统"
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default="BTC",
        help="交易对 (默认: BTC)"
    )

    parser.add_argument(
        "--size",
        type=Decimal,
        default=Decimal("0.01"),
        dest="target_quantity",
        help="交易数量 (默认: 0.01)"
    )

    parser.add_argument(
        "--spread-threshold",
        type=Decimal,
        default=Decimal("0.002"),
        dest="min_spread_threshold",
        help="最小价差阈值 (默认: 0.002 = 0.2%%)"
    )

    parser.add_argument(
        "--slippage-buffer",
        type=Decimal,
        default=Decimal("0.0005"),
        help="滑点保护 (默认: 0.0005 = 0.05%%)"
    )

    parser.add_argument(
        "--min-profit",
        type=Decimal,
        default=Decimal("0.001"),
        help="最小利润 (默认: 0.001 = 0.1%%)"
    )

    parser.add_argument(
        "--max-spread",
        type=Decimal,
        default=Decimal("0.05"),
        help="极端价差阈值 (默认: 0.05 = 5%%)"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        dest="single_side_timeout",
        help="单边超时时间（秒） (默认: 3.0)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行模式"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志模式"
    )

    args = parser.parse_args()

    return BotConfig(
        symbol=args.symbol,
        target_quantity=args.target_quantity,
        min_spread_threshold=args.min_spread_threshold,
        slippage_buffer=args.slippage_buffer,
        min_profit=args.min_profit,
        max_spread=args.max_spread,
        single_side_timeout=args.single_side_timeout,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


async def main():
    """主函数"""
    # 解析配置
    config = parse_arguments()

    # 验证配置
    if not config.validate():
        logger.error("配置参数无效")
        sys.exit(1)

    # 检查环境变量（使用专用验证模块）
    from env_validator import check_env_before_start

    if not check_env_before_start():
        sys.exit(1)

    # 创建并启动机器人
    bot = SpreadArbBot(config)

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"运行异常: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
