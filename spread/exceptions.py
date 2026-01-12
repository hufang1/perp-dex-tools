"""
自定义异常类：Lighter-Extended 单向价差收敛套利系统

定义套利系统中使用的所有自定义异常
"""


class SpreadArbError(Exception):
    """套利系统基础异常类"""
    pass


class OrderBookNotReadyError(SpreadArbError):
    """订单簿未就绪异常

    当尝试访问尚未初始化或无效的订单簿数据时抛出
    """
    pass


class InsufficientDepthError(SpreadArbError):
    """订单簿深度不足异常

    当订单簿深度不足以执行目标交易数量时抛出
    """
    def __init__(self, exchange: str, required: float, available: float):
        self.exchange = exchange
        self.required = required
        self.available = available
        super().__init__(
            f"{exchange} 订单簿深度不足：需要 {required}，可用 {available}"
        )


class RiskValidationFailedError(SpreadArbError):
    """风控验证失败异常

    当交易未通过风控检查时抛出（余额不足、价差异常等）
    """
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"风控验证失败：{reason}")


class ExecutionTimeoutError(SpreadArbError):
    """执行超时异常

    当订单执行时间超过允许的最大时间时抛出
    """
    def __init__(self, timeout: float, side: str):
        self.timeout = timeout
        self.side = side
        super().__init__(
            f"{side} 订单执行超时：{timeout} 秒"
        )


class StateLoadError(SpreadArbError):
    """状态加载异常

    当无法从文件加载保存的状态时抛出
    """
    def __init__(self, file_path: str, original_error: str = ""):
        self.file_path = file_path
        self.original_error = original_error
        message = f"无法加载状态文件：{file_path}"
        if original_error:
            message += f" - {original_error}"
        super().__init__(message)


class StateSaveError(SpreadArbError):
    """状态保存异常

    当无法将状态保存到文件时抛出
    """
    def __init__(self, file_path: str, original_error: str = ""):
        self.file_path = file_path
        self.original_error = original_error
        message = f"无法保存状态文件：{file_path}"
        if original_error:
            message += f" - {original_error}"
        super().__init__(message)


class BalanceInsufficientError(SpreadArbError):
    """余额不足异常

    当账户余额不足以执行交易时抛出
    """
    def __init__(self, exchange: str, required: float, available: float):
        self.exchange = exchange
        self.required = required
        self.available = available
        super().__init__(
            f"{exchange} 余额不足：需要 {required}，可用 {available}"
        )


class WebSocketConnectionError(SpreadArbError):
    """WebSocket 连接异常

    当 WebSocket 连接失败或断开时抛出
    """
    def __init__(self, exchange: str, message: str = ""):
        self.exchange = exchange
        self.message = message
        super().__init__(
            f"{exchange} WebSocket 连接失败" + (f": {message}" if message else "")
        )


class OrderBookSequenceError(SpreadArbError):
    """订单簿序列号异常

    当检测到订单簿序列号不连续（数据缺失）时抛出
    """
    def __init__(self, exchange: str, expected: int, received: int):
        self.exchange = exchange
        self.expected = expected
        self.received = received
        super().__init__(
            f"{exchange} 订单簿序列号异常：期望 {expected}，收到 {received}"
        )


class SingleSideExecutionError(SpreadArbError):
    """单边成交异常

    当只有一方的订单成交时抛出（需要紧急处理）
    """
    def __init__(self, executed_exchange: str, pending_exchange: str):
        self.executed_exchange = executed_exchange
        self.pending_exchange = pending_exchange
        super().__init__(
            f"单边成交检测：{executed_exchange} 已成交，{pending_exchange} 未成交"
        )


class InvalidPriceError(SpreadArbError):
    """价格无效异常

    当价格数据无效或不合理时抛出
    """
    def __init__(self, exchange: str, price: float, reason: str = ""):
        self.exchange = exchange
        self.price = price
        self.reason = reason
        super().__init__(
            f"{exchange} 价格无效：{price}" + (f" - {reason}" if reason else "")
        )


class ExtremeSpreadError(SpreadArbError):
    """极端价差异常

    当检测到极端价差（可能是数据错误或市场异常）时抛出
    """
    def __init__(self, spread: float, max_allowed: float):
        self.spread = spread
        self.max_allowed = max_allowed
        super().__init__(
            f"极端价差检测：{spread:.2%} 超过最大允许值 {max_allowed:.2%}"
        )
