from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _run_version(command: list[str], timeout: float = 6.0) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"status": "missing", "available": False, "path": None, "version": None,
                "error": f"{command[0]} was not found on PATH"}
    try:
        result = subprocess.run([executable, *command[1:]], capture_output=True, text=True,
                                timeout=timeout, errors="replace")
        output = (result.stdout or result.stderr or "").strip().splitlines()
        version = output[0][:300] if output else None
        if result.returncode != 0:
            return {"status": "warning", "available": True, "path": executable,
                    "version": version, "error": f"Command exited with code {result.returncode}"}
        return {"status": "ok", "available": True, "path": executable, "version": version, "error": None}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "error", "available": True, "path": executable, "version": None,
                "error": str(exc)}


def _memory() -> dict[str, Any]:
    # psutil is optional; Windows fallback uses GlobalMemoryStatusEx.
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        return {"total_bytes": int(vm.total), "available_bytes": int(vm.available),
                "used_bytes": int(vm.used), "percent": float(vm.percent), "source": "psutil"}
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                used = status.ullTotalPhys - status.ullAvailPhys
                return {"total_bytes": int(status.ullTotalPhys), "available_bytes": int(status.ullAvailPhys),
                        "used_bytes": int(used), "percent": float(status.dwMemoryLoad), "source": "Windows API"}
        except Exception:
            pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(pages * page_size)
        available = int(os.sysconf("SC_AVPHYS_PAGES") * page_size)
        return {"total_bytes": total, "available_bytes": available,
                "used_bytes": total - available, "percent": round((total - available) / total * 100, 1),
                "source": "sysconf"}
    except Exception as exc:
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None,
                "percent": None, "source": None, "error": str(exc)}


def _gpu() -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total,memory.free,driver_version,utilization.gpu,uuid",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=8, errors="replace")
            if result.returncode == 0 and result.stdout.strip():
                devices = []
                for line in result.stdout.strip().splitlines():
                    fields = [part.strip() for part in line.split(",")]
                    if len(fields) >= 5:
                        devices.append({"name": fields[0], "vram_total_mb": _as_float(fields[1]),
                                        "vram_free_mb": _as_float(fields[2]), "driver_version": fields[3],
                                        "utilization_percent": _as_float(fields[4]), "uuid": fields[5] if len(fields)>5 else None})
                if devices:
                    return {"status": "ok", "available": True, "method": "nvidia-smi",
                            "devices": devices, "error": None}
            error = (result.stderr or "nvidia-smi returned no GPU data").strip()
            return {"status": "warning", "available": False, "method": "nvidia-smi",
                    "devices": [], "error": error[:500]}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "warning", "available": False, "method": "nvidia-smi",
                    "devices": [], "error": str(exc)}
    # Torch CUDA detection is an optional fallback and must never prevent startup.
    try:
        if importlib.util.find_spec("torch") is not None:
            import torch  # type: ignore
            if torch.cuda.is_available():
                devices = []
                for index in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(index)
                    free_bytes, total_bytes = torch.cuda.mem_get_info(index)
                    devices.append({"name": props.name, "vram_total_mb": round(total_bytes / 1048576),
                                    "vram_free_mb": round(free_bytes / 1048576),
                                    "driver_version": None, "utilization_percent": None})
                return {"status": "ok", "available": True, "method": "torch.cuda",
                        "devices": devices, "error": None}
            return {"status": "warning", "available": False, "method": "torch.cuda",
                    "devices": [], "error": "PyTorch is installed but CUDA is not available in this environment"}
    except Exception as exc:
        return {"status": "warning", "available": False, "method": "torch.cuda",
                "devices": [], "error": str(exc)[:500]}
    return {"status": "warning", "available": False, "method": None, "devices": [],
            "error": "NVIDIA GPU not detected via nvidia-smi; PyTorch CUDA is not installed or unavailable"}


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _windows_inventory() -> dict[str, Any]:
    """Hardware inventory only; WMI adapter RAM is deliberately not usable VRAM."""
    if os.name != "nt":
        return {}
    script = "@{cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion);storage=@(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size)} | ConvertTo-Json -Depth 4 -Compress"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=12, errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _ffmpeg_shared_runtime(ffmpeg_path: str | None) -> dict[str, Any]:
    """Check for FFmpeg shared DLLs required by TorchCodec on Windows."""
    if os.name != "nt" or not ffmpeg_path:
        return {"required": False, "available": True, "dll_directory": None, "missing": []}
    try:
        exe = Path(ffmpeg_path).resolve()
        directory = exe.parent
        required = ["avcodec-*.dll", "avformat-*.dll", "avutil-*.dll", "swresample-*.dll"]
        missing = [pattern for pattern in required if not list(directory.glob(pattern))]
        return {
            "required": True,
            "available": not missing,
            "dll_directory": str(directory),
            "missing": missing,
        }
    except OSError as exc:
        return {"required": True, "available": False, "dll_directory": None, "missing": ["unable to inspect FFmpeg DLLs", str(exc)]}


def _ffmpeg_rubberband_available(ffmpeg_path: str | None) -> bool:
    """Check if the FFmpeg installation includes the librubberband audio filter."""
    if not ffmpeg_path:
        return False
    try:
        res = subprocess.run([ffmpeg_path, "-filters"], capture_output=True, text=True, timeout=5, errors="replace")
        return "rubberband" in (res.stdout or "")
    except Exception:
        return False


