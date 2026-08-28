# Nouveau Fermi DDR3 Memory Reclocking — Deep Analysis

## Executive Summary

This document is a comprehensive reverse-engineering analysis of DDR3 memory reclocking
on the **NVIDIA GeForce GT 555M** (Fermi / **GF106M**, Device ID `10de:0dcd`, 3072 MiB DDR3,
1920×1080 @ 120 Hz). It combines findings from:

- **Proprietary NVIDIA 390.157 mmiotrace** (`nvidia_full_reclock_trace.txt`, 24 MB decoded by `demmio`)
- **VBIOS performance tables** parsed by `nvbios` (`gpu_vbios_perf.txt`)
- **Direct BAR0 register sniffing** (`sniff_memory_reclock.py` / `.sh`)
- **Nouveau kernel driver source** (`ramgf100.c`, `gt215.c`, `memx.c`, `base.c`)
- **Patch analysis** (`nouveau-fermi-reclock.patch`, 377 lines across 6 files)

### Current Status

| Component | Status | Notes |
|---|---|---|
| Core/Shader Reclocking | ✅ Working | GPC/ROP clocks transition to 590 MHz cleanly |
| Memory Reclocking | ❌ Broken | PMU MEMX script hangs; PRIVRING faults flood `dmesg` |
| Dynamic Clock Daemon | ✅ Working | `nouveau-dynclockd.py` scales pstates based on GPU load |
| Backlight Sync | ✅ Working | ACPI → `nv_backlight` brightness forwarding |

---

## 1. Hardware Specifications

| Parameter | Value |
|---|---|
| GPU | GeForce GT 555M (GF106M, stepping A1) |
| Chipset ID | `0x0c3680a1` (GF106, TSMC foundry) |
| VRAM Type | **DDR3** (NOT GDDR5) |
| VRAM Size | 3072 MiB |
| VRAM Bus Width | 192-bit |
| RAMCFG Strap | `0x6` |
| Display | 1920×1080 @ 120 Hz (DP-1 internal panel) |

### P-State Table (from VBIOS BIT 'P' table)

| State | Core Clock | Memory Clock | Effective Bandwidth | Voltage |
|---|---|---|---|---|
| `03` | 50 MHz | 135 MHz | 270 MT/s | 820 mV |
| `07` | 202 MHz | 324 MHz | 648 MT/s | 820 mV |
| `0f` | 590 MHz | 900 MHz | 1800 MT/s | 1030 mV |

---

## 2. The Reclocking Pipeline

### 2.1 Full Execution Path

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
          │   │           └─ PMU microcontroller executes the bytecode script
          │   │              independently, sequencing register writes, delays,
          │   │              VBLANK waits, and PLL lock waits
          │   └─► gf100_ram_tidy()
          └─► nvkm_cstate_prog()   [clk/base.c] — programs core/shader clocks
