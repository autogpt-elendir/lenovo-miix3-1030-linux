#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Generate private SDHCI layout assertions from this running kernel's BTF."""

import argparse
import json
from pathlib import Path
import re
import subprocess

STRUCTURES = ("sdhci_host", "sdhci_ops")


def select_structures(document):
    types = document.get("types") if isinstance(document, dict) else document
    if not isinstance(types, list):
        raise ValueError("Invalid bpftool JSON type inventory")
    selected = []
    for name in STRUCTURES:
        candidates = [item for item in types if isinstance(item, dict)
                      and item.get("kind") == "STRUCT" and item.get("name") == name]
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one complete {name} structure")
        structure = candidates[0]
        size = structure.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError(f"Invalid size for {name}")
        if not isinstance(structure.get("members"), list) or not structure["members"]:
            raise ValueError(f"No member layout for {name}")
        selected.append(structure)
    return selected


def assertions(document):
    lines = ["/* Generated from the current running kernel BTF; do not reuse elsewhere. */",
             "#include <linux/build_bug.h>", "#include <linux/stddef.h>"]
    count = 0
    for structure in select_structures(document):
        name = structure["name"]
        lines.append(f"static_assert(sizeof(struct {name}) == {structure['size']});")
        count += 1
        seen = set()
        checked = 0
        for member in structure["members"]:
            field = member.get("name")
            offset = member.get("bits_offset", member.get("offset"))
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise ValueError(f"Invalid member offset in {name}")
            if offset > structure["size"] * 8:
                raise ValueError(f"Out-of-range member in {name}")
            if not field or member.get("bitfield_size", 0):
                continue  # C offsetof cannot address anonymous members or bitfields.
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
                raise ValueError(f"Invalid C field name in {name}")
            if field in seen or offset % 8:
                raise ValueError(f"Duplicate or non-byte-aligned field in {name}")
            seen.add(field)
            lines.append(f"static_assert(offsetof(struct {name}, {field}) == {offset // 8});")
            count += 1
            checked += 1
        if not checked:
            raise ValueError(f"No checkable fields in {name}")
    return "\n".join(lines) + "\n", count


def running_abi(runner=subprocess.run, base=Path("/sys/kernel/btf/vmlinux"),
                module=Path("/sys/kernel/btf/sdhci")):
    result = runner(["bpftool", "-B", str(base), "-j", "btf", "dump", "file", str(module)],
                    check=False, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Cannot read the running SDHCI BTF; check bpftool and file permissions")
    if len(result.stdout) > 8 * 1024 * 1024:
        raise ValueError("Unexpectedly large SDHCI BTF inventory")
    return select_structures(json.loads(result.stdout))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Read an already captured bpftool JSON instead")
    parser.add_argument("--output", type=Path, required=True, help="Create a new header; never overwrite")
    args = parser.parse_args()
    try:
        data = json.loads(args.json.read_text()) if args.json else running_abi()
        header, count = assertions(data)
        with args.output.open("x") as destination:
            destination.write(header)
        print(json.dumps({"abi_assertions": count, "header": str(args.output)}))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"BTF validation failed: {error}\n")


if __name__ == "__main__":
    main()
