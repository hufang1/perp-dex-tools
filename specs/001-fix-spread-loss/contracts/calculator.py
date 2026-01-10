# Calculator Interface Contract

**Module**: `spread/calculator.py`
**Version**: 2.0 (修复后)
**Date**: 2026-01-10

## 接口定义

### calculate_spread_opportunity()

计算价差套利机会，返回最优策略或None。

```python
def calculate_spread_opportunity(
    extended_bid: Decimal,
    extended_ask: Decimal,
    lighter_bid: Decimal,
    lighter_ask: Decimal,
    extended_mid_price: Optional[Decimal] = None
) -> Optional[Dict[str, Any]]:
    """
    计算价差套利机会（修复版）

    修复内容：
    1. 做多机会：lighter_price = lighter_ask（卖一价）
    2. 做空机会：lighter_price = lighter_bid（买一价）
    3. 做空价差率：spread_rate = spread / extended_ask

    Args:
        extended_bid: Extended最佳买价
        extended_ask: Extended最佳卖价
        lighter_bid: Lighter最佳买价
        lighter_ask: Lighter最佳卖价
        extended_mid_price: Extended中间价（用于计算数量）

    Returns:
        套利机会字典，如果没有机会则返回None

        {
            'type': 'buy_extended_sell_lighter' | 'sell_extended_buy_lighter',
            'side': 'buy' | 'sell',              # Extended方向
            'spread': Decimal,                    # 绝对价差
            'spread_rate': Decimal,               # 价差率
            'expected_profit_rate': Decimal,      # 预期利润率
            'extended_price': Decimal,            # Extended挂单价格
            'lighter_price': Decimal,             # Lighter预期成交价格
            'quantity': Decimal,                  # 建议下单量
            'maker_timeout_ms': int,              # maker单超时时间
            'use_maker_order': bool               # 是否使用maker单
        }

    Raises:
        无异常抛出

    Examples:
        >>> calc = SpreadCalculator(config)
        >>> opp = calc.calculate_spread_opportunity(
        ...     extended_bid=Decimal('3090.00'),
        ...     extended_ask=Decimal('3095.00'),
        ...     lighter_bid=Decimal('3098.00'),
        ...     lighter_ask=Decimal('3103.00')
        ... )
        >>> assert opp['type'] == 'buy_extended_sell_lighter'
        >>> assert opp['lighter_price'] == Decimal('3103.00')  # 卖一价！
        >>> assert opp['spread_rate'] == Decimal('3103') - Decimal('3090') / Decimal('3090')
    """
```

## 行为契约

### 做多机会（buy_extended_sell_lighter）

**条件**: `extended_bid < lighter_ask`

**返回值**:
```python
{
    'type': 'buy_extended_sell_lighter',
    'side': 'buy',
    'spread': lighter_ask - extended_bid,
    'spread_rate': (lighter_ask - extended_bid) / extended_bid,  # 分母是extended_bid
    'expected_profit_rate': spread_rate - latency_buffer,
    'extended_price': extended_bid,      # 在买一挂maker单
    'lighter_price': lighter_ask,       # ✅ 修复：使用卖一价
    'quantity': order_quantity_usdt / extended_mid_price
}
```

**验证**:
```python
# 只在Extended买一 < Lighter卖一时开多仓
assert extended_bid < lighter_ask
assert opportunity['lighter_price'] == lighter_ask
```

### 做空机会（sell_extended_buy_lighter）

**条件**: `extended_ask > lighter_bid`

**返回值**:
```python
{
    'type': 'sell_extended_buy_lighter',
    'side': 'sell',
    'spread': extended_ask - lighter_bid,
    'spread_rate': (extended_ask - lighter_bid) / extended_ask,  # ✅ 修复：分母是extended_ask
    'expected_profit_rate': spread_rate - latency_buffer,
    'extended_price': extended_ask,      # 在卖一挂maker单
    'lighter_price': lighter_bid,       # ✅ 修复：使用买一价
    'quantity': order_quantity_usdt / extended_mid_price
}
```

**验证**:
```python
# 只在Extended卖一 > Lighter买一时开空仓
assert extended_ask > lighter_bid
assert opportunity['lighter_price'] == lighter_bid
# ✅ 分母修正
assert opportunity['spread_rate'] == (extended_ask - lighter_bid) / extended_ask
```

## 修复前后对比

### 做多机会

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| 条件 | `lighter_bid > extended_bid` | `extended_bid < lighter_ask` |
| lighter_price | `lighter_bid` ❌ | `lighter_ask` ✅ |
| 含义 | 在Lighter买一卖出？ | 在Lighter卖一卖出 ✅ |

### 做空机会

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| 条件 | `extended_ask > lighter_ask` | `extended_ask > lighter_bid` |
| lighter_price | `lighter_ask` ❌ | `lighter_bid` ✅ |
| spread_rate分母 | `lighter_ask` ❌ | `extended_ask` ✅ |
| 含义 | 在Lighter卖一买入？ | 在Lighter买一买入 ✅ |

## 测试契约

### 单元测试要求

```python
def test_long_opportunity_uses_correct_prices():
    """验证做多机会使用正确价格"""
    calc = SpreadCalculator(config)

    # Given: Extended买一 < Lighter卖一
    extended_bid = Decimal('3090.00')
    lighter_ask = Decimal('3103.00')

    # When: 计算机会
    opp = calc.calculate_spread_opportunity(
        extended_bid=extended_bid,
        extended_ask=Decimal('3095.00'),
        lighter_bid=Decimal('3098.00'),
        lighter_ask=lighter_ask
    )

    # Then: 使用lighter_ask作为Lighter卖出价
    assert opp is not None
    assert opp['type'] == 'buy_extended_sell_lighter'
    assert opp['lighter_price'] == lighter_ask

def test_short_opportunity_uses_correct_denominator():
    """验证做空机会价差率使用正确分母"""
    calc = SpreadCalculator(config)

    # Given: Extended卖一 > Lighter买一
    extended_ask = Decimal('3105.00')
    lighter_bid = Decimal('3090.00')

    # When: 计算机会
    opp = calc.calculate_spread_opportunity(
        extended_bid=Decimal('3095.00'),
        extended_ask=extended_ask,
        lighter_bid=lighter_bid,
        lighter_ask=Decimal('3098.00')
    )

    # Then: 价差率分母是extended_ask
    expected_rate = (extended_ask - lighter_bid) / extended_ask
    assert opp is not None
    assert opp['spread_rate'] == expected_rate
    assert opp['lighter_price'] == lighter_bid
```

## 性能要求

- **执行时间**: < 1ms
- **内存占用**: < 1KB per call
- **无副作用**: 不修改输入参数

## 版本兼容性

- **输入格式**: 与v1.0兼容
- **输出格式**: 新增`maker_timeout_ms`和`use_maker_order`字段
- **迁移路径**: v1.0调用者无需修改（新增字段可选）
