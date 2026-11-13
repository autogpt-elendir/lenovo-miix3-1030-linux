#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Enable the tested SDIO workaround only on the Lenovo MIIX 3-1030."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time

KERNEL = "7.0.0-42-generic"
TARGET_NAME = "INT33BB:00"
STOCK = "sdhci-acpi"
CUSTOM = "miix_sdhci_diag"


@dataclass(frozen=True)
class RootState:
    source: str
    path: str
    parent: str
    driver: str


class Controller:
    def __init__(self, sysfs=Path("/sys"), runner=subprocess.run, kernel=None):
        self.sysfs = Path(sysfs)
        self.runner = runner
        self.kernel = kernel or os.uname().release
        self.target = self.sysfs / "bus/platform/devices" / TARGET_NAME
        self.drivers = self.sysfs / "bus/platform/drivers"

    def command(self, *args):
        result = self.runner(args, capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def driver(self):
        path = self.target / "driver"
        return path.resolve().name if path.exists() else None

    def guard(self):
        if self.kernel != KERNEL:
            raise RuntimeError("Refusing an unqualified kernel")
        required = {
            "class/dmi/id/sys_vendor": "LENOVO",
            "class/dmi/id/product_name": "80HV",
            "bus/acpi/devices/INT33BB:00/hid": "INT33BB",
            "bus/acpi/devices/INT33BB:00/uid": "2",
        }
        for name, value in required.items():
            if (self.sysfs / name).read_text().strip() != value:
                raise RuntimeError(f"Unexpected hardware identity: {name}")
        blocks = self.sysfs / "class/block"
        if any(TARGET_NAME in str(p.resolve()) for p in blocks.iterdir()):
            raise RuntimeError("Refusing a controller carrying block storage")
        source = self.command("findmnt", "-no", "SOURCE", "/").split("[")[0]
        if not source.startswith("/dev/mmcblk"):
            raise RuntimeError("Unexpected root block device")
        root = (blocks / Path(source).name).resolve(strict=True)
        if TARGET_NAME in str(root):
            raise RuntimeError("The Wi-Fi target carries the root filesystem")
        parent = next(
            (p for p in root.parents
             if p.name.startswith("80860F14:") and (p / "driver").exists()),
            None,
        )
        if parent is None or (parent / "driver").resolve().name != STOCK:
            raise RuntimeError("Unexpected eMMC controller or driver")
        if self.driver() not in (None, STOCK, CUSTOM):
            raise RuntimeError("Unexpected Wi-Fi controller driver")
        override = (self.target / "driver_override").read_text().strip()
        if override not in ("", "(null)", CUSTOM):
            raise RuntimeError("Refusing another driver's override")
        return RootState(source, str(root), str(parent),
                         str((parent / "driver").resolve()))

    def verify_root(self, before):
        if self.guard() != before:
            raise RuntimeError("Root storage changed during the operation")

    def configured(self):
        if self.driver() != CUSTOM:
            return False
        parameters = self.sysfs / "module" / CUSTOM / "parameters"
        return ((parameters / "legacy").read_text().strip() == "Y"
                and (parameters / "pio").read_text().strip() == "N")

    def write_driver(self, driver, action):
        (self.drivers / driver / action).write_text(TARGET_NAME + "\n")

    def interfaces(self):
        return [p.name for p in (self.sysfs / "class/net").iterdir()
                if TARGET_NAME in str((p / "device").resolve())]

    def wait_interface(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.interfaces():
                return
            time.sleep(0.2)
        raise RuntimeError("No internal Wi-Fi interface after controller setup")

    def restore(self, before):
        self.verify_root(before)
        if self.driver() == CUSTOM:
            self.write_driver(CUSTOM, "unbind")
        (self.target / "driver_override").write_text("\n")
        if self.driver() is None:
            self.write_driver(STOCK, "bind")
        self.command("modprobe", "r8723bs")
        if (self.sysfs / "module" / CUSTOM).exists():
            self.command("rmmod", CUSTOM)
        self.verify_root(before)
        if self.driver() != STOCK:
            raise RuntimeError("Stock Wi-Fi controller was not restored")

    def start(self):
        before = self.guard()
        if self.configured():
            return {"changed": False, "driver": CUSTOM}
        deadline = time.monotonic() + 15
        while self.driver() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if self.driver() != STOCK:
            raise RuntimeError("Wi-Fi controller is not attached to stock driver")
        functions = list(self.target.glob("mmc_host/mmc*/mmc*:*/mmc*:*:1"))
        if (len(functions) != 1 or
                (functions[0] / "vendor").read_text().strip() != "0x024c" or
                (functions[0] / "device").read_text().strip() != "0xb723"):
            raise RuntimeError("Unexpected SDIO Wi-Fi function")
        try:
            self.command("modprobe", CUSTOM, "legacy=1", "pio=0")
            self.command("modprobe", "-r", "r8723bs")
            (self.target / "driver_override").write_text(CUSTOM + "\n")
            self.write_driver(STOCK, "unbind")
            if self.driver() is None:
                self.write_driver(CUSTOM, "bind")
            self.command("modprobe", "r8723bs")
            self.wait_interface()
            self.verify_root(before)
            if not self.configured():
                raise RuntimeError("Unexpected controller diagnostic parameters")
        except Exception as error:
            try:
                self.restore(before)
            except Exception as rollback_error:
                raise RuntimeError(
                    f"Setup failed ({error}); rollback failed ({rollback_error})"
                ) from error
            raise
        return {"changed": True, "driver": CUSTOM}

    def stop(self):
        before = self.guard()
        changed = (self.driver() != STOCK or
                   (self.target / "driver_override").read_text().strip()
                   not in ("", "(null)"))
        if changed:
            self.restore(before)
        return {"changed": changed, "driver": self.driver()}

    def status(self):
        self.guard()
        return {"kernel": self.kernel, "driver": self.driver(),
                "configured": self.configured(), "interfaces": self.interfaces()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root on the qualified tablet")
    print(json.dumps(getattr(Controller(), args.action)()))


if __name__ == "__main__":
    main()
