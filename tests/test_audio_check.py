#!/usr/bin/env python3
"""Audio checks never capture a microphone or select an arbitrary sink."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import wave

SOURCE = Path(__file__).resolve().parents[1] / "scripts/audio_check.py"
SPEC = importlib.util.spec_from_file_location("miix_audio_check", SOURCE)
audio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio)


def speaker_node(identifier=56, **overrides):
    properties = {"media.class": "Audio/Sink", "node.name": audio.SPEAKER_NAME,
                  "device.api": "alsa", "api.alsa.card.name": audio.CARD_NAME,
                  "node.description": "PRIVATE_PERSONAL_HOSTNAME",
                  "application.process.user": "PRIVATE_USERNAME",
                  "private.server.address": "192.0.2.123"}
    properties.update(overrides)
    return {"id": identifier, "type": "PipeWire:Interface:Node",
            "info": {"props": properties}}


class FakeRunner:
    def __init__(self, nodes=None, volume=0.40, muted=False):
        self.nodes = [speaker_node()] if nodes is None else nodes
        self.current_volume = volume
        self.muted = muted
        self.calls = []
        self.played_path = None
        self.play_hook = None

    def __call__(self, argv, timeout=5):
        self.calls.append((list(argv), timeout))
        if argv == ["pw-dump"]:
            return json.dumps(self.nodes)
        if argv[:2] == ["wpctl", "get-volume"]:
            return f"Volume: {self.current_volume:.2f}" + (" [MUTED]" if self.muted else "")
        if argv[:2] == ["wpctl", "set-volume"]:
            self.current_volume = float(argv[3])
            return ""
        if argv[:2] == ["wpctl", "set-mute"]:
            self.muted = argv[3] != "0"
            return ""
        if argv[:2] == ["wpctl", "set-default"]:
            return ""
        if argv[0] == "pw-play":
            self.played_path = Path(argv[-1])
            if self.play_hook:
                self.play_hook(self.played_path)
            return ""
        raise AssertionError(f"Unexpected command: {argv}")


class AudioCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="miix-audio-test-")
        self.addCleanup(self.directory.cleanup)
        self.sysfs = Path(self.directory.name) / "sys"
        dmi = self.sysfs / "class/dmi/id"
        dmi.mkdir(parents=True)
        (dmi / "sys_vendor").write_text("LENOVO\n")
        (dmi / "product_name").write_text("80HV\n")
        patch = mock.patch.object(audio.os, "geteuid", return_value=1000)
        patch.start()
        self.addCleanup(patch.stop)

    def session(self, runner=None):
        return audio.AudioSession(runner=runner or FakeRunner(), sysfs=self.sysfs)

    def test_default_diagnostic_is_read_only_and_redacts_untrusted_metadata(self):
        runner = FakeRunner()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = audio.main([], self.session(runner))
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())["diagnostic"]
        self.assertTrue(report["internal_hifi_speaker_found"])
        self.assertEqual(report["speaker_node"], 56)
        for private in ("PRIVATE_PERSONAL_HOSTNAME", "PRIVATE_USERNAME", "192.0.2.123"):
            self.assertNotIn(private, output.getvalue())
        self.assertEqual([call[0][0] for call in runner.calls], ["pw-dump", "wpctl"])
        self.assertEqual(runner.calls[-1][0][1], "get-volume")

    def test_wrong_hardware_refuses_playback_and_selection(self):
        (self.sysfs / "class/dmi/id/product_name").write_text("OTHER")
        runner = FakeRunner()
        for action in ("test_speaker", "select_speaker"):
            with self.assertRaises(audio.AudioError):
                getattr(self.session(runner), action)()
        self.assertEqual(runner.calls, [])

    def test_root_cannot_change_or_play_desktop_audio(self):
        runner = FakeRunner()
        with mock.patch.object(audio.os, "geteuid", return_value=0):
            with self.assertRaises(audio.AudioError):
                self.session(runner).test_speaker()
        self.assertEqual(runner.calls, [])

    def test_wrong_profile_or_codec_cannot_be_selected(self):
        variants = [
            {"node.name": "alsa_output.platform-bytcr_rt5640.pro-output-0"},
            {"node.name": "alsa_output.platform-bytcr_rt5640.HiFi__Headphones__sink"},
            {"api.alsa.card.name": "Other codec"},
            {"device.api": "test-loopback"},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                runner = FakeRunner(nodes=[speaker_node(**variant)])
                with self.assertRaises(audio.AudioError):
                    self.session(runner).select_speaker()
                self.assertEqual([call[0] for call in runner.calls], [["pw-dump"]])

    def test_duplicate_matching_speakers_are_not_guessed(self):
        runner = FakeRunner(nodes=[speaker_node(56), speaker_node(57)])
        with self.assertRaises(audio.AudioError):
            self.session(runner).select_speaker()

    def test_selection_reduces_before_unmuting_and_uses_dynamic_id(self):
        runner = FakeRunner(nodes=[speaker_node(93)], volume=0.80, muted=True)
        result = self.session(runner).select_speaker()
        changes = [call[0] for call in runner.calls if call[0][0] == "wpctl"][1:]
        self.assertEqual(changes, [["wpctl", "set-volume", "93", "0.35"],
                                   ["wpctl", "set-mute", "93", "0"],
                                   ["wpctl", "set-default", "93"]])
        self.assertTrue(result["volume_was_limited"])
        self.assertEqual(result["acoustic_confirmation"], "required")

    def test_selection_never_raises_an_existing_low_volume(self):
        runner = FakeRunner(volume=0.10)
        self.session(runner).select_speaker()
        self.assertFalse(any(c[0][1] == "set-volume" for c in runner.calls if c[0][0] == "wpctl"))
        self.assertFalse(any(c[0][1] == "set-mute" for c in runner.calls if c[0][0] == "wpctl"))
        self.assertEqual(runner.current_volume, 0.10)

    def test_tone_is_quiet_s16_stereo_48khz_with_fades(self):
        output = io.BytesIO()
        audio.make_tone(output)
        with wave.open(io.BytesIO(output.getvalue()), "rb") as tone:
            self.assertEqual((tone.getnchannels(), tone.getsampwidth(), tone.getframerate()), (2, 2, 48000))
            self.assertEqual(tone.getnframes(), 36000)
            raw = tone.readframes(tone.getnframes())
        samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
        self.assertLessEqual(max(abs(x) for x in samples), 984)
        self.assertGreater(max(abs(x) for x in samples), 900)
        self.assertEqual(samples[::2], samples[1::2])
        self.assertEqual((samples[0], samples[-1]), (0, 0))

    def test_playback_targets_speaker_only_and_removes_its_tempfile(self):
        runner = FakeRunner()
        observed = []
        runner.play_hook = lambda path: observed.append(path.is_file())
        result = self.session(runner).test_speaker()
        self.assertEqual(observed, [True])
        self.assertFalse(runner.played_path.exists())
        command, timeout = runner.calls[-1]
        self.assertEqual(command[:3], ["pw-play", "--target", audio.SPEAKER_NAME])
        self.assertEqual(timeout, 8)
        self.assertFalse(any(c[0][0] in ("pw-record", "arecord") for c in runner.calls))
        self.assertFalse(any(c[0][0] == "wpctl" and c[0][1].startswith("set-") for c in runner.calls))
        self.assertTrue(result["software_playback_completed"])
        self.assertEqual(result["acoustic_confirmation"], "required")

    def test_failed_playback_still_removes_only_its_tempfile(self):
        runner = FakeRunner()
        def fail(path):
            raise audio.AudioError("Synthetic playback failure")
        runner.play_hook = fail
        with self.assertRaises(audio.AudioError):
            self.session(runner).test_speaker()
        self.assertFalse(runner.played_path.exists())

    def test_replaced_temporary_symlink_and_target_are_not_deleted(self):
        runner = FakeRunner()
        protected = Path(self.directory.name) / "keep.txt"
        protected.write_text("keep")
        def replace(path):
            path.unlink()
            path.symlink_to(protected)
        runner.play_hook = replace
        try:
            with self.assertRaisesRegex(audio.AudioError, "cleanup skipped"):
                self.session(runner).test_speaker()
            self.assertTrue(runner.played_path.is_symlink())
            self.assertEqual(protected.read_text(), "keep")
        finally:
            if runner.played_path and runner.played_path.is_symlink():
                runner.played_path.unlink()

    def test_muted_zero_or_amplified_volume_requires_explicit_change(self):
        for volume, muted in ((0.4, True), (0.0, False), (1.5, False)):
            with self.subTest(volume=volume, muted=muted):
                runner = FakeRunner(volume=volume, muted=muted)
                with self.assertRaises(audio.AudioError):
                    self.session(runner).test_speaker()
                self.assertFalse(any(c[0][0] == "pw-play" for c in runner.calls))

    def test_missing_inventory_info_is_skipped_safely(self):
        runner = FakeRunner(nodes=[{"type": "PipeWire:Interface:Node", "info": None}, speaker_node()])
        self.assertEqual(self.session(runner).speaker(), 56)

    def test_no_human_audibility_claim_is_generated_by_cli(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = audio.main(["--select-speaker", "--test"], self.session())
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["test"]["acoustic_confirmation"], "required")
        self.assertNotIn("audible", report["test"])


if __name__ == "__main__":
    unittest.main()
