# Victron Virtual Battery Inverted

[English primary README](README.md) | [Deutsche Version](README.de.md)

I built this for Victron Venus OS because a BMS in my setup was reporting battery current with the wrong sign. In my case it was a Deye BMS. That made the battery state shown in GX and VRM pretty misleading.

This project creates a small virtual battery service on DBus that mirrors the real battery, but corrects the current direction. It started as a fix for a specific Deye issue, but it may also help with other batteries or BMS integrations that show the same problem.

![GX screenshot showing the original battery and the corrected inverted virtual battery](screenshots/settings-system-batteries.png)

## Why I made this
Some BMS integrations appear to report current direction incorrectly on Victron systems. When that happens, the system may show `Discharging` while the battery is actually charging, or the other way around.

These Victron Community threads describe the same or very similar behavior:

- [Issue integrating Deye RW-F16 battery with Victron MultiPlus-II GX](https://community.victronenergy.com/t/issue-integrating-deye-rw-f16-battery-with-victron-multiplus-ii-gx/38218)
- [Battery name correct on older Cerbo units, incorrect on new Cerbo units](https://community.victronenergy.com/t/battery-name-correct-on-older-cerbo-units-incorrect-on-new-cerbo-units/31622/15)

## What the script does
The script creates a separate virtual battery service on DBus:

- Voltage is mirrored
- SoC is mirrored
- Current is inverted
- Power is recalculated from voltage and current
- Temperature is passed through when the source battery provides it

After that, you can simply select the virtual battery as the battery monitor in the GX settings.

## Check the battery service name first
Before installing anything, connect to your Cerbo GX over SSH and run:

```sh
dbus-spy
```

Look for the battery service that starts with `com.victronenergy.battery`.

If your service name is not `com.victronenergy.battery.socketcan_vecan0`, edit the Python file after downloading it and change `SOURCE_SERVICE`.

## Installation on Cerbo GX

### 1. Enable SSH
- On the Cerbo GX, go to `Settings -> General -> Access Level`
- Set it to `User and Installer` using password `zzz`
- Under `Firmware -> Online Updates`, set a superuser password
- Enable `SSH on LAN`

### 2. Download the Python Service
```sh
mkdir -p /data/dbus-virtual-battery
wget -O /data/dbus-virtual-battery/dbus-virtual-battery.py https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/dbus-virtual-battery.py
wget -O /data/dbus-virtual-battery/install.sh https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/install.sh
chmod +x /data/dbus-virtual-battery/dbus-virtual-battery.py
chmod +x /data/dbus-virtual-battery/install.sh
```

If needed, edit the source service name:

```sh
nano /data/dbus-virtual-battery/dbus-virtual-battery.py
```

### 3. Install the service and make it survive reboots
```sh
/data/dbus-virtual-battery/install.sh
```

On Venus OS, `/service` is rebuilt during boot, so the install script needs to run again after every reboot and firmware update. Add this boot hook:

```sh
grep -qxF "/data/dbus-virtual-battery/install.sh" /data/rc.local || echo "/data/dbus-virtual-battery/install.sh" >> /data/rc.local
chmod +x /data/rc.local
```

Also make sure `Settings -> General -> Modification checks -> Modifications enabled` is turned on, otherwise Venus OS will disable `/data/rc.local`.

The install script recreates the `run` file in `/data/conf/service/dbus-virtual-battery`, relinks `/service/dbus-virtual-battery`, and restarts the service.

## Restart and troubleshooting
Restart the service:

```sh
svc -t /service/dbus-virtual-battery
```

Bring it up manually:

```sh
svc -u /service/dbus-virtual-battery
```

Check status:

```sh
svstat /service/dbus-virtual-battery
```

Watch the log:

```sh
tail -f /data/log/dbus-virtual-battery.log
```

If the values still look wrong:

1. Double-check the real battery service name in `dbus-spy`
2. Make sure the source battery actually exposes `/Dc/0/Temperature` if you expect temperature to appear
3. Confirm the virtual service shows up as `com.victronenergy.battery.inverted_vecan0`
4. Restart the service after every change to the script

## Final setup in GX
1. Open the GX Remote Console
2. Go to `Settings -> System Setup`
3. Select `Inverted Battery` as the battery monitor
4. Check in `dbus-spy` that the values and signs now make sense

## If you want to support it
If this project was useful and you feel like buying me a coffee, you can do that here:

- [paypal.me/northy](https://paypal.me/northy)

That is completely optional.

This is not an official Victron Energy product. Use it at your own risk.
