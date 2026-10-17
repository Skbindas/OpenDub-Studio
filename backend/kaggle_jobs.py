"""Durable notebook intent ledger; ambiguous submissions require reconciliation."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

TERMINAL = {'completed','failed','cancelled','review_required'}
SCHEMA = '''CREATE TABLE IF NOT EXISTS remote_jobs (
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, operation TEXT NOT NULL,
 state TEXT NOT NULL, request TEXT NOT NULL, dataset_handle TEXT NOT NULL,
 kernel_handle TEXT NOT NULL, dataset_state TEXT NOT NULL DEFAULT 'prepared',
 message TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS remote_attempts (
 job_id TEXT NOT NULL,attempt INTEGER NOT NULL,handle TEXT NOT NULL,state TEXT NOT NULL,
 created_at REAL NOT NULL,PRIMARY KEY(job_id,attempt));
'''


@contextmanager
def database(base):
    path = Path(base)/'kaggle/jobs.sqlite3'
    path.parent.mkdir(parents=True,exist_ok=True)
    conn = sqlite3.connect(path,timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        columns={r[1] for r in conn.execute('PRAGMA table_info(remote_jobs)')}
        for name,default in [('parent_job_id','NULL'),('kernel_state',"'not_submitted'")]:
            if name not in columns:conn.execute(f'ALTER TABLE remote_jobs ADD COLUMN {name} TEXT DEFAULT {default}')
        if 'terminal_observed_at' not in columns:conn.execute('ALTER TABLE remote_jobs ADD COLUMN terminal_observed_at REAL')
        with conn: yield conn
    finally: conn.close()


def create(base, request, username):
    encoded = json.dumps(request,sort_keys=True,separators=(',',':'))
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    dataset_slug = 'opendub-input-'+fingerprint[:24]
    kernel_slug = 'opendub-run-'+fingerprint[:24]
    now = time.time()
    with database(base) as conn:
        conn.execute('INSERT OR IGNORE INTO remote_jobs (id,fingerprint,operation,state,request,dataset_handle,kernel_handle,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (str(uuid.uuid4()),fingerprint,request['operation'],'prepared',encoded,username+'/'+dataset_slug,username+'/'+kernel_slug,now,now))
        row = conn.execute('SELECT * FROM remote_jobs WHERE fingerprint=?',(fingerprint,)).fetchone()
    return dict(row)


def get(base, job_id):
    with database(base) as conn:
        row = conn.execute('SELECT * FROM remote_jobs WHERE id=?',(job_id,)).fetchone()
    if row is None: raise ValueError('Remote job not found.')
    return dict(row)


def list_jobs(base):
    with database(base) as conn:
        rows=[dict(row) for row in conn.execute('SELECT id,operation,state,message,attempts,created_at,updated_at,kernel_handle,parent_job_id,request FROM remote_jobs ORDER BY created_at DESC LIMIT 100')]
        for row in rows:row['schema_version']=json.loads(row.pop('request')).get('schema_version',1)
        return rows


def active_jobs(base):
    if not (Path(base)/'kaggle/jobs.sqlite3').is_file():return []
    with database(base) as conn:
        return [dict(row) for row in conn.execute("SELECT id,state FROM remote_jobs WHERE state IN ('submitting','submission_uncertain','waiting','queued','running','downloading','detached')")]


def update(base, job_id, state, message='', dataset_state=None):
    with database(base) as conn:
        conn.execute('UPDATE remote_jobs SET state=?,message=?,updated_at=? WHERE id=?',(state,message,time.time(),job_id))
        if dataset_state:
            conn.execute('UPDATE remote_jobs SET dataset_state=? WHERE id=?',(dataset_state,job_id))
    return get(base,job_id)


def retry_terminal(base, job_id):
    """A new session only after an explicitly reconciled terminal attempt."""
    with database(base) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM remote_jobs WHERE id=?',(job_id,)).fetchone()
        if not row or row['state']!='review_required':raise RuntimeError('Reconcile a terminal remote attempt before retrying.')
        if not row['message'].startswith('Remote attempt is terminal.'):
            raise RuntimeError('Setup/content/output failures require correction, not an automatic retry.')
        conn.execute('INSERT OR IGNORE INTO remote_attempts VALUES (?,?,?,?,?)',(job_id,row['attempts'],row['kernel_handle'],'terminal',time.time()))
        root=row['kernel_handle'].split('-retry-')[0]
        handle=root+'-retry-'+str(row['attempts']+1)
        conn.execute("UPDATE remote_jobs SET state='prepared',kernel_state='not_submitted',terminal_observed_at=NULL,kernel_handle=?,message='New session requested; completed units retained.',updated_at=? WHERE id=?",(handle,time.time(),job_id))
    return get(base,job_id)


def set_control(base,job_id,**fields):
    if not fields or not set(fields)<={'kernel_state','parent_job_id','terminal_observed_at'}:raise ValueError('Invalid remote control field.')
    with database(base) as conn:
        conn.execute('UPDATE remote_jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),job_id))


def claim_submission(base, job_id):
    """One caller claims a prepared intent; no duplicate concurrent submissions."""
    with database(base) as conn:
        conn.execute('BEGIN IMMEDIATE')
        active = conn.execute("SELECT id FROM remote_jobs WHERE state IN ('submitting','submission_uncertain','waiting','queued','running','downloading','detached') AND id!=?",(job_id,)).fetchone()
        if active: raise RuntimeError('Another notebook is active or requires reconciliation; completed work is retained.')
        changed = conn.execute("UPDATE remote_jobs SET state='submitting', attempts=attempts+1,updated_at=? WHERE id=? AND state='prepared'",(time.time(),job_id)).rowcount
        if not changed: raise RuntimeError('This intent was already submitted. Reconcile its existing kernel before retrying.')
    return get(base,job_id)
