# Deye Battery CAN für Victron

[English version](README.md)

Das Projekt begann ursprünglich als kleiner Workaround für Victron Venus OS, weil ein Deye-BMS in meinem Setup den Batteriestrom mit dem falschen Vorzeichen gemeldet hat.

Inzwischen ist daraus eine deutlich breitere **Deye-Batterie-CAN-Integration für Victron** geworden, mit einer optionalen virtuellen Batterieschicht für Fälle, in denen die Stromrichtung zusätzlich korrigiert werden muss.

## Was dieses Projekt heute ist

Das Repository enthält aktuell zwei zusammengehörige Komponenten:

1. **Einen Deye-CAN-Batterie-Quelltreiber**, der Deye-Batteriedaten von SocketCAN liest und als Victron-Batteriedienst auf dem DBus veröffentlicht.
2. **Eine virtuelle Batterie-Spiegelung**, die einen vorhandenen DBus-Batteriedienst spiegelt, das Stromvorzeichen invertiert und fast alle anderen Batteriepfade automatisch übernimmt.

Beide Teile können einzeln oder gemeinsam genutzt werden.

![GX-Screenshot mit Originalbatterie und korrigierter virtueller Batterie](screenshots/settings-system-batteries.png)

## Empfohlene Sicht auf das Projekt

Am besten versteht man dieses Repo heute als:

- **Deye Battery CAN implementation on Victron**

Und zusätzlich als:

- **optionale virtuelle Korrekturschicht**

Das beschreibt den heutigen Funktionsumfang deutlich besser als der alte Projektname.

## Aktueller Stand

### Option A: Deye-Batterie direkt von CAN veröffentlichen
Der Deye-Quelltreiber lauscht auf SocketCAN und veröffentlicht einen Victron-Batteriedienst auf dem DBus.

Aktuell werden die Deye-Summary-Frames dekodiert, die in meinen Logs sichtbar waren, unter anderem:

- Batteriespannung
- Batteriestrom
- Batterieleistung
- SoC
- SoH
- Batterietemperatur
- MOS-Temperatur
- maximale Ladespannung
- maximaler Ladestrom
- maximaler Entladestrom
- Unterspannungsgrenze der Batterie
- Lade-/Entladefreigaben
- minimale / maximale Zellspannung
- minimale / maximale Zelltemperatur
- Modulanzahl
- Zyklenzahl
- rohe Alarmbits
- ausgewählte Firmware-/Serienstring-Fragmente, wenn vorhanden

Die installierte Batteriekapazität wird aus der Umgebungsvariable `BATTERY_CAPACITY_AH` übernommen. Für eine Deye RW-F16 ist der korrekte Wert typischerweise **314 Ah**.

Die im GX angezeigte verfügbare Kapazität wird berechnet aus:

- installierter Kapazität
- aktuellem SoC

### Option B: Vorhandenen Batteriedienst spiegeln und Vorzeichen korrigieren
Das ist weiterhin nützlich, wenn die Batterie bereits auf dem DBus vorhanden ist, aber die Stromrichtung nicht stimmt.

Die virtuelle Batterie:

- übernimmt die Spannung
- übernimmt den SoC
- invertiert den Strom
- berechnet die Leistung aus der gespiegelten Spannung und dem gespiegelten Strom neu
- übernimmt fast alle anderen Batteriepfade automatisch über DBus-Erkennung

### Option C: Beides zusammen nutzen
Das ist die empfohlene Variante, wenn:

- deine Deye-Daten noch nicht auf dem DBus vorhanden sind und
- das Stromvorzeichen für Victron zusätzlich korrigiert werden muss.

In diesem Setup:

- veröffentlicht `dbus-deye-can-battery.py` den Dienst `com.victronenergy.battery.deye_vecan0`
- spiegelt `dbus-virtual-battery.py` diesen Dienst nach `com.victronenergy.battery.inverted_vecan0`

## Welche Variante solltest du nutzen?

