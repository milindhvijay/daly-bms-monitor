#!/usr/bin/env python3
"""
Enhanced example script to connect to a Daly BMS via Bluetooth with improved reliability.
This example demonstrates the enhanced connection features including retry logic,
connection diagnostics, and better error handling for intermittent BMS detection issues.

Run this script on your Raspberry Pi with Bluetooth enabled.
"""

import asyncio
import logging
import argparse
import sys
from bleak import BleakScanner
from daly_bms import DalyBMS
from bt_connection import bt_connection_diagnostics, validate_bms_connection

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("example_reliable")

async def scan_for_daly_bms(extended_scan=False):
    """Scan for Daly BMS devices with optional extended scanning."""
    scan_duration = 10.0 if extended_scan else 5.0
    print(f"Scanning for Daly BMS devices (duration: {scan_duration}s)...")
    
    devices = await BleakScanner.discover(timeout=scan_duration)
    
    daly_devices = []
    all_devices = []
    
    for device in devices:
        all_devices.append(device)
        # Daly BMS typically has a name starting with "DL-"
        if device.name and device.name.startswith("DL-"):
            daly_devices.append(device)
            print(f"Found Daly BMS: {device.name} ({device.address})")
    
    if not daly_devices:
        print("No Daly BMS devices found.")
        if not extended_scan:
            print("All discovered devices:")
            for device in all_devices:
                print(f"  - {device.name or '<unnamed>'} ({device.address})")
            
    return daly_devices

async def display_bms_info_reliable(device, reconnect=False, verbose=False, use_scanner=False):
    """Connect to BMS and display information with enhanced reliability."""
    bms = DalyBMS(device, reconnect=reconnect, verbose_log=verbose)
    
    try:
        print(f"\nConnecting to {bms} with enhanced reliability...")
        
        if use_scanner:
            print("Using scanner-based connection for better reliability...")
            await bms._connect_with_scanner(timeout=30, max_scan_attempts=3)
        else:
            print("Using standard connection with retry logic...")
            await bms.connect(timeout=25, max_retries=3)
            
        print("Connected successfully!")
        
        # Validate connection health
        print("Validating connection health...")
        if await validate_bms_connection(bms):
            print("Connection validation passed!")
        else:
            print("Warning: Connection validation failed, but proceeding...")
        
        print("\nFetching BMS data...")
        data = await bms.update()
        
        if not data:
            print("Failed to retrieve BMS data!")
            return
            
        # Display general information
        print(f"\n{'='*50}")
        print(f"BMS Information for {device.name} ({device.address})")
        print(f"{'='*50}")
        
        # Voltage information
        if 'voltage' in data:
            print(f"\nVoltage Information:")
            voltage_data = data['voltage']
            print(f"  Total Voltage: {voltage_data.get('total', 'N/A')} V")
            print(f"  Cell Count: {len(voltage_data.get('cells', []))}")
            
            cells = voltage_data.get('cells', [])
            if cells:
                print(f"  Cell Voltages:")
                for i, cell_v in enumerate(cells, 1):
                    print(f"    Cell {i:2d}: {cell_v:.3f} V")
                
                min_cell = min(cells)
                max_cell = max(cells)
                print(f"  Min Cell: {min_cell:.3f} V")
                print(f"  Max Cell: {max_cell:.3f} V")
                print(f"  Cell Difference: {max_cell - min_cell:.3f} V")
        
        # Current and power
        if 'current' in data:
            current = data['current']
            print(f"\nCurrent: {current} A")
        
        if 'power' in data:
            power = data['power']
            print(f"Power: {power} W")
        
        # SOC and capacity
        if 'soc' in data:
            soc = data['soc']
            print(f"State of Charge: {soc}%")
            
        if 'capacity' in data:
            capacity_data = data['capacity']
            print(f"\nCapacity Information:")
            print(f"  Remaining: {capacity_data.get('ah_remaining', 'N/A')} Ah")
            print(f"  Total: {capacity_data.get('ah_total', 'N/A')} Ah")
        
        # Temperature
        if 'temperature' in data:
            temp_data = data['temperature']
            temps = temp_data.get('temperatures', [])
            if temps:
                print(f"\nTemperatures:")
                for i, temp in enumerate(temps, 1):
                    print(f"  Sensor {i}: {temp}°C")
        
        # Status and alarms
        if 'status' in data:
            status = data['status']
            print(f"\nStatus: {status}")
            
        if 'alarms' in data:
            alarms = data['alarms']
            if any(alarms.values()):
                print(f"\nActive Alarms:")
                for alarm, active in alarms.items():
                    if active:
                        print(f"  - {alarm}")
            else:
                print(f"\nNo active alarms")
        
        print(f"\n{'='*50}")
        print("Data retrieval completed successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        logger.error("BMS connection/data retrieval failed", exc_info=True)
    finally:
        try:
            await bms.disconnect()
            print("Disconnected from BMS")
        except Exception as e:
            print(f"Warning: Error during disconnect: {e}")

async def run_diagnostics():
    """Run Bluetooth connection diagnostics."""
    print("\nRunning Bluetooth diagnostics...")
    devices = await bt_connection_diagnostics(logger)
    return devices

async def main():
    parser = argparse.ArgumentParser(description='Enhanced Daly BMS Bluetooth Example with Reliability Features')
    parser.add_argument('--address', '-a', help='BMS Bluetooth address (e.g., AA:BB:CC:DD:EE:FF)')
    parser.add_argument('--reconnect', '-r', action='store_true', help='Enable reconnection on disconnect')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--diagnostics', '-d', action='store_true', help='Run Bluetooth diagnostics first')
    parser.add_argument('--scanner', '-s', action='store_true', help='Use scanner-based connection method')
    parser.add_argument('--extended-scan', '-e', action='store_true', help='Use extended scanning duration')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Run diagnostics if requested
        if args.diagnostics:
            await run_diagnostics()
            print()
        
        # If address is provided, connect directly
        if args.address:
            # Create a mock device object
            class MockDevice:
                def __init__(self, address):
                    self.address = address
                    self.name = f"DL-{address.replace(':', '')[-6:]}"  # Generate a name
            
            device = MockDevice(args.address)
            await display_bms_info_reliable(device, args.reconnect, args.verbose, args.scanner)
        else:
            # Scan for devices
            devices = await scan_for_daly_bms(args.extended_scan)
            
            if not devices:
                print("\nNo Daly BMS devices found. Try:")
                print("1. Make sure your BMS is powered on and in range")
                print("2. Check that no other app is connected to the BMS")
                print("3. Use --extended-scan for longer scanning")
                print("4. Use --diagnostics to check Bluetooth status")
                print("5. Specify address directly with --address if you know it")
                sys.exit(1)
            
            # If multiple devices found, let user choose
            if len(devices) > 1:
                print(f"\nFound {len(devices)} Daly BMS devices:")
                for i, device in enumerate(devices):
                    print(f"{i+1}. {device.name} ({device.address})")
                
                while True:
                    try:
                        choice = input(f"\nSelect device (1-{len(devices)}): ")
                        idx = int(choice) - 1
                        if 0 <= idx < len(devices):
                            selected_device = devices[idx]
                            break
                        else:
                            print("Invalid selection. Please try again.")
                    except (ValueError, KeyboardInterrupt):
                        print("\nExiting...")
                        sys.exit(0)
            else:
                selected_device = devices[0]
            
            await display_bms_info_reliable(selected_device, args.reconnect, args.verbose, args.scanner)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
        logger.error("Unexpected error in main", exc_info=True)

if __name__ == "__main__":
    # Run the event loop
    asyncio.run(main())
