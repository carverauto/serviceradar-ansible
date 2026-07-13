#!/usr/bin/env python3
"""Print a deterministic SHA256 for reviewed repository content."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".ansible",
    ".cache",
    ".collections",
    ".molecule",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
}


def main() -> None:
    digest = hashlib.sha256()
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    print(digest.hexdigest())


if __name__ == "__main__":
    main()
