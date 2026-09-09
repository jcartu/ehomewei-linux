#!/bin/bash
# Install the ehomewei golden-state enforcer:
#   /usr/local/bin/ehwctl_unlock.py   HID unlock + boost switch (pyusb)
#   /usr/local/bin/ehomewei-apply     HID pass + DDC/CI settings
#   systemd oneshot                   runs at boot
#   udev rule                         re-runs on every monitor plug-in
set -e
cd "$(dirname "$0")"

[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"

command -v python3 >/dev/null || { echo "python3 required"; exit 1; }
python3 -c 'import usb' 2>/dev/null || {
    echo "pyusb missing — install python-pyusb (Arch) / python3-usb (Debian) first"
    exit 1
}
command -v ddcutil >/dev/null || { echo "ddcutil required"; exit 1; }

install -m 755 ehwctl_unlock.py /usr/local/bin/ehwctl_unlock.py
install -m 755 ehomewei-apply   /usr/local/bin/ehomewei-apply
install -m 644 ehomewei-apply.service /etc/systemd/system/ehomewei-apply.service
install -m 644 99-ehomewei.rules /etc/udev/rules.d/99-ehomewei.rules

systemctl daemon-reload
systemctl enable --now ehomewei-apply.service
udevadm control --reload

echo "installed. Test: systemctl start ehomewei-apply.service && journalctl -u ehomewei-apply -n 5"
