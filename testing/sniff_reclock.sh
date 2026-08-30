#!/usr/bin/env bash
set -e

TRACE_FILE="/home/twilight/Projects/nvidia_reclock.trace"

echo "=== Fermi GPU Reclocking Sniffer ==="
echo "This script will record GPU register writes when shifting power states."
echo "Please enter your sudo password when prompted."
echo ""

# Make sure debugfs is mounted
if [ ! -d /sys/kernel/debug/tracing ]; then
    echo "Mounting debugfs..."
    sudo mount -t debugfs nodev /sys/kernel/debug
fi

# Enable mmiotrace
echo "Enabling mmiotrace..."
sudo sh -c "echo mmiotrace > /sys/kernel/debug/tracing/current_tracer"

# Start recording trace pipe in background
echo "Starting trace logger..."
sudo cat /sys/kernel/debug/tracing/trace_pipe > "$TRACE_FILE" &
LOG_PID=$!

echo "Launching glxgears to force GPU into P0 performance state..."
# Run glxgears with v-sync disabled to maximize GPU core load
__GL_SYNC_TO_VBLANK=0 glxgears > /dev/null 2>&1 &
GEARS_PID=$!

# Trace for 5 seconds
echo "Tracing active... waiting 5 seconds..."
sleep 5

echo "Stopping workload and loggers..."
# Terminate glxgears and logger
kill "$GEARS_PID" || true
sudo kill "$LOG_PID" || true

# Reset tracer to default
echo "Resetting tracer..."
sudo sh -c "echo nop > /sys/kernel/debug/tracing/current_tracer"

echo ""
echo "=== Done! ==="
echo "Trace log saved to: $TRACE_FILE"
echo "You can decode this trace by running:"
echo "  demmio -p <device_pci_id> < $TRACE_FILE"
echo ""
