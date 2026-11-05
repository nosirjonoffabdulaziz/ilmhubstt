"""Windows: pip orqali o'rnatilgan NVIDIA kutubxonalarini (nvidia-cublas-cu12, nvidia-cudnn-cu12)
CTranslate2 topa olishi uchun DLL qidiruv yo'liga qo'shish."""
from __future__ import annotations

import os
import sys

_done = False


def add_nvidia_dll_dirs() -> None:
    global _done
    if _done or os.name != "nt":
        return
    _done = True
    for base in sys.path:
        nv = os.path.join(base, "nvidia")
        if not os.path.isdir(nv):
            continue
        for sub in os.listdir(nv):
            b = os.path.join(nv, sub, "bin")
            if os.path.isdir(b):
                try:
                    os.add_dll_directory(b)
                except (OSError, AttributeError):
                    pass
                os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")
