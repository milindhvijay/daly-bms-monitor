#!/usr/bin/env python3
"""
Daly BMS Continuous Monitoring Script

This script continuously monitors a Daly BMS via Bluetooth, logs data every 10 seconds,
and saves it to a text file. It handles connection issues with automatic reconnection.

Usage:
  python3 bms_monitor.py --address 41:19:05:01:13:D0
  python3 bms_monitor.py --address 41:19:05:01:13:D0 --interval 5 --output bms_data.log
"""

import asyncio
import argparse
import datetime
import logging
import os
import signal
import sys
import time
from typing import Optional, Dict, Any, List

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from daly_bms import DalyBMS
from bt_connection import validate_bms_connection

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bms_monitor")

# Global flag to control monitor loop
running = True

class BMSMonitor:
    """Continuous BMS monitor with data logging and automatic reconnection."""
    
    def __init__(self, 
                 device_address: str, 
                 device_name: str = "Daly BMS",
                 output_file: str = "bms_data.txt",
                 interval: int = 10,
                 use_scanner: bool = True,
                 verbose: bool = False):
        """Initialize the BMS monitor.
        
        Args:
            device_address: BMS Bluetooth address
            device_name: Device name for display
            output_file: Output file path for data logging
            interval: Polling interval in seconds
            use_scanner: Whether to use scanner-based connection
            verbose: Enable verbose logging
        """
        self.device_address = device_address
        self.device_name = device_name
        self.output_file = output_file
        self.interval = interval
        self.use_scanner = use_scanner
        self.verbose = verbose
        
        self.bms = None
        self.connected = False
        self.connect_attempt = 0
        self.max_connect_attempts = 10
        self.reconnect_delay = 5  # seconds
        self.data_count = 0
        
        # Configure logging
        if verbose:
            logger.setLevel(logging.DEBUG)
        
        # Setup output file header
        self._setup_output_file()
    
    def _setup_output_file(self):
        """Setup the output file if needed."""
        # No header needed for the new format
        pass
    
    def _create_device(self):
        """Create a BLEDevice object for the BMS."""
        try:
            # Try the new bleak version constructor
            return BLEDevice(self.device_address, self.device_name)
        except TypeError:
            # Fall back to older bleak version constructor
            return BLEDevice(self.device_address, self.device_name, {})
    
    async def connect(self):
        """Connect to the BMS with retry logic."""
        if self.bms and self.bms._bt.is_connected:
            return True
            
        self.connect_attempt += 1
        logger.info(f"Connection attempt {self.connect_attempt} to {self.device_address}")
        
        try:
            # Create BLEDevice and DalyBMS instance
            device = self._create_device()
            self.bms = DalyBMS(device, reconnect=True, verbose_log=self.verbose)
            
            # Use enhanced connection with reliability features
            await self.bms.connect(timeout=30, max_retries=3, use_scanner=self.use_scanner)
            
            # Validate connection (using our own validation instead of validate_bms_connection)
            if not self.bms._bt.is_connected:
                logger.warning("Connection validation failed, will retry later")
                await self.disconnect()
                return False
                
            # Check services
            try:
                services = self.bms._bt.client.services
                if not services:
                    logger.warning("Connected but no services available")
                    await self.disconnect()
                    return False
            except Exception as e:
                logger.warning(f"Connection validation failed: {e}")
                await self.disconnect()
                return False
                
            logger.info(f"Successfully connected to BMS {self.device_address}")
            self.connected = True
            self.connect_attempt = 0  # Reset counter on successful connection
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {type(e).__name__}: {str(e)}")
            await self.disconnect()
            
            if self.connect_attempt >= self.max_connect_attempts:
                logger.error(f"Maximum connection attempts ({self.max_connect_attempts}) reached")
                return False
                
            # Exponential backoff for reconnection attempts
            delay = min(60, self.reconnect_delay * (1.5 ** min(self.connect_attempt, 5)))
            logger.info(f"Will retry in {delay:.1f} seconds")
            return False
    
    async def disconnect(self):
        """Safely disconnect from BMS."""
        self.connected = False
        if self.bms:
            try:
                await self.bms.disconnect()
                logger.debug("Disconnected from BMS")
            except Exception as e:
                logger.debug(f"Error during disconnect: {e}")
    
    def format_data_for_log(self, data: Dict[str, Any]) -> str:
        """Format BMS data in a human-readable format for the log file."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Start with timestamp as header
        output = f"Data logged at: {timestamp}\n\n"
        
        # === BMS General Information ===
        output += "=== BMS General Information ===\n"
        
        voltage = data.get("voltage", 0)
        output += f"Total Voltage: {voltage:.2f} V\n"
        
        current = data.get("current", 0)
        output += f"Current: {current:.2f} A\n"
        
        power = data.get("power", 0)
        output += f"Power: {power:.2f} W\n"
        
        soc = data.get("battery_level", 0)
        output += f"State of Charge: {soc:.1f}%\n"
        
        status = "Charging" if data.get("battery_charging", False) else "Discharging"
        output += f"Status: {status}\n"
        
        cycle_charge = data.get("cycle_charge", 0)
        output += f"Cycle Charge: {cycle_charge:.2f} Ah\n"
        
        cycles = data.get("cycles", 0)
        output += f"Cycle Count: {cycles}\n"
        
        # Calculate average temperature
        temp_sensors = [data[key] for key in data if key.startswith("temp_") and key != "temp_sensors"]
        temp_avg = sum(temp_sensors) / len(temp_sensors) if temp_sensors else 0
        output += f"Average Temperature: {temp_avg:.1f}°C\n\n"
        
        # === Cell Voltages ===
        output += "=== Cell Voltages ===\n"
        
        cell_count = int(data.get("cell_count", 0))
        output += f"Number of cells: {cell_count}\n"
        
        for i in range(cell_count):
            cell_key = f"cell_voltage_{i}"
            if cell_key in data:
                output += f"Cell {i+1}: {data[cell_key]:.3f} V\n"
        
        output += "\n"
        
        # === Temperature Sensors ===
        output += "=== Temperature Sensors ===\n"
        
        temp_keys = sorted([key for key in data.keys() if key.startswith("temp_")])
        for temp_key in temp_keys:
            sensor_num = temp_key.split('_')[1]
            output += f"Sensor {sensor_num}: {data[temp_key]:.1f}°C\n"
        
        # Problem codes if present
        if "problem_code" in data and data["problem_code"] != 0:
            output += f"\nProblem Code: 0x{data['problem_code']:X}\n"
        
        output += "\nBMS update completed successfully!\n"
        output += "\n" + "-"*50 + "\n\n"  # Separator between entries
        
        return output
    
    async def log_data(self):
        """Fetch data from BMS and log it to file."""
        try:
            if not self.bms or not self.bms._bt.is_connected:
                logger.warning("Cannot log data: BMS not connected")
                return False
            
            # Fetch data with timeout
            data = await asyncio.wait_for(self.bms.update(), timeout=15)
            if not data:
                logger.warning("Received empty data from BMS")
                return False
                
            # Format data for log file
            log_line = self.format_data_for_log(data)
            
            # Write to log file
            with open(self.output_file, 'a') as f:
                f.write(log_line)
                
            self.data_count += 1
            logger.info(f"Data point #{self.data_count} logged successfully to {self.output_file}")
            
            # Print summary to console
            self._print_data_summary(data)
            return True
            
        except asyncio.TimeoutError:
            logger.error("Data update timed out")
        except Exception as e:
            logger.error(f"Error logging data: {type(e).__name__}: {str(e)}")
        
        return False
    
    def _print_data_summary(self, data: Dict[str, Any]):
        """Print a summary of the BMS data to console."""
        voltage = data.get("voltage", 0)
        current = data.get("current", 0)
        power = data.get("power", 0)
        soc = data.get("battery_level", 0)
        status = "Charging" if data.get("battery_charging", False) else "Discharging"
        
        # Get cell min/max
        cells = []
        for i in range(int(data.get("cell_count", 0))):
            cell_key = f"cell_voltage_{i}"
            if cell_key in data:
                cells.append(data[cell_key])
        
        min_cell = min(cells) if cells else 0
        max_cell = max(cells) if cells else 0
        delta = max_cell - min_cell
        
        print(f"\r{datetime.datetime.now().strftime('%H:%M:%S')} - "
              f"V: {voltage:.2f}V | I: {current:.2f}A | P: {power:.2f}W | "
              f"SoC: {soc:.1f}% | {status} | "
              f"Cells: {min_cell:.3f}V-{max_cell:.3f}V (Δ{delta:.3f}V)", end="")
        sys.stdout.flush()
    
    async def monitor_loop(self):
        """Main monitoring loop."""
        logger.info(f"Starting BMS monitoring, logging to {self.output_file} every {self.interval} seconds")
        
        while running:
            if not self.connected:
                connected = await self.connect()
                if not connected:
                    # Wait before retry
                    await asyncio.sleep(self.reconnect_delay)
                    continue
            
            # Log data if connected
            success = await self.log_data()
            if not success and not self.bms._bt.is_connected:
                # Connection lost, will attempt reconnect
                self.connected = False
                continue
            
            # Wait for next interval
            await asyncio.sleep(self.interval)
    
    async def shutdown(self):
        """Clean shutdown of the monitor."""
        logger.info("Shutting down BMS monitor")
        await self.disconnect()


def signal_handler(sig, frame):
    """Handle keyboard interrupt and other signals."""
    global running
    print("\nShutting down...")
    running = False

async def main():
    parser = argparse.ArgumentParser(description='Daly BMS Continuous Monitoring')
    parser.add_argument('-a', '--address', required=True, help='BMS Bluetooth address (e.g., 41:19:05:01:13:D0)')
    parser.add_argument('-n', '--name', default="Daly BMS", help='Device name')
    parser.add_argument('-o', '--output', default="bms_data.txt", help='Output log file')
    parser.add_argument('-i', '--interval', type=int, default=10, help='Polling interval in seconds')
    parser.add_argument('-s', '--scanner', action='store_true', help='Use scanner-based connection (more reliable)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run the monitor
    monitor = BMSMonitor(
        device_address=args.address,
        device_name=args.name,
        output_file=args.output,
        interval=args.interval,
        use_scanner=args.scanner,
        verbose=args.verbose
    )
    
    try:
        await monitor.monitor_loop()
    finally:
        await monitor.shutdown()
        print("\nMonitoring stopped")

if __name__ == "__main__":
    asyncio.run(main())
