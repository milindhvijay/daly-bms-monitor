"""Module to support Daly Smart BMS via Bluetooth."""

import asyncio
from collections.abc import Callable
import logging
from typing import Final, Dict, Union, List
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.uuids import normalize_uuid_str

from bt_connection import BtBms

# Constants for BMS attributes
ATTR_VOLTAGE = "voltage"
ATTR_CURRENT = "current"
ATTR_BATTERY_LEVEL = "battery_level"  # SOC in %
ATTR_BATTERY_CHARGING = "battery_charging"
ATTR_POWER = "power"  # in watts
ATTR_CYCLE_CHRG = "cycle_charge"  # Ah
ATTR_CYCLE_CAP = "cycle_capacity"  # Wh
ATTR_CYCLES = "cycles"
ATTR_DELTA_VOLTAGE = "delta_cell_voltage"
ATTR_TEMPERATURE = "temperature"
ATTR_RUNTIME = "runtime"  # in seconds
ATTR_PROBLEM = "problem"

# Keys for special data
KEY_CELL_COUNT = "cell_count"
KEY_CELL_VOLTAGE = "cell_voltage_"
KEY_TEMP_SENS = "temp_sensors"
KEY_TEMP_VALUE = "temp_"
KEY_PROBLEM = "problem_code"
KEY_DESIGN_CAP = "design_capacity"

# Type definition for BMS samples
BMSsample = Dict[str, Union[int, float, bool]]


def crc_modbus(data: bytearray) -> int:
    """Calculate CRC-16-CCITT MODBUS."""
    crc: int = 0xFFFF
    for i in data:
        crc ^= i & 0xFF
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc % 2 else (crc >> 1)
    return crc & 0xFFFF


