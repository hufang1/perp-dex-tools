# Feature Specification: 修复Lighter SDK初始化错误导致下单失败

**Feature Branch**: `003-fix-lighter-sdk`
**Created**: 2026-01-12
**Status**: Draft
**Input**: 用户报告Lighter交易所下单失败，错误日志显示 `AttributeError: 'NoneType' object has no attribute 'code'`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 修复Lighter SDK客户端初始化失败 (Priority: P1)

套利机器人在尝试Lighter交易所下单时失败，抛出`AttributeError: 'NoneType' object has no attribute 'code'`异常。这导致Extended交易所成交但Lighter失败，形成单腿持仓，触发紧急回滚和熔断器，系统完全暂停交易。

**问题根源**：
- 错误发生在`lighter_client.create_order()`调用时
- SDK内部某个对象为`None`，访问其`code`属性时失败
- 可能原因：
  1. Lighter客户端初始化不完整（`lighter_client`为None）
  2. SDK的`api_client`或`rest_client`未正确设置
  3. 代理配置导致SDK连接失败，内部对象未初始化

**为什么这个优先级**：这是阻塞性问题（P0），导致Lighter交易所完全无法下单，套利功能失效。

**独立测试**：可以通过触发一次套利机会来验证。如果Extended和Lighter都成功返回订单ID，日志显示"双腿成交"而非"单腿持仓"，则修复成功。

**Acceptance Scenarios**：

1. **Given** 套利机器人正在运行，**When** 发现套利机会并尝试下单，**Then** Extended和Lighter都成功下单，日志显示"双腿成交"
2. **Given** Lighter客户端初始化，**When** 调用`place_open_order`，**Then** 不抛出`AttributeError`异常
3. **Given** 并发下单完成，**When** 检查执行结果，**Then** Lighter的`success=True`且`order_id`不为None

---

### User Story 2 - 增强Lighter客户端初始化诊断日志 (Priority: P2)

当前错误日志只显示`AttributeError: 'NoneType' object has no attribute 'code'`，但没有指出具体哪个对象为None，难以诊断问题根源。

**为什么这个优先级**：增强诊断能力可以帮助快速定位未来的SDK问题，但不如修复核心问题紧急。

**独立测试**：查看日志输出，确认所有关键的SDK对象状态都有记录。

**Acceptance Scenarios**：

1. **Given** Lighter客户端初始化，**When** 初始化完成，**Then** 日志记录`lighter_client`、`api_client`、`rest_client`的状态
2. **Given** 调用SDK方法失败，**When** 捕获异常，**Then** 日志包含完整的对象状态和异常堆栈

---

### User Story 3 - 添加SDK健康检查机制 (Priority: P3)

在下单前检查Lighter SDK是否健康可用，避免下单时才发现SDK未初始化。

**为什么这个优先级**：这是防御性改进，可以在问题发生前就检测到，但不修复根本问题。

**独立测试**：在SDK未初始化时，健康检查应该返回失败状态。

**Acceptance Scenarios**：

1. **Given** 套利机器人启动，**When** 执行SDK健康检查，**Then** 检查所有关键对象不为None
2. **Given** 健康检查失败，**When** 尝试下单，**Then** 系统提前拒绝并记录详细错误

---

### Edge Cases

- SDK初始化过程中网络临时不可用
- 代理服务器配置错误导致连接失败
- SDK内部对象延迟初始化（异步创建）
- Lighter交易所API端点变更
- 多次重试后SDK仍然无法初始化

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须在Lighter客户端初始化完成后，验证所有关键对象（`lighter_client`、`api_client`、`rest_client`）不为None
- **FR-002**: 系统必须在调用`create_order`前，检查SDK内部对象的完整性
- **FR-003**: 系统必须在SDK初始化失败时，提供清晰的错误消息指出哪个对象为None
- **FR-004**: 系统必须在捕获`AttributeError`异常时，记录SDK对象的状态快照
- **FR-005**: 系统必须在下单失败时，不触发单腿持仓回滚（如果Lighter SDK从未成功初始化）
- **FR-006**: 系统必须提供SDK健康检查接口，在下单前验证SDK可用性
- **FR-007**: 系统必须在代理配置失败时，提供fallback机制（记录警告但继续运行）

### Key Entities

- **LighterClient**: Lighter交易所客户端封装，负责与Lighter SDK交互
- **SDK状态**: 包含`lighter_client`、`api_client`、`rest_client`的对象状态
- **订单结果**: 包含`success`、`order_id`、`error`字段的执行结果

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Lighter下单成功率从0%提升到90%以上（基于10次连续套利机会测试）
- **SC-002**: 单腿持仓率从100%降低到<10%
- **SC-003**: 错误日志包含SDK对象状态信息，诊断时间<5分钟
- **SC-004**: SDK初始化失败时，系统在启动阶段就检测到并拒绝运行，而不是等到下单时才失败
- **SC-005**: 并发下单时Extended和Lighter的发送时间差<5ms
- **SC-006**: 熔断器不再因为Lighter下单失败而触发完全暂停

## Dependencies & Assumptions

### Dependencies

- Lighter SDK 0.1.4正确安装
- 网络连接可以访问Lighter交易所API
- 代理服务器配置正确（如果使用代理）

### Assumptions

- 错误是由于SDK初始化不完整导致的，不是SDK版本bug
- 代理配置可能影响SDK初始化
- SDK对象在某些情况下可能为None（异步初始化、连接失败等）
- Extended交易所工作正常（从日志看Extended确实成功下单）

## Out of Scope

- 修改Lighter SDK源码（假设是官方SDK，不应修改）
- 更换Lighter SDK版本（除非确定是SDK bug）
- 优化网络延迟（这是基础设施问题）
- 修改Extended交易所逻辑（Extended工作正常）
