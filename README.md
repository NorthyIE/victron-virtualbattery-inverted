# Victron DBus Virtual Inverted Battery

Ich habe das hier für Victron Venus OS gebaut, weil ein Deye-BMS in meinem Setup den Batteriestrom mit dem falschen Vorzeichen gemeldet hat. Dadurch waren die Anzeigen im GX und im VRM ziemlich irreführend.

Dieses Projekt erstellt einen kleinen virtuellen Batterie-Dienst auf dem DBus, der die echte Batterie spiegelt, aber die Stromrichtung korrigiert. Entstanden ist es für Deye, aber es kann möglicherweise auch bei anderen Batterien oder BMS helfen, wenn dort derselbe Fehler auftaucht.

## Warum 
Einige BMS (in meinem Fall von Deye) scheinen auf Victron-Systemen die Stromrichtung falsch zu melden. Dann steht im System zum Beispiel `Entladen`, obwohl die Batterie gerade geladen wird, oder genau andersherum.

In der Victron Community gibt es dazu passende oder sehr ähnliche Berichte:

- [Issue integrating Deye RW-F16 battery with Victron MultiPlus-II GX](https://community.victronenergy.com/t/issue-integrating-deye-rw-f16-battery-with-victron-multiplus-ii-gx/38218)
- [Battery name correct on older Cerbo units, incorrect on new Cerbo units](https://community.victronenergy.com/t/battery-name-correct-on-older-cerbo-units-incorrect-on-new-cerbo-units/31622/15)

## Was das Skript macht
Das Skript legt einen separaten virtuellen Batterie-Dienst auf dem DBus an:

- Spannung wird gespiegelt
- SoC wird gespiegelt
- Strom wird invertiert
- Leistung wird aus Spannung und Strom neu berechnet
- Temperatur wird übernommen, wenn die Quellbatterie sie bereitstellt

Danach kannst du im GX einfach die virtuelle Batterie als Batteriewächter auswählen.

## Installation auf dem Cerbo GX

### 1. SSH aktivieren
- Auf dem Cerbo GX zu `Settings -> General -> Access Level` gehen
- `User and Installer` mit dem Passwort `zzz` setzen
- Unter `Firmware -> Online Updates` ein Superuser-Passwort vergeben
- `SSH on LAN` aktivieren

## Den richtigen Batterie-Dienst prüfen
Verbinde dich per SSH mit dem Cerbo GX und starte:

```sh
dbus-spy
```

Suche dort nach dem Batterie-Dienst, der mit `com.victronenergy.battery` beginnt.

Falls dein Dienst nicht `com.victronenergy.battery.socketcan_vecan0` heißt, passe nach dem Download in der Python-Datei `SOURCE_SERVICE` an.

### 2. Python-Dienst herunterladen
```sh
mkdir -p /data/dbus-virtual-battery
wget -O /data/dbus-virtual-battery/dbus-virtual-battery.py https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/dbus-virtual-battery.py
chmod +x /data/dbus-virtual-battery/dbus-virtual-battery.py
```

Falls nötig, den Dienstnamen anzupassen:

```sh
nano /data/dbus-virtual-battery/dbus-virtual-battery.py
```

### 3. `run`-Datei herunterladen
```sh
mkdir -p /data/conf/service/dbus-virtual-battery
wget -O /data/conf/service/dbus-virtual-battery/run https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/run
chmod +x /data/conf/service/dbus-virtual-battery/run
ln -s /data/conf/service/dbus-virtual-battery /service/dbus-virtual-battery
```

## Neustart und Fehlersuche
Dienst neu starten:

```sh
svc -t /service/dbus-virtual-battery
```

Dienst manuell starten:

```sh
svc -u /service/dbus-virtual-battery
```

Status prüfen:

```sh
svstat /service/dbus-virtual-battery
```

Logs live ansehen:

```sh
tail -f /data/log/dbus-virtual-battery.log
```

Falls die Werte noch nicht stimmen:

1. Mit `dbus-spy` den echten Batterie-Dienstnamen noch einmal prüfen
2. Sicherstellen, dass die Quellbatterie `/Dc/0/Temperature` wirklich bereitstellt, wenn Temperatur erwartet wird
3. Prüfen, ob der virtuelle Dienst als `com.victronenergy.battery.inverted_vecan0` erscheint
4. Den Dienst nach jeder Skript-Änderung neu starten

## Einrichtung im GX
1. Die GX Remote Console öffnen
2. Zu `Settings -> System Setup` gehen
3. `Inverted Battery` als Batteriewächter auswählen
4. Mit `dbus-spy` prüfen, ob Werte und Vorzeichen jetzt plausibel sind

## Wenn du das Projekt unterstützen möchtest
Falls dir das Projekt geholfen hat und du mir einen Kaffee ausgeben möchtest:

- [paypal.me/northy](https://paypal.me/northy) - Das ist natürlich komplett freiwillig.

Das ist kein offizielles Produkt von Victron Energy. Nutzung auf eigene Gefahr.
