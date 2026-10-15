#!/usr/bin/env python3
"""可选的来源适配器：按 id 取 Get笔记 的原文，存进 work/full/<id>.json。

  python3 adapters/getnote/fetch.py 1920347657994434784 1923693579251833424 …
  python3 adapters/getnote/fetch.py --from-digest work/notes-digest.md --grep 书单

列表接口（pull.py 不带 --full 时）给的 text 只是 Get笔记 的 AI 摘要（六百字左右），
写画像、找书、核对引子要原话时，用这个脚本把挑中的几条取回来；不要为全部笔记取原文。
凭证只从环境变量读（GETNOTE_API_KEY、GETNOTE_CLIENT_ID），任何输出都不打印密钥值。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

import getnote  # noqa: E402

_SECRET = re.compile(r"[A-Za-z0-9_\-]{24,}")   # 报错信息里凡是像令牌的长串都遮掉


def safe(msg: str) -> str:
    return _SECRET.sub("…", msg)


def ids_from_digest(path: Path, pattern: str | None) -> list[str]:
    """notes-digest.md 每行带 `getnote:<id>`；--grep 只取匹配的行。"""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if pattern and not re.search(pattern, line):
            continue
        out += re.findall(r"getnote:(\d{6,})", line)
    return list(dict.fromkeys(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="笔记 id（带不带 getnote: 前缀都行）")
    ap.add_argument("--from-digest", help="从 notes-digest.md 里取 id")
    ap.add_argument("--grep", help="配合 --from-digest：只取匹配这个正则的行")
    ap.add_argument("--out", default=str(HERE.parents[1] / "work" / "full"))
    args = ap.parse_args()
    ids = [i.split(":")[-1] for i in args.ids]
    if args.from_digest:
        ids += ids_from_digest(Path(args.from_digest), args.grep)
    ids = list(dict.fromkeys(ids))
    if not ids:
        sys.exit("没有 id。给几个 id，或 --from-digest work/notes-digest.md --grep 关键词")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i in ids:
        dst = out / f"{i}.json"
        if dst.exists():
            print(f"  已有 {dst.name}"); ok += 1
            continue
        try:
            item = getnote.get_item(i)
        except getnote.GetNoteError as e:
            print(f"  取不到 {i}：{safe(str(e))}", file=sys.stderr)
            continue
        dst.write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
        text = item.get("content") or item.get("text") or ""
        print(f"✓ {i}：{(item.get('title') or '')[:30]}  原文 {len(text)} 字 → {dst}")
        ok += 1
    print(f"{ok}/{len(ids)} 条在 {out}/（work/ 不进 git）")


if __name__ == "__main__":
    main()
