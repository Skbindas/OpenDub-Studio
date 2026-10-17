"""Restart-safe status reconciler. It never submits a new notebook automatically."""
import threading
import time
import json
from pathlib import Path
from .compute_settings import read_settings
from . import kaggle_jobs as jobs
from .kaggle_service import reconcile

_started=False
_lock=threading.Lock()


def start(projects_root):
    global _started
    with _lock:
        if _started:return
        _started=True
    def watch():
        from .compute_routes import launch_control
        while True:
            for base in Path(projects_root).glob('*'):
                try:
                    if not (base/'kaggle/jobs.sqlite3').is_file() or read_settings(base)['provider']!='kaggle':continue
                    for job in jobs.list_jobs(base):
                        retryable=job['state']=='review_required' and any(s in job['message'] for s in ('session failure','capacity failure','session ended without','Session recovery pending'))
                        if (job['state'] in {'prepared','submitting','submission_uncertain','waiting','queued','running','downloading'} or retryable) and time.time()-job['updated_at']>=60:
                            def check(base=base,job_id=job['id']):
                                detail=jobs.get(base,job_id)
                                if json.loads(detail['request']).get('schema_version')==2:
                                    from .kaggle_recovery import reconcile as reconcile_task
                                    return reconcile_task(base,job_id)
                                from .kaggle_lock import account_lock
                                with account_lock(base,json.loads(detail['request'])['username']):return reconcile(base,job_id)
                            launch_control(base,job['id'],check)
                except Exception:
                    # No provider logs or credentials are emitted by this watcher.
                    pass
            time.sleep(15)
    threading.Thread(target=watch,name='opendub-kaggle-reconciler',daemon=True).start()
