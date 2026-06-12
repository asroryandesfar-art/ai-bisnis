from __future__ import annotations

import sys
from pathlib import Path


def ensure_vendor_on_path() -> None:
    """
    Ensure `vendor/` (pip --target install dir) is importable.
    vendor/ berisi build Windows — di Linux pakai site-packages biasa.
    Vendor hanya dimuat jika fastapi belum tersedia di sys.path normal.
    """
    import importlib.util
    # Jika fastapi sudah ada dari site-packages, jangan pakai vendor
    # (vendor/*.pyd adalah Windows binary — tidak berjalan di Linux)
    if importlib.util.find_spec("fastapi") is not None:
        return

    base = Path(__file__).resolve().parent
    vendor = base / "vendor"
    if vendor.exists():
        v = str(vendor)
        if v not in sys.path:
            sys.path.insert(0, v)


ensure_vendor_on_path()

