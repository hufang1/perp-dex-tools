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
            extended_fee_rate=config.extended_fee_rate,
            lighter_fee_rate=config.lighter_fee_rate
        )
        self.profit_calculator = ProfitCalculator(
            extended_fee_rate=config.extended_fee_rate,
            lighter_fee_rate=config.lighter_fee_rate
        )
        
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
            'max_open_pairs': 0
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
                
                # 计算价差机会
                extended_mid = (extended_bid + extended_ask) / Decimal('2')
                opportunity = self.calculator.calculate_spread_opportunity(
                    extended_bid=extended_bid,
                    extended_ask=extended_ask,
                    lighter_bid=lighter_bid,
                    lighter_ask=lighter_ask,
                    extended_mid_price=extended_mid
                )
                
                if opportunity:
                    self.stats['total_opportunities'] += 1
                    
                    # 检查是否有反向持仓可以平仓
                    close_pair = self._find_opposite_pair(opportunity)
                    
                    if close_pair and self.config.prioritize_closing:
                        # 优先平仓
                        self.logger.info(
                            f"🎯 发现平仓机会: 套利对 #{close_pair.pair_id} "
                            f"价差率: {opportunity['spread_rate']:.4%}"
                        )
                        await self._close_pair(close_pair, opportunity)
                    else:
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
                                self.logger.info(
                                    f"🎯 发现开仓机会: {opportunity['type']} "
                                    f"价差率: {opportunity['spread_rate']:.4%} "
                                    f"预期利润: {opportunity['expected_profit_rate']:.4%}"
                                )

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
                                        await self._open_new_pair(opportunity)
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
                else:
                    self.logger.info("📊 当前无持仓")

                # 检查强制平仓条件（保留原有逻辑）
                for pair in self.open_pairs[:]:  # 复制列表
                    # 确定当前平仓价格
                    if pair.extended_side == 'buy':
                        current_extended = extended_ask
                        current_lighter = lighter_bid
                    else:
                        current_extended = extended_bid
                        current_lighter = lighter_ask

                    # 检查强制平仓条件
                    should_close, reason = self._check_force_close(
                        pair, current_extended, current_lighter
                    )

                    if should_close:
                        self.logger.warning(
                            f"⚠️ 套利对 #{pair.pair_id} 触发强制平仓: {reason}"
                        )
                        await self._force_close_pair(pair)

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

                # 🆕 显示对冲失败率
                if len(self.hedge_attempts) >= 5:
                    _, failure_rate = self._check_hedge_failure_rate()
                    self.logger.info(f"  对冲失败率: {failure_rate:.2%} ({len(self.hedge_attempts)} 次尝试)")

                # 🔴 显示未对冲仓位警告
                if len(self.unhedged_positions) > 0:
                    self.logger.error(f"  ⚠️ 未对冲仓位: {len(self.unhedged_positions)} 个")
                    for pos in self.unhedged_positions:
                        self.logger.error(
                            f"     - {pos['side']} {pos['quantity']:.4f} @ {pos['price']:.2f} "
                            f"(订单ID: {pos['order_id']})"
                        )

                self.logger.info("="*60)
                
            except Exception as e:
                self.logger.error(f"统计报告错误: {e}")
    
    def _find_opposite_pair(self, opportunity: Dict[str, Any]) -> Optional[SpreadPair]:
        """查找反向持仓"""
        for pair in self.open_pairs:
            if pair.should_close(opportunity):
                return pair
        return None
    
    async def _open_new_pair(self, opportunity: Dict[str, Any]) -> bool:
        """开新的套利对"""
        try:
            self.logger.info(f"开仓套利对...")
            self.logger.info(
                f"[DEBUG] 机会详情: type={opportunity['type']}, "
                f"side={opportunity['side']}, "
                f"extended_price={opportunity['extended_price']}, "
                f"lighter_price={opportunity['lighter_price']}, "
                f"quantity={opportunity['quantity']:.6f}"
            )

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

            # 1. Extended 下 Maker 单
            order = await self.order_manager.place_spread_maker_order(
                side=opportunity['side'],
                price=opportunity['extended_price'],
                quantity=opportunity['quantity']
            )

            self.logger.info(f"[DEBUG] 下单返回: success={order['success']}, order_id={order.get('order_id')}")

            if not order['success']:
                self.stats['failed_opens'] += 1
                self.consecutive_failures += 1
                return False
            
            # 2. 等待成交
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
            
            # 3. 执行对冲
            hedge_side = 'sell' if opportunity['side'] == 'buy' else 'buy'
            hedge_result = await self.hedge_manager.execute_hedge(
                side=hedge_side,
                quantity=fill_result['filled_quantity'],
                expected_price=opportunity['lighter_price']
            )

            # 🆕 记录对冲尝试结果
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
                    'expected_price': opportunity['lighter']['price'],  # 预期的对冲价格
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

            self.next_pair_id += 1
            self.open_pairs.append(pair)

            # 更新统计
            self.stats['successful_opens'] += 1
            self.stats['opportunities_taken'] += 1
            self.stats['max_open_pairs'] = max(self.stats['max_open_pairs'], len(self.open_pairs))
            self.consecutive_failures = 0

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

            return True
            
        except Exception as e:
            self.logger.error(f"开仓失败: {e}")
            self.logger.error(traceback.format_exc())
            self.stats['failed_opens'] += 1
            self.consecutive_failures += 1
            
            # 触发断路器
            if self.consecutive_failures >= self.config.max_consecutive_failures:
                self._trigger_circuit_breaker()
            
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
    
    async def _force_close_pair(self, pair: SpreadPair) -> bool:
        """
        强制平仓套利对

        使用对手价模拟市价单，快速平仓以避免进一步损失。

        Args:
            pair: 需要平仓的套利对

        Returns:
            bool: 平仓是否成功

        Flow:
            1. 检查 is_closing 标志，防止重复平仓
            2. 获取当前订单簿的对手价
            3. 构造 opportunity 字典
            4. 调用 _close_pair 执行平仓
            5. 记录结果到统计和日志
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
        self.logger.info(
            f"[DEBUG] bot收到订单更新: order_data={order_data}, "
            f"current_order_id={self.order_manager.current_order_id}"
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
    
    async def _cleanup(self):
        """清理资源"""
        self.logger.info("清理资源...")
        self.stop_flag = True

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

