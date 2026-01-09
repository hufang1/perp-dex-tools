# Feature Specification: Trade Logging for Arbitrage Verification

**Feature Branch**: `001-trade-log`
**Created**: 2026-01-09
**Status**: Draft
**Input**: User description: "请你给这个套利程序加日志。我希望在程序进行开仓和平仓动作的时候清晰记录下对应交易所的开仓价格，仓位收益（包含具体的计算过程）等信息，记录在@logs/trade.log中。为什么我要这个日志呢 是因为我想结合实际交易所中的仓位进行一个比对。看一下两边是否是一致的，防止你计算出来是有收益的，但实际是负收益的这种情况的出现"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trade Activity Logging (Priority: P1)

As a system operator, I want every trade action (opening and closing positions) to be automatically logged to a dedicated trade log file, so that I can verify the system's calculations against actual exchange positions.

**Why this priority**: This is the core requirement - without detailed logging, operators cannot detect discrepancies between calculated profits and actual exchange positions, which could lead to undetected losses.

**Independent Test**: Can be fully tested by running the arbitrage system through one complete open/close cycle and verifying that a detailed log entry is created in `logs/trade.log` containing all required trade information.

**Acceptance Scenarios**:

1. **Given** the arbitrage system is running, **When** an opening trade is executed (both Extended and Lighter positions are established), **Then** a detailed log entry MUST be written to `logs/trade.log` containing: timestamp, trade direction (LONG/SHORT), exchange-specific prices, quantities, order IDs, and initial spread calculation
2. **Given** the arbitrage system is running, **When** a closing trade is executed (both positions are closed), **Then** a detailed log entry MUST be written to `logs/trade.log` containing: timestamp, closing prices, quantities, order IDs, step-by-step profit/loss calculation, and final realized PnL
3. **Given** the log file does not exist, **When** the first trade is executed, **Then** the system MUST automatically create the `logs/trade.log` file with appropriate headers

---

### User Story 2 - Calculation Verification (Priority: P2)

As a system operator, I want the log entries to include the complete step-by-step profit/loss calculation process, so that I can manually verify the calculation logic and identify any errors in the computation.

**Why this priority**: This enables operators to audit the system's profit calculations and catch cases where the system reports profits but actual exchange positions show losses.

**Independent Test**: Can be fully tested by examining a closing log entry and manually verifying that each step of the PnL calculation (Extended PnL + Lighter PnL = Total PnL) is clearly documented and mathematically correct.

**Acceptance Scenarios**:

1. **Given** a LONG position is being closed, **When** the log entry is written, **Then** it MUST show: Extended PnL calculation (close_price - open_price) × quantity, Lighter PnL calculation (open_price - close_price) × quantity, and the sum
2. **Given** a SHORT position is being closed, **When** the log entry is written, **Then** it MUST show: Extended PnL calculation (open_price - close_price) × quantity, Lighter PnL calculation (close_price - open_price) × quantity, and the sum

---

### User Story 3 - Human-Readable Format (Priority: P3)

As a system operator, I want the log entries to be formatted in a clear, human-readable way, so that I can quickly understand trade details without needing special tools or parsing scripts.

**Why this priority**: While less critical than the logging itself, good formatting enables faster manual verification and reduces the risk of misreading log data.

**Independent Test**: Can be fully tested by opening the `logs/trade.log` file in a text editor and verifying that entries are clearly formatted with labeled fields and consistent structure.

**Acceptance Scenarios**:

1. **Given** a log entry is written, **When** I view the file, **Then** each field MUST be clearly labeled (e.g., "Extended Open Price: $3450.50")
2. **Given** multiple log entries exist, **When** I view the file, **Then** each entry MUST be separated by clear delimiters for easy parsing
3. **Given** a log entry contains monetary values, **When** I view the file, **Then** all values MUST include currency symbols and appropriate decimal formatting

---

### Edge Cases

- What happens when the log file cannot be written (disk full, permissions error)?
  - System MUST emit an error notification to the operator and retry logging
  - Trade execution MUST continue even if logging fails (trading takes priority)
- What happens when a trade is partially filled (Extended fills but Lighter fails)?
  - System MUST log the partial state clearly indicating incomplete hedge
  - Log MUST show "UNHEDGED POSITION" warning with full details
- What happens when the log file becomes very large (>100MB)?
  - System MUST implement log rotation or provide clear indicators in the log
- What happens when multiple trades occur simultaneously?
  - Each log entry MUST be atomically written (no interleaving of data)
  - Entries MUST include sequence numbers or timestamps for ordering

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST write a detailed log entry to `logs/trade.log` every time a spread pair position is opened
- **FR-002**: System MUST write a detailed log entry to `logs/trade.log` every time a spread pair position is closed
- **FR-003**: Opening log entries MUST include: timestamp, pair ID, direction (LONG/SHORT), Extended exchange price/quantity/order ID, Lighter exchange price/quantity/order ID, initial spread value, and spread rate
- **FR-004**: Closing log entries MUST include: timestamp, pair ID, opening prices (for reference), closing prices/quantities/order IDs for both exchanges, holding time duration, and complete profit/loss calculation breakdown
- **FR-005**: Profit/loss calculation breakdown MUST show: Extended PnL (formula + result), Lighter PnL (formula + result), and Total PnL (sum)
- **FR-006**: System MUST automatically create the `logs/` directory and `trade.log` file if they do not exist
- **FR-007**: Log entries MUST be written in a structured, human-readable format with clear field labels
- **FR-008**: System MUST handle logging failures gracefully (emit error, continue trading)
- **FR-009**: Log entries MUST be written atomically to prevent data corruption from concurrent writes
- **FR-010**: Each log entry MUST include a unique identifier (pair ID + timestamp) for cross-referencing with exchange records

### Key Entities

- **Trade Log Entry**: A record of a single trading event (open or close) containing timestamp, pair ID, exchange details (price, quantity, order ID for both Extended and Lighter), calculated metrics (spread, PnL), and verification data
- **Spread Pair Reference**: The association between opening and closing log entries via pair ID, enabling complete trade lifecycle tracking
- **PnL Calculation Record**: The step-by-step breakdown of profit/loss computation showing exchange-specific contributions and the final sum

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can manually verify 100% of closed trades against actual exchange positions using the log file within 5 minutes per trade
- **SC-002**: Discrepancies between calculated profits and actual exchange positions are detectable by comparing log entries with exchange data
- **SC-003**: Log entries contain all required fields (price, quantity, order ID, PnL calculation) for 100% of trades
- **SC-004**: The log file format allows operators to identify calculation errors without requiring additional tools or scripts
- **SC-005**: Zero trading interruptions occur due to logging failures (system logs errors but continues trading)

## Assumptions

- The `logs/` directory will be located in the project root directory
- File system permissions allow writing to the project directory
- Trading volume is low enough that log size won't become unmanageable (estimated <10,000 trades per day)
- Operators have basic text file viewing capabilities
- The existing `SpreadPair` class in `spread/spread_pair.py` accurately represents trade data structure

## Out of Scope

- Real-time log monitoring or alerting (log is for retrospective verification)
- Automatic log rotation or archival (will be addressed separately if needed)
- Integration with external logging systems or databases
- Web-based log viewer or analysis tools
- Modification of the trading logic itself (only adding logging, not changing behavior)
