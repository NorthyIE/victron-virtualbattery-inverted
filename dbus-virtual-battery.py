#!/usr/bin/env python3

import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Callable, Dict, Optional

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

SOURCE_SERVICE = os.environ.get("SOURCE_SERVICE", "com.victronenergy.battery.socketcan_vecan0")
VIRTUAL_NAME = os.environ.get("VIRTUAL_NAME", "com.victronenergy.battery.inverted_vecan0")
DEVICE_INSTANCE = int(os.environ.get("DEVICE_INSTANCE", "100"))
LOG_FILE = os.environ.get("LOG_FILE", "/data/log/dbus-virtual-battery/dbus-virtual-battery.log")
POLL_INTERVAL_MS = int(os.environ.get("POLL_INTERVAL_MS", "2000"))

VE_LIB_PATH = "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"
if VE_LIB_PATH not in sys.path:
    sys.path.insert(1, VE_LIB_PATH)

from vedbus import VeDbusService

logger = logging.getLogger("dbus_virtual_battery")


def identity(value: Any) -> Any:
    return value


def invert_signed_numeric(value: Any) -> float:
    return float(value) * -1


CORE_DATA_PATHS: Dict[str, Callable[[Any], Any]] = {
    "/Dc/0/Voltage": identity,
    "/Dc/0/Current": invert_signed_numeric,
    "/Dc/0/Power": invert_signed_numeric,
    "/Soc": identity,
    "/Dc/0/Temperature": identity,
}

OPTIONAL_DATA_PATHS: Dict[str, Callable[[Any], Any]] = {
    # Battery state and identity
    "/State": identity,
    "/Mode": identity,
    "/DeviceName": identity,
    "/FirmwareVersion": identity,
    "/HardwareVersion": identity,
    "/Serial": identity,

    # Standard Victron BMS control / DVCC
    "/Info/MaxChargeCurrent": identity,
    "/Info/MaxDischargeCurrent": identity,
    "/Info/MaxChargeVoltage": identity,
    "/Info/BatteryLowVoltage": identity,
    "/Info/ChargeRequest": identity,
    "/Bms/AllowToCharge": identity,
    "/Bms/AllowToDischarge": identity,
    "/Bms/BmsExpected": identity,
    "/Bms/Error": identity,
    "/Bms/Charge/AllowedA": identity,
    "/Bms/Discharge/AllowedA": identity,

    # DC measurements and cell summary
    "/Dc/0/Temperature": identity,
    "/Dc/0/MosfetTemperature": identity,
    "/Dc/0/MaxCellVoltage": identity,
    "/Dc/0/MinCellVoltage": identity,
    "/Dc/0/MidVoltage": identity,
    "/Dc/0/MidVoltageDeviation": identity,
    "/Dc/0/AlarmFlags": identity,

    # Capacity / energy / runtime
    "/Capacity": identity,
    "/InstalledCapacity": identity,
    "/ConsumedAmphours": identity,
    "/TimeToGo": identity,

    # System / module / pack detail
    "/System/MinCellTemperature": identity,
    "/System/MaxCellTemperature": identity,
    "/System/MinVoltageCellId": identity,
    "/System/MaxVoltageCellId": identity,
    "/System/MinTemperatureCellId": identity,
    "/System/MaxTemperatureCellId": identity,
    "/System/NrOfCellsPerBattery": identity,
    "/System/NrOfModulesOnline": identity,
    "/System/NrOfModulesOffline": identity,
    "/System/NrOfModulesBlockingCharge": identity,
    "/System/NrOfModulesBlockingDischarge": identity,
    "/System/MostDischargedCell": identity,
    "/System/MostChargedCell": identity,

    # IO / balancing
    "/Io/AllowToCharge": identity,
    "/Io/AllowToDischarge": identity,
    "/Io/AllowToBalance": identity,
    "/Balancing": identity,

    # Alarms
    "/Alarms/Alarm": identity,
    "/Alarms/LowVoltage": identity,
    "/Alarms/HighVoltage": identity,
    "/Alarms/LowSoc": identity,
    "/Alarms/HighChargeCurrent": identity,
    "/Alarms/HighDischargeCurrent": identity,
    "/Alarms/HighCurrent": identity,
    "/Alarms/CellImbalance": identity,
    "/Alarms/InternalFailure": identity,
    "/Alarms/LowTemperature": identity,
    "/Alarms/HighTemperature": identity,
    "/Alarms/LowChargeTemperature": identity,
    "/Alarms/HighChargeTemperature": identity,
    "/Alarms/LowCellVoltage": identity,
    "/Alarms/HighCellVoltage": identity,
    "/Alarms/HighInternalTemperature": identity,
    "/Alarms/BmsCable": identity,
    "/Alarms/Contactor": identity,
    "/Alarms/FuseBlown": identity,

    # Settings / feature flags
    "/Settings/HasTemperature": identity,
    "/Settings/HasMidVoltage": identity,
    "/Settings/HasStarterVoltage": identity,

    # History
    "/History/ChargeCycles": identity,
    "/History/DeepestDischarge": identity,
    "/History/LastDischarge": identity,
    "/History/AverageDischarge": identity,
    "/History/FullDischarges": identity,
    "/History/TotalAhDrawn": identity,
    "/History/MinimumVoltage": identity,
    "/History/MaximumVoltage": identity,
    "/History/TimeSinceLastFullCharge": identity,
    "/History/AutomaticSyncs": identity,
    "/History/LowVoltageAlarms": identity,
    "/History/HighVoltageAlarms": identity,
    "/History/LowStarterVoltageAlarms": identity,
    "/History/HighStarterVoltageAlarms": identity,
}

