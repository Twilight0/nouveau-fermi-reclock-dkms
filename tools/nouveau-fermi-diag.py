#!/usr/bin/env python3
"""
Nouveau Fermi Diagnostic & Hardware Telemetry Tool
===================================================
A standalone diagnostic utility to collect GPU chipset details, VBIOS power states,
display connector modes, and hardware registers for NVIDIA Fermi (GF100-GF119) GPUs.

Usage:
    sudo python3 nouveau-fermi-diag.py
"""

import glob
import os
import re
import subprocess
import sys
import time

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return f"Error executing '{cmd}': {e}"

def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return None

def main():
    if os.geteuid() != 0:
        print("[!] Warning: Running without root privileges. Some debugfs nodes may not be readable.")
        print("    For full diagnostic output, please run: sudo python3 nouveau-fermi-diag.py\n")

    report = []
    report.append("# 📋 Nouveau Fermi Hardware Diagnostic Report")
    report.append(f"- **Generated at:** `{time.strftime('%Y-%m-%d %H:%M:%S %Z')}`")
    report.append(f"- **Kernel Version:** `{run_cmd('uname -srm')}`")

    # 1. PCI & GPU Identification
    report.append("\n## 🖥️ GPU & PCI Hardware Identity")
    pci_out = run_cmd("lspci -nn -d 10de:*")
    if pci_out:
        report.append(f"```text\n{pci_out}\n```")
    
    # Subsystem details
    subsystem_out = run_cmd("lspci -v -d 10de:* | grep -E 'Subsystem|Control|Status|Kernel driver|Kernel modules'")
    if subsystem_out:
        report.append("### Subsystem & Driver Association")
        report.append(f"```text\n{subsystem_out}\n```")

    # DMI / Machine information
    dmi_vendor = read_file("/sys/class/dmi/id/sys_vendor") or "Unknown"
    dmi_product = read_file("/sys/class/dmi/id/product_name") or "Unknown"
    dmi_version = read_file("/sys/class/dmi/id/product_version") or ""
    report.append(f"- **Host Machine:** `{dmi_vendor} {dmi_product} {dmi_version}`.strip()")

    # 2. Kernel Module & Boot Options
    report.append("\n## ⚙️ Nouveau Driver Parameters")
    modinfo = run_cmd("systool -v -m nouveau 2>/dev/null | grep -A 25 'Parameters:'")
    if modinfo:
        report.append(f"```text\n{modinfo}\n```")
    else:
        cmdline = read_file("/proc/cmdline") or "N/A"
        report.append(f"- **Boot Command Line:** `{cmdline}`")

    # 3. P-States & Reclocking Status
    report.append("\n## ⚡ Performance States (DebugFS)")
    pstate_found = False
    for pstate_file in sorted(glob.glob("/sys/kernel/debug/dri/*/pstate")):
        content = read_file(pstate_file)
        if content:
            pstate_found = True
            report.append(f"### Node: `{pstate_file}`")
            report.append(f"```text\n{content}\n```")
    if not pstate_found:
        report.append("- *No debugfs pstate node found. Is debugfs mounted and nouveau loaded?*")

    # 4. DRM Connectors & Display Panels
    report.append("\n## 📺 Display Connectors & Refresh Rates")
    connectors = sorted(glob.glob("/sys/class/drm/card*-*"))
    for conn in connectors:
        conn_name = os.path.basename(conn)
        status = read_file(os.path.join(conn, "status")) or "unknown"
        if status == "connected":
            modes = read_file(os.path.join(conn, "modes")) or "None"
            enabled = read_file(os.path.join(conn, "enabled")) or "unknown"
            dpms = read_file(os.path.join(conn, "dpms")) or "unknown"
            
            report.append(f"### Connector: `{conn_name}` (**Connected**)")
            report.append(f"- **Enabled:** `{enabled}` | **DPMS:** `{dpms}`")
            report.append(f"- **Available Modes:**\n```text\n{modes}\n```")
            
            # EDID info if available
            edid_path = os.path.join(conn, "edid")
            if os.path.exists(edid_path) and os.path.getsize(edid_path) > 0:
                report.append(f"- **EDID Size:** `{os.path.getsize(edid_path)} bytes`")

    # 5. VBIOS Extraction Summary
    report.append("\n## 💾 VBIOS Information")
    vbios_paths = glob.glob("/sys/kernel/debug/dri/*/vbios.rom")
    if vbios_paths:
        for vpath in vbios_paths:
            size = os.path.getsize(vpath) if os.path.exists(vpath) else 0
            report.append(f"- **VBIOS ROM Node:** `{vpath}` ({size} bytes available)")
    else:
        report.append("- *VBIOS debugfs node not directly accessible.*")

    report_text = "\n".join(report)

    # Print to stdout
    print("\n" + "=" * 70)
    print(report_text)
    print("=" * 70 + "\n")

    # Save to file
    out_file = "nouveau_fermi_diag_report.md"
    try:
        with open(out_file, "w") as f:
            f.write(report_text + "\n")
        print(f"[✓] Diagnostic report saved to: {os.path.abspath(out_file)}")
        print("    You can copy the contents of this file directly into a GitHub Issue!")
    except Exception as e:
        print(f"[!] Could not write to {out_file}: {e}")

if __name__ == "__main__":
    main()
