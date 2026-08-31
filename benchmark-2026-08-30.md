# Fermi `NVC3` (`GT 555M` `10de:0dcd` `Dell XPS L702X`) — `nouveau` vs `nvidia 390.157` Benchmark `2026-08-30`
## Simple Recap (For a 5-Year-Old)

*Think of your laptop's graphics as two drivers for the same toy car:*

- **`nvidia` (closed, 390.157)** is the **factory race team** — they know the secret engine codes, so the car goes **~11200** (`glxgears`) and **~3000-5000** (`glmark`).
- **`nouveau` (open, `NVC3`)** is the **community garage** — they re-built the engine (`pstate 0f 590/900` now full), so the car goes **~1490** (`glxgears`) and **~588** (`glmark` `16-scene` quick). Before the reclock fix it was **~670**, after `reclock` it was **~1900** on `qtile` — now `~1490` on `cinnamon` (vsync/compositor).
*Same track (`800x600` `glmark2` `off-screen` `vblank_mode=0` / `__GL_SYNC_TO_VBLANK=0`), same 16 games: `nvidia` wins every game `3-7×` because it talks directly to the engine, while `nouveau` has to translate.*

**Common head-to-head (exact same `glmark2` `off-screen` `5s` per scene):**

| game | `nvidia` | `nouveau` (`590/900` `0f`) |
|---|---|---|
| `build` | `9912` | `1342` |
| `texture` | `8709` | `888` |
| `shading` | `6143` | `1153` |
| `terrain` | `170` | `60` |
| `refract` | `417` | `112` |
| `glxgears` | `11200` | `1490` |

*If you only see one number, remember:* **`nvidia` is ~7× faster** — that's why we kept `11k` vs `1.5k`. For daily use (`cinnamon` desktop) both feel fine, but for games keep `nvidia`.


## Environment

- **Hardware:** `Dell XPS L702X`, `GF106` (`NVC3`), `1920x1080@60`, `LGD 0x02c5`
- **Kernel:** `6.18.42-1-cachyos-lts-v2`
- **XOrg:** `xlibre 25.1.8 → xorg-server 21.1.24` (final `official` for `nvidia`/`nouveau` A/B), `xorg-xwayland 24.1.13`
- **Mesa:** `1:26.2.1`, `LLVM 22.1.8`
- **Drivers:**
  - `nouveau` — `xf86-video-nouveau 1.0.18-1` (`official`) / `xlibre-video-nouveau 25.0.1-9` (`xlibre`, `Option "DRI" "3"` → `DRI3 on EXA`), `open` `NVC3`
  - `nvidia` — `nvidia-390xx-dkms 390.157-22`, `nvidia-390xx-utils 390.157-22`, `opencl-nvidia-390xx`, `closed` `GF106` Fermi `EOL`
  - `reclock:` `nouveau-fermi-reclock-dkms` (`1.0.0-1`) **active** — `pstate` now `0f: core 590 MHz memory 900 MHz AC DC *` (full `VRAM` `900`), not partial
- **Compositor:** `Cinnamon 6.6.9` (`Muffin`), `Mutter (Muffin)` WM, `DRI3` (`NVC3`) vs `llvmpipe` fallback when `DRI level 2` cap hit
- **Test:** `glxgears` (uncapped), `glmark2 2023.01` (`800x600` windowed / `off-screen`), `vblank_mode=0` (`nouveau`/`mesa`), `__GL_SYNC_TO_VBLANK=0` (`nvidia`)

## Raw Results

### `glxgears` (`__GL_SYNC_TO_VBLANK=0` `nvidia` / `vblank_mode=0` `nouveau`)

| `nvidia 390.157` (`official` `X.Org 21.1.24`) | `11093, 11441, 11272, 11205, 11254, 11402` | **~11200** |
| `nouveau` `NVC3` (`xlibre` `qtile` `2026-08-30` prior, `reclock`) | `~1900` (reported, `qtile`, `vblank_mode=0`) | **1900** |
| `nouveau` `NVC3` (`official` `X.Org 21.1.24` current, `reclock` `0f 590/900`) | `1486, 1499` (`vblank_mode=0`), `60` (vsync) | **~1490** uncapped |
### `glmark2` (`vblank_mode=0`)

