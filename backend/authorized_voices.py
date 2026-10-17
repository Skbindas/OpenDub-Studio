"""Private user-supplied references; source attestations are not model QA."""
import copy
import json
from pathlib import Path
import shutil
import uuid

from .voice_bank_quality import audio_metrics, fingerprint, reviewed_eligibility, write_report
from .voice_catalog import reference_blockers


def import_reference(data_root: Path, source: Path, name: str, transcript: str,
                     permission: bool, single_speaker: bool, clean_background: bool) -> dict:
    name, transcript = name.strip(), transcript.strip()
    if not 1 <= len(name) <= 60 or not 1 <= len(transcript) <= 4000:
        raise ValueError('Enter a voice name and the exact words in this recording.')
    if not all((permission, single_speaker, clean_background)):
        raise ValueError('Confirm permission, one speaking voice and a clean background before import.')
    source=source.resolve()
    if not source.is_file() or source.stat().st_size > 8*1024*1024:
        raise ValueError('Use a WAV reference up to 8 MB; original video uploads have separate rules.')
    import soundfile as sf
    if sf.info(source).format != 'WAV':
        raise ValueError('Use a WAV recording for the reference.')
    metrics=audio_metrics(source)
    if not 3 <= metrics['duration_sec'] <= 10.01:
        raise ValueError('The voice engine needs 3–10 seconds of continuous, complete speech.')
    if metrics['rms_dbfs'] < -60 or metrics.get('fixed_tone_suspected') or metrics['clipped_fraction'] > .001:
        raise ValueError('This reference is silent, tonal or clipped. Choose a clearer recording.')
    vid='user_'+uuid.uuid4().hex
    folder=data_root/'voice-bank-audit/user'/vid
    folder.mkdir(parents=True,exist_ok=False)
    target=folder/'reference.wav'
    shutil.copy2(source,target)
    record={'voice_id':vid,'origin':'user_supplied','display_name':name,
            'reference_path':str(target.resolve()),'sha256':fingerprint(target),'metrics':metrics,
            'permissions':{'private_dubbing_permission_attested':True,'confirmed_by':'user',
                           'public_distribution_verified':False},
            'audit':{'status':'single_speaker_candidate','speech_text':transcript,
                     'method':'user_reviewed_upload','speaker_count_detected':None,
                     'user_confirmed_single_speaker':True,'automatic_asr_performed':False,
                     'automatic_diarization_performed':False},
            'review':{'single_speaker':True,'speech_present':True,'background_clean':True},
            'perceived_voice':{'type':'unknown','age_band':'unknown'},
            'clone':{'status':'not_tested'},'eligible_for_defaults':False,'audition_acceptance':{}}
    write_report(data_root/'voice-bank-audit/records'/(vid+'.json'),record)
    return record


def load_authorized_voices(data_root: Path) -> list[dict]:
    rows=[]
    allowed=(data_root/'voice-bank-audit/user').resolve()
    for path in sorted((data_root/'voice-bank-audit/records').glob('user_*.json')):
        try:
            record=json.loads(path.read_text(encoding='utf8'))
            ref=Path(record['reference_path']).resolve()
            if record.get('origin')!='user_supplied' or record.get('voice_id')!=path.stem:
                continue
            if not ref.is_relative_to(allowed) or not ref.is_file() or fingerprint(ref)!=record['sha256']:
                continue
            eligible,blockers=reviewed_eligibility(record)
            row={'character_id':record['voice_id'],'character_name':record['display_name'],
                 'display_name':record['display_name'],'gender':'unknown','age_group':'unknown',
                 'duration_sec':record['metrics']['duration_sec'],'sample_available':True,
                 'reference_path':str(ref),'origin':'user_supplied','permissions':record['permissions'],
                 'selection_blockers':reference_blockers(record),'eligible_for_defaults':eligible,
                 'review_blockers':blockers,'repairs':[],'source_audio_url':None}
            for key in ('audit','review','clone','perceived_voice'):row[key]=copy.deepcopy(record.get(key,{}))
            acceptance=record.get('audition_acceptance',{});output=Path(row['clone'].get('file',''))
            row['audition_accepted']=(acceptance.get('status')=='user_accepted'
                and output.is_file() and acceptance.get('output_sha256')==row['clone'].get('output_sha256')
                and fingerprint(output)==acceptance.get('output_sha256'))
            rows.append(row)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return rows
