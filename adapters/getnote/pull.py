#!/usr/bin/env python3
"""可选的来源适配器：把 Get笔记 最近的收藏批量存进 inbox/，省得 AI 一条条搬。

  python3 adapters/getnote/pull.py --days 30 [--full] [--inbox inbox/]

凭证只从环境变量读（GETNOTE_API_KEY、GETNOTE_CLIENT_ID），任何输出都不打印密钥值。
--full 会逐条取原文（列表里的 content 只是 AI 摘要）；接口有限流，条数多时慢一些。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

import getnote  # noqa: E402
from zine.inbox import normalize_item  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--full", action="store_true", help="逐条取原文")
    ap.add_argument("--inbox", default=str(HERE.parents[1] / "inbox"))
    args = ap.parse_args()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    items = getnote.list_items(since)
    out = Path(args.inbox); out.mkdir(parents=True, exist_ok=True)
    path = out / f"getnote-{dt.date.today().isoformat()}.jsonl"
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for it in items:
            raw = dict(it)
            if args.full:
                try:
                    raw.update({k: v for k, v in getnote.get_item(it["id"]).items() if v})
                except getnote.GetNoteError as e:
                    print(f"  原文取不到 {it['id']}：{e}", file=sys.stderr)
            raw.setdefault("source", "getnote")
            row = normalize_item(raw, source="getnote")
            if row:
                f.write(json.dumps(row, ensure_ascii=False) + "\n"); n += 1
    print(f"✓ {n} 条 → {path}；接着跑 python3 run.py ingest {out}")


if __name__ == "__main__":
    main()
