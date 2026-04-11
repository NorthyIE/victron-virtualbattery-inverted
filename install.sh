#!/bin/sh
set -eu

BASE_DIR="/data/dbus-virtual-battery"
VIRTUAL_SERVICE_NAME="dbus-virtual-battery"
DEYE_SERVICE_NAME="dbus-deye-battery"
VIRTUAL_SCRIPT_PATH="$BASE_DIR/dbus-virtual-battery.py"
DEYE_SCRIPT_PATH="$BASE_DIR/dbus-deye-can-battery.py"
VIRTUAL_SERVICE_DIR="/data/conf/service/$VIRTUAL_SERVICE_NAME"
DEYE_SERVICE_DIR="/data/conf/service/$DEYE_SERVICE_NAME"
VIRTUAL_LIVE_SERVICE_DIR="/service/$VIRTUAL_SERVICE_NAME"
DEYE_LIVE_SERVICE_DIR="/service/$DEYE_SERVICE_NAME"
VIRTUAL_LOG_DIR="/data/log/$VIRTUAL_SERVICE_NAME"
DEYE_LOG_DIR="/data/log/$DEYE_SERVICE_NAME"

INSTALL_VIRTUAL_BATTERY="${INSTALL_VIRTUAL_BATTERY:-1}"
INSTALL_DEYE_SOURCE="${INSTALL_DEYE_SOURCE:-0}"

mkdir -p "$BASE_DIR" "$VIRTUAL_LOG_DIR" "$DEYE_LOG_DIR"

create_virtual_service() {
    mkdir -p "$VIRTUAL_SERVICE_DIR"

    if [ ! -f "$VIRTUAL_SCRIPT_PATH" ]; then
        echo "Missing $VIRTUAL_SCRIPT_PATH" >&2
        exit 1
    fi

    cat > "$VIRTUAL_SERVICE_DIR/run" <<EOF
#!/bin/sh
export SOURCE_SERVICE="${SOURCE_SERVICE:-com.victronenergy.battery.socketcan_vecan0}"
export VIRTUAL_NAME="${VIRTUAL_NAME:-com.victronenergy.battery.inverted_vecan0}"
export DEVICE_INSTANCE="${VIRTUAL_DEVICE_INSTANCE:-100}"
export LOG_FILE="${VIRTUAL_LOG_FILE:-/data/log/dbus-virtual-battery/dbus-virtual-battery.log}"
export POLL_INTERVAL_MS="${VIRTUAL_POLL_INTERVAL_MS:-2000}"
exec python3 "$VIRTUAL_SCRIPT_PATH"
EOF

    chmod +x "$VIRTUAL_SCRIPT_PATH" "$VIRTUAL_SERVICE_DIR/run"
    rm -f "$VIRTUAL_LIVE_SERVICE_DIR"
    ln -s "$VIRTUAL_SERVICE_DIR" "$VIRTUAL_LIVE_SERVICE_DIR"

    if command -v svc >/dev/null 2>&1; then
        svc -t "$VIRTUAL_LIVE_SERVICE_DIR" 2>/dev/null || true
        svc -u "$VIRTUAL_LIVE_SERVICE_DIR" 2>/dev/null || true
    fi
}

create_deye_service() {
    mkdir -p "$DEYE_SERVICE_DIR"

    if [ ! -f "$DEYE_SCRIPT_PATH" ]; then
        echo "Missing $DEYE_SCRIPT_PATH" >&2
        exit 1
    fi

    cat > "$DEYE_SERVICE_DIR/run" <<EOF
#!/bin/sh
export CAN_INTERFACE="${CAN_INTERFACE:-vecan0}"
export SERVICE_NAME="${SERVICE_NAME:-com.victronenergy.battery.deye_vecan0}"
export DEVICE_INSTANCE="${DEYE_DEVICE_INSTANCE:-101}"
export PRODUCT_NAME="${PRODUCT_NAME:-Deye CAN Battery}"
export CUSTOM_NAME="${CUSTOM_NAME:-Deye Battery}"
export LOG_FILE="${DEYE_LOG_FILE:-/data/log/dbus-deye-battery/dbus-deye-battery.log}"
export POLL_INTERVAL_MS="${DEYE_POLL_INTERVAL_MS:-1000}"
export ONLINE_TIMEOUT_SECONDS="${ONLINE_TIMEOUT_SECONDS:-5}"
export NR_OF_CELLS_PER_BATTERY="${NR_OF_CELLS_PER_BATTERY:-16}"
export BATTERY_CAPACITY_AH="${BATTERY_CAPACITY_AH:-100}"
export CURRENT_SIGN_CORRECTION="${CURRENT_SIGN_CORRECTION:--1}"
export PUBLISH_RAW_STRINGS="${PUBLISH_RAW_STRINGS:-1}"
exec python3 "$DEYE_SCRIPT_PATH"
EOF

    chmod +x "$DEYE_SCRIPT_PATH" "$DEYE_SERVICE_DIR/run"
    rm -f "$DEYE_LIVE_SERVICE_DIR"
    ln -s "$DEYE_SERVICE_DIR" "$DEYE_LIVE_SERVICE_DIR"

    if command -v svc >/dev/null 2>&1; then
        svc -t "$DEYE_LIVE_SERVICE_DIR" 2>/dev/null || true
        svc -u "$DEYE_LIVE_SERVICE_DIR" 2>/dev/null || true
    fi
}

if [ "$INSTALL_DEYE_SOURCE" = "1" ]; then
    create_deye_service
fi

if [ "$INSTALL_VIRTUAL_BATTERY" = "1" ]; then
    create_virtual_service
fi

if [ "$INSTALL_DEYE_SOURCE" != "1" ] && [ "$INSTALL_VIRTUAL_BATTERY" != "1" ]; then
    echo "Nothing selected. Set INSTALL_DEYE_SOURCE=1 and/or INSTALL_VIRTUAL_BATTERY=1." >&2
    exit 1
fi
