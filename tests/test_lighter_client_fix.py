"""
Lighter Client Fix Tests

测试Lighter交易所客户端的修复，包括：
1. 代理配置正确应用
2. SDK初始化成功
3. AttributeError异常捕获和记录
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal

from exchanges.lighter import LighterClient
from spread.config import SpreadArbConfig


class TestLighterProxyConfiguration:
    """测试代理配置正确应用"""

    @pytest.mark.asyncio
    async def test_proxy_configuration_applied_to_rest_client(self):
        """测试代理配置正确应用到rest_client"""
        env_vars = {
            'https_proxy': 'http://proxy.example.com:8080',
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0  # ETH market_id

            client = LighterClient(config)

            # Mock SignerClient and ApiClient
            with patch('exchanges.lighter.SignerClient') as mock_signer_class, \
                 patch('exchanges.lighter.ApiClient') as mock_api_client_class:

                # 创建mock对象
                mock_signer = Mock()
                mock_api_client = Mock()
                mock_rest_client = Mock()

                mock_signer_class.return_value = mock_signer
                mock_api_client_class.return_value = mock_api_client
                mock_signer.check_client.return_value = None  # 成功
                mock_signer.api_client = mock_api_client
                mock_api_client.rest_client = mock_rest_client

                # 初始化客户端
                await client._initialize_lighter_client()

                # 验证代理设置
                assert mock_rest_client.proxy == 'http://proxy.example.com:8080'

    @pytest.mark.asyncio
    async def test_proxy_configuration_with_delayed_rest_client(self):
        """测试rest_client延迟创建时的代理设置"""
        env_vars = {
            'https_proxy': 'http://proxy.example.com:8080',
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)

            with patch('exchanges.lighter.SignerClient') as mock_signer_class, \
                 patch('exchanges.lighter.ApiClient') as mock_api_client_class:

                mock_signer = Mock()
                mock_api_client = Mock()
                mock_rest_client = Mock()

                mock_signer_class.return_value = mock_signer
                mock_api_client_class.return_value = mock_api_client
                mock_signer.check_client.return_value = None
                mock_signer.api_client = mock_api_client

                # 模拟rest_client延迟创建
                type(mock_api_client).rest_client = None

                # 初始化客户端
                await client._initialize_lighter_client()

                # 验证至少尝试设置configuration.proxy
                assert mock_api_client.configuration.proxy == 'http://proxy.example.com:8080'


class TestLighterSDKInitialization:
    """测试SDK初始化成功"""

    @pytest.mark.asyncio
    async def test_check_client_returns_none_on_success(self):
        """测试check_client返回None表示成功"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)

            with patch('exchanges.lighter.SignerClient') as mock_signer_class:
                mock_signer = Mock()
                mock_signer_class.return_value = mock_signer
                mock_signer.check_client.return_value = None  # 成功

                # 初始化应该成功
                result = await client._initialize_lighter_client()
                assert result is not None
                assert mock_signer.check_client.called

    @pytest.mark.asyncio
    async def test_check_client_raises_on_error(self):
        """测试check_client返回错误时抛出异常"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)

            with patch('exchanges.lighter.SignerClient') as mock_signer_class:
                mock_signer = Mock()
                mock_signer_class.return_value = mock_signer
                mock_signer.check_client.return_value = "Connection error"

                # 初始化应该抛出异常
                with pytest.raises(Exception) as exc_info:
                    await client._initialize_lighter_client()

                assert "CheckClient error" in str(exc_info.value)


class TestLighterErrorHandling:
    """测试AttributeError异常捕获和记录"""

    @pytest.mark.asyncio
    async def test_attribute_error_in_place_open_order_is_caught(self):
        """测试place_open_order中的AttributeError被正确捕获"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0
            config.tick_size = Decimal('0.1')  # 添加tick_size属性

            client = LighterClient(config)
            client.lighter_client = Mock()
            client.base_amount_multiplier = 1
            client.price_multiplier = 1
            client.current_order_client_id = 12345
            client.current_order = None

            # Mock fetch_bbo_prices返回有效价格
            client.fetch_bbo_prices = AsyncMock(return_value=(Decimal('3000'), Decimal('3001')))

            # 模拟create_order抛出AttributeError
            client.lighter_client.create_order = Mock(
                side_effect=AttributeError("'NoneType' object has no attribute 'code'")
            )

            # 调用place_open_order应该抛出异常，且异常消息包含AttributeError
            with pytest.raises(Exception) as exc_info:
                await client.place_open_order(
                    contract_id=0,
                    quantity=Decimal('0.01'),
                    direction='buy'
                )

            # 验证异常消息包含SDK异常信息
            assert "AttributeError" in str(exc_info.value)
            assert "'NoneType' object has no attribute 'code'" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_message_contains_exception_type(self):
        """测试错误消息包含异常类型"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0
            config.tick_size = Decimal('0.1')  # 添加tick_size属性

            client = LighterClient(config)
            client.lighter_client = Mock()
            client.base_amount_multiplier = 1
            client.price_multiplier = 1
            client.current_order_client_id = 12345
            client.current_order = None

            # Mock fetch_bbo_prices返回有效价格
            client.fetch_bbo_prices = AsyncMock(return_value=(Decimal('3000'), Decimal('3001')))

            # 模拟SDK异常
            client.lighter_client.create_order = Mock(
                side_effect=AttributeError("'NoneType' object has no attribute 'code'")
            )

            # 验证异常被正确抛出并包含正确的错误信息
            with pytest.raises(Exception) as exc_info:
                await client.place_open_order(
                    contract_id=0,
                    quantity=Decimal('0.01'),
                    direction='buy'
                )

            # 验证错误消息格式包含SDK exception和AttributeError
            error_msg = str(exc_info.value)
            assert "OPEN" in error_msg  # 应该包含[OPEN]标记
            assert "SDK exception" in error_msg or "AttributeError" in error_msg
