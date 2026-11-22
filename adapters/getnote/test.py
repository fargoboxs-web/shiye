#!/usr/bin/env python3
"""试连 Get笔记：问一次配额。成功退出 0，失败把原因打到 stderr。不打印凭证。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import getnote  # noqa: E402

try:
    getnote.quota()
except Exception as e:  # noqa: BLE001
    sys.exit(f"Get笔记 连不上：{e}")
print("ok")
