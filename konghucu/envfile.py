"""Read KEY=value lines from a git-ignored .env at the repo root into os.environ
(only for variables not already set). Keeps API keys out of the shell history
and out of chat."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> dict:
    """Returns {"path": str, "found": bool, "keys": [names loaded]} for diagnostics."""
    info = {"path": str(path), "found": path.exists(), "keys": []}
    if not path.exists():
        return info
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k.startswith("export "):
            k = k[7:].strip()
        if v and not os.environ.get(k):  # an empty exported variable counts as unset
            os.environ[k] = v
            info["keys"].append(k)
    return info
