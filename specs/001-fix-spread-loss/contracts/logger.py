# Logger Interface Contract

**Module**: `spread/trade_logger.py`
**Version**: 2.0 (增强版)
**Date**: 2026-01-10

## 接口定义

### StructuredTradeLogger

结构化交易日志记录器，使用JSON Lines格式。

```python
class StructuredTradeLogger:
    """
    结构化交易日志记录器

    日志格式: JSON Lines (每行一个JSON对象)
    文件位置: logs/trade.log
    编码: UTF-8

    Attributes:
        log_file_path: str - 日志文件路径
        logger: logging.Logger - Python logger实例
    """

    def __init__(self, log_file_path: str = "logs/trade.log"):
        """
        初始化日志记录器

        Args:
            log_file_path: 日志文件路径

        Raises:
            IOError: 日志目录无法创建
        """

    def log_event(
        self,
        event_type: str,
        level: str = "INFO",
        **data
    ) -> bool:
        """
        记录结构化事件

        Args:
            event_type: 事件类型（见支持的事件类型列表）
            level: 日志级别 (DEBUG/INFO/WARN/ERROR)
            **data: 事件数据（会被序列化为JSON）

        Returns:
            bool: 是否成功写入

        Raises:
            无异常抛出（写入失败时返回False）

        Examples:
            >>> logger = StructuredTradeLogger()
            >>> logger.log_event(
            ...     "EXTENDED_ORDER_PLACED",
            ...     order_type="MAKER",
            ...     price="3090.00",
            ...     quantity="0.01133"
            ... )
            True
        """

    def log_opening_trade(self, pair: SpreadPair) -> bool:
        """记录开仓交易（便捷方法）"""

    def log_closing_trade(self, pair: SpreadPair) -> bool:
        """记录平仓交易（便捷方法）"""

    def log_unhedged_position(self, position: Dict) -> bool:
        """记录未对冲仓位（便捷方法）"""
```

## 支持的事件类型

### 系统事件

| event_type | level | 触发时机 | 必需字段 |
|------------|-------|----------|----------|
| SYSTEM_START | INFO | 程序启动 | config |
| SHUTDOWN | INFO | 程序关闭 | reason |

### 交易事件

| event_type | level | 触发时机 | 必需字段 |
|------------|-------|----------|----------|
| SPREAD_OPPORTUNITY | DEBUG | 价差机会检测 | extended_bid/ask, lighter_bid/ask, decision |
| EXTENDED_ORDER_PLACED | INFO | Extended下单 | order_type, price, quantity, order_id |
| EXTENDED_FILLED | INFO | Extended成交 | filled_price, filled_quantity, wait_duration_ms, fee_type |
| EXTENDED_MAKER_TIMEOUT | WARN | Maker单超时 | wait_duration_ms, action |
| LIGHTER_HEDGE | INFO | Lighter对冲 | expected_price, actual_price, slippage_usdt |
| LIGHTER_HEDGE_FAILED | ERROR | Lighter对冲失败 | error, quantity |
| POSITION_OPENED | INFO | 开仓完成 | pair_id, extended, lighter, open_spread |
| POSITION_CLOSED | INFO | 平仓完成 | pair_id, pnl, fees, slippage |
| POSITION_FORCE_CLOSED | WARN | 强制平仓 | pair_id, reason |

### 统计事件

| event_type | level | 触发时机 | 必需字段 |
|------------|-------|----------|----------|
| HOURLY_STATISTICS | INFO | 每小时统计 | trading, volume, pnl, fees |

## 日志格式契约

### 通用格式

```json
{
  "timestamp": "2026-01-10T05:01:23.456Z",
  "level": "INFO",
  "event_type": "EVENT_TYPE",
  "data": {
    "字段名": "字段值",
    ...
  }
}
```

### 字段规范

| 字段 | 类型 | 必填 | 格式 |
|------|------|------|------|
| timestamp | string | ✅ | ISO 8601 (YYYY-MM-DDTHH:MM:SS.sssZ) |
| level | string | ✅ | DEBUG/INFO/WARN/ERROR |
| event_type | string | ✅ | 大写+下划线 |
| data | object | ✅ | 事件特定数据 |

### 数据字段规范

**价格字段**:
- 类型: string
- 格式: 数字字符串，保留2位小数
- 示例: `"3090.50"`

**数量字段**:
- 类型: string
- 格式: 数字字符串，保留4-6位小数
- 示例: `"0.01133"`

**金额字段**:
- 类型: string
- 格式: 数字字符串，保留6位小数
- 示例: `"0.006950"`

**百分比字段**:
- 类型: string
- 格式: 数字字符串，科学计数法或小数
- 示例: `"0.0005"` 或 `"5e-4"`

## 错误处理契约

### 写入失败处理

```python
def log_event(self, event_type: str, level: str = "INFO", **data) -> bool:
    try:
        # 1. 格式化日志
        log_entry = self._format_entry(event_type, level, data)

        # 2. 写入文件
        with open(self.log_file_path, 'a') as f:
            f.write(log_entry + '\n')

        return True
    except Exception as e:
        # 3. 记录到stderr，不抛异常
        sys.stderr.write(f"日志写入失败: {e}\n")
        return False
```

**契约**:
- 日志写入失败不抛出异常
- 失败时返回False
- 错误信息输出到stderr

### 并发写入

```python
import threading

class StructuredTradeLogger:
    def __init__(self, log_file_path: str = "logs/trade.log"):
        self._lock = threading.Lock()
        ...

    def log_event(self, ...):
        with self._lock:
            # 原子写入
            ...
```

**契约**:
- 使用线程锁保证并发安全
- 每条日志原子写入（不会被截断）

## 性能契约

### 延迟要求

| 操作 | 最大延迟 | 说明 |
|------|----------|------|
| log_event() | 10ms | 包含格式化和写入 |
| 格式化 | 2ms | JSON序列化 |
| 磁盘写入 | 5ms | SSD环境 |

### 吞吐量要求

| 场景 | 要求 |
|------|------|
| 每秒写入 | > 100条/秒 |
| 每小时写入 | > 200,000条/小时 |
| 文件大小 | 自动轮转，单文件<100MB |

## 测试契约

### 格式验证测试

```python
def test_log_format_is_valid_json():
    """验证日志格式是有效JSON"""
    logger = StructuredTradeLogger()
    logger.log_event("TEST", value=123)

    with open('logs/trade.log') as f:
        for line in f:
            entry = json.loads(line)  # 不抛出异常
            assert 'timestamp' in entry
            assert 'event_type' in entry
```

### 并发写入测试

```python
def test_concurrent_writing():
    """验证并发写入不会丢失数据"""
    logger = StructuredTradeLogger()

    def write_events(n):
        for i in range(n):
            logger.log_event("TEST", id=i)

    threads = [threading.Thread(target=write_events, args=(1000,))
               for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 验证所有事件都写入
    count = sum(1 for line in open('logs/trade.log'))
    assert count == 10000
```

## 版本兼容性

### v1.0 → v2.0 变更

| 项目 | v1.0 | v2.0 |
|------|------|------|
| 格式 | 文本 | JSON Lines |
| 方法 | log_opening_trade() | log_event() + 便捷方法 |
| 返回值 | None | bool |
| 错误处理 | 异常 | 返回False |

### 迁移路径

```python
# v1.0代码
logger.log_opening_trade(pair)

# v2.0代码（向后兼容）
logger.log_opening_trade(pair)  # 仍然支持

# v2.0推荐
logger.log_event("POSITION_OPENED", **pair.to_dict())
```

---

**契约状态**: 已完成，可以开始实施。
