"""
价差套利主引擎
"""

import asyncio
import logging
import time
import traceback
from decimal import Decimal
from typing import List, Optional, Dict, Any

from .config import SpreadArbConfig
from .spread_pair import SpreadPair
from .calculator import SpreadCalculator
from .order_manager import SpreadOrderManager
from .hedge_manager import HedgeManager
from .trade_logger import TradeLogger
from .position_aggregator import PositionAggregator, UnifiedPosition
from .profit_calculator import ProfitCalculator, ProfitBreakdown
from .models import SpreadChange, CloseDecision, PositionBalance, SpreadSnapshot
from .data_collector import DataCollector
from .trade_analyzer import TradeAnalyzer
from .spread_recorder import SpreadRecorder
from .safety_monitor import SafetyMonitor
from .adaptive_threshold_manager import AdaptiveThresholdManager

# 001-fix-order-type: 成功率追踪器
from .success_tracker import SuccessTracker, SpreadOperationResult
from .models import (
    SpreadChange, CloseDecision, PositionBalance, SpreadSnapshot,
    OperationType, OperationStatus, ExchangeType, FailureReason
)

# 011-async-ws-ioc-trading: 异步重构模块
from .performance_monitor import PerformanceMonitor
from .websocket_manager import WebSocketManager
from .concurrent_executor import ConcurrentExecutor
from .ioc_order_manager import IocOrderManager
from .risk_validator import RiskValidator

# 012-dual-leg-concurrency: 单腿回滚处理
from .leg_rollback_handler import LegRollbackHandler

# 012-dual-leg-concurrency: 极简平仓策略
from .simple_close_strategy import SimpleCloseStrategy

from .models import (
    OrderBookSnapshot,
    TimingRecord,
    DataFreshnessResult,
    SlippageCheckResult,
    ProfitabilityCheckResult,
    TradeOperationRecord,
    ConcurrentOrderResult,
    LegRollbackEvent,
)


