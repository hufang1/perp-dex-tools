# Data Model: SDK健康状态管理

**Feature**: 003-fix-lighter-sdk
**Date**: 2026-01-12

## Overview

本文档定义了用于Lighter SDK健康检查和状态管理的数据模型。

## Core Entities

### 1. SDKHealthStatus

SDK整体健康状态，用于表示SDK是否可用。

```python
@dataclass
class SDKHealthStatus:
    """SDK健康状态"""
    healthy: bool                    # SDK是否健康可用
    errors: List[str]                # 错误消息列表
    timestamp: float = field(default_factory=time.time)  # 检查时间戳

    def is_healthy(self) -> bool:
        """检查SDK是否健康"""
        return self.healthy and len(self.errors) == 0

    def get_error_summary(self) -> str:
        """获取错误摘要"""
        return "; ".join(self.errors) if self.errors else "No errors"
```

**字段说明**：
- `healthy`: 主健康标志，快速判断SDK是否可用
- `errors`: 详细的错误消息列表，用于诊断
- `timestamp`: 检查时间戳，用于判断状态是否过期

**使用场景**：
- SDK初始化后验证
- 下单前健康检查
- 错误诊断时状态快照

### 2. SDKObjectState

单个SDK对象的状态信息。

```python
@dataclass
class SDKObjectState:
    """SDK对象状态"""
    name: str                       # 对象名称（如"lighter_client"）
    exists: bool                    # 对象是否存在（不为None）
    object_type: Optional[str]      # 对象类型名
    available: bool = True          # 对象是否可用（可能存在但不可用）

    def __str__(self) -> str:
        """格式化输出"""
        status = "✓" if self.exists and self.available else "✗"
        return f"{status} {self.name}: {self.object_type or 'None'}"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'exists': self.exists,
            'type': self.object_type,
            'available': self.available
        }
```

**字段说明**：
- `name`: 对象名称，用于日志输出
- `exists`: 对象是否存在（`is not None`）
- `object_type`: 对象的类型名（用于诊断）
- `available`: 对象是否可用（可能存在但已失效）

**使用场景**：
- 记录单个对象的状态
- 构建状态快照
- 日志输出

### 3. SDKStateSnapshot

SDK完整状态快照，包含所有关键对象的状态。

```python
@dataclass
class SDKStateSnapshot:
    """SDK状态快照"""
    timestamp: float                 # 快照时间戳
    objects: Dict[str, SDKObjectState]  # 所有对象的状态
    overall_status: str              # 整体状态描述

    def add_object(self, name: str, obj: Any, available: bool = True) -> None:
        """添加对象状态"""
        self.objects[name] = SDKObjectState(
            name=name,
            exists=obj is not None,
            object_type=type(obj).__name__ if obj else None,
            available=available if obj is not None else False
        )

    def get_failed_objects(self) -> List[str]:
        """获取失败的对象列表"""
        return [name for name, state in self.objects.items()
                if not state.exists or not state.available]

    def format_for_log(self) -> str:
        """格式化为日志输出"""
        lines = [f"SDK State Snapshot at {self.timestamp}"]
        for name, state in self.objects.items():
            lines.append(f"  {state}")
        lines.append(f"Overall: {self.overall_status}")
        return "\n".join(lines)
```

**字段说明**：
- `timestamp`: 快照时间戳
- `objects`: 所有对象的状态字典
- `overall_status`: 整体状态描述（如"Healthy", "Degraded", "Failed"）

**使用场景**：
- 错误时记录完整状态
- 健康检查结果输出
- 诊断问题

## State Transitions

### SDK Lifecycle States

```
┌─────────┐
│ Created │  初始化完成，对象已创建
└────┬────┘
     │
     v
┌─────────┐
│ Valid   │  对象验证通过，所有对象不为None
└────┬────┘
     │
     v
┌─────────┐
│ Healthy │  健康检查通过，API可用
└────┬────┘
     │
     ├────> ┌─────────┐
     │      │ Degraded│  部分功能不可用
     │      └─────────┘
     │
     v
┌─────────┐
│ Failed  │  完全不可用，需要重新初始化
└─────────┘
```

### State Validation Rules

