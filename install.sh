#!/bin/sh
set -eu

SERVICE_NAME="dbus-virtual-battery"
BASE_DIR="/data/dbus-virtual-battery"
SCRIPT_PATH="$BASE_DIR/dbus-virtual-battery.py"
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
export LOG_FILE=/data/log/dbus-virtual-battery/dbus-virtual-battery.log
exec python3 /data/dbus-virtual-battery/dbus-virtual-battery.py
EOF

chmod +x "$SCRIPT_PATH" "$RUN_FILE"

rm -f "$LIVE_SERVICE_DIR"
ln -s "$SERVICE_DIR" "$LIVE_SERVICE_DIR"

if command -v svc >/dev/null 2>&1; then
    svc -t "$LIVE_SERVICE_DIR" 2>/dev/null || true
    svc -u "$LIVE_SERVICE_DIR" 2>/dev/null || true
fi
