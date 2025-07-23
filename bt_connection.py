import asyncio
import backoff
import bleak.exc
import re
import subprocess
import time
import uuid
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from typing import Callable, List, Union, Dict

from util import get_logger, FuturesPool

BleakDeviceNotFoundError = getattr(bleak.exc, 'BleakDeviceNotFoundError', bleak.exc.BleakError)

CharSpec = Union[BleakGATTCharacteristic, int, str, uuid.UUID]


@backoff.on_exception(backoff.expo, Exception, max_time=30, logger=None)
async def bt_discovery(logger, timeout=10, scan_duration=5.0):
    """Discover Bluetooth devices with enhanced scanning."""
    logger.info('BT Discovery (timeout=%ds, scan_duration=%.1fs):', timeout, scan_duration)
    
    try:
        # Use longer scan duration for better device discovery
        devices = await BleakScanner.discover(timeout=scan_duration)
        if not devices:
            logger.info(' - no devices found - ')
        else:
            logger.info('Found %d devices:', len(devices))
            for d in devices:
                logger.info("BT %s %26s", d.address, d.name or "<unnamed>")
        return devices
    except Exception as e:
        logger.error("BT discovery failed: %s", e)
        return []


def bleak_version() -> str:
    """Get the Bleak library version."""
    try:
        import bleak
        return bleak.__version__
    except AttributeError:
        from importlib.metadata import version
        return str(version('bleak'))


def bt_stack_version():
    """Get the Bluetooth stack version."""
    try:
        # get BlueZ version
        p = subprocess.Popen(["bluetoothctl", "--version"], stdout=subprocess.PIPE)
        out, _ = p.communicate()
        s = re.search(b"(\\d+).(\\d+)", out.strip(b"'"))
        bluez_version = tuple(map(int, s.groups()))
        return 'bluez-v%i.%i' % bluez_version
    except:
        return 'unknown'


async def bt_connection_diagnostics(logger, adapter=None):
    """Run Bluetooth connection diagnostics."""
    logger.info("=== Bluetooth Connection Diagnostics ===")
    
    # Check Bluetooth stack
    stack_version = bt_stack_version()
    logger.info("Bluetooth stack: %s", stack_version)
    logger.info("Bleak version: %s", bleak_version())
    
    # Check adapter status
    try:
        bt_power(True)  # Ensure BT is powered on
        logger.info("Bluetooth power: ON")
    except Exception as e:
        logger.error("Bluetooth power check failed: %s", e)
    
    # Run discovery test
    try:
        devices = await bt_discovery(logger, scan_duration=8.0)
        logger.info("Discovery test: Found %d devices", len(devices))
        return devices
    except Exception as e:
        logger.error("Discovery test failed: %s", e)
        return []


async def validate_bms_connection(bms_instance, max_validation_attempts=3):
    """Validate BMS connection health by attempting basic operations."""
    logger = bms_instance.logger
    
    for attempt in range(max_validation_attempts):
        try:
            logger.debug("Connection validation attempt %d/%d", attempt + 1, max_validation_attempts)
            
            # Check if still connected
            if not bms_instance.is_connected:
                raise RuntimeError("Connection lost")
            
            # Try to read services (basic connectivity test)
            services = bms_instance.client.services
            if not services:
                raise RuntimeError("No services available")
            
            logger.debug("Connection validation successful")
            return True
            
        except Exception as e:
            logger.warning("Connection validation failed (attempt %d/%d): %s", 
                         attempt + 1, max_validation_attempts, e)
            if attempt < max_validation_attempts - 1:
                await asyncio.sleep(1.0)
    
    logger.error("Connection validation failed after %d attempts", max_validation_attempts)
    return False


