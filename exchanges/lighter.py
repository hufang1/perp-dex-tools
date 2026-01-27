"""
Lighter exchange client implementation.
"""

import os
import asyncio
import time
import logging
import warnings
import traceback
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

from .base import BaseExchangeClient, OrderResult, OrderInfo, query_retry
from helpers.logger import TradingLogger

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
        """Initialize the Lighter client using official SDK."""
        if self.lighter_client is None:
            try:
                self.lighter_client = SignerClient(
                    url=self.base_url,
                    private_key=self.api_key_private_key,
                    account_index=self.account_index,
                    api_key_index=self.api_key_index,
                )

                # Check client
                err = self.lighter_client.check_client()
                if err is not None:
                    raise Exception(f"CheckClient error: {err}")

                self.logger.log("Lighter client initialized successfully", "INFO")
            except Exception as e:
                self.logger.log(f"Failed to initialize Lighter client: {e}", "ERROR")
                raise
        return self.lighter_client

    async def connect(self) -> None:
        """Connect to Lighter."""
        try:
            # Initialize shared API client
            self.api_client = ApiClient(configuration=Configuration(host=self.base_url))

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

            if order_data['client_order_index'] == self.current_order_client_id or order_type == 'OPEN':
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
        create_order, tx_hash, error = await self.lighter_client.create_order(**order_params)
        if error is not None:
            return OrderResult(
                success=False, order_id=str(order_params['client_order_index']),
                error_message=f"Order creation error: {error}")

        else:
            return OrderResult(success=True, order_id=str(order_params['client_order_index']))

    async def place_limit_order(self, contract_id: str, quantity: Decimal, price: Decimal,
                                side: str, time_in_force: int = None, reduce_only: bool = False) -> OrderResult:
        """Place a limit order with Lighter using official SDK.

        Args:
            contract_id: Market/contract ID
            quantity: Order quantity
            price: Order price
            side: 'buy' or 'sell'
            time_in_force: Time in force (0=IOC, 1=GTT, 2=POST_ONLY). Default=1 (GTT)
        """
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Ensure market config is loaded (multipliers are set)
        if self.base_amount_multiplier is None or self.price_multiplier is None:
            ticker = self.config.ticker
            await self._get_market_config(ticker)

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

        # Use provided time_in_force or default to GTT
        if time_in_force is None:
            time_in_force = self.lighter_client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME

        # For IOC orders, use 0 expiry; for others, use default 28-day expiry
        order_expiry = 0 if time_in_force == 0 else -1

        # Create order parameters
        order_params = {
            'market_index': self.config.contract_id,
            'client_order_index': client_order_index,
            'base_amount': int(quantity * self.base_amount_multiplier),
            'price': int(price * self.price_multiplier),
            'is_ask': is_ask,
            'order_type': self.lighter_client.ORDER_TYPE_LIMIT,
            'time_in_force': time_in_force,
            'reduce_only': reduce_only,
            'trigger_price': 0,
            'order_expiry': order_expiry,
        }

        order_result = await self._submit_order_with_retry(order_params)
        return order_result

    async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
        """
        ⚠️ DEPRECATED: 此方法使用Maker模式（中间价+GTT+等待循环）

        此方法将于未来版本移除。

        请使用以下Taker模式替代：
        - spread套利：使用 trade_executor._place_lighter_order_taker()
        - 直接调用：使用 place_limit_order(..., time_in_force=0)

        Migration Guide:
        - 旧代码：await client.place_open_order(contract_id, qty, direction)
        - 新代码：await client.place_limit_order(contract_id, qty, ask*1.002 or bid*0.998, direction, time_in_force=0)

        Args:
            contract_id: 合约ID
            quantity: 数量
            direction: 方向 ('buy' or 'sell')

        Returns:
            OrderResult: 订单结果
        """
        warnings.warn(
            "place_open_order is DEPRECATED and uses Maker mode. "
            "Use Taker mode with time_in_force=0 instead. "
            "This method will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2
        )

        self.current_order = None
        self.current_order_client_id = None
        order_price = await self.get_order_price(direction)

        order_price = self.round_to_tick(order_price)
        order_result = await self.place_limit_order(contract_id, quantity, order_price, direction)
        if not order_result.success:
            raise Exception(f"[OPEN] Error placing order: {order_result.error_message}")

        start_time = time.time()
        order_status = 'OPEN'

        # While waiting for order to be filled
        while time.time() - start_time < 10 and order_status != 'FILLED':
            await asyncio.sleep(0.1)
            if self.current_order is not None:
                order_status = self.current_order.status

        return OrderResult(
            success=True,
            order_id=self.current_order.order_id,
            side=direction,
            size=quantity,
            price=order_price,
            status=self.current_order.status
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
        """
        ⚠️ DEPRECATED: 此方法使用中间价计算，不适合Taker模式

        此方法将于未来版本移除。

        Migration Guide:
        - Taker买入价：best_ask * 1.002
        - Taker卖出价：best_bid * 0.998

        Args:
            side: 方向

        Returns:
            Decimal: 订单价格（中间价）
        """
        warnings.warn(
            "get_order_price is DEPRECATED. "
            "For Taker mode, use: ask*1.002 (buy) or bid*0.998 (sell). "
            "This method will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2
        )

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
        """Get order information from Lighter using official SDK."""
        try:
            # Use shared API client to get account info
            account_api = lighter.AccountApi(self.api_client)

            # Get account orders
            account_data = await account_api.account(by="index", value=str(self.account_index))

            # Look for the specific order in account positions
            for position in account_data.positions:
                if position.symbol == self.config.ticker:
                    position_amt = abs(float(position.position))
                    if position_amt > 0.001:  # Only include significant positions
                        return OrderInfo(
                            order_id=order_id,
                            side="buy" if float(position.position) > 0 else "sell",
                            size=Decimal(str(position_amt)),
                            price=Decimal(str(position.avg_price)),
                            status="FILLED",  # Positions are filled orders
                            filled_size=Decimal(str(position_amt)),
                            remaining_size=Decimal('0')
                        )

            return None

        except Exception as e:
            self.logger.log(f"Error getting order info: {e}", "ERROR")
            return None

    @query_retry(reraise=True)
    async def _fetch_orders_with_retry(self) -> List[Dict[str, Any]]:
        """Get orders using official SDK."""
        # Ensure client is initialized
        if self.lighter_client is None:
            await self._initialize_lighter_client()

        # Generate auth token for API call
        auth_token, error = self.lighter_client.create_auth_token_with_expiry()
        if error is not None:
            self.logger.log(f"Error creating auth token: {error}", "ERROR")
            raise ValueError(f"Error creating auth token: {error}")

        # Use OrderApi to get active orders
        order_api = lighter.OrderApi(self.api_client)

        # Get active orders for the specific market
        orders_response = await order_api.account_active_orders(
            account_index=self.account_index,
            market_id=self.config.contract_id,
            auth=auth_token
        )

        if not orders_response:
            self.logger.log("Failed to get orders", "ERROR")
            raise ValueError("Failed to get orders")

        return orders_response.orders

    async def get_active_orders(self, contract_id: str) -> List[OrderInfo]:
        """Get active orders for a contract using official SDK."""
        order_list = await self._fetch_orders_with_retry()

        # Filter orders for the specific market
        contract_orders = []
        for order in order_list:
            # Convert Lighter Order to OrderInfo
            side = "sell" if order.is_ask else "buy"
            size = Decimal(order.initial_base_amount)
            price = Decimal(order.price)

            # Only include orders with remaining size > 0
            if size > 0:
                contract_orders.append(OrderInfo(
                    order_id=str(order.order_index),
                    side=side,
                    size=Decimal(order.remaining_base_amount),  # FIXME: This is wrong. Should be size
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
        """
        Get account positions using official SDK.

        Returns:
            Decimal: 持仓数量（绝对值）
        """
        result = await self.get_detailed_position()
        return result['quantity']

    async def get_detailed_position(self) -> Dict[str, Any]:
        """
        获取详细的仓位信息，包括平均开仓价格

        Returns:
            Dict containing:
            - quantity: 持仓数量（绝对值）
            - avg_price: 平均开仓价格
            - market_id: 市场ID
        """
        try:
            # Get account info which includes positions
            positions = await self._fetch_positions_with_retry()

            self.logger.log(
                f"[get_detailed_position] 查询到 {len(positions)} 个仓位",
                "DEBUG"
            )

            # Find position for current market
            for position in positions:
                if position.market_id == self.config.contract_id:
                    # 返回绝对值（仓位大小），与 extended.py 保持一致
                    pos_value = position.position
                    if isinstance(pos_value, float):
                        quantity = abs(Decimal(str(pos_value)))
                    else:
                        quantity = abs(Decimal(pos_value))

                    # 获取平均开仓价格（兼容不同字段名）
                    avg_price = Decimal('0')
                    found_attrs = []
                    for attr in ['avg_price', 'average_price', 'avg_entry_price', 'average_entry_price', 'entry_price']:
                        if hasattr(position, attr):
                            found_attrs.append(attr)
                            price_value = getattr(position, attr)
                            if price_value is not None and price_value != 0:
                                avg_price = Decimal(str(price_value))
                                break

                    if avg_price > 0:
                        self.logger.log(
                            f"[get_detailed_position] 找到仓位 | "
                            f"market_id={position.market_id} | "
                            f"quantity={quantity} | "
                            f"avg_price={avg_price} | fields={found_attrs}",
                            "INFO"
                        )
                    else:
                        self.logger.log(
                            f"[get_detailed_position] 找到仓位但未取到均价 | "
                            f"market_id={position.market_id} | "
                            f"quantity={quantity} | "
                            f"fields={found_attrs} | attrs={dir(position)}",
                            "WARNING"
                        )

                    return {
                        'quantity': quantity,
                        'avg_price': avg_price,
                        'market_id': position.market_id
                    }

            self.logger.log(
                f"[get_detailed_position] 未找到market_id={self.config.contract_id}的仓位",
                "WARNING"
            )

            return {
                'quantity': Decimal('0'),
                'avg_price': Decimal('0'),
                'market_id': self.config.contract_id
            }

        except Exception as e:
            self.logger.log(
                f"[get_detailed_position] 查询失败: {e} | "
                f"traceback={traceback.format_exc()}",
                "ERROR"
            )
            return {
                'quantity': Decimal('0'),
                'avg_price': Decimal('0'),
                'market_id': self.config.contract_id
            }

    async def get_contract_attributes(self) -> Tuple[str, Decimal]:
        """Get contract ID for a ticker."""
        ticker = self.config.ticker
        if len(ticker) == 0:
            self.logger.log("Ticker is empty", "ERROR")
            raise ValueError("Ticker is empty")

        # Use direct HTTP request to avoid SDK validation issues with 'inactive' status
        import requests
        lighter_base_url = "https://mainnet.zklighter.elliot.ai"
        lighter_market_url = f"{lighter_base_url}/api/v1/orderBooks"

        try:
            response = requests.get(lighter_market_url, headers={"accept": "application/json"}, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Find the market that matches our ticker
            market_info = None
            for market in data.get("order_books", []):
                if market["symbol"] == ticker:
                    market_info = market
                    break

            if market_info is None:
                self.logger.log(f"Market {ticker} not found", "ERROR")
                raise ValueError(f"Market {ticker} not found")

            # Set contract_id to market_id (Lighter uses market IDs as identifiers)
            market_id = market_info["market_id"]
            self.config.contract_id = market_id

            # Get multipliers from market info
            supported_size_decimals = market_info.get("supported_size_decimals", 2)
            supported_price_decimals = market_info.get("supported_price_decimals", 2)
            self.base_amount_multiplier = pow(10, supported_size_decimals)
            self.price_multiplier = pow(10, supported_price_decimals)

            # Calculate tick size from price decimals
            self.config.tick_size = Decimal("1") / (Decimal("10") ** supported_price_decimals)

            self.logger.log(
                f"Lighter contract attributes: market_id={market_id}, "
                f"tick_size={self.config.tick_size}, "
                f"base_amount_multiplier={self.base_amount_multiplier}, "
                f"price_multiplier={self.price_multiplier}",
                "INFO"
            )

            return self.config.contract_id, self.config.tick_size

        except Exception as e:
            self.logger.log(f"Failed to get contract attributes: {e}", "ERROR")
            raise
