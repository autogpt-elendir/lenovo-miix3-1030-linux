#!/usr/bin/env python3
"""Behavioral tests for the optional, user-scoped kiosk memory guard."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts/kiosk_memory_guard.py"
spec = importlib.util.spec_from_file_location("kiosk_guard", SOURCE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def sample(total=None, invocation="a" * 32, active=True):
    total = guard.LIMIT + 1 if total is None else total
    return dict(active=active, invocation=invocation, ram=total // 2,
                swap=total - total // 2)


class DecisionTests(unittest.TestCase):
    def test_hold_requires_sixty_seconds_and_strictly_over_limit(self):
        state = {}
        for now in (0, 15, 30, 45):
            state, restart = guard.decision(state, sample(), now, "boot")
            self.assertFalse(restart)
        state, restart = guard.decision(state, sample(), 60, "boot")
        self.assertTrue(restart)
        self.assertEqual(state["last_restart"], 60)
        state, restart = guard.decision({}, sample(guard.LIMIT), 0, "boot")
        self.assertFalse(restart)
        self.assertNotIn("above_since", state)

    def test_lower_sample_cancels_a_window(self):
        state, _ = guard.decision({}, sample(), 0, "boot")
        state, _ = guard.decision(state, sample(1), 15, "boot")
        self.assertNotIn("above_since", state)
        state, restart = guard.decision(state, sample(), 30, "boot")
        self.assertEqual(state["above_since"], 30)
        self.assertFalse(restart)

    def test_missed_samples_cannot_count_as_continuous_pressure(self):
        state, _ = guard.decision({}, sample(), 0, "boot")
        state, restart = guard.decision(state, sample(), 61, "boot")
        self.assertFalse(restart)
        self.assertEqual(state["above_since"], 61)

    def test_new_invocation_starts_its_own_window(self):
        state, _ = guard.decision({}, sample(), 0, "boot")
        state, restart = guard.decision(state, sample(invocation="b" * 32), 60, "boot")
        self.assertFalse(restart)
        self.assertEqual(state["above_since"], 60)

    def test_cooldown_survives_observer_runs_and_reserves_attempts(self):
        state = {"boot_id": "boot", "last_restart": 60}
        for now in range(75, 660, 15):
            state, restart = guard.decision(state, sample(), now, "boot")
            self.assertFalse(restart)
        state, restart = guard.decision(state, sample(), 660, "boot")
        self.assertTrue(restart)
        self.assertEqual(state["last_restart"], 660)

    def test_inactive_unit_and_boot_change_clear_old_window(self):
        state, _ = guard.decision({}, sample(), 0, "old")
        state, restart = guard.decision(state, sample(active=False), 15, "old")
        self.assertFalse(restart)
        self.assertNotIn("above_since", state)
        state["last_restart"] = 1000
        state, restart = guard.decision(state, sample(), 1, "new")
        self.assertFalse(restart)
        self.assertNotIn("last_restart", state)


class SamplingTests(unittest.TestCase):
    def props(self, cgroup, active="active", invocation="a" * 32):
        return (f"ActiveState={active}\nMainPID=42\n"
                f"InvocationID={invocation}\nControlGroup={cgroup}\n")

    def test_foreign_or_traversing_cgroups_are_refused(self):
        uid = guard.os.getuid()
        prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
        for cgroup in ("/system.slice/miix-kiosk.service",
                       prefix + "../miix-kiosk.service",
                       prefix + "another.service"):
            with self.subTest(cgroup=cgroup), patch.object(
                    guard, "systemctl", return_value=self.props(cgroup)):
                with self.assertRaises(ValueError):
                    guard.sample_browser()

    def test_sampling_sums_the_real_ram_and_swap_counter_files(self):
        uid = guard.os.getuid()
        prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cgroup = root / prefix.lstrip("/") / guard.UNIT
            cgroup.mkdir(parents=True)
            (cgroup / "memory.current").write_text("12345\n")
            (cgroup / "memory.swap.current").write_text("67890\n")
            def local_path(value, *args):
                return root if str(value) == "/sys/fs/cgroup" else Path(value, *args)
            with patch.object(guard, "Path", side_effect=local_path), \
                    patch.object(guard, "systemctl", return_value=self.props(prefix + guard.UNIT)):
                observed = guard.sample_browser()
            self.assertEqual(observed["ram"], 12345)
            self.assertEqual(observed["swap"], 67890)

    def test_cgroup_link_cannot_escape_the_own_user_subtree(self):
        uid = guard.os.getuid()
        prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / prefix.lstrip("/")
            parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (parent / guard.UNIT).symlink_to(outside, target_is_directory=True)
            def local_path(value, *args):
                return root if str(value) == "/sys/fs/cgroup" else Path(value, *args)
            with patch.object(guard, "Path", side_effect=local_path), \
                    patch.object(guard, "systemctl", return_value=self.props(prefix + guard.UNIT)):
                with self.assertRaises(ValueError):
                    guard.sample_browser()

    def test_inactive_unit_does_not_read_cgroup_counters(self):
        with patch.object(guard, "systemctl", return_value=self.props("", active="inactive")):
            self.assertEqual(guard.sample_browser()["ram"], 0)

    def test_invalid_invocation_is_rejected(self):
        uid = guard.os.getuid()
        cgroup = f"/user.slice/user-{uid}.slice/user@{uid}.service/miix-kiosk.service"
        with patch.object(guard, "systemctl", return_value=self.props(cgroup, invocation="bad")):
            with self.assertRaises(ValueError):
                guard.sample_browser()


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        guard.save_state(self.path, {"boot_id": "boot", "last_sample": 45,
                                   "above_since": 0, "invocation": "a" * 32})

    def contexts(self, observations):
        return (patch.object(guard, "sample_browser", side_effect=observations),
                patch.object(guard.time, "clock_gettime", return_value=60),
                patch.object(guard, "read_boot_id", return_value="boot"))

    def test_recovery_uses_try_restart_for_an_active_current_invocation(self):
        a, b, c = self.contexts([sample(), sample()])
        with a, b, c, patch.object(guard, "systemctl") as systemctl:
            self.assertTrue(guard.check_once(self.path))
        systemctl.assert_called_once_with("--no-block", "try-restart", "miix-kiosk.service")
        self.assertEqual(guard.read_state(self.path)["last_restart"], 60)

    def test_concurrent_stop_or_new_invocation_prevents_restart(self):
        for confirmation in (sample(active=False), sample(invocation="b" * 32), sample(1)):
            guard.save_state(self.path, {"boot_id": "boot", "last_sample": 45,
                                       "above_since": 0, "invocation": "a" * 32})
            a, b, c = self.contexts([sample(), confirmation])
            with a, b, c, patch.object(guard, "systemctl") as systemctl:
                self.assertFalse(guard.check_once(self.path))
            systemctl.assert_not_called()

    def test_failed_enqueue_keeps_the_cooldown(self):
        a, b, c = self.contexts([sample(), sample()])
        with a, b, c, patch.object(guard, "systemctl", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                guard.check_once(self.path)
        self.assertEqual(guard.read_state(self.path)["last_restart"], 60)

    def test_counter_error_cancels_the_window_without_recovery(self):
        with patch.object(guard, "sample_browser", side_effect=ValueError("bad counter")), \
                patch.object(guard, "systemctl") as systemctl:
            with self.assertRaises(ValueError):
                guard.check_once(self.path)
        self.assertNotIn("above_since", guard.read_state(self.path))
        systemctl.assert_not_called()

    def test_invalid_persisted_timestamp_is_rejected(self):
        self.path.write_text(json.dumps({"last_sample": float("inf")}))
        with self.assertRaises(ValueError):
            guard.read_state(self.path)

    def test_help_requires_neither_runtime_directory_nor_systemd(self):
        result = subprocess.run(["python3", str(SOURCE), "--help"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
