# EHOMEWEI / RTK scaler — vendor USB HID control protocol

Reverse-engineered from the vendor's official apps (no protocol docs exist publicly):

- **Windows**: `EHome_Wei_Setup.exe` (NSIS → `DisplayController.exe`, 32-bit MFC,
  statically linked hidapi, glog; version 1.0.0.135, Shenzhen Yihong Electronics)
- **macOS**: `Ehomewei Display 1.1.4 (260407).dmg` (Mach-O universal, ObjC +
  Swift; classes `EDHIDCreateCommand`, `EDHIDSenderManager`, `EDHIDDeviceMonitor`,
  `EDUltraHDR`)

## Device

USB HID, full-speed, on the monitor's USB-C upstream (behind its internal hub):

| VID:PID | App's name for it |
|---|---|
| `056a:8191` | "touch" variant (RO9 Pro ships with this; clones Wacom's VID) |
| `1a2c:2d23` | "keyboard" variant |
| `05ac:0265` | "iPad" variant (clones Apple's VID) |

Interfaces: 0 = pen/touch reports (1 IN endpoint), **1 = control** (IN `0x82` +
OUT `0x02`, interrupt, 64-byte packets). iManufacturer/iProduct both `"HID"`;
serial = unit serial (e.g. `1610100701`).

Note: the vendor app on macOS additionally gates writes on
`device.manufacturer.lowercaseString == "ehomewei"` — the shipped RO9 Pro
firmware reports `HID`, so even the vendor's own macOS app can't send to these
units without that check disabled. The device itself accepts the commands below.

## Framing

64-byte reports. First byte doubles as **HID report ID** and **source tag**:

- Host → device: `0x02` (pad payload with zeros to 64 bytes, write to `EP 0x02`)
- Device → host: `0x01`, then echo of the command byte, then data

Transport is plain interrupt OUT/IN (also accepted via SET_REPORT control
transfers). Responses are fire-and-forget for write commands — **expect no ACK**
and verify by re-reading state. Under hub brownout the device queues replies
one-behind; drain the IN endpoint with retries.

## Commands (payload as written on the wire)

| Bytes | Meaning | Verified |
|---|---|---|
| `02 03 01` | announce "mac mode" | silent, effect unknown |
| `02 04` | get device info → `01 04 "EHOMEWEI" <4B serial> <3B fw> <model str>` | ✓ (`e0 10 05`, "RO9 Pro") |
| `02 05` | heartbeat → `01 05` | ✓ |
| `02 01 <arg>` | gravity sensor get/set | dead on fw e0.10.05 |
| `02 07 <arg>` | stylus switch / gravity sensing | dead |
| `02 08 <0\|1>` | switch (vendor: on/off pair) | dead |
| `02 09` | get dual-screen mode | dead |
| `02 0A [<arg>]` | touch state query → `01 0A <state>` (any/no arg returns state) | ✓ |
| `02 0E <arg>` | vendor switch pair | dead |
| **`02 0F 0/1`** | **backlight brightness unlock OFF/ON** | ✓ silent-fire (visible effect) |
| `02 EE` | get menu type → `01 EE <type>` (3 on RO9 Pro) | ✓ |
| `02 EE <page> FF` | get menu page (all item values) → `01 EE <page> FF <items...>` | ✓ |
| `02 EE <page> <item>` | get single item → `01 EE <page> <item> <val>...` | ✓ |
| **`02 EF <page> <item> <val>`** | **set menu item** — only `04 01 01` verified working | ✓ for page 4 |

Replies to unknown commands: none. A bare `01 00 ...` packet sometimes trails
page reads — treat as end-of-data marker.

## Menu pages (RO9 Pro, menuType=3)

| Page | Readback `01 EE <p> FF ...` | Meaning |
|---|---|---|
| 1 | `00 00 00 32 64 32` | volume/backlight-ish bundle (items differ per input) |
| 2 | `00 00 00 02 00` | misc |
| 3 | `32 32 32 01 32 32` | picture: brightness/contrast/saturation/etc (50 50 50 1 50 50) |
| **4** | **`01 02 01 00`** | **UltraHDR page** — the boost state; item 0 reflects boost ON |
| 5 | `00 01` | misc |

Page 4 semantics established experimentally (diffing an "amazing" unit against a
stock one, then flipping bits):

- `02 EF 04 01 01` → page 4 becomes `01 02 01 00` = **boost/UltraHDR engaged**
  (idempotent: re-sending changes nothing)
- Writing item 0 instead (`02 EF 04 00 01`) did nothing on the affected unit;
  the writable selector is **item 1**
- The scaler's HDR EDID block (HDR static metadata, 408 cd/m² PQ) is a
  separate, persistent state — restored by DDC/CI `setvcp 04 1` (factory reset)

## The two "extra brightness" levers, exactly

```python
import usb.core, time
d = usb.core.find(idVendor=0x056a, idProduct=0x8191)
cfg = d.get_active_configuration()
iface = next(i for i in cfg if len(list(i)) == 2)   # 2-endpoint control iface
d.detach_kernel_driver(iface.bInterfaceNumber)       # usbhid/wacom holds it
usb.util.claim_interface(d, iface.bInterfaceNumber)
for payload in ([0x02,0x05], [0x02,0xEF,0x04,0x01,0x01], [0x02,0x0F,0x01]):
    d.write(0x02, bytes(payload).ljust(64, b'\0'), 2000)
    time.sleep(0.25)
```

Order matters loosely: heartbeat first (wakes the endpoint), then the page-4
switch, then the unlock. No replies will come — that is normal.

## Reverse-engineering methodology (for other models)

1. `7z x` the NSIS installer → `DisplayController.exe`. Imports `HID.DLL`,
   `SETUPAPI` (no `dxva2.dll`) → the app is HID-only, not DDC/CI.
2. `strings -e l` (UTF-16LE) surfaces the vendor's log strings — command
   validation ("HandleCommand 错误的来源/错误的长度", resend logic) and the
   full OSD item name list (`UltraHDR`, `HDRAuto`, `menu_item_*`).
3. Windows payload constants: `objdump -d` and grep for `movw $0x??02`
   (little-endian `02 <cmd>` words) — that yields the opcode set above.
4. Cleaner still: the macOS dmg (7z extracts it) — ObjC symbols name everything
   (`EDHIDCreateCommand.brightnessUnLockCommand:`, `setMenuValCommand:itemIndex:itemVal:`,
   `createEHWTouchDevice` → VID/PID constants in `mov edx, imm32`).
5. On Linux, talk raw USB with pyusb — do not rely on hidraw (descriptors can
   read back empty after brownouts; the wacom driver misbinds).

## Not found / dead ends (as of 2026-09)

- No ehomewei service/factory menu documented anywhere (any model). The only
  RTK-scaler factory-mode combo on record is cocopar's: monitor off, no signal,
  hold Menu + long-press Power ~3 s — untested here, unnecessary given the above.
- ehomewei publishes no firmware images (their `ISP.zip` is a Realtek RTD ISP
  flashing tool with an empty firmware directory). Firmware flows through
  support@ehomewei.com.
- Menu writes other than page 4 item 1, and all of commands 01/03/06/07/08/09/0E,
  were silently ignored on firmware `e0.10.05` both before and after clean power
  cycles. Queries always work.
