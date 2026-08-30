#!/usr/bin/env bash
set -e

DIR="/home/twilight/Projects"
RAW_TRACE="$DIR/mmiotrace_capture.raw"
DECODED_TRACE="$DIR/mmiotrace_decoded.txt"

echo "=== NVIDIA Proprietary Driver Memory Reclocking Tracer ==="
echo ""

# Find tracing directory
if [ -d /sys/kernel/tracing ]; then
    TRACE_DIR="/sys/kernel/tracing"
elif [ -d /sys/kernel/debug/tracing ]; then
    TRACE_DIR="/sys/kernel/debug/tracing"
else
    mount -t tracefs nodev /sys/kernel/tracing 2>/dev/null || mount -t debugfs nodev /sys/kernel/debug 2>/dev/null
    TRACE_DIR="/sys/kernel/tracing"
fi

echo "[*] Using tracefs at $TRACE_DIR"

if ! grep -qw mmiotrace "$TRACE_DIR/available_tracers"; then
    echo "[-] Error: Kernel was not built with CONFIG_MMIOTRACE (mmiotrace not in available_tracers)."
    echo "    Available tracers: $(cat "$TRACE_DIR/available_tracers")"
    exit 1
fi

# 2. Reset and enable mmiotrace
echo "[*] Activating kernel mmiotrace..."
echo nop > "$TRACE_DIR/current_tracer"
echo "" > "$TRACE_DIR/trace" 2>/dev/null || true
echo mmiotrace > "$TRACE_DIR/current_tracer"

# 3. Start background trace pipe logger
echo "[*] Capturing MMIO trace stream to $RAW_TRACE..."
cat "$TRACE_DIR/trace_pipe" > "$RAW_TRACE" &
TRACE_PID=$!

# 4. Trigger state transition by launching glxgears as user twilight
echo "[*] Launching glxgears on DISPLAY=:0 to trigger P0 state transition..."
su - twilight -c 'DISPLAY=:0 __GL_SYNC_TO_VBLANK=0 glxgears >/dev/null 2>&1 &'
sleep 4

# 5. Stop glxgears to capture return to P8 idle
echo "[*] Terminating glxgears to capture down-clock transition..."
pkill -f glxgears || true
sleep 3

# 6. Stop mmiotrace
echo "[*] Stopping tracer..."
kill "$TRACE_PID" 2>/dev/null || true
echo nop > "$TRACE_DIR/current_tracer"

echo "[*] Trace captured! File size: $(wc -c < "$RAW_TRACE") bytes"

# 7. Decode with demmio
if command -v demmio >/dev/null 2>&1; then
    echo "[*] Decoding trace with demmio for GF106 (01:00.0)..."
    demmio -p 01:00.0 < "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null || demmio < "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null || true
    echo "[*] Decoded output saved to: $DECODED_TRACE"
fi

echo ""
echo "=== Done! ==="
