"""Hardware probing. Never alters drivers or system CUDA; falls back to CPU instead."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def add_cuda_dll_dirs() -> list[str]:
    """Make the venv's pip-installed cuBLAS/cuDNN visible to CTranslate2 (Windows)."""
    added: list[str] = []
    for base in sys.path:
        root = Path(base) / "nvidia"
        if not root.is_dir():
            continue
        for lib in root.iterdir():
            for sub in ("bin", "lib"):
                d = lib / sub
                if d.is_dir() and any(d.glob("*.dll")):
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(str(d))
                    os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                    added.append(str(d))
    return added


def gpu_name() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0] if out else None


def cuda_available() -> bool:
    add_cuda_dll_dirs()
    import ctranslate2

    return ctranslate2.get_cuda_device_count() > 0


def choose(device: str = "auto") -> tuple[str, str]:
    """(device, compute_type): cuda/int8_float16 when usable, else cpu/int8."""
    if device != "cpu" and cuda_available():
        return "cuda", "int8_float16"
    return "cpu", "int8"
