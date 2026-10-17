"""Local user-reference intake and secret-free first-run guidance."""
from pathlib import Path
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router=APIRouter()


@router.get('/api/setup/guide')
def setup_guide():
    from . import app as studio
    from fastapi.responses import FileResponse
    return FileResponse(studio.ROOT/'docs/QUICK_START.md',media_type='text/plain; charset=utf-8')


@router.post('/api/voices/import')
async def import_voice(file: UploadFile=File(...), name: str=Form(...), transcript: str=Form(...),
                       permission: bool=Form(False), single_speaker: bool=Form(False),
                       clean_background: bool=Form(False)):
    from . import app as studio
    from .authorized_voices import import_reference
    if Path(file.filename or '').suffix.lower()!='.wav':
        raise HTTPException(422,'Choose a 3–10 second WAV recording. This limit is for references, not source videos.')
    folder=studio.DATA_ROOT/'voice-bank-audit/uploads'
    folder.mkdir(parents=True,exist_ok=True)
    staging=folder/(uuid.uuid4().hex+'.wav')
    try:
        total=0
        with staging.open('xb') as out:
            while chunk:=await file.read(65536):
                total+=len(chunk)
                if total>8*1024*1024:raise HTTPException(413,'Reference file exceeds 8 MB.')
                out.write(chunk)
        row=import_reference(studio.DATA_ROOT,staging,name,transcript,permission,single_speaker,clean_background)
        return {'voice_id':row['voice_id'],'display_name':row['display_name'],
                'audio_url':f"/api/voices/{row['voice_id']}/preview",'clone_status':'not_tested',
                'status':'reference_imported_audition_pending','eligible_for_defaults':False,
                'notice':'Saved privately. Source statements are your review; no automatic speech/identity analysis or clone approval was fabricated. Choose and lock this reference for a short audition before delivery.'}
    except HTTPException:raise
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    except RuntimeError:raise HTTPException(422,'The WAV could not be decoded. Use a valid clear recording.') from None
    finally:
        await file.close()
        if staging.resolve().is_relative_to(folder.resolve()):staging.unlink(missing_ok=True)


@router.get('/api/setup/status')
def get_setup_status(fresh: bool=False):
    from . import app as studio
    from .authorized_voices import load_authorized_voices
    from .clone_runtime import clone_python
    from .setup_readiness import setup_status
    report=studio.system_diagnostics(fresh=fresh)
    result=setup_status(report,clone_environment=clone_python().is_file(),
                        separator_files=any((studio.ROOT/'runtime/models/separation').glob('*.ckpt')),
                        translation_configured=studio.semantic_provider_configured(),
                        owned_voices=len(load_authorized_voices(studio.DATA_ROOT)))
    result['checked_at']=report.get('checked_at')
    return result
