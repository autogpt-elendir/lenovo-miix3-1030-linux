# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_wifi as builder


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sysfs = self.root / "sys"
        for name, value in {"class/dmi/id/sys_vendor": "LENOVO",
                            "class/dmi/id/product_name": "80HV",
                            "kernel/btf/vmlinux": "fixture", "kernel/btf/sdhci": "fixture"}.items():
            p = self.sysfs / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value)
        self.release = self.root / "os-release"
        self.release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
        self.headers = self.root / "headers"
        self.headers.mkdir()
        (self.headers / "Makefile").write_text("# fixture\n")
        self.abi = [
            {"kind": "STRUCT", "name": n, "size": 8,
             "members": [{"name": "field", "bits_offset": 0}]}
            for n in ("sdhci_host", "sdhci_ops")]

    def preflight(self, **kwargs):
        params = dict(sysfs=self.sysfs, release=self.release, kernel=builder.KERNEL,
                      machine="x86_64", headers=self.headers, which=lambda _: "/bin/tool",
                      abi_reader=lambda: self.abi,
                      runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=builder.SOURCE_VERSION))
        params.update(kwargs)
        return builder.preflight(**params)

    def test_preflight_has_no_filesystem_mutation(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        result, header = self.preflight()
        self.assertEqual(result["kernel"], builder.KERNEL)
        self.assertEqual(result["abi_assertions"], 4)
        self.assertIn("static_assert", header)
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))

    def test_wrong_kernel_rejected_before_abi_or_build(self):
        abi = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, "qualified x86_64"):
            self.preflight(kernel="another-kernel", abi_reader=abi)
        abi.assert_not_called()

    def test_wrong_model_and_wrong_source_version_refused(self):
        (self.sysfs / "class/dmi/id/product_name").write_text("other")
        with self.assertRaisesRegex(RuntimeError, "80HV"):
            self.preflight()
        (self.sysfs / "class/dmi/id/product_name").write_text("80HV")
        with self.assertRaisesRegex(RuntimeError, "source version"):
            self.preflight(runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="7.0.0-99.99"))

    def test_download_hash_mismatch_and_size_limit_refuse_source(self):
        for payload in (b"wrong", b"x" * (builder.MAX_SOURCE_BYTES + 1)):
            response = mock.Mock()
            response.__enter__ = mock.Mock(return_value=io.BytesIO(payload))
            response.__exit__ = mock.Mock(return_value=False)
            with self.subTest(size=len(payload)), self.assertRaises(RuntimeError):
                builder.download("https://example.invalid/source", "0" * 64,
                                 opener=lambda *a, **k: response)

    def test_header_delta_requires_exact_single_change_and_result_hash(self):
        original = (builder.HEADER_OLD + "\n").encode()
        expected = (builder.HEADER_NEW + "\n").encode()
        self.assertEqual(builder.ubuntu_header(original, builder.digest(expected)), expected)
        for source, digest in ((original * 2, builder.digest(expected)),
                               (original, "0" * 64)):
            with self.assertRaises(ValueError):
                builder.ubuntu_header(source, digest)

    def test_build_refuses_root_or_existing_workspace_before_network(self):
        with mock.patch.object(builder.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "regular user"):
                builder.build(self.root / "new", {}, {}, "")
        with mock.patch.object(builder.os, "geteuid", return_value=1000), \
                mock.patch.object(builder, "download") as download:
            with self.assertRaises(FileExistsError):
                builder.build(self.root, {}, {}, "")
            download.assert_not_called()

    def test_module_rejects_aliases_or_wrong_vermagic(self):
        module = self.root / "miix.ko"
        module.write_bytes(b"fixture")
        for vermagic, alias in (("wrong SMP", ""), (builder.KERNEL + " SMP", "acpi:*")):
            def runner(args, **kwargs):
                return SimpleNamespace(returncode=0,
                                       stdout=vermagic if args[2] == "vermagic" else alias)
            with self.subTest(vermagic=vermagic, alias=alias), self.assertRaises(RuntimeError):
                builder.validate_module(module, runner=runner)

    def test_timeout_kills_the_whole_build_process_group(self):
        proc = mock.Mock(pid=4321)
        proc.wait.side_effect = [subprocess.TimeoutExpired("make", 900), 0]
        with mock.patch.object(builder.subprocess, "Popen", return_value=proc) as popen, \
                mock.patch.object(builder.os, "killpg") as kill:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                builder.compile_module(self.root, self.headers, self.root / "build.log")
        kill.assert_called_once_with(4321, signal.SIGKILL)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIn("-j1", popen.call_args.args[0])

    def test_cancelled_build_does_not_leave_compilers_running(self):
        proc = mock.Mock(pid=4321)
        proc.wait.side_effect = [KeyboardInterrupt(), 0]
        proc.poll.return_value = None
        with mock.patch.object(builder.subprocess, "Popen", return_value=proc), \
                mock.patch.object(builder.os, "killpg") as kill:
            with self.assertRaises(KeyboardInterrupt):
                builder.compile_module(self.root, self.headers, self.root / "cancelled-build.log")
        kill.assert_called_once_with(4321, signal.SIGKILL)

    def test_manifest_and_cli_help(self):
        self.assertEqual(builder.manifest()["kernel"], builder.KERNEL)
        for script in ("build_wifi.py", "btf_abi.py"):
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--help"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_patched_source_preparation_records_only_verified_output(self):
        original_header = (builder.HEADER_OLD + "\n").encode()
        expected_header = (builder.HEADER_NEW + "\n").encode()
        profile = {"sources": {"sdhci-acpi.c": {"url": "source", "sha256": "unused"},
                               "sdhci.h": {"url": "header", "sha256": "unused"}},
                   "ubuntu_header_sha256": builder.digest(expected_header),
                   "patched_source_sha256": builder.digest(b"/* trusted source fixture */\n")}
        checks = {"kernel": builder.KERNEL, "headers": str(self.headers), "abi_assertions": 4}
        def downloaded(url, checksum):
            return original_header if url == "header" else b"/* trusted source fixture */\n"
        def compiled(workdir, headers, logfile):
            (workdir / "miix_sdhci_diag.ko").write_bytes(b"module fixture")
        work = self.root / "new-build"
        with mock.patch.object(builder.os, "geteuid", return_value=1000), \
                mock.patch.object(builder, "download", side_effect=downloaded), \
                mock.patch.object(builder.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as patch, \
                mock.patch.object(builder, "compile_module", side_effect=compiled), \
                mock.patch.object(builder, "validate_module", return_value="a" * 64):
            result = builder.build(work, profile, checks, "/* live ABI */\n")
        self.assertEqual(json.loads((work / "build-result.json").read_text()), result)
        self.assertEqual((work / "sdhci.h").read_bytes(), expected_header)
        self.assertTrue((work / "miix_sdhci_diag.c").exists())
        self.assertIn("--fuzz=0", patch.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
