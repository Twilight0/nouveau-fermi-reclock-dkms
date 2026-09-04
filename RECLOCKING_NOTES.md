# Nouveau & NVIDIA Proprietary Driver Reclocking & Architecture Guide

This document is the unified reference for GPU reclocking, performance optimization, and display architecture on the **Dell XPS L702X** laptop equipped with an **NVIDIA GeForce GT 555M** (Fermi / **GF106M**, Device ID `10de:0dcd`, 3072 MiB DDR3, 1920×1080 @ 120 Hz 3D panel).

---

## 1. Hardware & System Specifications

| Parameter | Value |
|---|---|
| **GPU** | GeForce GT 555M (Fermi GF106M, stepping A1) |
| **Chipset ID** | `0x0c3680a1` (GF106, TSMC foundry) |
| **VRAM Type** | **DDR3** (192-bit bus width, NOT GDDR5) |
| **VRAM Size** | 3072 MiB |
| **RAMCFG Strap** | `0x6` |
| **Internal Panel** | 1920×1080 @ 120 Hz (eDP-1 / LGD `0x02c5`, 396.36 MHz pixel clock) |
| **Active Kernel** | Linux CachyOS LTS (6.18+) |

### VBIOS P-State Table (from BIT 'P' Table)

| State | Core Clock | Memory Clock | Effective Bandwidth | Voltage | Usage Profile |
|---|---|---|---|---|---|
| `03` | 50 MHz | 135 MHz | 270 MT/s | 820 mV | Low-Power Idle / Standby |
| `07` (or `08`) | 202 MHz | 324 MHz | 648 MT/s | 820 mV | Standard 2D Desktop Idle |
| `0f` | 590 MHz | 900 MHz | 1800 MT/s | 1030 mV | Full 3D Performance |

---

## 2. Executive Summary & Component Status

| Component | Status | Description / Solution |
|---|---|---|
| **Core / Shader Reclocking** | ✅ **Working** | Transitions to `590 MHz` core / `1180 MHz` shader cleanly via `nvkm_cstate_prog()`. |
| **Memory Reclocking Loop Locks** | ✅ **Fixed** | Fixed PRIVRING bus faults (`0x10a580`) and PMU D-state timeout deadlocks. |
| **DDR3 Memory Reclocking Path** | ⚠️ **Gated (`NvFermiMemReclock=0`)** | Full DDR3 MEMX reclocking sequence reverse-engineered; gated by default for absolute stability. |
| **Dynamic Clock Daemon** | ✅ **Working** | `nouveau-dynclockd.py` scales pstates (`07` ↔ `0f`) automatically based on GPU load. |
| **Backlight Control** | ✅ **Working** | ACPI EC hotkey driver (`dell-xps-brightness-dkms`) and hardware backlight sync. |
| **Fan RPM Reading** | ✅ **Working** | `dell_smm_hwmon` configured with `fan_mult=1` in `/etc/modprobe.d/dell-smm-hwmon.conf`. |

---

## 3. Nouveau Fermi Reclocking Architecture & Bug Fixes

### 3.1 The Reclocking Execution Pipeline

```
Userspace write to /sys/kernel/debug/dri/0/pstate
  └─► nvkm_clk_ustate()           [clk/base.c]
      └─► nvkm_pstate_prog()      [clk/base.c]
          ├─► Memory Reclock Block (if NvFermiMemReclock=1):
          │   ├─► gf100_ram_calc(ram, khz)    [fb/ramgf100.c]
          │   │   ├─ BIOS rammap/ramcfg/timing lookup
          │   │   ├─ gt215_pll_calc() for refpll & mempll
          │   │   └─ Generates MEMX bytecode via ram_wr32/ram_wait/ram_nsec
          │   │      └─► memx_cmd()            [pmu/memx.c]
          │   │          └─ Packages into PMU data segment via 0x10a1c4
          │   ├─► gf100_ram_prog()             [fb/ramgf100.c]
          │   │   └─► ram_exec() → nvkm_memx_fini(exec=true)
          │   │       └─► nvkm_pmu_send(MEMX_MSG_EXEC)  [pmu/gt215.c]
          │   │           └─ PMU Falcon microcontroller executes bytecode autonomously
          │   └─► gf100_ram_tidy()
          └─► nvkm_cstate_prog()   [clk/base.c] — programs core and shader clock domains
```

### 3.2 Resolved Kernel Bugs