```

### 2.2 Key Architectural Detail

The memory reclocking is **NOT** done by the host CPU writing registers directly.
Instead, the host builds a **MEMX bytecode script** and uploads it to the PMU's
internal data segment. The PMU (a Falcon microcontroller) then executes the script
autonomously with microsecond-level timing precision that the host CPU cannot achieve.

The MEMX bytecode supports these operations:
- `MEMX_WR32` — Write a 32-bit value to an MMIO register
- `MEMX_WAIT` — Poll a register with bitmask until condition met (with timeout)
- `MEMX_DELAY` — Wait for N nanoseconds
- `MEMX_VBLANK` — Wait for vertical blanking period on a specific display head
- `MEMX_TRAIN` — Execute DDR memory training (GDDR5 only)
- `FB PAUSE` / `FB RESUME` — Stall/unstall the framebuffer access

---

## 3. Proprietary Driver MEMX Scripts (from mmiotrace)

The proprietary NVIDIA 390.157 driver executes **two distinct MEMX scripts** during
a memory reclocking event. These were captured via `mmiotrace` + `demmio` decoding.

### 3.1 Script A — Downclocking (P0 → P8, 900 MHz → 324 MHz)

This script runs first to transition from high-performance to idle clocks.

```
┌─ Phase 1: PLL Preparation ──────────────────────────────────────────────┐
│ R[0x10fe20] := 0x20030000    # REFPLL setup                            │
│ R[0x137320] := 0x00000103    # PCLOCK PLL reference divider source      │
│ R[0x137330] := 0x81200600    # PCLOCK PLL reference divider control     │
│ R[0x10fe20] := 0x20030001    # Enable REFPLL                            │
│ WAIT BITMASK R[0x137390] & 0x00020000 == 0x00020000  (64µs timeout)     │
│                              ^^^ Wait for REFPLL lock                   │
│ R[0x10fe20] := 0x20030005    # REFPLL locked, enable output             │
│ R[0x132004] := 0x00071806    # MEMPLL M/N/P = M=6, N=0x18, P=7         │
│                              # → 324 MHz DDR3 (648 MT/s)                │
│ R[0x132000] := 0x18000001    # MEMPLL enable                            │
│ WAIT BITMASK R[0x137390] & 0x00000002 == 0x00000002  (64µs timeout)     │
│                              ^^^ Wait for MEMPLL lock                   │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 2: Pre-Switch Setup ─────────────────────────────────────────────┐
│ R[0x137370] := 0x00000007    # Clock routing control                    │
│ R[0x137380] := 0x00000001    # Clock routing commit                     │
│ R[0x100b0c] := 0x00080012    # PFFB pre-switch configuration            │
│ WAIT STATUS HEAD0_VBLANK, 45478000 ns (≈45ms, ~1 frame @ 120Hz)        │
│ WAIT STATUS !HEAD0_VBLANK, 45478000 ns                                  │
│                              ^^^ Sync to vertical blanking boundary!    │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 3: FB Pause & RAM Self-Refresh ──────────────────────────────────┐
│ R[0x611200] := 0x00003300    # Display stall (PDISPLAY flush)           │
│ FB PAUSE                     # Halt all framebuffer access              │
│ R[0x10f200] := 0x00028000    # CFG0: disable active RAM access          │
│ R[0x10f314] := 0x00000001    # Issue PRECHARGE ALL                      │
│ R[0x10f210] := 0x00000000    # Disable auto-refresh                     │
│ R[0x10f310] := 0x00000001    # Manual REFRESH (×2)                      │
│ WAIT 1000 ns                                                            │
│ R[0x10f090] := 0x00000060    # PFB clock gate                           │
│ R[0x10f090] := 0xc000007e    # PFB clock gate + self-refresh entry      │
│ R[0x10f660] := 0x00001010    # Drive strength idle config               │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 4: Clock Switch & DDR3 MR Programming ──────────────────────────┐
│ R[0x137370] := 0x00000007                                               │
│ R[0x137380] := 0x00000001                                               │
│ R[0x137360] := 0x00000000    # Switch memory clock to new PLL output    │
│ R[0x10f090] := 0x4000007f    # Exit self-refresh                        │
│ R[0x10f210] := 0x80000000    # Re-enable auto-refresh                   │
│ WAIT 2000 ns                                                            │
│ R[0x10f300] := 0x00001520    # MR0: DLL Reset + CAS Latency            │
│ WAIT 1000 ns                                                            │
│ R[0x10f300] := 0x00001420    # MR0: DLL stable                          │
│ WAIT 1000 ns                                                            │
│ R[0x10f300] := 0x00001420    # MR0 again (paranoia write)               │
│ WAIT 1000 ns                                                            │
│ R[0x10f870] := 0xaaaaaaaa    # DDR3 ZQ calibration pattern              │
│ R[0x10f300] := 0x00001520    # MR0 DLL Reset (re-trigger)               │
│ WAIT 1000 ns                                                            │
│ R[0x10f300] := 0x00001420    # MR0 DLL stable                           │
│ WAIT 1000 ns                                                            │
│ WAIT 2000 ns                 # Extra settling time                      │
│ R[0x10f324] := 0x000003cb    # EMR3 training sequence (×6 writes)       │
│ R[0x10f324] := 0x000006cb                                               │
│ R[0x10f324] := 0x000001cb                                               │
│ R[0x10f324] := 0x000003ca                                               │
│ R[0x10f324] := 0x000006ca                                               │
│ R[0x10f324] := 0x000001ca                                               │
│ R[0x10f830] := 0x01000017    # PHY DLL reset pulse                      │
│ R[0x10f830] := 0x00000017    # PHY DLL release                          │
│ FB RESUME                    # Unstall framebuffer                      │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 5: Post-Switch Cleanup ──────────────────────────────────────────┐
│ R[0x100b0c] := 0x00080028    # PFFB post-switch config                  │
│ R[0x611200] := 0x00003330    # Display un-stall                         │
│ R[0x10f200] := 0x00028800    # CFG0: re-enable active RAM access        │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Script B — Upclocking (P8 → P0, 324 MHz → 900 MHz)

