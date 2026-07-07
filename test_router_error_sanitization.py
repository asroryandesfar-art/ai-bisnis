"""Regression guard: sanitized router error responses must not interpolate the
raw exception (which can leak DB/schema/internal detail) into HTTPException detail.

Scoped to the files hardened in the product-code-polish pass.
"""
import re
from pathlib import Path

import pytest

# HTTPException(..., f"...{e}...") / {exc} / {err} leaking the exception object.
_LEAK_RE = re.compile(r'HTTPException\([^)]*f["\'][^"\']*\{(e|exc|err|ex)\}')

FILES = [
    "bn_platform/action_executor_router.py",
    "bn_platform/omnichannel.py",
]


@pytest.mark.parametrize("relpath", FILES)
def test_no_exception_leak_in_http_detail(relpath):
    src = Path(relpath).read_text(encoding="utf-8")
    leaks = _LEAK_RE.findall(src)
    assert not leaks, (
        f"{relpath}: HTTPException still interpolates the raw exception "
        f"({leaks}); log it server-side and return a generic message instead."
    )
