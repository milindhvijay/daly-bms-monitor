#!/usr/bin/env python3
"""
Optimized example script to connect to a Daly BMS via Bluetooth with enhanced reliability.
This version combines your existing code with our reliability improvements.
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
logger = logging.getLogger("example_optimized")

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
    
    if not daly_devices and all_devices:
        print("No Daly BMS devices found.")
        print("All discovered devices:")
        for device in all_devices:
            print(f"  - {device.name or '<unnamed>'} ({device.address})")
            
    return daly_devices

async def display_bms_info(device, reconnect=False, verbose=False, use_scanner=False):
    """Connect to BMS and display information with enhanced reliability."""
    bms = DalyBMS(device, reconnect=reconnect, verbose_log=verbose)
    
    try:
        print(f"\nConnecting to {bms}...")
        try:
            # Use enhanced connection methods with reliability improvements
            if use_scanner:
                print("Using scanner-based connection for better reliability...")
                await bms.connect(timeout=30, max_retries=3, use_scanner=True)
            else:
                print("Using standard connection with retry logic...")
                await bms.connect(timeout=30, max_retries=3)
                
            print("Connected successfully!")
            
            # Validate connection health (optional but recommended)
            print("Validating connection health...")
            if await validate_bms_connection(bms):
                print("Connection validation passed!")
            else:
                print("Warning: Connection validation failed, but proceeding...")
                
        except asyncio.TimeoutError:
            print("Connection timed out! Make sure the BMS is powered on and within range.")
            return
        except Exception as connect_err:
            print(f"Connection error: {type(connect_err).__name__}: {str(connect_err)}")
            return
        
        print("\nFetching BMS data...")
        try:
            data = await asyncio.wait_for(bms.update(), timeout=15)
            
            if not data:
                print("Failed to retrieve BMS data - empty response!")
                return
        except asyncio.TimeoutError:
            print("Data retrieval timed out!")
            return
        except Exception as update_err:
            print(f"Data update error: {type(update_err).__name__}: {str(update_err)}")
            return
            
        # Display general information
        print("\n=== BMS General Information ===")
        if "voltage" in data:
            print(f"Total Voltage: {data['voltage']:.2f} V")
        if "current" in data:
            print(f"Current: {data['current']:.2f} A")
        if "power" in data:
            print(f"Power: {data['power']:.2f} W")
        if "battery_level" in data:
            print(f"State of Charge: {data['battery_level']:.1f}%")
        if "battery_charging" in data:
            status = "Charging" if data["battery_charging"] else "Discharging"
            print(f"Status: {status}")
        if "cycle_charge" in data:
            print(f"Cycle Charge: {data['cycle_charge']:.2f} Ah")
        if "cycles" in data:
            print(f"Cycle Count: {data['cycles']}")
        if "temperature" in data:
            print(f"Average Temperature: {data['temperature']:.1f}°C")
            
        # Display cell voltages
        print("\n=== Cell Voltages ===")
        cell_count = int(data["cell_count"])
        print(f"Number of cells: {cell_count}")
        
        for i in range(cell_count):
            cell_key = f"cell_voltage_{i}"
            if cell_key in data:
                print(f"Cell {i+1}: {data[cell_key]:.3f} V")
                
        # Display all temperature sensors
        print("\n=== Temperature Sensors ===")
        temp_sensors = [key for key in data.keys() if key.startswith("temp_")]
        for temp_key in sorted(temp_sensors):
            sensor_num = temp_key.split('_')[1]
            print(f"Sensor {sensor_num}: {data[temp_key]:.1f}°C")
            
        # Display any problem codes
        if "problem_code" in data and data["problem_code"] != 0:
            print(f"\nProblem Code: 0x{data['problem_code']:X}")
            
        print("\nBMS update completed successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        logger.error("BMS connection/data retrieval failed", exc_info=True)
    finally:
        print("Disconnecting from BMS...")
        try:
            await bms.disconnect()
            print("Disconnected")
        except Exception as e:
            print(f"Warning: Error during disconnect: {e}")

async def run_diagnostics():
    """Run Bluetooth connection diagnostics."""
    print("\nRunning Bluetooth diagnostics...")
    devices = await bt_connection_diagnostics(logger)
    return devices

async def main():
    parser = argparse.ArgumentParser(description='Optimized Daly BMS Bluetooth Example with Reliability Features')
    parser.add_argument('-a', '--address', help='BMS Bluetooth address (e.g., AA:BB:CC:DD:EE:FF)')
    parser.add_argument('-n', '--name', help='Device name', default="Daly BMS")
    parser.add_argument('-r', '--reconnect', action='store_true', help='Reconnect after each update')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('-d', '--diagnostics', action='store_true', help='Run Bluetooth diagnostics first')
    parser.add_argument('-s', '--scanner', action='store_true', help='Use scanner-based connection method')
    parser.add_argument('-e', '--extended-scan', action='store_true', help='Use extended scanning duration')
    
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
            from bleak.backends.device import BLEDevice
            try:
                # Try the new bleak version constructor
                device = BLEDevice(args.address, args.name)
            except TypeError:
                # Fall back to older bleak version constructor that requires details
                import platform
                details = {}
                device = BLEDevice(args.address, args.name, details)
            
            await display_bms_info(device, args.reconnect, args.verbose, args.scanner)
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
            
            await display_bms_info(selected_device, args.reconnect, args.verbose, args.scanner)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
        logger.error("Unexpected error in main", exc_info=True)

if __name__ == "__main__":
    # Run the event loop
    asyncio.run(main())