```
┌─ Phase 1: PLL Preparation ──────────────────────────────────────────────┐
│ R[0x1373ec] := 0x00020909    # Clock routing pre-config                 │
│ ... (same REFPLL sequence as Script A)                                  │
│ R[0x132004] := 0x0002230b    # MEMPLL M/N/P = M=0xb, N=0x23, P=2       │
│                              # → 900 MHz DDR3 (1800 MT/s)               │
│ R[0x132000] := 0x18030001    # MEMPLL enable + additional flags         │
│ WAIT BITMASK R[0x137390] & 0x00000002 == 0x00000002  (64µs)             │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 2: VBLANK Sync & FB Pause ───────────────────────────────────────┐
│ (same VBLANK wait + FB PAUSE sequence as Script A)                      │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 3: Clock Switch & DDR3 Timing Reprogramming ─────────────────────┐
│ R[0x10f300] := 0x00001520    # MR0 DLL Reset                            │
│ WAIT 1000 ns                                                            │
│ R[0x10f300] := 0x00001420    # MR0 stable                               │
│ WAIT 1000 ns                                                            │
│ R[0x10f320] := 0x002000a0    # EMR2: CAS Write Latency for 900 MHz      │
│ WAIT 1000 ns                                                            │
│ R[0x10f300] := 0x00001e04    # MR0: CAS=7, BL=8 for 900 MHz            │
│ WAIT 1000 ns                                                            │
│ R[0x10f224] := 0x0e070c07    # Arbiter timing                           │
│                                                                         │
│ *** THE CRITICAL DDR3 TIMING REGISTERS FOR 900 MHz ***                  │
│ R[0x10f290] := 0x0e44922e    # MEM_TIMINGS_0 (tRAS/tRC)                 │
│ R[0x10f294] := 0x4ce3848c    # MEM_TIMINGS_1 (tRCD/tRP)                 │
│ R[0x10f298] := 0x440e0711    # MEM_TIMINGS_2 (tWR/tRFC)                 │
│ R[0x10f29c] := 0x000050b6    # MEM_TIMINGS_3 (tFAW)                     │
│ R[0x10f2a0] := 0x42e38069    # MEM_TIMINGS_4 (tRRD/tWTR)                │
│                                                                         │
│ R[0x10f200] := 0x00029000    # CFG0: DDR3 900 MHz active config         │
│ R[0x10f604] := 0xf1000000    # PHY calibration                          │
│ R[0x10f614] := 0x40044e77    # Output drive strength (900 MHz)          │
│ R[0x10f610] := 0x40044e77    # ODT (On-Die Termination)                 │
│ R[0x10f808] := 0x56920000    # PHY DLL config for 900 MHz               │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 4: ZQ Calibration & DLL Training ────────────────────────────────┐
│ R[0x1373f8] := 0x00002040    # Clock routing post-switch                │
│ R[0x10f870] := 0xaaaaaaaa    # ZQ calibration pattern                   │
│ R[0x100c00] := 0x04000124    # PFFB training trigger                    │
│ R[0x10f300] := 0x00001f04    # MR0 DLL reset for training               │
│ WAIT 1000 ns                                                            │
│ R[0x10f300] := 0x00001e04    # MR0 stable after training                │
│ WAIT 1000 ns                                                            │
│ WAIT 1000 ns                                                            │
│ R[0x10f830] := 0x01000011    # PHY DLL reset pulse                      │
│ R[0x10f830] := 0x00000011    # PHY DLL release                          │
│ FB RESUME                                                               │
└──────────────────────────────────────────────────────────────────────────┘
┌─ Phase 5: Post-Switch ──────────────────────────────────────────────────┐
│ R[0x100b0c] := 0x00080028    # PFFB post-switch                         │
│ R[0x611200] := 0x00003330    # Display un-stall                         │
│ R[0x10f200] := 0x00029800    # CFG0 final (900 MHz active + DLL on)     │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.3 DDR3 PHY Configuration (Host-Side, Before MEMX)

These are written directly by the host CPU **before** the MEMX script runs:

| Register | Low-Clock (324 MHz) | High-Clock (900 MHz) | Description |
|---|---|---|---|
| `0x10f050` | `0xff000450` | `0xff001050` | PFB broadcast mode control |
| `0x10f440` | `0x22f84f10` | `0x22f84f10` | DDR3 impedance calibration (constant) |
| `0x10f444` | `0x04cc001f` | `0x04cc883f` | DDR3 termination tuning |
| `0x10f468` | `0x00001005` | `0x00020020` | DDR3 data strobe timing |
| `0x10f808` | `0x08020004` | `0x08020004` | PHY DLL configuration (constant during setup) |
| `0x10f824` | `0x000279e7` | `0x00021e67` | PHY DLL feedback divider |

> **Critical Finding**: The proprietary driver uses `0x10f824 = 0x000279e7` for the
> **low-clock** state and `0x10f824 = 0x00021e67` for the **high-clock** state. The
> nouveau patch had these values but applied `0x00021e67` unconditionally for both
> mode 0 and mode 1, which is incorrect for downclocking.

---

## 4. What Nouveau Gets Wrong (Root Cause Analysis)

### 4.1 Bug #1 — PRIVRING Fault Loop (CRITICAL, causes infinite hang)

**Symptom**: `dmesg` floods with:
```
nouveau: bus: MMIO write of 00000001 FAULT at 10a580 [ PRIVRING ]
```
~33,000 faults per 5 seconds, writing to `0x10a580` hangs in a `do { } while()` loop.

**Root Cause**: Register `0x10a580` is a **PMU data segment arbitration lock** that
exists on Tesla (GT215, `card_type < NV_C0`). On Fermi (`NV_C0` / GF100+), this register
does not exist or is mapped differently. Writing to it triggers a PRIVRING bus fault,
and reading it back never returns the expected value, causing an infinite loop:

```c
// gt215.c — send path
do {
    nvkm_wr32(device, 0x10a580, 0x00000001);  // PRIVRING FAULT!
} while (nvkm_rd32(device, 0x10a580) != 0x00000001);  // NEVER TRUE → infinite loop
```

This loop is entered in **three** places:
- `gt215_pmu_send()` — acquire lock with value `0x01` (write)
- `gt215_pmu_recv()` — acquire lock with value `0x02` (read)
- `nvkm_memx_init()` — acquire lock with value `0x03` (exclusive)

And released in **three** places:
- `gt215_pmu_send()` — release lock with `0x00`
- `gt215_pmu_recv()` — release lock with `0x00`
- `nvkm_memx_fini()` — release lock with `0x00`

**Fix applied in patch**: Guard all `0x10a580` accesses with `if (device->card_type < NV_C0)`.
On Fermi, the PMU data segment access does not require this lock — the host can write to
`0x10a1c0`/`0x10a1c4` directly.

### 4.2 Bug #2 — PMU Reply Timeout (causes D-state hang)

**Symptom**: Process writing to `/sys/kernel/debug/dri/0/pstate` enters D-state
(uninterruptible sleep) and never returns.

**Root Cause**: The original `gt215_pmu_send()` used:
```c
wait_event(pmu->recv.wait, pmu->recv.process == 0);
```
This waits **indefinitely** for the PMU to fire a receive interrupt. If the PMU is stuck
executing a MEMX script (e.g., waiting for a VBLANK that never arrives on the PMU's
interrupt path, or waiting for a PLL lock that fails), the host thread hangs forever.

**Fix applied in patch**: Replace with active polling + 100ms timeout:
```c
unsigned long deadline = jiffies + msecs_to_jiffies(100);
while (pmu->recv.process != 0 && time_before(jiffies, deadline)) {
    gt215_pmu_recv(pmu);
    usleep_range(50, 100);
}
if (pmu->recv.process != 0)
    return -ETIMEDOUT;
