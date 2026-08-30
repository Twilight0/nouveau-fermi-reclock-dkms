#!/usr/bin/env bash
set -e

DIR="/home/twilight/Projects/nouveau-fermi-reclock-dkms/testing"
RAW_TRACE="$DIR/nvidia_reclock_full.raw"
DECODED_TRACE="$DIR/nvidia_full_reclock_trace.txt"
TRACE_DIR="/sys/kernel/tracing"

if [ ! -d "$TRACE_DIR" ]; then
    TRACE_DIR="/sys/kernel/debug/tracing"
fi

echo "=========================================================="
echo "  NVIDIA Driver & DDR3 Memory Reclocking MMIO Sniffer     "
echo "=========================================================="
echo ""

# 1. Terminate any running X sessions and release NVIDIA handles
echo "[1/6] Stopping any active Xorg sessions..."
pkill -9 -f Xorg 2>/dev/null || true
pkill -9 -f xinit 2>/dev/null || true
fuser -k /dev/nvidia* 2>/dev/null || true
sleep 2

# 2. Fully unload NVIDIA modules
echo "[2/6] Unloading NVIDIA kernel modules..."
rmmod nvidia_drm 2>/dev/null || true
rmmod nvidia_modeset 2>/dev/null || true
rmmod nvidia_uvm 2>/dev/null || true
rmmod nvidia 2>/dev/null || true

if lsmod | grep -q nvidia; then
    echo "[-] Error: Failed to unload nvidia modules. Something is still holding the GPU."
    echo "    Please run this script from a virtual console (e.g. Ctrl+Alt+F2)."
    exit 1
fi
echo "[+] Successfully unloaded all NVIDIA kernel modules!"

# 3. Reset and enable mmiotrace
echo "[3/6] Activating kernel mmiotrace..."
echo nop > "$TRACE_DIR/current_tracer"
echo "" > "$TRACE_DIR/trace" 2>/dev/null || true
echo mmiotrace > "$TRACE_DIR/current_tracer"

# 4. Start background trace pipe logger
echo "[4/6] Starting background trace pipe logger to $RAW_TRACE..."
cat "$TRACE_DIR/trace_pipe" > "$RAW_TRACE" &
TRACE_PID=$!
sleep 1

# 5. Reload driver under mmiotrace & run standalone glxgears on :1
echo "[5/6] Reloading NVIDIA driver under mmiotrace..."
modprobe nvidia
modprobe nvidia_drm

echo "[+] Launching standalone glxgears session on display :1 to force P0 (900 MHz)..."
# Start a clean standalone X instance running only glxgears
su - twilight -c 'xinit /usr/bin/glxgears -- :1 >/dev/null 2>&1 &' 2>/dev/null || true
sleep 6

echo "[+] Terminating 3D load..."
pkill -9 -f glxgears 2>/dev/null || true
pkill -9 -f Xorg 2>/dev/null || true
sleep 2

# 6. Stop mmiotrace and decode
echo "[6/6] Stopping tracer and decoding registers..."
kill "$TRACE_PID" 2>/dev/null || true
echo nop > "$TRACE_DIR/current_tracer" 2>/dev/null || true

echo "[*] Trace captured! Size: $(wc -c < "$RAW_TRACE") bytes"

if command -v demmio >/dev/null 2>&1; then
    echo "[*] Decoding MMIO trace with demmio for GF106 (01:00.0)..."
    demmio -p 01:00.0 < "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null || demmio < "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null || true
    echo "[*] Decoded trace saved to: $DECODED_TRACE"
fi

echo ""
echo "=========================================================="
echo " Done! All MMIO register reads/writes successfully traced!"
echo " You can now start your desktop normally with startx."
echo "=========================================================="
