#!/bin/sh
set -eu

SERVICE_NAME="dbus-deye-battery"
BASE_DIR="/data/dbus-deye-battery"
SCRIPT_PATH="$BASE_DIR/dbus-deye-can-battery.py"
SERVICE_DIR="/data/conf/service/$SERVICE_NAME"
LIVE_SERVICE_DIR="/service/$SERVICE_NAME"
RUN_FILE="$SERVICE_DIR/run"
LOG_DIR="/data/log/$SERVICE_NAME"

mkdir -p "$BASE_DIR" "$SERVICE_DIR" "$LOG_DIR"

if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Missing $SCRIPT_PATH" >&2
    exit 1
fi

cat > "$RUN_FILE" <<'EOF'
#!/bin/sh
export CAN_INTERFACE=${CAN_INTERFACE:-vecan0}
export SERVICE_NAME=${SERVICE_NAME:-com.victronenergy.battery.deye_vecan0}
export DEVICE_INSTANCE=${DEVICE_INSTANCE:-101}
export LOG_FILE=/data/log/dbus-deye-battery/dbus-deye-battery.log
export NR_OF_CELLS_PER_BATTERY=${NR_OF_CELLS_PER_BATTERY:-16}
export BATTERY_CAPACITY_AH=${BATTERY_CAPACITY_AH:-100}
export CURRENT_SIGN_CORRECTION=${CURRENT_SIGN_CORRECTION:--1}
exec python3 /data/dbus-deye-battery/dbus-deye-can-battery.py
EOF

chmod +x "$SCRIPT_PATH" "$RUN_FILE"

rm -f "$LIVE_SERVICE_DIR"
ln -s "$SERVICE_DIR" "$LIVE_SERVICE_DIR"

if command -v svc >/dev/null 2>&1; then
    svc -t "$LIVE_SERVICE_DIR" 2>/dev/null || true
    svc -u "$LIVE_SERVICE_DIR" 2>/dev/null || true
fi