class DalyBMS:
    """Daly Smart BMS implementation."""

    HEAD_READ: Final[bytes] = b"\xD2\x03"
    CMD_INFO: Final[bytes] = b"\x00\x00\x00\x3E\xD7\xB9"
    MOS_INFO: Final[bytes] = b"\x00\x3E\x00\x09\xF7\xA3"
    HEAD_LEN: Final[int] = 3
    CRC_LEN: Final[int] = 2
    MAX_CELLS: Final[int] = 32
    MAX_TEMP: Final[int] = 8
    INFO_LEN: Final[int] = 84 + HEAD_LEN + CRC_LEN + MAX_CELLS + MAX_TEMP
    MOS_TEMP_POS: Final[int] = HEAD_LEN + 8
    TIMEOUT: Final[int] = 10
    MAX_CELL_VOLTAGE: Final[float] = 5.906  # max cell potential
    
    _FIELDS: Final[list[tuple[str, int, int, Callable[[int], int | float]]]] = [
        (ATTR_VOLTAGE, 80 + HEAD_LEN, 2, lambda x: float(x / 10)),
        (ATTR_CURRENT, 82 + HEAD_LEN, 2, lambda x: float((x - 30000) / 10)),
        (ATTR_BATTERY_LEVEL, 84 + HEAD_LEN, 2, lambda x: float(x / 10)),
        (ATTR_CYCLE_CHRG, 96 + HEAD_LEN, 2, lambda x: float(x / 10)),
        (KEY_CELL_COUNT, 98 + HEAD_LEN, 2, lambda x: min(x, DalyBMS.MAX_CELLS)),
        (KEY_TEMP_SENS, 100 + HEAD_LEN, 2, lambda x: min(x, DalyBMS.MAX_TEMP)),
        (ATTR_CYCLES, 102 + HEAD_LEN, 2, lambda x: x),
        (ATTR_DELTA_VOLTAGE, 112 + HEAD_LEN, 2, lambda x: float(x / 1000)),
        (KEY_PROBLEM, 116 + HEAD_LEN, 8, lambda x: x % 2**64),
    ]

    def __init__(self, ble_device: BLEDevice, reconnect: bool = False, verbose_log: bool = False):
        """Initialize Daly BMS."""
        self.name = ble_device.name or "undefined"
        self._ble_device = ble_device
        self._reconnect = reconnect
        self._log = logging.getLogger(f"DalyBMS::{self.name}:{self._ble_device.address[-5:].replace(':','')}")
        
        if verbose_log:
            self._log.setLevel(logging.DEBUG)
        else:
            self._log.setLevel(logging.INFO)
            
        # Setup logging handler if not already present
        if not self._log.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self._log.addHandler(handler)
        
        # Create BT connection
        self._bt = BtBms(ble_device.address, self.name, keep_alive=not reconnect, verbose_log=verbose_log)
        
        # Setup data buffer and event
        self._data: bytearray = bytearray()
        self._data_event: Final[asyncio.Event] = asyncio.Event()

    @staticmethod
    def matcher_dict_list() -> list[dict]:
        """Provide BluetoothMatcher definition."""
        return [
            {
                "local_name": "DL-*",
                "service_uuid": DalyBMS.uuid_services()[0],
                "connectable": True,
            },
        ] + [
            {"manufacturer_id": m_id, "connectable": True}
            for m_id in (0x102, 0x104, 0x0302)
        ]

    @staticmethod
    def device_info() -> dict[str, str]:
        """Return device information for the battery management system."""
        return {"manufacturer": "Daly", "model": "Smart BMS"}

    @staticmethod
    def uuid_services() -> list[str]:
        """Return list of 128-bit UUIDs of services required by BMS."""
        return [normalize_uuid_str("fff0")]

    @staticmethod
    def uuid_rx() -> str:
        """Return 16-bit UUID of characteristic that provides notification/read property."""
        return "fff1"

    @staticmethod
    def uuid_tx() -> str:
        """Return 16-bit UUID of characteristic that provides write property."""
        return "fff2"

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle notifications from the BMS."""
        self._log.debug("RX BLE data: %s", data)

        if (
            len(data) < DalyBMS.HEAD_LEN
            or data[0:2] != DalyBMS.HEAD_READ
            or int(data[2]) + 1 != len(data) - len(DalyBMS.HEAD_READ) - DalyBMS.CRC_LEN
        ):
            self._log.debug("response data is invalid")
            return

        if (crc := crc_modbus(data[:-2])) != int.from_bytes(
            data[-2:], byteorder="little"
        ):
            self._log.debug(
                "invalid checksum 0x%X != 0x%X",
                int.from_bytes(data[-2:], byteorder="little"),
                crc,
            )
            self._data.clear()
            return

        self._data = data
        self._data_event.set()

    async def _await_reply(self, data: bytes) -> None:
        """Send data to the BMS and wait for valid reply notification."""
        self._log.debug("TX BLE data: %s", data.hex(" "))
        self._data_event.clear()  # clear event before requesting new data
        await self._bt.client.write_gatt_char(normalize_uuid_str(self.uuid_tx()), data)
        await asyncio.wait_for(self._data_event.wait(), timeout=self.TIMEOUT)
        self._data_event.clear()

    async def connect(self) -> None:
        """Connect to the BMS."""
        if not self._bt.is_connected:
            await self._bt.connect()
            await self._bt.client.start_notify(
                normalize_uuid_str(self.uuid_rx()), self._notification_handler
            )

    async def disconnect(self) -> None:
        """Disconnect from the BMS."""
        if self._bt.is_connected:
            await self._bt.disconnect()

    async def update(self) -> BMSsample:
        """Update battery status information."""
        await self.connect()
        
        data: BMSsample = {}
        try:
            # request MOS temperature (possible outcome: response, empty response, no response)
            await self._await_reply(DalyBMS.HEAD_READ + DalyBMS.MOS_INFO)

            if sum(self._data[DalyBMS.MOS_TEMP_POS :][:2]):
                self._log.debug("MOS info: %s", self._data)
                data |= {
                    f"{KEY_TEMP_VALUE}0": float(
                        int.from_bytes(
                            self._data[DalyBMS.MOS_TEMP_POS :][:2],
                            byteorder="big",
                            signed=True,
                        )
                        - 40
                    )
                }
        except asyncio.TimeoutError:
            self._log.debug("no MOS temperature available.")

        await self._await_reply(DalyBMS.HEAD_READ + DalyBMS.CMD_INFO)

        if len(self._data) != DalyBMS.INFO_LEN:
            self._log.debug("incorrect frame length: %i", len(self._data))
            return {}

        data |= {
            key: func(
                int.from_bytes(
                    self._data[idx : idx + size], byteorder="big", signed=True
                )
            )
            for key, idx, size, func in DalyBMS._FIELDS
        }

        # Get temperatures
        # shift index if MOS temperature is available
        t_off: Final[int] = 1 if f"{KEY_TEMP_VALUE}0" in data else 0
        data |= {
            f"{KEY_TEMP_VALUE}{((idx-64-DalyBMS.HEAD_LEN)>>1) + t_off}": float(
                int.from_bytes(self._data[idx : idx + 2], byteorder="big", signed=True)
                - 40
            )
            for idx in range(
                64 + self.HEAD_LEN, 64 + self.HEAD_LEN + int(data[KEY_TEMP_SENS]) * 2, 2
            )
        }

        # Get cell voltages
        data |= {
            f"{KEY_CELL_VOLTAGE}{idx}": float(
                int.from_bytes(
                    self._data[DalyBMS.HEAD_LEN + 2 * idx : DalyBMS.HEAD_LEN + 2 * idx + 2],
                    byteorder="big",
                    signed=True,
                )
                / 1000
            )
            for idx in range(int(data[KEY_CELL_COUNT]))
        }

        # Calculate additional values
        self._add_missing_values(data)

        if self._reconnect:
            # disconnect after data update to force reconnect next time
            await self.disconnect()

        return data
    
    def _add_missing_values(self, data: BMSsample) -> None:
        """Calculate missing BMS values from existing ones."""
        if not data:
            return
            
        # Calculate power from voltage and current
        if ATTR_VOLTAGE in data and ATTR_CURRENT in data and ATTR_POWER not in data:
            data[ATTR_POWER] = round(data[ATTR_VOLTAGE] * data[ATTR_CURRENT], 3)
            
        # Calculate charge indicator from current
        if ATTR_CURRENT in data and ATTR_BATTERY_CHARGING not in data:
            data[ATTR_BATTERY_CHARGING] = data[ATTR_CURRENT] > 0
            
        # Calculate temperature (average of all sensors)
        if f"{KEY_TEMP_VALUE}0" in data and ATTR_TEMPERATURE not in data:
            temps = [v for k, v in data.items() if k.startswith(KEY_TEMP_VALUE)]
            data[ATTR_TEMPERATURE] = round(sum(temps) / len(temps), 3)
            
    async def get_cell_voltages(self) -> List[float]:
        """Get list of cell voltages."""
        data = await self.update()
        return [data[f"{KEY_CELL_VOLTAGE}{idx}"] for idx in range(int(data[KEY_CELL_COUNT]))]
        
    async def get_temperatures(self) -> List[float]:
        """Get list of temperature readings."""
        data = await self.update()
        return [v for k, v in data.items() if k.startswith(KEY_TEMP_VALUE)]

    def __str__(self):
        """String representation."""
        return f"DalyBMS({self._ble_device.address}, {self.name})"
