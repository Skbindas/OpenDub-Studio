"""Crash-releasing account lock across threads/processes; no new dependency."""
from contextlib import contextmanager
import os
import time
from pathlib import Path


@contextmanager
def account_lock(base,username,*,wait=False,cancelled=lambda:False):
    path=Path(base).resolve().parent.parent/'kaggle-control'/(username+'.lock')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        while True:
            if wait and cancelled():raise InterruptedError('Cloud coordinator paused while waiting for the account lock.')
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if wait:
                    time.sleep(.25)
                    continue
                from .kaggle_tasks import RemoteWaiting
                raise RemoteWaiting('Another coordinator is using this Kaggle account. Wait or explicitly choose local; completed work is retained.') from None
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
