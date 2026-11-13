#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the qualified MIIX 3-1030 Wi-Fi host workaround from pinned sources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import urllib.request

sys.dont_write_bytecode = True

from btf_abi import assertions, running_abi

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "profiles/wifi-source-manifest.json"
KERNEL = "7.0.0-42-generic"
SOURCE_VERSION = "7.0.0-42.42"
MAX_SOURCE_BYTES = 1024 * 1024
BUILD_TIMEOUT = 900
HEADER_OLD = "\tunsigned int\t\ttuning_err;"
HEADER_NEW = "\tint\t\t\ttuning_err;"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    document = json.loads(MANIFEST.read_text())
    if document["kernel"] != KERNEL or document["ubuntu_source_version"] != SOURCE_VERSION:
        raise ValueError("Source profile does not match the qualified kernel")
    if set(document["sources"]) != {"sdhci-acpi.c", "sdhci.h"}:
        raise ValueError("Unexpected source inventory")
    for source in document["sources"].values():
        if not source["url"].startswith("https://raw.githubusercontent.com/torvalds/linux/"):
            raise ValueError("Source must use the pinned official Linux mirror")
        if document["base_commit"] not in source["url"]:
            raise ValueError("Source URL is not pinned to the manifest commit")
        if not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            raise ValueError("Invalid source checksum")
    patch = ROOT / "patches/sdhci-miix-controller.patch"
    if digest(patch.read_bytes()) != document["patch_sha256"]:
        raise ValueError("Controller patch does not match its manifest checksum")
    return document


def release_values(path):
    return {key: value.strip().strip('"') for key, value in
            (line.split("=", 1) for line in path.read_text().splitlines()
             if "=" in line and not line.startswith("#"))}


def preflight(sysfs=Path("/sys"), release=Path("/etc/os-release"),
              kernel=None, machine=None, headers=None, which=shutil.which,
              abi_reader=running_abi, runner=subprocess.run):
    kernel = kernel or os.uname().release
    machine = machine or os.uname().machine
    if kernel != KERNEL or machine != "x86_64":
        raise RuntimeError("Boot the qualified x86_64 kernel 7.0.0-42-generic first")
    if ((sysfs / "class/dmi/id/sys_vendor").read_text().strip() != "LENOVO"
            or (sysfs / "class/dmi/id/product_name").read_text().strip() != "80HV"):
        raise RuntimeError("This workaround is qualified only for Lenovo model 80HV")
    values = release_values(release)
    if values.get("ID") != "ubuntu" or values.get("VERSION_ID") != "26.04":
        raise RuntimeError("This build profile requires Ubuntu 26.04")
    headers = headers or Path("/lib/modules") / kernel / "build"
    if not (headers / "Makefile").is_file():
        raise RuntimeError("Install headers for the exact running kernel")
    package = runner(["dpkg-query", "-W", "-f=${Version}",
                      "linux-headers-" + kernel], check=False, text=True,
                     capture_output=True, timeout=15)
    if package.returncode or package.stdout.strip() != SOURCE_VERSION:
        raise RuntimeError("The installed Ubuntu header source version is not qualified")
    missing = [name for name in ("gcc-15", "make", "patch", "modinfo", "bpftool", "nice")
               if not which(name)]
    if missing:
        raise RuntimeError("Missing build dependencies: " + ", ".join(missing))
    for name in ("vmlinux", "sdhci"):
        if not (sysfs / "kernel/btf" / name).is_file():
            raise RuntimeError("Running kernel SDHCI BTF is required")
    header, count = assertions(abi_reader())
    return {"kernel": kernel, "ubuntu_source_version": SOURCE_VERSION,
            "headers": str(headers), "abi_assertions": count}, header


def download(url, expected_sha256, opener=urllib.request.urlopen):
    with opener(url, timeout=30) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise RuntimeError("Pinned source exceeds the download size limit")
    if digest(data) != expected_sha256:
        raise RuntimeError("Pinned source checksum mismatch")
    return data


