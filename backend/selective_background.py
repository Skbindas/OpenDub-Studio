"""Keep original music/vocals outside reviewed dialogue using bounded PCM blocks."""
import math,uuid
from pathlib import Path
import numpy as np,soundfile as sf


def preserve_non_dialogue_audio(source,stem,output,intervals,padding=.1,fade=.03):
    from .kaggle_tasks import project_for
    if project_for(output):
        from .kaggle_operations import background
        return background(source,stem,output,intervals,padding,fade)
    source,stem,output=map(Path,(source,stem,output))
    original,background=sf.info(source),sf.info(stem)
    if (original.samplerate,original.channels,original.frames)!=(background.samplerate,background.channels,background.frames):
        raise ValueError('Background stem must match source samples, channels and rate before selective preservation.')
    windows=[]
    for start,end in sorted(intervals):
        if not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end<=original.duration+.02:
            raise ValueError('Invalid dialogue interval; source background was retained.')
        left=max(0,round((start-padding)*original.samplerate));right=min(original.frames,round((end+padding)*original.samplerate))
        if windows and left<=windows[-1][1]:windows[-1]=(windows[-1][0],max(right,windows[-1][1]))
        else:windows.append((left,right))
    temporary=output.with_name(output.stem+'.'+uuid.uuid4().hex+'.pending.wav')
    output.parent.mkdir(parents=True,exist_ok=True);window_index=0;fade_frames=max(1,round(fade*original.samplerate))
    try:
        with sf.SoundFile(source) as a,sf.SoundFile(stem) as b,sf.SoundFile(temporary,'w',samplerate=original.samplerate,
                channels=original.channels,subtype='PCM_16',format='RF64' if original.frames*original.channels*2>0xffff0000 else 'WAV') as out:
            for offset in range(0,original.frames,65536):
                count=min(65536,original.frames-offset)
                src=a.read(count,dtype='int16',always_2d=True);bg=b.read(count,dtype='int16',always_2d=True)
                if len(src)!=count or len(bg)!=count:raise ValueError('Truncated audio; previous background retained.')
                weights=np.zeros(count,dtype=np.float32)
                while window_index<len(windows) and windows[window_index][1]<=offset:window_index+=1
                index=window_index
                while index<len(windows) and windows[index][0]<offset+count:
                    left,right=windows[index];first,last=max(offset,left),min(offset+count,right)
                    frames=np.arange(first,last)
                    weights[first-offset:last-offset]=np.minimum(1,np.minimum((frames-left+1)/fade_frames,(right-frames)/fade_frames))
                    index+=1
                pcm=np.rint(src.astype(np.float32)*(1-weights[:,None])+bg.astype(np.float32)*weights[:,None]).clip(-32768,32767).astype(np.int16)
                out.write(pcm)
        temporary.replace(output)
    finally:temporary.unlink(missing_ok=True)
    return {'original_outside_dialogue_retained':True,'gain_db':0,'dialogue_windows':len(windows),
            'transition_padding_sec':padding,'crossfade_sec':fade,'source_sample_count':original.frames,
            'notice':'Original soundtrack retained outside reviewed dialogue; separation artifacts inside dialogue still need listening review.'}
