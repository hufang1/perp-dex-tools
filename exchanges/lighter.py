"""
Lighter exchange client implementation.
"""

import os
import asyncio
import time
import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from .base import BaseExchangeClient, OrderResult, OrderInfo, query_retry
from helpers.logger import TradingLogger

# 011-fix-lighter-hedge: Import OrderCache for WebSocket race condition handling
from spread.models import OrderCache

# Import official Lighter SDK for API client
import lighter
from lighter import SignerClient, ApiClient, Configuration

# Import custom WebSocket implementation
from .lighter_custom_websocket import LighterCustomWebSocketManager

# Suppress Lighter SDK debug logs
logging.getLogger('lighter').setLevel(logging.WARNING)
# Also suppress root logger DEBUG messages that might be coming from Lighter SDK
root_logger = logging.getLogger()
if root_logger.level == logging.DEBUG:
    root_logger.setLevel(logging.WARNING)


# ========================================================================
# 003-fix-lighter-sdk: SDK健康状态数据类
# ========================================================================

@dataclass
class SDKHealthStatus:
    """SDK健康状态

    003-fix-lighter-sdk US3: 健康状态数据类
    """
    healthy: bool                    # SDK是否健康可用
    errors: List[str]                # 错误消息列表
    timestamp: float = field(default_factory=time.time)  # 检查时间戳

    def is_healthy(self) -> bool:
        """检查SDK是否健康"""
        return self.healthy and len(self.errors) == 0

    def get_error_summary(self) -> str:
        """获取错误摘要"""
        return "; ".join(self.errors) if self.errors else "No errors"


# ========================================================================
# End 003-fix-lighter-sdk data classes
# ========================================================================