```

### 4.3 Bug #3 — Swallowed Error Return (causes silent failures)

**Symptom**: Memory clock appears to change in pstate output but is actually stuck
at boot frequency.

**Root Cause**: In `nvkm_pstate_prog()` (`base.c`), the memory reclock result is
discarded:

```c
do {
    ret = ram->func->calc(ram, khz);
    if (ret == 0)
        ret = ram->func->prog(ram);
} while (ret > 0);
ram->func->tidy(ram);

return nvkm_cstate_prog(clk, pstate, ...);
//     ^^^ ret is overwritten — memory failure silently ignored
```

Additionally, `nvkm_memx_fini()` ignores the return value of `nvkm_pmu_send()`:
```c
nvkm_pmu_send(pmu, reply, PROC_MEMX, MEMX_MSG_EXEC, ...);
// return value not checked — -ETIMEDOUT silently swallowed
```

### 4.4 Bug #4 — Wrong DDR3 Timing Values in `ramgf100.c`

**Symptom**: Even if the MEMX script executes, DDR3 memory corruption or instability.

**Root Cause**: The original `gf100_ram_calc()` was written for **GDDR5** desktop cards.
It applies GDDR5-specific register values to DDR3 mobile GPUs:

| Register | Nouveau (GDDR5) | Proprietary (DDR3 @ 900 MHz) | Purpose |
|---|---|---|---|
| `0x10f290` | `0x0b343825` | `0x0e44922e` | Memory timing CAS/RAS |
| `0x10f294` | `0x3483028e` | `0x4ce3848c` | Memory timing tRCD/tRP |
| `0x10f298` | `0x440c0600` | `0x440e0711` | Memory timing tWR/tRFC |
| `0x10f29c` | `0x0000214c` | `0x000050b6` | Memory timing tFAW |
| `0x10f2a0` | `0x42e20069` | `0x42e38069` | Memory timing tRRD/tWTR |
| `0x10f614` | `0x60044e77` | `0x40044e77` | PHY drive strength |
| `0x10f610` | `0x60044e77` | `0x40044e77` | On-Die Termination |

The patch attempts to fix this with DDR3-specific branches, but uses **different**
values from the proprietary driver trace. See Section 6 for the correct values.

### 4.5 Bug #5 — Missing GDDR5 Training Guard

**Symptom**: GPU hangs during `gf100_ram_train()` on DDR3 hardware.

**Root Cause**: `gf100_ram_calc()` calls `gf100_ram_train()` unconditionally. This
function generates MEMX training bytecode that requires GDDR5-specific hardware
training circuits. On DDR3, these circuits don't exist, causing the PMU to hang.

**Fix applied in patch**: Skip `gf100_ram_train()` when `ram->base.type == NVKM_RAM_TYPE_DDR3`.

### 4.6 Bug #6 — Missing VBLANK Synchronization

**Symptom**: Display corruption / glitches during memory clock transitions.

**Root Cause**: The proprietary driver explicitly waits for `HEAD0_VBLANK` with a
45.478 ms timeout (about 1 frame at 120 Hz) before pausing the framebuffer. The nouveau
`gf100_ram_calc()` does **not** include any VBLANK wait in the MEMX script for DDR3.

The `ram_wait_vblank()` function exists in `ramfuc.h` but is never called from the
GF100 reclocking path — it's only used in `ramgt215.c` and `ramnv50.c`.

### 4.7 Bug #7 — Missing DDR3 Mode Register Programming

**Symptom**: DDR3 DRAM chips are not properly configured for the new frequency.

**Root Cause**: The proprietary driver performs extensive DDR3 **Mode Register** (MR)
programming during the clock transition:

```
R[0x10f300] := 0x00001520  — MR0: DLL Reset, CAS Latency
R[0x10f300] := 0x00001420  — MR0: DLL stable
R[0x10f320] := 0x002000a0  — EMR2: CAS Write Latency (900 MHz)
R[0x10f300] := 0x00001e04  — MR0: Final CAS=7, BL=8
R[0x10f324] := 0x000003cb  — EMR3: DDR3 write leveling/training
    ... (6 EMR3 writes for training calibration)
