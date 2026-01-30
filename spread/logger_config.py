"""
日志配置模块

提供精简的日志格式配置，确保关键信息在一行内完整呈现
"""

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Optional


class CompactFormatter(logging.Formatter):
    """
    精简日志格式化器

    格式: [LEVEL] 模块名: 消息
    去除换行，确保关键信息在一行内
    """

    # 颜色代码（仅终端支持）
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m',       # 重置
    }

    def __init__(self, use_colors: bool = True):
        """
        初始化格式化器

        Args:
            use_colors: 是否使用颜色输出
        """
        self.use_colors = use_colors and sys.stderr.isatty()
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录

        Args:
            record: 日志记录

        Returns:
            格式化后的日志字符串
        """
        # 获取颜色前缀
        if self.use_colors:
            color = self.COLORS.get(record.levelname, '')
            reset = self.COLORS['RESET']
            level_color = f"{color}{record.levelname}{reset}"
        else:
            level_color = record.levelname

        # 精简格式: [LEVEL] 模块: 消息
        # 移除asctime、pathname等冗余信息
        message = record.getMessage()
        module = record.name.split('.')[-1] if record.name else 'root'

        return f"[{level_color}] {module}: {message}"


def setup_logging(
    level: int = logging.INFO,
    compact: bool = True,
    log_file: Optional[str] = None,
    file_compact: bool = False,
    rotate_when: str = "D",
    backup_count: int = 14,
    max_bytes: Optional[int] = None,
) -> None:
    """
    配置日志系统

    Args:
        level: 日志级别（默认INFO）
        compact: 是否使用精简格式（默认True）
        log_file: 可选的日志文件路径
    """
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除现有处理器
    root_logger.handlers.clear()

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)

    # 设置格式化器
    if compact:
        formatter = CompactFormatter(use_colors=True)
    else:
        # 标准格式（详细模式）
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 可选的文件处理器（支持按时间或大小滚动）
    if log_file:
        if max_bytes and max_bytes > 0:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
        else:
            file_handler = TimedRotatingFileHandler(
                log_file,
                when=rotate_when,
                backupCount=backup_count,
                encoding='utf-8'
            )
        file_handler.setLevel(level)
        # 文件使用完整格式（含时间戳），或精简格式
        if file_compact:
            file_formatter = CompactFormatter(use_colors=False)
        else:
            file_formatter = logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)


# 预定义的日志级别快捷方式
def set_debug() -> None:
    """设置为DEBUG级别"""
    setup_logging(level=logging.DEBUG, compact=True)


def set_info() -> None:
    """设置为INFO级别"""
    setup_logging(level=logging.INFO, compact=True)


def set_warning() -> None:
    """设置为WARNING级别"""
    setup_logging(level=logging.WARNING, compact=True)


def set_error() -> None:
    """设置为ERROR级别"""
    setup_logging(level=logging.ERROR, compact=True)
