"""Local account setup and explicit bounded cloud-job controls."""
import json
import threading
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from .compute_settings import read_settings,write_settings
from .kaggle_credentials import credential_status,save_credentials
from . import kaggle_jobs as jobs
from . import kaggle_service as service

router=APIRouter()
_control_lock=threading.Lock()
_active_controls=set()


def launch_control(base,job_id,operation):
    key=(str(base),job_id)
    with _control_lock:
        if key in _active_controls:return False
        _active_controls.add(key)
    def execute():
        try:operation()
        except Exception as exc:
            from .kaggle_tasks import waiting_error
            if waiting_error(exc):return
            current=jobs.get(base,job_id)
            if current['state'] not in {'submitting','submission_uncertain','waiting','detached'}:
                jobs.update(base,job_id,'review_required','Operation stopped; inspect setup/output and preserve completed work.')
        finally:
            with _control_lock:_active_controls.discard(key)
    threading.Thread(target=execute,name='opendub-kaggle-control',daemon=True).start()
    return True


def local_request(request):
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.headers.get('host'):
        raise HTTPException(403,'Cross-origin account or compute changes are blocked.')
    if request.headers.get('sec-fetch-site')=='cross-site':raise HTTPException(403,'Cross-site compute changes are blocked.')


def project(project_id):
    from . import app as studio
    item=studio.get_project(studio.DB_PATH,project_id)
    if not item:raise HTTPException(404,'Project not found.')
    return studio,studio.project_dir(project_id),item


@router.get('/api/compute/kaggle')
def kaggle_status():return credential_status()


@router.post('/api/compute/kaggle/credentials')
async def credentials(request:Request):
    local_request(request)
    try:
        body=await request.json()
        if not isinstance(body,dict) or any(not isinstance(body.get(k,''),str) for k in ('username','token','legacy_key')):raise ValueError()
        return save_credentials(body.get('username',''),body.get('token',''),body.get('legacy_key',''))
    except (ValueError,RuntimeError) as exc:
        raise HTTPException(400,str(exc) or 'Invalid credential request.') from None
    except Exception:
        raise HTTPException(503,'OS credential storage is unavailable; no plaintext credential was saved.') from None


class Settings(BaseModel):
    provider:Literal['local','kaggle']='local'
    username:str=Field(default='',max_length=64)
    accelerator:str='NvidiaTeslaT4'
    allow_media_upload:bool=False
    allow_model_upload:bool=False


@router.get('/api/projects/{project_id}/compute')
def read(project_id:str):
    _,base,_=project(project_id)
    return {'settings':read_settings(base),'account':credential_status(),'jobs':jobs.list_jobs(base)}


@router.put('/api/projects/{project_id}/compute')
def write(project_id:str,body:Settings,request:Request):
    local_request(request);studio,base,_=project(project_id)
    with studio.connect(studio.DB_PATH) as conn:
        active=conn.execute("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','claimed','running','retrying')",(project_id,)).fetchone()
    cloud_active=[j for j in jobs.list_jobs(base) if j['state'] in {'submitting','waiting','queued','running','downloading','submission_uncertain'}]
    if active or (cloud_active and body.provider!='local'):
        raise HTTPException(409,'Pause/reconcile active work before changing compute providers.')
    try:
        saved=write_settings(base,**body.model_dump())
        if body.provider=='local':
            for job in cloud_active:jobs.update(base,job['id'],'detached','Local processing selected. Remote notebook may still run; monitor it on Kaggle. It has not been cancelled.')
        return saved
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


class Crop(BaseModel):
    operation:Literal['transcription','separation']
    start:float=Field(ge=0)
    end:float=Field(gt=0)
    model_size:Literal['tiny','base','small','medium','large-v3']='small'
    language:str|None=Field(default=None,max_length=16)


@router.post('/api/projects/{project_id}/compute/jobs')
def create(project_id:str,body:Crop,request:Request):
    local_request(request);studio,base,item=project(project_id)
    if not item.get('source_path'):raise HTTPException(409,'Upload a source first.')
    duration=(item.get('duration_ms') or 0)/1000
    if body.end>duration+.01:raise HTTPException(400,'Crop exceeds the source duration.')
    try:
        job=service.create_request(base,(studio.ROOT/item['source_path']).resolve(),**body.model_dump())
        return {k:v for k,v in job.items() if k!='request'}
    except (ValueError,RuntimeError) as exc:raise HTTPException(400,str(exc)) from None


@router.post('/api/projects/{project_id}/compute/jobs/{job_id}/{action}')
def action(project_id:str,job_id:str,action:Literal['prepare','submit','reconcile','retry'],request:Request):
    local_request(request);studio,base,item=project(project_id)
    try:
        detail=jobs.get(base,job_id)
    except ValueError as exc:raise HTTPException(404,str(exc)) from None
    if json.loads(detail['request']).get('schema_version')==2:
        from .kaggle_recovery import reconcile
        if action in {'prepare','submit'}:raise HTTPException(409,'Resume Auto-Dub to submit this retained pipeline task. Reconcile checks existing remote work.')
        operation=lambda:reconcile(base,job_id,manual_retry=action=='retry')
    elif action=='prepare':
        source=(studio.ROOT/item['source_path']).resolve()
        operation=lambda:service.prepare_request(base,job_id,source)
    elif action=='submit':operation=lambda:service.submit(base,job_id)
    elif action=='retry':operation=lambda:service.retry(base,job_id)
    else:operation=lambda:service.reconcile(base,job_id)
    if json.loads(detail['request']).get('schema_version')!=2:
        original=operation
        def operation():
            from .kaggle_lock import account_lock
            with account_lock(base,json.loads(detail['request'])['username']):return original()
    if not launch_control(base,job_id,operation):raise HTTPException(409,'This job already has a control operation in progress.')
    return {'accepted':True,'job_id':job_id,'action':action}