Nutze **nur den Deye-Quelltreiber**, wenn du einen nativen Deye-Batteriedienst auf dem DBus willst und das Vorzeichen in deiner Umgebung bereits stimmt.

Nutze **nur die virtuelle Batterie**, wenn deine echte Batterie schon in `dbus-spy` erscheint und du nur das Vorzeichen korrigieren möchtest.

Nutze **beides zusammen**, wenn du eine Deye-Batterie direkt von CAN integrieren willst und zusätzlich eine Vorzeichenkorrektur für GX/VRM brauchst.

## Hinweis zur Benennung des Projekts

Der Repository-Name enthält noch den älteren Begriff `virtualbattery-inverted`, weil das ursprünglich der Projektfokus war.

Inzwischen ist der Funktionsumfang deutlich darüber hinausgewachsen. Langfristig wären passendere Namen zum Beispiel:

- `victron-deye-can-battery`
- `deye-battery-victron`
- `victron-deye-bms`

Bis auf Weiteres bleibt dieses Repository das aktive Zuhause des Projekts, aber die Dokumentation beschreibt jetzt den breiteren Funktionsumfang.

## Den richtigen Batteriedienst prüfen
Bevor du installierst, verbinde dich per SSH mit dem Cerbo GX und starte:

```sh
dbus-spy
```

Suche dort nach Batteriediensten, die mit `com.victronenergy.battery` beginnen.

Typische Beispiele:

- `com.victronenergy.battery.socketcan_vecan0`
- `com.victronenergy.battery.deye_vecan0`
- `com.victronenergy.battery.inverted_vecan0`

## Installation auf dem Cerbo GX

### 1. SSH aktivieren
- Auf dem Cerbo GX zu `Settings -> General -> Access Level` gehen
- `User and Installer` mit dem Passwort `zzz` setzen
- Unter `Firmware -> Online Updates` ein Superuser-Passwort vergeben
- `SSH on LAN` aktivieren

### 2. Dateien herunterladen

```sh
mkdir -p /data/dbus-virtual-battery
wget -O /data/dbus-virtual-battery/dbus-virtual-battery.py https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/dbus-virtual-battery.py
wget -O /data/dbus-virtual-battery/dbus-deye-can-battery.py https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/dbus-deye-can-battery.py
wget -O /data/dbus-virtual-battery/install.sh https://raw.githubusercontent.com/NorthyIE/victron-virtualbattery-inverted/main/install.sh
chmod +x /data/dbus-virtual-battery/dbus-virtual-battery.py
chmod +x /data/dbus-virtual-battery/dbus-deye-can-battery.py
chmod +x /data/dbus-virtual-battery/install.sh
```

### 3. Modus auswählen

#### Nur Deye-CAN-Quelle

```sh
INSTALL_DEYE_SOURCE=1 INSTALL_VIRTUAL_BATTERY=0 BATTERY_CAPACITY_AH=314 /data/dbus-virtual-battery/install.sh
```

Optionale Umgebungsvariablen:

```sh
CAN_INTERFACE=vecan0
SERVICE_NAME=com.victronenergy.battery.deye_vecan0
DEVICE_INSTANCE=101
BATTERY_CAPACITY_AH=314
CURRENT_SIGN_CORRECTION=-1
```

#### Nur vorhandenen DBus-Batteriedienst spiegeln

```sh
SOURCE_SERVICE=com.victronenergy.battery.socketcan_vecan0 /data/dbus-virtual-battery/install.sh
```

Falls dein vorhandener Batteriedienst anders heißt, passe `SOURCE_SERVICE` entsprechend an.

#### Deye-CAN-Quelle plus virtuelle Korrekturschicht

```sh
INSTALL_DEYE_SOURCE=1 \
INSTALL_VIRTUAL_BATTERY=1 \
BATTERY_CAPACITY_AH=314 \
SOURCE_SERVICE=com.victronenergy.battery.deye_vecan0 \
/data/dbus-virtual-battery/install.sh
```

