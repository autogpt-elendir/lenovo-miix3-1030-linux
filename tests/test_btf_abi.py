# SPDX-License-Identifier: GPL-2.0-only
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import btf_abi


def sample():
    return {"types": [
        {"kind": "STRUCT", "name": "sdhci_host", "size": 16,
         "members": [{"name": "mmc", "bits_offset": 0},
                     {"name": "flags", "bits_offset": 64},
                     {"name": "active", "bits_offset": 96, "bitfield_size": 1}]},
        {"kind": "STRUCT", "name": "sdhci_ops", "size": 8,
         "members": [{"name": "read_l", "bits_offset": 0}]},
    ]}


class BtfTests(unittest.TestCase):
    def test_generates_sizes_and_byte_offsets_but_skips_bitfields(self):
        header, count = btf_abi.assertions(sample())
        self.assertEqual(count, 5)
        self.assertIn("sizeof(struct sdhci_host) == 16", header)
        self.assertIn("offsetof(struct sdhci_host, flags) == 8", header)
        self.assertNotIn(", active)", header)

    def test_missing_or_duplicate_structures_are_refused(self):
        data = sample()
        data["types"].pop()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            btf_abi.assertions(data)
        data = sample()
        data["types"].append(data["types"][0])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            btf_abi.assertions(data)

    def test_injected_c_field_name_is_refused(self):
        data = sample()
        data["types"][0]["members"][0]["name"] = "field); malicious("
        with self.assertRaisesRegex(ValueError, "C field"):
            btf_abi.assertions(data)

    def test_out_of_bounds_and_unaligned_offsets_are_refused(self):
        for offset in (-1, 3, 4096):
            data = sample()
            data["types"][0]["members"][0]["bits_offset"] = offset
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                btf_abi.assertions(data)

    def test_bpf_failure_is_not_a_zero_assertion_success(self):
        runner = mock.Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="permission"))
        with self.assertRaisesRegex(RuntimeError, "Cannot read"):
            btf_abi.running_abi(runner=runner)

    def test_running_btf_uses_base_and_module_from_same_kernel(self):
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0,
                                                      stdout=json.dumps(sample()), stderr=""))
        data = btf_abi.running_abi(runner=runner)
        self.assertEqual(len(data), 2)
        args = runner.call_args.args[0]
        self.assertEqual(args[1:3], ["-B", "/sys/kernel/btf/vmlinux"])
        self.assertEqual(args[-1], "/sys/kernel/btf/sdhci")


if __name__ == "__main__":
    unittest.main()