R[0x10f870] := 0xaaaaaaaa  — ZQ Calibration pattern
```

Nouveau's `gf100_ram_calc()` does **none** of this for DDR3. The DRAM chips remain
configured for the boot-time frequency, causing data corruption at higher speeds.

---

## 5. The MEMX Execution Model

### 5.1 Script Upload

```
Host CPU                         PMU Falcon µC
   │                                  │
   ├── nvkm_memx_init()               │
   │   ├── Send MEMX_MSG_INFO         │
   │   │   └── PMU replies with ──────┤ base address & size of data segment
   │   ├── Set 0x10a1c0 = base addr   │
   │   └── Begin writing commands ─────┤ via 0x10a1c4 (auto-increment)
   │                                   │
   ├── ram_wr32/ram_wait/etc.          │ (buffered, not yet executed)
   │                                   │
   ├── nvkm_memx_fini(exec=true)       │
   │   ├── Flush remaining commands    │
   │   ├── Release data segment        │
   │   └── Send MEMX_MSG_EXEC ─────────┤
   │                                   ├── PMU executes bytecode:
   │       (host waits for reply)       │   ├── WR32 commands
   │                                   │   ├── WAIT BITMASK (PLL lock)
   │                                   │   ├── DELAY (nanoseconds)
   │                                   │   ├── VBLANK wait
   │                                   │   └── FB PAUSE / RESUME
   │                                   │
   │   ◄── PMU reply (exec time) ──────┤
   └── Done                            │
