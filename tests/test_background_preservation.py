from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from backend.background_preservation import (
    duck_source_audio,
    extract_full_fidelity_audio,
    generate_ducking_control_signal,
    preserve_background_audio,
    probe_audio_duration,
)


class BackgroundPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which("ffmpeg")
        cls.ffprobe = shutil.which("ffprobe")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("FFmpeg/ffprobe required for background preservation tests")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.analysis_dir = self.root / "analysis"
        self.output_dir = self.root / "output"
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate a synthetic 4-second source audio (48kHz stereo sine wave)
        self.source_audio = self.analysis_dir / "source_16k_mono.wav"
        subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=4.0",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(self.source_audio),
            ],
            check=True,
            capture_output=True,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_probe_audio_duration(self):
        dur = probe_audio_duration(self.source_audio)
        self.assertAlmostEqual(dur, 4.0, delta=0.1)

    def test_generate_ducking_control_signal(self):
        ctl_path = self.output_dir / "control.wav"
        intervals = [(1.0, 2.5)]
        generate_ducking_control_signal(ctl_path, duration_sec=4.0, intervals=intervals, sample_rate=48000)
        self.assertTrue(ctl_path.is_file())
        self.assertGreater(ctl_path.stat().st_size, 1000)

        with wave.open(str(ctl_path), "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), 48000)
            n_frames = w.getnframes()
            self.assertEqual(n_frames, 48000 * 4)

            # Check samples before dialogue window (silence)
            w.setpos(int(0.5 * 48000))
            frame_pre = w.readframes(1)
            val_pre = struct.unpack("<h", frame_pre)[0]
            self.assertEqual(val_pre, 0)

            # Check samples during dialogue window (active ~30000)
            w.setpos(int(1.5 * 48000))
            frame_mid = w.readframes(1)
            val_mid = struct.unpack("<h", frame_mid)[0]
            self.assertEqual(val_mid, 30000)

            # Check samples after dialogue window (silence)
            w.setpos(int(3.5 * 48000))
            frame_post = w.readframes(1)
            val_post = struct.unpack("<h", frame_post)[0]
            self.assertEqual(val_post, 0)

    def test_duck_source_audio_preserves_duration_and_non_destructive(self):
        output_wav = self.output_dir / "ducked.wav"
        intervals = [(1.0, 2.0)]
        orig_hash_stat = self.source_audio.stat().st_size

        res = duck_source_audio(
            source_audio=self.source_audio,
            output_path=output_wav,
            intervals=intervals,
            duck_db=-18.0,
            attack_ms=50.0,
            release_ms=150.0,
        )

        self.assertTrue(output_wav.is_file())
        self.assertAlmostEqual(res["output_duration"], 4.0, delta=0.2)
        self.assertEqual(res["intervals_ducked"], 1)
        self.assertEqual(res["method"], "smooth_sidechain_ducking")

        # Verify source audio was not modified or overwritten
        self.assertEqual(self.source_audio.stat().st_size, orig_hash_stat)

    def test_duck_source_audio_empty_intervals_is_passthrough(self):
        output_wav = self.output_dir / "ducked_empty.wav"
        res = duck_source_audio(
            source_audio=self.source_audio,
            output_path=output_wav,
            intervals=[],
        )
        self.assertTrue(output_wav.is_file())
        self.assertEqual(res["intervals_ducked"], 0)
        self.assertEqual(res["method"], "passthrough")

    def test_preserve_background_audio_mode_ducking_with_manifest_sync(self):
        # Create dialogue_manifest.json with dialogue units
        manifest_path = self.analysis_dir / "dialogue_manifest.json"
        manifest_data = {
            "schema_version": 1,
            "units": [
                {
                    "segment_index": 0,
                    "start_sec": 0.5,
                    "end_sec": 1.5,
                    "source_text": "Hello",
                },
                {
                    "segment_index": 1,
                    "start_sec": 2.2,
                    "end_sec": 3.2,
                    "source_text": "World",
                },
            ],
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        result = preserve_background_audio(
            project_root=self.root,
            mode="ducking",
            duck_db=-18.0,
            attack_ms=50.0,
            release_ms=150.0,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["mode"], "ducking")
        self.assertEqual(result["dialogue_intervals_count"], 2)

        bg_file = Path(result["background_audio"])
        self.assertTrue(bg_file.is_file())
        self.assertGreater(bg_file.stat().st_size, 1000)

        # Verify metadata file was written
        meta_file = self.output_dir / "background_metadata.json"
        self.assertTrue(meta_file.is_file())
        saved_meta = json.loads(meta_file.read_text(encoding="utf-8"))
        self.assertEqual(saved_meta["mode"], "ducking")

        # Verify dialogue_manifest.json was updated with dialogue_removal state
        updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for unit in updated_manifest["units"]:
            self.assertIn("dialogue_removal", unit)
            self.assertEqual(unit["dialogue_removal"]["status"], "completed")
            self.assertEqual(unit["dialogue_removal"]["mode"], "ducking")

    def test_missing_separation_model_does_not_claim_background_preservation(self):
        with self.assertRaisesRegex(RuntimeError,"Background separation unavailable"):
            preserve_background_audio(
                project_root=self.root,
                mode="separation",
                model_filename="non_existent_uvr_model.onnx",
            )
        self.assertFalse((self.root/'output/background_preserved.wav').exists())

    def test_preserve_background_audio_mode_user_stem(self):
        # Create a synthetic user-supplied background WAV
        user_stem = self.root / "my_background_track.wav"
        subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=550:sample_rate=48000:duration=4.0",
                "-c:a",
                "pcm_s16le",
                str(user_stem),
            ],
            check=True,
            capture_output=True,
        )

        result = preserve_background_audio(
            project_root=self.root,
            mode="user_stem",
            user_stem_path=str(user_stem),
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["mode"], "user_stem")
        self.assertTrue(Path(result["background_audio"]).is_file())


if __name__ == "__main__":
    unittest.main()
def test_completed_separation_reuses_only_matching_source_pcm(tmp_path, monkeypatch):
    import json
    import numpy as np
    import soundfile as sf
    import backend.background_preservation as bg
    analysis=tmp_path/'analysis'; folder=analysis/'separation';folder.mkdir(parents=True)
    source=tmp_path/'source.wav'; original=folder/'original_mix.wav'
    data=np.zeros((48000,2),dtype='float32')
    for file in (source,original,folder/'vocals.wav',folder/'instrumental.wav'):
        sf.write(file,data,48000,subtype='PCM_16')
    report={'status':'completed','model':'UVR-MDX-NET-Inst_HQ_3.onnx','original_mix':str(original),
            'dialogue_candidate':str(folder/'vocals.wav'),'background_candidate':str(folder/'instrumental.wav')}
    (analysis/'separation.json').write_text(json.dumps(report))
    monkeypatch.setattr(bg,'_separate_single',lambda *args: (_ for _ in ()).throw(RuntimeError('new inference')))
    assert bg.separate_dialogue_candidate(source,folder)['reused']
    sf.write(source,np.ones((48000,2),dtype='float32')*.1,48000,subtype='PCM_16')
    import pytest
    with pytest.raises(RuntimeError,match='new inference'):
        bg.separate_dialogue_candidate(source,folder)
