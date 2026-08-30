#!/usr/bin/env python3
"""
Nouveau Fermi Diagnostic, MMIO Register & VBIOS Telemetry Tool
==============================================================
A comprehensive diagnostic utility for NVIDIA Fermi (GF100-GF119) GPUs.
Gathers PCI identity, VBIOS BIT tables, live hardware MMIO registers
(CRTC raster, pixel clock PLLs, display hub gating), and tracing capabilities.

Usage:
    sudo python3 tools/nouveau-fermi-diag.py
"""

import glob
import mmap
import os
import re
import struct
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

def parse_vbios_bit(rom_data):
    """Parses VBIOS BIT header and extracts P, M, U, C, d tables."""
    bit_offset = rom_data.find(b"BIT\x00")
    if bit_offset == -1:
        return None
    
    res = {
        "offset": hex(bit_offset),
        "tables": []
    }
    
    try:
        num_entries = rom_data[bit_offset + 10]
        entry_size = 6  # Standard Fermi/Tesla BIT descriptor entry size
        ptr = bit_offset + 12
        
        for i in range(num_entries):
            char_code = rom_data[ptr]
            if 65 <= char_code <= 90 or 97 <= char_code <= 122:  # ASCII A-Z, a-z
                entry_type = chr(char_code)
                tbl_ver = rom_data[ptr + 1]
                tbl_size = struct.unpack("<H", rom_data[ptr + 2:ptr + 4])[0]
                tbl_offset = struct.unpack("<H", rom_data[ptr + 4:ptr + 6])[0]
                
                if tbl_size > 0 and tbl_offset > 0:
                    table_info = f"BIT '{entry_type}' (ver {tbl_ver}, size {tbl_size} bytes, offset {hex(tbl_offset)})"
                    res["tables"].append((entry_type, table_info, tbl_offset))
            ptr += entry_size
    except Exception as e:
        res["error"] = str(e)
        
    return res

def read_mmio_registers(pci_slot="0000:01:00.0"):
    """Reads Fermi MMIO hardware registers via PCI resource0."""
    res_path = f"/sys/bus/pci/devices/{pci_slot}/resource0"
    if not os.path.exists(res_path):
        devs = glob.glob("/sys/bus/pci/devices/*/resource0")
        for d in devs:
            vendor = read_file(os.path.join(os.path.dirname(d), "vendor"))
            if vendor and "10de" in vendor.lower():
                res_path = d
                break

    if not os.path.exists(res_path) or os.geteuid() != 0:
        return None

    mmio_data = {}
    try:
        with open(res_path, "rb") as f:
            mmio = mmap.mmap(f.fileno(), 0x1000000, access=mmap.ACCESS_READ)
            
            # CRTC0 / CRTC1 Active & Total Raster Timing
            # 0x6100f4 = CRTC0 Active, 0x6100f8 = CRTC0 Total Blanking
            # 0x610af4 = CRTC1 Active, 0x610af8 = CRTC1 Total Blanking
            for head, base in [(0, 0x610000), (1, 0x610a00)]:
                act_raw = struct.unpack("<I", mmio[base + 0xf4:base + 0xf8])[0]
                tot_raw = struct.unpack("<I", mmio[base + 0xf8:base + 0xfc])[0]
                pll_raw = struct.unpack("<I", mmio[base + 0xd0:base + 0xd4])[0]
                
                act_w = act_raw & 0xffff
                act_h = (act_raw >> 16) & 0xffff
                tot_w = tot_raw & 0xffff
                tot_h = (tot_raw >> 16) & 0xffff
                
                mmio_data[f"head{head}"] = {
                    "active": f"{act_w}x{act_h}" if act_w and act_h else "Inactive",
                    "total_raster": f"{tot_w}x{tot_h}" if tot_w and tot_h else "0x0",
                    "tot_w": tot_w,
                    "tot_h": tot_h,
                    "pll_raw": hex(pll_raw),
                    "raster_raw": hex(tot_raw),
                }

            # Display Engine Hub Clock (0x137100 / hubk07)
            mmio_data["hub_clk"] = hex(struct.unpack("<I", mmio[0x137100:0x137104])[0])

            # Core & Shader PLL registers (0x137000 / 0x137004)
            mmio_data["core_pll"] = hex(struct.unpack("<I", mmio[0x137000:0x137004])[0])
            mmio_data["shader_pll"] = hex(struct.unpack("<I", mmio[0x137004:0x137008])[0])

            # Backlight PWM (0x61c084)
            mmio_data["backlight_pwm"] = hex(struct.unpack("<I", mmio[0x61c084:0x61c088])[0])

            # RAMCFG Straps & Memory Controller (0x100c14)
            mmio_data["ramcfg_strap"] = hex(struct.unpack("<I", mmio[0x100c14:0x100c18])[0])

            mmio.close()
    except Exception as e:
        mmio_data["error"] = str(e)

    return mmio_data

