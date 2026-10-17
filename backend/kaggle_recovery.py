"""Conservative bounded recovery: reconcile first, retain completed units."""
import json
import time
from pathlib import Path
from . import kaggle_jobs as jobs
from .kaggle_tasks import _collect,RemoteWaiting
from .kaggle_transport import kernel_status,ProviderError,run,dataset_ready
from .kaggle_lock import account_lock
from .compute_settings import read_settings
from .kaggle_models import ensure_private_model,ModelPending


def wake_parent(base,job):
    settings=read_settings(base);task=json.loads(job['request'])
    if settings['provider']!='kaggle' or settings['username']!=task['username'] or job['state']=='detached':return
    parent=job.get('parent_job_id')
    if not parent:return
    from . import app as studio
    with studio.connect(studio.DB_PATH) as conn:
        changed=conn.execute("UPDATE jobs SET status='queued',claimed_by=NULL,claimed_at=NULL,message='Kaggle checkpoint ready; resuming retained work.',updated_at=? WHERE id=? AND status='waiting' AND cancel_requested=0",(studio.now(),parent)).rowcount
        if changed:conn.execute("UPDATE projects SET status='processing',updated_at=? WHERE id=?",(studio.now(),Path(base).name))


def reconcile(base,job_id,manual_retry=False):
    job=jobs.get(base,job_id);task=json.loads(job['request']);settings=read_settings(base)
    with account_lock(base,task['username']):
        if job['state']=='completed':wake_parent(base,job);return job
        if job['kernel_state']=='not_submitted':
            try:ensure_private_model(base,settings,task['operation'],task['model'])
            except ModelPending as exc:return jobs.update(base,job_id,'waiting',str(exc))
            # Source/model dataset processing may have completed while the parent was parked.
            if job['dataset_state'] in {'created','uploading'}:
                status=run(task['username'],['datasets','status',job['dataset_handle']],timeout=60).lower()
                if dataset_ready(status):
                    jobs.update(base,job_id,'prepared','Input ready; resume the unsubmitted task.',dataset_state='created');wake_parent(base,jobs.get(base,job_id))
            elif job['dataset_state']=='prepared':
                jobs.update(base,job_id,'prepared','Model input ready; resume the retained task.');wake_parent(base,jobs.get(base,job_id))
            return jobs.get(base,job_id)
        try:state=kernel_status(task['username'],job['kernel_handle'])
        except ProviderError as exc:
            return jobs.update(base,job_id,'waiting' if exc.kind=='quota' else 'submission_uncertain',str(exc))
        if state in {'running','queued'}:return jobs.update(base,job_id,state,'Actual Kaggle status: '+state)
        if state not in {'completed','failed','cancelled'}:return jobs.update(base,job_id,'submission_uncertain','Unknown remote status; duplicate submission blocked.')
        if state=='cancelled':return jobs.update(base,job_id,'review_required','Remote cancellation confirmed. Automatic restart is disabled for cancelled work.')
        observed=job.get('terminal_observed_at') or time.time()
        if not job.get('terminal_observed_at'):jobs.set_control(base,job_id,terminal_observed_at=observed)
        kind=None
        try:
            _collect(base,job);wake_parent(base,jobs.get(base,job_id));return jobs.get(base,job_id)
        except RemoteWaiting:
            # A returned failure receipt distinguishes setup/model/code failures from session/capacity failures.
            current=jobs.get(base,job_id)
            if 'session failure' in current['message'] or 'capacity failure' in current['message']:kind='session'
            else:return current
        except Exception:
            # Errored session with no durable receipt: one bounded, delayed recovery is allowed.
            if state=='failed':kind='session'
            else:return jobs.update(base,job_id,'review_required','Remote output verification failed. No automatic retry of content/integrity errors.')
        budget=min(3,max(0,int(settings.get('max_session_retries',2))))
        if kind=='session' and (manual_retry or settings.get('automatic_resume')) and job['attempts']<=budget:
            delay=min(300,30*2**max(0,job['attempts']-1))
            if not manual_retry and time.time()-observed<delay:
                return jobs.update(base,job_id,'review_required','Session recovery pending; terminal attempt confirmed, completed units retained.')
            jobs.update(base,job_id,'review_required','Remote attempt is terminal. Session recovery retains completed units.')
            fresh=jobs.retry_terminal(base,job_id)
            wake_parent(base,fresh)
            return fresh
        return jobs.update(base,job_id,'review_required','Session retry limit reached. Completed units retained; choose local or review account capacity.')