def collect_diagnostics(data_root: Path, app_version: str = "unknown") -> dict[str, Any]:
    """Collect local runtime diagnostics without uploading or reading project media."""
    try:
        disk = shutil.disk_usage(data_root if data_root.exists() else data_root.parent)
        disk_info = {"path": str(data_root.resolve()), "total_bytes": disk.total,
                     "used_bytes": disk.used, "free_bytes": disk.free,
                     "status": "warning" if disk.free < 5 * 1024**3 else "ok"}
    except OSError as exc:
        disk_info = {"path": str(data_root), "total_bytes": None, "used_bytes": None,
                     "free_bytes": None, "status": "error", "error": str(exc)}
    memory = _memory()
    ffmpeg_path = shutil.which("ffmpeg")
    ffmpeg_shared = _ffmpeg_shared_runtime(ffmpeg_path)
    rubberband_avail = _ffmpeg_rubberband_available(ffmpeg_path)
    # Keep startup diagnostics local/fast. Gated-model authorization is checked only by the diarization stage.
    diarization_access = {
        "status": "not_checked",
        "reason": "Model authorization is checked when speaker diarization runs.",
        "model_url": "https://huggingface.co/pyannote/speaker-diarization-community-1",
    }
    py = {"status": "ok", "version": platform.python_version(), "executable": sys.executable,
          "implementation": platform.python_implementation()}
    try:
        import psutil
        physical_cores = psutil.cpu_count(logical=False)
        frequency = psutil.cpu_freq()
        cpu_mhz = frequency.current if frequency else None
    except Exception:
        physical_cores, cpu_mhz = None, None
    acceleration = {"asr_cuda": False, "separation_cuda": False, "notice": "CPU execution is available. Dedicated GPU detection does not establish model runtime compatibility."}
    if _module_available("torch"):
        code = "import json,torch; cuda=torch.cuda.is_available();\ntry:\n import ctranslate2; asr=bool(ctranslate2.get_cuda_device_count())\nexcept Exception: asr=False\ntry:\n import onnxruntime; sep='CUDAExecutionProvider' in onnxruntime.get_available_providers()\nexcept Exception: sep=False\nprint(json.dumps({'asr_cuda':asr,'separation_cuda':bool(cuda and sep)}))"
        try:
            result = subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,timeout=15)
            if result.returncode == 0:
                acceleration.update(json.loads(result.stdout.strip().splitlines()[-1]))
        except (OSError,subprocess.SubprocessError,ValueError,IndexError):
            pass
    # Roformer uses Torch independently of the main environment's ONNX provider.
    sep_python = Path(os.getenv("OPENDUB_SEPARATION_PYTHON") or str(Path(__file__).resolve().parents[1] / "runtime/separation-env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")))
    if sep_python.is_file():
        try:
            probe = subprocess.run([str(sep_python), "-c", "import torch; from audio_separator.separator import Separator; print(int(torch.cuda.is_available()))"], capture_output=True, text=True, timeout=20)
            acceleration["separation_cuda"] = probe.returncode == 0 and probe.stdout.strip().endswith("1")
        except (OSError, subprocess.SubprocessError):
            pass
    # Diarization receives decoded PCM tensors, so optional TorchCodec DLLs are
    # not a prerequisite of this installed pipeline.
    ffmpeg_shared.update(required=False, decoder="FFmpeg binary + PCM tensor input")
    report = {
        "ok": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "app": {"name": "OpenDub Studio", "version": app_version},
        "system": {"os": platform.system(), "release": platform.release(),
                   "version": platform.version(), "architecture": platform.machine(),
                   "processor": platform.processor() or None, "logical_cpu_count": os.cpu_count(),
                   "physical_cpu_count": physical_cores, "cpu_frequency_mhz": cpu_mhz},
        "python": py,
        "ffmpeg": {
            **_run_version(["ffmpeg", "-version"]),
            "shared_runtime": ffmpeg_shared,
            "rubberband_filter": rubberband_avail,
        },
        "ffprobe": _run_version(["ffprobe", "-version"]),
        "gpu": _gpu(),
        "memory": memory,
        "acceleration": acceleration,
        "disk": disk_info,
        "optional_modules": {name: _module_available(name)
                             for name in ("torch", "faster_whisper", "whisper", "psutil", "pyannote.audio",
                                          "numpy", "soundfile", "edge_tts", "PIL", "cv2")},
        "integrations": {
            "huggingface_token_configured": bool(os.getenv("HF_TOKEN")),
            "diarization_runtime_installed": _module_available("pyannote.audio"),
            "diarization_ready": bool(os.getenv("HF_TOKEN")) and _module_available("pyannote.audio") and diarization_access.get("status") == "ready",
            "diarization_access": diarization_access,
        },
    }
    inventory = _windows_inventory()
    if inventory.get("cpu"):
        report["system"]["processor"] = inventory["cpu"][0].get("Name") or report["system"]["processor"]
    report["storage_devices"] = inventory.get("storage") or []
    report["display_adapters"] = inventory.get("gpu") or []
    if not report["gpu"].get("available") and report["display_adapters"]:
        report["gpu"].update(status="info", available=True, method="Windows CIM hardware inventory",
                             devices=[{"name": adapter.get("Name"), "driver_version": adapter.get("DriverVersion"),
                                       "vram_total_mb": None, "vram_free_mb": None} for adapter in report["display_adapters"]],
                             error=None, notice="Usable dedicated VRAM is unavailable; capacity uses CPU fallback.")
    from .resource_plan import plan_resources
    report["processing_plan"] = plan_resources(report)
    return report


def format_diagnostics_for_log(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
