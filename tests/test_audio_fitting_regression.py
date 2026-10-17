"""Regression and safety tests for OpenDub Studio Phase 23 audio fitting, silence trimming, lip-sync QA, and diagnostics."""
from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from backend.doctor import run_doctor
from backend.lipsync_qa import classify_lipsync_segment, evaluate_project_lipsync_qa
from backend.mixing import fit_audio, measure_and_trim_wav_silence, atempo_chain


def generate_synthetic_tone(
    path: Path,
    duration: float,
    freq: float = 440.0,
    sr: int = 48000,
    lead_silence_sec: float = 0.0,
    trail_silence_sec: float = 0.0,
) -> None:
    """Generate a clean synthetic sine wave tone with optional leading/trailing silence."""
    lead_samples = int(sr * lead_silence_sec)
    tone_samples = int(sr * duration)
    trail_samples = int(sr * trail_silence_sec)
    total_samples = lead_samples + tone_samples + trail_samples

    fade_len = min(int(0.02 * sr), max(1, tone_samples // 2))
    step = 2.0 * math.pi * freq / sr

    data = bytearray(total_samples * 2)
    for i in range(tone_samples):
        val = 0.5 * math.sin(i * step)
        if fade_len > 0:
            if i < fade_len:
                val *= (i / fade_len)
            elif i >= tone_samples - fade_len:
                val *= ((tone_samples - 1 - i) / fade_len)
        int_val = int(val * 32767.0)
        struct.pack_into("<h", data, (lead_samples + i) * 2, int_val)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data)


def measure_wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


class AudioFittingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_short_dialogue_fits_target_without_clipping(self):
        """Short dialogue fits target duration cleanly without speech clipping."""
        src = self.tmp / "short_src.wav"
        out = self.tmp / "short_fit.wav"
        generate_synthetic_tone(src, duration=0.8, freq=300.0)

        res = fit_audio(src, out, target=1.0, max_speedup=1.25, max_slowdown=0.80)
        self.assertTrue(out.is_file())
        self.assertFalse(res["speech_truncated"])
        self.assertAlmostEqual(res["applied_tempo"], 0.8, delta=0.01)

        actual_dur = measure_wav_duration(out)
        self.assertAlmostEqual(actual_dur, 1.0, delta=0.05)

    def test_02_long_dialogue_timestretched_without_truncation(self):
        """Long dialogue is time-stretched without spoken content truncation."""
        src = self.tmp / "long_src.wav"
        out = self.tmp / "long_fit.wav"
        generate_synthetic_tone(src, duration=2.4, freq=500.0)

        res = fit_audio(src, out, target=2.0, max_speedup=1.25, max_slowdown=0.80)
        self.assertTrue(out.is_file())
        self.assertFalse(res["speech_truncated"])
        self.assertFalse(res["duration_fit_limited"])
        self.assertAlmostEqual(res["applied_tempo"], 1.20, delta=0.01)

        actual_dur = measure_wav_duration(out)
        self.assertAlmostEqual(actual_dur, 2.0, delta=0.05)

    def test_03_actual_fitted_duration_matches_measured_wav(self):
        """The actual fitted duration in result matches the measured audio sample count."""
        src = self.tmp / "measure_src.wav"
        out = self.tmp / "measure_fit.wav"
        generate_synthetic_tone(src, duration=1.5, freq=400.0)

        res = fit_audio(src, out, target=1.3)
        measured_dur = measure_wav_duration(out)

        self.assertAlmostEqual(res["actual_fitted_duration"], measured_dur, delta=0.01)
        self.assertEqual(res["sample_rate"], 48000)
        self.assertTrue(res["math_reconciled"])
        self.assertFalse(res["speech_truncated"])

    def test_04_tempo_remains_inside_configured_limits(self):
        """Applied tempo is clamped within [max_slowdown, max_speedup]."""
        src = self.tmp / "extreme_src.wav"
        out = self.tmp / "extreme_fit.wav"
        generate_synthetic_tone(src, duration=5.0, freq=350.0)

        res = fit_audio(src, out, target=1.0, max_speedup=1.28, max_slowdown=0.82)
        self.assertEqual(res["applied_tempo"], 1.28)
        self.assertTrue(res["duration_fit_limited"])
        self.assertTrue(res["semantic_compression_recommended"])
        self.assertFalse(res["speech_truncated"])

    def test_05_duration_fit_limited_flagged_instead_of_atrim_clipping(self):
        """When speech cannot fit safely, it is flagged duration_fit_limited=True without atrim amputation."""
        src = self.tmp / "overlong_src.wav"
        out = self.tmp / "overlong_fit.wav"
        generate_synthetic_tone(src, duration=3.0, freq=440.0)

        res = fit_audio(src, out, target=1.5, max_speedup=1.25, max_slowdown=0.82)
        self.assertTrue(res["duration_fit_limited"])
        self.assertFalse(res["speech_truncated"])

        actual_dur = measure_wav_duration(out)
        self.assertGreater(actual_dur, 2.0)
        self.assertAlmostEqual(actual_dur, 2.4, delta=0.08)

    def test_06_segment_07_regression_preservation(self):
        """Segment 07 must remain 'बस, भरोसा रख!' and authentic Chinese '就这样，相信我。'."""
        trans_path = Path("translation_qa_phase22.json")
        if trans_path.is_file():
            data = json.loads(trans_path.read_text(encoding="utf-8"))
            seg7_res = data.get("segment_07_resolution", {})
            self.assertEqual(seg7_res.get("resolved_chinese_source"), "就这样，相信我。")
            self.assertIn("बस, भरोसा रख!", seg7_res.get("phase22_corrected_translation", ""))

            seg7 = next((s for s in data.get("segments", []) if s.get("segment_index") == 7), None)
            if seg7:
                self.assertEqual(seg7.get("source_text_chinese"), "就这样，相信我。")
                self.assertEqual(seg7.get("hindi_translation"), "बस, भरोसा रख!")

    def test_07_segments_06_and_17_remain_warnings(self):
        """Segments 06 and 17 must remain classified as WARNING in Phase 22 & Phase 23 QA manifests."""
        for fname in ("lipsync_report_phase22.json", "lipsync_report_phase23.json"):
            lipsync_path = Path(fname)
            if lipsync_path.is_file():
                data = json.loads(lipsync_path.read_text(encoding="utf-8"))
                segs = {s["segment_index"]: s["classification"] for s in data.get("segments", [])}
                self.assertEqual(segs.get(6), "WARNING")
                self.assertEqual(segs.get(7), "WARNING")
                self.assertEqual(segs.get(17), "WARNING")
                if fname == "lipsync_report_phase23.json":
                    self.assertEqual(segs.get(8), "PASS")
                    self.assertEqual(segs.get(14), "PASS")
                    self.assertEqual(segs.get(26), "PASS")
                    self.assertEqual(data.get("fail_count"), 0)

    def test_08_phase22_and_phase23_verdict_consistency(self):
        """Baseline Phase 22 and Phase 23 manifests must contain 28 segments with 0 collisions and 0 truncations."""
        for fname in ("alignment_report_phase22.json", "alignment_report_phase23.json"):
            align_path = Path(fname)
            if align_path.is_file():
                data = json.loads(align_path.read_text(encoding="utf-8"))
                self.assertEqual(len(data), 28)
                for s in data:
                    self.assertTrue(s["math_reconciled"])
                    self.assertFalse(s.get("clipping_detected", True))
                    self.assertGreaterEqual(s.get("gap_to_next_dialogue", 0), 0.0)

    def test_09_non_destructive_silence_trimming_priority(self):
        """Leading and trailing silence are removed before time-stretching without clipping active speech."""
        src = self.tmp / "padded_speech.wav"
        out = self.tmp / "fitted_speech.wav"
        # 0.25s leading silence + 1.0s active tone + 0.35s trailing silence = 1.60s total
        generate_synthetic_tone(
            src,
            duration=1.0,
            freq=380.0,
            lead_silence_sec=0.25,
            trail_silence_sec=0.35,
        )
        res = fit_audio(src, out, target=1.0, trim_silence=True)
        self.assertAlmostEqual(res["source_duration"], 1.60, delta=0.03)
        self.assertAlmostEqual(res["trimmed_duration"], 1.03, delta=0.05)
        self.assertAlmostEqual(res["leading_silence_duration"], 0.235, delta=0.03)
        self.assertAlmostEqual(res["trailing_silence_duration"], 0.335, delta=0.03)
        # Since trimmed duration (~1.03s) fits target (1.0s) with only ~1.03x tempo instead of 1.60x:
        self.assertLess(res["applied_tempo"], 1.08)
        self.assertFalse(res["duration_fit_limited"])
        self.assertFalse(res["speech_truncated"])

    def test_10_lipsync_qa_classification_rules(self):
        """Verify PRD §24 & §28.5 lip-sync classification rules (PASS, WARNING, FAIL, NOT_VERIFIABLE)."""
        # Off-screen / wide-shot -> NOT_VERIFIABLE
        unver = classify_lipsync_segment(
            segment_index=0,
            speaker_id="SPEAKER_02",
            speech_onset_sec=0.32,
            speech_end_sec=1.20,
            visible_mouth_onset_sec=0.32,
            visible_mouth_end_sec=1.20,
            max_face_coverage=0.008,
            shot_type="wide shot / small face",
        )
        self.assertEqual(unver["classification"], "NOT_VERIFIABLE")

        # Close-up within 120ms -> PASS with high confidence
        passed = classify_lipsync_segment(
            segment_index=8,
            speaker_id="SPEAKER_01",
            speech_onset_sec=16.20,
            speech_end_sec=16.60,
            visible_mouth_onset_sec=16.20,
            visible_mouth_end_sec=16.55,
            max_face_coverage=0.11,
            shot_type="close-up / medium close-up",
        )
        self.assertEqual(passed["classification"], "PASS")
        self.assertGreaterEqual(passed["confidence"], 0.85)

        # Moderate offset (200ms) -> WARNING
        warned = classify_lipsync_segment(
            segment_index=6,
            speaker_id="SPEAKER_01",
            speech_onset_sec=11.83,
            speech_end_sec=14.55,
            visible_mouth_onset_sec=11.83,
            visible_mouth_end_sec=14.35,
            max_face_coverage=0.06,
            shot_type="medium shot",
        )
        self.assertEqual(warned["classification"], "WARNING")

        # Large offset (600ms) -> FAIL
        failed = classify_lipsync_segment(
            segment_index=99,
            speaker_id="SPEAKER_01",
            speech_onset_sec=10.0,
            speech_end_sec=12.60,
            visible_mouth_onset_sec=10.0,
            visible_mouth_end_sec=12.00,
            max_face_coverage=0.09,
            shot_type="close-up",
        )
        self.assertEqual(failed["classification"], "FAIL")

    def test_11_doctor_diagnostics_report_structure(self):
        """Verify python -m backend.doctor returns structured dependency items per PRD §10 & §35."""
        report = run_doctor()
        self.assertIn("items", report)
        self.assertIn("summary", report)
        names = {item["name"] for item in report["items"]}
        for expected in ("python", "pip", "ffmpeg", "ffprobe", "librubberband", "opendub_stdlib_dsp"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