class LighterClient(BaseExchangeClient):
    """Lighter exchange client implementation."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize Lighter client."""
        super().__init__(config)

        # Lighter credentials from environment
        self.api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
        self.account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
        self.api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))
        self.base_url = "https://mainnet.zklighter.elliot.ai"

        if not self.api_key_private_key:
            raise ValueError("API_KEY_PRIVATE_KEY must be set in environment variables")

        # Initialize logger
        self.logger = TradingLogger(exchange="lighter", ticker=self.config.ticker, log_to_console=False)
        self._order_update_handler = None

        # Initialize Lighter client (will be done in connect)
        self.lighter_client = None

        # Initialize API client (will be done in connect)
        self.api_client = None

        # Market configuration
        self.base_amount_multiplier = None
        self.price_multiplier = None
        self.orders_cache = {}
        self.current_order_client_id = None
        self.current_order = None

        # 011-fix-lighter-hedge: OrderCache for WebSocket race conditions
        self.order_cache = OrderCache()

    def _validate_config(self) -> None:
        """Validate Lighter configuration."""
        required_env_vars = ['API_KEY_PRIVATE_KEY', 'LIGHTER_ACCOUNT_INDEX', 'LIGHTER_API_KEY_INDEX']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")

    async def _get_market_config(self, ticker: str) -> Tuple[int, int, int]:
        """Get market configuration for a ticker using official SDK."""
        try:
            # Use shared API client
            order_api = lighter.OrderApi(self.api_client)

            # Get order books to find market info
            order_books = await order_api.order_books()

            for market in order_books.order_books:
                if market.symbol == ticker:
                    market_id = market.market_id
                    base_multiplier = pow(10, market.supported_size_decimals)
                    price_multiplier = pow(10, market.supported_price_decimals)

                    # Store market info for later use
                    self.config.market_info = market

                    self.logger.log(
                        f"Market config for {ticker}: ID={market_id}, "
                        f"Base multiplier={base_multiplier}, Price multiplier={price_multiplier}",
                        "INFO"
                    )
                    return market_id, base_multiplier, price_multiplier

            raise Exception(f"Ticker {ticker} not found in available markets")

        except Exception as e:
            self.logger.log(f"Error getting market config: {e}", "ERROR")
            raise

    async def _initialize_lighter_client(self):
        """Initialize the Lighter client using official SDK.

        001-fix-lighter-trading: 修复代理配置和SDK初始化问题
        - 确保rest_client.proxy正确设置
        - 添加健壮性检查处理延迟创建的rest_client
        - 增强错误日志记录
        """
        if self.lighter_client is None:
            try:
                # 获取代理设置
                https_proxy = os.getenv('https_proxy') or os.getenv('HTTPS_PROXY')
                http_proxy = os.getenv('http_proxy') or os.getenv('HTTP_PROXY')
                proxy_url = https_proxy or http_proxy

                if proxy_url:
                    self.logger.log(f"Configuring proxy for SignerClient: {proxy_url}", "INFO")

                # 创建SignerClient（会在内部创建ApiClient和RESTClient）
                self.lighter_client = SignerClient(
                    url=self.base_url,
                    private_key=self.api_key_private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )

                # 001-fix-lighter-trading T014: 添加rest_client.proxy设置的健壮性检查
                if proxy_url and hasattr(self.lighter_client, 'api_client'):
                    # 003-fix-lighter-sdk T015: 先检查api_client是否为None，避免AttributeError
                    if self.lighter_client.api_client is not None:
                        # 先设置configuration.proxy
                        self.lighter_client.api_client.configuration.proxy = proxy_url

                        # 检查rest_client是否存在
                        if hasattr(self.lighter_client.api_client, 'rest_client') and self.lighter_client.api_client.rest_client is not None:
                            # rest_client已创建，直接设置proxy
                            self.lighter_client.api_client.rest_client.proxy = proxy_url
                            self.logger.log(f"[LIGHTER] Proxy configured on rest_client: {proxy_url}", "INFO")
                        else:
                            # rest_client尚未创建，延迟设置
                            # 注意：这可能导致首次请求时代理不生效，但后续请求会使用代理
                            import asyncio
                            await asyncio.sleep(0.1)
                            if hasattr(self.lighter_client.api_client, 'rest_client') and self.lighter_client.api_client.rest_client is not None:
                                self.lighter_client.api_client.rest_client.proxy = proxy_url
                                self.logger.log(f"[LIGHTER] Proxy configured after delay: {proxy_url}", "INFO")
                            else:
                                self.logger.log(f"[LIGHTER] WARNING: rest_client not available, proxy may not be active until next request", "WARNING")
                    else:
                        # 003-fix-lighter-sdk: api_client为None，这是SDK初始化失败的症状
                        self.logger.log(f"[LIGHTER] ERROR: api_client is None after SignerClient initialization!", "ERROR")
                        self.logger.log(f"[LIGHTER] This indicates the SDK did not initialize properly. Proxy may have caused the issue.", "ERROR")

                # 001-fix-lighter-trading T016: 验证check_client()返回None表示成功并添加日志记录
                err = self.lighter_client.check_client()
                if err is not None:
                    self.logger.log(f"[LIGHTER] CheckClient failed: {err}", "ERROR")
                    raise Exception(f"CheckClient error: {err}")

                self.logger.log("[LIGHTER] CheckClient passed: SDK initialized successfully", "INFO")

                # 003-fix-lighter-sdk US1 T012-T016: 验证SDK关键对象已正确初始化
                if not self._validate_sdk_objects():
                    raise Exception("SDK validation failed: one or more critical objects are None")

            except Exception as e:
                # 001-fix-lighter-trading T017: 添加代理连接失败的fallback处理
                # 记录详细错误信息但不中断程序（除非是关键错误）
                self.logger.log(f"[LIGHTER] Failed to initialize Lighter client: {type(e).__name__}: {str(e)}", "ERROR")

                # 如果是代理相关错误，提供fallback建议
                if proxy_url and ('proxy' in str(e).lower() or 'connection' in str(e).lower()):
                    self.logger.log(f"[LIGHTER] WARNING: Proxy connection failed. Consider checking proxy settings or trying without proxy.", "WARNING")

                # 重新抛出异常让上层处理
                raise

        return self.lighter_client

    # ========================================================================
    # 003-fix-lighter-sdk: SDK对象验证和健康检查
    # ========================================================================

    def _validate_sdk_objects(self) -> bool:
        """验证SDK关键对象已正确初始化

        Returns:
            bool: True if all objects are valid, False otherwise

        003-fix-lighter-sdk US1: 验证lighter_client、api_client、rest_client存在性
        """
        errors = []

        # 检查lighter_client
        if self.lighter_client is None:
            errors.append("lighter_client is None")
        elif not hasattr(self.lighter_client, 'api_client'):
            errors.append("lighter_client.api_client attribute does not exist")
        elif self.lighter_client.api_client is None:
            errors.append("api_client is None")
        elif not hasattr(self.lighter_client.api_client, 'rest_client'):
            errors.append("api_client.rest_client attribute does not exist")
        elif self.lighter_client.api_client.rest_client is None:
            errors.append("rest_client is None")

        if errors:
            # 003-fix-lighter-sdk US1 T015-T016: 记录详细的错误消息和对象状态
            self.logger.log(f"[LIGHTER] SDK validation failed: {', '.join(errors)}", "ERROR")
            self._log_sdk_object_states()
            return False

        self.logger.log("[LIGHTER] SDK validation passed: all objects initialized", "INFO")
        self._log_sdk_object_states()
        return True

    def _get_sdk_object_state(self) -> Dict[str, Dict[str, Any]]:
        """获取SDK对象状态快照

        Returns:
            Dict[str, Dict[str, Any]]: 包含每个对象状态的字典

        003-fix-lighter-sdk US1 T013: 获取对象状态快照
        """
        state = {}

        # 检查lighter_client状态
        if self.lighter_client is None:
            state['lighter_client'] = {'exists': False, 'type': None}
        else:
            state['lighter_client'] = {
                'exists': True,
                'type': type(self.lighter_client).__name__
            }

            # 检查api_client状态
            if hasattr(self.lighter_client, 'api_client'):
                if self.lighter_client.api_client is None:
                    state['api_client'] = {'exists': False, 'type': None}
                else:
                    state['api_client'] = {
                        'exists': True,
                        'type': type(self.lighter_client.api_client).__name__
                    }

                    # 检查rest_client状态
                    if hasattr(self.lighter_client.api_client, 'rest_client'):
                        if self.lighter_client.api_client.rest_client is None:
                            state['rest_client'] = {'exists': False, 'type': None}
                        else:
                            state['rest_client'] = {
                                'exists': True,
                                'type': type(self.lighter_client.api_client.rest_client).__name__
                            }
                    else:
                        state['rest_client'] = {'exists': False, 'type': 'attribute missing'}
            else:
                state['api_client'] = {'exists': False, 'type': 'attribute missing'}
                state['rest_client'] = {'exists': False, 'type': 'unknown'}

        return state

    def _log_sdk_object_states(self) -> None:
        """记录SDK对象状态到日志

        003-fix-lighter-sdk US1 T016: 记录每个对象的类型和存在状态
        """
        state = self._get_sdk_object_state()

        for obj_name, obj_state in state.items():
            if obj_state['exists']:
                self.logger.log(
                    f"[LIGHTER] SDK Object: {obj_name} = {obj_state['type']} ✓",
                    "INFO"
                )
            else:
                self.logger.log(
                    f"[LIGHTER] SDK Object: {obj_name} = {obj_state.get('type', 'None')} ✗",
                    "ERROR"
                )

    def _log_sdk_state_snapshot(self) -> None:
        """记录完整的SDK状态快照到日志

        003-fix-lighter-sdk US2 T020: 格式化输出对象状态
        """
        import time
        timestamp = time.time()

        self.logger.log("=" * 60, "INFO")
        self.logger.log(f"[LIGHTER] SDK State Snapshot at {timestamp}", "INFO")
        self.logger.log("-" * 60, "INFO")

        state = self._get_sdk_object_state()
        for obj_name, obj_state in state.items():
            status_symbol = "✓" if obj_state['exists'] else "✗"
            obj_type = obj_state.get('type', 'None')
            self.logger.log(
                f"  {status_symbol} {obj_name}: {obj_type}",
                "INFO" if obj_state['exists'] else "ERROR"
            )

        # 判断整体状态
        failed_objects = [name for name, state in state.items() if not state['exists']]
        if failed_objects:
            overall_status = f"Failed: {', '.join(failed_objects)}"
            self.logger.log(f"Overall: {overall_status}", "ERROR")
        else:
            self.logger.log("Overall: Healthy - all objects initialized", "INFO")

        self.logger.log("=" * 60, "INFO")

    async def check_sdk_health(self):
        """检查SDK健康状态

        Returns:
            SDKHealthStatus: SDK健康状态对象

        003-fix-lighter-sdk US3 T027: 检查所有对象和API可用性
        """
        import time
        errors = []

        # 检查对象存在性
        if self.lighter_client is None:
            errors.append("lighter_client is None")
        elif not hasattr(self.lighter_client, 'api_client'):
            errors.append("lighter_client.api_client attribute does not exist")
        elif self.lighter_client.api_client is None:
            errors.append("api_client is None")
        elif not hasattr(self.lighter_client.api_client, 'rest_client'):
            errors.append("api_client.rest_client attribute does not exist")
        elif self.lighter_client.api_client.rest_client is None:
            errors.append("rest_client is None")

        if errors:
            return SDKHealthStatus(
                healthy=False,
                errors=errors,
                timestamp=time.time()
            )

        # 检查API可用性
        try:
            err = self.lighter_client.check_client()
            if err is not None:
                errors.append(f"CheckClient failed: {err}")
                return SDKHealthStatus(
                    healthy=False,
                    errors=errors,
                    timestamp=time.time()
                )
        except Exception as e:
            errors.append(f"CheckClient exception: {type(e).__name__}: {e}")
            return SDKHealthStatus(
                healthy=False,
                errors=errors,
                timestamp=time.time()
            )

        return SDKHealthStatus(
            healthy=True,
            errors=[],
            timestamp=time.time()
        )

    # ========================================================================
    # End 003-fix-lighter-sdk
    # ========================================================================

    async def connect(self) -> None:
        """Connect to Lighter."""
        try:
            # 🔴 FIX: 配置代理支持 - 从环境变量获取代理设置
            # 检查环境变量中的代理设置
            https_proxy = os.getenv('https_proxy') or os.getenv('HTTPS_PROXY')
            http_proxy = os.getenv('http_proxy') or os.getenv('HTTP_PROXY')
            proxy_url = https_proxy or http_proxy

            # 创建配置对象
            config = Configuration(host=self.base_url)

            # 如果存在代理设置，则应用
            if proxy_url:
                config.proxy = proxy_url
                self.logger.log(f"Using proxy: {proxy_url}", "INFO")

            # Initialize shared API client with proxy configuration
            self.api_client = ApiClient(configuration=config)

            # 🔴 FIX: 在初始化 Lighter client 之前，先获取 contract_id
            # 因为 _initialize_lighter_client() 和后续代码需要 contract_id
            if not hasattr(self.config, 'contract_id') or self.config.contract_id is None:
                self.logger.log(f"[LIGHTER] 获取 contract_id for {self.config.ticker}...", "INFO")
                contract_id, tick_size = await self.get_contract_attributes()
                self.logger.log(f"[LIGHTER] contract_id={contract_id}, tick_size={tick_size}", "INFO")

            # Initialize Lighter client
            await self._initialize_lighter_client()

            # Add market config to config for WebSocket manager
            self.config.market_index = self.config.contract_id
            self.config.account_index = self.account_index
            self.config.lighter_client = self.lighter_client

            # Initialize WebSocket manager (using custom implementation)
            self.ws_manager = LighterCustomWebSocketManager(
                config=self.config,
                order_update_callback=self._handle_websocket_order_update
            )

            # Set logger for WebSocket manager
            self.ws_manager.set_logger(self.logger)

            # Start WebSocket connection in background task
            asyncio.create_task(self.ws_manager.connect())
            # Wait a moment for connection to establish
            await asyncio.sleep(2)

        except Exception as e:
            self.logger.log(f"Error connecting to Lighter: {e}", "ERROR")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Lighter."""
        try:
            if hasattr(self, 'ws_manager') and self.ws_manager:
                await self.ws_manager.disconnect()

            # Close shared API client
            if self.api_client:
                await self.api_client.close()
                self.api_client = None
        except Exception as e:
            self.logger.log(f"Error during Lighter disconnect: {e}", "ERROR")

    def get_exchange_name(self) -> str:
        """Get the exchange name."""
        return "lighter"

    def setup_order_update_handler(self, handler) -> None:
        """Setup order update handler for WebSocket."""
        self._order_update_handler = handler

    def _handle_websocket_order_update(self, order_data_list: List[Dict[str, Any]]):
        """Handle order updates from WebSocket."""
        for order_data in order_data_list:
            if order_data['market_index'] != self.config.contract_id:
                continue

            side = 'sell' if order_data['is_ask'] else 'buy'
            if side == self.config.close_order_side:
                order_type = "CLOSE"
            else:
                order_type = "OPEN"

            order_id = order_data['order_index']
            status = order_data['status'].upper()
            filled_size = Decimal(order_data['filled_base_amount'])
            size = Decimal(order_data['initial_base_amount'])
            price = Decimal(order_data['price'])
            remaining_size = Decimal(order_data['remaining_base_amount'])

            if order_id in self.orders_cache.keys():
                if (self.orders_cache[order_id]['status'] == 'OPEN' and
                        status == 'OPEN' and
                        filled_size == self.orders_cache[order_id]['filled_size']):
                    continue
                elif status in ['FILLED', 'CANCELED']:
                    del self.orders_cache[order_id]
                else:
                    self.orders_cache[order_id]['status'] = status
                    self.orders_cache[order_id]['filled_size'] = filled_size
            elif status == 'OPEN':
                self.orders_cache[order_id] = {'status': status, 'filled_size': filled_size}

            if status == 'OPEN' and filled_size > 0:
                status = 'PARTIALLY_FILLED'

            if status == 'OPEN':
                self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                f"{size} @ {price}", "INFO")
            else:
                self.logger.log(f"[{order_type}] [{order_id}] {status} "
                                f"{filled_size} @ {price}", "INFO")

            # 🔴 FIX: 只有当订单ID匹配时才更新current_order
            # BUG: 之前使用 `or order_type == 'OPEN'` 会导致任何OPEN订单都设置current_order
            # 这可能导致误将其他订单的状态当作当前订单状态
            if order_data['client_order_index'] == self.current_order_client_id:
                current_order = OrderInfo(
                    order_id=order_id,
                    side=side,
                    size=size,
                    price=price,
                    status=status,
                    filled_size=filled_size,
                    remaining_size=remaining_size,
                    cancel_reason=''
                )
                self.current_order = current_order
                self.logger.log(f"[订单匹配] order_id={order_id}, status={status}, filled={filled_size}", "DEBUG")

            if status in ['FILLED', 'CANCELED']:
                self.logger.log_transaction(order_id, side, filled_size, price, status)

    @query_retry(default_return=(0, 0))
    async def fetch_bbo_prices(self, contract_id: str) -> Tuple[Decimal, Decimal]:
        """Get orderbook using official SDK."""
        # Use WebSocket data if available
        if (hasattr(self, 'ws_manager') and
                self.ws_manager.best_bid and self.ws_manager.best_ask):
            best_bid = Decimal(str(self.ws_manager.best_bid))
            best_ask = Decimal(str(self.ws_manager.best_ask))

            if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
                self.logger.log("Invalid bid/ask prices", "ERROR")
                raise ValueError("Invalid bid/ask prices")
        else:
            self.logger.log("Unable to get bid/ask prices from WebSocket.", "ERROR")
            raise ValueError("WebSocket not running. No bid/ask prices available")

        return best_bid, best_ask

    async def _submit_order_with_retry(self, order_params: Dict[str, Any]) -> OrderResult:
        """Submit an order with Lighter using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            # This is a sync method, so we need to handle this differently
            # For now, raise an error if client is not initialized
            raise ValueError("Lighter client not initialized. Call connect() first.")

        # Create order using official SDK
        try:
            # 🔴 DEBUG: 打印order_params内容以诊断问题
            self.logger.log(f"[DEBUG] order_params: {order_params}", "INFO")
            self.logger.log(f"[DEBUG] lighter_client类型: {type(self.lighter_client)}", "INFO")
            self.logger.log(f"[DEBUG] lighter_client存在: {self.lighter_client is not None}", "INFO")

            # 003-fix-lighter-sdk: 验证contract_id已正确设置
            if not hasattr(self.config, 'contract_id') or self.config.contract_id is None:
                error_msg = "contract_id is not set! Call get_contract_attributes() before placing orders."
                self.logger.log(f"[LIGHTER] ERROR: {error_msg}", "ERROR")
                self.logger.log(f"[LIGHTER] ERROR: config attributes: {dir(self.config)}", "ERROR")
                return OrderResult(
                    success=False,
                    order_id=str(order_params.get('client_order_index', 'unknown')),
                    error_message=error_msg
                )

            self.logger.log(f"[DEBUG] contract_id已设置: {self.config.contract_id}", "INFO")

            # 检查客户端的api_client和tx_api状态
            self.logger.log(f"[DEBUG] api_client存在: {hasattr(self.lighter_client, 'api_client') and self.lighter_client.api_client is not None}", "INFO")
            if hasattr(self.lighter_client, 'api_client') and self.lighter_client.api_client:
                self.logger.log(f"[DEBUG] api_client配置: {self.lighter_client.api_client.configuration}", "INFO")

            # 003-fix-lighter-sdk: 验证SDK的market_info是否已加载
            if hasattr(self.config, 'market_info') and self.config.market_info is not None:
                self.logger.log(f"[DEBUG] market_info已加载: symbol={self.config.market_info.symbol}, market_id={self.config.market_info.market_id}", "INFO")
            else:
                self.logger.log(f"[LIGHTER] WARNING: market_info未加载，这可能导致SDK查找market失败", "WARNING")

            create_order, tx_hash, error = await self.lighter_client.create_order(**order_params)

            self.logger.log(f"[DEBUG] create_order返回: create_order={create_order}, tx_hash={tx_hash}, error={error}", "INFO")

            if error is not None:
                return OrderResult(
                    success=False, order_id=str(order_params['client_order_index']),
                    error_message=f"Order creation error: {error}")

            else:
                return OrderResult(success=True, order_id=str(order_params['client_order_index']))
        except lighter.exceptions.BadRequestException as e:
            # 捕获400错误（通常是请求参数错误）
            self.logger.log(f"[LIGHTER] ERROR: BadRequestException (400) in create_order", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: Exception: {e}", "ERROR")
            if hasattr(e, 'body') and e.body:
                self.logger.log(f"[LIGHTER] ERROR: Response body: {e.body}", "ERROR")
            if hasattr(e, 'data') and e.data:
                self.logger.log(f"[LIGHTER] ERROR: Response data: {e.data}", "ERROR")
            # 记录SDK状态快照
            self._log_sdk_state_snapshot()
            return OrderResult(
                success=False,
                order_id=str(order_params.get('client_order_index', 'unknown')),
                error_message=f"BadRequestException (400): {str(e)}"
            )
        except lighter.exceptions.ServiceException as e:
            # 捕获500错误（服务器错误）
            self.logger.log(f"[LIGHTER] ERROR: ServiceException (500-599) in create_order", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: Exception: {e}", "ERROR")
            if hasattr(e, 'status'):
                self.logger.log(f"[LIGHTER] ERROR: HTTP Status: {e.status}", "ERROR")
            if hasattr(e, 'body') and e.body:
                self.logger.log(f"[LIGHTER] ERROR: Response body: {e.body}", "ERROR")
            # 记录SDK状态快照
            self._log_sdk_state_snapshot()
            return OrderResult(
                success=False,
                order_id=str(order_params.get('client_order_index', 'unknown')),
                error_message=f"ServiceException (500): {str(e)}"
            )
        except lighter.exceptions.UnauthorizedException as e:
            # 捕获401错误（认证错误）
            self.logger.log(f"[LIGHTER] ERROR: UnauthorizedException (401) in create_order", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: Exception: {e}", "ERROR")
            # 记录SDK状态快照
            self._log_sdk_state_snapshot()
            return OrderResult(
                success=False,
                order_id=str(order_params.get('client_order_index', 'unknown')),
                error_message=f"UnauthorizedException (401): Authentication failed"
            )
        except AttributeError as e:
            # 捕获AttributeError（SDK内部错误，通常是ret.code访问失败）
            self.logger.log(f"[LIGHTER] ERROR: AttributeError in create_order - SDK内部错误", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: Exception: {e}", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: 这通常表示send_tx返回了None，可能是网络连接或API服务器问题", "ERROR")
            # 记录SDK状态快照
            self._log_sdk_state_snapshot()
            return OrderResult(
                success=False,
                order_id=str(order_params.get('client_order_index', 'unknown')),
                error_message=f"SDK内部错误: {str(e)} - 可能是网络连接问题或API服务器不可用"
            )
        except Exception as e:
            # 001-fix-lighter-trading T015: 增强错误捕获，记录完整SDK异常堆栈
            import traceback
            error_type = type(e).__name__
            error_msg = str(e)
            stack_trace = traceback.format_exc()

            # 003-fix-lighter-sdk US2 T021-T022: 记录SDK状态快照
            self.logger.log(f"[LIGHTER] ERROR: SDK exception in create_order", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: Exception type: {error_type}", "ERROR")
            self.logger.log(f"[LIGHTER] ERROR: Exception message: {error_msg}", "ERROR")

            # 记录SDK状态快照
            self._log_sdk_state_snapshot()

            self.logger.log(f"[LIGHTER] ERROR: Stack trace:\n{stack_trace}", "ERROR")

            # 返回包含详细错误信息的OrderResult
            return OrderResult(
                success=False,
                order_id=str(order_params.get('client_order_index', 'unknown')),
                error_message=f"SDK exception: {error_type}: {error_msg}"
            )

    async def place_limit_order(self, contract_id: str, quantity: Decimal, price: Decimal,
                                side: str) -> OrderResult:
        """Place a post only order with Lighter using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Determine order side and price
        if side.lower() == 'buy':
            is_ask = False
        elif side.lower() == 'sell':
            is_ask = True
        else:
            raise Exception(f"Invalid side: {side}")

        # Generate unique client order index
        client_order_index = int(time.time() * 1000) % 1000000  # Simple unique ID
        self.current_order_client_id = client_order_index

        # Create order parameters
        order_params = {
            'market_index': self.config.contract_id,
            'client_order_index': client_order_index,
            'base_amount': int(quantity * self.base_amount_multiplier),
            'price': int(price * self.price_multiplier),
            'is_ask': is_ask,
            'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
            'time_in_force': self.lighter_client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,  # 011-fix-lighter-hedge: IOC
            'reduce_only': False,
            'trigger_price': 0,
        }

        order_result = await self._submit_order_with_retry(order_params)
        return order_result

    async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
        """Place an open order with Lighter using official SDK.

        011-fix-lighter-hedge: Now uses IOC orders - returns immediately after placement.
        No wait loop - order will either fill or cancel immediately.
        """
        import time
        start = time.time()

        self.current_order = None
        self.current_order_client_id = None

        self.logger.log(f"[Lighter开仓] 开始获取价格，已耗时 {time.time() - start:.2f}s", "INFO")
        order_price = await self.get_order_price(direction)
        self.logger.log(f"[Lighter开仓] 获取价格完成，已耗时 {time.time() - start:.2f}s", "INFO")

        order_price = self.round_to_tick(order_price)

        self.logger.log(f"[Lighter开仓] 调用 place_limit_order 前，已耗时 {time.time() - start:.2f}s", "INFO")
        order_result = await self.place_limit_order(contract_id, quantity, order_price, direction)
        self.logger.log(f"[Lighter开仓] place_limit_order 完成，已耗时 {time.time() - start:.2f}s", "INFO")

        if not order_result.success:
            raise Exception(f"[OPEN] Error placing order: {order_result.error_message}")

        # 011-fix-lighter-hedge: Wait briefly (0.5s) for WebSocket update, not 10s
        # IOC orders should execute immediately, but we wait a short time for WebSocket callback
        self.logger.log(f"[Lighter开仓] 等待 WebSocket 更新前，已耗时 {time.time() - start:.2f}s", "INFO")
        await asyncio.sleep(0.5)
        self.logger.log(f"[Lighter开仓] WebSocket 等待完成，已耗时 {time.time() - start:.2f}s", "INFO")

        # Return immediately - IOC order is either filled or cancelled
        if self.current_order is not None:
            # 🔴 FIX: 只有当order_id存在时，才认为订单有效
            # 如果order_id为None，说明WebSocket回调可能有问题，应该查询API验证
            if self.current_order.order_id is not None:
                return OrderResult(
                    success=(self.current_order.status == 'FILLED'),
                    order_id=self.current_order.order_id,
                    side=direction,
                    size=quantity,
                    price=order_price,
                    status=self.current_order.status
                )
            else:
                # 🔴 FIX: 013-fix-order-timeout - order_id为None是无效状态
                # 问题: 之前的代码继续执行，最终可能返回success=True, order_id=None
                # 解决: 直接返回失败，不继续查询API（使用临时ID查询不到真正的订单）
                self.logger.log(
                    f"[警告] current_order存在但order_id为None，status={self.current_order.status}，直接返回失败",
                    level="WARNING"
                )
                return OrderResult(
                    success=False,
                    order_id=None,
                    side=direction,
                    size=Decimal('0'),
                    price=order_price,
                    status='FAILED',
                    error_message='No order_id in callback - cannot verify order status'
                )
        else:
            # No WebSocket update yet - query order status to verify if filled
            # IOC orders should either fill immediately or be cancelled
            # 🔴 FIX: get_active_orders() returns empty list, use get_inactive_orders() instead
            try:
                # Query inactive orders (filled/cancelled) to verify if order was filled
                # Note: get_active_orders() returns empty list for Lighter
                inactive_orders = await self.get_inactive_orders(contract_id)

                filled_order = None
                for order in inactive_orders:
                    if order.order_id == order_result.order_id:
                        filled_order = order
                        break

                if filled_order and filled_order.status == 'FILLED':
                    # Order was filled but WebSocket callback was delayed
                    self.logger.log(
                        f"[订单查询] order_id={order_result.order_id} 在inactive订单中找到，状态=FILLED",
                        "INFO"
                    )
                    return OrderResult(
                        success=True,
                        order_id=filled_order.order_id,
                        side=direction,
                        size=filled_order.filled_size,  # Use actual filled size
                        price=order_price,
                        status='FILLED'
                    )
                else:
                    # IOC order was not filled - it was rejected or cancelled
                    # 🔴 IMPORTANT: 对于IOC订单，如果在inactive订单中找不到或状态不是FILLED，
                    # 说明订单没有成交，应该返回失败
                    self.logger.log(
                        f"[订单查询] order_id={order_result.order_id} 未成交 "
                        f"(在inactive订单中{'找到但状态=' + filled_order.status if filled_order else '未找到'})",
                        "WARNING"
                    )
                    return OrderResult(
                        success=False,
                        order_id=order_result.order_id,
                        side=direction,
                        size=Decimal('0'),  # No fill
                        price=order_price,
                        status='CANCELLED',
                        error_message='IOC order not filled within 0.5s and not found in inactive orders'
                    )
            except Exception as e:
                # If query fails, assume order failed for safety
                self.logger.log(f"[订单查询] 查询失败: {str(e)}", "ERROR")
                return OrderResult(
                    success=False,
                    order_id=order_result.order_id,
                    side=direction,
                    size=Decimal('0'),
                    price=order_price,
                    status='FAILED',
                    error_message=f'Failed to query order status: {str(e)}'
                )

    async def _get_active_close_orders(self, contract_id: str) -> int:
        """Get active close orders for a contract using official SDK."""
        active_orders = await self.get_active_orders(contract_id)
        active_close_orders = 0
        for order in active_orders:
            if order.side == self.config.close_order_side:
                active_close_orders += 1
        return active_close_orders

    async def place_close_order(self, contract_id: str, quantity: Decimal, price: Decimal, side: str) -> OrderResult:
        """Place a close order with Lighter using official SDK."""
        self.current_order = None
        self.current_order_client_id = None
        order_result = await self.place_limit_order(contract_id, quantity, price, side)

        # wait for 5 seconds to ensure order is placed
        await asyncio.sleep(5)
        if order_result.success:
            return OrderResult(
                success=True,
                order_id=order_result.order_id,
                side=side,
                size=quantity,
                price=price,
                status='OPEN'
            )
        else:
            raise Exception(f"[CLOSE] Error placing order: {order_result.error_message}")
    
    async def get_order_price(self, side: str = '') -> Decimal:
        """Get the price of an order with Lighter using official SDK."""
        # Get current market prices
        best_bid, best_ask = await self.fetch_bbo_prices(self.config.contract_id)
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            self.logger.log("Invalid bid/ask prices", "ERROR")
            raise ValueError("Invalid bid/ask prices")

        order_price = (best_bid + best_ask) / 2

        active_orders = await self.get_active_orders(self.config.contract_id)
        close_orders = [order for order in active_orders if order.side == self.config.close_order_side]
        for order in close_orders:
            if side == 'buy':
                order_price = min(order_price, order.price - self.config.tick_size)
            else:
                order_price = max(order_price, order.price + self.config.tick_size)

        return order_price

    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order with Lighter."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Cancel order using official SDK
        cancel_order, tx_hash, error = await self.lighter_client.cancel_order(
            market_index=self.config.contract_id,
            order_index=int(order_id)  # Assuming order_id is the order index
        )

        if error is not None:
            return OrderResult(success=False, error_message=f"Cancel order error: {error}")

        if tx_hash:
            return OrderResult(success=True)
        else:
            return OrderResult(success=False, error_message='Failed to send cancellation transaction')

    async def get_order_info(self, order_id: str) -> Optional[OrderInfo]:
        """Get order information from Lighter.

        注意：order_id是client_order_index，而API返回的是order_index。
        使用self.current_order来获取最新订单信息（由WebSocket更新）。

        修复：增加更多诊断日志和fallback机制来解决"无法获取订单信息"问题。
        """
        try:
            self.logger.log(
                f"[get_order_info] 查询订单信息: order_id={order_id}, "
                f"current_order存在={self.current_order is not None}, "
                f"current_order_client_id={getattr(self, 'current_order_client_id', None)}",
                "DEBUG"
            )

            # 首先检查current_order（由WebSocket实时更新）
            if self.current_order is not None:
                self.logger.log(
                    f"[get_order_info] current_order详情: "
                    f"order_id={self.current_order.order_id}, "
                    f"status={self.current_order.status}, "
                    f"side={self.current_order.side}, "
                    f"size={self.current_order.filled_size}",
                    "DEBUG"
                )

                # 验证订单ID是否匹配
                if self.current_order.order_id == order_id:
                    # current_order包含最新的订单信息
                    self.logger.log(f"[get_order_info] ✅ ID匹配，返回current_order", "DEBUG")
                    return self.current_order
                else:
                    self.logger.log(
                        f"⚠️ current_order ID不匹配: 期望={order_id}, 实际={self.current_order.order_id}",
                        "WARNING"
                    )

                    # 尝试匹配client_order_id
                    if hasattr(self, 'current_order_client_id') and self.current_order_client_id:
                        self.logger.log(
                            f"[get_order_info] 尝试匹配client_order_id: "
                            f"期望={order_id}, 当前={self.current_order_client_id}",
                            "DEBUG"
                        )
                        # client_order_id可能存储为字符串或整数
                        if str(self.current_order_client_id) == str(order_id):
                            self.logger.log(f"[get_order_info] ✅ client_order_id匹配，返回current_order", "DEBUG")
                            return self.current_order

            # Fallback 1: 检查最近的WebSocket更新（通过时间戳）
            if hasattr(self, '_last_order_update_time') and self._last_order_update_time:
                time_since_update = time.time() - self._last_order_update_time
                if time_since_update < 2.0:  # 2秒内有更新
                    self.logger.log(
                        f"[get_order_info] ⚠️ 最近的WebSocket更新可能是我们要找的订单 "
                        f"({time_since_update:.1f}秒前)，但ID不匹配",
                        "WARNING"
                    )

            # Fallback 2: 如果current_order不可用，尝试从活跃订单查询
            self.logger.log(f"🔍 current_order不可用，尝试查询所有订单（活跃+已成交）", "DEBUG")

            try:
                # 先查询活跃订单
                active_orders = await self.get_active_orders(self.config.contract_id)

                # 同时查询已成交订单
                inactive_orders = await self.get_inactive_orders(self.config.contract_id)

                # 合并所有订单
                all_orders = active_orders + inactive_orders

                if all_orders:
                    self.logger.log(f"[get_order_info] 找到 {len(all_orders)} 个订单", "DEBUG")

                    # 尝试通过client_order_index匹配
                    for order_info in all_orders:
                        if str(order_info.order_id) == str(order_id):
                            self.logger.log(f"[get_order_info] ✅ 在订单列表中找到匹配", "DEBUG")
                            return order_info

                    # 如果没有精确匹配，返回最新的订单（可能是刚下的单）
                    # 按时间排序（如果有时间戳）
                    latest_order = all_orders[0]
                    self.logger.log(
                        f"[get_order_info] ⚠️ 没有精确匹配，返回最新订单: "
                        f"order_id={latest_order.order_id}, status={latest_order.status}",
                        "WARNING"
                    )
                    return latest_order
            except Exception as e:
                self.logger.log(f"[get_order_info] 查询订单列表失败: {e}", "ERROR")

            # Fallback 3: 如果还是没有，检查positions
            self.logger.log(f"🔍 订单查询失败，尝试从持仓推断订单信息", "DEBUG")
            try:
                account_api = lighter.AccountApi(self.api_client)
                account_data = await account_api.account(by="index", value=str(self.account_index))

                for position in account_data.positions:
                    if position.symbol == self.config.ticker:
                        position_amt = abs(float(position.position))
                        if position_amt > 0.001:
                            self.logger.log(
                                f"📊 从持仓推断订单信息: {position_amt:.4f} @ {position.avg_price:.2f}",
                                "DEBUG"
                            )
                            return OrderInfo(
                                order_id=order_id,
                                side="buy" if float(position.position) > 0 else "sell",
                                size=Decimal(str(position_amt)),
                                price=Decimal(str(position.avg_price)),
                                status="FILLED",
                                filled_size=Decimal(str(position_amt)),
                                remaining_size=Decimal('0')
                            )
            except Exception as e:
                self.logger.log(f"[get_order_info] 查询持仓失败: {e}", "ERROR")

            # 所有方法都失败
            self.logger.log(
                f"❌ 无法获取订单信息: order_id={order_id}, "
                f"current_order={self.current_order.order_id if self.current_order else None}, "
                f"client_order_id={getattr(self, 'current_order_client_id', None)}",
                "ERROR"
            )
            return None

        except Exception as e:
            self.logger.log(f"❌ get_order_info异常: {e}", "ERROR")
            import traceback
            self.logger.log(f"堆栈跟踪: {traceback.format_exc()}", "ERROR")
            return None

    @query_retry(reraise=True)
    async def _fetch_orders_with_retry(self) -> List[Dict[str, Any]]:
        """Get inactive (filled/cancelled) orders using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Generate auth token for API call
        auth_token, error = self.lighter_client.create_auth_token_with_expiry()
        if error is not None:
            self.logger.log(f"Error creating auth token: {error}", "ERROR")
            raise ValueError(f"Error creating auth token: {error}")

        # Use OrderApi to get inactive orders (filled/cancelled)
        order_api = lighter.OrderApi(self.api_client)

        # Get inactive orders for the specific market
        # limit参数是必需的，设置为100以获取足够的历史订单
        orders_response = await order_api.account_inactive_orders(
            account_index=self.account_index,
            market_id=self.config.contract_id,
            auth=auth_token,
            limit=100
        )

        if not orders_response:
            self.logger.log("Failed to get inactive orders", "ERROR")
            raise ValueError("Failed to get inactive orders")

        return orders_response.orders

    async def get_active_orders(self, contract_id: str) -> List[OrderInfo]:
        """Get active orders for a contract using official SDK.

        注意：Lighter的API没有活跃订单端点，所以这里返回空列表。
        活跃订单应该通过WebSocket的current_order来获取。
        """
        # Lighter的活跃订单通过WebSocket实时更新，存储在current_order中
        # API端点只返回已成交/已取消的订单
        return []

    async def get_inactive_orders(self, contract_id: str) -> List[OrderInfo]:
        """Get inactive (filled/cancelled) orders for a contract using official SDK."""
        order_list = await self._fetch_orders_with_retry()

        # Convert Lighter Order to OrderInfo
        contract_orders = []
        for order in order_list:
            # Convert Lighter Order to OrderInfo
            side = "sell" if order.is_ask else "buy"
            size = Decimal(order.initial_base_amount)
            price = Decimal(order.price)

            contract_orders.append(OrderInfo(
                order_id=str(order.order_index),
                side=side,
                size=Decimal(order.initial_base_amount),
                price=price,
                status=order.status.upper(),
                filled_size=Decimal(order.filled_base_amount),
                remaining_size=Decimal(order.remaining_base_amount)
            ))

        return contract_orders

    @query_retry(reraise=True)
    async def _fetch_positions_with_retry(self) -> List[Dict[str, Any]]:
        """Get positions using official SDK."""
        # Use shared API client
        account_api = lighter.AccountApi(self.api_client)

        # Get account info
        account_data = await account_api.account(by="index", value=str(self.account_index))

        if not account_data or not account_data.accounts:
            self.logger.log("Failed to get positions", "ERROR")
            raise ValueError("Failed to get positions")

        return account_data.accounts[0].positions

    async def get_account_positions(self) -> Decimal:
        """Get account positions using official SDK."""
        # Get account info which includes positions
        positions = await self._fetch_positions_with_retry()

        # Find position for current market
        for position in positions:
            if position.market_id == self.config.contract_id:
                return Decimal(position.position)

        return Decimal(0)

    async def get_contract_attributes(self) -> Tuple[str, Decimal]:
        """Get contract ID for a ticker."""
        ticker = self.config.ticker
        if len(ticker) == 0:
            self.logger.log("Ticker is empty", "ERROR")
            raise ValueError("Ticker is empty")

        # 使用 requests 直接调用 REST API,避免 SDK 的 Pydantic 验证问题
        # 参考对冲模式的实现 (hedge_mode_ext.py)
        import requests
        
        url = f"{self.base_url}/api/v1/orderBooks"
        headers = {"accept": "application/json"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            if not response.text.strip():
                raise ValueError("Empty response from Lighter API")
            
            data = response.json()
            
            if "order_books" not in data:
                raise ValueError("Unexpected response format")
            
            # 查找匹配的市场
            for market in data["order_books"]:
                if market["symbol"] == ticker:
                    market_id = market["market_id"]
                    self.base_amount_multiplier = pow(10, market["supported_size_decimals"])
                    self.price_multiplier = pow(10, market["supported_price_decimals"])
                    tick_size = Decimal("1") / (Decimal("10") ** market["supported_price_decimals"])
                    
                    # 设置配置
                    self.config.contract_id = market_id
                    self.config.tick_size = tick_size
                    
                    self.logger.log(
                        f"Contract found: ID={market_id}, tick_size={tick_size}",
                        "INFO"
                    )
                    
                    return market_id, tick_size
            
            raise ValueError(f"Ticker {ticker} not found in available markets")
            
        except Exception as e:
            self.logger.log(f"Error getting contract attributes: {e}", "ERROR")
            raise