class SpreadArbitrageBot:
    """价差套利主引擎"""
    
    def __init__(
        self,
        config: SpreadArbConfig,
        extended_client,
        lighter_client
    ):
        """
        初始化套利机器人
        
        Args:
            config: 配置对象
            extended_client: Extended 客户端实例
            lighter_client: Lighter 客户端实例
        """
        self.config = config
        self.extended_client = extended_client
        self.lighter_client = lighter_client
        
        # 设置日志
        self.logger = logging.getLogger("SpreadArbBot")
        self.logger.setLevel(getattr(logging, config.log_level))
        
        # 初始化模块
        self.calculator = SpreadCalculator(config)
        self.order_manager = SpreadOrderManager(config, extended_client)
        self.hedge_manager = HedgeManager(config, lighter_client)

        # 初始化交易日志记录器
        self.trade_logger = TradeLogger(log_file_path="logs/trade.log")

        # 初始化持仓聚合器和收益计算器
        self.position_aggregator = PositionAggregator(
            extended_fee_rate=config.extended_maker_fee_rate,
            lighter_fee_rate=config.lighter_fee_rate
        )
        self.profit_calculator = ProfitCalculator(
            extended_fee_rate=config.extended_maker_fee_rate,
            lighter_fee_rate=config.lighter_fee_rate
        )

        # T117: 初始化数据收集器和交易分析器
        self.data_collector = DataCollector(output_dir="data")
        self.trade_analyzer = TradeAnalyzer(data_collector=self.data_collector)
        self.collected_orders: List[Dict[str, Any]] = []  # 收集的订单记录

        # 价差记录器（001-spread-recorder）
        self.spread_recorder: Optional[SpreadRecorder] = None
        if config.enable_spread_recorder:
            self.spread_recorder = SpreadRecorder(config)
            self.logger.info("价差记录器已启用")

        # P0: 安全监控器（010-fix-position-imbalance）
        self.safety_monitor = SafetyMonitor(config, self.logger)
        if config.safety_enabled:
            self.logger.info("安全监控器已启用")

        # P1: 动态阈值管理器（010-fix-position-imbalance）
        self.adaptive_threshold_manager: Optional[AdaptiveThresholdManager] = None
        if config.adaptive_threshold_enabled:
            self.adaptive_threshold_manager = AdaptiveThresholdManager(config, self.safety_monitor)
            self.logger.info("动态阈值管理器已启用")

        # 001-fix-order-type: 成功率追踪器
        self.success_tracker = SuccessTracker(output_dir="data")
        self.logger.info("成功率追踪器已初始化")

        # ========================================================================
        # 011-async-ws-ioc-trading: 异步重构模块初始化
        # ========================================================================

        # 性能监控器 - 所有异步功能的核心
        self.performance_monitor = PerformanceMonitor(config, self.logger)
        self.logger.info("性能监控器已初始化")

        # WebSocket管理器 - 实时订单簿数据
        self.websocket_manager: Optional[WebSocketManager] = None
        # WebSocket将在_initialize中连接，避免在__init__中执行异步操作

        # 并发执行器 - 双腿并发交易
        self.concurrent_executor: Optional[ConcurrentExecutor] = None
        # 将在WebSocket连接后初始化，需要传入exchange clients

        # IOC订单管理器 - IOC订单创建和定价
        self.ioc_order_manager = IocOrderManager(config, self.logger)
        if config.use_ioc_orders:
            self.logger.info("IOC订单管理器已启用")

        # 风控验证器 - 开仓前综合验证
        self.risk_validator = RiskValidator(config, self.performance_monitor, self.logger)
        self.logger.info("风控验证器已初始化")

        # ========================================================================

        # WebSocket 订单簿数据
        self.extended_orderbook: Dict[str, Dict[Decimal, Decimal]] = {
            'bids': {},
            'asks': {}
        }
        self.lighter_orderbook: Dict[str, Dict[Decimal, Decimal]] = {
            'bids': {},
            'asks': {}
        }
        
        self.extended_orderbook_ready = False
        self.lighter_orderbook_ready = False
        
        # 套利对管理
        self.open_pairs: List[SpreadPair] = []
        self.next_pair_id = 1
        self.closed_pairs: List[SpreadPair] = []
        
        # 断路器
        self.consecutive_failures = 0
        self.is_paused = False
        self.pause_until = 0
        
        # 运行控制
        self.stop_flag = False

        # 启动预热期（防止启动时立即开仓）
        self.startup_time = time.time()
        self.startup_warmup_seconds = 5  # 预热期5秒
        
        # 统计
        self.stats = {
            'total_opportunities': 0,
            'opportunities_taken': 0,
            'opportunities_rejected': 0,
            'successful_opens': 0,
            'failed_opens': 0,
            'successful_closes': 0,
            'failed_closes': 0,
            'total_profit': Decimal('0'),
            'total_loss': Decimal('0'),
            'max_open_pairs': 0,
            # T087-T088: 阈值相关统计
            'threshold_rejections': 0,  # 因阈值不足拒绝的次数
            'threshold_violations': 0   # 阈值违规次数
        }

        # 🔴 未对冲的Extended仓位跟踪（关键修复）
        self.unhedged_positions = []  # List[Dict] 记录未对冲的Extended订单

        # 🆕 对冲失败率统计
        self.hedge_attempts = []  # List[bool] 记录最近的对冲尝试 (True=成功, False=失败)

        # 🔴 关键修复：防止并发开仓的标志
        self.is_opening = False  # 是否正在执行开仓操作
        self.opening_lock = asyncio.Lock()  # 开仓操作的锁
    
    async def run(self):
        """主运行循环"""
        try:
            self.logger.info("="*60)
            self.logger.info("价差套利机器人启动")
            self.logger.info("="*60)
            
            # 1. 初始化
            await self._initialize()
            
            # 2. 启动任务
            tasks = [
                asyncio.create_task(self._strategy_loop(), name="strategy"),
                asyncio.create_task(self._monitor_pairs(), name="monitor"),
                asyncio.create_task(self._stats_reporter(), name="stats"),
                asyncio.create_task(self._reconciliation_loop(), name="reconciliation")  # 🆕 持仓对账
            ]

            # 3. 添加价差记录器任务（如果启用）
            if self.spread_recorder:
                tasks.append(
                    asyncio.create_task(
                        self.spread_recorder.record_loop(self._get_orderbook_prices),
                        name="spread_recorder"
                    )
                )
            
            # 3. 运行
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except KeyboardInterrupt:
            self.logger.info("\n用户中断")
        except Exception as e:
            self.logger.error(f"致命错误: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            await self._cleanup()
    
    async def _initialize(self):
        """初始化连接和客户端"""
        self.logger.info("初始化中...")

        # ========================================================================
        # 011-async-ws-ioc-trading: 初始化WebSocket管理器
        # ========================================================================
        self.websocket_manager = WebSocketManager(self.config, self.logger)

        # 设置订单簿回调
        self.websocket_manager.set_orderbook_callback(self._handle_websocket_orderbook)

        # 连接WebSocket（如果启用了）
        try:
            self.logger.info("连接WebSocket...")
            await self.websocket_manager.connect_all()

            # 订阅订单簿
            symbol = f"{self.config.ticker}-USD"
            await self.websocket_manager.subscribe_orderbook('extended', symbol)
            await self.websocket_manager.subscribe_orderbook('lighter', symbol)

            self.logger.info("✅ WebSocket已连接并订阅订单簿")
        except Exception as e:
            self.logger.warning(f"⚠️ WebSocket连接失败: {e}，将使用现有订单簿更新机制")
            # WebSocket失败不影响原有功能，继续使用原有的订单簿更新机制

        # 初始化并发执行器
        self.concurrent_executor = ConcurrentExecutor(
            config=self.config,
            monitor=self.performance_monitor,
            extended_client=self.extended_client,
            lighter_client=self.lighter_client,
            logger=self.logger
        )
        self.logger.info("✅ 并发执行器已初始化")

        # 012-dual-leg-concurrency: 初始化单腿回滚处理器（User Story 3）
        if self.config.enable_leg_rollback:
            self.leg_rollback_handler = LegRollbackHandler(
                config=self.config,
                monitor=self.performance_monitor,
                extended_client=self.extended_client,
                lighter_client=self.lighter_client,
                logger=self.logger
            )
            self.logger.info("✅ 单腿回滚处理器已启用")
        else:
            self.leg_rollback_handler = None

        # 012-dual-leg-concurrency: 初始化极简平仓策略（User Story 6）
        if self.config.enable_simple_close:
            self.simple_close_strategy = SimpleCloseStrategy(
                config=self.config,
                concurrent_executor=self.concurrent_executor,
                ioc_order_manager=self.ioc_order_manager,
                logger=self.logger
            )
            self.logger.info("✅ 极简平仓策略已启用")
        else:
            self.simple_close_strategy = None

        # ========================================================================

        # Extended 和 Lighter 客户端已经在外部初始化并连接
        # 这里只需要等待订单簿数据就绪

        # 设置订单更新回调
        self.extended_client.setup_order_update_handler(
            self._handle_extended_order_update
        )

        # 等待订单簿就绪
        self.logger.info("等待订单簿数据...")
        timeout = 30
        start = time.time()
        
        while not (self.extended_orderbook_ready and self.lighter_orderbook_ready):
            if time.time() - start > timeout:
                self.logger.error(f"初始化超时! 状态: Extended={self.extended_orderbook_ready}, Lighter={self.lighter_orderbook_ready}")
                self.logger.error(f"Extended Book: {len(self.extended_orderbook.get('bids', {}))} bids, {len(self.extended_orderbook.get('asks', {}))} asks")
                self.logger.error(f"Lighter Book: {len(self.lighter_orderbook.get('bids', {}))} bids, {len(self.lighter_orderbook.get('asks', {}))} asks")
                raise Exception("订单簿数据超时未就绪")
            
            # 每2秒打印一次等待状态
            if time.time() - start > 2 and int(time.time() * 2) % 4 == 0:
                self.logger.info(f"等待订单簿... Extended: {self.extended_orderbook_ready}, Lighter: {self.lighter_orderbook_ready}")
            
            await asyncio.sleep(0.5)
        
        self.logger.info("✅ 初始化完成")
        self.logger.info("-"*60)
        self._log_config()
        self.logger.info("-"*60)
    
    def _log_config(self):
        """记录配置信息"""
        self.logger.info("配置参数:")
        self.logger.info(f"  交易对: {self.config.ticker}")
        self.logger.info(f"  单次下单金额: ${self.config.order_quantity_usdt}")
        self.logger.info(
            f"  最小价差率: {self.config.min_spread_rate:.4%} "
            f"(有效阈值: {self.config.effective_min_spread:.4%} 含延迟缓冲)"
        )
        self.logger.info(f"  延迟缓冲: {self.config.latency_buffer:.4%}")
        self.logger.info(f"  最大套利对数: {self.config.max_open_pairs}")
        self.logger.info(f"  最大持仓时间: {self.config.max_holding_time}秒")
        self.logger.info(f"  时间平仓阈值: {self.config.time_close_threshold}秒")
        self.logger.info(f"  盈利目标: {self.config.profit_target_rate:.4%}")
        self.logger.info(f"  未对冲持仓超时: {self.config.unhedged_position_timeout}秒")
        self.logger.info(f"  优先平仓: {self.config.prioritize_closing}")
    
    async def _strategy_loop(self):
        """策略主循环"""
        self.logger.info("策略循环启动")

        while not self.stop_flag:
            try:
                # 🔴 关键安全检查：如果有未对冲仓位，立即暂停
                if len(self.unhedged_positions) > self.config.max_unhedged_positions:
                    self.logger.error(
                        f"🚨 检测到 {len(self.unhedged_positions)} 个未对冲仓位! "
                        f"超过最大限制 {self.config.max_unhedged_positions}! "
                        f"禁止开新仓! 请手动处理!"
                    )
                    await asyncio.sleep(5)
                    continue

                # 检查断路器
                if self.is_paused:
                    if time.time() < self.pause_until:
                        await asyncio.sleep(1)
                        continue
                    else:
                        self.is_paused = False
                        self.consecutive_failures = 0
                        self.logger.info("🔄 断路器恢复")

                # 🔴 启动预热期检查（防止启动时立即开仓）
                if time.time() - self.startup_time < self.startup_warmup_seconds:
                    await asyncio.sleep(0.5)
                    continue
                
                # 获取最佳价格
                extended_bid = max(self.extended_orderbook['bids'].keys()) if self.extended_orderbook['bids'] else Decimal('0')
                extended_ask = min(self.extended_orderbook['asks'].keys()) if self.extended_orderbook['asks'] else Decimal('999999')
                lighter_bid = max(self.lighter_orderbook['bids'].keys()) if self.lighter_orderbook['bids'] else Decimal('0')
                lighter_ask = min(self.lighter_orderbook['asks'].keys()) if self.lighter_orderbook['asks'] else Decimal('999999')
                self.logger.debug(
                    f"价格更新: Extended bid={extended_bid:.2f} ask={extended_ask:.2f}, "
                    f"Lighter bid={lighter_bid:.2f} ask={lighter_ask:.2f}"
                )
                # 检查价格有效性
                if extended_bid <= 0 or lighter_bid <= 0:
                    await asyncio.sleep(0.1)
                    continue

                # T064-T065: 数据新鲜度检查（User Story 5）
                current_time = time.time() * 1000
                ext_ts = self.extended_orderbook.get('timestamp_ms', current_time)
                lit_ts = self.lighter_orderbook.get('timestamp_ms', current_time)

                both_fresh, freshness_results = self.performance_monitor.check_both_data_freshness(
                    extended_ts=ext_ts,
                    lighter_ts=lit_ts,
                    current_time=current_time
                )

                if not both_fresh:
                    # 数据过期，跳过本次循环
                    await asyncio.sleep(0.1)
                    continue

                # 计算价差机会
                # 009-fix-spread-loss-fees: T029 - 使用真实价差计算（对手价）替代中间价
                opportunity = self.calculator.calculate_real_spread_opportunity(
                    extended_bid=extended_bid,
                    extended_ask=extended_ask,
                    lighter_bid=lighter_bid,
                    lighter_ask=lighter_ask
                )

                if opportunity:
                    self.stats['total_opportunities'] += 1

                    # T021-T022: 移除 _find_opposite_pair 和机会平仓逻辑
                    # 只关注开新仓，平仓由 _monitor_pairs 通过市价平仓处理

                    # 检查是否可以开新仓
                    if len(self.open_pairs) < self.config.max_open_pairs:
                        # 检查 Lighter 深度
                        hedge_side = 'sell' if opportunity['side'] == 'buy' else 'buy'
                        is_sufficient, safe_qty, avg_price = self.calculator.calculate_max_safe_quantity(
                            self.lighter_orderbook,
                            hedge_side,
                            opportunity['quantity']
                        )

                        if is_sufficient:
                            # P1: 使用动态阈值（010-fix-position-imbalance）
                            if self.adaptive_threshold_manager:
                                threshold = self.adaptive_threshold_manager.get_effective_min_spread_rate()
                            else:
                                threshold = self.config.effective_min_spread

                            # T030: DEBUG级别日志记录真实价差计算过程
                            # T086: 添加阈值对比日志
                            self.logger.debug(
                                f"📊 [真实价差详情] direction={opportunity.get('direction', 'N/A')}, "
                                f"extended_price={opportunity['extended_price']:.4f}, "
                                f"lighter_price={opportunity['lighter_price']:.4f}, "
                                f"spread={opportunity.get('spread', 0):.4f}, "
                                f"spread_rate={opportunity['spread_rate']:.4%}, "
                                f"expected_profit={opportunity['expected_profit_rate']:.4%}, "
                                f"【阈值对比】 spread_rate={opportunity['spread_rate']:.4%} >= "
                                f"threshold={threshold:.4%} ✓"
                            )
                            if opportunity.get('costs'):
                                costs = opportunity['costs']
                                self.logger.debug(
                                    f"📊 [成本分解] extended_cost={costs.extended_cost:.4%}, "
                                    f"lighter_cost={costs.lighter_cost:.4%}, "
                                    f"total_cost_rate={costs.total_cost_rate:.4%}"
                                )

                            self.logger.info(
                                f"🎯 发现开仓机会: {opportunity['type']} "
                                f"价差率: {opportunity['spread_rate']:.4%} "
                                f"预期利润: {opportunity['expected_profit_rate']:.4%} "
                                f"(阈值: {threshold:.4%})"
                            )

                            # ========================================================================
                            # T084: 011-async-ws-ioc-trading 时间戳记录
                            # ========================================================================
                            # 记录信号时间戳
                            self.performance_monitor.record_timestamp('signal')

                            # 获取数据时间戳
                            ext_ts, lit_ts = self._get_orderbook_timestamps()
                            if ext_ts:
                                self.performance_monitor.record_timestamp('data_A')
                            if lit_ts:
                                self.performance_monitor.record_timestamp('data_B')

                            # 数据新鲜度检查
                            both_fresh = True
                            freshness_results = []
                            if self.config.enable_data_freshness_check:
                                # 如果有WebSocket时间戳，使用它们进行验证
                                if ext_ts and lit_ts:
                                    both_fresh, freshness_results = self.risk_validator.validate_data_freshness(ext_ts, lit_ts)
                                    if not both_fresh:
                                        self.logger.warning(
                                            f"⚠️ 数据过期，跳过此机会"
                                        )
                                        self.stats['opportunities_rejected'] += 1
                                        await asyncio.sleep(0.1)
                                        continue
                            # ========================================================================

                            # 🔴 关键修复：检查是否正在开仓，防止并发
                            if self.is_opening:
                                self.logger.warning(
                                    f"⚠️ 正在执行开仓操作，跳过此机会 "
                                    f"(防止Ext和Lighter仓位不对等)"
                                )
                                self.stats['opportunities_rejected'] += 1
                                await asyncio.sleep(0.5)
                                continue

                            # 使用锁确保同时只有一个开仓操作
                            async with self.opening_lock:
                                if self.is_opening:
                                    # 双重检查
                                    self.logger.warning("⚠️ 开仓锁已获取，跳过")
                                    continue

                                self.is_opening = True
                                try:
                                    # T085: 传递时间戳和新鲜度结果用于TradeOperationRecord
                                    await self._open_new_pair(
                                        opportunity,
                                        ext_ts=ext_ts,
                                        lit_ts=lit_ts,
                                        freshness_results=freshness_results
                                    )
                                finally:
                                    self.is_opening = False
                        else:
                            self.stats['opportunities_rejected'] += 1
                            self.logger.debug(
                                f"⚠️ Lighter 深度不足: "
                                f"{safe_qty:.4f} < {opportunity['quantity']:.4f}"
                            )
                    else:
                        self.stats['opportunities_rejected'] += 1
                        self.logger.debug(
                            f"⚠️ 已达最大套利对数: {len(self.open_pairs)}/{self.config.max_open_pairs}"
                        )
                else:
                    # T087: 记录阈值拒绝次数
                    self.stats['threshold_rejections'] += 1
                    # T086: 日志显示阈值对比
                    threshold = self.config.effective_min_spread
                    self.logger.debug(
                        f"📊 [阈值检查] 无有效机会，当前价差不满足阈值 {threshold:.4%}"
                    )

                await asyncio.sleep(0.1)  # 100ms 检查间隔
                
            except Exception as e:
                self.logger.error(f"策略循环错误: {e}")
                self.logger.error(traceback.format_exc())
                await asyncio.sleep(1)
    
    async def _monitor_pairs(self):
        """监控套利对,检查强制平仓条件"""
        while not self.stop_flag:
            try:
                # 获取当前价格
                extended_bid = max(self.extended_orderbook['bids'].keys()) if self.extended_orderbook['bids'] else Decimal('0')
                extended_ask = min(self.extended_orderbook['asks'].keys()) if self.extended_orderbook['asks'] else Decimal('999999')
                lighter_bid = max(self.lighter_orderbook['bids'].keys()) if self.lighter_orderbook['bids'] else Decimal('0')
                lighter_ask = min(self.lighter_orderbook['asks'].keys()) if self.lighter_orderbook['asks'] else Decimal('999999')

                # 🆕 新的聚合显示逻辑
                if self.open_pairs:
                    self._log_unified_positions(extended_bid, extended_ask, lighter_bid, lighter_ask)

                    # T043: 计算并记录仓位平衡状态
                    extended_total_qty = sum(
                        p.extended_quantity for p in self.open_pairs
                        if p.extended_side == 'buy'
                    ) - sum(
                        p.extended_quantity for p in self.open_pairs
                        if p.extended_side == 'sell'
                    )

                    lighter_total_qty = sum(
                        p.lighter_quantity for p in self.open_pairs
                        if p.extended_side == 'sell'  # Lighter方向与Extended相反
                    ) - sum(
                        p.lighter_quantity for p in self.open_pairs
                        if p.extended_side == 'buy'
                    )

                    # P0: 更新安全监控器的仓位失衡率（010-fix-position-imbalance）
                    self.safety_monitor.update_position_imbalance(
                        extended_qty=extended_total_qty,
                        lighter_qty=lighter_total_qty
                    )

                    # 创建仓位平衡对象
                    position_balance = PositionBalance(
                        timestamp=time.time(),
                        extended_total_qty=abs(extended_total_qty),
                        lighter_total_qty=abs(lighter_total_qty),
                        diff_qty=abs(extended_total_qty - lighter_total_qty)
                    )

                    # 记录仓位平衡（仅在有失衡时）
                    if position_balance.is_imbalanced:
                        if not self.trade_logger.log_position_balance(position_balance):
                            self.logger.warning("仓位平衡记录失败，但交易继续")
                else:
                    self.logger.info("📊 当前无持仓")

                # T074-T077: 极简平仓策略（User Story 6）
                if self.simple_close_strategy is not None:
                    for pair in self.open_pairs[:]:  # 复制列表
                        # 使用SimpleCloseStrategy判断是否平仓
                        decision = self.simple_close_strategy.should_close(
                            pair=pair,
                            current_extended_bid=extended_bid,
                            current_extended_ask=extended_ask,
                            current_lighter_bid=lighter_bid,
                            current_lighter_ask=lighter_ask
                        )

                        # T077: 存储SimpleCloseDecision
                        pair.simple_close_decision = decision

                        if decision.should_close:
                            self.simple_close_strategy.log_decision(decision, pair.pair_id)

                            # 执行并发平仓
                            extended_orderbook = {'bid': extended_bid, 'ask': extended_ask}
                            lighter_orderbook = {'bid': lighter_bid, 'ask': lighter_ask}

                            close_result = await self.simple_close_strategy.execute_close(
                                pair=pair,
                                extended_orderbook=extended_orderbook,
                                lighter_orderbook=lighter_orderbook
                            )

                            if close_result.is_both_filled:
                                # 更新套利对状态
                                pair.close_extended_order_id = close_result.extended_order_id
                                pair.close_lighter_order_id = close_result.lighter_order_id
                                pair.close_extended_price = close_result.extended_filled_price
                                pair.close_lighter_price = close_result.lighter_filled_price
                                pair.is_closed = True
                                pair.close_time = time.time()

                                # 计算盈亏
                                profit = pair.close(
                                    close_extended_price=close_result.extended_filled_price,
                                    close_lighter_price=close_result.lighter_filled_price
                                )

                                # 从open_pairs移除
                                if pair in self.open_pairs:
                                    self.open_pairs.remove(pair)
                                self.closed_pairs.append(pair)

                                # 更新统计
                                self.stats['successful_closes'] += 1
                                if profit >= 0:
                                    self.stats['total_profit'] += float(profit)
                                else:
                                    self.stats['total_loss'] += abs(float(profit))

                                self.logger.info(
                                    f"✅ [平仓完成] pair_id={pair.pair_id}, "
                                    f"盈亏: ${profit:.2f}, 持仓时间: {pair.holding_time:.0f}秒"
                                )
                else:
                    # 使用原有的P1-P5优先级系统（T075: 保留作为备用）
                    for pair in self.open_pairs[:]:  # 复制列表
                        # 检查是否应该平仓（多级优先级）
                        decision = self._should_close_position(
                            pair,
                            extended_bid,
                            extended_ask,
                            lighter_bid,
                            lighter_ask
                        )

                    if decision and decision.should_close:
                        self.logger.warning(
                            f"⚠️ [P{decision.priority}] 套利对 #{pair.pair_id} 触发平仓: {decision.reason}"
                        )
                        # T043: 记录平仓分析
                        if not self.trade_logger.log_close_analysis(pair, decision):
                            self.logger.warning("平仓分析记录失败，但交易继续")

                        # 使用市价平仓
                        await self._close_pair_with_market_price(
                            pair,
                            extended_bid,
                            extended_ask,
                            lighter_bid,
                            lighter_ask
                        )

                await asyncio.sleep(5)  # 每 5 秒检查一次

            except Exception as e:
                self.logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(5)

    async def _stats_reporter(self):
        """定期报告统计信息"""
        while not self.stop_flag:
            try:
                await asyncio.sleep(60)  # 每分钟报告一次

                self.logger.info("="*60)
                self.logger.info("📊 统计报告")
                self.logger.info(f"  持仓套利对: {len(self.open_pairs)}")
                self.logger.info(f"  已平仓套利对: {len(self.closed_pairs)}")
                self.logger.info(f"  总机会数: {self.stats['total_opportunities']}")
                self.logger.info(f"  成功开仓: {self.stats['successful_opens']}")
                self.logger.info(f"  失败开仓: {self.stats['failed_opens']}")
                self.logger.info(f"  成功平仓: {self.stats['successful_closes']}")
                self.logger.info(f"  总盈利: ${self.stats['total_profit']:.2f}")
                self.logger.info(f"  总亏损: ${self.stats['total_loss']:.2f}")
                net_pnl = self.stats['total_profit'] - self.stats['total_loss']
                self.logger.info(f"  净盈亏: ${net_pnl:.2f}")

                # T087-T088: 显示阈值相关统计
                if self.stats['threshold_rejections'] > 0:
                    self.logger.info(f"  阈值拒绝: {self.stats['threshold_rejections']} 次")
                if self.stats['threshold_violations'] > 0:
                    self.logger.warning(f"  阈值违规: {self.stats['threshold_violations']} 次")

                # 🆕 显示对冲失败率
                if len(self.hedge_attempts) >= 5:
                    _, failure_rate = self._check_hedge_failure_rate()
                    self.logger.info(f"  对冲失败率: {failure_rate:.2%} ({len(self.hedge_attempts)} 次尝试)")

                # P0: 显示安全监控状态（010-fix-position-imbalance）
                safety_state = self.safety_monitor.get_safety_state()
                circuit_level, reason = self.safety_monitor.check_circuit_breaker()

                self.logger.info(f"  🛡️ 安全监控:")
                self.logger.info(f"     熔断级别: {circuit_level} ({reason})")
                self.logger.info(
                    f"     对冲失败率: {safety_state.hedge_failure_rate:.2%} "
                    f"({safety_state.total_hedge_failures}/{safety_state.total_hedge_attempts})"
                )
                self.logger.info(
                    f"     仓位失衡率: {safety_state.position_imbalance_rate:.2%}"
                )
                if safety_state.is_paused:
                    self.logger.error(f"     ⚠️ 系统已暂停: {safety_state.pause_reason}")

                # 🔴 显示未对冲仓位警告
                if len(self.unhedged_positions) > 0:
                    self.logger.error(f"  ⚠️ 未对冲仓位: {len(self.unhedged_positions)} 个")
                    for pos in self.unhedged_positions:
                        self.logger.error(
                            f"     - {pos['side']} {pos['quantity']:.4f} @ {pos['price']:.2f} "
                            f"(订单ID: {pos['order_id']})"
                        )

                # T118: 显示maker订单统计
                maker_stats = self.order_manager.get_maker_stats()
                if maker_stats['attempts'] > 0:
                    self.logger.info("  Maker订单统计:")
                    self.logger.info(f"    尝试: {maker_stats['attempts']} 次")
                    self.logger.info(f"    成功: {maker_stats['successes']} 次")
                    self.logger.info(f"    被拒: {maker_stats['rejections']} 次")
                    self.logger.info(f"    转taker: {maker_stats['converts']} 次")
                    self.logger.info(f"    成功率: {maker_stats['success_rate']:.2%}")
                    if maker_stats['should_adjust_tick']:
                        self.logger.warning(f"    建议: price_tick可能需要调整")

                # T118: 显示交易分析报告
                if len(self.closed_pairs) > 0:
                    analysis = self.trade_analyzer.calculate_win_rate(self.closed_pairs)
                    if analysis['total_trades'] > 0:
                        self.logger.info("")
                        self.logger.info("📊 交易分析:")
                        self.logger.info(f"  胜率: {analysis['win_rate']:.2%}")
                        self.logger.info(f"  盈亏比: {analysis['profit_factor']:.2f}")
                        self.logger.info(f"  平均盈利: ${analysis['avg_profit']:.2f}")
                        self.logger.info(f"  平均亏损: ${analysis['avg_loss']:.2f}")

                # 001-fix-order-type: T058 - 显示成功率统计
                summary = self.success_tracker.get_stats_summary()
                if summary['open_attempts'] > 0 or summary['close_attempts'] > 0:
                    self.logger.info("")
                    self.logger.info("📊 成功率统计:")
                    if summary['open_attempts'] > 0:
                        self.logger.info(f"  开仓成功率: {summary['open_success_rate']:.2%} "
                                       f"({summary['open_successes']}/{summary['open_attempts']})")
                    if summary['close_attempts'] > 0:
                        self.logger.info(f"  平仓成功率: {summary['close_success_rate']:.2%} "
                                       f"({summary['close_successes']}/{summary['close_attempts']})")
                    if summary['failure_reasons']:
                        self.logger.info(f"  主要失败原因: {list(summary['failure_reasons'].keys())[0].value}")

                # T117: 定期导出交易数据
                if len(self.closed_pairs) > 0:
                    trades_file = self.data_collector.export_trades_csv(self.closed_pairs)
                    if trades_file:
                        self.logger.debug(f"  交易记录已导出: {trades_file}")
                    if self.collected_orders:
                        orders_file = self.data_collector.export_orders_csv(self.collected_orders)
                        if orders_file:
                            self.logger.debug(f"  订单记录已导出: {orders_file}")

                self.logger.info("="*60)
                
            except Exception as e:
                self.logger.error(f"统计报告错误: {e}")
    
    def _find_opposite_pair(self, opportunity: Dict[str, Any]) -> Optional[SpreadPair]:
        """
        查找反向持仓（已废弃 - T023）

        此方法已不再使用，因为平仓逻辑已改为基于市价和优先级条件。

        保留此方法仅用于向后兼容。建议使用 _check_close_conditions 替代。

        Args:
            opportunity: 套利机会字典

        Returns:
            Optional[SpreadPair]: 反向持仓或None
        """
        # 此方法已废弃，但保留接口以防外部调用
        for pair in self.open_pairs:
            if pair.should_close(opportunity):
                return pair
        return None

    def _check_close_conditions(
        self,
        pair: SpreadPair,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> Optional[CloseDecision]:
        """
        T028: 检查平仓条件（五级优先级）

        按优先级检查是否应该平仓：
        P1: 盈利目标平仓 - 未实现盈亏达到目标收益率
        P2: 时间小额平仓 - 持仓超时且有小额利润
        P3: 回本止损 - 持仓超时且亏损，等待回本后平仓
        P4: 强制平仓 - 持仓超过最大时间
        P5: 价差扩大延迟平仓 - 价差扩大时的延迟处理

        Args:
            pair: 套利对
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            CloseDecision对象，如果不平仓则返回None
        """
        # 1. 检查价差收敛
        is_converged, status_msg, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 2. 确定平仓价格
        if pair.extended_side == 'buy':
            close_extended_price = extended_bid
            close_lighter_price = lighter_ask
        else:
            close_extended_price = extended_ask
            close_lighter_price = lighter_bid

        # 3. 计算未实现盈亏
        unrealized_pnl = pair.calculate_unrealized_pnl(
            close_extended_price, close_lighter_price
        )

        # 计算盈亏率
        investment = pair.extended_quantity * pair.extended_price
        pnl_rate = unrealized_pnl / investment if investment > 0 else Decimal('0')

        # 持仓时间
        holding_time = pair.holding_time

        # ===== Priority 1: 盈利目标平仓 =====
        if self.config.enable_profit_target:
            profit_target = investment * self.config.profit_target_rate
            if unrealized_pnl >= profit_target:
                return self._create_close_decision(
                    pair=pair,
                    should_close=True,
                    priority=1,
                    reason=f"盈利目标达标 (PnL=${unrealized_pnl:.2f} >= ${profit_target:.2f})",
                    reason_code="P1_CONVERGE_PROFIT",
                    spread_change=spread_change,
                    unrealized_pnl=unrealized_pnl,
                    pnl_rate=pnl_rate,
                    holding_time=holding_time,
                    extended_close_price=close_extended_price,
                    lighter_close_price=close_lighter_price,
                    is_warning=False
                )

        # ===== Priority 2: 时间小额平仓 =====
        if holding_time > self.config.time_close_threshold:
            if unrealized_pnl > 0:
                return self._create_close_decision(
                    pair=pair,
                    should_close=True,
                    priority=2,
                    reason=f"时间小额平仓 (持仓{holding_time:.0f}秒, PnL=${unrealized_pnl:.2f})",
                    reason_code="P2_TIME_SMALL_PROFIT",
                    spread_change=spread_change,
                    unrealized_pnl=unrealized_pnl,
                    pnl_rate=pnl_rate,
                    holding_time=holding_time,
                    extended_close_price=close_extended_price,
                    lighter_close_price=close_lighter_price,
                    is_warning=False
                )

        # ===== Priority 3: 回本止损 =====
        if holding_time > self.config.time_close_threshold:
            if unrealized_pnl < 0:
                # 检查是否接近回本
                if unrealized_pnl >= 0:
                    return self._create_close_decision(
                        pair=pair,
                        should_close=True,
                        priority=3,
                        reason=f"回本止损 (持仓{holding_time:.0f}秒, PnL=${unrealized_pnl:.2f})",
                        reason_code="P3_BREAK_EVEN",
                        spread_change=spread_change,
                        unrealized_pnl=unrealized_pnl,
                        pnl_rate=pnl_rate,
                        holding_time=holding_time,
                        extended_close_price=close_extended_price,
                        lighter_close_price=close_lighter_price,
                        is_warning=False
                    )
                # 否则继续等待
                self.logger.debug(
                    f"套利对 #{pair.pair_id} 持仓{holding_time:.0f}秒, "
                    f"PnL=${unrealized_pnl:.2f}, 等待回本"
                )

        # ===== Priority 4: 强制平仓 =====
        if holding_time > self.config.max_holding_time:
            return self._create_close_decision(
                pair=pair,
                should_close=True,
                priority=4,
                reason=f"强制平仓 (持仓{holding_time:.0f}秒 > {self.config.max_holding_time}秒, PnL=${unrealized_pnl:.2f})",
                reason_code="P4_FORCE_CLOSE",
                spread_change=spread_change,
                unrealized_pnl=unrealized_pnl,
                pnl_rate=pnl_rate,
                holding_time=holding_time,
                extended_close_price=close_extended_price,
                lighter_close_price=close_lighter_price,
                is_warning=True
            )

        # ===== Priority 5: 价差扩大延迟平仓 =====
        if not is_converged:
            # 价差扩大，根据配置决定是否延迟平仓
            if self.config.enable_delay_on_divergence:
                self.logger.debug(
                    f"套利对 #{pair.pair_id} 价差扩大，延迟平仓: {status_msg}"
                )
                # 返回不平仓的决策，但标记为警告
                return None
            else:
                # 不延迟，立即平仓
                return self._create_close_decision(
                    pair=pair,
                    should_close=True,
                    priority=5,
                    reason=f"价差扩大平仓: {status_msg}",
                    reason_code="P5_DIVERGENCE_CLOSE",
                    spread_change=spread_change,
                    unrealized_pnl=unrealized_pnl,
                    pnl_rate=pnl_rate,
                    holding_time=holding_time,
                    extended_close_price=close_extended_price,
                    lighter_close_price=close_lighter_price,
                    is_warning=True
                )

        # 不满足任何平仓条件
        return None

    def _create_close_decision(
        self,
        pair: SpreadPair,
        should_close: bool,
        priority: int,
        reason: str,
        reason_code: str,
        spread_change: SpreadChange,
        unrealized_pnl: Decimal,
        pnl_rate: Decimal,
        holding_time: float,
        extended_close_price: Decimal,
        lighter_close_price: Decimal,
        is_warning: bool
    ) -> CloseDecision:
        """
        T029: 创建CloseDecision对象（辅助函数）

        Args:
            pair: 套利对
            should_close: 是否应该平仓
            priority: 优先级(1-5)
            reason: 决策理由
            reason_code: 理由代码
            spread_change: 价差变化
            unrealized_pnl: 未实现盈亏
            pnl_rate: 盈亏率
            holding_time: 持仓时间
            extended_close_price: Extended平仓价格
            lighter_close_price: Lighter平仓价格
            is_warning: 是否为警告平仓

        Returns:
            CloseDecision对象
        """
        return CloseDecision(
            pair_id=pair.pair_id,
            should_close=should_close,
            priority=priority,
            reason=reason,
            reason_code=reason_code,
            spread_change=spread_change,
            unrealized_pnl=unrealized_pnl,
            pnl_rate=pnl_rate,
            holding_time=holding_time,
            is_warning=is_warning,
            timestamp=time.time(),
            extended_close_price=extended_close_price,
            lighter_close_price=lighter_close_price
        )
    
    async def _open_new_pair(
        self,
        opportunity: Dict[str, Any],
        ext_ts: Optional[float] = None,
        lit_ts: Optional[float] = None,
        freshness_results: Optional[List[DataFreshnessResult]] = None
    ) -> bool:
        """开新的套利对

        Args:
            opportunity: 机会字典
            ext_ts: Extended数据时间戳
            lit_ts: Lighter数据时间戳
            freshness_results: 数据新鲜度检查结果
        """
        # T084: 获取信号时间戳
        signal_ts = self.performance_monitor.get_latency('signal', 'data_A')
        if signal_ts is None:
            signal_ts = 0  # 使用时间戳记录中的值

        # T084: 记录计算时间戳
        self.performance_monitor.record_timestamp('calc')

        try:
            # P0: 安全检查（010-fix-position-imbalance）
            if self.safety_monitor.should_pause_opening():
                self.logger.warning(
                    f"安全监控器禁止开仓: {self.safety_monitor.state.pause_reason}"
                )
                self.stats['opportunities_rejected'] += 1
                return False

            circuit_level, reason = self.safety_monitor.check_circuit_breaker()
            if circuit_level >= 2:
                self.logger.warning(
                    f"熔断器级别{circuit_level}禁止开仓: {reason}"
                )
                self.stats['opportunities_rejected'] += 1
                return False

            self.logger.info(f"开仓套利对...")
            self.logger.info(
                f"[DEBUG] 机会详情: type={opportunity['type']}, "
                f"side={opportunity['side']}, "
                f"extended_price={opportunity['extended_price']}, "
                f"lighter_price={opportunity['lighter_price']}, "
                f"quantity={opportunity['quantity']:.6f}"
            )

            # 001-fix-order-type: T048 - 记录开仓机会检测
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.OPEN_ATTEMPT,
                status=OperationStatus.PENDING,
                exchange=ExchangeType.BOTH,
                quantity=opportunity.get('quantity'),
                spread_rate=opportunity.get('spread_rate')
            ))

            # 获取当前价格（用于T042价差快照）
            extended_bid = max(self.extended_orderbook['bids'].keys()) if self.extended_orderbook['bids'] else Decimal('0')
            extended_ask = min(self.extended_orderbook['asks'].keys()) if self.extended_orderbook['asks'] else Decimal('999999')
            lighter_bid = max(self.lighter_orderbook['bids'].keys()) if self.lighter_orderbook['bids'] else Decimal('0')
            lighter_ask = min(self.lighter_orderbook['asks'].keys()) if self.lighter_orderbook['asks'] else Decimal('999999')

            # 🆕 预检查：验证Lighter是否有足够的流动性和条件
            hedge_side = 'sell' if opportunity['side'] == 'buy' else 'buy'

            self.logger.info(f"[预检查] 检查Lighter对冲条件...")

            # 检查Lighter订单簿深度
            lighter_depth_value = self.calculator.check_lighter_depth_value(
                lighter_orderbook=self.lighter_orderbook,
                side=hedge_side
            )

            if lighter_depth_value < self.config.min_lighter_depth_usdt:
                self.logger.warning(
                    f"❌ 预检查失败: Lighter深度不足 "
                    f"(${lighter_depth_value:.2f} < ${self.config.min_lighter_depth_usdt})"
                )
                self.stats['opportunities_rejected'] += 1
                return False

            # 检查具体的安全数量
            is_sufficient, safe_quantity, avg_price = self.calculator.calculate_max_safe_quantity(
                lighter_orderbook=self.lighter_orderbook,
                side=hedge_side,
                target_quantity=opportunity['quantity']
            )

            if not is_sufficient:
                self.logger.warning(
                    f"❌ 预检查失败: Lighter深度不足以执行完整对冲 "
                    f"(需要{opportunity['quantity']:.4f}, 安全{safe_quantity:.4f})"
                )
                self.stats['opportunities_rejected'] += 1
                return False

            self.logger.info(
                f"✅ 预检查通过: Lighter深度=${lighter_depth_value:.2f}, "
                f"可对冲{safe_quantity:.4f} @ ${avg_price:.2f}"
            )

            # ========================================================================
            # 001-fix-order-type: 强制使用taker订单，禁用maker逻辑
            # ========================================================================
            use_maker = False  # 强制使用taker订单

            # 使用对手价作为taker订单价格
            if opportunity['side'] == 'buy':
                extended_price = extended_ask  # 买单使用ask价格（对手价）
            else:
                extended_price = extended_bid  # 卖单使用bid价格（对手价）

            self.logger.info(f"[001-fix-order-type] 使用Taker订单: side={opportunity['side']}, price=${extended_price:.4f}")

            # ========================================================================
            # 012-dual-leg-concurrency: 双腿并发下单（使用IOC订单）
            # ========================================================================
            if self.config.enable_dual_leg_concurrent:
                return await self._open_new_pair_concurrent(
                    opportunity=opportunity,
                    extended_orderbook={'bid': extended_bid, 'ask': extended_ask},
                    lighter_orderbook={'bid': lighter_bid, 'ask': lighter_ask},
                    ext_ts=ext_ts,
                    lit_ts=lit_ts,
                    freshness_results=freshness_results
                )

            # ========== 以下是原有的串行执行逻辑（保留兼容性） ==========
            # T084: 记录Extended发送时间戳
            self.performance_monitor.record_timestamp('send_A')

            # 1. Extended 下单（强制post_only=False使用taker）
            order = await self.order_manager.place_spread_maker_order(
                side=opportunity['side'],
                price=extended_price,
                quantity=opportunity['quantity'],
                post_only=False  # 001-fix-order-type: 强制taker订单
            )

            # T084: 记录Extended ACK时间戳（订单ID返回即视为ACK）
            self.performance_monitor.record_timestamp('ack_A')

            self.logger.info(f"[DEBUG] 下单返回: success={order['success']}, order_id={order.get('order_id')}")

            if not order['success']:
                self.stats['failed_opens'] += 1
                self.consecutive_failures += 1
                return False

            # ========================================================================
            # 001-fix-order-type: 简化taker订单等待逻辑（移除maker超时转换）
            # ========================================================================
            # taker订单直接等待成交
            fill_result = await self.order_manager.wait_for_fill(
                order_id=order['order_id'],
                timeout=self.config.extended_fill_timeout,
                allow_partial=self.config.enable_partial_fill
            )

            if fill_result['status'] == 'TIMEOUT' and fill_result['filled_quantity'] == 0:
                # 完全未成交,取消订单
                await self.order_manager.cancel_order(order['order_id'])
                self.stats['failed_opens'] += 1
                self.consecutive_failures += 1
                return False

            if fill_result['filled_quantity'] == 0:
                self.stats['failed_opens'] += 1
                self.consecutive_failures += 1
                return False

            # T084: 记录Lighter发送时间戳
            self.performance_monitor.record_timestamp('send_B')

            # 3. 执行对冲
            hedge_side = 'sell' if opportunity['side'] == 'buy' else 'buy'
            hedge_result = await self.hedge_manager.execute_hedge(
                side=hedge_side,
                quantity=fill_result['filled_quantity'],
                expected_price=opportunity['lighter_price']
            )

            # T084: 记录Lighter ACK时间戳
            self.performance_monitor.record_timestamp('ack_B')

            # P0: 记录对冲尝试结果到安全监控器（010-fix-position-imbalance）
            await self.safety_monitor.record_hedge_attempt(
                success=hedge_result['success'],
                failure_reason=hedge_result.get('error')
            )

            # 保留旧的对冲记录方法以保持兼容性
            self._record_hedge_attempt(hedge_result['success'])

            if not hedge_result['success']:
                self.stats['failed_opens'] += 1
                self.consecutive_failures += 1

                # 🔴 关键修复：记录未对冲的Extended仓位
                unhedged_position = {
                    'pair_id': self.next_pair_id,
                    'order_id': order['order_id'],
                    'side': opportunity['side'],
                    'quantity': fill_result['filled_quantity'],
                    'price': fill_result['filled_price'],
                    'expected_price': opportunity['lighter_price'],  # 预期的对冲价格
                    'timestamp': time.time(),
                    'error': hedge_result.get('error', 'Unknown')
                }
                self.unhedged_positions.append(unhedged_position)

                # 记录未对冲仓位到交易日志文件
                if not self.trade_logger.log_unhedged_position(unhedged_position):
                    self.logger.warning(f"交易日志记录失败 (未对冲仓位)，但交易继续")

                self.logger.error(
                    f"❌ 对冲失败! Extended单边仓位累积!\n"
                    f"   订单ID: {order['order_id']}\n"
                    f"   方向: {opportunity['side']}\n"
                    f"   数量: {fill_result['filled_quantity']:.4f} @ {fill_result['filled_price']:.2f}\n"
                    f"   错误: {hedge_result.get('error', 'Unknown')}\n"
                    f"   未对冲仓位总数: {len(self.unhedged_positions)}"
                )

                # 001-fix-order-type: T052 - 记录对冲失败（Lighter端）
                error_msg = hedge_result.get('error', 'Unknown')
                failure_reason = FailureReason.NETWORK_TIMEOUT  # 默认网络超时
                if 'insufficient' in error_msg.lower() or 'balance' in error_msg.lower():
                    failure_reason = FailureReason.INSUFFICIENT_BALANCE
                elif 'rejected' in error_msg.lower():
                    failure_reason = FailureReason.ORDER_REJECTED

                self.success_tracker.record_operation(SpreadOperationResult(
                    timestamp=time.time(),
                    operation_type=OperationType.OPEN_FAILED,
                    status=OperationStatus.FAILED,
                    exchange=ExchangeType.LIGHTER,
                    failure_reason=failure_reason,
                    error_message=error_msg
                ))

                # 🔴 触发紧急熔断：立即暂停，防止继续开仓
                self.is_paused = True
                self.pause_until = time.time() + 3600  # 暂停1小时
                self.logger.error(
                    f"🚨 触发紧急熔断! 检测到未对冲仓位，暂停交易1小时!\n"
                    f"   请手动检查并平仓未对冲的Extended仓位!"
                )

                return False
            
            # 4. 创建套利对 (新增订单ID记录)
            pair = SpreadPair(
                pair_id=self.next_pair_id,
                extended_side=opportunity['side'],
                extended_price=fill_result['filled_price'],
                extended_quantity=fill_result['filled_quantity'],
                lighter_price=hedge_result['filled_price'],
                lighter_quantity=hedge_result['filled_quantity'],
                extended_order_id=order['order_id'],
                lighter_order_id=hedge_result.get('order_id')  # T040: 记录 Lighter 开仓订单ID
            )

            # ========================================================================
            # 001-fix-order-type: 验证仓位一致性
            # ========================================================================
            if self.config.enable_position_consistency_check:
                check_result = await self.validate_position_consistency(pair)

                # 如果仓位不一致，记录警告并继续（暂不强制清理）
                if not check_result.is_consistent:
                    self.logger.warning(
                        f"[001-fix-order-type] 开仓后仓位不一致！\n"
                        f"   套利对ID: {pair.pair_id}\n"
                        f"   Extended: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}\n"
                        f"   Lighter: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}\n"
                        f"   差异: {check_result.difference:.4f} ({check_result.difference_rate:.2%})\n"
                        f"   阈值: 数量<{self.config.position_consistency_threshold}, "
                        f"比率<{self.config.position_consistency_rate_threshold:.0%}"
                    )
                    # TODO: 可以在这里添加自动清理逻辑（T036）
                    # 暂时仅记录警告，不强制清理

            self.next_pair_id += 1
            self.open_pairs.append(pair)

            # 更新统计
            self.stats['successful_opens'] += 1
            self.stats['opportunities_taken'] += 1
            self.stats['max_open_pairs'] = max(self.stats['max_open_pairs'], len(self.open_pairs))
            self.consecutive_failures = 0

            # 001-fix-order-type: T051 - 记录开仓成功
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH,
                order_id=pair.open_extended_order_id,
                quantity=pair.extended_quantity,
                price=pair.extended_price,
                pair_id=pair.pair_id,
                spread_rate=pair.open_spread_rate
            ))

            # T085: 创建TradeOperationRecord用于CSV导出
            timestamps = self.performance_monitor._timestamps
            decision_record = TradeOperationRecord(
                timestamp=time.time(),
                operation_type='OPEN',
                exchange='BOTH',
                signal_ts=timestamps.get('signal'),
                data_ts_A=ext_ts,
                data_ts_B=lit_ts,
                calc_ts=timestamps.get('calc'),
                send_A_ts=timestamps.get('send_A'),
                send_B_ts=timestamps.get('send_B'),
                ack_A_ts=timestamps.get('ack_A'),
                ack_B_ts=timestamps.get('ack_B'),
                spread_rate=opportunity.get('spread_rate'),
                decision='ALLOWED',
                status='SUCCESS',
            )
            self.performance_monitor.record_decision(decision_record)

            # T041: 增强开仓日志 (包含交易所、方向、价格、数量、时间戳、订单ID)
            self.logger.info(
                f"✅ 开仓成功! 套利对 #{pair.pair_id}\n"
                f"   方向: {pair.extended_side.upper()}\n"
                f"   数量: {pair.extended_quantity:.4f}\n"
                f"   Extended: 价格@${pair.extended_price:.2f} (订单ID: {pair.open_extended_order_id})\n"
                f"   Lighter: 价格@${pair.lighter_price:.2f} (订单ID: {pair.open_lighter_order_id})\n"
                f"   开仓价差: ${pair.open_spread:.2f} ({pair.open_spread_rate:.4%})\n"
                f"   时间戳: {pair.open_time:.2f}"
            )

            # 记录到交易日志文件
            if not self.trade_logger.log_opening_trade(pair):
                self.logger.warning(f"交易日志记录失败 (开仓) - 套利对 #{pair.pair_id}，但交易继续")

            # T042: 记录开仓时的价差快照
            spread_snapshot = SpreadSnapshot(
                timestamp=time.time(),
                extended_bid=extended_bid,
                extended_ask=extended_ask,
                extended_mid=(extended_bid + extended_ask) / Decimal('2'),
                lighter_bid=lighter_bid,
                lighter_ask=lighter_ask,
                lighter_mid=(lighter_bid + lighter_ask) / Decimal('2'),
                spread=pair.open_spread,
                spread_rate=pair.open_spread_rate,
                spread_sign="positive" if pair.open_spread > 0 else "negative" if pair.open_spread < 0 else "zero",
                arbitrage_direction="long_spread" if pair.extended_side == 'buy' else "short_spread"
            )
            if not self.trade_logger.log_spread_snapshot(spread_snapshot):
                self.logger.warning(f"价差快照记录失败 - 套利对 #{pair.pair_id}，但交易继续")

            return True
            
        except Exception as e:
            self.logger.error(f"开仓失败: {e}")
            self.logger.error(traceback.format_exc())
            self.stats['failed_opens'] += 1
            self.consecutive_failures += 1

            # 001-fix-order-type: T052 - 记录开仓失败
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.OPEN_FAILED,
                status=OperationStatus.FAILED,
                exchange=ExchangeType.BOTH,
                failure_reason=FailureReason.UNKNOWN_ERROR,
                error_message=str(e)
            ))

            # 触发断路器
            if self.consecutive_failures >= self.config.max_consecutive_failures:
                self._trigger_circuit_breaker()

            return False

    # ========================================================================
    # 012-dual-leg-concurrency: 双腿并发下单实现（User Story 1）
    # ========================================================================
    async def _open_new_pair_concurrent(
        self,
        opportunity: Dict[str, Any],
        extended_orderbook: Dict[str, Decimal],
        lighter_orderbook: Dict[str, Decimal],
        ext_ts: Optional[float] = None,
        lit_ts: Optional[float] = None,
        freshness_results: Optional[List[DataFreshnessResult]] = None
    ) -> bool:
        """使用双腿并发下单开新套利对（T018-T022）

        特性:
        - 使用asyncio.gather同时发送两个订单（<5ms时间差）
        - 使用IOC订单（立即成交或取消，无需等待）
        - 完整的性能日志记录

        Args:
            opportunity: 机会字典
            extended_orderbook: Extended订单簿 {'bid': Decimal, 'ask': Decimal}
            lighter_orderbook: Lighter订单簿 {'bid': Decimal, 'ask': Decimal}
            ext_ts: Extended数据时间戳
            lit_ts: Lighter数据时间戳
            freshness_results: 数据新鲜度检查结果

        Returns:
            bool: 是否成功开仓
        """
        # T084: 记录信号和计算时间戳
        signal_ts = self.performance_monitor.get_latency('signal', 'data_A')
        if signal_ts is None:
            signal_ts = 0
        self.performance_monitor.record_timestamp('calc')

        try:
            # 安全检查
            if self.safety_monitor.should_pause_opening():
                self.logger.warning(
                    f"安全监控器禁止开仓: {self.safety_monitor.state.pause_reason}"
                )
                self.stats['opportunities_rejected'] += 1
                return False

            # 记录开仓机会检测
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.OPEN_ATTEMPT,
                status=OperationStatus.PENDING,
                exchange=ExchangeType.BOTH,
                quantity=opportunity.get('quantity'),
                spread_rate=opportunity.get('spread_rate')
            ))

            self.logger.info(
                f"[双腿并发] 准备开仓: side={opportunity['side']}, "
                f"quantity={opportunity['quantity']:.6f}"
            )

            # T056-T058: 增强利润风控检查（User Story 4）
            if self.config.enable_enhanced_profit_check:
                profit_check = self.risk_validator.validate_profitability(
                    spread_rate=opportunity.get('spread_rate', Decimal('0'))
                )

                if not profit_check.is_profitable:
                    # T057: 利润不足拒绝日志
                    self.logger.warning(
                        f"⚠️ [利润不足] 拒绝开仓 | "
                        f"价差率: {profit_check.spread_rate:.4%} | "
                        f"净利: {profit_check.net_profit_rate:.4%} | "
                        f"最小净利: {profit_check.min_net_profit:.4%}"
                    )
                    self.stats['opportunities_rejected'] += 1
                    return False

                self.logger.info(
                    f"✅ [利润检查] 通过 | 净利: {profit_check.net_profit_rate:.4%}"
                )

            # T018: 创建双腿IOC订单
            extended_order, lighter_order = self.ioc_order_manager.create_dual_leg_orders(
                opportunity=opportunity,
                extended_orderbook=extended_orderbook,
                lighter_orderbook=lighter_orderbook
            )

            # T019: 并发执行双腿订单
            concurrent_result = await self.concurrent_executor.execute_dual_leg_orders(
                extended_order=extended_order,
                lighter_order=lighter_order,
                opportunity=opportunity
            )

            # T021: 性能日志 - 发送时间差
            if concurrent_result.send_gap_ms > 5:
                self.logger.warning(
                    f"⚠️ [并发性能] 发送时间差过大: {concurrent_result.send_gap_ms:.2f}ms (目标<5ms)"
                )
            else:
                self.logger.info(
                    f"✅ [并发性能] 发送时间差: {concurrent_result.send_gap_ms:.2f}ms"
                )

            # T022: 性能日志 - 总执行时间
            if concurrent_result.total_latency_ms > 500:
                self.logger.warning(
                    f"⚠️ [并发性能] 总执行时间过长: {concurrent_result.total_latency_ms:.2f}ms (目标<500ms)"
                )
            else:
                self.logger.info(
                    f"✅ [并发性能] 总执行时间: {concurrent_result.total_latency_ms:.2f}ms"
                )

            # 处理执行结果
            if concurrent_result.is_both_failed:
                # 双边失败
                self.stats['failed_opens'] += 1
                self.consecutive_failures += 1
                self.logger.error(
                    f"❌ [双边失败] Extended: {concurrent_result.extended_error}, "
                    f"Lighter: {concurrent_result.lighter_error}"
                )
                self.success_tracker.record_operation(SpreadOperationResult(
                    timestamp=time.time(),
                    operation_type=OperationType.OPEN_FAILED,
                    status=OperationStatus.FAILED,
                    exchange=ExchangeType.BOTH,
                    failure_reason=FailureReason.NETWORK_TIMEOUT,
                    error_message=f"双边失败: {concurrent_result.extended_error}, {concurrent_result.lighter_error}"
                ))
                return False

            if concurrent_result.is_legging:
                # 单腿持仓 - 触发紧急回滚（User Story 3: T045-T048）
                legging_side = 'extended' if concurrent_result.extended_success else 'lighter'
                self.logger.error(
                    f"🚨 [单腿持仓] {legging_side}成交，触发紧急回滚！"
                )

                if self.leg_rollback_handler is not None:
                    # 检测单腿持仓
                    is_legging = self.leg_rollback_handler.detect_legging(concurrent_result)

                    if is_legging:
                        # 执行紧急平仓
                        rollback_event = await self.leg_rollback_handler.execute_emergency_close(
                            result=concurrent_result,
                            pair_id=self.next_pair_id
                        )

                        # 存储回滚事件记录
                        self.logger.warning(
                            f"🔄 [回滚完成] pair_id={self.next_pair_id}, "
                            f"latency={rollback_event.rollback_latency_ms:.2f}ms, "
                            f"success={rollback_event.rollback_success}"
                        )

                        # 记录回滚事件到成功率追踪器
                        if rollback_event.rollback_success:
                            self.success_tracker.record_operation(SpreadOperationResult(
                                timestamp=time.time(),
                                operation_type=OperationType.OPEN_FAILED,
                                status=OperationStatus.FAILED,
                                exchange=ExchangeType.BOTH,
                                failure_reason=FailureReason.POSITION_IMBALANCE,
                                error_message=f"单腿持仓已回滚: {legging_side}"
                            ))
                        else:
                            self.success_tracker.record_operation(SpreadOperationResult(
                                timestamp=time.time(),
                                operation_type=OperationType.OPEN_FAILED,
                                status=OperationStatus.FAILED,
                                exchange=ExchangeType.BOTH,
                                failure_reason=FailureReason.UNKNOWN_ERROR,
                                error_message=f"单腿持仓回滚失败: {rollback_event.rollback_error}"
                            ))

                self.stats['failed_opens'] += 1
                return False

            # 双腿成交成功
            pair = SpreadPair(
                pair_id=self.next_pair_id,
                extended_side=opportunity['side'],
                extended_price=concurrent_result.extended_filled_price,
                extended_quantity=concurrent_result.extended_filled_qty,
                lighter_price=concurrent_result.lighter_filled_price,
                lighter_quantity=concurrent_result.lighter_filled_qty,
                extended_order_id=concurrent_result.extended_order_id,
                lighter_order_id=concurrent_result.lighter_order_id
            )

            # 存储并发执行结果（用于后续分析）
            pair.concurrent_result = concurrent_result
            pair.order_type = "IOC"

            # 验证仓位一致性
            if self.config.enable_position_consistency_check:
                check_result = await self.validate_position_consistency(pair)
                if not check_result.is_consistent:
                    self.logger.warning(
                        f"[双腿并发] 开仓后仓位不一致！\n"
                        f"   套利对ID: {pair.pair_id}\n"
                        f"   Extended: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}\n"
                        f"   Lighter: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}\n"
                        f"   差异: {check_result.difference:.4f} ({check_result.difference_rate:.2%})"
                    )

            self.next_pair_id += 1
            self.open_pairs.append(pair)

            # 更新统计
            self.stats['successful_opens'] += 1
            self.stats['opportunities_taken'] += 1
            self.stats['max_open_pairs'] = max(self.stats['max_open_pairs'], len(self.open_pairs))
            self.consecutive_failures = 0

            # 记录开仓成功
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.OPEN_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH,
                order_id=pair.open_extended_order_id,
                quantity=pair.extended_quantity,
                price=pair.extended_price,
                pair_id=pair.pair_id,
                spread_rate=pair.open_spread_rate
            ))

            # 创建TradeOperationRecord用于CSV导出
            timestamps = self.performance_monitor._timestamps
            decision_record = TradeOperationRecord(
                timestamp=time.time(),
                operation_type='OPEN',
                exchange='BOTH',
                signal_ts=timestamps.get('signal'),
                data_ts_A=ext_ts,
                data_ts_B=lit_ts,
                calc_ts=timestamps.get('calc'),
                send_A_ts=concurrent_result.send_a_ts,
                send_B_ts=concurrent_result.send_b_ts,
                spread_rate=opportunity.get('spread_rate'),
                decision='ALLOWED',
                status='SUCCESS',
                send_gap_ms=concurrent_result.send_gap_ms
            )
            self.performance_monitor.record_decision(decision_record)

            # 增强开仓日志
            self.logger.info(
                f"✅ [双腿并发] 开仓成功! 套利对 #{pair.pair_id}\n"
                f"   方向: {pair.extended_side.upper()}\n"
                f"   数量: {pair.extended_quantity:.4f}\n"
                f"   Extended: 价格@${pair.extended_price:.2f} (订单ID: {pair.open_extended_order_id})\n"
                f"   Lighter: 价格@${pair.lighter_price:.2f} (订单ID: {pair.open_lighter_order_id})\n"
                f"   开仓价差: ${pair.open_spread:.2f} ({pair.open_spread_rate:.4%})\n"
                f"   发送间隔: {concurrent_result.send_gap_ms:.2f}ms\n"
                f"   总延迟: {concurrent_result.total_latency_ms:.2f}ms"
            )

            # 记录到交易日志
            if not self.trade_logger.log_opening_trade(pair):
                self.logger.warning(f"交易日志记录失败 (开仓) - 套利对 #{pair.pair_id}")

            return True

        except Exception as e:
            self.logger.error(f"[双腿并发] 开仓失败: {e}")
            self.logger.error(traceback.format_exc())
            self.stats['failed_opens'] += 1
            self.consecutive_failures += 1
            return False

    async def _close_pair(self, pair: SpreadPair, opportunity: Dict[str, Any]) -> bool:
        """平仓套利对"""
        try:
            self.logger.info(f"平仓套利对 #{pair.pair_id}...")
            
            # 1. Extended 平仓
            close_side = 'sell' if pair.extended_side == 'buy' else 'buy'
            close_order = await self.order_manager.place_spread_maker_order(
                side=close_side,
                price=opportunity['extended_price'],
                quantity=pair.extended_quantity
            )
            
            if not close_order['success']:
                self.stats['failed_closes'] += 1
                return False
            
            # 2. 等待成交
            fill_result = await self.order_manager.wait_for_fill(
                order_id=close_order['order_id'],
                timeout=self.config.extended_fill_timeout,
                allow_partial=False  # 平仓不允许部分成交
            )
            
            if fill_result['status'] != 'FILLED':
                # 取消订单
                await self.order_manager.cancel_order(close_order['order_id'])
                self.stats['failed_closes'] += 1
                return False
            
            # 3. Lighter 平仓对冲
            hedge_side = 'buy' if pair.extended_side == 'buy' else 'sell'
            hedge_result = await self.hedge_manager.execute_hedge(
                side=hedge_side,
                quantity=pair.lighter_quantity,
                expected_price=opportunity['lighter_price']
            )

            if not hedge_result['success']:
                self.stats['failed_closes'] += 1
                self.logger.error("❌ 平仓对冲失败!存在未平仓风险!")
                return False

            # T042-T043: 记录平仓订单ID
            pair.close_extended_order_id = close_order['order_id']
            pair.close_lighter_order_id = hedge_result.get('order_id')

            # 4. 计算盈亏
            profit = pair.close(
                close_extended_price=fill_result['filled_price'],
                close_lighter_price=hedge_result['filled_price']
            )

            # T044-T045: 增强平仓日志和平仓总结
            self.logger.info(
                f"💰 平仓成功! 套利对 #{pair.pair_id}\n"
                f"   盈亏: ${profit:.2f} ({(profit/(pair.extended_quantity*pair.extended_price))*100:.2f}%)\n"
                f"   持仓时间: {pair.holding_time:.0f}秒\n"
                f"   Extended平仓: 价格@${pair.close_extended_price:.2f} (订单ID: {pair.close_extended_order_id})\n"
                f"   Lighter平仓: 价格@${pair.close_lighter_price:.2f} (订单ID: {pair.close_lighter_order_id})"
            )

            # T045: 输出交易对总结
            self.logger.info(
                f"📊 交易对 #{pair.pair_id} 总结:\n"
                f"   开仓: Extended@${pair.extended_price:.2f} → Lighter@${pair.lighter_price:.2f}\n"
                f"   平仓: Extended@${pair.close_extended_price:.2f} → Lighter@${pair.close_lighter_price:.2f}\n"
                f"   收益率: {(profit/(pair.extended_quantity*pair.extended_price))*100:.2f}%"
            )

            # 记录到交易日志文件
            if not self.trade_logger.log_closing_trade(pair):
                self.logger.warning(f"交易日志记录失败 (平仓) - 套利对 #{pair.pair_id}，但交易继续")

            # 5. 更新统计
            self.stats['successful_closes'] += 1
            if profit > 0:
                self.stats['total_profit'] += profit
            else:
                self.stats['total_loss'] += abs(profit)

            # 6. 从持仓列表移除
            self.open_pairs.remove(pair)
            self.closed_pairs.append(pair)
            
            return True
            
        except Exception as e:
            self.logger.error(f"平仓失败: {e}")
            self.logger.error(traceback.format_exc())
            self.stats['failed_closes'] += 1
            return False

    # ==================== T071-T076: 平仓决策辅助方法 ====================

    def _calculate_close_pnl(
        self,
        pair: SpreadPair,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> Decimal:
        """
        T071: 计算平仓时的盈亏（使用真实价差）

        Args:
            pair: 套利对
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            Decimal: 平仓盈亏
        """
        # 确定平仓价格（对手价）
        if pair.extended_side == 'buy':
            close_extended = extended_bid
            close_lighter = lighter_ask
        else:
            close_extended = extended_ask
            close_lighter = lighter_bid

        # 计算盈亏
        if pair.extended_side == 'buy':
            extended_pnl = (close_extended - pair.extended_price) * pair.extended_quantity
            lighter_pnl = (pair.lighter_price - close_lighter) * pair.lighter_quantity
        else:
            extended_pnl = (pair.extended_price - close_extended) * pair.extended_quantity
            lighter_pnl = (close_lighter - pair.lighter_price) * pair.lighter_quantity

        return extended_pnl + lighter_pnl

    def _is_spread_diverging(
        self,
        pair: SpreadPair,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> bool:
        """
        T072: 判断价差是否扩大（不利方向）

        Args:
            pair: 套利对
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            bool: True=价差扩大（不利）, False=价差收敛（有利）
        """
        # 检查价差收敛
        is_converged, status_msg, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 如果未收敛，说明价差在扩大（不利）
        return not is_converged

    def _should_close_position(
        self,
        pair: SpreadPair,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> Optional[CloseDecision]:
        """
        T073: 判断是否应该平仓（多级优先级）

        P1: 盈利目标平仓 - 未实现盈亏达到目标收益率
        P2: 时间小额平仓 - 持仓超时且有小额利润
        P3: 回本止损 - 持仓超时且亏损，等待回本后平仓
        P4: 强制平仓 - 持仓超过最大时间
        P5: 价差扩大延迟平仓 - 价差扩大时的延迟处理

        Args:
            pair: 套利对
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            CloseDecision对象，如果不平仓则返回None
        """
        # 计算当前盈亏
        unrealized_pnl = self._calculate_close_pnl(
            pair, extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 计算盈亏率
        investment = pair.extended_quantity * pair.extended_price
        pnl_rate = unrealized_pnl / investment if investment > 0 else Decimal('0')

        # 检查价差收敛
        is_converged, status_msg, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 持仓时间
        holding_time = pair.holding_time

        # P1: 盈利目标平仓
        if self.config.enable_profit_target and pnl_rate >= self.config.profit_target_rate:
            return CloseDecision(
                pair_id=pair.pair_id,
                should_close=True,
                priority=1,
                reason=f"达到盈利目标: {pnl_rate:.4%} >= {self.config.profit_target_rate:.4%}",
                reason_code="PROFIT_TARGET",
                spread_change=spread_change,
                unrealized_pnl=unrealized_pnl,
                pnl_rate=pnl_rate,
                holding_time=holding_time,
                is_warning=False,
                timestamp=time.time()
            )

        # P2: 时间小额平仓
        if (self.config.enable_time_close and
            holding_time >= self.config.time_close_threshold and
            pnl_rate > self.config.time_close_profit_threshold):
            return CloseDecision(
                pair_id=pair.pair_id,
                should_close=True,
                priority=2,
                reason=f"时间小额平仓: {holding_time:.0f}秒, 利润{pnl_rate:.4%}",
                reason_code="TIME_SMALL_PROFIT",
                spread_change=spread_change,
                unrealized_pnl=unrealized_pnl,
                pnl_rate=pnl_rate,
                holding_time=holding_time,
                is_warning=False,
                timestamp=time.time()
            )

        # P3: 回本止损
        if (holding_time >= self.config.time_close_threshold and
            pnl_rate < 0 and
            pnl_rate > -self.config.max_close_loss_rate):
            # 还在亏损但未达到止损线，继续等待
            return None

        # P3: 回本后平仓
        if (holding_time >= self.config.time_close_threshold and
            pnl_rate >= 0 and pnl_rate < self.config.profit_target_rate):
            return CloseDecision(
                pair_id=pair.pair_id,
                should_close=True,
                priority=3,
                reason=f"回本平仓: {holding_time:.0f}秒, 盈亏{pnl_rate:.4%}",
                reason_code="BREAK_EVEN",
                spread_change=spread_change,
                unrealized_pnl=unrealized_pnl,
                pnl_rate=pnl_rate,
                holding_time=holding_time,
                is_warning=False,
                timestamp=time.time()
            )

        # P4: 强制平仓
        if holding_time >= self.config.max_holding_time:
            return CloseDecision(
                pair_id=pair.pair_id,
                should_close=True,
                priority=4,
                reason=f"强制平仓: 超过最大持仓时间 {holding_time:.0f}秒",
                reason_code="FORCE_CLOSE",
                spread_change=spread_change,
                unrealized_pnl=unrealized_pnl,
                pnl_rate=pnl_rate,
                holding_time=holding_time,
                is_warning=True,
                timestamp=time.time()
            )

        # P5: 价差扩大延迟平仓
        is_diverging = self._is_spread_diverging(
            pair, extended_bid, extended_ask, lighter_bid, lighter_ask
        )
        if is_diverging and self.config.enable_delay_on_divergence:
            # 价差扩大，延迟平仓
            return None

        # 不满足任何平仓条件
        return None

    # ==================== T102-T103, T106: 策略优化方法 ====================

    def _should_open_with_taker(
        self,
        opportunity: Dict[str, Any],
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> bool:
        """
        T102: 检查使用taker订单是否仍有足够利润

        当maker订单可能被拒绝时，需要验证taker订单的利润是否足够。

        注意：opportunity['expected_profit_rate'] 已经是扣除taker手续费后的利润
        （在RealSpreadCalculator中计算的），所以这里不需要再扣手续费。

        Args:
            opportunity: 机会字典
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            bool: True=可以开仓, False=利润不足
        """
        # 获取期望收益率（已经扣除taker手续费和点差成本）
        expected_profit = opportunity.get('expected_profit_rate', Decimal('0'))

        # 检查是否仍满足最小盈利阈值
        min_threshold = self.config.min_profit_threshold

        self.logger.debug(
            f"[Taker利润检查] Taker期望利润={expected_profit:.4%}, "
            f"阈值={min_threshold:.4%}"
        )

        return expected_profit >= min_threshold

    def detect_divergence_signal(
        self,
        pair: SpreadPair,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> Dict[str, Any]:
        """
        T106: 检测价差扩大信号

        Args:
            pair: 套利对
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            Dict: 包含is_diverging, spread_delta, signal_strength等信息
        """
        # 检查价差收敛状态
        is_converged, status_msg, spread_change = pair.is_spread_converged(
            extended_bid, extended_ask, lighter_bid, lighter_ask
        )

        # 如果未收敛，说明在扩大
        is_diverging = not is_converged

        # 计算信号强度（基于价差变化幅度）
        if spread_change.spread_change_rate != 0:
            signal_strength = abs(spread_change.spread_change_rate)
        else:
            signal_strength = Decimal('0')

        return {
            'is_diverging': is_diverging,
            'spread_delta': spread_change.spread_delta,
            'spread_change_rate': spread_change.spread_change_rate,
            'signal_strength': signal_strength,
            'status': spread_change.status
        }

    async def _close_pair_with_market_price(
        self,
        pair: SpreadPair,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> bool:
        """
        T020: 使用市价（对手价）平仓套利对

        根据持仓方向选择正确的对手价进行平仓：
        - 做多仓位（extended_side='buy'）:
          - Extended卖出平仓：使用bid价格
          - Lighter买入平仓：使用ask价格
        - 做空仓位（extended_side='sell'）:
          - Extended买入平仓：使用ask价格
          - Lighter卖出平仓：使用bid价格

        Args:
            pair: 需要平仓的套利对
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Returns:
            bool: 平仓是否成功

        Flow:
            1. 检查 is_closing 标志，防止重复平仓
            2. 根据持仓方向确定平仓价格
            3. 构造 opportunity 字典
            4. 调用 _close_pair 执行平仓
            5. 记录结果到统计和日志
        """
        try:
            self.logger.info(f"[市价平仓] 开始平仓套利对 #{pair.pair_id}")

            # 001-fix-order-type: T053 - 记录平仓尝试
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.CLOSE_ATTEMPT,
                status=OperationStatus.PENDING,
                exchange=ExchangeType.BOTH,
                pair_id=pair.pair_id
            ))

            # 1. 防止重复平仓
            if getattr(pair, 'is_closing', False):
                self.logger.warning(f"套利对 #{pair.pair_id} 正在平仓中，跳过")
                return False

            # 设置标志
            pair.is_closing = True

            # 2. 确定平仓价格（根据持仓方向选择对手价）
            if pair.extended_side == 'buy':
                # 做多平仓：卖出Extended（对手价bid），买入Lighter（对手价ask）
                close_extended_price = extended_bid
                close_lighter_price = lighter_ask
            else:
                # 做空平仓：买入Extended（对手价ask），卖出Lighter（对手价bid）
                close_extended_price = extended_ask
                close_lighter_price = lighter_bid

            self.logger.debug(
                f"平仓价格选择: {pair.extended_side}仓位\n"
                f"  Extended平仓价格: ${close_extended_price:.2f} "
                f"({'bid' if pair.extended_side == 'buy' else 'ask'})\n"
                f"  Lighter平仓价格: ${close_lighter_price:.2f} "
                f"({'ask' if pair.extended_side == 'buy' else 'bid'})"
            )

            # 3. 构造 opportunity 字典（复用 _close_pair 的接口）
            opportunity = {
                'side': 'sell' if pair.extended_side == 'buy' else 'buy',
                'extended_price': close_extended_price,
                'lighter_price': close_lighter_price
            }

            # 4. 调用现有的平仓逻辑
            success = await self._close_pair(pair, opportunity)

            if not success:
                self.logger.error(f"市价平仓失败！套利对 #{pair.pair_id} 仍持仓")
                pair.is_closing = False  # 重置标志，允许重试

                # 001-fix-order-type: T055 - 记录平仓失败
                self.success_tracker.record_operation(SpreadOperationResult(
                    timestamp=time.time(),
                    operation_type=OperationType.CLOSE_FAILED,
                    status=OperationStatus.FAILED,
                    exchange=ExchangeType.BOTH,
                    pair_id=pair.pair_id,
                    failure_reason=FailureReason.UNKNOWN_ERROR,
                    error_message="市价平仓失败"
                ))

                return False

            # 001-fix-order-type: T054 - 记录平仓成功
            self.success_tracker.record_operation(SpreadOperationResult(
                timestamp=time.time(),
                operation_type=OperationType.CLOSE_SUCCESS,
                status=OperationStatus.SUCCESS,
                exchange=ExchangeType.BOTH,
                pair_id=pair.pair_id,
                price=close_extended_price  # Extended平仓价格
            ))

            # T043: 记录平仓分析
            # 创建价差变化对象
            is_converged, status_msg, spread_change = pair.is_spread_converged(
                extended_bid, extended_ask, lighter_bid, lighter_ask
            )

            # 创建平仓决策对象
            decision = CloseDecision(
                pair_id=pair.pair_id,
                should_close=True,
                priority=4,  # 市价平仓通常是P4或更高优先级
                reason="市价强制平仓",
                reason_code="MARKET_FORCE_CLOSE",
                spread_change=spread_change,
                unrealized_pnl=pair.realized_pnl if pair.realized_pnl else Decimal('0'),
                pnl_rate=Decimal('0'),
                holding_time=pair.holding_time,
                is_warning=True,
                timestamp=time.time(),
                extended_close_price=close_extended_price,
                lighter_close_price=close_lighter_price
            )

            if not self.trade_logger.log_close_analysis(pair, decision):
                self.logger.warning(f"平仓分析记录失败 - 套利对 #{pair.pair_id}，但交易继续")

            # 5. 平仓成功
            self.logger.info(f"✅ 市价平仓成功！套利对 #{pair.pair_id}")
            return True

        except Exception as e:
            self.logger.error(f"市价平仓异常: {e}")
            self.logger.error(traceback.format_exc())
            pair.is_closing = False
            return False

    async def _force_close_pair(self, pair: SpreadPair) -> bool:
        """
        强制平仓套利对（保留用于兼容性，但标记为废弃）

        使用对手价模拟市价单，快速平仓以避免进一步损失。

        注意：此方法已被 _close_pair_with_market_price 替代，
        保留仅用于向后兼容。建议直接使用新方法。

        Args:
            pair: 需要平仓的套利对

        Returns:
            bool: 平仓是否成功
        """
        try:
            self.logger.info(f"[强制平仓] 开始平仓套利对 #{pair.pair_id}")

            # 1. 防止重复平仓
            if getattr(pair, 'is_closing', False):
                self.logger.warning(f"套利对 #{pair.pair_id} 正在平仓中，跳过")
                return False

            # 设置标志
            pair.is_closing = True

            # 2. 获取当前对手价（模拟市价单）
            if not self.extended_orderbook['bids'] or not self.extended_orderbook['asks']:
                self.logger.error("订单簿数据不足，无法平仓")
                pair.is_closing = False
                return False

            extended_bid = max(self.extended_orderbook['bids'].keys())
            extended_ask = min(self.extended_orderbook['asks'].keys())
            lighter_bid = max(self.lighter_orderbook['bids'].keys())
            lighter_ask = min(self.lighter_orderbook['asks'].keys())

            # 确定平仓价格（使用对手价）
            if pair.extended_side == 'buy':
                # 做多平仓：卖出Extended（对手价bid），买入Lighter（对手价ask）
                close_extended_price = extended_bid
                close_lighter_price = lighter_ask
            else:
                # 做空平仓：买入Extended（对手价ask），卖出Lighter（对手价bid）
                close_extended_price = extended_ask
                close_lighter_price = lighter_bid

            # 3. 构造 opportunity 字典（复用 _close_pair 的接口）
            opportunity = {
                'side': 'sell' if pair.extended_side == 'buy' else 'buy',
                'extended_price': close_extended_price,
                'lighter_price': close_lighter_price
            }

            # 4. 调用现有的平仓逻辑
            success = await self._close_pair(pair, opportunity)

            if not success:
                self.logger.error(f"强制平仓失败！套利对 #{pair.pair_id} 仍持仓")
                pair.is_closing = False  # 重置标志，允许重试
                return False

            # 5. 平仓成功
            self.logger.info(f"✅ 强制平仓成功！套利对 #{pair.pair_id}")
            return True

        except Exception as e:
            self.logger.error(f"强制平仓异常: {e}")
            pair.is_closing = False
            return False

    def _log_position_status(
        self,
        pair: SpreadPair,
        current_extended_price: Decimal,
        current_lighter_price: Decimal
    ) -> None:
        """
        输出单个持仓状态信息（保留用于兼容性，但不再使用）

        Args:
            pair: 套利对
            current_extended_price: 当前 Extended 价格
            current_lighter_price: 当前 Lighter 价格
        """
        # 此方法已弃用，使用 _log_unified_positions 替代
        pass

    def _log_unified_positions(
        self,
        extended_bid: Decimal,
        extended_ask: Decimal,
        lighter_bid: Decimal,
        lighter_ask: Decimal
    ) -> None:
        """
        输出统一持仓监控信息

        Args:
            extended_bid: Extended买一价
            extended_ask: Extended卖一价
            lighter_bid: Lighter买一价
            lighter_ask: Lighter卖一价

        Output Format (简体中文):
            📊 持仓监控汇总
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            做多仓位 (共3个套利对):
               总数量: 0.0300 ETH
               Extended平均价格: $3087.10
               Lighter平均价格: $3058.93
               持仓时间: 37-49秒 (剩余 1751秒)
               当前价格: Extended $3087.00 / Lighter $3089.42
               未实现盈亏: -$0.92
               距离盈利目标: $0.96
               平仓后收益: -$1.22 (含手续费 $0.30)
        """
        try:
            # 聚合持仓
            unified_positions = self.position_aggregator.aggregate_positions(self.open_pairs)

            if not unified_positions:
                return

            # 输出标题
            self.logger.info("📊 持仓监控汇总")
            self.logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 按方向输出
            for direction, position in unified_positions.items():
                direction_label = "做多" if direction == 'long' else "做空"
                pair_count = len(position.pair_ids)

                self.logger.info(f"{direction_label}仓位 (共{pair_count}个套利对):")

                # 计算持仓时间范围
                earliest_holding, latest_holding = position.calculate_holding_time_range()
                remaining_time = max(0, self.config.max_holding_time - latest_holding)

                # 确定当前价格（根据方向）
                if direction == 'long':
                    current_extended = extended_ask
                    current_lighter = lighter_bid
                else:
                    current_extended = extended_bid
                    current_lighter = lighter_ask

                # 计算未实现盈亏
                unrealized_pnl = self._calculate_unified_pnl(position, current_extended, current_lighter)

                # 计算盈利目标差距
                profit_target = position.total_quantity * current_extended * self.config.profit_target_rate
                profit_gap = profit_target - unrealized_pnl

                # 计算平仓后收益
                profit_breakdown = self.profit_calculator.calculate_profit(
                    position, extended_bid, extended_ask, lighter_bid, lighter_ask
                )

                # 格式化输出
                self.logger.info(f"   总数量: {position.total_quantity:.4f} ETH")
                self.logger.info(f"   Extended平均价格: ${position.extended_avg_price:.2f}")
                self.logger.info(f"   Lighter平均价格: ${position.lighter_avg_price:.2f}")
                self.logger.info(f"   持仓时间: {earliest_holding:.0f}-{latest_holding:.0f}秒 (剩余 {remaining_time:.0f}秒)")
                self.logger.info(f"   当前价格: Extended ${current_extended:.2f} / Lighter ${current_lighter:.2f}")
                self.logger.info(f"   未实现盈亏: ${unrealized_pnl:.2f}")
                self.logger.info(f"   距离盈利目标: ${profit_gap:.2f}")

                # 输出平仓后收益（如果计算成功）
                if profit_breakdown is not None:
                    total_fees = position.total_opening_fees + profit_breakdown.estimated_closing_fees
                    profit_sign = "+" if profit_breakdown.net_profit >= 0 else ""
                    self.logger.info(f"   平仓后收益: {profit_sign}${profit_breakdown.net_profit:.2f} (含手续费 ${total_fees:.2f})")
                else:
                    self.logger.info("   平仓后收益: 价格数据异常，无法计算")

                self.logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # T062: 使用新的calculate_balance方法计算仓位平衡
            balance_result = self.position_aggregator.calculate_balance(self.open_pairs)

            # T064: 更新日志输出显示imbalance_level
            self.logger.info("📊 仓位平衡状态:")
            self.logger.info(f"   Extended总仓位: {balance_result.summary.extended_total_qty:.4f}")
            self.logger.info(f"   Lighter总仓位: {balance_result.summary.lighter_total_qty:.4f}")
            self.logger.info(f"   差异: {balance_result.summary.diff_qty:.4f} ({balance_result.diff_rate:.2%})")

            # T065: 添加仓位不平衡警报逻辑
            if balance_result.warning_level == 'CRITICAL':
                self.logger.error(f"   🚨 状态: 严重失衡！需要人工干预！")
            elif balance_result.warning_level == 'WARN':
                self.logger.warning(f"   ⚠️ 状态: 失衡，请关注")
            else:
                self.logger.info(f"   ✅ 状态: 平衡")
            self.logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        except Exception as e:
            self.logger.debug(f"统一持仓状态输出错误: {e}")

    def _calculate_unified_pnl(
        self,
        position: UnifiedPosition,
        current_extended_price: Decimal,
        current_lighter_price: Decimal
    ) -> Decimal:
        """
        计算统一持仓的未实现盈亏

        Args:
            position: 统一持仓
            current_extended_price: 当前 Extended 价格
            current_lighter_price: 当前 Lighter 价格

        Returns:
            未实现盈亏
        """
        if position.direction == 'long':
            # 做多：Extended买入价，Lighter卖出价
            extended_pnl = (current_extended_price - position.extended_avg_price) * position.total_quantity
            lighter_pnl = (position.lighter_avg_price - current_lighter_price) * position.total_quantity
        else:
            # 做空：Extended卖出价，Lighter买入价
            extended_pnl = (position.extended_avg_price - current_extended_price) * position.total_quantity
            lighter_pnl = (current_lighter_price - position.lighter_avg_price) * position.total_quantity

        return extended_pnl + lighter_pnl

    def _log_all_positions(
        self,
        pairs: list,
        extended_bid: Optional[Decimal] = None,
        extended_ask: Optional[Decimal] = None,
        lighter_bid: Optional[Decimal] = None,
        lighter_ask: Optional[Decimal] = None
    ) -> None:
        """
        整合输出所有持仓的监控信息

        Args:
            pairs: 持仓列表
            extended_bid: Extended bid价格（用于计算已实现收益）
            extended_ask: Extended ask价格（用于计算已实现收益）
            lighter_bid: Lighter bid价格（用于计算已实现收益）
            lighter_ask: Lighter ask价格（用于计算已实现收益）

        Output Format (简体中文):
            📊 持仓监控汇总
               持仓 #1 (做多):
                  ...
               ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
               持仓 #2 (做空):
                  ...
               总持仓: 2 | 总未实现盈亏: $12.34
        """
        try:
            # 空持仓列表
            if not pairs:
                self.logger.info("📊 持仓监控汇总\n   无活跃持仓")
                return

            # 检查订单簿数据是否可用
            has_prices = extended_bid is not None and extended_ask is not None and lighter_bid is not None and lighter_ask is not None

            # 构建输出行
            output_lines = ["📊 持仓监控汇总"]

            # 如果没有价格数据，添加警告
            if not has_prices:
                output_lines.append("   ⚠️ 订单簿数据不可用")

            total_unrealized_pnl = Decimal('0')

            # 遍历所有持仓
            for i, pair in enumerate(pairs):
                # 添加分隔符（除了第一个持仓）
                if i > 0:
                    output_lines.append("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

                try:
                    # 计算持仓时间和剩余时间
                    holding_time = pair.holding_time
                    remaining_time = max(0, self.config.max_holding_time - holding_time)

                    # 确定方向
                    direction = "做多" if pair.extended_side == 'buy' else "做空"
                    closing_mark = " [平仓中]" if pair.is_closing else ""

                    # 获取当前价格
                    if extended_bid is not None and lighter_ask is not None:
                        current_extended = extended_bid
                        current_lighter = lighter_ask

                        # 计算未实现盈亏
                        unrealized_pnl = pair.calculate_unrealized_pnl(
                            current_extended, current_lighter
                        )
                        total_unrealized_pnl += unrealized_pnl

                        # 计算已实现收益（使用对手价）
                        # 做多: extended用bid平仓, lighter用ask平仓
                        # 做空: extended用ask平仓, lighter用bid平仓
                        if pair.extended_side == 'buy':
                            # 做多
                            realized_pnl = pair.calculate_realized_pnl(
                                extended_close_price=extended_bid,
                                lighter_close_price=lighter_ask
                            )
                        else:
                            # 做空
                            realized_pnl = pair.calculate_realized_pnl(
                                extended_close_price=extended_ask,
                                lighter_close_price=lighter_bid
                            )

                        # 计算盈利目标差距
                        profit_target = (pair.extended_quantity * current_extended *
                                        self.config.profit_target_rate)
                        profit_gap = profit_target - unrealized_pnl

                        # 格式化持仓信息
                        output_lines.append(f"   持仓 #{pair.pair_id} ({direction}){closing_mark}:")
                        output_lines.append(f"      持仓时间: {holding_time:.0f}秒 (剩余 {remaining_time:.0f}秒)")
                        output_lines.append(f"      Extended仓位: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}")
                        output_lines.append(f"      当前价格: ${current_extended:.2f}")
                        output_lines.append(f"      Lighter仓位: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}")
                        output_lines.append(f"      当前价格: ${current_lighter:.2f}")
                        # 显示已实现收益
                        if realized_pnl is not None:
                            output_lines.append(f"      当前已实现收益: ${realized_pnl:.2f}")
                        else:
                            output_lines.append(f"      当前已实现收益: N/A")
                        output_lines.append(f"      未实现盈亏: ${unrealized_pnl:.2f}")
                        output_lines.append(f"      距离盈利目标: ${profit_gap:.2f}")
                    else:
                        # 价格缺失时的输出
                        output_lines.append(f"   持仓 #{pair.pair_id} ({direction}){closing_mark}:")
                        output_lines.append(f"      持仓时间: {holding_time:.0f}秒 (剩余 {remaining_time:.0f}秒)")
                        output_lines.append(f"      Extended仓位: {pair.extended_quantity:.4f} @ ${pair.extended_price:.2f}")
                        output_lines.append(f"      当前价格: N/A")
                        output_lines.append(f"      Lighter仓位: {pair.lighter_quantity:.4f} @ ${pair.lighter_price:.2f}")
                        output_lines.append(f"      当前价格: N/A")
                        output_lines.append(f"      未实现盈亏: N/A")
                        output_lines.append(f"      距离盈利目标: N/A")

                except Exception as e:
                    # 单个持仓计算失败，记录debug日志但不中断
                    self.logger.debug(f"持仓 #{pair.pair_id} 状态计算错误: {e}")
                    output_lines.append(f"   持仓 #{pair.pair_id}: 状态计算错误")

            # 添加摘要行（多个持仓时）
            if len(pairs) > 1:
                output_lines.append("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                output_lines.append(f"   总持仓: {len(pairs)} | 总未实现盈亏: ${total_unrealized_pnl:.2f}")

            # 单次输出所有信息
            self.logger.info("\n".join(output_lines))

        except Exception as e:
            self.logger.debug(f"持仓监控汇总输出错误: {e}")

    def _check_force_close(
        self,
        pair: SpreadPair,
        current_extended_price: Decimal,
        current_lighter_price: Decimal
    ) -> tuple[bool, Optional[str]]:
        """
        检查是否需要强制平仓

        新的多层平仓策略 (按优先级):
        1. 盈利目标平仓 (Priority 1): PnL >= profit_target_rate, 立即平仓锁定利润
        2. 时间小额平仓 (Priority 2): 持仓 > time_close_threshold 且 PnL > 0, 平仓获取小额利润
        3. 回本止损 (Priority 3): 持仓 > time_close_threshold 且 PnL < 0, 等待 PnL >= 0 时平仓
        4. 强制平仓 (Priority 4): 持仓 > max_holding_time, 无论盈亏强制平仓

        Args:
            pair: 套利对
            current_extended_price: 当前 Extended 价格
            current_lighter_price: 当前 Lighter 价格

        Returns:
            (should_close, reason): 是否应该平仓及原因
        """
        # 计算未实现盈亏
        unrealized_pnl = pair.calculate_unrealized_pnl(
            current_extended_price,
            current_lighter_price
        )

        # 计算持仓时间
        holding_time = pair.holding_time

        # ===== Priority 1: 盈利目标平仓 (最高优先级) =====
        if self.config.enable_profit_target:
            # 计算盈利目标 (基于 Extended 平仓价格)
            profit_target = pair.extended_quantity * current_extended_price * self.config.profit_target_rate

            if unrealized_pnl >= profit_target:
                return True, (
                    f"盈利目标达标 (${unrealized_pnl:.2f} >= ${profit_target:.2f}), "
                    f"持仓{holding_time:.0f}秒"
                )

        # ===== Priority 2: 时间小额平仓 =====
        if holding_time > self.config.time_close_threshold:
            # 超过时间阈值后,如果有小额利润则平仓
            if unrealized_pnl > 0:
                return True, (
                    f"时间小额平仓 (持仓{holding_time:.0f}秒, PnL=${unrealized_pnl:.2f})"
                )

        # ===== Priority 3: 回本止损 =====
        if holding_time > self.config.time_close_threshold:
            # 超过时间阈值后,如果亏损则等待回本
            if unrealized_pnl < 0:
                # 检查是否接近回本 (PnL >= 0)
                if unrealized_pnl >= 0:
                    return True, (
                        f"回本止损 (持仓{holding_time:.0f}秒, PnL=${unrealized_pnl:.2f})"
                    )
                else:
                    # 仍在亏损,继续等待
                    self.logger.debug(
                        f"套利对 #{pair.pair_id} 持仓{holding_time:.0f}秒, "
                        f"PnL=${unrealized_pnl:.2f}, 等待回本"
                    )

        # ===== Priority 4: 强制平仓 (避免长期风险) =====
        if holding_time > self.config.max_holding_time:
            return True, (
                f"强制平仓 (持仓{holding_time:.0f}秒 > 最大{self.config.max_holding_time}秒, "
                f"PnL=${unrealized_pnl:.2f})"
            )

        # ===== 传统止损检查 (可选,如果启用) =====
        if self.config.enable_stop_loss:
            if unrealized_pnl < -self.config.stop_loss_usdt:
                return True, f"止损触发 (PnL=${unrealized_pnl:.2f} < -${self.config.stop_loss_usdt})"

        return False, None
    
    def _trigger_circuit_breaker(self):
        """触发断路器"""
        self.is_paused = True
        self.pause_until = time.time() + self.config.cooldown_period
        self.logger.warning(
            f"⚠️ 连续失败 {self.consecutive_failures} 次, "
            f"触发断路器,暂停 {self.config.cooldown_period} 秒"
        )
    
    def _handle_extended_order_update(self, order_data: Dict[str, Any]):
        """处理 Extended 订单更新 (WebSocket 回调)"""
        order_id = order_data.get('order_id')
        current_order_id = self.order_manager.current_order_id

        # T013: 区分"直接处理"和"缓存处理"两种路径
        if current_order_id is None:
            self.logger.info(
                f"🔄 [缓存处理路径] bot收到订单更新: order_id={order_id}, "
                f"current_order_id=None → 订单将被缓存"
            )
        elif order_id == current_order_id:
            self.logger.info(
                f"✅ [直接处理路径] bot收到订单更新: order_id={order_id}, "
                f"status={order_data.get('status')} → 直接应用更新"
            )
        else:
            self.logger.info(
                f"📦 [缓存处理路径] bot收到订单更新: 收到order_id={order_id}, "
                f"当前current_order_id={current_order_id} → 订单将被缓存"
            )

        self.order_manager.update_order_status(order_data)
    
    def update_extended_orderbook(self, orderbook_data: Dict[str, Any]):
        """更新 Extended 订单簿 (由外部调用)"""
        # 更新逻辑由外部 WebSocket 处理
        self.extended_orderbook = orderbook_data
        self.extended_orderbook_ready = True
    
    def update_lighter_orderbook(self, orderbook_data: Dict[str, Any]):
        """更新 Lighter 订单簿 (由外部调用)"""
        self.lighter_orderbook = orderbook_data
        self.lighter_orderbook_ready = True

    def _get_orderbook_prices(self):
        """获取当前订单簿价格（用于价差记录器）

        Returns:
            tuple: (extended_bid, extended_ask, lighter_bid, lighter_ask)
        """
        extended_bid = max(self.extended_orderbook['bids'].keys()) if self.extended_orderbook['bids'] else Decimal('0')
        extended_ask = min(self.extended_orderbook['asks'].keys()) if self.extended_orderbook['asks'] else Decimal('999999')
        lighter_bid = max(self.lighter_orderbook['bids'].keys()) if self.lighter_orderbook['bids'] else Decimal('0')
        lighter_ask = min(self.lighter_orderbook['asks'].keys()) if self.lighter_orderbook['asks'] else Decimal('999999')

        return (extended_bid, extended_ask, lighter_bid, lighter_ask)

    # ========================================================================
    # 011-async-ws-ioc-trading: WebSocket订单簿回调
    # ========================================================================

    def _handle_websocket_orderbook(self, exchange: str, orderbook: Dict[str, Any]) -> None:
        """处理WebSocket订单簿更新回调

        Args:
            exchange: 'extended' 或 'lighter'
            orderbook: 订单簿数据 {'bid': Decimal, 'ask': Decimal, 'bid_qty': Decimal, 'ask_qty': Decimal, 'timestamp': float}
        """
        try:
            # 更新本地订单簿数据（保持与现有格式兼容）
            if exchange == 'extended':
                if orderbook.get('bid') and orderbook.get('bid'):
                    self.extended_orderbook['bids'] = {orderbook['bid']: orderbook.get('bid_qty', Decimal('1'))}
                if orderbook.get('ask') and orderbook.get('ask'):
                    self.extended_orderbook['asks'] = {orderbook['ask']: orderbook.get('ask_qty', Decimal('1'))}
                self.extended_orderbook_ready = True
            elif exchange == 'lighter':
                if orderbook.get('bid') and orderbook.get('bid'):
                    self.lighter_orderbook['bids'] = {orderbook['bid']: orderbook.get('bid_qty', Decimal('1'))}
                if orderbook.get('ask') and orderbook.get('ask'):
                    self.lighter_orderbook['asks'] = {orderbook['ask']: orderbook.get('ask_qty', Decimal('1'))}
                self.lighter_orderbook_ready = True

            # 调试日志
            if self.config.log_all_timestamps:
                self.logger.debug(
                    f"[WebSocket订单簿] {exchange}: bid={orderbook.get('bid')}, "
                    f"ask={orderbook.get('ask')}, ts={orderbook.get('timestamp'):.0f}"
                )

        except Exception as e:
            self.logger.error(f"处理WebSocket订单簿更新错误 ({exchange}): {e}")

    def _get_orderbook_timestamps(self) -> tuple[Optional[float], Optional[float]]:
        """获取订单簿时间戳（用于数据新鲜度检查）

        Returns:
            (extended_timestamp_ms, lighter_timestamp_ms)
        """
        ext_ts = None
        lit_ts = None

        if self.websocket_manager:
            ext_ts = self.websocket_manager.get_orderbook_timestamp('extended')
            lit_ts = self.websocket_manager.get_orderbook_timestamp('lighter')

        return ext_ts, lit_ts

    # ========================================================================

    async def _cleanup(self):
        """清理资源"""
        self.logger.info("清理资源...")
        self.stop_flag = True

        # ========================================================================
        # 011-async-ws-ioc-trading: 断开WebSocket连接
        # ========================================================================
        if self.websocket_manager:
            self.logger.info("断开WebSocket连接...")
            await self.websocket_manager.disconnect_all()

        # 导出性能监控统计
        if self.config.enable_enhanced_logging:
            self.performance_monitor.log_stats_summary()
        # ========================================================================

        # 停止价差记录器
        if self.spread_recorder:
            self.spread_recorder.stop()

        # 打印最终统计
        self.logger.info("="*60)
        self.logger.info("📊 最终统计")
        self.logger.info(f"  剩余持仓: {len(self.open_pairs)}")
        self.logger.info(f"  已平仓: {len(self.closed_pairs)}")
        self.logger.info(f"  总机会: {self.stats['total_opportunities']}")
        self.logger.info(f"  成功开仓: {self.stats['successful_opens']}")
        self.logger.info(f"  成功平仓: {self.stats['successful_closes']}")
        net_pnl = self.stats['total_profit'] - self.stats['total_loss']
        self.logger.info(f"  净盈亏: ${net_pnl:.2f}")

        # 001-fix-order-type: T056-T057 - 导出成功率统计数据
        operations_file = self.success_tracker.export_operations_csv()
        if operations_file:
            self.logger.info(f"  操作记录已导出: {operations_file}")

        summary_file = self.success_tracker.export_summary_csv()
        if summary_file:
            self.logger.info(f"  成功率汇总已导出: {summary_file}")

        # T086: 011-async-ws-ioc-trading - 导出性能数据和决策记录
        performance_file = self.performance_monitor.export_performance_data()
        if performance_file:
            self.logger.info(f"  性能数据已导出: {performance_file}")

        decisions_file = self.performance_monitor.export_decision_records()
        if decisions_file:
            self.logger.info(f"  决策记录已导出: {decisions_file}")

        # 🔴 显示未对冲仓位警告
        if len(self.unhedged_positions) > 0:
            self.logger.error("")
            self.logger.error("🚨🚨🚨 警告：存在未对冲的Extended仓位！ 🚨🚨🚨")
            self.logger.error(f"   数量：{len(self.unhedged_positions)} 个")
            self.logger.error("   请立即手动平仓这些仓位，否则面临巨大风险！")
            self.logger.error("")
            for pos in self.unhedged_positions:
                self.logger.error(
                    f"   ❌ {pos['side'].upper()} {pos['quantity']:.4f} @ ${pos['price']:.2f} "
                    f"(订单ID: {pos['order_id']}, 错误: {pos['error']})"
                )
            self.logger.error("")

        self.logger.info("="*60)

    def _record_hedge_attempt(self, success: bool):
        """记录对冲尝试结果"""
        self.hedge_attempts.append(success)
        # 只保留最近的N次记录
        if len(self.hedge_attempts) > self.config.hedge_failure_window:
            self.hedge_attempts.pop(0)

    # ========================================================================
    # 001-fix-order-type: 仓位一致性验证方法
    # ========================================================================

    async def validate_position_consistency(
        self,
        pair,
        threshold: Decimal = None,
        rate_threshold: float = None
    ):
        """
        001-fix-order-type: 验证开仓后仓位一致性

        Args:
            pair: 套利对对象
            threshold: 差异数量阈值（从配置读取，默认0.001 ETH）
            rate_threshold: 差异率阈值（从配置读取，默认10%）

        Returns:
            PositionConsistencyCheck: 一致性检查结果
        """
        # 从配置读取阈值
        if threshold is None:
            threshold = self.config.position_consistency_threshold
        if rate_threshold is None:
            rate_threshold = self.config.position_consistency_rate_threshold

        # 调用position_aggregator的检查方法
        check_result = self.position_aggregator.get_position_balance_for_pair(
            pair=pair,
            threshold=threshold,
            rate_threshold=rate_threshold
        )

        # 记录日志
        if check_result.is_consistent:
            self.logger.info(
                f"[001-fix-order-type] 仓位一致性检查通过: {check_result}"
            )
        else:
            self.logger.warning(
                f"[001-fix-order-type] 仓位不一致警告: {check_result}"
            )

        return check_result

    def reset_circuit_breaker(self):
        """手动重置熔断器

        用于用户确认问题解决后恢复交易
        """
        self.safety_monitor.reset_circuit_breaker()
        self.logger.info("熔断器已手动重置")

    def _check_hedge_failure_rate(self) -> tuple[bool, Decimal]:
        """检查对冲失败率

        Returns:
            (是否超过阈值, 当前失败率)
        """
        if len(self.hedge_attempts) < 5:  # 至少5次尝试才统计
            return False, Decimal('0')

        failures = sum(1 for attempt in self.hedge_attempts if not attempt)
        failure_rate = Decimal(failures) / Decimal(len(self.hedge_attempts))

        is_exceeded = failure_rate > self.config.hedge_failure_threshold

        if is_exceeded:
            self.logger.error(
                f"🚨 对冲失败率过高: {failure_rate:.2%} > {self.config.hedge_failure_threshold:.2%} "
                f"({failures}/{len(self.hedge_attempts)} 次失败)"
            )

        return is_exceeded, failure_rate

    async def _reconciliation_loop(self):
        """持仓对账循环 - 定期验证持仓状态"""
        self.logger.info("持仓对账循环启动")

        while not self.stop_flag:
            try:
                await asyncio.sleep(self.config.reconciliation_interval)

                if not self.config.enable_reconciliation:
                    continue

                # 1. 检查未对冲持仓是否超时
                current_time = time.time()
                timeout_positions = [
                    pos for pos in self.unhedged_positions
                    if current_time - pos['timestamp'] > self.config.unhedged_position_timeout
                ]

                if timeout_positions:
                    self.logger.error(
                        f"🚨 检测到 {len(timeout_positions)} 个超时的未对冲持仓! "
                        f"超时阈值: {self.config.unhedged_position_timeout}秒"
                    )
                    for pos in timeout_positions:
                        age = int(current_time - pos['timestamp'])
                        self.logger.error(
                            f"   ❌ {pos['side'].upper()} {pos['quantity']:.4f} @ ${pos['price']:.2f} "
                            f"(已存在 {age}秒)"
                        )

                    # 如果启用了自动平仓，警告用户
                    if self.config.auto_close_unhedged:
                        self.logger.error("⚠️ 自动平仓已启用，请手动检查!")
                    else:
                        self.logger.error("请手动检查并处理这些持仓!")

                # 2. 验证open_pairs与实际持仓是否匹配
                # 这里可以添加与交易所API的持仓对账逻辑
                # 例如: 调用 get_account_positions() 并与 self.open_pairs 比较

                # 3. 检查对冲失败率
                is_exceeded, failure_rate = self._check_hedge_failure_rate()
                if is_exceeded:
                    self.logger.error("⚠️ 对冲失败率过高，建议检查Lighter连接状态!")

            except Exception as e:
                self.logger.error(f"对账循环错误: {e}")
                self.logger.error(traceback.format_exc())

