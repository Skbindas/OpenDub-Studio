"""Atomic checkpoint replacement with bounded Windows sharing-lock retries."""
from pathlib import Path
import time
import os
import shutil
import uuid
import threading
from contextlib import contextmanager

_locks_guard = threading.Lock()
_locks = {}


@contextmanager
def project_mutation_lock(folder: Path, timeout: float = 60):
    """Serialize metadata commits across threads AND independent workers."""
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    with _locks_guard:
        lock = _locks.setdefault(str(folder), threading.RLock())
    with lock, (folder / '.metadata.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Project metadata is busy; saved audio retained')
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def replace_with_retry(source: Path, target: Path, *, attempts: int = 15) -> None:
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except (PermissionError, FileNotFoundError, OSError):
            if not source.exists():
                raise
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def publish_audio_revision(source: Path, target: Path) -> None:
    """Keep the previous clip before atomically promoting a completed replacement."""
    if target.is_file():
        history = target.parent / ".history"
        history.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, history / f"{target.stem}.{uuid.uuid4().hex}{target.suffix}")
    replace_with_retry(source, target)
