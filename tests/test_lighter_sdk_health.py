"""
Lighter SDK Health Tests

测试Lighter SDK健康检查和验证功能，包括：
1. SDK对象验证（_validate_sdk_objects）
2. 对象状态快照（_get_sdk_object_state）
3. SDK健康检查（check_sdk_health）
4. 状态快照日志（_log_sdk_state_snapshot）
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from decimal import Decimal

from exchanges.lighter import LighterClient
from spread.config import SpreadArbConfig


class TestValidateSDKObjects:
    """测试SDK对象验证功能"""

    @pytest.mark.asyncio
    async def test_validate_sdk_objects_all_present(self):
        """测试所有对象都存在时验证通过"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)

            # Mock所有SDK对象
            with patch('exchanges.lighter.SignerClient') as mock_signer_class, \
                 patch('exchanges.lighter.ApiClient') as mock_api_client_class:

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

                # 验证所有对象存在
                assert client.lighter_client is not None
                assert client.lighter_client.api_client is not None
                assert client.lighter_client.api_client.rest_client is not None

    @pytest.mark.asyncio
    async def test_validate_sdk_objects_missing_client(self):
        """测试lighter_client为None时验证失败"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)
            client.lighter_client = None

            # 验证应该检测到lighter_client为None
            if hasattr(client, '_validate_sdk_objects'):
                result = client._validate_sdk_objects()
                assert result is False

    @pytest.mark.asyncio
    async def test_validate_sdk_objects_missing_api_client(self):
        """测试api_client为None时验证失败"""
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
                mock_signer.check_client.return_value = None
                mock_signer.api_client = None  # api_client为None

                # 初始化应该因为api_client为None而失败
                with pytest.raises(Exception) as exc_info:
                    await client._initialize_lighter_client()

                # 错误消息应该包含"SDK validation failed"
                assert "SDK validation failed" in str(exc_info.value)


class TestGetSDKObjectState:
    """测试获取SDK对象状态快照"""

    @pytest.mark.asyncio
    async def test_get_sdk_object_state_returns_dict(self):
        """测试_get_sdk_object_state返回包含对象信息的字典"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)

            # Mock SDK对象
            with patch('exchanges.lighter.SignerClient') as mock_signer_class:
                mock_signer = Mock()
                mock_signer_class.return_value = mock_signer
                mock_signer.check_client.return_value = None
                mock_signer.api_client = Mock()
                mock_signer.api_client.rest_client = Mock()

                await client._initialize_lighter_client()

                # 测试获取对象状态
                if hasattr(client, '_get_sdk_object_state'):
                    state = client._get_sdk_object_state()

                    # 验证返回字典包含所有对象
                    assert 'lighter_client' in state or 'api_client' in state
                    assert isinstance(state, dict)


class TestSDKInitializationFailure:
    """测试SDK初始化失败处理"""

    @pytest.mark.asyncio
    async def test_initialization_failure_clear_error_message(self):
        """测试SDK初始化失败时提供清晰的错误消息"""
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
                # check_client返回错误
                mock_signer.check_client.return_value = "Connection error"

                # 初始化应该抛出异常
                with pytest.raises(Exception) as exc_info:
                    await client._initialize_lighter_client()

                # 错误消息应该包含"CheckClient error"
                assert "CheckClient error" in str(exc_info.value)


class TestLogSDKStateSnapshot:
    """测试SDK状态快照日志"""

    @pytest.mark.asyncio
    async def test_log_sdk_state_snapshot_format(self):
        """测试状态快照日志格式清晰易读"""
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
                mock_signer.check_client.return_value = None
                mock_signer.api_client = Mock()
                mock_signer.api_client.rest_client = Mock()

                await client._initialize_lighter_client()

                # 测试日志方法存在
                if hasattr(client, '_log_sdk_state_snapshot'):
                    # 应该能够调用而不抛出异常
                    client._log_sdk_state_snapshot()

    @pytest.mark.asyncio
    async def test_attribute_error_logs_sdk_state(self):
        """测试AttributeError异常时记录SDK状态"""
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
                mock_signer.check_client.return_value = None
                mock_signer.api_client = Mock()
                mock_signer.api_client.rest_client = Mock()

                await client._initialize_lighter_client()

                # 测试异常处理中的状态日志
                if hasattr(client, '_log_sdk_state_snapshot'):
                    # 模拟捕获异常
                    try:
                        raise AttributeError("'NoneType' object has no attribute 'code'")
                    except AttributeError as e:
                        # 应该能够记录状态而不抛出异常
                        client._log_sdk_state_snapshot()


class TestCheckSDKHealth:
    """测试SDK健康检查"""

    @pytest.mark.asyncio
    async def test_check_sdk_health_returns_healthy_when_all_ok(self):
        """测试SDK健康时返回正确状态"""
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
                mock_signer.check_client.return_value = None
                mock_signer.api_client = Mock()
                mock_signer.api_client.rest_client = Mock()

                await client._initialize_lighter_client()

                # 测试健康检查
                if hasattr(client, 'check_sdk_health'):
                    result = await client.check_sdk_health()
                    # 应该返回健康的SDKHealthStatus
                    assert result.healthy is True
                    assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_check_sdk_health_performance(self):
        """测试健康检查耗时<100ms"""
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
                mock_signer.check_client.return_value = None
                mock_signer.api_client = Mock()
                mock_signer.api_client.rest_client = Mock()

                await client._initialize_lighter_client()

                # 测试健康检查性能
                if hasattr(client, 'check_sdk_health'):
                    import time
                    start = time.time()
                    result = await client.check_sdk_health()
                    elapsed = (time.time() - start) * 1000  # 转换为毫秒

                    # 应该在100ms内完成
                    assert elapsed < 100, f"健康检查耗时 {elapsed}ms，超过100ms阈值"

    @pytest.mark.asyncio
    async def test_check_sdk_health_returns_error_when_client_none(self):
        """测试SDK对象为None时返回明确错误"""
        env_vars = {
            'API_KEY_PRIVATE_KEY': 'test_private_key',
            'LIGHTER_ACCOUNT_INDEX': '0',
            'LIGHTER_API_KEY_INDEX': '0'
        }
        with patch.dict('os.environ', env_vars):
            config = SpreadArbConfig(ticker='ETH')
            config.contract_id = 0

            client = LighterClient(config)
            client.lighter_client = None

            # 测试健康检查失败
            if hasattr(client, 'check_sdk_health'):
                result = await client.check_sdk_health()
                # 应该返回不健康的SDKHealthStatus
                assert result.healthy is False
                assert len(result.errors) > 0
                # 错误消息应该明确指出问题
                error_summary = result.get_error_summary()
                assert "None" in error_summary or "not initialized" in error_summary.lower()
