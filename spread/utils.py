"""
工具函数：Lighter-Extended 单向价差收敛套利系统

通用工具函数，包括 VWAP 计算、价格验证等
"""

from decimal import Decimal, getcontext, ROUND_DOWN
from typing import Dict, Tuple, Optional
from datetime import datetime
import uuid

# 设置 Decimal 精度
getcontext().prec = 18


def calculate_vwap(
    order_book: Dict[Decimal, Decimal],
    target_quantity: Decimal,
    side: str
) -> Optional[Decimal]:
    """
    计算成交量加权平均价 (VWAP)

    VWAP 计算方法：从订单簿的最优价格开始，累积成交量直到达到目标数量，
    然后计算加权平均价格。

    Args:
        order_book: 订单簿，{价格: 数量}
        target_quantity: 目标交易数量
        side: "buy" 或 "sell"

    Returns:
        VWAP 价格，如果深度不足则返回 None

    Examples:
        >>> order_book = {
        ...     Decimal("100.0"): Decimal("1.0"),
        ...     Decimal("101.0"): Decimal("2.0"),
        ...     Decimal("102.0"): Decimal("3.0")
        ... }
        >>> calculate_vwap(order_book, Decimal("2.0"), "buy")
        Decimal("100.5")
    """
    if not order_book or target_quantity <= 0:
        return None

    remaining = target_quantity
    total_value = Decimal("0")
    total_qty = Decimal("0")

    # 对于买入，从最低价格开始（升序）
    # 对于卖出，从最高价格开始（降序）
    sorted_prices = sorted(order_book.keys(), reverse=(side == "sell"))

    for price in sorted_prices:
        if remaining <= 0:
            break

        available_qty = order_book[price]
        if available_qty <= 0:
            continue

        # 取当前价格层级的最小可用数量
        take_qty = min(remaining, available_qty)

        total_value += price * take_qty
        total_qty += take_qty
        remaining -= take_qty

    # 检查是否达到目标数量
    if remaining > 0:
        return None

    # 计算 VWAP
    vwap = total_value / total_qty
    return vwap.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def validate_price(price: Decimal) -> bool:
    """
    验证价格的有效性

    Args:
        price: 待验证的价格

    Returns:
        True 如果价格有效，否则 False
    """
    if price is None:
        return False
    try:
        price_decimal = Decimal(str(price))
        return price_decimal > 0
    except (ValueError, TypeError):
        return False


def validate_quantity(quantity: Decimal) -> bool:
    """
    验证数量的有效性

    Args:
        quantity: 待验证的数量

    Returns:
        True 如果数量有效，否则 False
    """
    if quantity is None:
        return False
    try:
        qty_decimal = Decimal(str(quantity))
        return qty_decimal > 0
    except (ValueError, TypeError):
        return False


def validate_spread(spread: Decimal, max_spread: Decimal) -> bool:
    """
    验证价差的合理性

    Args:
        spread: 价差值（小数形式，如 0.02 表示 2%）
        max_spread: 允许的最大价差

    Returns:
        True 如果价差合理，否则 False
    """
    if spread is None:
        return False

    try:
        spread_decimal = Decimal(str(spread))
        max_spread_decimal = Decimal(str(max_spread))

        # 价差必须在 [0, max_spread] 范围内
        return Decimal("0") <= spread_decimal <= max_spread_decimal
    except (ValueError, TypeError):
        return False


def calculate_spread_percentage(
    price1: Decimal,
    price2: Decimal
) -> Optional[Decimal]:
    """
    计算两个价格之间的价差百分比

    公式：(price1 - price2) / price2

    Args:
        price1: 价格1（分子）
        price2: 价格2（分母，基准价格）

    Returns:
        价差百分比（小数形式），如 0.02 表示 2%
        如果计算失败则返回 None
    """
    if not validate_price(price1) or not validate_price(price2):
        return None

    if price2 == 0:
        return None

    try:
        spread = (price1 - price2) / price2
        return spread.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def format_decimal(value: Decimal, precision: int = 2) -> str:
    """
    格式化 Decimal 为字符串

    Args:
        value: Decimal 值
        precision: 小数位数

    Returns:
        格式化后的字符串
    """
    if value is None:
        return "0.00"

    try:
        quantizer = Decimal("0." + "0" * precision)
        return str(value.quantize(quantizer, rounding=ROUND_DOWN))
    except (ValueError, TypeError):
        return "0.00"