def bt_power(on):
    """Toggle Bluetooth power."""
    cmd = ["bluetoothctl", "power", "on" if on else "off"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        print(p, out, err)
        raise Exception('error with cmd %s: %s' % (cmd, bytes.decode(err or out, 'utf-8')))


class BtBms:
    """Base class for Bluetooth BMS connection."""
    shutdown = False

    def __init__(self, address: str, name: str, keep_alive=False, adapter=None, verbose_log=False):
        self.address = address
        self.name = name
        self.keep_alive = keep_alive
        self.verbose_log = verbose_log
        self.logger = get_logger(verbose_log)
        self._fetch_futures = FuturesPool()
        self._connect_time = 0
        self._pending_disconnect_call = False
        self._adapter = adapter
        self._in_disconnect = False
        
        # Initialize the client
        kwargs = {}
        if adapter:  # hci0, hci1 (BT adapter hardware)
            self.logger.info('Using adapter %s', adapter)
            kwargs['adapter'] = adapter
        
        self.client = BleakClient(address,
                                 disconnected_callback=self._on_disconnect,
                                 **kwargs)

    @property
    def connect_time(self):
        """Get the time of connection."""
        return self._connect_time

    async def start_notify(self, char_specifier: Union[CharSpec, List[CharSpec]],
                          callback: Callable[[int, bytearray], None], **kwargs) -> CharSpec:
        """Start notification on a characteristic."""
        if not isinstance(char_specifier, list):
            char_specifier = [char_specifier]
        exception = None
        for cs in char_specifier:
            try:
                try:
                    await self.client.stop_notify(cs)  # stop any orphan notifies
                except:
                    pass
                await self.client.start_notify(cs, callback, **kwargs)
                return cs
            except Exception as e:
                exception = e
        await enumerate_services(self.client, self.logger)
        raise exception

    def find_char(self, uuid_or_handle: Union[str, int], property_name: str, service=None):
        """Find characteristic by uuid or handle."""
        for service in ((service,) if service else self.client.services):
            for char in service.characteristics:
                if (char.uuid == uuid_or_handle or char.handle == uuid_or_handle) and property_name in char.properties:
                    return char if char.__hash__ else char.uuid
        return None

    def get_service(self, uuid):
        """Get service by UUID."""
        for s in self.client.services:
            if s.uuid.startswith(uuid):
                return s
        raise RuntimeError(f"service {uuid} not found (have {list(s.uuid for s in self.client.services)})")

    def _on_disconnect(self, _client):
        """Handle disconnection events."""
        # Skip warning if this was an intentional disconnect
        if self._in_disconnect:
            self.logger.debug('BMS %s disconnected intentionally after %.1fs', 
                           self.__str__(), time.time() - self._connect_time)
            return
            
        # Only log warning for unexpected disconnects
        if self.keep_alive and self._connect_time:
            self.logger.warning('BMS %s unexpectedly disconnected after %.1fs!', 
                             self.__str__(), time.time() - self._connect_time)

        if self.is_connected:
            self.logger.warning("%s _on_disconnect callback but is_connected=True", self.__str__())

        try:
            self._fetch_futures.clear()
        except Exception as e:
            self.logger.warning('Error clearing futures pool: %s', str(e) or type(e))

    async def _connect_client(self, timeout):
        """Internal connect method with enhanced error handling."""
        if BtBms.shutdown:
            raise RuntimeError("in shutdown")

        self.logger.debug("connecting BLE client %s (adapter %s, timeout %ds)",
                            self.client.address,
                            self._adapter or "default", timeout)
        try:
            await asyncio.wait_for(self.client.connect(timeout=timeout), timeout=timeout + 1)
            
            # Validate connection by checking if we can read services
            if self.client.is_connected:
                try:
                    services = self.client.services
                    if not services:
                        self.logger.warning("Connected but no services available, connection may be unstable")
                except Exception as e:
                    self.logger.warning("Connected but service enumeration failed: %s", e)
                    
        except BleakDeviceNotFoundError as exc:
            self.logger.error("%s, starting enhanced discovery", exc)
            await bt_discovery(self.logger, timeout=min(timeout, 10), scan_duration=8.0)
            raise
        except Exception as exc:
            self.logger.error("Connection failed: %s", exc)
            raise

        self._connect_time = time.time()
        self.logger.info("Successfully connected to %s", self.client.address)

        if self.verbose_log:
            try:
                await enumerate_services(self.client, logger=self.logger)
            except Exception as e:
                self.logger.debug("Service enumeration failed: %s", e)

    @property
    def is_connected(self):
        """Check if client is connected."""
        return self.client.is_connected

    async def connect(self, timeout=20, max_retries=3):
        """Establish a BLE connection with retry logic."""
        if self._pending_disconnect_call:
            self._pending_disconnect_call = False
            await self.disconnect()

        last_exception = None
        for attempt in range(max_retries):
            try:
                self.logger.debug("Connection attempt %d/%d", attempt + 1, max_retries)
                await self._connect_client(timeout=timeout)
                return  # Success!
                
            except BleakDeviceNotFoundError as e:
                last_exception = e
                self.logger.warning("Device not found on attempt %d/%d: %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    # Wait longer between retries, with exponential backoff
                    wait_time = 2 ** attempt
                    self.logger.info("Waiting %ds before retry...", wait_time)
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                last_exception = e
                self.logger.warning("Connection failed on attempt %d/%d: %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    wait_time = 1.5 ** attempt
                    self.logger.info("Waiting %.1fs before retry...", wait_time)
                    await asyncio.sleep(wait_time)
        
        # All retries failed
        self.logger.error("All %d connection attempts failed", max_retries)
        raise last_exception or RuntimeError("Connection failed after all retries")

    async def _connect_with_scanner(self, timeout=20, max_scan_attempts=3):
        """Connect with scanner, useful for some BMS types with enhanced reliability."""
        if self._pending_disconnect_call:
            self._pending_disconnect_call = False
            await self.disconnect()

        if BtBms.shutdown:
            raise RuntimeError("in shutdown")

        scanner_kw = {}
        if self._adapter:
            scanner_kw['adapter'] = self._adapter
        
        last_exception = None
        
        # Try multiple scan sessions if device not found
        for scan_attempt in range(max_scan_attempts):
            scanner = BleakScanner(**scanner_kw)
            self.logger.info("Starting scan session %d/%d", scan_attempt + 1, max_scan_attempts)
            
            try:
                await scanner.start()
                
                # Allow more time for device discovery in each scan session
                scan_duration = 5.0 + (scan_attempt * 2.0)  # Increase scan time with each attempt
                self.logger.debug("Scanning for %.1f seconds...", scan_duration)
                await asyncio.sleep(scan_duration)
                
                attempt = 1
                max_connect_attempts = 8
                
                while attempt <= max_connect_attempts:
                    try:
                        discovered = set(b.address for b in scanner.discovered_devices)
                        discovered_names = {b.address: b.name for b in scanner.discovered_devices}
                        
                        self.logger.debug("Discovered %d devices: %s", len(discovered), 
                                        {addr: name for addr, name in discovered_names.items()})
                        
                        if self.client.address not in discovered:
                            if attempt == 1:  # Only log this once per scan session
                                self.logger.warning(
                                    'Device %s not discovered in scan session %d. '
                                    'Found devices: %s. Make sure device is in range and not being accessed by another app.',
                                    self.client.address, scan_attempt + 1, list(discovered))
                            
                            if attempt < max_connect_attempts:
                                await asyncio.sleep(1.0)  # Wait before checking again
                                attempt += 1
                                continue
                            else:
                                raise BleakDeviceNotFoundError(
                                    self.client.address, 
                                    f'Device {self.client.address} not discovered after {max_connect_attempts} attempts. '
                                    f'Found devices: {list(discovered)}')

                        self.logger.debug("Device found, connect attempt %d", attempt)
                        await self._connect_client(timeout=timeout / 2)
                        await scanner.stop()
                        return  # Success!
                        
                    except BleakDeviceNotFoundError:
                        # Re-raise device not found errors
                        raise
                    except Exception as e:
                        last_exception = e
                        await self.client.disconnect()
                        if attempt < max_connect_attempts:
                            wait_time = 0.2 * (1.5 ** attempt)
                            self.logger.debug('Connect retry %d/%d after error %s (waiting %.1fs)', 
                                            attempt, max_connect_attempts, e, wait_time)
                            await asyncio.sleep(wait_time)
                            attempt += 1
                        else:
                            break  # Try next scan session
                            
            except Exception as e:
                last_exception = e
                self.logger.error("Scan session %d failed: %s", scan_attempt + 1, e)
            finally:
                try:
                    await scanner.stop()
                except:
                    pass
            
            # Wait between scan sessions
            if scan_attempt < max_scan_attempts - 1:
                wait_time = 3.0 + scan_attempt  # Increasing wait time
                self.logger.info("Waiting %.1fs before next scan session...", wait_time)
                await asyncio.sleep(wait_time)
        
        # All scan sessions failed
        self.logger.error("All %d scan sessions failed to connect", max_scan_attempts)
        raise last_exception or RuntimeError("Connection failed after all scan attempts")

    async def disconnect(self):
        """Disconnect from BMS."""
        if not self.client.is_connected:
            self.logger.debug("Disconnect called but client is already disconnected")
            return
            
        try:
            self._in_disconnect = True
            self.logger.debug("Disconnecting from %s", self.client.address)
            await self.client.disconnect()
            self.logger.debug("Successfully disconnected from %s", self.client.address)
        except Exception as e:
            self.logger.warning("Error during disconnect: %s", e)
        finally:
            self._in_disconnect = False
            self._fetch_futures.clear()

    def __str__(self):
        return f'{self.__class__.__name__}({self.client.address},{self.name})'

    async def __aenter__(self):
        if self.keep_alive and self.is_connected:
            return
        await self.connect()

    async def __aexit__(self, *args):
        if self.keep_alive:
            return
        if self.client.is_connected:
            await self.disconnect()

    def __await__(self):
        return self.__aexit__().__await__()

    def set_keep_alive(self, keep):
        """Set keep alive flag."""
        if keep:
            self.logger.debug("BMS %s keep alive enabled", self.__str__())
        self.keep_alive = keep


async def enumerate_services(client: BleakClient, logger):
    """Enumerate available services and characteristics."""
    try:
        services = client.services
        assert services
    except:
        services = await client.get_services()
    for service in services:
        logger.info(f"[Service] {service}")
        for char in service.characteristics:
            if "read" in char.properties:
                try:
                    value = bytes(await client.read_gatt_char(char.uuid))
                    logger.info(
                        f"\t[Characteristic] {char} ({','.join(char.properties)}), Value: {value}"
                    )
                except Exception as e:
                    logger.error(
                        f"\t[Characteristic] {char} ({','.join(char.properties)}), Value: {e}"
                    )

            else:
                value = None
                logger.info(
                    f"\t[Characteristic] {char} ({','.join(char.properties)}), Value: {value}"
                )
