"""
环境变量验证模块

在启动时检查必需的 API 密钥和配置
"""

import os
import sys
import logging
from typing import List, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class EnvironmentValidationError(Exception):
    """环境变量验证失败异常"""
    pass


def validate_environment() -> bool:
    """
    验证所有必需的环境变量已设置

    Returns:
        True 如果验证通过，否则抛出异常

    Raises:
        EnvironmentValidationError: 如果缺少必需的环境变量
    """
    # 首先加载 .env 文件
    load_dotenv()

    required_vars = {
        # Lighter 交易所配置
        "API_KEY_PRIVATE_KEY": "Lighter API 密钥私钥",
        "LIGHTER_ACCOUNT_INDEX": "Lighter 账户索引",
        "LIGHTER_API_KEY_INDEX": "Lighter API 密钥索引",

        # Extended 交易所配置
        "EXTENDED_VAULT": "Extended Vault 地址",
        "EXTENDED_STARK_KEY_PRIVATE": "Extended Stark 私钥",
        "EXTENDED_STARK_KEY_PUBLIC": "Extended Stark 公钥",
        "EXTENDED_API_KEY": "Extended API 密钥",
    }

    missing_vars = []

    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        if value is None or value.strip() == "":
            missing_vars.append(f"  - {var_name}: {description}")

    if missing_vars:
        error_msg = "缺少必需的环境变量:\n" + "\n".join(missing_vars)
        logger.error(error_msg)
        raise EnvironmentValidationError(error_msg)

    # 验证数值类型的环境变量
    try:
        account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", "0"))
        if account_index < 0 or api_key_index < 0:
            raise ValueError("账户索引和 API 密钥索引必须是非负整数")
    except ValueError as e:
        raise EnvironmentValidationError(f"环境变量值无效: {e}")

    logger.info("环境变量验证通过")
    return True


def validate_optional_environment() -> List[str]:
    """
    验证可选的环境变量并返回警告信息

    Returns:
        警告信息列表
    """
    warnings = []

    # Telegram 通知配置（可选）
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if telegram_token and not telegram_chat_id:
        warnings.append("TELEGRAM_BOT_TOKEN 已设置但 TELEGRAM_CHAT_ID 未设置，Telegram 通知可能无法正常工作")

    if telegram_chat_id and not telegram_token:
        warnings.append("TELEGRAM_CHAT_ID 已设置但 TELEGRAM_BOT_TOKEN 未设置，Telegram 通知可能无法正常工作")

    # 时区配置（可选）
    timezone = os.getenv("TIMEZONE")
    if timezone:
        try:
            import pytz
            pytz.timezone(timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            warnings.append(f"无效的时区设置: {timezone}")

    return warnings


def print_environment_summary():
    """打印环境配置摘要（精简单行格式）"""
    logger.info(f"环境: Lighter账户{os.getenv('LIGHTER_ACCOUNT_INDEX', '未设置')} | "
                f"Extended Vault{'已配置' if os.getenv('EXTENDED_VAULT') else '未配置'}")


def format_config_summary(symbol: str, size: float, open_threshold: float,
                          profit_target: float, buffer: float) -> str:
    """
    格式化配置为单行摘要

    Args:
        symbol: 交易对
        size: 交易数量
        open_threshold: 开仓阈值（百分比）
        profit_target: 盈利目标（百分比）
        buffer: 缓冲期（秒）

    Returns:
        单行配置摘要字符串
    """
    return f"配置: {symbol}|{size}|开仓{open_threshold:.2%}|盈利{profit_target:.2%}|缓冲{buffer}s"


def check_env_before_start():
    """
    启动前检查环境

    这是主入口点，应该在程序启动时调用
    """
    try:
        # 验证必需的环境变量
        validate_environment()

        # 检查可选环境变量
        warnings = validate_optional_environment()
        for warning in warnings:
            logger.warning(warning)

        # 打印配置摘要
        print_environment_summary()

        return True

    except EnvironmentValidationError as e:
        logger.error(f"环境验证失败: {e}")
        logger.error("请设置必需的环境变量后重试")
        logger.error("可以参考 .env.example 文件创建 .env 文件")
        return False
