#!/usr/bin/env python3
"""Inspect MIIX 3-1030 audio; optionally select or test its internal speaker."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import wave

SPEAKER_NAME = "alsa_output.platform-bytcr_rt5640.HiFi__Speaker__sink"
CARD_NAME = "sof-bytcht rt5640"
SAMPLE_RATE = 48000
TONE_SECONDS = 0.75
TONE_AMPLITUDE = 0.03
MAX_SELECTED_VOLUME = 0.35


class AudioError(RuntimeError):
    """A diagnostic or an explicitly requested audio action could not finish."""


def command(argv, timeout=5):
    """Capture command output for parsing; never echo raw server metadata."""
    environment = dict(os.environ, LC_ALL="C")
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout, env=environment)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise AudioError(f"{argv[0]} is unavailable or timed out") from error
    if result.returncode:
        raise AudioError(f"{argv[0]} failed; check the desktop audio session")
    return result.stdout


def make_tone(output):
    """Write a quiet stereo S16_LE WAV, with a short fade to avoid clicks."""
    count = int(SAMPLE_RATE * TONE_SECONDS)
    fade_samples = int(SAMPLE_RATE * 0.02)
    frames = bytearray()
    for index in range(count):
        fade = min(1, index / fade_samples,
                   (count - 1 - index) / fade_samples)
        value = round(32767 * TONE_AMPLITUDE * fade *
                      math.sin(2 * math.pi * 880 * index / SAMPLE_RATE))
        frames.extend(struct.pack("<hh", value, value))
    with wave.open(output, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(frames)


class AudioSession:
    def __init__(self, runner=None, sysfs=Path("/sys")):
        self.run = runner or command
        self.sysfs = Path(sysfs)

    def compatible_hardware(self):
        try:
            vendor = (self.sysfs / "class/dmi/id/sys_vendor").read_text().strip()
            product = (self.sysfs / "class/dmi/id/product_name").read_text().strip()
        except OSError:
            return False
        return vendor == "LENOVO" and product == "80HV"

    def nodes(self):
        try:
            nodes = json.loads(self.run(["pw-dump"], timeout=5))
        except (ValueError, TypeError) as error:
            raise AudioError("PipeWire did not return a valid node inventory") from error
        if not isinstance(nodes, list):
            raise AudioError("PipeWire did not return a node list")
        return nodes

    def speaker(self):
        matches = []
        for node in self.nodes():
            if not isinstance(node, dict):
                continue
            info = node.get("info")
            if node.get("type") != "PipeWire:Interface:Node" or not isinstance(info, dict):
                continue
            properties = info.get("props")
            if not isinstance(properties, dict):
                continue
            if (properties.get("media.class") == "Audio/Sink" and
                    properties.get("node.name") == SPEAKER_NAME and
                    properties.get("device.api") == "alsa" and
                    properties.get("api.alsa.card.name") == CARD_NAME):
                identifier = node.get("id")
                if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0:
                    raise AudioError("The speaker node has an invalid identifier")
                matches.append(identifier)
        if len(matches) != 1:
            raise AudioError("Expected exactly one internal RT5640 HiFi Speaker sink")
        return matches[0]

    def volume(self, node):
        value = self.run(["wpctl", "get-volume", str(node)], timeout=5)
        match = re.search(r"\bVolume:\s*([0-9]+(?:\.[0-9]+)?)", value)
        if not match:
            raise AudioError("WirePlumber did not report a speaker volume")
        volume = float(match.group(1))
        if not math.isfinite(volume):
            raise AudioError("The speaker volume is not finite")
        return {"volume": volume, "muted": "[MUTED]" in value}

    def action_guard(self):
        if not self.compatible_hardware():
            raise AudioError("This action requires a Lenovo MIIX 3-1030 (80HV)")
        if os.geteuid() == 0:
            raise AudioError("Use the logged-in desktop account, without sudo")
        return self.speaker()

    def report(self):
        report = {"expected_model": "Lenovo MIIX 3-1030 / 80HV",
                  "compatible_hardware": self.compatible_hardware(),
                  "acoustic_confirmation": "not_performed"}
        try:
            node = self.speaker()
        except AudioError:
            report["internal_hifi_speaker_found"] = False
            return report
        report.update({"internal_hifi_speaker_found": True,
                       "speaker_node": node, "speaker": self.volume(node)})
        return report

    def select_speaker(self):
        node = self.action_guard()
        old = self.volume(node)
        if old["volume"] > MAX_SELECTED_VOLUME:
            self.run(["wpctl", "set-volume", str(node),
                      str(MAX_SELECTED_VOLUME)], timeout=5)
        if old["muted"]:
            self.run(["wpctl", "set-mute", str(node), "0"], timeout=5)
        self.run(["wpctl", "set-default", str(node)], timeout=5)
        return {"speaker_node": node, "selected": True,
                "volume_was_limited": old["volume"] > MAX_SELECTED_VOLUME,
                "acoustic_confirmation": "required"}

    def test_speaker(self):
        node = self.action_guard()
        state = self.volume(node)
        if state["muted"] or state["volume"] <= 0:
            raise AudioError("The speaker is muted or silent; select/unmute it explicitly first")
        if state["volume"] > 1:
            raise AudioError("Reduce amplified speaker volume before testing")
        descriptor, name = tempfile.mkstemp(prefix="miix-audio-", suffix=".wav")
        path = Path(name)
        identity = os.fstat(descriptor)
        try:
            with os.fdopen(descriptor, "wb") as output:
                make_tone(output)
            self.run(["pw-play", "--target", SPEAKER_NAME, str(path)], timeout=8)
        finally:
            try:
                current = path.lstat()
            except FileNotFoundError:
                current = None
            if current is not None:
                if (not stat.S_ISREG(current.st_mode) or
                        (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)):
                    raise AudioError("Temporary audio file changed; cleanup skipped")
                path.unlink()
        return {"speaker_node": node, "software_playback_completed": True,
                "format": "S16_LE", "sample_rate": SAMPLE_RATE,
                "seconds": TONE_SECONDS, "acoustic_confirmation": "required"}


def main(argv=None, session=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="Play a short quiet tone on the internal HiFi speaker")
    parser.add_argument("--select-speaker", action="store_true",
                        help="Select the internal speaker; cap volume at 35%% and unmute")
    args = parser.parse_args(argv)
    session = session or AudioSession()
    try:
        result = {"diagnostic": session.report()}
        if args.select_speaker:
            result["selection"] = session.select_speaker()
        if args.test:
            result["test"] = session.test_speaker()
    except (AudioError, OSError) as error:
        message = str(error) if isinstance(error, AudioError) else "Unable to read audio state or create a temporary tone"
        print(json.dumps({"error": message}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
