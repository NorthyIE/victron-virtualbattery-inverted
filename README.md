# Victron Virtual Battery Inverted

[Deutsche Version](README.de.md)

I originally built this for Victron Venus OS because a BMS in my setup was reporting battery current with the wrong sign. In my case it was a Deye BMS. That made the battery state shown in GX and VRM pretty misleading.

The project now consists of two related parts:

1. **A Deye CAN battery source driver** that reads Deye battery frames from SocketCAN and publishes them as a Victron battery service on DBus.
2. **A virtual battery mirror** that copies a real battery service on DBus and inverts current and power, while mirroring almost all other available battery paths automatically.

You can use either one on its own, or chain them together.

![GX screenshot showing the original battery and the corrected inverted virtual battery](screenshots/settings-system-batteries.png)

## What this repo can do now

### Option A: Publish a Deye battery directly from CAN
The Deye source driver listens on SocketCAN and publishes a Victron battery DBus service for a Deye battery.

It currently decodes the summary frames that were visible in my Deye logs, including:

- battery voltage
- battery current
- battery power
- SoC
- SoH
- battery temperature
- MOS temperature
- max charge voltage
- max charge current
- max discharge current
- battery low-voltage limit
- charge/discharge allow flags
- min/max cell voltage
- min/max temperature
- module counts
- cycle count
- raw alarm flags
- selected firmware / serial string fragments when present

The installed battery capacity is read from the environment variable `BATTERY_CAPACITY_AH`. For a Deye RW-F16 the correct value is typically **314 Ah**.

The available capacity shown on GX is calculated from:

- installed capacity
- current SoC

### Option B: Mirror an existing battery service and invert the sign
This is the original use case.

The virtual battery service mirrors a real battery service and:

- mirrors voltage
- mirrors SoC
- inverts current
- inverts power
- mirrors almost all other source battery paths automatically via DBus discovery

This is useful when your battery is already visible on DBus, but the current direction is wrong.

### Option C: Use both together
This is the best choice if:

- your Deye data is not yet exposed on DBus, and
- the Deye current sign is also wrong for Victron.

In that setup:

- `dbus-deye-can-battery.py` publishes `com.victronenergy.battery.deye_vecan0`
- `dbus-virtual-battery.py` mirrors that service and inverts the sign into `com.victronenergy.battery.inverted_vecan0`

Then you select the **Inverted Battery** in GX.

## Which setup should you use?

Use **only the Deye source driver** if you want a native Deye battery service on DBus and the sign already looks correct in your environment.

Use **only the virtual battery** if your real battery already appears in `dbus-spy` and you only need to fix the sign.

Use **both together** if you are integrating a Deye battery from CAN and still need the current sign corrected.

## Check the battery service name first
Before installing anything, connect to your Cerbo GX over SSH and run:

```sh
dbus-spy
```

Look for battery services that start with `com.victronenergy.battery`.

Common examples:

- `com.victronenergy.battery.socketcan_vecan0`
- `com.victronenergy.battery.deye_vecan0`
- `com.victronenergy.battery.inverted_vecan0`

## Installation on Cerbo GX

### 1. Enable SSH
- On the Cerbo GX, go to `Settings -> General -> Access Level`
- Set it to `User and Installer` using password `zzz`
- Under `Firmware -> Online Updates`, set a superuser password
- Enable `SSH on LAN`

### 2. Download the files

```sh
mkdir -p /data/dbus-virtual-battery
wget -O /data/dbus-virtual-battery/dbus-virtual-battery.py https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/dbus-virtual-battery.py
wget -O /data/dbus-virtual-battery/dbus-deye-can-battery.py https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/dbus-deye-can-battery.py
wget -O /data/dbus-virtual-battery/install.sh https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/install.sh
chmod +x /data/dbus-virtual-battery/dbus-virtual-battery.py
chmod +x /data/dbus-virtual-battery/dbus-deye-can-battery.py
chmod +x /data/dbus-virtual-battery/install.sh
```

### 3. Pick your mode

#### Deye CAN source only
This creates a Deye battery service directly from CAN without creating the inverted mirror.

```sh
INSTALL_DEYE_SOURCE=1 INSTALL_VIRTUAL_BATTERY=0 BATTERY_CAPACITY_AH=314 /data/dbus-virtual-battery/install.sh
```

