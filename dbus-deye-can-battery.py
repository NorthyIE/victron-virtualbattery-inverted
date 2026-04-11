#!/usr/bin/env python3

import logging
import os
import select
import signal
import socket
import struct
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Any, Dict

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

VE_LIB_PATH = "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python"
if VE_LIB_PATH not in sys.path:
    sys.path.insert(1, VE_LIB_PATH)

from vedbus import VeDbusService

CAN_INTERFACE = os.environ.get("CAN_INTERFACE", "vecan0")
SERVICE_NAME = os.environ.get("SERVICE_NAME", f"com.victronenergy.battery.deye_{CAN_INTERFACE}")
DEVICE_INSTANCE = int(os.environ.get("DEVICE_INSTANCE", "101"))
PRODUCT_NAME = os.environ.get("PRODUCT_NAME", "Deye CAN Battery")
CUSTOM_NAME = os.environ.get("CUSTOM_NAME", "Deye Battery")
LOG_FILE = os.environ.get("LOG_FILE", "/data/log/dbus-deye-battery/dbus-deye-battery.log")
POLL_INTERVAL_MS = int(os.environ.get("POLL_INTERVAL_MS", "1000"))
ONLINE_TIMEOUT_SECONDS = int(os.environ.get("ONLINE_TIMEOUT_SECONDS", "5"))
NR_OF_CELLS_PER_BATTERY = int(os.environ.get("NR_OF_CELLS_PER_BATTERY", "16"))
BATTERY_CAPACITY_AH = float(os.environ.get("BATTERY_CAPACITY_AH", "100"))
CURRENT_SIGN_CORRECTION = float(os.environ.get("CURRENT_SIGN_CORRECTION", "-1"))
PUBLISH_RAW_STRINGS = os.environ.get("PUBLISH_RAW_STRINGS", "1") == "1"

logger = logging.getLogger("dbus_deye_battery")

CAN_FRAME_FORMAT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FORMAT)


