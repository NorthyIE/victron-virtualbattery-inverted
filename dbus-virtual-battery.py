#!/usr/bin/env python3

import logging
import os
import signal
import sys
import xml.etree.ElementTree as ET
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, Optional, Set

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

SOURCE_SERVICE = os.environ.get("SOURCE_SERVICE", "com.victronenergy.battery.socketcan_vecan0")
VIRTUAL_NAME = os.environ.get("VIRTUAL_NAME", "com.victronenergy.battery.inverted_vecan0")
DEVICE_INSTANCE = int(os.environ.get("DEVICE_INSTANCE", "100"))
LOG_FILE = os.environ.get("LOG_FILE", "/data/log/dbus-virtual-battery/dbus-virtual-battery.log")
POLL_INTERVAL_MS = int(os.environ.get("POLL_INTERVAL_MS", "2000"))
DISCOVERY_INTERVAL_MS = int(os.environ.get("DISCOVERY_INTERVAL_MS", "30000"))

VE_LIB_PATH = "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"
if VE_LIB_PATH not in sys.path:
    sys.path.insert(1, VE_LIB_PATH)

from vedbus import VeDbusService

logger = logging.getLogger("dbus_virtual_battery")

INVERTED_PATHS = {
    "/Dc/0/Current",
    "/Dc/0/Power",
}

OWN_METADATA_PATHS = {
    "/Mgmt/ProcessName",
    "/Mgmt/ProcessVersion",
    "/Mgmt/Connection",
    "/DeviceInstance",
    "/ProductId",
    "/ProductName",
    "/Connected",
    "/CustomName",
}

IGNORED_SOURCE_PATHS = {
    "/State",
    "/SystemSwitch",
}


def identity(value: Any) -> Any:
    return value


def invert_signed_numeric(value: Any) -> float:
    return float(value) * -1


