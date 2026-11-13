# SPDX-License-Identifier: GPL-2.0-only
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/internal_wifi.py"
spec = importlib.util.spec_from_file_location("tab_lenovo_internal_wifi", SOURCE)
wifi = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wifi
spec.loader.exec_module(wifi)


class InternalWifiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sysfs = Path(self.tmp.name)
        for name, value in {
            "class/dmi/id/sys_vendor": "LENOVO",
            "class/dmi/id/product_name": "80HV",
            "bus/acpi/devices/INT33BB:00/hid": "INT33BB",
            "bus/acpi/devices/INT33BB:00/uid": "2",
        }.items():
            path = self.sysfs / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + "\n")
        self.target = self.sysfs / "devices/platform/INT33BB:00"
        self.target.mkdir(parents=True)
        self.function = self.target / "mmc_host/mmc0/mmc0:0001/mmc0:0001:1"
        self.function.mkdir(parents=True)
        (self.function / "vendor").write_text("0x024c\n")
        (self.function / "device").write_text("0xb723\n")
        (self.target / "driver_override").write_text("\n")
        devices = self.sysfs / "bus/platform/devices"
        devices.mkdir(parents=True)
        (devices / "INT33BB:00").symlink_to(self.target)
        self.drivers = self.sysfs / "bus/platform/drivers"
        for driver in (wifi.STOCK, wifi.CUSTOM):
            (self.drivers / driver).mkdir(parents=True)
        (self.target / "driver").symlink_to(self.drivers / wifi.STOCK)
        parent = self.sysfs / "devices/platform/80860F14:00"
        parent.mkdir(parents=True)
        (parent / "driver").symlink_to(self.drivers / wifi.STOCK)
        self.root = parent / "mmc_host/mmc2/mmc2:0001/block/mmcblk2/mmcblk2p2"
        self.root.mkdir(parents=True)
        blocks = self.sysfs / "class/block"
        blocks.mkdir(parents=True)
        (blocks / "mmcblk2p2").symlink_to(self.root)
        (self.sysfs / "class/net").mkdir(parents=True)
        self.commands = []
        self.controller = wifi.Controller(self.sysfs, self.run_command, wifi.KERNEL)

    def run_command(self, args, **kwargs):
        self.commands.append(args)
        output = "/dev/mmcblk2p2[/@]\n" if args[0] == "findmnt" else ""
        if args[:2] == ("modprobe", wifi.CUSTOM):
            self.custom_parameters()
        if args == ("rmmod", wifi.CUSTOM):
            module = self.sysfs / "module" / wifi.CUSTOM
            for p in (module / "parameters").iterdir():
                p.unlink()
            (module / "parameters").rmdir()
            module.rmdir()
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    def custom_parameters(self):
        parameters = self.sysfs / "module" / wifi.CUSTOM / "parameters"
        parameters.mkdir(parents=True, exist_ok=True)
        (parameters / "legacy").write_text("Y\n")
        (parameters / "pio").write_text("N\n")

    def change_driver(self, driver):
        current = self.target / "driver"
        if current.is_symlink():
            current.unlink()
        if driver:
            current.symlink_to(self.drivers / driver)

    def test_guards_accept_dynamic_storage_indices(self):
        state = self.controller.guard()
        self.assertIn("mmcblk2p2", state.source)
        self.assertIn("80860F14:00", state.parent)

    def test_rejects_another_tablet_without_mutation(self):
        (self.sysfs / "class/dmi/id/product_name").write_text("other")
        with self.assertRaisesRegex(RuntimeError, "hardware identity"):
            self.controller.start()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.controller.driver(), wifi.STOCK)

    def test_rejects_any_block_device_under_wifi_target(self):
        block = self.target / "block/mmcblk3"
        block.mkdir(parents=True)
        (self.sysfs / "class/block/mmcblk3").symlink_to(block)
        with self.assertRaisesRegex(RuntimeError, "block storage"):
            self.controller.start()
        self.assertEqual(self.commands, [])

    def test_rejects_root_filesystem_under_wifi_target(self):
        root_link = self.sysfs / "class/block/mmcblk2p2"
        root_link.unlink()
        root_link.symlink_to(self.target)
        with self.assertRaises(RuntimeError):
            self.controller.start()
        self.assertEqual(self.controller.driver(), wifi.STOCK)

    def test_refuses_another_sdio_function_without_driver_mutation(self):
        (self.function / "device").write_text("0x1234")
        with self.assertRaisesRegex(RuntimeError, "SDIO Wi-Fi"):
            self.controller.start()
        self.assertEqual(self.controller.driver(), wifi.STOCK)
        self.assertTrue(all(c[0] == "findmnt" for c in self.commands))

    def test_refuses_unqualified_kernel(self):
        self.controller.kernel = "7.1-other"
        with self.assertRaisesRegex(RuntimeError, "unqualified kernel"):
            self.controller.start()
        self.assertEqual(self.commands, [])

    def test_start_is_idempotent_when_already_configured(self):
        self.custom_parameters()
        self.change_driver(wifi.CUSTOM)
        result = self.controller.start()
        self.assertFalse(result["changed"])
        self.assertTrue(all(c[0] == "findmnt" for c in self.commands))

    def test_failed_custom_bind_restores_stock(self):
        def write_driver(driver, action):
            if action == "unbind":
                self.change_driver(None)
            elif driver == wifi.CUSTOM:
                raise OSError("simulated custom bind failure")
            else:
                self.change_driver(driver)
        with mock.patch.object(self.controller, "write_driver", side_effect=write_driver):
            with self.assertRaisesRegex(OSError, "simulated custom"):
                self.controller.start()
        self.assertEqual(self.controller.driver(), wifi.STOCK)
        self.assertEqual((self.target / "driver_override").read_text().strip(), "")
        self.assertIn(("rmmod", wifi.CUSTOM), self.commands)

    def test_stop_restores_stock_without_network_dependency(self):
        self.custom_parameters()
        self.change_driver(wifi.CUSTOM)
        (self.target / "driver_override").write_text(wifi.CUSTOM)
        def write_driver(driver, action):
            self.change_driver(None if action == "unbind" else driver)
        with mock.patch.object(self.controller, "write_driver", side_effect=write_driver):
            result = self.controller.stop()
        self.assertTrue(result["changed"])
        self.assertEqual(self.controller.driver(), wifi.STOCK)
        self.assertTrue(all(c[0] in ("findmnt", "modprobe", "rmmod") for c in self.commands))

    def test_help_is_available_without_hardware(self):
        result = subprocess.run([sys.executable, str(SOURCE), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("start,stop,status", result.stdout)


if __name__ == "__main__":
    unittest.main()
