"""Evidence-backed character review and versioned, explicit voice configuration locks."""
import copy
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from .voice_bank_quality import safe_reference_windows
from .voice_profiles import normalize_voice_profile


def profile_hash(profile):
    profile=normalize_voice_profile(profile)
    return hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def voice_locked(character):
    lock=character.get('voice_lock',{})
    return bool(lock.get('status')=='locked' and lock.get('profile_sha256')==profile_hash(character.get('voice_profile'))
                and lock.get('source_speaker_id')==character.get('source_speaker_id')
                and lock.get('aliases',[])==sorted(character.get('aliases',[]))
                and lock.get('casting_label')==character.get('casting_label')
                and lock.get('voice_age_style')==character.get('voice_age_style')
                and not character.get('review_required',True))


def lock_voice(character,confirmed=False,reviewed_by='user'):
    if not confirmed:raise ValueError('Confirm the character and voice choice before locking.')
    if reviewed_by not in {'user','assistant_review','automated_test'}:raise ValueError('Unsupported review provenance')
    result=copy.deepcopy(character);profile=normalize_voice_profile(result.get('voice_profile'))
    if not profile.get('provider') or not (profile.get('voice_id') or profile.get('model_path')):
        raise ValueError('Choose a voice provider and voice ID/model first.')
    result['voice_profile']=profile;result['review_required']=False
    result['voice_lock']={'status':'locked','profile_sha256':profile_hash(profile),
                          'source_speaker_id':result.get('source_speaker_id'),'confirmed_by':reviewed_by,
                          'aliases':sorted(result.get('aliases',[])),'casting_label':result.get('casting_label'),
                          'voice_age_style':result.get('voice_age_style'),
                          'confirmed_at':datetime.now(timezone.utc).isoformat()}
    return result


