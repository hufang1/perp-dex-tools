"""
状态管理器：管理系统状态和持久化

负责：
1. 管理机器人状态（IDLE, OPENING, OPENING_WAIT, HOLDING, CLOSING, ERROR）
2. 管理持仓信息
3. 管理统计信息
4. 状态持久化到文件
5. 从文件恢复状态
"""

import json
import asyncio
from pathlib import Path
from decimal import Decimal
from typing import Optional
from datetime import datetime
import logging

from models import (
    BotState,
    Position,
    PositionState,
    BotStats,
    BotConfig,
    Portfolio,  # 新增 (016-spread-optimize)
    OpenPosition,  # 新增 (016-spread-optimize)
)
from exceptions import StateLoadError, StateSaveError


logger = logging.getLogger(__name__)


class StateManager:
    """
    管理系统状态和持久化

    定期保存状态到文件，支持崩溃后恢复
    """

    # 状态中文映射
    STATE_NAMES_CN = {
        BotState.IDLE: "空闲",
        BotState.OPENING: "开仓中",
        BotState.OPENING_MAKER_WAIT: "开仓挂单等待成交",  # 新增 (017-ext-maker-mode)
        BotState.OPENING_WAIT: "开仓等待确认",
        BotState.HOLDING: "持仓中",
        BotState.CLOSING: "平仓中",
        BotState.CLOSING_MAKER_WAIT: "平仓挂单等待成交",  # 新增 (017-ext-maker-mode)
        BotState.CLOSING_TAKER: "市价平仓中",
        BotState.LIGHTER_HEDGING: "lighter对冲中",  # 新增 (017-ext-maker-mode)
        BotState.CLOSING_WAIT: "平仓等待确认",
        BotState.PAUSED: "风控暂停",
        BotState.ERROR: "错误",
    }

    def __init__(self, state_file: Path):
        """
        初始化状态管理器

        Args:
            state_file: 状态文件路径
        """
        self.state_file = state_file

        # 内存状态
        self._current_state: BotState = BotState.IDLE
        self._position: Optional[Position] = None
        self._portfolio: Portfolio = Portfolio()  # 新增 (016-spread-optimize)
        self._stats: BotStats = BotStats()
        self._last_save_time: Optional[datetime] = None

        # 自动保存配置
        self._auto_save_interval: int = 60  # 60 秒
        self._save_task: Optional[asyncio.Task] = None

        # 配置对象引用（用于重置策略状态）
        self._config: Optional[BotConfig] = None

        logger.info(f"状态管理器初始化: {state_file}")

    async def load_state(self) -> BotState:
        """
        加载状态

        Returns:
            当前机器人状态

        Raises:
            StateLoadError: 状态加载失败
        """
        try:
            if not self.state_file.exists():
                logger.info("状态文件不存在，使用默认状态")
                self._current_state = BotState.IDLE
                self._position = None
                self._portfolio = Portfolio()  # 新增 (016-spread-optimize)
                self._stats = BotStats()
                return self._current_state

            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 解析状态
            state_str = data.get("state", "IDLE")
            self._current_state = BotState[state_str]

            # 解析持仓（保持向后兼容）
            position_data = data.get("position")
            if position_data:
                self._position = Position(
                    state=PositionState[position_data.get("state", "NONE")],
                    extended_entry_price=Decimal(str(position_data.get("extended_entry_price", 0))),
                    lighter_entry_price=Decimal(str(position_data.get("lighter_entry_price", 0))),
                    entry_spread=Decimal(str(position_data.get("entry_spread", 0))),
                    entry_time=datetime.fromisoformat(position_data["entry_time"]) if position_data.get("entry_time") else None,
                    extended_quantity=Decimal(str(position_data.get("extended_quantity", 0))),
                    lighter_quantity=Decimal(str(position_data.get("lighter_quantity", 0))),
                    extended_order_id=position_data.get("extended_order_id"),
                    lighter_order_id=position_data.get("lighter_order_id"),
                )
            else:
                self._position = None

            # 解析Portfolio（新增 016-spread-optimize，向后兼容）
            portfolio_data = data.get("portfolio")
            if portfolio_data:
                self._portfolio = Portfolio()
                for pos_data in portfolio_data.get("positions", []):
                    position = OpenPosition(
                        position_id=pos_data.get("position_id", ""),
                        open_time=pos_data.get("open_time", 0),
                        ext_price=Decimal(str(pos_data.get("ext_price", 0))),
                        lig_price=Decimal(str(pos_data.get("lig_price", 0))),
                        open_spread=Decimal(str(pos_data.get("open_spread", 0))),
                        quantity=Decimal(str(pos_data.get("quantity", 0))),
                        ext_order_id=pos_data.get("ext_order_id"),
                        lig_order_id=pos_data.get("lig_order_id"),
                        is_active=pos_data.get("is_active", True),
                    )
                    self._portfolio.add_position(position)
            else:
                # 向后兼容：如果有旧Position，转换为Portfolio
                self._portfolio = Portfolio()
                if self._position and self._position.is_open():
                    # 将旧Position转换为OpenPosition
                    import time
                    open_position = OpenPosition(
                        position_id=f"legacy_{int(time.time())}",
                        open_time=self._position.entry_time.timestamp() if self._position.entry_time else time.time(),
                        ext_price=self._position.extended_entry_price,
                        lig_price=self._position.lighter_entry_price,
                        open_spread=self._position.entry_spread,
                        quantity=abs(self._position.extended_quantity),
                        ext_order_id=self._position.extended_order_id,
                        lig_order_id=self._position.lighter_order_id,
                        is_active=True,
                    )
                    self._portfolio.add_position(open_position)

            # 解析统计信息
            stats_data = data.get("stats", {})
            self._stats = BotStats(
                total_trades=stats_data.get("total_trades", 0),
                profitable_trades=stats_data.get("profitable_trades", 0),
                total_profit=Decimal(str(stats_data.get("total_profit", 0))),
                total_fees=Decimal(str(stats_data.get("total_fees", 0))),
                start_time=datetime.fromisoformat(stats_data["start_time"]) if stats_data.get("start_time") else None,
                last_trade_time=datetime.fromisoformat(stats_data["last_trade_time"]) if stats_data.get("last_trade_time") else None,
            )

            # 解析策略状态配置 (016-spread-optimize Phase 9: T053 状态恢复)
            # 扩展 (003-spreading-improvements): 添加阶梯开仓和双模式平仓配置
            #
            # 注意：只恢复运行时状态（如 opening_count），不覆盖配置参数（如 initial_open_spread, spread_step）
            # 配置参数应该由命令行参数决定，状态文件只保存运行时状态
            config_state_data = data.get("config_state")
            if config_state_data:
                if hasattr(self, '_config') and self._config:
                    # 只恢复运行时状态
                    self._config.cached_open_spread = Decimal(str(config_state_data.get("cached_open_spread", 0)))
                    self._config.opening_count = config_state_data.get("opening_count", 0)

                    # 不再恢复配置参数，保持命令行参数的优先级
                    # self._config.initial_open_spread = ...
                    # self._config.spread_step = ...
                    # self._config.limit_close_spread_a = ...
                    # self._config.market_close_spread_b = ...

                    logger.info(
                        f"策略运行时状态已恢复: cached_spread={self._config.cached_open_spread:.3%}, "
                        f"opening_count={self._config.opening_count} "
                        f"(配置参数使用命令行值: initial={self._config.initial_open_spread:.3%}, step={self._config.spread_step:.3%})"
                    )
                logger.info(
                    f"策略状态已恢复: cached_spread={self._config.cached_open_spread:.3%}, "
                    f"opening_count={self._config.opening_count}"
                )
            else:
                self._config_state = None

            logger.info(f"状态加载成功: {self._current_state.value}")

            return self._current_state

        except json.JSONDecodeError as e:
            raise StateLoadError(str(self.state_file), str(e))
        except Exception as e:
            raise StateLoadError(str(self.state_file), str(e))

    async def save_state(
        self,
        state: Optional[BotState] = None,
        position: Optional[Position] = None,
        stats: Optional[BotStats] = None
    ) -> None:
        """
        保存状态

        Args:
            state: 机器人状态（可选，不提供则使用当前状态）
            position: 持仓信息（可选）
            stats: 统计信息（可选）
        """
        try:
            # 更新内存状态
            if state is not None:
                self._current_state = state
            if position is not None:
                self._position = position
            if stats is not None:
                self._stats = stats

            # 构建保存数据
            data = {
                "state": self._current_state.value,
                "position": None,
                "portfolio": None,  # 新增 (016-spread-optimize)
                "stats": {
                    "total_trades": self._stats.total_trades,
                    "profitable_trades": self._stats.profitable_trades,
                    "total_profit": str(self._stats.total_profit),
                    "total_fees": str(self._stats.total_fees),
                    "start_time": self._stats.start_time.isoformat() if self._stats.start_time else None,
                    "last_trade_time": self._stats.last_trade_time.isoformat() if self._stats.last_trade_time else None,
                },
                "last_save_time": datetime.now().isoformat(),
            }

            if self._position:
                data["position"] = {
                    "state": self._position.state.value,
                    "extended_entry_price": str(self._position.extended_entry_price),
                    "lighter_entry_price": str(self._position.lighter_entry_price),
                    "entry_spread": str(self._position.entry_spread),
                    "entry_time": self._position.entry_time.isoformat() if self._position.entry_time else None,
                    "extended_quantity": str(self._position.extended_quantity),
                    "lighter_quantity": str(self._position.lighter_quantity),
                    "extended_order_id": self._position.extended_order_id,
                    "lighter_order_id": self._position.lighter_order_id,
                }

            # 新增 (016-spread-optimize): 保存Portfolio
            if self._portfolio and self._portfolio.positions:
                data["portfolio"] = {
                    "positions": [
                        {
                            "position_id": pos.position_id,
                            "open_time": pos.open_time,
                            "ext_price": str(pos.ext_price),
                            "lig_price": str(pos.lig_price),
                            "open_spread": str(pos.open_spread),
                            "quantity": str(pos.quantity),
                            "ext_order_id": pos.ext_order_id,
                            "lig_order_id": pos.lig_order_id,
                            "is_active": pos.is_active,
                        }
                        for pos in self._portfolio.positions
                    ],
                    "total_quantity": str(self._portfolio.total_quantity),
                    "weighted_avg_entry_spread": str(self._portfolio.weighted_avg_entry_spread),
                    "first_open_time": self._portfolio.first_open_time,
                    "last_open_time": self._portfolio.last_open_time,
                }

            # 新增 (016-spread-optimize Phase 9): 保存策略状态配置
            # 扩展 (003-spreading-improvements): 添加阶梯开仓和双模式平仓配置
            if hasattr(self, '_config') and self._config:
                data["config_state"] = {
                    "cached_open_spread": str(self._config.cached_open_spread),
                    "spread_step": str(self._config.spread_step),
                    # 新增 (003-spreading-improvements)
                    "initial_open_spread": str(self._config.initial_open_spread),
                    "spread_step": str(self._config.spread_step),
                    "opening_count": self._config.opening_count,
                    "limit_close_spread_a": str(self._config.limit_close_spread_a),
                    "market_close_spread_b": str(self._config.market_close_spread_b),
                }

            # 确保目录存在
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self._last_save_time = datetime.now()
            logger.debug(f"状态已保存: {self.state_file}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"保存状态失败: {error_msg}")
            raise StateSaveError(str(self.state_file), error_msg)

    async def clear_state(self) -> None:
        """清除状态文件"""
        try:
            if self.state_file.exists():
                self.state_file.unlink()
                logger.info("状态文件已清除")

            # 重置内存状态
            self._current_state = BotState.IDLE
            self._position = None
            # 保留统计信息

        except Exception as e:
            logger.error(f"清除状态文件失败: {e}")

    def get_position(self) -> Optional[Position]:
        """获取当前持仓"""
        return self._position

    def update_position(self, position: Position) -> None:
        """更新持仓信息"""
        self._position = position

    def get_portfolio(self) -> Portfolio:
        """获取仓位组合"""
        return self._portfolio

    def update_portfolio(self, portfolio: Portfolio) -> None:
        """更新仓位组合"""
        self._portfolio = portfolio

    def get_state(self) -> BotState:
        """获取机器人状态"""
        return self._current_state

    # 状态中文映射
    STATE_NAMES_CN = {
        BotState.IDLE: "空闲",
        BotState.OPENING: "开仓中",
        BotState.OPENING_MAKER_WAIT: "开仓挂单等待成交",  # 新增 (017-ext-maker-mode)
        BotState.OPENING_WAIT: "开仓等待确认",
        BotState.HOLDING: "持仓中",
        BotState.CLOSING: "平仓中",
        BotState.CLOSING_MAKER_WAIT: "平仓挂单等待成交",  # 新增 (017-ext-maker-mode)
        BotState.LIGHTER_HEDGING: "lighter对冲中",  # 新增 (017-ext-maker-mode)
        BotState.CLOSING_WAIT: "平仓等待确认",
        BotState.PAUSED: "风控暂停",
        BotState.ERROR: "错误",
        BotState.CLOSING_TAKER: "市价平仓中",
    }

    def set_config(self, config: BotConfig) -> None:
        """
        设置配置对象引用

        Args:
            config: 机器人配置对象
        """
        self._config = config

    def _log_state_transition(self, old_state: BotState, new_state: BotState, reason: str = "") -> None:
        """
        统一状态转换日志函数

        输出格式：💥 {旧状态中文} -> {新状态中文} | {原因}
        同时使用print()强制输出到控制台和logger.info()记录到日志文件

        Args:
            old_state: 旧状态
            new_state: 新状态
            reason: 状态转换的原因（可选）
        """
        # 获取中文名称
        old_name = self.STATE_NAMES_CN.get(old_state, old_state.value)
        new_name = self.STATE_NAMES_CN.get(new_state, new_state.value)

        # 使用print()强制输出到控制台（不受logging级别影响）
        if reason:
            print(f"💥 {old_name} -> {new_name} | {reason}")
        else:
            print(f"💥 {old_name} -> {new_name}")

        # 同时使用logger.info()记录到日志文件
        if reason:
            logger.info(f"💥 {old_name} -> {new_name} | {reason}")
        else:
            logger.info(f"💥 {old_name} -> {new_name}")

    def set_state(self, state: BotState, reason: str = "") -> None:
        """
        设置机器人状态

        Args:
            state: 新状态
            reason: 状态转换的原因（可选）
        """
        old_state = self._current_state
        self._current_state = state

        # 使用统一状态转换日志函数
        self._log_state_transition(old_state, state, reason)

        # 进入IDLE状态时重置开仓价差
        if state == BotState.IDLE and self._config and self._config.cached_open_spread != 0:
            old_spread = self._config.cached_open_spread
            self._config.cached_open_spread = Decimal("0")
            logger.info(f"进入空闲状态，重置开仓价差: {old_spread:.3%} -> 0%")

    def get_stats(self) -> BotStats:
        """获取统计信息"""
        return self._stats

    def update_stats(self, stats: BotStats) -> None:
        """更新统计信息"""
        self._stats = stats

    async def start_auto_save(self) -> None:
        """启动自动保存"""
        if self._save_task is not None:
            logger.warning("自动保存任务已在运行")
            return

        self._save_task = asyncio.create_task(self._auto_save_loop())
        logger.info(f"自动保存已启动: 间隔 {self._auto_save_interval} 秒")

    async def stop_auto_save(self) -> None:
        """停止自动保存"""
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
            self._save_task = None
            logger.info("自动保存已停止")

    async def _auto_save_loop(self) -> None:
        """自动保存循环"""
        while True:
            try:
                await asyncio.sleep(self._auto_save_interval)
                await self.save_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自动保存失败: {e}")