```

### 5.2 Where Execution Can Hang

| Hang Point | Cause | Detection |
|---|---|---|
| `WAIT BITMASK R[0x137390]` | PLL fails to lock (wrong M/N/P coefficients) | PMU stuck in loop; host times out after 100ms |
| `WAIT STATUS HEAD0_VBLANK` | VBLANK interrupt not delivered to PMU | PMU stuck; timeout after 45ms per attempt |
| `do { wr32(0x10a580) } while()` | PRIVRING fault on Fermi | Host CPU stuck in infinite loop (Bug #1) |
| `wait_event(recv.wait)` | PMU never fires reply interrupt | Host CPU D-state forever (Bug #2) |

---

## 6. Correct DDR3 Register Values (from Proprietary Driver Trace)

### 6.1 PHY Configuration (Host-Side, Before MEMX)

| Register | 324 MHz (P7) | 900 MHz (P0) | Register Name |
|---|---|---|---|
| `0x10f050` | `0xff000450` | `0xff001050` | PFB broadcast mode |
| `0x10f440` | `0x22f84f10` | `0x22f84f10` | Impedance calibration |
| `0x10f444` | `0x04cc001f` | `0x04cc883f` | Termination tuning |
| `0x10f468` | `0x00001005` | `0x00020020` | Data strobe timing |
| `0x10f808` | `0x08020004` | `0x08020004` | PHY DLL config |
| `0x10f824` | `0x000279e7` | `0x00021e67` | PHY DLL feedback |

### 6.2 DDR3 Memory Timing Registers (Inside MEMX Script)

| Register | 324 MHz (P8 idle) | 900 MHz (P0 load) | Purpose |
|---|---|---|---|
| `0x10f290` | `0x061a3813` | `0x0e44922e` | tRAS / tRC |
| `0x10f294` | (not read in trace) | `0x4ce3848c` | tRCD / tRP |
| `0x10f298` | `0x44060411` | `0x440e0711` | tWR / tRFC |
| `0x10f29c` | `0x00001e6a` | `0x000050b6` | tFAW |
| `0x10f2a0` | `0x42e28069` | `0x42e38069` | tRRD / tWTR |
| `0x10f224` | (not read in trace) | `0x0e070c07` | Arbiter timing |

### 6.3 MEMPLL Coefficients

| Target | Register `0x132004` | M | N | P | Resulting Clock |
|---|---|---|---|---|---|
| 324 MHz | `0x00071806` | 6 | 0x18 (24) | 7 | 324 MHz |
| 900 MHz | `0x0002230b` | 0xb (11) | 0x23 (35) | 2 | 900 MHz |

### 6.4 DDR3 Mode Registers (Inside MEMX Script)

| Register | Value | DDR3 Meaning |
|---|---|---|
| `0x10f300` = `0x00001520` | MR0 | DLL Reset + CAS Latency for target freq |
| `0x10f300` = `0x00001420` | MR0 | DLL stable (after tDLLK) |
| `0x10f300` = `0x00001e04` | MR0 | CAS=7, Burst Length=8 (900 MHz) |
| `0x10f320` = `0x002000a0` | EMR2 | CAS Write Latency for 900 MHz |
| `0x10f324` = `0x000003cb/06cb/01cb/03ca/06ca/01ca` | EMR3 | Write leveling training |

### 6.5 PHY Drive Strength & DLL (Inside MEMX Script)

| Register | 324 MHz | 900 MHz | Purpose |
|---|---|---|---|
| `0x10f614` | `0x40044f77` | `0x40044e77` | Output drive strength |
| `0x10f610` | `0x40044f77` | `0x40044e77` | On-Die Termination |
| `0x10f808` | `0x48020004` | `0x56920000` | PHY DLL (inside MEMX, differs from host-side!) |
| `0x10f824` | `0x00021867` | (set before MEMX) | PHY DLL feedback (inside MEMX) |
| `0x10f830` | `0x01000017` → `0x00000017` | `0x01000011` → `0x00000011` | DLL reset pulse |
| `0x10f604` | `0xf0000000` | `0xf1000000` | PHY calibration |
| `0x10f874` | `0x04000000` | `0x00000000` | PHY unknown (zeroed during upclock) |
| `0x10f914` | `0x00000000` | `0x00002000` | PHY unknown (set during upclock) |
| `0x10f200` | `0x00028800` | `0x00029800` | CFG0 (boot idle → 900 MHz active) |
| `0x10f300` | `0x00001420` | `0x00001e04` | MR0 (boot idle → 900 MHz CAS=7) |
| `0x10f320` | `0x00200080` | `0x002000a0` | EMR2 (boot idle → 900 MHz CWL) |

> **Important**: The proprietary driver uses **different** `0x10f808` values inside the
> MEMX script (`0x48020004` / `0x56920000`) vs. the host-side pre-setup (`0x08020004`).
> Nouveau's patch uses `0x08020004` in both paths, which may be incorrect for the
> MEMX-internal PHY reconfiguration.

---

## 7. Reverse Engineering Completeness Assessment

### 7.1 What Is Complete

| Area | Coverage | Source |
|---|---|---|
| MEMPLL M/N/P coefficients | ✅ Complete | mmiotrace (`0x132004`) |
| REFPLL lock sequence | ✅ Complete | MEMX script (`0x137390` wait) |
| DDR3 timing registers (P0) | ✅ Complete | MEMX script (`0x10f290–0x10f2a0`) |
| PHY DLL values (host-side) | ✅ Complete | MMIO writes (`0x10f824`, `0x10f050`) |
| VBLANK synchronization | ✅ Complete | MEMX script (`HEAD0_VBLANK` wait) |
| FB PAUSE/RESUME protocol | ✅ Complete | MEMX script |
| Display stall/unstall | ✅ Complete | `0x611200` = `0x3300` → `0x3330` |
| DDR3 Mode Register programming | ✅ Complete | MEMX script (`0x10f300`, `0x10f320`, `0x10f324`) |
| ZQ Calibration pattern | ✅ Complete | `0x10f870` = `0xaaaaaaaa` |
| PFFB pre/post switch | ✅ Complete | `0x100b0c` = `0x00080012` → `0x00080028` |

### 7.2 What Is Incomplete / Uncertain

| Area | Status | Gap |
|---|---|---|
| DDR3 timing `0x10f294` at 324 MHz | ⚠️ Missing | Not read by proprietary driver in trace; may need to be derived from JEDEC DDR3-1333 spec |
| DDR3 timing `0x10f224` at 324 MHz | ⚠️ Missing | Arbiter timing not read at idle; may be unchanged or set by VBIOS |
| PCLOCK routing registers | ⚠️ Partial | `0x137370`/`0x137380`/`0x137360` writes are captured but their exact bitfield meanings are undocumented |
| `0x10f660` (drive strength idle) | ⚠️ Missing | `0x00001010` seen during downclocking; never read at idle in trace |
| `0x13d8b4` (PXBAR) | ❓ Unknown | Written to `0x00000000` repeatedly; appears to be a synchronization barrier |
| EMR3 training sequence meaning | ⚠️ Partial | The 6 writes to `0x10f324` appear to be DDR3 write leveling but the exact purpose of each value is unclear |
| Voltage scaling during transitions | ❌ Not captured | Voltage changes (820 mV → 1030 mV) are likely handled by a separate I²C/GPIO path not visible in mmiotrace |

> **Note**: Previously many values were listed as "unknown" but have since been extracted
> from `MMIO32 R` (register read) entries in the mmiotrace. The proprietary driver reads
> registers before modifying them, giving us the idle-state baseline. The remaining gaps
> are registers that were **never read** in the captured trace.

### 7.3 Gaps in the Sniffing Scripts

The `sniff_memory_reclock.py` script reads BAR0 via `mmap`, which captures only the
**final state** of registers after the proprietary driver has finished a reclock. It
does **not** capture the intermediate states or the **sequence** of writes. Only
`mmiotrace` (`nvidia_full_reclock_trace.txt`) captures the full write ordering, which
is critical because DDR3 memory reclocking is deeply order-dependent.

The `regs_p8_idle.txt` file in the testing directory is essentially empty (only contains
a header line), suggesting the `sniff_memory_reclock.sh` script using `nvapeek` was
run but may have failed (possibly because `nvapeek` requires `envytools` to be installed).

---

## 8. Recommended Fix Strategy

### Phase 1: Make Reclocking Non-Destructive (Prerequisite)

1. **Propagate errors** from `nvkm_pmu_send()` through `nvkm_memx_fini()` and up to
   `nvkm_pstate_prog()`. Currently `-ETIMEDOUT` is silently swallowed.
2. **Add diagnostic logging** at each stage of `gf100_ram_calc()` to identify exactly
   where the BIOS lookup / PLL calculation / MEMX generation fails.

### Phase 2: Fix the DDR3 MEMX Script

The MEMX script generated by `gf100_ram_calc()` must match the proprietary driver's
sequence. Key changes needed:

1. **Add VBLANK wait** before FB PAUSE (use `ram_wait_vblank()` from `ramfuc.h`).
2. **Add DDR3 Mode Register programming** (`0x10f300`, `0x10f320`, `0x10f324`).
3. **Use correct timing values** from Section 6.2 instead of hardcoded GDDR5 values.
4. **Add ZQ calibration** (`0x10f870 = 0xaaaaaaaa`).
5. **Add EMR3 training sequence** for DDR3 write leveling.
6. **Use correct PHY DLL values** inside the MEMX script (different from host-side values).

### Phase 3: Validate with Diagnostic Tracing

1. Boot with `nouveau.debug=debug`.
2. Trigger reclock: `echo 0f > /sys/kernel/debug/dri/0/pstate`.
3. Capture `dmesg` to verify the MEMX script contents.
4. Compare the generated script against the proprietary driver's script from Section 3.

### Phase 4: Missing Data Collection

To fill the remaining gaps, run `sniff_memory_reclock.py` under the **proprietary**
driver to capture the full register state at P8 idle. This requires:

```bash
# Under proprietary NVIDIA 390.157 driver:
# 1. Boot to idle (no 3D apps) — GPU will be at P8/324 MHz
sudo python3 testing/sniff_memory_reclock.py
# This captures both P8 (idle) and P0 (glxgears load) register snapshots
```

---

## 9. Patch Status & File Inventory

### 9.1 Modified Driver Files

| File | Changes | Status |
|---|---|---|
| `nouveau_backlight.c` | Force `nv_backlight` registration, bypass ACPI check | ✅ Working |
| `nvkm/subdev/clk/base.c` | Gate memory reclock behind `NvFermiMemReclock`, add error logging | ✅ Working |
| `nvkm/subdev/clk/gf100.c` | Fix clock domain table (remove invalid `dom6`), add `NVKM_CLK_DOM_FLAG_CORE` | ✅ Working |
| `nvkm/subdev/fb/ramgf100.c` | DDR3 timing branches, skip GDDR5 training, add `0x10f440/444/468` | ⚠️ Partially correct (values don't match trace) |
| `nvkm/subdev/pmu/gt215.c` | Guard PRIVRING `0x10a580`, replace `wait_event` with polling+timeout | ✅ Correct |
| `nvkm/subdev/pmu/memx.c` | Guard PRIVRING `0x10a580` in `memx_init`/`memx_fini` | ✅ Correct |

### 9.2 Testing & Reverse Engineering Files

| File | Purpose | Size |
|---|---|---|
| `testing/nvidia_full_reclock_trace.txt` | Full demmio-decoded mmiotrace of proprietary driver | 24 MB |
| `testing/nvidia_reclock_full.raw` | Raw mmiotrace binary capture | 28 MB |
| `testing/gpu_vbios_perf.txt` | `nvbios` dump of VBIOS performance tables | 70 KB |
| `testing/full_vbios.rom` / `gpu_vbios.rom` | Raw VBIOS ROM dumps | 56 KB each |
| `testing/nouveau_boot.log` | Nouveau boot log with pstate enumeration | 11 KB |
| `testing/sniff_memory_reclock.py` | BAR0 mmap register snapshot tool (P8 vs P0 diff) | 6 KB |
| `testing/sniff_memory_reclock.sh` | Shell-based nvapeek register capture + mmiotrace | 3 KB |
| `testing/sniff_reclock.sh` | Simplified reclock sniffing script | 1 KB |
| `testing/run_mmiotrace.sh` | mmiotrace capture automation | 2 KB |
| `testing/trace_driver_reload.sh` | Driver reload with tracing | 3 KB |

---

## 10. References

- [envytools hwdoc — GF100 memory](https://envytools.readthedocs.io/en/latest/hw/memory/gf100-pfb.html)
- [envytools hwdoc — Fermi PCLOCK](https://envytools.readthedocs.io/en/latest/hw/pm/gf100-clock.html)
- [nouveau wiki — PM / Reclocking](https://nouveau.freedesktop.org/PowerManagement.html)
- [JEDEC DDR3 SDRAM Standard (JESD79-3F)](https://www.jedec.org/standards-documents/docs/jesd-79-3d)

---

*Document generated from reverse engineering analysis of Dell XPS L702X / GT 555M (GF106M, DDR3)*
*Last updated: 2026-08-27*
