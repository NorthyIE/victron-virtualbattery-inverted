#!/usr/bin/env python3

import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

SOURCE_SERVICE = os.environ.get("SOURCE_SERVICE", "com.victronenergy.battery.socketcan_vecan0")
VIRTUAL_NAME = os.environ.get("VIRTUAL_NAME", "com.victronenergy.battery.inverted_vecan0")
DEVICE_INSTANCE = int(os.environ.get("DEVICE_INSTANCE", "100"))
LOG_FILE = os.environ.get("LOG_FILE", "/data/log/dbus-virtual-battery/dbus-virtual-battery.log")
POLL_INTERVAL_MS = int(os.environ.get("POLL_INTERVAL_MS", "2000"))
POLL_RETRY_MAX_ATTEMPTS = int(os.environ.get("POLL_RETRY_MAX_ATTEMPTS", "3"))

VE_LIB_PATH = "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"
if VE_LIB_PATH not in sys.path:
    sys.path.insert(1, VE_LIB_PATH)

from vedbus import VeDbusService

logger = logging.getLogger("dbus_virtual_battery")

DATA_PATHS = {
    "/Dc/0/Voltage": lambda value: value,
    "/Dc/0/Current": lambda value: float(value) * -1,
    "/Dc/0/Power": lambda value: float(value) * -1,
    "/Soc": lambda value: value,
    "/Dc/0/Temperature": lambda value: value,
}