class DeyeCanBattery:
    def __init__(self):
        self._setup_logging()

        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.dbusservice = VeDbusService(SERVICE_NAME, self.bus, register=False)
        self.mainloop = GLib.MainLoop()
        self.socket = None
        self.last_frame_monotonic = 0.0
        self.raw_strings: Dict[int, str] = {}
        self.values: Dict[str, Any] = {}

        self._setup_paths()
        self.dbusservice.register()
        self._open_can_socket()
        self._setup_exit_handlers()

        GLib.io_add_watch(self.socket.fileno(), GLib.IO_IN, self._handle_can_io)
        GLib.timeout_add(POLL_INTERVAL_MS, self._heartbeat)

        logger.info("Started Deye CAN battery service %s on %s", SERVICE_NAME, CAN_INTERFACE)

    def _setup_logging(self):
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        if logger.handlers:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

        handler = RotatingFileHandler(LOG_FILE, maxBytes=100 * 1024, backupCount=1)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False

    def _setup_exit_handlers(self):
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("Service is shutting down on signal %s.", signum)
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
        if self.mainloop.is_running():
            self.mainloop.quit()

    def _setup_paths(self):
        add = self.dbusservice.add_path
        add("/Mgmt/ProcessName", __file__)
        add("/Mgmt/ProcessVersion", "1.0")
        add("/Mgmt/Connection", f"SocketCAN {CAN_INTERFACE}")
        add("/DeviceInstance", DEVICE_INSTANCE)
        add("/ProductId", 0xFFFF)
        add("/ProductName", PRODUCT_NAME)
        add("/Connected", 0)
        add("/CustomName", CUSTOM_NAME)

        default_paths = {
            "/State": 0,
            "/Mode": 1,
            "/Soc": 0.0,
            "/Soh": 0.0,
            "/Capacity": BATTERY_CAPACITY_AH,
            "/InstalledCapacity": BATTERY_CAPACITY_AH,
            "/Dc/0/Voltage": 0.0,
            "/Dc/0/Current": 0.0,
            "/Dc/0/Power": 0.0,
            "/Dc/0/Temperature": 0.0,
            "/Dc/0/MosfetTemperature": 0.0,
            "/Dc/0/MaxCellVoltage": 0.0,
            "/Dc/0/MinCellVoltage": 0.0,
            "/Dc/0/AlarmFlags": 0,
            "/Info/MaxChargeCurrent": 0.0,
            "/Info/MaxDischargeCurrent": 0.0,
            "/Info/MaxChargeVoltage": 0.0,
            "/Info/BatteryLowVoltage": 0.0,
            "/Info/ChargeRequest": 0,
            "/Io/AllowToCharge": 0,
            "/Io/AllowToDischarge": 0,
            "/Io/AllowToBalance": 0,
            "/SystemSwitch": 0,
            "/System/MaxCellVoltage": 0.0,
            "/System/MinCellVoltage": 0.0,
            "/System/MaxCellTemperature": 0.0,
            "/System/MinCellTemperature": 0.0,
            "/System/MaxVoltageCellId": "",
            "/System/MinVoltageCellId": "",
            "/System/NrOfBatteries": 1,
            "/System/NrOfModulesOnline": 0,
            "/System/NrOfModulesOffline": 0,
            "/System/NrOfModulesBlockingCharge": 0,
            "/System/NrOfModulesBlockingDischarge": 0,
            "/System/NrOfCellsPerBattery": NR_OF_CELLS_PER_BATTERY,
            "/History/ChargeCycles": 0,
            "/Alarms/Alarm": 0,
            "/Alarms/LowVoltage": 0,
            "/Alarms/HighVoltage": 0,
            "/Alarms/CellImbalance": 0,
            "/Alarms/LowTemperature": 0,
            "/Alarms/HighTemperature": 0,
            "/FirmwareVersion": "",
            "/Serial": "",
            "/DeviceName": PRODUCT_NAME,
        }

        for path, value in default_paths.items():
            add(path, value)

        self.values.update(default_paths)

    def _open_can_socket(self):
        self.socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.socket.setblocking(False)
        self.socket.bind((CAN_INTERFACE,))

    def _handle_can_io(self, source, condition):
        try:
            while True:
                readable, _, _ = select.select([self.socket], [], [], 0)
                if not readable:
                    break
                frame = self.socket.recv(CAN_FRAME_SIZE)
                if len(frame) < CAN_FRAME_SIZE:
                    break
                can_id, dlc, data = struct.unpack(CAN_FRAME_FORMAT, frame)
                self.last_frame_monotonic = time.monotonic()
                self._decode_frame(can_id & socket.CAN_EFF_MASK, bytes(data[:dlc]))
        except BlockingIOError:
            pass
        except OSError as exc:
            logger.error("CAN read failed: %s", exc)
        return True

    def _heartbeat(self):
        connected = int((time.monotonic() - self.last_frame_monotonic) <= ONLINE_TIMEOUT_SECONDS)
        if self.dbusservice["/Connected"] != connected:
            self.dbusservice["/Connected"] = connected
        return True

    def _set(self, path: str, value: Any):
        self.values[path] = value
        self.dbusservice[path] = value

    @staticmethod
    def _u16le(data: bytes, offset: int, scale: float = 1.0) -> float:
        return int.from_bytes(data[offset:offset + 2], "little", signed=False) * scale

    @staticmethod
    def _i16le(data: bytes, offset: int, scale: float = 1.0) -> float:
        return int.from_bytes(data[offset:offset + 2], "little", signed=True) * scale

    def _decode_frame(self, can_id: int, data: bytes):
        if can_id == 0x351 and len(data) >= 8:
            self._set("/Info/MaxChargeVoltage", self._u16le(data, 0, 0.1))
            self._set("/Info/MaxChargeCurrent", self._u16le(data, 2, 0.1))
            self._set("/Info/MaxDischargeCurrent", self._u16le(data, 4, 0.1))
            self._set("/Info/BatteryLowVoltage", self._u16le(data, 6, 0.1))

        elif can_id == 0x355 and len(data) >= 2:
            self._set("/Soc", float(data[0]))
            self._set("/Soh", float(data[1]))

        elif can_id == 0x356 and len(data) >= 6:
            voltage = self._u16le(data, 0, 0.01)
            current = self._i16le(data, 2, 0.1) * CURRENT_SIGN_CORRECTION
            temperature = self._u16le(data, 4, 0.1)
            self._set("/Dc/0/Voltage", voltage)
            self._set("/Dc/0/Current", current)
            self._set("/Dc/0/Power", round(voltage * current, 1))
            self._set("/Dc/0/Temperature", temperature)

        elif can_id == 0x359 and len(data) >= 8:
            raw_alarm_flags = int.from_bytes(data[:8], "little", signed=False)
            self._set("/Dc/0/AlarmFlags", raw_alarm_flags)
            generic_alarm = 2 if raw_alarm_flags else 0
            self._set("/Alarms/Alarm", generic_alarm)

        elif can_id == 0x35C and len(data) >= 1:
            allow_charge = 1 if data[0] & 0x80 else 0
            allow_discharge = 1 if data[0] & 0x40 else 0
            self._set("/Io/AllowToCharge", allow_charge)
            self._set("/Io/AllowToDischarge", allow_discharge)
            self._set("/SystemSwitch", 1 if (allow_charge or allow_discharge) else 0)
            self._set("/Info/ChargeRequest", 0 if allow_discharge else 1)

        elif can_id == 0x361 and len(data) >= 8:
            max_cell = self._u16le(data, 0, 0.001)
            min_cell = self._u16le(data, 2, 0.001)
            max_temp = self._u16le(data, 4, 0.1)
            min_temp = self._u16le(data, 6, 0.1)
            self._set("/Dc/0/MaxCellVoltage", max_cell)
            self._set("/Dc/0/MinCellVoltage", min_cell)
            self._set("/System/MaxCellVoltage", max_cell)
            self._set("/System/MinCellVoltage", min_cell)
            self._set("/System/MaxCellTemperature", max_temp)
            self._set("/System/MinCellTemperature", min_temp)
            delta_mv = (max_cell - min_cell) * 1000.0
            self._set("/Alarms/CellImbalance", 1 if delta_mv >= 30.0 else 0)

        elif can_id == 0x364 and len(data) >= 5:
            modules_online = int(data[0])
            modules_blocking_charge = int(data[1])
            modules_blocking_discharge = int(data[2])
            total_modules = int(data[4]) if data[4] else max(modules_online, 1)
            modules_offline = max(total_modules - modules_online, 0)
            self._set("/System/NrOfBatteries", total_modules)
            self._set("/System/NrOfModulesOnline", modules_online)
            self._set("/System/NrOfModulesOffline", modules_offline)
            self._set("/System/NrOfModulesBlockingCharge", modules_blocking_charge)
            self._set("/System/NrOfModulesBlockingDischarge", modules_blocking_discharge)

        elif can_id == 0x371 and len(data) >= 4:
            self._set("/Info/MaxChargeCurrent", self._u16le(data, 0, 0.1))
            self._set("/Info/MaxDischargeCurrent", self._u16le(data, 2, 0.1))

        elif can_id == 0x400 and len(data) >= 4:
            state = int(data[0])
            cycles = int.from_bytes(data[2:4], "little", signed=False)
            self._set("/State", state)
            self._set("/History/ChargeCycles", cycles)

        elif can_id == 0x250 and len(data) >= 8:
            self._set("/Dc/0/MosfetTemperature", self._u16le(data, 0, 0.1))
            self._set("/Info/MaxChargeCurrent", self._u16le(data, 4, 1.0))
            self._set("/Info/MaxDischargeCurrent", self._u16le(data, 6, 1.0))

        elif can_id == 0x500 and len(data) >= 8 and PUBLISH_RAW_STRINGS:
            self.raw_strings[0x500] = data.decode("ascii", errors="ignore").strip("\x00")
            self._publish_identity_strings()

        elif can_id == 0x35E and len(data) >= 8 and PUBLISH_RAW_STRINGS:
            self.raw_strings[0x35E] = data.decode("ascii", errors="ignore").strip("\x00")
            self._publish_identity_strings()

        elif can_id == 0x600 and len(data) >= 8 and PUBLISH_RAW_STRINGS:
            self.raw_strings[0x600] = data.decode("ascii", errors="ignore").strip("\x00")
            self._publish_identity_strings()

        elif can_id == 0x650 and len(data) >= 8 and PUBLISH_RAW_STRINGS:
            self.raw_strings[0x650] = data.decode("ascii", errors="ignore").strip("\x00")
            self._publish_identity_strings()

    def _publish_identity_strings(self):
        firmware = self.raw_strings.get(0x500, "")
        serial = "".join(filter(None, [self.raw_strings.get(0x600, ""), self.raw_strings.get(0x650, "")]))
        if firmware:
            self._set("/FirmwareVersion", firmware)
        if serial:
            self._set("/Serial", serial)

    def run(self):
        self.mainloop.run()


if __name__ == "__main__":
    try:
        service = DeyeCanBattery()
        service.run()
    except Exception as exc:
        if logger.handlers:
            logger.critical("Service crashed: %s", exc)
        else:
            print(f"Service crashed: {exc}", file=sys.stderr)
        sys.exit(1)
