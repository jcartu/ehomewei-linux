#!/usr/bin/env python3
"""EHOMEWEI golden state enforcer — run at boot and on monitor hotplug.

Per unit (056a:8191 / 1a2c:2d23 / 05ac:0265), fire-and-forget (no ACKs):
  02 05          heartbeat (wakes the control endpoint)
  02 EF 04 01 01 UltraHDR/boost switch ON  (page4 item1; idempotent — verified
                 on both RO9 Pro units; sets page4 to 01 02 01 00)
  02 0F 01       backlight brightness unlock
"""
import time
import usb.core

IDS = [(0x056a, 0x8191), (0x1a2c, 0x2d23), (0x05ac, 0x0265)]
EP_OUT = 0x02
CMDS = [[0x02, 0x05], [0x02, 0xEF, 0x04, 0x01, 0x01], [0x02, 0x0F, 0x01]]

ok = 0
for vid, pid in IDS:
    for d in usb.core.find(find_all=True, idVendor=vid, idProduct=pid):
        try:
            cfg = d.get_active_configuration()
            iface = next(i for i in cfg if len(list(i)) == 2)
            ifn = iface.bInterfaceNumber
            try:
                if d.is_kernel_driver_active(ifn):
                    d.detach_kernel_driver(ifn)
            except NotImplementedError:
                pass
            usb.util.claim_interface(d, ifn)
            try:
                for p in CMDS:
                    d.write(EP_OUT, bytes(p).ljust(64, b'\0'), 2000)
                    time.sleep(0.25)
                ok += 1
            finally:
                usb.util.release_interface(d, ifn)
        except Exception as e:
            print(f'ehwctl: {d.bus:03d}/{d.address:03d} failed: {e}')
print(f'ehwctl: golden state (boost+unlock) applied to {ok} device(s)')