def read(path,default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def overlap_evidence_hash(diarization):
    evidence={'source':diarization.get('identity_source_sha256'),
              'events':diarization.get('overlap_events',[]),'turns':diarization.get('regular_turns',[])}
    return hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()


def reference_matches_lock(profile,data_root):
    if profile.get('provider') not in {'omnivoice','cloned'}:return True
    voice_id=str(profile.get('voice_id') or '')
    if not voice_id or any(x in voice_id for x in ('/','\\','..')):return False
    try:
        record=read(Path(data_root)/'voice-bank-audit/records'/(voice_id+'.json'),{})
        reference=Path(record.get('reference_path',''))
        if not reference.is_file():return False
        audio_hash=hashlib.sha256(reference.read_bytes()).hexdigest()
        text_hash=hashlib.sha256(str(record.get('audit',{}).get('speech_text','')).encode()).hexdigest()
    except (OSError,ValueError,TypeError):return False
    return bool(profile.get('reference_sha256')==audio_hash and profile.get('reference_text_sha256')==text_hash)


def review_state(base,registry):
    base=Path(base);diar=read(base/'analysis/diarization.json',{});transcript=read(base/'analysis/transcript.json',{})
    chars=registry.get('characters',[]);cards=[];speakers={s['speaker_id']:s for s in diar.get('speakers',[])}
    links=registry.get('speaker_links',{})
    turns=transcript.get('segments',[])
    from .speaker_tools import current_tool_result
    traits=current_tool_result(base,read(base/'analysis/voice_traits.json',{}))
    disposition=read(base/'analysis/speaker_dispositions.json',{})
    choices=disposition.get('speakers',{}) if disposition.get('evidence_sha256')==overlap_evidence_hash(diar) else {}
    transcribed={r.get('speaker_id') for r in turns if str(r.get('text') or '').strip()}
    excluded={s:r for s,r in choices.items() if r.get('confirmed') and r.get('category') in {'music_or_singing','non_speech'} and s not in transcribed}
    active=set(speakers)-set(excluded)
    unresolved=[i for i,r in enumerate(turns) if not r.get('speaker_id') or r.get('speaker_review_required')]
    for char in chars:
        sid=char.get('source_speaker_id');speaker=speakers.get(sid,{})
        sids=sorted(s for s in active if links.get(s)==char.get('character_id') or (s==sid and s not in links))
        if not sids:continue
        rows=[r for r in diar.get('regular_turns',diar.get('turns',[])) if r['speaker_id'] in sids]
        windows=[w for s in sids for w in safe_reference_windows(diar,s,minimum=.4,maximum=8)]
        cards.append({**char,'speaker_ids':sids,'voice_locked':voice_locked(char) and reference_matches_lock(char.get('voice_profile') or {},base.parent.parent),'source_windows':sorted(windows,key=lambda w:w['end']-w['start'],reverse=True)[:3],
                      'trait_suggestion':traits.get('characters',{}).get(char['character_id']),
                      'first_seen':min((r['start'] for r in rows),default=None),
                      'speaking_seconds':round(sum(r['end']-r['start'] for r in rows),2),
                      'identity_method':speaker.get('identity_method','provisional_cluster'),
                      'vocal_profile':speaker.get('vocal_profile',{'vocal_type':'unknown'}),
                      'embedding_kind':speaker.get('embedding_kind','unavailable')})
    valid_chars={c['character_id'] for c in chars}
    mapped={s for s,c in links.items() if c in valid_chars};missing=sorted(active-mapped)
    untranscribed=sorted(active-transcribed)
    overlap_review=read(base/'analysis/speaker_overlap_review.json',{})
    approved=overlap_review.get('events',{}) if overlap_review.get('evidence_sha256')==overlap_evidence_hash(diar) else {}
    overlaps=diar.get('overlap_events',[])
    unresolved_overlaps=[i for i,e in enumerate(overlaps) if str(i) not in approved and len(set(e['speaker_ids'])&active)>1]
    raw=bool(diar.get('raw_overlap_available'))
    blocking=[]
    if not raw:blocking.append('Analyse with raw overlap preservation first.')
    if not chars:blocking.append('No speaking identities are registered yet.')
    if missing:blocking.append(f'{len(missing)} detected identities have no character mapping.')
    if unresolved:blocking.append(f'{len(unresolved)} dialogue turns need speaker review.')
    if untranscribed:blocking.append(f'{len(untranscribed)} detected speakers have no attributed transcript; review missing speech.')
    if unresolved_overlaps:blocking.append(f'{len(unresolved_overlaps)} overlap regions need listening and transcript review; automatic recovery is not certified.')
    locked=sum(c['voice_locked'] for c in cards)
    if locked<len(cards):blocking.append(f'{len(cards)-locked} character voice choices need confirmation/locking.')
    analysis=read(base/'analysis/analysis_manifest.json',{}).get('stages',{})
    auto=read(base/'auto_dub_status.json',{})
    units=read(base/'analysis/dialogue_manifest.json',{}).get('units',[])
    qa=read(base/'output/render_qa_report.json',{})
    steps=['source_media_validate','vocal_audio_prepare','transcription','speaker_diarization']
    statuses=[analysis.get(s,{}).get('status','pending') for s in steps]
    statuses.append('completed' if not blocking else 'awaiting_review' if speakers else 'pending')
    for name in ['translation','tts','timing']:
        values=[u.get(name,{}).get('status','pending') for u in units]
        statuses.append('completed' if values and all(v=='completed' for v in values) else 'running' if 'running' in values else 'pending')
    statuses.append('completed' if (base/'output/dubbed_audio_mix.wav').is_file() else 'pending')
    statuses.append('completed' if qa.get('status')=='PASSED' and any((base/'output').glob('*_dubbed.mp4')) else 'pending')
    return {'schema_version':1,'estimated_speakers':len(speakers),'active_speakers':len(active),'excluded_speakers':excluded,'cards':cards,'locked_voices':locked,
            'unresolved_turns':unresolved,'unmapped_speakers':missing,'raw_overlap_available':raw,
            'overlap_events':overlaps,'unresolved_overlap_events':unresolved_overlaps,'untranscribed_speakers':untranscribed,
            'ready_for_dubbing':not blocking,'blocking':blocking,
            'overlap_candidates':current_tool_result(base,read(base/'analysis/overlap_candidates.json',{})).get('events',{}),
            'flow_status':statuses,'processing_status':auto.get('status','pending'),
            'processing_message':auto.get('current_stage_label'),
            'turns':[{k:r.get(k) for k in ('start','end','text','speaker_id','speaker_review_required','speaker_review_reason','overlapping_speakers')}
                     for r in turns],
            'flow':['Upload and source check','Separate dialogue vocals','Transcribe with source timestamps',
                    'Detect speakers and overlaps','Review identities and lock voices','Translate into Hindi',
                    'Synthesize locked voices','Fit timing','Preserve original BGM/SFX and mix','Render and verify']}