# Common dynamic per-cell path layouts used by Victron battery drivers and aggregators.
DYNAMIC_PATH_PATTERNS = [
    "/Voltages/Cell{index}",
    "/Balances/Cell{index}",
    "/Cell/{index}/Volts",
    "/Cell/{index}/Balancing",
]


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
        self.dbusservice.register()
        self._setup_signal_receiver()
        self._prime_source_paths()
        self._setup_exit_handlers()

        GLib.timeout_add(POLL_INTERVAL_MS, self.poll_source)
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

    def _probe_path(self, path: str) -> Optional[Any]:
        try:
            proxy = self.bus.get_object(SOURCE_SERVICE, path)
            iface = dbus.Interface(proxy, "com.victronenergy.BusItem")
            return iface.GetValue()
        except dbus.DBusException:
            return None

    def _enable_path(self, path: str, transform: Callable[[Any], Any], default_value: Any = 0):
        if path in self.active_paths:
            return

        self.active_paths[path] = transform
        self.dbusservice.add_path(path, default_value)
        logger.info("Mirroring path: %s", path)

    def _setup_service_paths(self):
        self.dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self.dbusservice.add_path("/Mgmt/ProcessVersion", "2.1")
        self.dbusservice.add_path("/Mgmt/Connection", f"Virtual Battery via {SOURCE_SERVICE}")
        self.dbusservice.add_path("/DeviceInstance", DEVICE_INSTANCE)
        self.dbusservice.add_path("/ProductId", 0xFFFF)
        self.dbusservice.add_path("/ProductName", "Virtual Inverted Battery")
        self.dbusservice.add_path("/Connected", 1)
        self.dbusservice.add_path("/CustomName", "Inverted Battery")

        for path, transform in CORE_DATA_PATHS.items():
            self._enable_path(path, transform)

        for path, transform in OPTIONAL_DATA_PATHS.items():
            if self._probe_path(path) is not None:
                self._enable_path(path, transform)

        for pattern in DYNAMIC_PATH_PATTERNS:
            for index in range(1, 33):
                path = pattern.format(index=index)
                if self._probe_path(path) is not None:
                    self._enable_path(path, identity)

    def _setup_signal_receiver(self):
        self.bus.add_signal_receiver(
            self.handle_dbus_change,
            dbus_interface="com.victronenergy.BusItem",
            signal_name="PropertiesChanged",
            path_keyword="path",
            bus_name=SOURCE_SERVICE,
        )

    def _prime_source_paths(self):
        for path in self.active_paths:
            try:
                proxy = self.bus.get_object(SOURCE_SERVICE, path)
                self.source_items[path] = dbus.Interface(proxy, "com.victronenergy.BusItem")
            except dbus.DBusException as exc:
                logger.warning("DBus path %s is not available: %s", path, exc)

        self.poll_source()

    def handle_dbus_change(self, changes, path):
        value = changes.get("Value")
        if value is not None and path in self.active_paths:
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