Optional environment overrides:

```sh
CAN_INTERFACE=vecan0
SERVICE_NAME=com.victronenergy.battery.deye_vecan0
DEVICE_INSTANCE=101
BATTERY_CAPACITY_AH=314
CURRENT_SIGN_CORRECTION=-1
```

#### Existing DBus battery only
This keeps the original behavior.

```sh
SOURCE_SERVICE=com.victronenergy.battery.socketcan_vecan0 /data/dbus-virtual-battery/install.sh
```

If your existing battery service has a different name, change `SOURCE_SERVICE` accordingly.

#### Deye CAN source plus inverted virtual battery
This installs both services and makes the virtual battery read from the Deye source service.

```sh
INSTALL_DEYE_SOURCE=1 \
INSTALL_VIRTUAL_BATTERY=1 \
BATTERY_CAPACITY_AH=314 \
SOURCE_SERVICE=com.victronenergy.battery.deye_vecan0 \
/data/dbus-virtual-battery/install.sh
```

This is the recommended mode if you want to decode Deye CAN data and still correct the current sign for GX/VRM.

### 4. Make it survive reboots
On Venus OS, `/service` is rebuilt during boot, so the install script needs to run again after every reboot and firmware update. Add this boot hook:

```sh
grep -qxF "/data/dbus-virtual-battery/install.sh" /data/rc.local || echo "/data/dbus-virtual-battery/install.sh" >> /data/rc.local
chmod +x /data/rc.local
```

If you use custom environment variables, put them in `/data/rc.local` too. Example:

```sh
grep -qxF "INSTALL_DEYE_SOURCE=1 INSTALL_VIRTUAL_BATTERY=1 BATTERY_CAPACITY_AH=314 SOURCE_SERVICE=com.victronenergy.battery.deye_vecan0 /data/dbus-virtual-battery/install.sh" /data/rc.local || echo "INSTALL_DEYE_SOURCE=1 INSTALL_VIRTUAL_BATTERY=1 BATTERY_CAPACITY_AH=314 SOURCE_SERVICE=com.victronenergy.battery.deye_vecan0 /data/dbus-virtual-battery/install.sh" >> /data/rc.local
chmod +x /data/rc.local
```

Also make sure `Settings -> General -> Modification checks -> Modifications enabled` is turned on, otherwise Venus OS will disable `/data/rc.local`.

## What the installer now does
The installer can now create either or both of these services:

- `/service/dbus-deye-battery`
- `/service/dbus-virtual-battery`

It recreates the `run` files in `/data/conf/service/...`, relinks `/service/...`, and restarts the services.

Logs are written to:

- `/data/log/dbus-deye-battery/dbus-deye-battery.log`
- `/data/log/dbus-virtual-battery/dbus-virtual-battery.log`

## Restart and troubleshooting

Restart the Deye source service:

```sh
svc -t /service/dbus-deye-battery
```

Restart the virtual battery service:

```sh
svc -t /service/dbus-virtual-battery
```

Check status:

```sh
svstat /service/dbus-deye-battery
svstat /service/dbus-virtual-battery
```

Watch logs:

```sh
tail -f /data/log/dbus-deye-battery/dbus-deye-battery.log
tail -f /data/log/dbus-virtual-battery/dbus-virtual-battery.log
```

If the values still look wrong:

1. Double-check the real battery service name in `dbus-spy`
2. Confirm that the Deye source service appears as `com.victronenergy.battery.deye_vecan0`
3. Confirm that the virtual service appears as `com.victronenergy.battery.inverted_vecan0`
4. If the current sign is still backwards, try changing `CURRENT_SIGN_CORRECTION` from `-1` to `1`
5. Restart the relevant service after every change

## Important limitations
The Deye source driver currently decodes the **summary / inverter-facing CAN frames** that were available in my logs. It does **not** yet decode the separate full per-cell InterCAN extended frames.

The virtual battery mirrors almost all source battery paths automatically, but it can only mirror data that really exists on the source battery DBus service.

## If you want to support it
If this project was useful and you feel like buying me a coffee, you can do that here:

- [paypal.me/northy](https://paypal.me/northy)

That is completely optional.

This is not an official Victron Energy product. Use it at your own risk.
