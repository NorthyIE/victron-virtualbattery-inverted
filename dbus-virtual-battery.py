#!/usr/bin/env python3
import logging
import os
import signal
import sys
import xml.etree.ElementTree as ET
from logging.handlers import RotatingFileHandler
from typing import Dict, Set, Optional, Any
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
SOURCE_SERVICE = os.environ.get("SOURCE_SERVICE", "com.victronenergy.battery.socketcan_vecan0")
VIRTUAL_NAME = os.environ.get("VIRTUAL_NAME", "com.victronenergy.battery.inverted_vecan0")
DEVICE_INSTANCE = int(os.environ.get("DEVICE_INSTANCE", "100"))
LOG_FILE = os.environ.get("LOG_FILE", "/data/log/dbus-virtual-battery/dbus-virtual-battery.log")
POLL_INTERVAL_MS = int(os.environ.get("POLL_INTERVAL_MS", "2000"))
POLL_RETRY_MAX_ATTEMPTS = int(os.environ.get("POLL_RETRY_MAX_ATTEMPTS", "3"))
_invert_str = os.environ.get("INVERT_PATHS", "/Dc/0/Current,/Dc/0/Power")
_passthrough_str = os.environ.get("PASSTHROUGH_PATHS", "/Soc,/Dc/0/Voltage,/Dc/0/Temperature,/State")
INVERT_PATHS: Set[str] = {p.strip() for p in _invert_str.split(',') if p.strip()} if _invert_str else set()
PASSTHROUGH_PATHS: Set[str] = {p.strip() for p in _passthrough_str.split(',') if p.strip()} if _passthrough_str else set()
AUTO_DISCOVER_PATHS = os.environ.get("AUTO_DISCOVER_PATHS", "true").lower() == "true"
SKIP_PATTERNS = {"/Mgmt", "/ProductId", "/ProductName", "/Connected", "/CustomName", "/DeviceInstance"}
VE_LIB_PATH = "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"
if VE_LIB_PATH not in sys.path:
    sys.path.insert(1, VE_LIB_PATH)
from vedbus import VeDbusService
logger = logging.getLogger("dbus_virtual_battery")
class DBusPathDiscovery:
    @staticmethod
    def discover_all_paths(bus: dbus.SystemBus, service_name: str) -> Set[str]:
        paths = set()
        try:
            logger.info("Introspecting %s for available paths...", service_name)
            obj = bus.get_object(service_name, "/")
            introspect_iface = dbus.Interface(obj, "org.freedesktop.DBus.Introspectable")
            xml_data = introspect_iface.Introspect()
            paths = DBusPathDiscovery._parse_introspection_xml(xml_data)
            logger.info("Discovered %d paths from %s", len(paths), service_name)
            for path in sorted(paths):
                logger.debug("  Discovered path: %s", path)
            return paths
        except Exception as exc:
            logger.error("Introspection failed: %s", exc)
            return set()
    @staticmethod
    def _parse_introspection_xml(xml_data: str) -> Set[str]:
        paths = set()
        try:
            root = ET.fromstring(xml_data)
            for node in root.findall("node"):
                path = node.get("name")
                if path and not any(skip in path for skip in SKIP_PATTERNS):
                    paths.add(path)
        except ET.ParseError as exc:
            logger.warning("Failed to parse introspection XML: %s", exc)
        return paths
class PathTransformer:
    @staticmethod
    def get_transformation_function(path: str) -> Optional[callable]:
        if path in INVERT_PATHS:
            return lambda value: float(value) * -1
        else:
            return lambda value: value
    @staticmethod
    def transform_value(path: str, value: Any) -> Optional[Any]:
        try:
            transform = PathTransformer.get_transformation_function(path)
            return transform(value) if transform else None
        except (TypeError, ValueError) as exc:
            logger.error("Transform failed for %s=%s: %s", path, value, exc)
            return None
