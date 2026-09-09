#!/usr/bin/env python3
"""ehwctl — EHOMEWEI monitor scaler control over USB HID (Linux).

Reverse-engineered from Ehomewei Display 1.1.4 (macOS) and DisplayController.exe
(Windows). Talks raw interrupt transfers to the Realtek scaler control HID,
bypassing the (broken/empty) HID report descriptors.

Device VID:PID variants: 056a:8191, 1a2c:2d23, 05ac:0265.
Protocol: 64-byte reports; outgoing [0]=0x02 (host); responses [0]=0x01.

  02 03 01                    mac-mode announce
  02 04                       get device info
  02 05                       heartbeat
  02 0F <0|1>                 brightness unlock OFF/ON  (the "Windows-only" boost)
  02 EE                       get menu type
  02 EE <page> FF             get menu page (all items)
  02 EE <page> <item>         get one menu item
  02 EF <page> <item> <val>   set menu item value

Usage:
  ehwctl.py list
  ehwctl.py info|menu-type|macmode [-a ADDR]
  ehwctl.py menu <page> [-a ADDR]
  ehwctl.py item <page> <item> [-a ADDR]
  ehwctl.py unlock <0|1> [-a ADDR]
  ehwctl.py set <page> <item> <val> [-a ADDR]
  ehwctl.py raw <hexbytes> [-a ADDR]
  ehwctl.py shell                       # interactive: one command per line
"""
import sys
import usb.core
import usb.util

EHW_IDS = [(0x056a, 0x8191), (0x1a2c, 0x2d23), (0x05ac, 0x0265)]
EP_OUT, EP_IN = 0x02, 0x82


def find_devices():
    devs = []
    for vid, pid in EHW_IDS:
        for d in usb.core.find(find_all=True, idVendor=vid, idProduct=pid):
            devs.append(d)
    return devs


class Dev:
    def __init__(self, d):
        self.d = d
        cfg = d.get_active_configuration()
        # control interface: the one with 2 endpoints (IN+OUT)
        self.iface = None
        for intf in cfg:
            eps = [(e.bEndpointAddress, e) for e in intf]
            if len(eps) == 2:
                self.iface = intf
                break
        if self.iface is None:
            raise RuntimeError('no control interface found')

    def open(self):
        for i in range(2):
            try:
                if self.d.is_kernel_driver_active(self.iface.bInterfaceNumber):
                    self.d.detach_kernel_driver(self.iface.bInterfaceNumber)
            except NotImplementedError:
                pass
            try:
                usb.util.claim_interface(self.d, self.iface.bInterfaceNumber)
                return
            except usb.core.USBError:
                if i == 1:
                    raise

    def close(self):
        try:
            usb.util.release_interface(self.d, self.iface.bInterfaceNumber)
        except usb.core.USBError:
            pass
        try:
            self.d.attach_kernel_driver(self.iface.bInterfaceNumber)
        except Exception:
            pass

    def xfer(self, payload, read_reply=True, timeout=2000):
        pkt = bytes(payload).ljust(64, b'\x00')
        self.d.write(EP_OUT, pkt, timeout)
        if not read_reply:
            return None
        r = self.d.read(EP_IN, 64, timeout)
        return bytes(r)


def run_all(fn, addr=None):
    devs = find_devices()
    if addr:
        bus, num = (int(x) for x in addr.rsplit('/', 2)[1:])
        devs = [d for d in devs if d.bus == bus and d.address == num]
    if not devs:
        print('no ehomewei control devices found', file=sys.stderr)
        return 1
    for d in devs:
        w = Dev(d)
        w.open()
        try:
            fn(w, f'{d.bus:03d}/{d.address:03d}')
        finally:
            w.close()
    return 0


def cmd_info():
    def fn(w, name):
        print(f'{name}:')
        print(f'  -> 0204')
        r = w.xfer([0x02, 0x04])
        print(f'  <- {r.hex() if r else "(timeout)"}')
    return run_all(fn)


def interactive():
    def process(w, name, line):
        h = bytes.fromhex(line)
        r = w.xfer(h)
        print(f'{name} <- {r.hex() if r else "(timeout)"}')
    while True:
        try:
            line = input('ehw> ').strip()
        except EOFError:
            break
        if not line:
            continue
        if line in ('q', 'quit', 'exit'):
            break
        try:
            run_all(lambda w, n: process(w, n, line))
        except Exception as e:
            print('error:', e)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    cmd, rest = args[0], args[1:]
    addr = None
    if '-a' in rest:
        i = rest.index('-a')
        addr = rest[i + 1]
        del rest[i:i + 2]

    if cmd == 'list':
        for d in find_devices():
            print(f'/dev/bus/usb/{d.bus:03d}/{d.address:03d}  {d.idVendor:04x}:{d.idProduct:04x}')
        return 0
    if cmd == 'shell':
        interactive()
        return 0

    def fn(w, name):
        print(f'{name}:')
        if cmd == 'info':
            r = w.xfer([0x02, 0x04])
        elif cmd == 'heartbeat':
            r = w.xfer([0x02, 0x05])
        elif cmd == 'macmode':
            r = w.xfer([0x02, 0x03, 0x01])
        elif cmd == 'menu-type':
            r = w.xfer([0x02, 0xEE])
        elif cmd == 'menu' and rest:
            r = w.xfer([0x02, 0xEE, int(rest[0], 0), 0xFF])
        elif cmd == 'item' and len(rest) >= 2:
            r = w.xfer([0x02, 0xEE, int(rest[0], 0), int(rest[1], 0)])
        elif cmd == 'unlock' and rest:
            r = w.xfer([0x02, 0x0F, int(rest[0], 0)])
        elif cmd == 'set' and len(rest) >= 3:
            p, i, v = (int(x, 0) for x in rest[:3])
            r = w.xfer([0x02, 0xEF, p, i, v])
        elif cmd == 'raw' and rest:
            r = w.xfer(bytes.fromhex(rest[0]))
        else:
            print('unknown command', file=sys.stderr)
            raise SystemExit(2)
        print(f'  <- {r.hex() if r else "(timeout)"}')

    return run_all(fn, addr)


if __name__ == '__main__':
    sys.exit(main())