1. **PRIVRING Fault Loop on Register `0x10a580` (Resolved)**:
   - *Problem*: Register `0x10a580` is a PMU data lock that exists only on Tesla (`card_type < NV_C0`). On Fermi (`NV_C0` / GF100+), writing to it generated ~33,000 PRIVRING faults every 5 seconds and hung in an infinite `do { wr32(0x10a580) } while (rd32 != 1)` loop.
   - *Fix*: Guarded all accesses with `if (device->card_type < NV_C0)`.

2. **PMU Reply Timeout D-State Hang (Resolved)**:
   - *Problem*: `gt215_pmu_send()` used unconditional `wait_event()`. If the PMU encountered a delay or missing VBlank interrupt, the calling thread entered uninterruptible sleep (D-state) forever.
   - *Fix*: Replaced `wait_event()` with active polling and a strict 100ms timeout window.

3. **Missing GDDR5 Training Guard on DDR3 (Resolved)**:
   - *Problem*: `gf100_ram_calc()` unconditionally called GDDR5 hardware training routines that do not exist on DDR3 cards, hanging the Falcon engine.
   - *Fix*: Added a check to skip GDDR5 training when `ram->base.type == NVKM_RAM_TYPE_DDR3`.

4. **Silent Error Swallowing (Resolved)**:
   - *Problem*: Return codes from memory reclocking failures were overwritten before exiting `nvkm_pstate_prog()`.
   - *Fix*: Correctly propagate PMU and MEMX error codes up the call stack.

5. **Display Hub Clock Locking & Black Screen Prevention (`gf100_clk_calc`)**:
   - *Problem*: In `nvkm/subdev/clk/gf100.c`, `gf100_clk_calc()` attempted to recalculate and reprogram display crossbar/hub clocks (`hubk07`, `hubk06`, `hubk01`) on every performance state change. On Fermi (particularly with high pixel-clock eDP 120Hz displays at 396.36 MHz), reprogramming the hub causes display FIFO underruns, display link loss, or black screens during clock transitions.
   - *Fix*: Omitted `hubk07`, `hubk06`, and `hubk01` from dynamic frequency transitions. The display hub remains locked to its stable boot frequency, enabling seamless core (`gpc`), shader, and `rop` scaling without display jitter.

6. **VBIOS VMAP Undervoltage Correction (`nvkm_pstate_new`)**:
   - *Problem*: `nvkm_volt_map` mapped the `0f` voltage ID to 862.5 mV (VID `0x04` = 870 mV) instead of factory 1.030 V (VID `0x01`), causing instability/freezes under 3D load.
   - *Fix*: Enforcing `cstate->voltage = 0x67` (1030000 µV fallback) for pstate `0x0f` guarantees factory 1.030 V delivery under full 3D load.

---

## 4. DDR3 Memory Reclocking Reverse Engineering (Proprietary Trace)

From the demmio-decoded mmiotrace of the NVIDIA 390.157 proprietary driver (`nvidia_full_reclock_trace.txt`), the complete register sequence for DDR3 reclocking on GF106 is documented below.

### 4.1 Host-Side PHY Configuration (Prior to MEMX Execution)

| Register | 324 MHz (P7/P8 Idle) | 900 MHz (P0 Load) | Description |
|---|---|---|---|
| `0x10f050` | `0xff000450` | `0xff001050` | PFB broadcast mode control |
| `0x10f440` | `0x22f84f10` | `0x22f84f10` | DDR3 impedance calibration |
| `0x10f444` | `0x04cc001f` | `0x04cc883f` | DDR3 termination tuning |
| `0x10f468` | `0x00001005` | `0x00020020` | DDR3 data strobe timing |
| `0x10f808` | `0x08020004` | `0x08020004` | PHY DLL configuration |
| `0x10f824` | `0x000279e7` | `0x00021e67` | PHY DLL feedback divider |

### 4.2 Critical DDR3 Timing Registers (Inside MEMX Script)

| Register | 324 MHz (Idle) | 900 MHz (Load) | Timing Parameter |
|---|---|---|---|
| `0x10f290` | `0x061a3813` | `0x0e44922e` | `tRAS` / `tRC` |
| `0x10f294` | Derived from JEDEC | `0x4ce3848c` | `tRCD` / `tRP` |
| `0x10f298` | `0x44060411` | `0x440e0711` | `tWR` / `tRFC` |
| `0x10f29c` | `0x00001e6a` | `0x000050b6` | `tFAW` |
| `0x10f2a0` | `0x42e28069` | `0x42e38069` | `tRRD` / `tWTR` |
| `0x10f224` | VBIOS default | `0x0e070c07` | Arbiter timing |

