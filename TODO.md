# 📋 Roadmap & TODO

This document tracks planned features, architectural improvements, and pending tasks for the **Nouveau Fermi Reclocking & 120Hz Driver** project.

---

## 🎯 Short-Term Tasks (Next Release)

- [ ] **Expose Shader Clock in DebugFS (`/sys/kernel/debug/dri/*/pstate`)**:
  - Update `gf100_clk_domains[]` in `nvkm/subdev/clk/gf100.c` to provide a display name (`"shader"`) for `nv_clk_src_shader`.
  - Enables explicit reporting of the $2\times$ hot clock (e.g., `core 590 MHz shader 1180 MHz memory 900 MHz`).

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

- [ ] **VRAM DDR3 Reclocking Stability**:
  - Implement PMU Falcon microcode VBlank blanking synchronization for `fb/ramgf100.c` DDR3 MEMX sequences.
  - Safely enable 900 MHz (1800 MT/s) memory reclocking without display jitter.

- [ ] **Community Hardware Telemetry Processing**:
  - Review submitted GitHub Issues from `tools/nouveau-fermi-diag.py`.
  - Validate support across GF100, GF104, GF108, GF110, and GF119 chipsets.

- [ ] **Nouveau Vulkan (NVK / Mesa NVC0) Tracking**:
  - Monitor upstream Mesa NVK / Zink progress for Fermi hardware capabilities.
