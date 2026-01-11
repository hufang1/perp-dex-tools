"""
IocOrderManager单元测试

测试011-async-ws-ioc-trading的IOC订单管理器功能
"""

import pytest
from decimal import Decimal

from spread.config import SpreadArbConfig
from spread.ioc_order_manager import IocOrderManager


@pytest.fixture
def config():
    """创建测试配置"""
    return SpreadArbConfig(
        ioc_slippage_tolerance_rate=Decimal('0.0005'),  # 0.05%
        ticker='ETH',
        use_ioc_orders=True
    )


@pytest.fixture
def ioc_manager(config):
    """创建测试用的IOC订单管理器"""
    return IocOrderManager(config)


class TestIocOrderManagerBasics:
    """测试IOC订单管理器基础功能"""

    def test_initialization(self, config):
        """测试初始化"""
        manager = IocOrderManager(config)
        assert manager.config == config

    def test_create_ioc_order_buy_extended(self, ioc_manager):
        """测试创建Extended买入IOC订单"""
        price = Decimal('3000.00')
        quantity = Decimal('0.1')

        order = ioc_manager.create_ioc_order(
            exchange='extended',
            side='buy',
            price=price,
            quantity=quantity
        )

        assert order['side'] == 'buy'
        assert order['type'] == 'LIMIT'
        assert order['timeInForce'] == 'IOC'
        assert order['postOnly'] is False
        assert Decimal(order['quantity']) == quantity
        # 价格应该高于基础价格（买入激进）
        assert Decimal(order['price']) > price

    def test_create_ioc_order_sell_extended(self, ioc_manager):
        """测试创建Extended卖出IOC订单"""
        price = Decimal('3000.00')
        quantity = Decimal('0.1')

        order = ioc_manager.create_ioc_order(
            exchange='extended',
            side='sell',
            price=price,
            quantity=quantity
        )

        assert order['side'] == 'sell'
        assert order['timeInForce'] == 'IOC'
        # 价格应该低于基础价格（卖出激进）
        assert Decimal(order['price']) < price

    def test_create_ioc_order_lighter(self, ioc_manager):
        """测试创建Lighter IOC订单（使用下划线命名）"""
        price = Decimal('3000.00')
        quantity = Decimal('0.1')

        order = ioc_manager.create_ioc_order(
            exchange='lighter',
            side='buy',
            price=price,
            quantity=quantity
        )

        assert order['side'] == 'buy'
        assert order['time_in_force'] == 'IOC'  # Lighter使用下划线
        assert order['post_only'] is False

    def test_create_ioc_order_invalid_exchange(self, ioc_manager):
        """测试无效交易所名称"""
        with pytest.raises(ValueError):
            ioc_manager.create_ioc_order(
                exchange='invalid',
                side='buy',
                price=Decimal('3000'),
                quantity=Decimal('0.1')
            )


class TestCalculateIocPrice:
    """测试IOC价格计算"""

    def test_calculate_ioc_price_buy(self, ioc_manager):
        """测试计算买入IOC价格"""
        base_price = Decimal('3000.00')
        slippage = Decimal('0.0005')  # 0.05%

        ioc_price = ioc_manager.calculate_ioc_price(base_price, 'buy', slippage)

        # 买入价格 = 基础价 * (1 + 滑点容忍度)
        # 3000 * 1.0005 = 3001.5
        expected = base_price * (Decimal('1') + slippage)
        assert ioc_price == expected
        assert ioc_price > base_price

    def test_calculate_ioc_price_sell(self, ioc_manager):
        """测试计算卖出IOC价格"""
        base_price = Decimal('3000.00')
        slippage = Decimal('0.0005')  # 0.05%

        ioc_price = ioc_manager.calculate_ioc_price(base_price, 'sell', slippage)

        # 卖出价格 = 基础价 * (1 - 滑点容忍度)
        # 3000 * 0.9995 = 2998.5
        expected = base_price * (Decimal('1') - slippage)
        assert ioc_price == expected
        assert ioc_price < base_price

    def test_calculate_ioc_price_different_slippage(self, ioc_manager):
        """测试不同滑点容忍度"""
        base_price = Decimal('3000.00')

        price_low_slip = ioc_manager.calculate_ioc_price(
            base_price, 'buy', Decimal('0.0001')
        )
        price_high_slip = ioc_manager.calculate_ioc_price(
            base_price, 'buy', Decimal('0.0010')
        )

        assert price_high_slip > price_low_slip
        assert price_low_slip > base_price