### 4. Reboot-fest machen
Unter Venus OS wird `/service` beim Booten neu aufgebaut, deshalb muss das Installationsskript nach jedem Neustart und Firmware-Update erneut laufen. Füge dafür diesen Boot-Hook hinzu:

```sh
grep -qxF "/data/dbus-virtual-battery/install.sh" /data/rc.local || echo "/data/dbus-virtual-battery/install.sh" >> /data/rc.local
chmod +x /data/rc.local
```

Wenn du eigene Umgebungsvariablen nutzt, schreibe diese ebenfalls in die `/data/rc.local`. Beispiel:

```sh
grep -qxF "INSTALL_DEYE_SOURCE=1 INSTALL_VIRTUAL_BATTERY=1 BATTERY_CAPACITY_AH=314 SOURCE_SERVICE=com.victronenergy.battery.deye_vecan0 /data/dbus-virtual-battery/install.sh" /data/rc.local || echo "INSTALL_DEYE_SOURCE=1 INSTALL_VIRTUAL_BATTERY=1 BATTERY_CAPACITY_AH=314 SOURCE_SERVICE=com.victronenergy.battery.deye_vecan0 /data/dbus-virtual-battery/install.sh" >> /data/rc.local
chmod +x /data/rc.local
```

Außerdem muss unter `Settings -> General -> Modification checks -> Modifications enabled` die Modifikationserlaubnis aktiv sein.

## Was das Installationsskript macht
Das Installationsskript kann einen oder beide dieser Dienste anlegen:

- `/service/dbus-deye-battery`
- `/service/dbus-virtual-battery`

Es erzeugt die `run`-Dateien in `/data/conf/service/...` neu, verlinkt `/service/...` und startet die Dienste neu.

Die Logs liegen hier:

- `/data/log/dbus-deye-battery/dbus-deye-battery.log`
- `/data/log/dbus-virtual-battery/dbus-virtual-battery.log`

## Neustart und Fehlersuche

Deye-Quelltreiber neu starten:

```sh
svc -t /service/dbus-deye-battery
```

Virtuelle Batterie neu starten:

```sh
svc -t /service/dbus-virtual-battery
```

Status prüfen:

```sh
svstat /service/dbus-deye-battery
svstat /service/dbus-virtual-battery
```

Logs live ansehen:

```sh
tail -f /data/log/dbus-deye-battery/dbus-deye-battery.log
tail -f /data/log/dbus-virtual-battery/dbus-virtual-battery.log
```

Falls die Werte noch nicht stimmen:

1. Mit `dbus-spy` den Batteriedienstnamen noch einmal prüfen
2. Kontrollieren, dass der Deye-Quelltreiber als `com.victronenergy.battery.deye_vecan0` erscheint
3. Kontrollieren, dass die virtuelle Batterie als `com.victronenergy.battery.inverted_vecan0` erscheint
4. Falls das Stromvorzeichen noch falsch ist, `CURRENT_SIGN_CORRECTION` von `-1` auf `1` ändern
5. Nach jeder Änderung den betreffenden Dienst neu starten

## Wichtige Einschränkungen
Der Deye-Quelltreiber dekodiert aktuell die **Summary- / inverterseitigen CAN-Frames**, die in meinen Logs sichtbar waren. Die separaten vollständigen InterCAN-Extended-Frames mit allen Einzelzellwerten werden noch nicht dekodiert.

Die virtuelle Batterie übernimmt fast alle Quellpfade automatisch, kann aber natürlich nur Daten spiegeln, die auf dem Quell-Batteriedienst auch wirklich existieren.

## Wenn du das Projekt unterstützen möchtest
Falls dir das Projekt geholfen hat und du mir einen Kaffee ausgeben möchtest:

- [paypal.me/northy](https://paypal.me/northy)

Das ist natürlich komplett freiwillig.

Das ist kein offizielles Produkt von Victron Energy. Nutzung auf eigene Gefahr.
