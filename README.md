# nouveau-fermi-reclock-dkms

Out-of-tree **Nouveau DKMS kernel module** with **Fermi (GF100–GF119)** core, shader, and voltage reclocking support, bundled with a load-aware dynamic GPU frequency governor and backlight synchronization daemon.

> [!WARNING]
> **EXPERIMENTAL SOFTWARE DISCLAIMER**
> This driver and dynamic clock governor are **experimental** and have been tested and verified specifically on a **Dell XPS L702X (GeForce GT 555M / GF106M, 3072 MB DDR3, 120Hz display)** running Linux. 
> Behavior on different hardware models, memory configurations (e.g. GDDR5 vs DDR3), or GPU variants may vary. Use at your own risk.

---

## Features

- **Fermi GPU Core & Shader Reclocking (GF100 / GF104 / GF106 / GF108 / GF110 / GF114 / GF116 / GF119)**:
  - Unlocks full core clock scaling from low-power idle `07` (e.g. 202 MHz) up to maximum performance `0f` (590+ MHz).
  - Enables full hardware 3D acceleration (achieving 1600+ FPS in `glxgears` on GeForce GT 555M).
- **Intelligent Dynamic Frequency Governor (`nouveau-dynclockd`)**:
  - Automatically manages GPU pstates (`07` $\leftrightarrow$ `0f`).
  - Hybrid activity tracking: Instant performance boost on dedicated 3D workloads + load-aware tick sampling for WebGL/browser canvas, keeping idle desktop usage cool and efficient at `07`.
- **Hardware Backlight Synchronization**:
  - Automatically bridges ACPI video and platform backlight nodes (`acpi_video0` / `dell_backlight`) to NVIDIA panel PWM (`nv_backlight`) at 100ms intervals.
- **DKMS Integration**:
  - Automatically rebuilds and installs across kernel upgrades.

---

## Hardware Configuration Tested

- **Laptop**: Dell XPS L702X
- **GPU**: NVIDIA GeForce GT 555M (Fermi / GF106M, Device ID `10de:0dcd`)
- **VRAM**: 3072 MB DDR3 (192-bit bus)
- **Display**: 1920x1080 @ 120Hz Internal Panel
- **Kernel Tested**: Linux 6.18 LTS (`linux-cachyos-lts` / Arch Linux)

---

## Installation

### Arch Linux / CachyOS / Manjaro (via AUR)

```bash
# Using yay
yay -S nouveau-fermi-reclock-dkms

# Or manual build
git clone https://aur.archlinux.org/nouveau-fermi-reclock-dkms.git
cd nouveau-fermi-reclock-dkms
makepkg -si
```

### Enable the Dynamic Clock Governor

```bash
sudo systemctl enable --now nouveau-dynclockd.service
```

---

## Recommended Kernel Parameters

Add the following options to your bootloader configuration (e.g. `/etc/default/grub`):

```text
nouveau.modeset=1 acpi_backlight=native video.allow_duplicates=1
```

After updating GRUB, rebuild the bootloader config:
```bash
sudo update-grub  # or sudo grub-mkconfig -o /boot/grub/grub.cfg
```

---

## Module Options

The driver supports experimental tuning options via `/etc/modprobe.d/nouveau.conf`:

```text
options nouveau modeset=1 vblank_continuous=1 config="NvFermiDispReclock=1"
```

- **`vblank_continuous`** (default: `0`): Keeps hardware VBlank interrupts running continuously to support high-refresh (120Hz) frame pacing.
- **`NvFermiDispReclock`** (default: `0`): Scales internal Fermi display hub clocks (`hubk07`/`hubk06`/`hubk01`) to 405 MHz during performance states for 120Hz pixel throughput.
- **`NvFermiMemReclock`** (default: `0`): Experimental DDR3 memory frequency scaling.

---

## Repository Contents

- `PKGBUILD`: Arch Linux / AUR package specification.
- `.SRCINFO`: AUR metadata.
- `dkms.conf`: DKMS module build and installation rules.
- `nouveau-fermi-reclock.patch`: Unified reclocking, display clocking, and backlight patch against upstream Nouveau.
- `nouveau-dynclockd.py`: Dynamic frequency scaling daemon with WebGL load awareness.
- `nouveau-dynclockd.service`: Systemd service unit for the clocking daemon.
- `RECLOCKING_NOTES.md`: Comprehensive DDR3 memory reclocking, display architecture, and reverse engineering notes.

---

## License

- Nouveau Kernel Module: `GPL-2.0-only`
- Daemon & Helper Scripts: `MIT`\n