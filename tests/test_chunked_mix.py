import json
import numpy as np
import soundfile as sf
import pytest
from backend.chunked_mix import render_mix_window, stitch_mix
from backend.chunked_asr import partition


def test_window_mix_preserves_background_and_spanning_dialogue(tmp_path):
    sr = 48000
    frames = sr*3
    original = np.full((frames,2), .125, np.float32)
    bg = tmp_path / "bg.wav"
    voice = tmp_path / "voice.wav"
    sf.write(bg,original,sr,subtype="FLOAT")
    sf.write(voice,np.full((sr,2),.0625,np.float32),sr,subtype="FLOAT")
    outputs = []
    for chunk in partition(3,1,0):
        spec = dict(chunk, background=str(bg), clips=[{"start_frame":round(.5*sr),"frames":sr,"file":str(voice)}])
        path = tmp_path / f"{chunk['id']}.wav"
        render_mix_window(spec,path)
        outputs.append({"payload":{"mix":str(path)}})
    output = tmp_path / "mix.wav"
    stitch_mix(outputs,output,frames)
    data,_=sf.read(output,dtype="float32",always_2d=True)
    expected=original.copy()
    expected[round(.5*sr):round(1.5*sr)] += .0625
    assert np.array_equal(data,expected)


def test_clip_that_would_clip_does_not_publish_window(tmp_path):
    bg=tmp_path / "bg.wav"
    voice=tmp_path / "voice.wav"
    sf.write(bg,np.full((4800,2),.75,np.float32),48000,subtype="FLOAT")
    sf.write(voice,np.full((4800,2),.5,np.float32),48000,subtype="FLOAT")
    output=tmp_path / "out.wav"
    output.write_bytes(b"old verified mix")
    spec={"start":0,"end":.1,"background":str(bg),"clips":[{"start_frame":0,"frames":4800,"file":str(voice)}]}
    with pytest.raises(RuntimeError,match="clip"):
        render_mix_window(spec,output)
    assert output.read_bytes()==b"old verified mix"


def test_stitch_rejects_incomplete_duration_and_keeps_previous_mix(tmp_path):
    window=tmp_path / "window.wav"
    sf.write(window,np.zeros((4800,2),np.float32),48000,subtype="FLOAT")
    out=tmp_path / "previous.wav"
    out.write_bytes(b"keep")
    with pytest.raises(RuntimeError,match="timeline"):
        stitch_mix([{"payload":{"mix":str(window)}}],out,48000)
    assert out.read_bytes()==b"keep"