class VirtualInvertedBattery:
    def __init__(self):
        self.setup_logging()
        logger.info("="*70)
        logger.info("Victron Virtual Battery Inverted v3.0 - Full Passthrough")
        logger.info("="*70)
        logger.info("Source: %s | Virtual: %s | Device: %d", SOURCE_SERVICE, VIRTUAL_NAME, DEVICE_INSTANCE)
        logger.info("Auto-discovery: %s", AUTO_DISCOVER_PATHS)
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.dbusservice = VeDbusService(VIRTUAL_NAME, self.bus, register=False)
        self.mainloop = GLib.MainLoop()
        self.discovered_paths: Set[str] = set()
        self.source_items: Dict[str, dbus.Interface] = {}
        self.source_values: Dict[str, Any] = {}
        self.poll_retry_count: Dict[str, int] = {}
        self.flush_updates_source_id: Optional[int] = None
        self._verify_source_service_exists()
        self._discover_and_register_all_paths()
        self._setup_management_paths()
        self.dbusservice.register()
        self._setup_signal_receiver()
        self._prime_source_paths()
        self._setup_exit_handlers()
        GLib.timeout_add(POLL_INTERVAL_MS, self.poll_source)
        logger.info("Started with %d paths", len(self.discovered_paths))
    def setup_logging(self):
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        if logger.handlers:
            for h in logger.handlers[:]:
                h.close()
                logger.removeHandler(h)
        h = RotatingFileHandler(LOG_FILE, maxBytes=50*1024, backupCount=1)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.setLevel(logging.DEBUG)
        logger.addHandler(h)
        logger.propagate = False
    def _verify_source_service_exists(self):
        try:
            self.bus.get_object(SOURCE_SERVICE, "/")
            logger.info("✓ Source service available")
        except Exception as exc:
            logger.error("✗ Source service not found: %s", exc)
            raise
    def _discover_and_register_all_paths(self):
        paths = INVERT_PATHS | PASSTHROUGH_PATHS
        if AUTO_DISCOVER_PATHS:
            paths |= DBusPathDiscovery.discover_all_paths(self.bus, SOURCE_SERVICE)
        self.discovered_paths = paths
        for path in sorted(paths):
            try:
                self.dbusservice.add_path(path, 0)
            except Exception as exc:
                logger.warning("Failed to register %s: %s", path, exc)
    def _setup_management_paths(self):
        self.dbusservice.add_path("/Mgmt/ProcessVersion", "3.0")
        self.dbusservice.add_path("/DeviceInstance", DEVICE_INSTANCE)
        self.dbusservice.add_path("/ProductId", 0xFFFF)
        self.dbusservice.add_path("/ProductName", "Virtual Inverted Battery")
        self.dbusservice.add_path("/Connected", 1)
    def _setup_signal_receiver(self):
        self.bus.add_signal_receiver(
            self.handle_dbus_change,
            dbus_interface="com.victronenergy.BusItem",
            signal_name="PropertiesChanged",
            path_keyword="path",
            bus_name=SOURCE_SERVICE,
        )
    def _prime_source_paths(self):
        for path in self.discovered_paths:
            try:
                proxy = self.bus.get_object(SOURCE_SERVICE, path)
                self.source_items[path] = dbus.Interface(proxy, "com.victronenergy.BusItem")
                self.poll_retry_count[path] = 0
            except:
                pass
        self.poll_source()
    def handle_dbus_change(self, changes, path):
        if path in self.discovered_paths:
            self.source_values[path] = changes.get("Value")
            self._schedule_flush_updates()
    def _schedule_flush_updates(self):
        if self.flush_updates_source_id is None:
            self.flush_updates_source_id = GLib.timeout_add(50, self.flush_updates)
    def flush_updates(self):
        self.flush_updates_source_id = None
        for path in self.discovered_paths:
            if path in self.source_values:
                val = PathTransformer.transform_value(path, self.source_values[path])
                if val is not None:
                    try:
                        self.dbusservice[path] = val
                    except:
                        pass
        return False
    def poll_source(self) -> bool:
        for path in self.discovered_paths:
            try:
                if path not in self.source_items:
                    self.source_items[path] = dbus.Interface(
                        self.bus.get_object(SOURCE_SERVICE, path), "com.victronenergy.BusItem"
                    )
                self.source_values[path] = self.source_items[path].GetValue()
                self.poll_retry_count[path] = 0
            except Exception as exc:
                self.poll_retry_count[path] = self.poll_retry_count.get(path, 0) + 1
                if self.poll_retry_count[path] >= POLL_RETRY_MAX_ATTEMPTS:
                    self.source_items.pop(path, None)
        self._schedule_flush_updates()
        return True
    def run(self):
        self.mainloop.run()
    def _setup_exit_handlers(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)
    def _handle_exit(self, signum, frame):
        logger.info("Shutdown signal %d", signum)
        if self.mainloop.is_running():
            self.mainloop.quit()
if __name__ == "__main__":
    try:
        service = VirtualInvertedBattery()
        service.run()
    except Exception as exc:
        try:
            logger.critical("Crashed: %s", exc)
        except:
            print(f"Crashed: {exc}", file=sys.stderr)
        sys.exit(1)