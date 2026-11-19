#!/usr/bin/env python3
"""拾页：笔记 → 书单 → 选篇 → 杂志 PDF。

脚本只做确定性的事；判断题（画像、书单、选篇、写作、刊名）由运行 skill 的 AI 做，步骤见 SKILL.md。

用法
  python3 run.py adapters                               # 列出装了哪些适配器（笔记来源、书库），哪些能用
  python3 run.py ingest inbox/ [--work work/]           # 收件箱 → work/notes.jsonl + work/notes-digest.md
  python3 run.py prepare books.yaml [--issue DIR]       # 拿书、拆章节 → issues/<日期>/books/、candidates.md；缺书列出、不中断
  python3 run.py show <期目录> <book> <章节号>             # 看某一章的全文（带段落编号）
  python3 run.py translate <期目录> [--api]               # 列出不是中文的选篇，AI 在会话里翻；--api 让脚本自己调模型 API 翻（可选，目前只接了 Claude API）
  python3 run.py render <期目录> [--fonts A|B|C|D] [--style A|B] [--out PDF]   # 校验 selection.json、读 cover.json，排成 PDF
                                                        # 期目录里有 封面.html / 封底.html / 封面.css 时用它们做封面
  python3 run.py covers <期目录> [--name 方向1]            # 把刚排好的封面、封底存成图 → <期目录>/小样/，给读者挑
  python3 run.py check <期目录> [--booklet] [--pdf PDF]             # 按 rules/quality/验收.md 2.1 查 PDF → <期目录>/检查报告.md
  python3 run.py select <期目录> --api                    # 可选：脚本自己调模型 API 选篇（目前只接了 Claude API，需要 ANTHROPIC_API_KEY）
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

CONFIG = {"name": "拾页", "fonts": "B", "pad_to_4": True}   # 总页数补成 4 的倍数（骑马钉；差的页补成空白笔记页，放在封底前）
BOOK_EXT = (".epub", ".pdf", ".txt", ".md", ".json", ".html")


def slug(s: str) -> str:
    """书的 key：文件名和 selection.json 里的 book 字段。汉字保留（控制论与科学方法论 → 控制论与科学方法论），西文转小写连字符。"""
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "-", s.lower()).strip("-")[:40] or "book-" + hashlib.md5(s.encode()).hexdigest()[:6]


def load_books(issue: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((issue / "books").glob("*.json"))}


try:
    from opencc import OpenCC
    _T2S = OpenCC("t2s")
except ImportError:   # 没装 opencc 就不做繁简归一
    _T2S = None


def _norm(s: str) -> str:
    """比对书名用：去标点空格、小写、繁转简（books.yaml 写「无路之路」也能对上文件「無路之路.epub」）。"""
    s = re.sub(r"[\s\W_]+", "", s).lower()
    return _T2S.convert(s) if _T2S else s


def find_local_book(e: dict, dirs: list[Path]) -> Path | None:
    """books.yaml 没写 file 时，在 books/ 里按书名找同名文件。
    中文书名（title / display_title）对上的优先于外文原名对上的：同一本书有中译本和原版两个文件时，取中译本（杂志全是中文，少翻一篇）。"""
    tiers = [[_norm(x) for x in (e.get("title"), e.get("display_title")) if x],
             [_norm(x) for x in (e.get("original_title"),) if x]]
    for names in tiers:
        for d in dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in BOOK_EXT and any(n and (n in _norm(p.stem) or _norm(p.stem) in n) for n in names):
                    return p
    return None


def cmd_adapters(args):
    """列出 adapters/ 下的插件：能不能用，缺什么。只看环境变量在不在，不打印值。"""
    import os
    root = ROOT / "adapters"
    sys.path.append(str(root)); import env; env.load()
    metas = {}
    for p in sorted(root.glob("*/adapter.json")):
        try:
            metas[p.parent.name] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"✗ {p.parent.name}：adapter.json 读不了（{e}）")
    if not metas:
        print("没有装适配器。笔记放进 inbox/，书放进 books/ 就能跑。")
        return

    def missing(m):
        out = [f"环境变量 {v}" for v in m.get("needs_env", []) if not os.environ.get(v)]
        out += [f"适配器 {a}" for a in m.get("needs_adapters", []) if a not in metas]
        return out

    for name, m in metas.items():
        kind = {"notes": "笔记", "books": "书"}.get(m.get("kind"), m.get("kind", "?"))
        lack = missing(m)
        alt = next((a for a in m.get("alternatives", []) if not missing(a)), None) if lack else None
        if m.get("needs_tools"):
            state = "要看 agent 有没有这些工具：" + "、".join(m["needs_tools"])
        elif not lack:
            state = "能用"
        elif alt:
            state = "主路线没接（缺 " + "、".join(lack) + "），备用路线能用"
        else:
            state = "没接（缺 " + "、".join(lack) + "）"
        print(f"【{kind}】{m.get('title', name)}（adapters/{name}/）：{state}")
        print(f"    {m.get('does', '')}")
        print(f"    跑法：{(alt or m).get('run', '见 README.md')}")
        for k, label in (("costs", "花费"), ("account_changes", "会动账号")):
            if m.get(k):
                print(f"    {label}：{m[k]}")


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
                print(f"  《{e['title']}》没写 file，用本地文件 {local.name}")
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
        book.update({k: v for k, v in e.items() if k in ("author", "year", "why_saved", "rights", "translator")})
        # 书名以 books.yaml 为准：电子书元数据里常是带副题和广告语的长串
        if book.get("title") and book["title"] != e["title"]:
            book["source_title"] = book["title"]
        book["title"] = e["title"]
        book["display_title"] = e.get("display_title") or e["title"]
        book["original_title"] = e.get("original_title") or (e["title"] if e.get("display_title") else None)
        book["source"] = source + ("（公有领域）" if "Gutenberg" in source or e.get("public_domain") or e.get("rights") == "public_domain" else "") \
            + ("，繁体转简体" if simplified else "")
        (issue / "books" / f"{key}.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        books[key] = book
        print(f"✓ {key}: {book.get('title')} / {book.get('author', '')}{'，' + book['translator'] + ' 译' if book.get('translator') else ''}"
              f" — {len(book['chapters'])} 章 [{book['source']}]{'，有封面' if cover else '，没找到封面'}，插图 {n_img} 张")
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
    # cover.json 里和整期配色有关的几项交给排版：每篇一个颜色、封面底色、标签颜色、扉页排法
    for k in ("layers", "paper", "label_colors", "style", "divider_edge"):
        if cover.get(k):
            sel["issue"][k] = cover[k]
    sel["issue"]["name"] = name
    if getattr(args, "style", None):        # 扉页排法 A（色块）/ B（白底加索引条），见 rules/typesetting/divider.md
        sel["issue"]["style"] = args.style
    out = Path(args.out) if args.out else issue / f"{name}-{issue.name}.pdf"
    cfg = {**CONFIG, "name": name, "cover": cover, "fonts": args.fonts or CONFIG.get("fonts", "B")}
    pages = render.render(sel, books, out, cfg, issue_dir=issue)
    print(f"✓ {out}（{pages} 页）")
    return out


def cmd_covers(args):
    """把排好的 PDF 的封面和封底存成图，给读者挑小样用：<期目录>/小样/<名字>-封面.png、-封底.png。"""
    import pdfplumber
    issue = Path(args.issue)
    pdf = Path(args.pdf) if args.pdf else max(issue.glob("*.pdf"), key=lambda q: q.stat().st_mtime, default=None)
    if not pdf:
        sys.exit(f"{issue} 里没有 PDF（先跑 run.py render）")
    out = issue / "小样"
    out.mkdir(exist_ok=True)
    with pdfplumber.open(pdf) as doc:
        for page, side in ((doc.pages[0], "封面"), (doc.pages[-1], "封底")):
            p = out / f"{args.name}-{side}.png"
            page.to_image(resolution=150).save(p)
            print(f"✓ {p}")


def cmd_check(args) -> bool:
    """验收第一级：脚本硬检查（条款见 rules/quality/验收.md 2.1）。zine/check.py 只量不改。"""
    import subprocess
    cmd = [sys.executable, str(ROOT / "zine" / "check.py"), str(args.issue)]
    if args.booklet:
        cmd.append("--booklet")
    if args.out:
        cmd += ["--out", args.out]
    if getattr(args, "pdf", None):
        cmd += ["--pdf", args.pdf]
    return subprocess.run(cmd).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("adapters")
    p = sub.add_parser("ingest"); p.add_argument("inbox"); p.add_argument("--work", default=str(ROOT / "work"))
    p = sub.add_parser("prepare"); p.add_argument("booklist"); p.add_argument("--issue")
    p = sub.add_parser("show"); p.add_argument("issue"); p.add_argument("book"); p.add_argument("chapter")
    p = sub.add_parser("select"); p.add_argument("issue"); p.add_argument("--api", action="store_true")
    p = sub.add_parser("translate"); p.add_argument("issue"); p.add_argument("--api", action="store_true")
    p = sub.add_parser("render"); p.add_argument("issue"); p.add_argument("--fonts", help="字体组合 A/B/C/D，见 rules/typesetting/fonts.md"); p.add_argument("--out"); p.add_argument("--style", choices=["A", "B"], help="扉页排法：A 色块 / B 白底加索引条")
    p = sub.add_parser("covers"); p.add_argument("issue"); p.add_argument("--name", default="方向1", help="这个小样叫什么"); p.add_argument("--pdf")
    p = sub.add_parser("check"); p.add_argument("issue"); p.add_argument("--booklet", action="store_true", help="骑马钉：页数不是 4 的倍数算不通过"); p.add_argument("--out"); p.add_argument("--pdf", help="查哪一份 PDF（比如方案 B 那份）")
    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(0 if cmd_check(args) else 1)
    {"adapters": cmd_adapters, "covers": cmd_covers, "ingest": cmd_ingest, "prepare": cmd_prepare, "show": cmd_show, "select": cmd_select,
     "translate": cmd_translate, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
    main()
