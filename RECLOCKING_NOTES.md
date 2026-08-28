# Nouveau & Nvidia Proprietary Reclocking Notes

This document provides a detailed summary of the graphics driver reclocking experiments, configurations, and performance optimization steps performed on the **Dell XPS L702X** laptop equipped with an **NVIDIA GeForce GT 555M** (Fermi / GF106) GPU under the **CachyOS LTS Kernel (6.18+)**.

---

## Part 1: Open-Source Nouveau Reclocking Experiment

### 1. Goal
The open-source `nouveau` driver does not support automatic reclocking on Fermi GPUs out-of-the-box, meaning the GPU is locked to its boot-time low-power state (typically state `08`), severely bottlenecking performance. The goal was to patch `nouveau` to support core reclocking and evaluate memory reclocking.

### 2. Custom Nouveau DKMS Patching
We modified the kernel driver code to support Fermi clock state transitions and packaged it as a custom DKMS package (`nouveau-fermi-reclock-dkms`). 

Key enhancements implemented in the patch:
*   Added a custom module option: **`NvFermiMemReclock`** (boolean, default: `0`).
*   Implemented a safe switch to enable core clock reclocking while keeping memory reclocking toggleable.

### 3. Key Findings on Nouveau Reclocking
*   **Memory Reclocking Lockups (`NvFermiMemReclock=1`):** Enabling memory reclocking caused immediate PMU (Power Management Unit) deadlocks and system freezes during transitions to higher performance states (e.g. from `08` to `0f`).
*   **Core Reclocking Success (`NvFermiMemReclock=0`):** Keeping memory reclocking disabled but allowing core reclocking to transition to state `0f` (590 MHz core clock) was completely stable.
*   **Nouveau Performance:** Core-only reclocking improved `glxgears` frame rates from standard boot-time levels up to **~2,700 FPS**.
*   **Nouveau Dynamic Clock Daemon (`nouveau-dynclockd.py`):** We created a user-space daemon to dynamically scale the GPU power state (`pstate`) between `08` (idle) and `0f` (active 3D load) by reading `/sys/kernel/debug/dri/0/pstate` based on GPU activity.

---

## Part 2: Proprietary NVIDIA Driver Setup & Troubleshooting

For maximum performance, we moved from Nouveau to the legacy proprietary **NVIDIA 390.157** driver.

### 1. Blacklisting Nouveau
To load the proprietary driver, we disabled the Nouveau module via `/etc/modprobe.d/nouveau.conf`:
```text
blacklist nouveau
options nouveau modeset=0
```
We also renamed `/etc/modprobe.d/nvidia.conf` to `nvidia.conf.disabled` to allow the Nvidia drivers to load.

### 2. Resolving the 640x480 Resolution Fallback
After loading the proprietary driver, X11 started in a fallback 640x480 resolution.
*   **Cause:** Because `nvidia_drm.modeset=1` was not active, Xorg did not associate the display with `nvidia-drm`. It fell back to the UEFI/EFI framebuffer (`simple-framebuffer` via `/dev/dri/card0`) using the generic `modesetting` driver, which was locked at boot resolution.
*   **Fix:** We created `/etc/X11/xorg.conf.d/20-nvidia.conf` to force Xorg to bind directly to the `nvidia` driver and search the Nvidia-specific GLX path first:
    ```xorg
    Section "Files"
        ModulePath "/usr/lib/nvidia/xorg"
        ModulePath "/usr/lib/xorg/modules"
    EndSection

    Section "Device"
        Identifier     "Device0"
        Driver         "nvidia"
        VendorName     "NVIDIA Corporation"
    EndSection
    ```
    This successfully restored the native panel resolution of **1920x1080 @ 120Hz** (DP-1) and configured external HDMI-0.

---

## Part 3: XLibre (X11 Fork) Installation & Optimization

To further optimize X11 performance, we experimented with **XLibre**, a community-driven fork of the X.Org Server focused on cleaning up legacy code and reducing CPU overhead.

### 1. Solving the `TimerForce` Symbol Crash
When using the stable version of `xlibre-xserver` (`25.0.0.22`), the X server crashed on boot with:
```text
(EE) Failed to load .../nvidia_drv.so: undefined symbol: TimerForce
```
*   **Cause:** The legacy Nvidia 390.157 driver calls Xorg's internal `TimerForce` function, which stable XLibre did not export (documented on [X11Libre Issue #311](https://github.com/X11Libre/xserver/issues/311)).
*   **Fix:** Upgrading to `xlibre-xserver-beta` (which contains [PR #629](https://github.com/X11Libre/xserver/pull/629) to explicitly re-export the `TimerForce` function) resolved the crash.

### 2. VSync and Performance Comparison
*   On the proprietary Nvidia driver, VSync is bypassed using the environment variable **`__GL_SYNC_TO_VBLANK=0`** (rather than Mesa's `vblank_mode=0`).
*   **glxgears Performance Comparison:**
    *   **Nouveau (reclocked to `0f`):** ~2,700 FPS
    *   **Proprietary Nvidia on Standard Xorg:** ~11,850 FPS
    *   **Proprietary Nvidia on XLibre:** **~12,750+ FPS** (~900–1000 FPS improvement due to XLibre's reduced X11 main-loop overhead).

---

## Part 4: Cleanup & Current State

*   **Custom Nouveau Module:** Cleanly uninstalled from DKMS and system packages via `pacman -Rns nouveau-fermi-reclock-dkms`.
*   **Active Driver:** Running proprietary Nvidia 390.157 stably on **XLibre-Beta** at 1920x1080 @ 120Hz.
*   **Future Transition Plan:** If KDE Plasma drops X11 entirely in the future (making Wayland mandatory, which the legacy Nvidia driver cannot support), fallback options include migrating to **Cinnamon** or **SonicDE** (a community fork of KDE Plasma dedicated to preserving X11 support).
