import shutil
import subprocess

import pytest

from backend.media import probe_media, verify_media_decode


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_truncated_faststart_movie_is_not_accepted_from_header(tmp_path):
    source = tmp_path / "good.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=96x64:rate=10:duration=3", "-f", "lavfi", "-i",
                    "sine=duration=3", "-c:v", "mpeg4", "-c:a", "aac",
                    "-movflags", "+faststart", str(source)], check=True)
    assert verify_media_decode(source)["status"] == "passed"
    broken = tmp_path / "truncated.mp4"
    data = source.read_bytes()
    broken.write_bytes(data[:int(len(data) * .7)])
    assert probe_media(broken)["duration_sec"] >= 3
    with pytest.raises(RuntimeError, match="decode|corrupt|incomplete"):
        verify_media_decode(broken)


def test_cancel_does_not_publish_a_validation_checkpoint(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not a movie")
    with pytest.raises(InterruptedError):
        verify_media_decode(source, cancelled=lambda: True)
