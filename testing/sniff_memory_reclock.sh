#!/usr/bin/env bash
set -e

DIR="/home/twilight/Projects"
P8_FILE="$DIR/regs_p8_idle.txt"
P0_FILE="$DIR/regs_p0_load.txt"
DIFF_FILE="$DIR/regs_p8_vs_p0_diff.txt"
TRACE_RAW="$DIR/mmiotrace_p0.raw"
TRACE_DECODED="$DIR/mmiotrace_p0.decoded"

echo "=========================================================="
echo "    Fermi GT 555M (GF106) Memory Reclocking Sniffer       "
echo "=========================================================="
echo ""

dump_registers() {
    local outfile="$1"
    echo "Dumping memory controller (PFB) & clock registers to $outfile..."
    {
        echo "=== PCLOCK / MEMPLL (0x132000 - 0x132200) ==="
        nvapeek 0x132000 0x200
        echo "=== PCLOCK / REFPLL / ROUTING (0x137000 - 0x137400) ==="
        nvapeek 0x137000 0x400
        echo "=== PFB / DDR3 PHY & TIMINGS (0x10f000 - 0x10fa00) ==="
        nvapeek 0x10f000 0xa00
        echo "=== PFB / REFREG (0x10fe00 - 0x10fe50) ==="
        nvapeek 0x10fe00 0x50
    } > "$outfile"
}

# 1. Capture Idle State (P8)
echo "[1/4] Ensuring GPU is at idle (P8)..."
sleep 2
dump_registers "$P8_FILE"
echo "Saved idle registers to $P8_FILE"
echo ""

# 2. Start mmiotrace
echo "[2/4] Enabling mmiotrace for sequence capture..."
if [ ! -d /sys/kernel/debug/tracing ]; then
    mount -t debugfs nodev /sys/kernel/debug
fi
echo mmiotrace > /sys/kernel/debug/tracing/current_tracer
cat /sys/kernel/debug/tracing/trace_pipe > "$TRACE_RAW" &
TRACE_PID=$!

# 3. Trigger 3D Load (P0) and Dump Registers
echo "[3/4] Launching glxgears to switch GPU to high-performance P0 state..."
__GL_SYNC_TO_VBLANK=0 glxgears > /dev/null 2>&1 &
GEARS_PID=$!

# Wait for clocks to ramp up to P0
sleep 2

# Dump P0 Registers while glxgears is actively rendering
dump_registers "$P0_FILE"
echo "Saved P0 load registers to $P0_FILE"

# Let it trace for a few more seconds
sleep 3

# Terminate workload and trace
kill "$GEARS_PID" 2>/dev/null || true
kill "$TRACE_PID" 2>/dev/null || true
echo nop > /sys/kernel/debug/tracing/current_tracer

# 4. Generate Diff and Decode Trace
echo "[4/4] Generating register diff and decoding trace..."
diff -u "$P8_FILE" "$P0_FILE" > "$DIFF_FILE" || true
echo "Register diff saved to: $DIFF_FILE"

if command -v demmio >/dev/null 2>&1; then
    demmio -p 01:00.0 < "$TRACE_RAW" > "$TRACE_DECODED" 2>/dev/null || true
    echo "Decoded MMIO trace saved to: $TRACE_DECODED"
fi

echo ""
echo "=========================================================="
echo " Capture complete! Files created in $DIR:"
echo " - $P8_FILE (Idle P8 register map)"
echo " - $P0_FILE (Load P0 900MHz register map)"
echo " - $DIFF_FILE (Differences between P8 and P0)"
echo "=========================================================="
