#!/usr/bin/python3

# ddcvolume - Monitor Volume Control Over DDC
# Copyright (C) 2021 Ingo Ruhnke <grumbel@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from typing import List

import argparse
import fcntl
import os
import re
import subprocess
import sys
import xdg.BaseDirectory
import dbus

# Workflow:
# retrieve current volume from cache file or monitor
# calculate new volume
# save new volume to cache file
# apply ddcvolume as last step

# FIXME: Could rewrite this to use sqlite for easier locking and robustness.

I2C_RE = re.compile(r"i2c-(\d+)", re.ASCII)


class DDCVolume:

    def __init__(self, ddcutil_exe: str, bus: int) -> None:
        self.ddcutil_exe = ddcutil_exe
        self.bus = bus

        try:
            self.ddcvolume_dir = os.path.join(xdg.BaseDirectory.get_runtime_dir(), "ddcvolume")
            os.mkdir(self.ddcvolume_dir)
        except FileExistsError:
            pass
        except:
            raise

    def commit(self) -> None:
        with open(os.path.join(self.ddcvolume_dir, "commit"), "a+") as fl:
            fcntl.flock(fl, fcntl.LOCK_EX)

            fl.seek(0)
            volume_str = fl.read()
            try:
                current_volume = int(volume_str)
            except ValueError:
                current_volume = None

            volume = self.get()

            if volume != current_volume:
                subprocess.check_call(["sudo", self.ddcutil_exe, "--noverify", "--bus", str(self.bus), "setvcp", "62", "--", str(volume)])

                fl.truncate(0)
                fl.seek(0)
                fl.write(str(volume))

    def set(self, volume_str: str) -> None:
        with open(os.path.join(self.ddcvolume_dir, "lock"), "w") as fl:
            fcntl.flock(fl, fcntl.LOCK_EX)
            volume = self._get()
            volume = self._update_volume(volume, volume_str)
            with open(os.path.join(self.ddcvolume_dir, "volume"), "w") as fout:
                fout.write(str(volume))
        return volume

    def get(self) -> int:
        with open(os.path.join(self.ddcvolume_dir, "lock"), "w") as fl:
            fcntl.flock(fl, fcntl.LOCK_EX)
            return self._get()

    def send_notify(self, volume: int):
        with open(os.path.join(self.ddcvolume_dir, "notification_id"), "a+") as fl:
            fcntl.flock(fl, fcntl.LOCK_EX)

            fl.seek(0)
            notify_id_str = fl.read()

            if not notify_id_str:
                notify_id = 0
            else:
                try:
                    notify_id = int(notify_id_str)
                except ValueError:
                    notify_id = 0

            if volume < 33:
                icon = "audio-volume-low-symbolic"
            elif volume < 66:
                icon = "audio-volume-medium-symbolic"
            else:
                icon = "audio-volume-high-symbolic"

            bus = dbus.SessionBus()
            notifications = bus.get_object('org.freedesktop.Notifications',
                                           '/org/freedesktop/Notifications')
            notifications_iface = dbus.Interface(notifications, dbus_interface="org.freedesktop.Notifications")
            notify_id = notifications_iface.Notify(
                dbus.String("ddcvolume volume control"), # app_name
                dbus.UInt32(notify_id), # replaces_id
                dbus.String(icon), # app_icon
                dbus.String(f"Volume {volume}%"), # summary
                dbus.String(""), # body
                dbus.Array([]), # actions
                dbus.Dictionary({ # hints
                    dbus.String("transient"): dbus.Boolean(True, variant_level=1),
                    dbus.String("x-canonical-private-synchronous"): dbus.String("", variant_level=1), # not working on xcfe
                    dbus.String("value"): dbus.Int32(volume, variant_level=1),
                }),
                dbus.Int32(2000))

            fl.truncate(0)
            fl.write(str(notify_id) + "\n")

    def _update_volume(self, volume: int, volume_str: str) -> str:
        if volume_str[0] == "+" or volume_str[0] == "-":
            return max(0, min(volume + int(volume_str), 100))
        else:
            return max(0, min(int(volume_str), 100))

    def _get(self) -> int:
        try:
            with open(os.path.join(self.ddcvolume_dir, "volume"), "r") as fin:
                volume = int(fin.read())
                return volume
        except FileNotFoundError:
            return self._refresh()

    def _refresh(self):
        result = subprocess.check_output(["sudo", self.ddcutil_exe, "--noverify", "--brief", "--bus", str(self.bus), "getvcp", "62"], text=True)
        volume = int(result.split()[3])
        with open(os.path.join(self.ddcvolume_dir, "volume"), "w") as fout:
            fout.write(str(volume))
        return volume


def find_i2c_bus(name: str) -> int:
    devices_path = "/sys/bus/i2c/devices"
    for entry in os.scandir(devices_path):
        m = I2C_RE.match(entry.name)
        if m is not None:
            with open(os.path.join(devices_path, entry.name, "name"), 'r') as fin:
                fin_content = fin.read().rstrip()
            if fin_content == name:
                return int(m.group(1))
    else:
        raise Exception("failed to find i2c device: {}".format(name))


def parse_args(args: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Volume Control over DDC")
    parser.add_argument("--set", metavar="volume", type=str, help="set volume to volume")
    parser.add_argument("--get", action='store_true', help="retrieve the current volume")
    parser.add_argument("--ddcutil", metavar="PATH", type=str, default='ddcutil', help="ddcutil executable to use")
    return parser.parse_args(args)


def main():
    args = parse_args(sys.argv[1:])
    bus = find_i2c_bus("Radeon i2c bit bus 0x92")
    ddcutil_exe = args.ddcutil
    ddcvolume = DDCVolume(ddcutil_exe, bus)
    if args.get:
        print(ddcvolume.get())
    elif args.set is not None:
        volume_str = args.set
        volume = ddcvolume.set(volume_str)
        ddcvolume.send_notify(volume)
        ddcvolume.commit()


if __name__ == "__main__":
    main()


# EOF #
