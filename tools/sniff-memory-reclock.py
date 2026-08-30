#!/usr/bin/env python3
"""
Fermi (GF100-GF119) DDR3/GDDR5 Memory Reclocking Direct Register Sniffer
=======================================================================
Directly maps GPU BAR0 MMIO space via sysfs to capture register state diffs
between idle (P8 / 324MHz) and full 3D load (P0 / 900MHz) performance states.

Captures Memory Controller (PFB), MEMPLL, PCLOCK routing, and PHY DLL timings.

Usage:
    sudo python3 tools/sniff-memory-reclock.py
"""

import glob
import mmap
import os
import struct
import subprocess
import sys
import time

BAR0_SIZE = 16 * 1024 * 1024  # 16 MB

REG_RANGES = [
    ("MEMPLL / Clocks", 0x132000, 0x132120),
    ("PCLOCK / REFPLL / Routing", 0x137000, 0x137410),
    ("PFB Refresh & Command", 0x10f000, 0x10f0c0),
    ("PFB Memory Timings (tCL/tRCD/tRP/tRAS)", 0x10f200, 0x10f2c0),
    ("PFB Training & PHY DLL", 0x10f300, 0x10f360),
    ("PFB Drive Strength & ODT", 0x10f600, 0x10f630),
    ("PFB Powerdown & DLL Control", 0x10f800, 0x10f850),
    ("PFB Config & Calibration", 0x10f960, 0x10f9d0),
    ("PFB Sub-blocks (0x10fb00)", 0x10fb00, 0x10fb20),
    ("PFB REFREG (0x10fe00)", 0x10fe00, 0x10fe40),
    ("Display & Flush (PDISP)", 0x611200, 0x611210),
    ("Display Timing (PDISP)", 0x61c140, 0x61c150),
]

def find_gpu_resource():
    devs = glob.glob("/sys/bus/pci/devices/*/resource0")
    for d in devs:
        vendor_file = os.path.join(os.path.dirname(d), "vendor")
        if os.path.exists(vendor_file):
            try:
                with open(vendor_file, "r") as f:
                    if "10de" in f.read().lower():
                        return d
            except Exception:
                pass
    return "/sys/bus/pci/devices/0000:01:00.0/resource0"

def main():
    if os.geteuid() != 0:
        print("[-] Error: Root privileges required (sudo).")
        print("    Usage: sudo python3 tools/sniff-memory-reclock.py")
        sys.exit(1)

    res_path = find_gpu_resource()
    if not os.path.exists(res_path):
        print(f"[-] Error: Could not find NVIDIA GPU PCI BAR0 resource at {res_path}")
        sys.exit(1)

    print("=" * 70)
    print("   NVIDIA Fermi Memory Reclocking Direct Hardware Sniffer   ")
    print("=" * 70)
    print(f"[*] Mapping BAR0 at {res_path}...")

    try:
        fd = os.open(res_path, os.O_RDONLY | os.O_SYNC)
        mm = mmap.mmap(fd, BAR0_SIZE, prot=mmap.PROT_READ)
    except Exception as e:
        print(f"[-] Failed to mmap BAR0: {e}")
        sys.exit(1)

    def read32(addr):
        return struct.unpack("<I", mm[addr:addr+4])[0]

    pmc_id = read32(0x0)
    print(f"[+] GPU Hardware Verified: PMC.ID = 0x{pmc_id:08x}")

    def dump_snapshot():
        snap = {}
        for section_name, start, end in REG_RANGES:
            sec_data = {}
            for addr in range(start, end, 4):
                sec_data[addr] = read32(addr)
            snap[section_name] = sec_data
        return snap

    # Step 1: Capture Idle State (P8)
    print("\n[1/3] Capturing idle (P8 / desktop) register snapshot...")
    time.sleep(1)
    p8_snapshot = dump_snapshot()

    # Step 2: Trigger 3D Load (P0)
    print("[2/3] Launching 3D workload to trigger performance state (P0 @ 900MHz)...")
    env = os.environ.copy()
    if "DISPLAY" not in env: env["DISPLAY"] = ":0"
    env["__GL_SYNC_TO_VBLANK"] = "0"
    if "WAYLAND_DISPLAY" not in env and os.path.exists("/run/user/1000/wayland-0"):
        env["WAYLAND_DISPLAY"] = "wayland-0"

    proc = None
    for cmd in [["glxgears"], ["vkcube"], ["weston-simple-egl", "-b"]]:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            break
        except Exception:
            continue

    time.sleep(3.0)

    # Step 3: Capture Load State (P0)
    print("[3/3] Capturing active load (P0) register snapshot...")
    p0_snapshot = dump_snapshot()

    if proc:
        proc.terminate()
        try: proc.wait(timeout=2)
        except Exception: proc.kill()

    mm.close()
    os.close(fd)

    # Generate Markdown Report
    print("\n[+] Comparing register states and generating report...")
    diff_sections = []
    total_diffs = 0

    for section_name in p8_snapshot.keys():
        s_p8 = p8_snapshot[section_name]
        s_p0 = p0_snapshot[section_name]
        diffs = []
        for addr in sorted(s_p8.keys()):
            v8, v0 = s_p8[addr], s_p0[addr]
            if v8 != v0:
                diffs.append((addr, v8, v0))
                total_diffs += 1
        
        if diffs:
            sec_lines = [f"### {section_name}", "| Register | Idle (P8) | Load (P0) | Description / Role |", "|---|---|---|---|"]
            for addr, v8, v0 in diffs:
                note = ""
                if addr == 0x132004: note = "**MEMPLL M/N/P Divider**"
                elif addr == 0x132000: note = "**MEMPLL Control & Lock**"
                elif addr == 0x1373f0: note = "**PCLOCK Memory Clock Routing**"
                elif 0x10f290 <= addr <= 0x10f2a0: note = "**DDR3/GDDR5 Timing Register**"
                elif 0x10f600 <= addr <= 0x10f630: note = "PHY Output Drive Strength & ODT"
                elif 0x10f800 <= addr <= 0x10f850: note = "PHY DLL & Powerdown Control"
                sec_lines.append(f"| `0x{addr:06x}` | `0x{v8:08x}` | `0x{v0:08x}` | {note} |")
            diff_sections.append("\n".join(sec_lines))

    report_content = f"""# Fermi GPU Memory Controller Register Diff (P8 vs P0)

- **Captured at:** `{time.strftime('%Y-%m-%d %H:%M:%S')}`
- **GPU PMC ID:** `0x{pmc_id:08x}`
- **Total Registers Modified During Reclocking:** `{total_diffs}`

---

## Modified Register Telemetry

{chr(10).join(diff_sections) if diff_sections else "*No register differences detected during load test.*"}
"""

    out_file = "fermi_memory_reclock_report.md"
    with open(out_file, "w") as f:
        f.write(report_content)

    print(f"\n[✓] Memory reclocking register diff saved to: {os.path.abspath(out_file)}")
    print(f"    Detected {total_diffs} hardware register modifications.")

if __name__ == "__main__":
    main()
