from __future__ import annotations

import os
import signal
import socket
import sys
import time
import webbrowser
from pathlib import Path
from threading import Timer

import uvicorn
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))
HOST = os.getenv("OPENDUB_HOST", "127.0.0.1")
PORT = int(os.getenv("OPENDUB_PORT", "7860"))
LOG_PATH = ROOT / os.getenv("OPENDUB_DATA_DIR", "runtime") / "logs" / "studio.log"


def confirm_close(message: str) -> bool:
    try:
        return input(message + " [yes/No]: ").strip().lower() in {"yes", "y"}
    except (EOFError, KeyboardInterrupt):
        print("\n[OpenDub] Shutdown declined. Studio remains active.", flush=True)
        return False


class ConfirmingServer(uvicorn.Server):
    def handle_exit(self, sig, frame) -> None:
        interactive_signal = sig in {signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGINT)}
        if interactive_signal and sys.stdin.isatty():
            if not confirm_close("\nStop OpenDub Studio and close its log terminal?"):
                print("[OpenDub] Continuing live logs. Press Ctrl+C to request shutdown.", flush=True)
                return
        # Do not re-raise an accepted Ctrl+C after graceful shutdown.
        self.should_exit = True


class LogStream:
    """Mirror output to a local log so a second launcher can follow it."""
    def __init__(self, original, logfile):
        self.original, self.logfile = original, logfile

    def write(self, value):
        self.original.write(value)
        if not self.logfile.closed:
            self.logfile.write(value)
            self.logfile.flush()
        return len(value)

    def flush(self):
        self.original.flush()
        if not self.logfile.closed:
            self.logfile.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


def open_browser() -> None:
    if os.getenv("OPENDUB_OPEN_BROWSER", "1").lower() in {"0", "false", "no"}:
        return
    try:
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass


def follow_existing_logs() -> None:
    print(f"[OpenDub] An instance is already serving http://{HOST}:{PORT}.")
    print("[OpenDub] Keeping this terminal open to follow its logs.")
    print("[OpenDub] Ctrl+C, then yes closes this viewer. The existing server keeps running.")
    open_browser()
    offset = 0
    while True:
        try:
            if LOG_PATH.exists():
                size = LOG_PATH.stat().st_size
                if size < offset:
                    offset = 0
                with LOG_PATH.open(encoding="utf-8", errors="replace") as handle:
                    handle.seek(offset)
                    content = handle.read()
                    offset = handle.tell()
                    if content:
                        print(content, end="", flush=True)
            time.sleep(0.5)
        except KeyboardInterrupt:
            if confirm_close("\nClose this log viewer? The existing studio will keep running."):
                return


def main() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        if probe.connect_ex((HOST, PORT)) == 0:
            follow_existing_logs()
            return 0
    print("\nOpenDub Studio | Local Hindi dubbing workspace")
    print(f"Web UI: http://{HOST}:{PORT}")
    print(f"Live logs: {LOG_PATH}")
    print("Keep this terminal open. Press Ctrl+C, then yes to stop the studio.\n")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as logfile:
        original_out, original_error = sys.stdout, sys.stderr
        sys.stdout = LogStream(original_out, logfile)
        sys.stderr = LogStream(original_error, logfile)
        try:
            timer = Timer(1.2, open_browser)
            timer.daemon = True
            timer.start()
            server = ConfirmingServer(uvicorn.Config("backend.app:app", host=HOST, port=PORT, log_level="info"))
            server.run()
            print("[OpenDub] Studio stopped. Source media and checkpoints remain saved.", flush=True)
        except (Exception, SystemExit) as exc:
            print(f"[OpenDub] Startup error: {exc}", flush=True)
            if sys.stdin.isatty():
                while not confirm_close("Close this terminal after the error?"):
                    pass
            return 1
        finally:
            sys.stdout, sys.stderr = original_out, original_error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
