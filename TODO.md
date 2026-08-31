# 📋 Roadmap & TODO

This document tracks planned features, architectural improvements, and pending tasks for the **Nouveau Fermi Reclocking & 120Hz Driver** project.

---

## 🎯 Short-Term Tasks (Next Release)

- [x] **Expose Shader Clock in DebugFS (`/sys/kernel/debug/dri/*/pstate`)** _(local only, not upstream)_:
  - Updated `gf100_clk_domains[]` in `nvkm/subdev/clk/gf100.c` to provide display name (`"shader"`) for `nv_clk_src_shader` via Python in `PKGBUILD` (safer than `sed` on 2-line `gpc` entry).
  - Now reports `core 590 MHz shader 1180 MHz memory 900 MHz` (needs `reboot` to load `1.0.2` `DKMS` — currently `pstate` still `core`/`memory` only).
- [x] **Voltage Table Fix — `0f` undervolted (870mV vs factory 1030mV)** _(root cause of OC freeze)_:
  - `nvkm_volt_map` (VMAP speedo formula) mapped the `0f` voltage ID `0x01` → `862.5mV` → VID `0x04` (870mV), never requesting VID `0x01` (1030mV) that the volt table lists. Hardware *does* reach 1030mV (`VOLT MAP: req=1030000uv -> vid=0x01 ret=0`, `in0_input`=1030).
  - Fix (in `nvkm_pstate_new`): `if (pstate->pstate == 0x0f) cstate->voltage = 0x67;` → `nvkm_volt_map` fallback `id*10000` = 1030000µV. Hack (relies on the fallback); clean fix = make volt table authoritative over VMAP.
  - Volt table (verified via dump): `vid_nr=4 vid_mask=0x07` — VID `0x05`=820, `0x04`=870, `0x03`=920, `0x01`=1030 mV.
- [x] **Custom OC P-State — re-added, gated by `NvFermiOC` module option (default OFF):**
  - Synthetic `0x10` pstate (`core 700 shader 1400`, memory 900 inherited, voltage 1030mV via the fix above). Enable with `options nouveau config=NvFermiOC=true`; select via `nouveau-ctrl set 10`.
  - Notes: memory `1000 MHz` hangs (no MEMX timings) → capped at 900; Fermi core via `nv_clk_src_gpc` (`mdiv 2000`); 7× gap is ~90% Gallium driver overhead, OC is only ~+18%.
- [ ] **Hardware Quirk / Profile Table (`quirks.h`)**:
  - Implement `struct fermi_device_profile` table matching Subsystem Vendor/Device IDs.
  - Automatically apply per-card rules for high-refresh eDP displays (120Hz/144Hz), display hub clock locking, and maximum stable P-states as community hardware reports arrive via `tools/nouveau-fermi-diag.py`.

---

## 🛠️ CLI Management Utility (`nouveau-ctrl` / `nouveau-smi`)

- [ ] **Build a Standalone CLI / TUI Management Tool**:
  - Provide an intuitive alternative to `nvidia-smi` and `nvidia-settings` for Nouveau Fermi users.
  - **Features**:
    - `nouveau-ctrl status`: Display real-time Core, Shader, and Memory clocks, temperature, voltage, fan RPM, and active DRM client processes.
    - `nouveau-ctrl set <state>`: Lock GPU to a specific P-State (`03`, `07`, `0f`) or return to automatic daemon control.
    - `nouveau-ctrl daemon [start|stop|status]`: Control the `nouveau-dynclockd` background governor.
    - `nouveau-ctrl fan <rpm|percentage>`: Set target fan speeds via `dell_smm_hwmon` / ACPI.
    - `nouveau-ctrl watch`: Live top-like monitor for GPU clock scaling and VRAM utilization.

---

## 🔬 Long-Term Research & Driver Enhancements

- [ ] **DC (Battery) Performance Limit — cap at P8 `07` (202 MHz)** _(after mmiotrace/voltage work)_:
  - Proprietary `390.157` behavior: AC + 3D load → `590/1180/900` @ `1.030V`; battery (DC) → limits to P8 `202 MHz` (conserves power).
  - nouveau already has `ustate_ac`/`ustate_dc`; set `NvClkModeDC=07` (or wire `nouveau-dynclockd` to drop to `07` on DC) so on battery the clock caps at `07` (202/404/324).
  - Confirm via `cat /sys/class/power_supply/*/online` → `clk->pwrsrc` selects `ustate_dc`.
- [ ] **VRAM DDR3 Reclocking Stability**:
  - Implement PMU Falcon microcode VBlank blanking synchronization for `fb/ramgf100.c` DDR3 MEMX sequences.
  - Safely enable 900 MHz (1800 MT/s) memory reclocking without display jitter.

- [ ] **Community Hardware Telemetry Processing**:
  - Review submitted GitHub Issues from `tools/nouveau-fermi-diag.py`.
  - Validate support across GF100, GF104, GF108, GF110, and GF119 chipsets.

- [ ] **Nouveau Vulkan (NVK / Mesa NVC0) Tracking**:
  - Monitor upstream Mesa NVK / Zink progress for Fermi hardware capabilities.
