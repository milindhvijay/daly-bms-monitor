# Bluetooth Connection Reliability Enhancements

This document describes the enhanced Bluetooth connection reliability features implemented to address intermittent BMS detection issues.

## Problem Statement

Bluetooth Low Energy (BLE) connections to BMS devices can be unreliable due to:
- Intermittent device visibility during scanning
- Connection timeouts in noisy RF environments
- Device busy states (connected to other apps)
- Bluetooth stack instabilities
- Power management issues

## Enhanced Features

### 1. Improved Discovery (`bt_discovery`)

**Enhancements:**
- Configurable scan duration (default: 5.0s, up to 8.0s for problem cases)
- Better error handling with fallback to empty device list
- Enhanced logging with device count and unnamed device handling
- Increased backoff time from 10s to 30s maximum

**Usage:**
```python
devices = await bt_discovery(logger, timeout=10, scan_duration=8.0)
```

### 2. Enhanced Connection Method (`connect`)

**New Features:**
- Configurable retry attempts (default: 3)
- Exponential backoff between retries (2^attempt seconds for device not found)
- Different retry strategies for different error types
- Comprehensive error logging and reporting

**Usage:**
```python
await bms.connect(timeout=25, max_retries=3)
```

### 3. Robust Scanner-Based Connection (`_connect_with_scanner`)

**Major Improvements:**
- Multiple scan sessions (default: 3) if device not found
- Progressive scan duration increase (5s, 7s, 9s)
- Enhanced device discovery logging
- Better separation of scan failures vs connection failures
- Configurable wait times between scan sessions

**Usage:**
```python
await bms._connect_with_scanner(timeout=30, max_scan_attempts=3)
```

### 4. Connection Diagnostics

**New Utility Functions:**

#### `bt_connection_diagnostics(logger, adapter=None)`
Runs comprehensive Bluetooth diagnostics:
- Bluetooth stack version detection
- Bleak library version reporting
- Bluetooth power status verification
- Discovery test with extended scanning

#### `validate_bms_connection(bms_instance, max_validation_attempts=3)`
Validates connection health:
- Connection status verification
- Service enumeration test
- Multiple validation attempts with retry logic

### 5. Enhanced Error Handling

**Improvements:**
- Connection validation after successful connect
- Service availability checking
- Better error categorization and logging
- Graceful degradation on partial failures

## Usage Examples

### Basic Reliable Connection
```python
from daly_bms import DalyBMS

bms = DalyBMS(device, verbose_log=True)
await bms.connect(timeout=25, max_retries=3)
```

### Scanner-Based Connection (Most Reliable)
```python
bms = DalyBMS(device, verbose_log=True)
await bms._connect_with_scanner(timeout=30, max_scan_attempts=3)
```

### With Diagnostics
```python
from bt_connection import bt_connection_diagnostics, validate_bms_connection

# Run diagnostics first
devices = await bt_connection_diagnostics(logger)

# Connect and validate
bms = DalyBMS(device)
await bms.connect()
is_healthy = await validate_bms_connection(bms)
```

### Enhanced Example Script
Use the new `example_reliable.py` script:

```bash
# Basic usage with enhanced reliability
python3 example_reliable.py

# With diagnostics
python3 example_reliable.py --diagnostics

# Scanner-based connection
python3 example_reliable.py --scanner

# Extended scanning
python3 example_reliable.py --extended-scan

# Direct connection to known address
python3 example_reliable.py --address AA:BB:CC:DD:EE:FF

# Verbose logging
python3 example_reliable.py --verbose
```

## Configuration Recommendations

### For Intermittent Detection Issues:
1. Use scanner-based connection: `_connect_with_scanner()`
2. Increase scan duration: `scan_duration=8.0`
3. Enable verbose logging for troubleshooting
4. Run diagnostics to check Bluetooth stack health

### For Noisy RF Environments:
1. Increase connection timeout: `timeout=30`
2. Increase retry attempts: `max_retries=5`
3. Use multiple scan sessions: `max_scan_attempts=5`

### For Power-Constrained Devices:
1. Enable keep-alive: `keep_alive=True`
2. Validate connections periodically
3. Implement reconnection logic in your application

## Troubleshooting

### Device Not Found
1. Run diagnostics: `bt_connection_diagnostics()`
2. Check Bluetooth power status
3. Verify device is not connected to another app
4. Use extended scanning: `--extended-scan`
5. Try scanner-based connection method

### Connection Timeouts
1. Increase timeout values
2. Check RF environment for interference
3. Verify Bluetooth stack version compatibility
4. Try different retry strategies

### Unstable Connections
1. Use connection validation: `validate_bms_connection()`
2. Implement periodic health checks
3. Enable reconnection on disconnect
4. Check for power management issues

## Logging Levels

- **INFO**: Connection attempts, scan results, major events
- **DEBUG**: Detailed retry logic, validation steps, timing information
- **WARNING**: Recoverable errors, validation failures
- **ERROR**: Unrecoverable errors, final failures

Enable verbose logging with `verbose_log=True` or `--verbose` flag for detailed troubleshooting information.