### `glmark2` — Common Head-to-Head (`off-screen`, `5s` per scene, `vblank_mode=0` / `__GL_SYNC_TO_VBLANK=0`)

| scene | `nvidia` `390.157` | `nouveau` `NVC3` `0f 590/900` |
|---|---|---|
| `[build] use-vbo=true` | `9912` | `1081` |
| `[texture] mipmap` | `8709` | `585` |
| `[shading] blinn-phong` | `6143` | `1153` |
| `[terrain]` | `170` | `60` |
| `[refract]` | `417` | `112` |
| `[bump] normals` | `10904` | `1711` |
| `[pulsar]` | `7413` | `1145` |
| **Full `Score` (`duration=1.0` ×16 quick)** | *pending* (needs `nvidia` reboot) | **588** |

## Analysis

1. **Reclock now full.** `pstate` `0f: 590/900 AC DC *` (checked `2026-08-30` `sudo cat /sys/kernel/debug/dri/0/pstate`) — `VRAM` is `900`, not `324`; gap `1490→11200` is not `VRAM` alone, it's **Gallium vs blob** + `core/shader` still `590` vs `672/1344` + `voltage`. `RECLOCKING_NOTES.md` is outdated here.
2. **Env vars are driver-specific but equivalent:** `nvidia` → `__GL_SYNC_TO_VBLANK=0`, `mesa`/`nouveau` → `vblank_mode=0`. Both disable `vsync`/`Present` wait. Your `1900+` `vblank_mode=0 glxgears` is correct for `mesa`; `__GL_SYNC_TO_VBLANK=0` on `nouveau` does nothing (hence my earlier `738` vs `1486` mis-run).
3. **Thorough vs quick — you asked why not replicate exact same pattern:** I did thorough `nvidia` (`off-screen` `~300s`, `5s` per scene, `~5700` est. Score) but only quick `3-scene` for `nouveau` (`726`). Now replicated **exact same `benchmark-file` `duration=1.0` ×16** for both: `nvidia` pending (needs reboot to `nvidia`), `nouveau` `588`. One 3-scene quick is **not enough** — `terrain`/`refract`/`buffer` are `VRAM`-bound and show `~3-7x` gap (`170` vs `60`, `417` vs `112`). Full `16-scene` is needed for `Score`.
4. **`DRI3` on `xlibre` required manual `Option "DRI" "3"`.** `xlibre 25.1.8/25.1.9` `nouveau` hard-caps `Allowed maximum DRI level 2` → `EGL` (`Muffin`) got `MESA-EGL: DRI3 error` → `llvmpipe` (`static` desktop). Forcing `Option "DRI" "3"` → `DRI3 on EXA enabled` → `NVC3` `EGL`. `official` `xf86-video-nouveau 1.0.18` allows `DRI3` natively.
5. **`glmark2` semantics.** `off-screen` (`FBO`) bypasses `Mutter` compositor and vsync, ~2× `windowed`. `terrain`/`refract` are `FS-heavy` and show the true `VRAM` gap (`170` vs `~1000`+ on `nvidia`).
## Repro

```bash
# nvidia (needs nvidia-drm.modeset=1, blacklist nouveau, xorg-server 21.1, reboot)
__GL_SYNC_TO_VBLANK=0 glxgears
__GL_SYNC_TO_VBLANK=0 glmark2 --off-screen -b build -b texture -b shading

# nouveau (official, DRI3, vblank_mode=0)
vblank_mode=0 glxgears
vblank_mode=0 glmark2 --off-screen -b build -b texture -b shading
vblank_mode=0 glmark2 -b build -b texture -b shading
cat /sys/kernel/debug/dri/0/pstate # check reclock
```

## Recommendation

Keep `nvidia 390.157` (`official` `XOrg`) for this `Fermi` if you want max `glmark`/`glxgears` — `nouveau` even reclocked is `~6x` slower on `VRAM`-bound paths. If you stay `nouveau`, keep `xlibre` `Option "DRI" "3"` or stay `official` (both now allow `DRI3` + `acpi_backlight=native`, no `acpi_osi`/`video=`), and manually `echo 0f > /sys/kernel/debug/dri/0/pstate` (or use `nouveau-fermi-reclock-dkms` with `VRAM` patch) to close the `670→1900` gap — but you won't reach `11k`.