def main():
    if os.geteuid() != 0:
        print("[!] Warning: Running without root privileges. MMIO registers and VBIOS will not be read.")
        print("    For complete hardware & register telemetry, run: sudo python3 tools/nouveau-fermi-diag.py\n")

    report = []
    report.append("# 📋 Nouveau Fermi Hardware & MMIO Diagnostic Report")
    report.append(f"- **Generated at:** `{time.strftime('%Y-%m-%d %H:%M:%S %Z')}`")
    report.append(f"- **Kernel Version:** `{run_cmd('uname -srm')}`")

    # 1. PCI & GPU Hardware Identity
    report.append("\n## 🖥️ GPU & PCI Hardware Identity")
    pci_out = run_cmd("lspci -nn -d 10de:*")
    if pci_out:
        report.append(f"```text\n{pci_out}\n```")
    
    subsystem_out = run_cmd("lspci -v -d 10de:* | grep -E 'Subsystem|Control|Status|Kernel driver|Kernel modules'")
    if subsystem_out:
        report.append("### Subsystem & Driver Association")
        report.append(f"```text\n{subsystem_out}\n```")

    dmi_vendor = read_file("/sys/class/dmi/id/sys_vendor") or "Unknown"
    dmi_product = read_file("/sys/class/dmi/id/product_name") or "Unknown"
    dmi_version = read_file("/sys/class/dmi/id/product_version") or ""
    report.append(f"- **Host Machine:** `{dmi_vendor} {dmi_product} {dmi_version}`.strip()")

    # 2. Live MMIO Hardware Registers
    report.append("\n## 🔬 Live GPU MMIO Hardware Registers (BAR0)")
    mmio_info = read_mmio_registers()
    if mmio_info and "error" not in mmio_info:
        report.append("| Hardware Register Domain | Register Offset | Raw Hex Value | Decoded Telemetry |")
        report.append("|---|---|---|---|")
        
        for h in [0, 1]:
            head_data = mmio_info.get(f"head{h}", {})
            act = head_data.get("active", "N/A")
            tot = head_data.get("total_raster", "N/A")
            raw_tot = head_data.get("raster_raw", "N/A")
            reg = "0x6100f8" if h == 0 else "0x610af8"
            
            calc_note = ""
            if head_data.get("tot_w") and head_data.get("tot_h"):
                tot_pixels = head_data["tot_w"] * head_data["tot_h"]
                pclk_120 = (tot_pixels * 120) / 1000000
                pclk_60 = (tot_pixels * 60) / 1000000
                calc_note = f"Active: {act}, Total Blanking: {tot} (PCLK: ~{pclk_120:.2f}MHz @120Hz / ~{pclk_60:.2f}MHz @60Hz)"
            else:
                calc_note = "Head Inactive / No Output"
            report.append(f"| **CRTC{h} Raster Timing** | `{reg}` | `{raw_tot}` | {calc_note} |")

        report.append(f"| **Display Hub Gating** | `0x137100` | `{mmio_info.get('hub_clk')}` | Hub clock divider / gating control |")
        report.append(f"| **Core PLL Register** | `0x137000` | `{mmio_info.get('core_pll')}` | Core domain multiplier / divider |")
        report.append(f"| **Shader PLL Register** | `0x137004` | `{mmio_info.get('shader_pll')}` | 2x Hot Clock shader multiplier |")
        report.append(f"| **Backlight PWM** | `0x61c084` | `{mmio_info.get('backlight_pwm')}` | Hardware display brightness duty cycle |")
        report.append(f"| **RAM Strap / Timing** | `0x100c14` | `{mmio_info.get('ramcfg_strap')}` | VRAM configuration strap |")
    else:
        report.append("- *MMIO register reading not available (requires root privileges).*")

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
        report.append("- *No debugfs pstate node found.*")

    # 4. VBIOS ROM & BIT Table Parsing
    report.append("\n## 💾 VBIOS BIT Structure Analysis")
    vbios_paths = glob.glob("/sys/kernel/debug/dri/*/vbios.rom")
    if vbios_paths and os.path.exists(vbios_paths[0]):
        try:
            with open(vbios_paths[0], "rb") as f:
                rom_bytes = f.read()
            bit_res = parse_vbios_bit(rom_bytes)
            if bit_res:
                report.append(f"- **VBIOS ROM Size:** `{len(rom_bytes)} bytes`")
                report.append(f"- **BIT Header Location:** `{bit_res['offset']}`")
                report.append("### Detected BIT Sub-Tables:")
                for entry_type, tbl_desc, _ in bit_res["tables"]:
                    desc = ""
                    if entry_type == "P": desc = " *(Performance / P-States Table)*"
                    elif entry_type == "M": desc = " *(Memory Timing & RAMCFG Straps)*"
                    elif entry_type == "U": desc = " *(Voltage / VID Regulator Steps)*"
                    elif entry_type == "C": desc = " *(Clock Domain & PLL Routing)*"
                    elif entry_type == "d": desc = " *(Display Engine & LVDS/eDP Table)*"
                    elif entry_type == "A": desc = " *(Analog Output Table)*"
                    elif entry_type == "B": desc = " *(BIOS Data Table)*"
                    elif entry_type == "I": desc = " *(Init Script Table)*"
                    elif entry_type == "L": desc = " *(LVDS / Flat Panel Table)*"
                    report.append(f"- `{tbl_desc}`{desc}")
        except Exception as e:
            report.append(f"- *Error parsing VBIOS: {e}*")
    else:
        report.append("- *VBIOS ROM node not directly readable.*")

    # 5. Tracing & Reverse-Engineering Capabilities
    report.append("\n## 🔍 System Tracing & Envytools Status")
    tracers = read_file("/sys/kernel/tracing/available_tracers") or read_file("/sys/kernel/debug/tracing/available_tracers") or ""
    mmiotrace_avail = "mmiotrace" in tracers
    report.append(f"- **Kernel `mmiotrace` Support:** {'✅ Available' if mmiotrace_avail else '❌ Not in available_tracers'}")
    
    for tool in ["nvaget", "nvapeek", "demmt", "wlr-randr", "xrandr"]:
        installed = subprocess.run(f"which {tool}", shell=True, capture_output=True).returncode == 0
        report.append(f"- **Tool `{tool}`:** {'✅ Installed' if installed else '❌ Missing'}")

    report_text = "\n".join(report)

    # Print to stdout
    print("\n" + "=" * 75)
    print(report_text)
    print("=" * 75 + "\n")

    # Save to file
    out_file = "nouveau_fermi_diag_report.md"
    try:
        with open(out_file, "w") as f:
            f.write(report_text + "\n")
        print(f"[✓] Comprehensive report saved to: {os.path.abspath(out_file)}")
        print("    You can copy this directly into your GitHub Telemetry Issue!")
    except Exception as e:
        print(f"[!] Could not write to {out_file}: {e}")

if __name__ == "__main__":
    main()