| State | Validation | Description |
|-------|-----------|-------------|
| Created | `obj is not None` | 对象已创建 |
| Valid | 所有对象 `is not None` | 所有关键对象存在 |
| Healthy | `check_client() == None` | API连接可用 |
| Degraded | 部分功能失败 | 主要对象可用，辅助功能失败 |
| Failed | 任何对象 `is None` | 关键对象缺失 |

## Usage Examples

### Example 1: SDK初始化验证

```python
# 初始化后验证
snapshot = SDKStateSnapshot(timestamp=time.time(), objects={}, overall_status="")

# 检查每个对象
snapshot.add_object("lighter_client", self.lighter_client)
if hasattr(self.lighter_client, 'api_client'):
    snapshot.add_object("api_client", self.lighter_client.api_client)
    if hasattr(self.lighter_client.api_client, 'rest_client'):
        snapshot.add_object("rest_client", self.lighter_client.api_client.rest_client)

# 判断状态
failed = snapshot.get_failed_objects()
if failed:
    snapshot.overall_status = f"Failed: {', '.join(failed)}"
    self.logger.log(snapshot.format_for_log(), "ERROR")
    raise Exception(f"SDK initialization failed: {failed}")
else:
    snapshot.overall_status = "Valid"
```

### Example 2: 下单前健康检查

```python
async def check_sdk_health(self) -> SDKHealthStatus:
    """检查SDK健康状态"""
    errors = []

    # 检查对象存在性
    if self.lighter_client is None:
        errors.append("lighter_client is None")
        return SDKHealthStatus(healthy=False, errors=errors)

    if self.lighter_client.api_client is None:
        errors.append("api_client is None")
        return SDKHealthStatus(healthy=False, errors=errors)

    # 检查API可用性
    try:
        err = self.lighter_client.check_client()
        if err is not None:
            errors.append(f"CheckClient failed: {err}")
            return SDKHealthStatus(healthy=False, errors=errors)
    except Exception as e:
        errors.append(f"CheckClient exception: {e}")
        return SDKHealthStatus(healthy=False, errors=errors)

    return SDKHealthStatus(healthy=True, errors=[])
```

### Example 3: 错误诊断时状态快照

```python
except Exception as e:
    # 记录状态快照
    snapshot = self._get_sdk_state_snapshot()
    self.logger.log(
        f"[LIGHTER] SDK exception caught. State:\n{snapshot.format_for_log()}",
        "ERROR"
    )
    self.logger.log(
        f"[LIGHTER] Exception: {type(e).__name__}: {e}",
        "ERROR"
    )

    # 返回错误结果
    return OrderResult(
        success=False,
        order_id=None,
        error_message=f"SDK exception: {type(e).__name__}: {e}"
    )
```

## Validation Rules

### Object Existence Rules

1. **lighter_client**: 必须 `is not None`
2. **api_client**: 必须 `is not None` 且 `hasattr(lighter_client, 'api_client')`
3. **rest_client**: 必须 `is not None` 且 `hasattr(api_client, 'rest_client')`

### Health Check Rules

1. 所有对象存在 → 执行 `check_client()`
2. `check_client()` 返回 `None` → Healthy
3. `check_client()` 返回非None → Failed（记录错误消息）
4. `check_client()` 抛出异常 → Failed（记录异常）

## Storage & Persistence

### In-Memory Storage

- SDK状态存储在内存中（`LighterClient`实例变量）
- 状态快照按需生成，不持久化
- 健康检查结果缓存1秒，避免频繁检查

### Logging

- 状态变化记录到日志文件
- 错误时自动记录完整状态快照
- 日志格式：`[LIGHTER] [状态] 消息`

## Security Considerations

- 状态快照不包含敏感信息（私钥、token等）
- 日志输出时过滤敏感字段
- 健康检查不修改SDK状态

## Performance Impact

- 对象存在性检查：<1ms
- `check_client()`调用：100-500ms
- 状态快照生成：<5ms
- 总体开销：下单前健康检查<100ms（使用缓存）

## Future Extensions

可能的未来扩展：

1. **历史状态跟踪**: 记录状态变化历史
2. **性能指标**: 添加API响应时间、错误率等指标
3. **自动恢复**: 检测到失败时自动重新初始化
4. **降级策略**: 部分功能失败时的降级处理
