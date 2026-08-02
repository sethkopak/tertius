"""What this machine can actually run, and which models suit it.

Everything here is measured (RAM from the OS, GPU from CTranslate2/nvidia-smi,
model sizes from the Hugging Face repos we download) rather than assumed. The
one judgement call is the memory headroom heuristic, marked as such.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import subprocess

log = logging.getLogger(__name__)

GB = 1024**3

# Download sizes of the exact files faster-whisper fetches (config, model.bin,
# tokenizer, vocabulary), measured from the Hugging Face API on 2026-08-01.
# Speed/quality notes are qualitative on purpose - real throughput depends on
# the machine, and a made-up "x times realtime" number would be misleading.
MODEL_CATALOG = {
    "tiny": {
        "download_bytes": 78_203_619,
        "speed": "Fastest",
        "quality": "Roughest. Fine for a quick test or very clean audio.",
    },
    "base": {
        "download_bytes": 147_882_941,
        "speed": "Very fast",
        "quality": "Noticeably better than tiny, still makes mistakes.",
    },
    "small": {
        "download_bytes": 486_212_372,
        "speed": "Fast",
        "quality": "Reasonable for clear speech. A good CPU-only choice.",
    },
    "medium": {
        "download_bytes": 1_530_571_735,
        "speed": "Slow",
        "quality": "Good. Usually beaten by turbo, which is also faster.",
    },
    "large-v2": {
        "download_bytes": 3_089_578_858,
        "speed": "Slowest",
        "quality": "Very good. Superseded by large-v3.",
    },
    "large-v3": {
        "download_bytes": 3_090_835_702,
        "speed": "Slowest",
        "quality": "Best accuracy available here.",
    },
    "large-v3-turbo": {
        "download_bytes": 1_621_665_983,
        "speed": "Fast",
        "quality": (
            "Near large-v3 accuracy, far quicker: same model pruned from 32 "
            "decoding layers to 4. The default, and the best all-rounder."
        ),
    },
}

# Judgement call: weights must fit in memory, plus room for the runtime, the
# audio being decoded, and the OS. Deliberately generous - being told "this may
# be tight" and being fine beats a swap-thrashing surprise an hour in.
MEMORY_HEADROOM_BYTES = 1 * GB


def total_ram_bytes() -> int | None:
    """Physical RAM, or None if we cannot tell on this platform."""
    if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError):
            pass
    if platform.system() == "Windows":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
    return None


def gpu_info() -> dict:
    """CUDA device count from CTranslate2, plus name/VRAM via nvidia-smi."""
    info = {"cuda_devices": 0, "name": None, "vram_bytes": None}
    try:
        import ctranslate2

        info["cuda_devices"] = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        log.debug("could not query CUDA devices: %s", exc)
        return info

    if info["cuda_devices"] and shutil.which("nvidia-smi"):
        try:
            output = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if output.returncode == 0 and output.stdout.strip():
                name, _, mib = output.stdout.strip().splitlines()[0].partition(",")
                info["name"] = name.strip()
                info["vram_bytes"] = int(float(mib.strip())) * 1024 * 1024
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            log.debug("nvidia-smi unavailable: %s", exc)
    return info


CUDA_PIP_PACKAGES = "nvidia-cublas-cu12 nvidia-cudnn-cu12"


def cuda_runtime_status(cuda_devices: int) -> dict:
    """Are the CUDA *runtime libraries* present, not just a GPU?

    These are different things, and confusing them is the trap: the NVIDIA
    driver is what makes a GPU appear, while cuBLAS/cuDNN are what actually run
    the model. A machine can report a CUDA device and still fail on first use.

    Checked cheaply here so a new user is told up front, rather than finding out
    part-way through their first batch.
    """
    if not cuda_devices:
        return {"state": "no_gpu", "detail": "No CUDA GPU detected.", "libraries": []}

    from .transcribe import nvidia_library_dirs, register_cuda_dll_directories

    register_cuda_dll_directories()
    pip_dirs = [str(p) for p in nvidia_library_dirs()]
    if pip_dirs:
        return {
            "state": "ok",
            "detail": "CUDA runtime libraries are installed.",
            "libraries": pip_dirs,
        }

    # No pip-installed libraries. A system-wide CUDA toolkit would also do, so
    # check whether the loader can find cuBLAS before declaring it missing.
    if os.name == "nt":
        import ctypes

        for candidate in ("cublas64_12.dll", "cublas64_11.dll"):
            try:
                ctypes.WinDLL(candidate)
                return {
                    "state": "ok",
                    "detail": f"Found {candidate} on the system path.",
                    "libraries": [candidate],
                }
            except OSError:
                continue

    return {
        "state": "missing",
        "detail": (
            "A CUDA GPU is present but its runtime libraries are not installed, "
            "so jobs will run on the CPU. Install them with: "
            f"pip install {CUDA_PIP_PACKAGES} (about 1.2 GB)."
        ),
        "libraries": [],
    }


def supported_compute_types() -> dict:
    try:
        import ctranslate2

        types = {"cpu": sorted(ctranslate2.get_supported_compute_types("cpu"))}
        if ctranslate2.get_cuda_device_count():
            types["cuda"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
        return types
    except Exception:
        return {}


def effective_device(device: str, cuda_devices: int, cuda_usable: bool = True) -> str:
    """What `auto` will actually resolve to.

    `cuda_usable` matters: a GPU whose runtime libraries are missing will be
    detected and then fall back to the CPU, so judging a model against VRAM it
    is never going to use would be wrong.
    """
    if device == "auto":
        return "cuda" if cuda_devices and cuda_usable else "cpu"
    return device


def assess_model(
    model_size: str, device: str, system: dict, cached: bool | None = None
) -> dict:
    """Rate one model for this machine: ok / tight / risky, with a reason."""
    entry = MODEL_CATALOG.get(model_size, {})
    needed = entry.get("download_bytes", 0) + MEMORY_HEADROOM_BYTES
    target = effective_device(
        device,
        system.get("cuda_devices", 0),
        cuda_usable=system.get("cuda_runtime", {}).get("state") != "missing",
    )

    if target == "cuda":
        available = system.get("vram_bytes")
        where = "VRAM"
    else:
        available = system.get("ram_bytes")
        where = "RAM"

    verdict, reason = "ok", ""
    if available is None:
        verdict = "unknown"
        reason = f"Could not read this machine's {where}."
    else:
        # Compared against *total* memory, so leave room for the OS and whatever
        # else is running: past ~90% it will not fit in practice, past ~60% it
        # will be uncomfortable.
        ratio = needed / available
        if ratio > 0.9:
            verdict = "risky"
            reason = (
                f"Needs roughly {needed / GB:.1f} GB of {where}; this machine has "
                f"{available / GB:.1f} GB in total. Expect it to fail or crawl."
            )
        elif ratio > 0.6:
            verdict = "tight"
            reason = (
                f"Needs roughly {needed / GB:.1f} GB of this machine's "
                f"{available / GB:.1f} GB of {where}. Should work, with little "
                "to spare."
            )

    if target == "cpu" and model_size in ("large-v2", "large-v3", "medium"):
        reason = (reason + " Large models are slow without a GPU.").strip()
        if verdict == "ok":
            verdict = "tight"

    return {
        "model": model_size,
        "verdict": verdict,
        "reason": reason,
        "runs_on": target,
        "download_bytes": entry.get("download_bytes"),
        "speed": entry.get("speed"),
        "quality": entry.get("quality"),
        "cached": cached,
    }


def check_compute_type(compute_type: str, device: str, system: dict) -> str | None:
    """Warn about a compute type this machine's device cannot do."""
    if compute_type == "default":
        return None
    target = effective_device(
        device,
        system.get("cuda_devices", 0),
        cuda_usable=system.get("cuda_runtime", {}).get("state") != "missing",
    )
    supported = (system.get("compute_types") or {}).get(target)
    if supported and compute_type not in supported:
        return (
            f"{compute_type} is not supported on {target} here "
            f"(available: {', '.join(supported)}). Use 'default' to let it choose."
        )
    return None


def describe_system() -> dict:
    """One snapshot of the machine, for the UI to reason about."""
    gpu = gpu_info()
    system = {
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": total_ram_bytes(),
        "cuda_devices": gpu["cuda_devices"],
        "gpu_name": gpu["name"],
        "vram_bytes": gpu["vram_bytes"],
        "compute_types": supported_compute_types(),
        "cuda_runtime": cuda_runtime_status(gpu["cuda_devices"]),
    }
    return system