def generate_trade_id() -> str:
    """
    生成唯一的交易 ID

    Returns:
        格式为 "TRADE-{timestamp}-{uuid}" 的唯一 ID
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"TRADE-{timestamp}-{unique_id}"


def depth_is_sufficient(
    order_book: Dict[Decimal, Decimal],
    required_quantity: Decimal,
    side: str
) -> bool:
    """
    检查订单簿深度是否足够

    Args:
        order_book: 订单簿，{价格: 数量}
        required_quantity: 需要的数量
        side: "buy" 或 "sell"

    Returns:
        True 如果深度足够，否则 False
    """
    if not order_book or required_quantity <= 0:
        return False

    total_quantity = sum(order_book.values())
    return total_quantity >= required_quantity


def get_available_liquidity(
    order_book: Dict[Decimal, Decimal],
    side: str
) -> Decimal:
    """
    获取订单簿的可用流动性

    Args:
        order_book: 订单簿，{价格: 数量}
        side: "buy" 或 "sell"

    Returns:
        可用总数量
    """
    if not order_book:
        return Decimal("0")

    return sum(order_book.values())


def calculate_profit(
    entry_spread: Decimal,
    exit_spread: Decimal,
    quantity: Decimal,
    entry_price: Decimal,
    fees: Decimal = Decimal("0.0005")  # 默认 0.05%（双向手续费）
) -> Decimal:
    """
    计算套利利润

    Args:
        entry_spread: 开仓价差（小数形式）
        exit_spread: 平仓价差（小数形式）
        quantity: 交易数量
        entry_price: 开仓基准价格
        fees: 手续费率（默认 0.05%）

    Returns:
        利润值
    """
    try:
        # 价差收敛利润
        spread_profit = (entry_spread - exit_spread) * entry_price * quantity

        # 手续费
        fee_cost = entry_price * quantity * fees

        # 净利润
        net_profit = spread_profit - fee_cost

        return net_profit.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    except (ValueError, TypeError):
        return Decimal("0")


def validate_order_book_integrity(
    current_sequence: int,
    last_sequence: int,
    exchange: str
) -> Tuple[bool, Optional[str]]:
    """
    验证订单簿数据完整性（序列号检查）

    Args:
        current_sequence: 当前序列号
        last_sequence: 上次序列号
        exchange: 交易所名称

    Returns:
        (is_valid, error_message) 元组
    """
    if last_sequence == 0:
        # 首次接收，总是有效
        return True, None

    if current_sequence <= last_sequence:
        return False, f"序列号未递增：{current_sequence} <= {last_sequence}"

    expected = last_sequence + 1
    if current_sequence != expected:
        return False, f"序列号缺失：期望 {expected}，收到 {current_sequence}"

    return True, None


def round_to_precision(value: Decimal, precision: int) -> Decimal:
    """
    将值四舍五入到指定精度

    Args:
        value: 待舍入的值
        precision: 小数位数

    Returns:
        舍入后的值
    """
    try:
        quantizer = Decimal("0." + "0" * precision)
        return value.quantize(quantizer, rounding=ROUND_DOWN)
    except (ValueError, TypeError):
        return value


def safe_decimal_divide(
    numerator: Decimal,
    denominator: Decimal,
    default: Decimal = Decimal("0")
) -> Decimal:
    """
    安全的 Decimal 除法

    Args:
        numerator: 分子
        denominator: 分母
        default: 除零时返回的默认值

    Returns:
        除法结果，或默认值（如果除零）
    """
    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except (ValueError, TypeError, ZeroDivisionError):
        return default