class VirtualInvertedBattery:
    def __init__(self):
        self.setup_logging()
        logger.info("Initializing virtual inverted battery from %s to %s", SOURCE_SERVICE, VIRTUAL_NAME)

        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.dbusservice = VeDbusService(VIRTUAL_NAME, self.bus, register=False)
        self.mainloop = GLib.MainLoop()
        self.source_items: Dict[str, dbus.Interface] = {}
        self.source_values: Dict[str, Any] = {}
        self.active_paths: Dict[str, Callable[[Any], Any]] = {}
        self.flush_updates_source_id: Optional[int] = None

        self._setup_service_paths()
        self._discover_and_enable_paths()
        self.dbusservice.register()
        self._setup_signal_receiver()
        self._prime_source_paths()
        self._setup_exit_handlers()

        GLib.timeout_add(POLL_INTERVAL_MS, self.poll_source)
        GLib.timeout_add(DISCOVERY_INTERVAL_MS, self.refresh_discovery)
        logger.info("Started monitoring %s with %d mirrored paths.", SOURCE_SERVICE, len(self.active_paths))

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

    def _setup_exit_handlers(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("Service is shutting down on signal %s.", signum)
        if self.mainloop.is_running():
            self.mainloop.quit()

    def _setup_service_paths(self):
        self.dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self.dbusservice.add_path("/Mgmt/ProcessVersion", "3.1")
        self.dbusservice.add_path("/Mgmt/Connection", f"Virtual Battery via {SOURCE_SERVICE}")
        self.dbusservice.add_path("/DeviceInstance", DEVICE_INSTANCE)
        self.dbusservice.add_path("/ProductId", 0xFFFF)
        self.dbusservice.add_path("/ProductName", "Virtual Inverted Battery")
        self.dbusservice.add_path("/Connected", 1)
        self.dbusservice.add_path("/CustomName", "Inverted Battery")

    def _transform_for_path(self, path: str) -> Callable[[Any], Any]:
        if path in INVERTED_PATHS:
            return invert_signed_numeric
        return identity

    def _probe_path(self, path: str) -> Optional[Any]:
        try:
            proxy = self.bus.get_object(SOURCE_SERVICE, path)
            iface = dbus.Interface(proxy, "com.victronenergy.BusItem")
            return iface.GetValue()
        except dbus.DBusException:
            return None

    def _enable_path(self, path: str, default_value: Any):
        if path in self.active_paths or path in OWN_METADATA_PATHS or path in IGNORED_SOURCE_PATHS:
            return

        transform = self._transform_for_path(path)
        self.active_paths[path] = transform
        self.dbusservice.add_path(path, default_value)
        logger.info("Mirroring path: %s", path)

    def _discover_bus_item_paths(self, root_path: str = "/") -> Set[str]:
        discovered: Set[str] = set()
        visited: Set[str] = set()

        def walk(path: str):
            if path in visited:
                return
            visited.add(path)

            try:
                proxy = self.bus.get_object(SOURCE_SERVICE, path)
            except dbus.DBusException:
                return

            try:
                iface = dbus.Interface(proxy, "com.victronenergy.BusItem")
                iface.GetValue()
                if path not in OWN_METADATA_PATHS and path not in IGNORED_SOURCE_PATHS:
                    discovered.add(path)
            except dbus.DBusException:
                pass

            try:
                introspect = dbus.Interface(proxy, "org.freedesktop.DBus.Introspectable")
                xml_data = introspect.Introspect()
                node = ET.fromstring(xml_data)
                for child in node.findall("node"):
                    name = child.attrib.get("name")
                    if not name:
                        continue
                    if path == "/":
                        child_path = f"/{name}"
                    else:
                        child_path = f"{path}/{name}"
                    walk(child_path)
            except (dbus.DBusException, ET.ParseError):
                return

        walk(root_path)
        return discovered

    def _discover_and_enable_paths(self):
        discovered_paths = self._discover_bus_item_paths()
        enabled_count_before = len(self.active_paths)

        for path in sorted(discovered_paths):
            value = self._probe_path(path)
            if value is None:
                continue
            self._enable_path(path, value)
            self.source_values[path] = value

        enabled_count_after = len(self.active_paths)
        if enabled_count_after != enabled_count_before:
            logger.info(
                "Discovered %d additional mirrored paths.",
                enabled_count_after - enabled_count_before,
            )

    def refresh_discovery(self):
        self._discover_and_enable_paths()
        self._prime_missing_source_items()
        self._schedule_flush_updates()
        return True

    def _setup_signal_receiver(self):
        self.bus.add_signal_receiver(
            self.handle_dbus_change,
            dbus_interface="com.victronenergy.BusItem",
            signal_name="PropertiesChanged",
            path_keyword="path",
            bus_name=SOURCE_SERVICE,
        )

    def _prime_missing_source_items(self):
        for path in self.active_paths:
            if path in self.source_items:
                continue
            try:
                proxy = self.bus.get_object(SOURCE_SERVICE, path)
                self.source_items[path] = dbus.Interface(proxy, "com.victronenergy.BusItem")
            except dbus.DBusException as exc:
                logger.warning("DBus path %s is not available: %s", path, exc)

    def _prime_source_paths(self):
        self._prime_missing_source_items()
        self.poll_source()

    def handle_dbus_change(self, changes, path):
        value = changes.get("Value")
        if value is None or path in IGNORED_SOURCE_PATHS:
            return

        if path not in self.active_paths and path not in OWN_METADATA_PATHS:
            self._enable_path(path, value)
            self._prime_missing_source_items()

        if path in self.active_paths:
            self.source_values[path] = value
            self._schedule_flush_updates()

    def _schedule_flush_updates(self):
        if self.flush_updates_source_id is None:
            self.flush_updates_source_id = GLib.timeout_add(50, self.flush_updates)

    def flush_updates(self):
        self.flush_updates_source_id = None

        for path, transform in self.active_paths.items():
            value = self.source_values.get(path)
            if value is None:
                continue

            try:
                new_value = transform(value)
                if self.dbusservice[path] != new_value:
                    self.dbusservice[path] = new_value
            except (TypeError, ValueError, dbus.DBusException) as exc:
                logger.error("Failed to map %s: %s", path, exc)

        return False

    def poll_source(self):
        for path in self.active_paths:
            try:
                source_item = self.source_items.get(path)
                if source_item is None:
                    proxy = self.bus.get_object(SOURCE_SERVICE, path)
                    source_item = dbus.Interface(proxy, "com.victronenergy.BusItem")
                    self.source_items[path] = source_item

                self.source_values[path] = source_item.GetValue()
            except dbus.DBusException as exc:
                self.source_items.pop(path, None)
                logger.debug("Polling failed for %s: %s", path, exc)

        self._schedule_flush_updates()
        return True

    def run(self):
        self.mainloop.run()


if __name__ == "__main__":
    try:
        service = VirtualInvertedBattery()
        service.run()
    except Exception as exc:
        if logger.handlers:
            logger.critical("Service crashed: %s", exc)
        else:
            print(f"Service crashed: {exc}", file=sys.stderr)
        sys.exit(1)