### 4.3 MEMPLL Frequency Dividers (`0x132004`)

- **324 MHz**: `0x00071806` ($M=6, N=24, P=7$)
- **900 MHz**: `0x0002230b` ($M=11, N=35, P=2$)

### 4.4 DDR3 Mode Register Sequence

1. `0x10f300` $\leftarrow$ `0x00001520` (MR0: DLL Reset + CAS Latency)
2. `0x10f300` $\leftarrow$ `0x00001420` (MR0: DLL Stable)
3. `0x10f320` $\leftarrow$ `0x002000a0` (EMR2: CAS Write Latency for 900 MHz)
4. `0x10f300` $\leftarrow$ `0x00001e04` (MR0: CAS=7, Burst Length=8)
5. `0x10f870` $\leftarrow$ `0xaaaaaaaa` (ZQ Calibration pattern)
6. `0x10f324` $\leftarrow$ Write leveling sequence (`0x03cb`, `0x06cb`, `0x01cb`, `0x03ca`, `0x06ca`, `0x01ca`)
7. `0x10f830` $\leftarrow$ `0x01000011` $\rightarrow$ `0x00000011` (PHY DLL reset pulse & release)

---

## 5. Display Engine & 120 Hz Investigation

### 5.1 Bandwidth Limits on Fermi eDP
- The 1920×1080 @ 120 Hz panel operates at a **396.36 MHz pixel clock**.
- Standard DisplayPort 1.1a (supported on Fermi GF106) provides 4 lanes at 2.7 Gbps (HBR), yielding a max usable data bandwidth of **8.64 Gbps**.
- At 24 bpp (8 bpc), 120 Hz requires **9.51 Gbps** (exceeds link bandwidth).
- Both drivers resolve this by clamping color depth to **6 bpc** (18 bpp, ~7.13 Gbps) with spatial dithering (`asyh->or.bpc = 6`).

### 5.2 Why Nouveau Compositor Locks to 60 FPS
1. **Aggressive VBlank Power Saving (`dev->vblank_disable_immediate = true`)**:
   In `dispnv50/disp.c` (line 3014), Nouveau disables VBlank interrupts immediately when unrequested. When desktop compositors (Muffin/Mutter/Clutter) query VBlank timestamps via DRI2/DRI3, waking up the IRQ creates micro-delays that degrade frame pacing, locking `glxgears` to ~53–57 FPS under VSync.
2. **Compositor Unredirection**:
   With VSync disabled (`vblank_mode=0`), the GPU renders at **556+ FPS** on Nouveau.
3. **Proprietary NVIDIA Driver Advantage**:
   The NVIDIA 390.157 driver utilizes its proprietary closed-source `NV-CONTROL` display pipeline, custom hardware microcode, and dedicated hardware timestamping registers that bypass generic Xorg KMS VBlank interrupt scheduling, achieving full native 120 FPS rendering.

---

## 6. Performance Benchmark Summary

| Configuration | Driver | Core Clock | Memory Clock | `glxgears` (Unthrottled) | `glxgears` (VSync) |
|---|---|---|---|---|---|
| **Boot State (Default)** | Nouveau | 202 MHz | 324 MHz | ~320 FPS | ~52 FPS |
| **Reclocked (`0f`)** | Nouveau | 590 MHz | 324 MHz | **~2,700 FPS** | ~57 FPS |
| **Proprietary (Xorg)** | NVIDIA 390.157 | 590 MHz | 900 MHz | **~11,850 FPS** | 120 FPS |
| **Proprietary (XLibre-Beta)** | NVIDIA 390.157 | 590 MHz | 900 MHz | **~12,750+ FPS** | 120 FPS |

---

## 7. Modified Driver Files Inventory

- **`nouveau_backlight.c`**: Force `nv_backlight` registration and bypass ACPI checks.
- **`nvkm/subdev/clk/base.c`**: Add `NvFermiMemReclock` safety gate and error propagation.
- **`nvkm/subdev/clk/gf100.c`**: Fix clock domain table and add `NVKM_CLK_DOM_FLAG_CORE`.
- **`nvkm/subdev/fb/ramgf100.c`**: Add DDR3 register tables, skip GDDR5 training on DDR3.
- **`nvkm/subdev/pmu/gt215.c`**: Guard `0x10a580` PRIVRING lock and add 100ms timeout polling.
- **`nvkm/subdev/pmu/memx.c`**: Guard `0x10a580` lock in `memx_init` and `memx_fini`.
