#!/usr/bin/env python3
"""Observe the kiosk cgroup and recover only an active, oversized browser."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

UNIT = "miix-kiosk.service"
RUNTIME_NAME = "miix-kiosk-memory-guard"
LIMIT = 2 * 1024**3
HOLD_SECONDS = 60
COOLDOWN_SECONDS = 600
MAX_SAMPLE_GAP = 30


def decision(state, sample, now, boot_id):
    """Require contiguous high observations from one browser invocation."""
    state = dict(state) if state.get("boot_id") == boot_id else {"boot_id": boot_id}
    previous = state.get("last_sample")
    if (previous is None or not 0 <= now - previous <= MAX_SAMPLE_GAP
            or state.get("invocation") != sample["invocation"]):
        state.pop("above_since", None)
    state.update(last_sample=now, invocation=sample["invocation"])
    if not sample["active"] or sample["ram"] + sample["swap"] <= LIMIT:
        state.pop("above_since", None)
        return state, False
    state.setdefault("above_since", now)
    ready = now - state["above_since"] >= HOLD_SECONDS
    previous_restart = state.get("last_restart")
    if previous_restart is not None:
        ready = ready and now - previous_restart >= COOLDOWN_SECONDS
    if ready:
        # Reserve the cooldown before a request, including failed requests.
        state["last_restart"] = now
        state.pop("above_since", None)
    return state, ready


def systemctl(*args):
    return subprocess.run(
        ["systemctl", "--user", *args], check=True, capture_output=True,
        text=True, timeout=8,
    ).stdout


def sample_browser():
    output = systemctl(
        "show", UNIT, "-p", "ActiveState", "-p", "MainPID", "-p",
        "InvocationID", "-p", "ControlGroup",
    )
    props = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    active = props.get("ActiveState") == "active" and int(props.get("MainPID", 0)) > 0
    invocation = props.get("InvocationID", "")
    if not active:
        return dict(active=False, invocation=invocation, ram=0, swap=0)
    relative = Path(props["ControlGroup"])
    prefix = f"/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/"
    if (not re.fullmatch(r"[0-9a-fA-F]{32}", invocation)
            or not str(relative).startswith(prefix)
            or relative.name != UNIT or ".." in relative.parts):
        raise ValueError("Refusing an unexpected kiosk cgroup")
    root = Path("/sys/fs/cgroup").resolve(strict=True)
    cgroup = (root / str(relative).lstrip("/")).resolve(strict=True)
    if not cgroup.is_relative_to(root / prefix.lstrip("/")):
        raise ValueError("Refusing a kiosk cgroup outside the user manager")
    ram = int((cgroup / "memory.current").read_text())
    swap = int((cgroup / "memory.swap.current").read_text())
    if min(ram, swap) < 0:
        raise ValueError("Invalid memory counter")
    return dict(active=True, invocation=invocation, ram=ram, swap=swap)


def read_state(path):
    try:
        if path.stat().st_size > 8192:
            raise ValueError("Guard state is too large")
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(state, dict):
        raise ValueError("Invalid guard state")
    for key in ("last_sample", "above_since", "last_restart"):
        if key in state and (type(state[key]) not in (int, float)
                             or not 0 <= state[key] < float("inf")):
            raise ValueError("Invalid guard timestamp")
    return state


def save_state(path, state):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(state, handle)
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def read_boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def check_once(state_path):
    state = read_state(state_path)
    try:
        sample = sample_browser()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        state.pop("above_since", None)
        save_state(state_path, state)
        raise
    now = time.clock_gettime(time.CLOCK_BOOTTIME)
    updated, ready = decision(state, sample, now, read_boot_id())
    save_state(state_path, updated)
    if ready:
        confirmation = sample_browser()
        if (not confirmation["active"]
                or confirmation["invocation"] != sample["invocation"]
                or confirmation["ram"] + confirmation["swap"] <= LIMIT):
            print("Recovery cancelled: the current browser no longer qualifies", flush=True)
            return False
        print(f"Recovering {UNIT}: RAM={confirmation['ram']} "
              f"swap={confirmation['swap']} limit={LIMIT}", flush=True)
        # try-restart cannot start a service stopped concurrently by its owner.
        systemctl("--no-block", "try-restart", UNIT)
        return True
    if "above_since" in updated and "above_since" not in state:
        print(f"Browser over {LIMIT} bytes; observing for {HOLD_SECONDS}s", flush=True)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    runtime = os.environ.get("RUNTIME_DIRECTORY")
    expected = Path(f"/run/user/{os.getuid()}/{RUNTIME_NAME}")
    if not runtime or Path(runtime) != expected:
        parser.error(f"Run through {RUNTIME_NAME}.service")
    try:
        check_once(expected / "state.json")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Observation failed; no recovery forced: {type(error).__name__}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
