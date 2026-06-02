from __future__ import annotations

import sys
from pathlib import Path


def ensure_vendor_on_path() -> None:
    """
    Ensure `vendor/` (pip --target install dir) is importable.
    This avoids issues when user-site packages are disabled/not on sys.path.
    """
    base = Path(__file__).resolve().parent
    vendor = base / "vendor"
    if vendor.exists():
        v = str(vendor)
        if v not in sys.path:
            sys.path.insert(0, v)


ensure_vendor_on_path()