def ubuntu_header(data, expected_sha256):
    source = data.decode("utf-8")
    if source.count(HEADER_OLD) != 1:
        raise ValueError("Unexpected Ubuntu SDHCI header delta")
    modified = source.replace(HEADER_OLD, HEADER_NEW, 1).encode("utf-8")
    if digest(modified) != expected_sha256:
        raise ValueError("Ubuntu-adjusted SDHCI header checksum mismatch")
    return modified


def compile_module(workdir, headers, log_path):
    command = ["nice", "-n", "15", "make", "-j1", "CC=gcc-15", "-C", str(headers),
               "M=" + str(workdir), "modules"]
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))
    with log_path.open("x") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, preexec_fn=limits)
        try:
            result = process.wait(timeout=BUILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError("Build timed out; its process group was stopped")
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    if result:
        raise RuntimeError(f"Kernel module build failed; see {log_path}")


def validate_module(module, kernel=KERNEL, runner=subprocess.run):
    if not module.is_file() or module.is_symlink():
        raise RuntimeError("The compiler did not produce a regular module")
    def info(field):
        result = runner(["modinfo", "-F", field, str(module)], capture_output=True,
                        text=True, check=False, timeout=15)
        if result.returncode:
            raise RuntimeError("Cannot inspect the built module")
        return result.stdout.strip()
    if not info("vermagic").startswith(kernel + " "):
        raise RuntimeError("Built module ABI does not match the running kernel")
    if info("alias"):
        raise RuntimeError("Refusing a module with automatic hardware aliases")
    return digest(module.read_bytes())


def build(workdir, profile, checks, abi_header):
    if os.geteuid() == 0:
        raise RuntimeError("Compile as a regular user; installation is a separate privileged step")
    # A new directory prevents accidentally replacing another build or user data.
    if workdir.exists() or workdir.is_symlink():
        raise FileExistsError("Choose a new, non-existent work directory")
    workdir.mkdir(parents=True)
    for name, source in profile["sources"].items():
        data = download(source["url"], source["sha256"])
        if name == "sdhci.h":
            data = ubuntu_header(data, profile["ubuntu_header_sha256"])
        (workdir / name).write_bytes(data)
    (workdir / "sdhci_abi_asserts.h").write_text(abi_header)
    patch = ROOT / "patches/sdhci-miix-controller.patch"
    with patch.open("rb") as source:
        result = subprocess.run(["patch", "--batch", "--fuzz=0", "-p1"], cwd=workdir,
                                stdin=source, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Pinned controller patch could not be applied exactly")
    if digest((workdir / "sdhci-acpi.c").read_bytes()) != profile["patched_source_sha256"]:
        raise RuntimeError("Patched controller source checksum mismatch")
    (workdir / "sdhci-acpi.c").rename(workdir / "miix_sdhci_diag.c")
    (workdir / "Kbuild").write_text("obj-m += miix_sdhci_diag.o\n")
    compile_module(workdir, checks["headers"], workdir / "build.log")
    module = workdir / "miix_sdhci_diag.ko"
    result = dict(checks, module_path=str(module.resolve()),
                  module_sha256=validate_module(module))
    with (workdir / "build-result.json").open("x") as destination:
        json.dump(result, destination, indent=2)
        destination.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only hardware, header and BTF checks")
    subparsers = parser.add_subparsers(dest="command")
    builder = subparsers.add_parser("build", help="Download pinned C sources and build as a regular user")
    builder.add_argument("--work-dir", required=True, type=Path, help="A new directory for sources and output")
    args = parser.parse_args()
    if args.check and args.command:
        parser.error("Choose either --check or build")
    if not args.check and args.command != "build":
        parser.error("Choose --check or build; see --help")
    try:
        profile = manifest()
        checks, header = preflight()
        if args.check:
            print(json.dumps(dict(checks, ready=True)))
        else:
            print(json.dumps(build(args.work_dir.expanduser().absolute(), profile, checks, header)))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Wi-Fi build refused: {error}\n")


if __name__ == "__main__":
    main()