class TestHandlePartialFill:
    """测试部分成交处理"""

    def test_handle_full_fill(self, ioc_manager):
        """测试完全成交"""
        order_result = {
            'status': 'filled',
            'executed_qty': '0.1',
            'avg_price': '3000.50'
        }
        expected_qty = Decimal('0.1')

        result = ioc_manager.handle_partial_fill(order_result, expected_qty)

        assert result['success'] is True
        assert result['filled_qty'] == Decimal('0.1')
        assert result['avg_price'] == Decimal('3000.50')
        assert result['is_partial'] is False
        assert result['unfilled_qty'] == Decimal('0')

    def test_handle_partial_fill(self, ioc_manager):
        """测试部分成交"""
        order_result = {
            'status': 'partially_filled',
            'executed_qty': '0.05',  # 只成交了一半
            'avg_price': '3000.50'
        }
        expected_qty = Decimal('0.1')

        result = ioc_manager.handle_partial_fill(order_result, expected_qty)

        assert result['success'] is True
        assert result['filled_qty'] == Decimal('0.05')
        assert result['is_partial'] is True
        assert result['unfilled_qty'] == Decimal('0.05')

    def test_handle_no_fill(self, ioc_manager):
        """测试完全未成交"""
        order_result = {
            'status': 'expired',  # IOC过期未成交
        }
        expected_qty = Decimal('0.1')

        result = ioc_manager.handle_partial_fill(order_result, expected_qty)

        assert result['success'] is False
        assert result['filled_qty'] == Decimal('0')
        assert result['is_partial'] is False
        assert result['unfilled_qty'] == expected_qty


class TestWarningLogs:
    """测试警告日志"""

    def test_log_partial_fill_warning(self, ioc_manager, caplog):
        """测试记录部分成交警告"""
        import logging
        caplog.set_level(logging.WARNING)

        result = {
            'success': True,
            'filled_qty': Decimal('0.05'),
            'avg_price': Decimal('3000.50'),
            'is_partial': True,
            'unfilled_qty': Decimal('0.05')
        }

        ioc_manager.log_partial_fill_warning(result, 'extended')

        assert '部分成交' in caplog.text
        assert 'extended' in caplog.text
        assert '0.05' in caplog.text

    def test_log_no_fill_warning(self, ioc_manager, caplog):
        """测试记录完全未成交警告"""
        import logging
        caplog.set_level(logging.ERROR)

        ioc_manager.log_no_fill_warning('lighter', Decimal('0.1'))

        assert '完全未成交' in caplog.text
        assert 'lighter' in caplog.text
        assert '0.1' in caplog.text


class TestCustomSlippageTolerance:
    """测试自定义滑点容忍度"""

    def test_create_ioc_order_custom_slippage(self, ioc_manager):
        """测试使用自定义滑点容忍度"""
        custom_slippage = Decimal('0.0010')  # 0.10%，比默认高

        order = ioc_manager.create_ioc_order(
            exchange='extended',
            side='buy',
            price=Decimal('3000'),
            quantity=Decimal('0.1'),
            slippage_tolerance=custom_slippage
        )

        # 验证价格使用自定义滑点
        # 3000 * 1.001 = 3003
        expected_price = Decimal('3000') * (Decimal('1') + custom_slippage)
        assert Decimal(order['price']) == expected_price
