#!/usr/bin/env python3
"""
Example script to connect to a Daly BMS via Bluetooth and display all the details.
Run this script on your Raspberry Pi with Bluetooth enabled.
"""

import asyncio
import logging
import argparse
from bleak import BleakScanner
from daly_bms import DalyBMS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("example")

async def scan_for_daly_bms():
    """Scan for Daly BMS devices."""
    print("Scanning for Daly BMS devices...")
    devices = await BleakScanner.discover()
    
    daly_devices = []
    for device in devices:
        # Daly BMS typically has a name starting with "DL-"
        if device.name and device.name.startswith("DL-"):
            daly_devices.append(device)
            print(f"Found Daly BMS: {device.name} ({device.address})")
            
    return daly_devices

async def display_bms_info(device, reconnect=False, verbose=False):
    """Connect to BMS and display information."""
    bms = DalyBMS(device, reconnect=reconnect, verbose_log=verbose)
    
    try:
        print(f"\nConnecting to {bms}...")
        await bms.connect()
        print("Connected successfully!")
        
        print("\nFetching BMS data...")
        data = await bms.update()
        
        if not data:
            print("Failed to retrieve BMS data!")
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
    finally:
        print("Disconnecting from BMS...")
        await bms.disconnect()
        print("Disconnected")

async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Connect to Daly BMS via Bluetooth')
    parser.add_argument('-a', '--address', help='Bluetooth address of the Daly BMS')
    parser.add_argument('-n', '--name', help='Device name', default="Daly BMS")
    parser.add_argument('-r', '--reconnect', action='store_true', help='Reconnect after each update')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()
    
    # If no address provided, scan for devices
    if not args.address:
        devices = await scan_for_daly_bms()
        if not devices:
            print("No Daly BMS devices found!")
            return
            
        # Use the first found device
        device = devices[0]
    else:
        # Create a custom device with the provided address
        from bleak.backends.device import BLEDevice
        device = BLEDevice(args.address, args.name)
    
    # Display BMS information
    await display_bms_info(device, args.reconnect, args.verbose)

if __name__ == "__main__":
    # Run the event loop
    asyncio.run(main())
