#!/usr/bin/env bash
#
# Automated Kernel MMIO Tracing Utility for NVIDIA Fermi Reclocking
# Captures GPU register reads and writes during 3D load transitions.
#
set -e

if [ "$EUID" -ne 0 ]; then
    echo "[-] Error: This script must be run as root (sudo)."
    exit 1
fi

OUT_DIR="$(pwd)"
RAW_TRACE="$OUT_DIR/mmiotrace_capture.raw"
DECODED_TRACE="$OUT_DIR/mmiotrace_decoded.txt"

# Find tracefs
if [ -d /sys/kernel/tracing ]; then
    TRACE_DIR="/sys/kernel/tracing"
elif [ -d /sys/kernel/debug/tracing ]; then
    TRACE_DIR="/sys/kernel/debug/tracing"
else
    mount -t tracefs nodev /sys/kernel/tracing 2>/dev/null || mount -t debugfs nodev /sys/kernel/debug 2>/dev/null
    TRACE_DIR="/sys/kernel/tracing"
fi

echo "=========================================================="
echo "      Kernel MMIO Tracing Utility for NVIDIA Fermi        "
echo "=========================================================="
echo "[*] TraceFS located at: $TRACE_DIR"

if ! grep -qw mmiotrace "$TRACE_DIR/available_tracers"; then
    echo "[-] Error: Kernel does not support CONFIG_MMIOTRACE."
    echo "    Available tracers: $(cat "$TRACE_DIR/available_tracers")"
    exit 1
fi

# Reset and activate mmiotrace
echo "[*] Activating kernel mmiotrace..."
echo nop > "$TRACE_DIR/current_tracer"
echo "" > "$TRACE_DIR/trace" 2>/dev/null || true
echo mmiotrace > "$TRACE_DIR/current_tracer"

# Start background logger
echo "[*] Capturing MMIO trace stream to $RAW_TRACE..."
cat "$TRACE_DIR/trace_pipe" > "$RAW_TRACE" &
TRACE_PID=$!

# Trigger load
echo "[*] Launching 3D load to trigger state transitions (4s)..."
if command -v glxgears >/dev/null 2>&1; then
    DISPLAY="${DISPLAY:-:0}" __GL_SYNC_TO_VBLANK=0 glxgears >/dev/null 2>&1 &
    LOAD_PID=$!
elif command -v vkcube >/dev/null 2>&1; then
    DISPLAY="${DISPLAY:-:0}" vkcube >/dev/null 2>&1 &
    LOAD_PID=$!
fi

sleep 4
if [ -n "$LOAD_PID" ]; then
    kill "$LOAD_PID" 2>/dev/null || true
fi
sleep 2

# Stop tracer
echo "[*] Stopping tracer..."
kill "$TRACE_PID" 2>/dev/null || true
echo nop > "$TRACE_DIR/current_tracer"

echo "[✓] MMIO Trace captured: $(wc -c < "$RAW_TRACE") bytes."

# Decode with demmt or demmio if available
if command -v demmt >/dev/null 2>&1; then
    echo "[*] Decoding trace with demmt..."
    demmt -l "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null || true
    echo "[✓] Decoded output saved to: $DECODED_TRACE"
elif command -v demmio >/dev/null 2>&1; then
    echo "[*] Decoding trace with demmio..."
    demmio < "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null || true
    echo "[✓] Decoded output saved to: $DECODED_TRACE"
else
    echo "[i] Note: Install 'envytools-git' to automatically decode $RAW_TRACE with demmt."
fi

echo "=========================================================="
echo " Done!"
echo "=========================================================="
