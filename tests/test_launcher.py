import signal
from unittest.mock import patch
import uvicorn
from scripts.launch import ConfirmingServer


def test_ctrl_c_keeps_server_running_when_shutdown_declined():
    server = ConfirmingServer(uvicorn.Config("backend.app:app"))
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="no"):
        server.handle_exit(signal.SIGINT, None)
    assert server.should_exit is False


def test_ctrl_c_stops_server_only_after_yes():
    server = ConfirmingServer(uvicorn.Config("backend.app:app"))
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="yes"):
        server.handle_exit(signal.SIGINT, None)
    assert server.should_exit is True


def test_noninteractive_shutdown_does_not_block_on_input():
    server = ConfirmingServer(uvicorn.Config("backend.app:app"))
    with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as prompt:
        server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit is True
    prompt.assert_not_called()