class VirtualInvertedBattery:
    def __init__(self):
        self.setup_logging()
        logger.info("Initializing virtual inverted battery...")

        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.dbusservice = VeDbusService(VIRTUAL_NAME, self.bus, register=False)
        self.mainloop = GLib.MainLoop()
        self.source_items = {}
        self.source_values = {}
        self.flush_updates_source_id = None
        self.poll_retry_count = {}

        self._setup_service_paths()
        self.dbusservice.register()
        self._setup_signal_receiver()
        self._verify_source_service_exists()
        self._prime_source_paths()
        self._setup_exit_handlers()

        GLib.timeout_add(POLL_INTERVAL_MS, self.poll_source)
        logger.info("Started monitoring %s.", SOURCE_SERVICE)

    def setup_logging(self):
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        if logger.handlers:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

        handler = RotatingFileHandler(LOG_FILE, maxBytes=50 * 1024, backupCount=1)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False

    def _verify_source_service_exists(self):
        """Verify that the source service is available on DBus at startup."""
        try:
            self.bus.get_object(SOURCE_SERVICE, "/Dc/0/Voltage")
            logger.info("Source service %s is available.", SOURCE_SERVICE)
        except dbus.DBusException as exc:
            logger.error("Source service %s not found: %s", SOURCE_SERVICE, exc)
            raise RuntimeError(f"Source service {SOURCE_SERVICE} not available on DBus")

    def _setup_exit_handlers(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("Service is shutting down on signal %s.", signum)
        try:
            if self.mainloop.is_running():
                self.mainloop.quit()
        except Exception as exc:
            logger.error("Error during shutdown: %s", exc)

    def _setup_service_paths(self):
        self.dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self.dbusservice.add_path("/Mgmt/ProcessVersion", "1.2")
        self.dbusservice.add_path("/Mgmt/Connection", "Virtual CAN Bus Bridge")
        self.dbusservice.add_path("/DeviceInstance", DEVICE_INSTANCE)
        self.dbusservice.add_path("/ProductId", 0xFFFF)
        self.dbusservice.add_path("/ProductName", "Virtual Inverted Battery")
        self.dbusservice.add_path("/Connected", 1)
        self.dbusservice.add_path("/CustomName", "Inverted Battery")

        for path in DATA_PATHS:
            self.dbusservice.add_path(path, 0)

    def _setup_signal_receiver(self):
        self.bus.add_signal_receiver(
            self.handle_dbus_change,
            dbus_interface="com.victronenergy.BusItem",
            signal_name="PropertiesChanged",
            path_keyword="path",
            bus_name=SOURCE_SERVICE,
        )

    def _prime_source_paths(self):
        for path in DATA_PATHS:
            try:
                proxy = self.bus.get_object(SOURCE_SERVICE, path)
                self.source_items[path] = dbus.Interface(proxy, "com.victronenergy.BusItem")
                self.poll_retry_count[path] = 0
            except dbus.DBusException as exc:
                logger.warning("DBus path %s is not available at startup: %s", path, exc)
                self.poll_retry_count[path] = 0

        self.poll_source()

    def handle_dbus_change(self, changes, path):
        value = changes.get("Value")
        if value is not None and path in DATA_PATHS:
            self.source_values[path] = value
            if path in self.poll_retry_count:
                self.poll_retry_count[path] = 0
            self._schedule_flush_updates()

    def _schedule_flush_updates(self):
        if self.flush_updates_source_id is None:
            self.flush_updates_source_id = GLib.timeout_add(50, self.flush_updates)

    def flush_updates(self):
        self.flush_updates_source_id = None

        for path, transform in DATA_PATHS.items():
            value = self.source_values.get(path)
            if value is None:
                continue

            try:
                new_value = transform(value)
                if self.dbusservice[path] != new_value:
                    self.dbusservice[path] = new_value
            except (TypeError, ValueError, dbus.DBusException) as exc:
                logger.error("Failed to map %s: %s", path, exc)

        if "/Dc/0/Power" not in self.source_values:
            self._update_power()

        return False

    def _update_power(self):
        """Calculate power from voltage and current if source doesn't provide it."""
        try:
            voltage = self.dbusservice["/Dc/0/Voltage"]
            current = self.dbusservice["/Dc/0/Current"]
            
            if voltage is None or current is None:
                return
            
            voltage = float(voltage)
            current = float(current)
            power = voltage * current
            
            if self.dbusservice["/Dc/0/Power"] != power:
                self.dbusservice["/Dc/0/Power"] = power
        except (TypeError, ValueError, dbus.DBusException) as exc:
            logger.error("Failed to calculate /Dc/0/Power: %s", exc)

    def poll_source(self):
        """Poll source service for current values with retry logic."""
        for path in DATA_PATHS:
            try:
                source_item = self.source_items.get(path)
                if source_item is None:
                    proxy = self.bus.get_object(SOURCE_SERVICE, path)
                    source_item = dbus.Interface(proxy, "com.victronenergy.BusItem")
                    self.source_items[path] = source_item
                    self.poll_retry_count[path] = 0

                self.source_values[path] = source_item.GetValue()
                self.poll_retry_count[path] = 0
            except dbus.DBusException as exc:
                retry_count = self.poll_retry_count.get(path, 0)
                if retry_count < POLL_RETRY_MAX_ATTEMPTS:
                    self.poll_retry_count[path] = retry_count + 1
                    logger.debug("Polling failed for %s (attempt %d/%d): %s", 
                               path, retry_count + 1, POLL_RETRY_MAX_ATTEMPTS, exc)
                else:
                    self.source_items.pop(path, None)
                    logger.warning("Polling failed for %s after %d attempts, removing from cache", 
                                 path, POLL_RETRY_MAX_ATTEMPTS)

        self._schedule_flush_updates()
        return True

    def run(self):
        self.mainloop.run()


if __name__ == "__main__":
    # Setup logging before any logger calls
    try:
        service = VirtualInvertedBattery()
        service.run()
    except Exception as exc:
        # Always try to log, but have fallback to stderr
        try:
            if logger.handlers:
                logger.critical("Service crashed: %s", exc)
            else:
                print(f"Service crashed: {exc}", file=sys.stderr)
        except Exception:
            print(f"Service crashed: {exc}", file=sys.stderr)
        sys.exit(1)