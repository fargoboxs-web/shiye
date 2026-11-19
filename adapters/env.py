"""读仓库根的 .env，把里面的 KEY=VALUE 放进环境变量（已有的环境变量优先，不覆盖）。不打印任何值。"""
from __future__ import annotations

import os
from pathlib import Path


def load(path: Path | None = None) -> None:
    p = path or Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0] if not v.lstrip().startswith(("'", '"')) else v   # 行尾注释
        if v.lstrip().startswith("#"):
            v = ""
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("'\"")
        if k and v and not os.environ.get(k):
            os.environ[k] = v
