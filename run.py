#!/usr/bin/env python3
"""拾页：笔记 → 书单 → 选篇 → 杂志 PDF。

脚本只做确定性的事；判断题（画像、书单、选篇、写作、刊名）由运行 skill 的 AI 做，步骤见 SKILL.md。

用法
  python3 run.py ingest inbox/ [--work work/]           # 收件箱 → work/notes.jsonl + work/notes-digest.md
  python3 run.py prepare books.yaml [--issue DIR]       # 拿书、拆章节 → issues/<日期>/books/、candidates.md；缺书列出、不中断
  python3 run.py show <期目录> <book> <章节号>             # 看某一章的全文（带段落编号）
  python3 run.py translate <期目录> [--api]               # 列出不是中文的选篇，AI 在会话里翻；--api 用 Claude API 翻
  python3 run.py render <期目录> [--fonts A|B|C|D] [--out PDF]   # 校验 selection.json、读 cover.json，排成 PDF
  python3 run.py check <期目录> [--booklet]               # 按 rules/quality/验收.md 2.1 查 PDF → <期目录>/检查报告.md
  python3 run.py select <期目录> --api                    # 可选：用 Claude API 自动选篇（需要 ANTHROPIC_API_KEY）
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from zine import fetch, inbox, parse, render, select, translate  # noqa: E402

CONFIG = {"name": "拾页", "fonts": "B", "pad_to_4": False}
BOOK_EXT = (".epub", ".pdf", ".txt", ".md", ".json", ".html")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "book-" + hashlib.md5(s.encode()).hexdigest()[:6]


def load_books(issue: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((issue / "books").glob("*.json"))}


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s).lower()


def find_local_book(e: dict, dirs: list[Path]) -> Path | None:
    """books.yaml 没写 file 时，在 books/ 里按书名找同名文件。"""
    names = [_norm(x) for x in (e.get("title"), e.get("original_title"), e.get("display_title")) if x]
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in BOOK_EXT and any(n and (n in _norm(p.stem) or _norm(p.stem) in n) for n in names):
                return p
    return None


def cmd_ingest(args):
    r = inbox.ingest(Path(args.inbox), Path(args.work))
    print(f"✓ {r['items']} 条 → {r['notes']}；摘要 {r['digest']}")
    if r["unknown"]:
        print("没认出来的文件（AI 自己看）：" + "、".join(r["unknown"]))


def cmd_prepare(args) -> Path:
    booklist = Path(args.booklist).absolute()
    spec = yaml.safe_load(booklist.read_text(encoding="utf-8"))
    entries = spec["books"] if isinstance(spec, dict) else spec
    issue = Path(args.issue) if args.issue else ROOT / "issues" / dt.date.today().isoformat()
    (issue / "books").mkdir(parents=True, exist_ok=True)
    cache = ROOT / "cache"
    books, missing = {}, []
    for e in entries:
        if isinstance(e, str):
            e = {"title": e}
        key = e.get("key") or slug(e.get("original_title") or e["title"])
        if not any(e.get(k) for k in ("file", "url", "gutenberg_id")):
            local = find_local_book(e, [booklist.parent / "books", ROOT / "books"])
            if local:
                e = {**e, "file": str(local)}
        try:
            path, source = fetch.resolve(e, cache, booklist.parent)
        except fetch.BookNotFound as err:
            missing.append((e["title"], str(err)))
            continue
        book = parse.parse(path)
        simplified = parse.maybe_simplify(book)
        n_img = parse.export_images(path, book, issue / "books" / f"{key}.img", f"{key}.img") if path.suffix.lower() == ".epub" else 0
        cover = parse.extract_cover(path)
        if cover:
            (issue / "books" / f"{key}.cover{cover[1]}").write_bytes(cover[0])
            book["cover"] = f"{key}.cover{cover[1]}"
        meta = fetch.lookup_metadata(e["title"], e.get("author") or book.get("author"))
        book.update({k: v for k, v in meta.items() if k not in book or k == "year"})
        book.update({k: v for k, v in e.items() if k in ("author", "year", "why_saved", "rights")})
        book["display_title"] = e.get("display_title") or e["title"]
        book["original_title"] = e.get("original_title") or (e["title"] if e.get("display_title") else None)
        book["source"] = source + ("（公有领域）" if "Gutenberg" in source or e.get("public_domain") or e.get("rights") == "public_domain" else "") \
            + ("，繁体转简体" if simplified else "")
        (issue / "books" / f"{key}.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        books[key] = book
        print(f"✓ {key}: {book.get('title')} — {len(book['chapters'])} 章 [{book['source']}]{'，有封面' if cover else '，没找到封面'}，插图 {n_img} 张")
    if missing:
        lines = ["# 缺书", "", "下面这些书没有拿到全文，这一期先不做它们。补上文件（放进 books/ 或在 books.yaml 写 file:）再跑一次 prepare。", ""]
        lines += [f"- 《{t}》：{why}" for t, why in missing]
        (issue / "缺书.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for t, why in missing:
            print(f"✗ 缺《{t}》：{why}", file=sys.stderr)
        print(f"缺书清单：{issue / '缺书.md'}", file=sys.stderr)
    if books:
        cand = select.write_candidates(issue, books)
        print(f"\n候选章节已写到 {cand}")
    else:
        sys.exit("一本书都没拿到，没法继续。")
    return issue


def cmd_show(args):
    book = load_books(Path(args.issue))[args.book]
    print(select.numbered_chapter(book, int(args.chapter)))


def cmd_select(args):
    issue = Path(args.issue)
    books = load_books(issue)
    if not args.api:
        print("agent 模式：读", issue / "candidates.md", "，按 rules/editor/selection.md 写", issue / "selection.json")
        return
    profile_path = issue / "reader.md" if (issue / "reader.md").exists() else ROOT / "reader.md"
    profile = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    meta = {"date": issue.name}
    sel = select.select_with_api(books, profile, meta)
    (issue / "selection.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    print("✓ selection.json 已生成")


def cmd_translate(args) -> bool:
    issue = Path(args.issue)
    books = load_books(issue)
    sel = json.loads((issue / "selection.json").read_text(encoding="utf-8"))
    left = translate.run(issue, sel, books, api=args.api)
    if left:
        print("下面这些选篇不是中文。按 rules/editor/translation.md 翻译，写成同名的 .json（去掉 .src，格式见 zine/translate.py 开头）：")
        for p in left:
            print("  ", p)
        return False
    print("✓ 所有选篇都是中文了")
    return True


def load_cover(issue: Path) -> dict:
    p = issue / "cover.json"
    if not p.exists():
        return {}
    cover = json.loads(p.read_text(encoding="utf-8"))
    title = (cover.get("title") or "").strip()
    if len(title) != 2:
        sys.exit(f"cover.json 的 title 必须是两个汉字，现在是 {title!r}（规则见 rules/editor/title.md）")
    return cover


def cmd_render(args) -> Path:
    issue = Path(args.issue)
    books = load_books(issue)
    sel = json.loads((issue / "selection.json").read_text(encoding="utf-8"))
    sel.setdefault("issue", {}).setdefault("date", issue.name)
    problems = select.validate(sel, books)
    if problems:
        sys.exit("selection.json 有问题：\n  " + "\n  ".join(problems))
    untranslated = translate.pending(issue, sel, books)
    if untranslated:
        sys.exit("还有选篇不是中文，先跑 `run.py translate`：" + ", ".join(f"{p['book']} 第 {p['chapter']} 章" for p in untranslated))
    cover = load_cover(issue)
    name = cover.get("title") or CONFIG["name"]
    out = Path(args.out) if args.out else issue / f"{name}-{issue.name}.pdf"
    cfg = {**CONFIG, "name": name, "cover": cover, "fonts": args.fonts or CONFIG.get("fonts", "B")}
    pages = render.render(sel, books, out, cfg, issue_dir=issue)
    print(f"✓ {out}（{pages} 页）")
    return out


def cmd_check(args) -> bool:
    """验收第一级：脚本硬检查（条款见 rules/quality/验收.md 2.1）。zine/check.py 只量不改。"""
    import subprocess
    cmd = [sys.executable, str(ROOT / "zine" / "check.py"), str(args.issue)]
    if args.booklet:
        cmd.append("--booklet")
    if args.out:
        cmd += ["--out", args.out]
    return subprocess.run(cmd).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("inbox"); p.add_argument("--work", default=str(ROOT / "work"))
    p = sub.add_parser("prepare"); p.add_argument("booklist"); p.add_argument("--issue")
    p = sub.add_parser("show"); p.add_argument("issue"); p.add_argument("book"); p.add_argument("chapter")
    p = sub.add_parser("select"); p.add_argument("issue"); p.add_argument("--api", action="store_true")
    p = sub.add_parser("translate"); p.add_argument("issue"); p.add_argument("--api", action="store_true")
    p = sub.add_parser("render"); p.add_argument("issue"); p.add_argument("--fonts", help="字体组合 A/B/C/D，见 rules/typesetting/fonts.md"); p.add_argument("--out")
    p = sub.add_parser("check"); p.add_argument("issue"); p.add_argument("--booklet", action="store_true", help="骑马钉：页数不是 4 的倍数算不通过"); p.add_argument("--out")
    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(0 if cmd_check(args) else 1)
    {"ingest": cmd_ingest, "prepare": cmd_prepare, "show": cmd_show, "select": cmd_select,
     "translate": cmd_translate, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
    main()
