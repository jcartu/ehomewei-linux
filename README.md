# ehomewei-linux — full brightness, HDR & color control for EHOMEWEI portable monitors on Linux

**Unlock the "Windows-only" extra brightness, enable HDR mode, and fix washed-out / tinted output on EHOMEWEI portable monitors — no Windows, no vendor app, no firmware flashing. Everything re-applies itself on every plug-in.**

Verified on: **EHOMEWEI RO9 Pro** (16" 3200×2000 120 Hz, Realtek/RTK scaler, firmware `e0.10.05`, mfg 2025-W34, reported as `RTK / "Monitor"` in EDID). The vendor's Windows/macOS "EHOMEWEI DisPlay" app talks to these monitors over USB HID — this repo contains that protocol, reverse-engineered, plus ready-made Linux tooling.

Also applies to other RTK-scaler EHOMEWEI models that expose the same control HID (`056a:8191`, `1a2c:2d23`, `05ac:0265`) — the vendor app supports them all through one code path.

---

## What this fixes

| Symptom | Root cause | Fix |
|---|---|---|
| Panel dimmer than it was on Windows; vendor app's brightness switch "only works on Windows" | Backlight is capped unless the host sends a vendor HID **brightness unlock** (`02 0F 01`) + **UltraHDR page-4 switch** (`02 EF 04 01 01`) | `ehwctl.py` / auto-apply service |
| HDR unavailable in KDE/GNOME ("incapable") | Scaler ships with HDR mode disabled → no HDR static-metadata block in EDID | DDC/CI factory reset (`setvcp 04 1`) restores the HDR EDID block, then enable HDR in your desktop |
| One screen washed out / faded | KDE KScreen per-connector override forcing RGB range `Full`, or monitor stuck in a user color preset with contrast 100 | `kscreen-doctor output.X.rgbrange.automatic` (+ delete stale overrides), DDC color preset 6500 K |
| Two identical monitors, one bluer/more saturated than the other | Plasma per-display **SDR gamut wideness** differs (100% vs 0%) | `kscreen-doctor output.X.sdrGamut.0` |
| Monitor USB hub flapping / disconnecting every few minutes | Bus-power brownout + the Linux `wacom` driver crash-looping on the vendor-cloned `056a:8191` HID (empty report descriptors) | Power the monitor properly; the enforcer detaches/rebinds safely per run |

## Quick start

```bash
# deps
sudo pacman -S python-pyusb ddcutil      # Arch; equivalent elsewhere
# (Debian/Ubuntu: sudo apt install python3-usb ddcutil)

# interactive tool — discover, query, and command the monitors
sudo ./ehwctl.py list
sudo ./ehwctl.py info          # -> 01 04 "EHOMEWEI" <serial> <fw> "RO9 Pro"
sudo ./ehwctl.py menu-type
sudo ./ehwctl.py menu 4        # UltraHDR page state

# one-time per monitor: enable the scaler's HDR EDID block
ddcutil setvcp 04 1            # factory reset (also restores HDR EDID)
ddcutil setvcp 10 100          # brightness max
ddcutil setvcp 12 50           # contrast
ddcutil setvcp 14 5            # 6500 K preset

# make it stick forever (unlock + boost on every boot/plug-in)
sudo ./deploy/install.sh
```

KDE Plasma users — align both displays (substitute your output names):

```bash
kscreen-doctor output.DP-1.hdr.enable
kscreen-doctor output.DP-1.sdr-brightness.408   # match your panels' peak
kscreen-doctor output.DP-1.sdrGamut.0           # 0% = plain sRGB desktop (recommended)
kscreen-doctor output.DP-1.rgbrange.automatic
```

If a screen stays washed out after all settings look right, check for stale
per-connector overrides: `~/.local/share/kscreen/control/outputs/*` (a
`"rgbrange": 1` left over from an old monitor silently forces Full range).

## How it works

The monitors expose a vendor control HID over their USB-C upstream:

```
Bus 003 Device 055: ID 056a:8191 Wacom Co., Ltd HID   <- NOT a Wacom tablet.
                                                       EHOMEWEI cloned the VID.
```

It has two interfaces: a pen/touch digitizer and a **control interface**
(2 interrupt endpoints, 64-byte reports). The Windows/macOS app sends
fire-and-forget reports there — no DDC/CI involved for these features:

```
02 05           heartbeat
02 EF 04 01 01  UltraHDR / boost switch ON   (menu page 4, item 1)
02 0F 01        backlight brightness unlock
```

Full protocol: **[PROTOCOL.md](PROTOCOL.md)** — opcode table, framing, menu
page map, what the firmware accepts/rejects, and the reverse-engineering
methodology (NSIS extraction → objdump on the MFC/Win32 binary, radare2 on the
macOS ObjC binary).

### USB quirks you will hit

- After hub power brownouts the scaler's HID report descriptors read back
  **empty (0 bytes)** → Linux can't bind `hid-generic`, no hidraw node.
  Raw USB via pyusb still works — that's why `ehwctl.py` bypasses HID.
- The `wacom` kernel driver claims `056a:8191`, fails ("Unknown device_type"),
  and can crash-loop the device. The enforcer detaches it per run and it
  rebinds harmlessly on replug.
- These are bus-powered-hungry panels. If the internal hub browns out every
  few minutes, feed the monitor's second USB-C port from a charger. A clean
  power cycle also restores the (broken-after-brownout) write path.

## Repository layout

```
ehwctl.py                  interactive CLI (list/info/menu/unlock/set/raw)
PROTOCOL.md                reverse-engineered vendor HID protocol
deploy/ehwctl_unlock.py    golden-state enforcer (unlock + boost, all units)
deploy/ehomewei-apply      orchestrator: HID pass + DDC/CI settings
deploy/ehomewei-apply.service   systemd oneshot
deploy/99-ehomewei.rules   udev: re-apply on monitor plug-in
deploy/install.sh          install everything
```

## Status of known levers (RO9 Pro, fw e0.10.05)

| Command | Effect | Ack |
|---|---|---|
| `02 04` | device info (magic `EHOMEWEI`, serial, fw, model) | ✓ |
| `02 05` | heartbeat | ✓ |
| `02 0A` | touch state query | ✓ |
| `02 EE` / `02 EE <page> FF` / `02 EE <page> <item>` | menu type / page / item read | ✓ |
| `02 0F 01` | **backlight brightness unlock** | silent (works) |
| `02 EF 04 01 01` | **UltraHDR boost switch** | silent (works, idempotent) |
| `02 EF <other>` | other menu writes | dead on this fw |

No ehomewei service/factory menu or public firmware exists anywhere (checked
official site/manual, Reddit, GitHub, search engines as of 2026-09). The
commands above are the vendor app's own — you're not missing anything.

---

### Solved with GLM-5.3 + OMP

This whole investigation — EDID forensics, NSIS/Mach-O reverse engineering,
raw-USB protocol discovery, and the Plasma color-pipeline debugging — was
solved in one session with **GLM-5.3 (Z.ai)** running in the **OMP (Oh My Pi)**
agent harness, 2026-09-09. No Windows machine was harmed (or used).

MIT License — see [LICENSE](LICENSE).
