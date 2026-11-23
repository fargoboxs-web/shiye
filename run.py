#!/usr/bin/env python3
"""拾页：笔记 → 方案 → 一本 A5 小册子的 PDF。

脚本只做确定性的事；判断题（画像、书单、选篇、写作、刊名、封面）由 agent 做，步骤见 skills/shiye/SKILL.md。
在读者的工作目录里运行（或设环境变量 SHIYE_HOME）；笔记、书、每一期都在工作目录，不在 skill 目录。

  python3 <skill>/run.py init                    # 第一次：在当前目录建 inbox/ books/ issues/ 和 .env
  python3 <skill>/run.py doctor                  # 自检：依赖、字体、每个连接器接没接上
  python3 <skill>/run.py pull                    # 按接上的连接器把笔记拉进 inbox/，再整理成 work/notes.jsonl
  python3 <skill>/run.py prepare books.yaml      # 拆书 → issues/<今天>/candidates.md；缺的书记进 缺书.md
  python3 <skill>/run.py show <期> <book> <章>    # 看一章全文（带段落编号）
  python3 <skill>/run.py plan <期>               # 按 selection.json 写 方案.md（选了什么、估多少页、缺什么书）
  python3 <skill>/run.py translate <期>          # 列出不是中文的选篇
  python3 <skill>/run.py render <期>             # 排成 PDF
  python3 <skill>/run.py covers <期>             # 把封面封底存成图
  python3 <skill>/run.py check <期>              # 质检 → 检查报告.md
<期> 可以写日期（2026-11-12）或期目录的路径。
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

import os

ROOT = Path(__file__).resolve().parent                    # skill 目录：引擎、规则、连接器、字体
HOME = Path(os.environ.get("SHIYE_HOME") or Path.cwd())   # 读者的工作目录：inbox/ books/ issues/ work/ reader.md .env
sys.path.insert(0, str(ROOT))

from zine import inbox, parse, render, select, translate  # noqa: E402

CONFIG = {"name": "拾页", "pad_to_4": True}   # 总页数补成 4 的倍数（骑马钉；差的页补成空白笔记页，放在封底前）
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


def issue_dir(x: str | None, create: bool = False) -> Path:
    """<期> 可以是日期或路径；不写就是今天（create）或最近一期。"""
    if x:
        p = Path(x)
        if not p.exists() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x):
            p = HOME / "issues" / x
        return p
    if create:
        return HOME / "issues" / dt.date.today().isoformat()
    done = sorted(d for d in (HOME / "issues").glob("*") if d.is_dir())
    if not done:
        sys.exit("issues/ 里还没有任何一期")
    return done[-1]


def adapters() -> dict[str, dict]:
    sys.path.append(str(ROOT / "adapters"))
    import env
    env.load(HOME / ".env")
    out = {}
    for p in sorted((ROOT / "adapters").glob("*/adapter.json")):
        try:
            out[p.parent.name] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"✗ adapters/{p.parent.name}/adapter.json 读不了：{e}")
    return out


def adapter_missing(m: dict) -> list[str]:
    return [a["env"] for a in m.get("ask", []) if not a.get("optional") and not os.environ.get(a["env"])]


def cmd_init(args):
    for d in ("inbox", "books", "issues"):
        (HOME / d).mkdir(parents=True, exist_ok=True)
    envf = HOME / ".env"
    if not envf.exists():
        lines = ["# 拾页的凭证。只放在这里，不要发给任何人，不要提交到 git。", ""]
        seen = set()
        for name, m in adapters().items():
            new = [a["env"] for a in m.get("ask", []) if a["env"] not in seen]
            seen.update(new)
            if new:
                lines += [f"# {m.get('title', name)}", *[f"{k}=" for k in new], ""]
        envf.write_text("\n".join(lines), encoding="utf-8")
    gi = HOME / ".gitignore"
    if not gi.exists():
        gi.write_text(".env\n", encoding="utf-8")
    print(f"✓ 工作目录 {HOME}：inbox/（放笔记）、books/（放电子书）、issues/（每一期）、.env（凭证）")


def cmd_doctor(args):
    """自检。只看环境变量在不在，不打印值。全部通过返回 0。"""
    import importlib
    import subprocess
    bad = 0
    for mod, pip in (("weasyprint", "weasyprint"), ("ebooklib", "ebooklib"), ("bs4", "beautifulsoup4"), ("lxml", "lxml"),
                     ("pypdf", "pypdf"), ("pdfplumber", "pdfplumber"), ("yaml", "pyyaml"), ("jinja2", "jinja2"), ("PIL", "pillow")):
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"✗ 缺 Python 包 {pip}（{type(e).__name__}）：pip install -r {ROOT / 'requirements.txt'}")
    fonts = [f for f in ("NotoSerifSC[wght].ttf", "NotoSansSC[wght].ttf", "LXGWWenKai-Regular.ttf") if not (ROOT / "fonts" / f).exists()]
    if fonts:
        bad += 1
        print(f"✗ 缺字体 {'、'.join(fonts)}：bash {ROOT / 'scripts' / 'fetch-fonts.sh'}")
    if not bad:
        print("✓ 排版引擎：依赖和字体都在")
    if not (HOME / "inbox").is_dir():
        bad += 1
        print(f"✗ {HOME} 还不是工作目录：先跑 run.py init")
    ads = adapters()
    notes_ok = 0
    for name, m in ads.items():
        kind = {"notes": "笔记", "books": "书"}.get(m.get("kind"), "?")
        lack = adapter_missing(m)
        if lack:
            print(f"– 【{kind}】{m.get('title', name)}：没接（缺 {'、'.join(lack)}，写进工作目录的 .env）")
            continue
        state = "凭证已填"
        if m.get("test"):
            r = subprocess.run([sys.executable, str(ROOT / "adapters" / name / m["test"])], capture_output=True, text=True, cwd=HOME)
            if r.returncode:
                bad += 1
                print(f"✗ 【{kind}】{m.get('title', name)}：凭证填了但连不上：{(r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else '没有输出'}")
                continue
            state = "连通"
        elif m.get("test_by_agent"):
            state = "凭证已填；" + m["test_by_agent"]
        notes_ok += m.get("kind") == "notes"
        print(f"✓ 【{kind}】{m.get('title', name)}：{state}")
    files = [p for p in (HOME / "inbox").rglob("*") if p.is_file()] if (HOME / "inbox").is_dir() else []
    if not notes_ok and not files:
        bad += 1
        print("✗ 没有任何笔记来源：接一个笔记连接器，或者把笔记文件放进 inbox/")
    elif files:
        print(f"✓ inbox/ 里有 {len(files)} 个文件")
    sys.exit(1 if bad else 0)


def cmd_pull(args):
    """按接上的笔记连接器拉取，再整理。一个都没接也行：只整理 inbox/ 里已有的文件。"""
    import subprocess
    for name, m in adapters().items():
        if m.get("kind") != "notes" or not m.get("pull") or adapter_missing(m):
            continue
        cmd = [sys.executable, str(ROOT / "adapters" / name / m["pull"][0]), *m["pull"][1:], "--inbox", str(HOME / "inbox")]
        print(f"→ {m.get('title', name)}" + (f"（{m['costs']}）" if m.get("costs") else ""))
        if subprocess.run(cmd, cwd=HOME).returncode:
            print(f"✗ {m.get('title', name)} 没拉成，继续做其余的", file=sys.stderr)
    r = inbox.ingest(HOME / "inbox", HOME / "work")
    print(f"✓ {r['items']} 条 → {r['notes']}；摘要 {r['digest']}")
    if r["unknown"]:
        print("没认出来的文件（自己打开看）：" + "、".join(r["unknown"]))


def cmd_prepare(args) -> Path:
    booklist = Path(args.booklist).absolute()
    spec = yaml.safe_load(booklist.read_text(encoding="utf-8"))
    entries = spec["books"] if isinstance(spec, dict) else spec
    issue = issue_dir(args.issue, create=True)
    (issue / "books").mkdir(parents=True, exist_ok=True)
    books, missing = {}, []
    for e in entries:
        if isinstance(e, str):
            e = {"title": e}
        key = e.get("key") or slug(e.get("original_title") or e["title"])
        if not e.get("file"):
            local = find_local_book(e, [booklist.parent / "books", HOME / "books"])
            if local:
                e = {**e, "file": str(local)}
                print(f"  《{e['title']}》没写 file，用本地文件 {local.name}")
        path = Path(e["file"]).expanduser() if e.get("file") else None
        if path and not path.is_absolute():
            path = booklist.parent / path
        if not path or not path.exists():
            missing.append((e["title"], "books/ 里没有这本书的电子书" if not e.get("file") else f"找不到文件 {e['file']}"))
            continue
        book = parse.parse(path)
        body = sum(c.get("chars", 0) + c.get("words", 0) for c in book.get("chapters", []))
        if not book.get("chapters") or body < 3000:
            why = "是扫描版 PDF，没有文字层" if path.suffix.lower() == ".pdf" else "拆不出正文"
            missing.append((e["title"], f"{path.name} {why}，用不了；换一个 EPUB 或带文字的版本"))
            continue
        simplified = parse.maybe_simplify(book)
        n_img = parse.export_images(path, book, issue / "books" / f"{key}.img", f"{key}.img") if path.suffix.lower() == ".epub" else 0
        cover = parse.extract_cover(path)
        if cover:
            (issue / "books" / f"{key}.cover{cover[1]}").write_bytes(cover[0])
            book["cover"] = f"{key}.cover{cover[1]}"
        book.update({k: v for k, v in e.items() if k in ("author", "year", "why_saved", "rights", "translator")})
        # 书名以 books.yaml 为准：电子书元数据里常是带副题和广告语的长串
        if book.get("title") and book["title"] != e["title"]:
            book["source_title"] = book["title"]
        book["title"] = e["title"]
        book["display_title"] = e.get("display_title") or e["title"]
        book["original_title"] = e.get("original_title") or (e["title"] if e.get("display_title") else None)
        book["source"] = {"licensed": "书库（出版方授权）", "public_domain": "公版书"}.get(e.get("rights"), "读者自备电子书") \
            + ("，繁体转简体" if simplified else "")
        (issue / "books" / f"{key}.json").write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        books[key] = book
        print(f"✓ {key}: {book.get('title')} / {book.get('author', '')}{'，' + book['translator'] + ' 译' if book.get('translator') else ''}"
              f" — {len(book['chapters'])} 章 [{book['source']}]{'，有封面' if cover else '，没找到封面'}，插图 {n_img} 张")
    if missing:
        lines = ["# 缺书", "", "下面这些书没有拿到能用的全文，这一期先不做它们。补上文件（放进 books/ 或在 books.yaml 写 file:）再跑一次 prepare。", ""]
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
    book = load_books(issue_dir(args.issue))[args.book]
    print(select.numbered_chapter(book, int(args.chapter)))


# 页数预估：第 3 期七篇的实测回归（汉字数、图数、段数 → 正文页数），误差一成半以内
def estimate_pages(chars: int, imgs: int, blocks: int) -> int:
    import math
    return math.ceil(chars * 0.00135 + imgs * 0.34 + blocks * 0.03) + 1      # +1 是篇首页


def cmd_plan(args):
    """把 selection.json 写成给读者看的 方案.md：选了哪几篇、为什么、估多少页、缺哪些书。读者点头之后才往下做。"""
    issue = issue_dir(args.issue)
    books = load_books(issue)
    sel = json.loads((issue / "selection.json").read_text(encoding="utf-8"))
    sel.setdefault("issue", {}).setdefault("date", issue.name)
    problems = select.validate(sel, books, issue)
    if problems:
        sys.exit("selection.json 有问题：\n  " + "\n  ".join(problems))
    rows, total = [], 3                                          # 封面、目录、封底
    for n, p in enumerate(sel["pieces"], 1):
        book = books[p["book"]]
        ch, blocks, a, z = translate.selected(p, book)
        text = [b for b in blocks if b.get("type") != "img"]
        chars = sum(len(b.get("text", "")) for b in text)
        foreign = translate.cjk_ratio(" ".join(b.get("text", "") for b in text[:40])) < 0.3
        if foreign:                                              # 外文：按词数折成汉字
            chars = int(sum(len(b.get("text", "").split()) for b in text) * 1.7)
        pages = estimate_pages(chars, len(blocks) - len(text), len(text))
        total += pages
        why = (p.get("context") or "").strip() or "（还没写为什么选这一篇）"
        rows.append(f"### {n}. 《{book.get('display_title') or book.get('title')}》　{book.get('author') or ''}\n\n"
                    f"- 选的是：{p.get('title') or ch['title']}" + ("（节选）" if p.get("excerpt") else "") + "\n"
                    f"- 约 {chars} 字{'（外文，要翻译）' if foreign else ''}，估 {pages} 页\n"
                    f"- 为什么是这一篇：{why}\n")
    padded = total + (-total) % 4
    n = len(sel["pieces"])
    verdict = []
    if not 5 <= n <= 6:
        verdict.append(f"篇数 {n}，建议 5–6 篇")
    long = [str(i) for i, r in enumerate(rows, 1) if int(re.search(r"估 (\d+) 页", r).group(1)) > 21]
    if long:
        verdict.append(f"第 {'、'.join(long)} 篇超过 20 页，偏长，节选短一点")
    if not 80 <= padded <= 100:
        verdict.append(f"估 {padded} 页，建议 80–100 页（{'太厚，减一篇或多节选' if padded > 100 else '偏薄，可以加一篇'}）")
    lines = [f"# 这一期的方案（{issue.name}）", "",
             f"{n} 篇，估 **{padded} 页**（A5，含封面、目录、封底）。" + ("篇数和厚度都合适。" if not verdict else "注意：" + "；".join(verdict) + "。"), "",
             "你看一眼：书对不对、篇目想不想读。要换哪本、去掉哪篇，直接说；没问题说一声，接着排版。", "", *rows]
    miss = issue / "缺书.md"
    if miss.exists():
        got = [ln for ln in miss.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
        if got:
            lines += ["## 没拿到的书", "", "这几本想放但没有全文。你有电子书的话放进 books/，我重新来；没有就先不做它们。", "", *got, ""]
    out = issue / "方案.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ {out}：{n} 篇，估 {padded} 页" + ("；" + "；".join(verdict) if verdict else ""))


def cmd_translate(args) -> bool:
    issue = issue_dir(args.issue)
    books = load_books(issue)
    sel = json.loads((issue / "selection.json").read_text(encoding="utf-8"))
    left = translate.run(issue, sel, books)
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
    issue = issue_dir(args.issue)
    books = load_books(issue)
    sel = json.loads((issue / "selection.json").read_text(encoding="utf-8"))
    sel.setdefault("issue", {}).setdefault("date", issue.name)
    problems = select.validate(sel, books, issue)
    if problems:
        sys.exit("selection.json 有问题：\n  " + "\n  ".join(problems))
    untranslated = translate.pending(issue, sel, books)
    if untranslated:
        sys.exit("还有选篇不是中文，先跑 `run.py translate`：" + ", ".join(f"{p['book']} 第 {p['chapter']} 章" for p in untranslated))
    cover = load_cover(issue)
    name = cover.get("title") or CONFIG["name"]
    # cover.json 里和整期配色有关的几项交给排版：每篇一个颜色、封面底色、标签颜色、篇首页色块的边
    for k in ("layers", "paper", "label_colors", "divider_edge"):
        if cover.get(k):
            sel["issue"][k] = cover[k]
    sel["issue"]["name"] = name
    out = Path(args.out) if args.out else issue / f"{name}-{issue.name}.pdf"
    cfg = {**CONFIG, "name": name, "cover": cover}
    pages = render.render(sel, books, out, cfg, issue_dir=issue)
    print(f"✓ {out}（{pages} 页）")
    return out


def cmd_covers(args):
    """把排好的 PDF 的封面和封底存成图，给读者挑小样用：<期目录>/小样/<名字>-封面.png、-封底.png。"""
    import pdfplumber
    issue = issue_dir(args.issue)
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
    """验收第一级：脚本硬检查（怎么读报告见 rules/quality/验收.md）。zine/check.py 只量不改。"""
    import subprocess
    cmd = [sys.executable, str(ROOT / "zine" / "check.py"), str(issue_dir(args.issue))]
    if args.out:
        cmd += ["--out", args.out]
    if getattr(args, "pdf", None):
        cmd += ["--pdf", args.pdf]
    return subprocess.run(cmd).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "doctor", "pull"):
        sub.add_parser(name)
    p = sub.add_parser("prepare"); p.add_argument("booklist"); p.add_argument("--issue")
    p = sub.add_parser("show"); p.add_argument("issue"); p.add_argument("book"); p.add_argument("chapter")
    for name in ("plan", "translate"):
        p = sub.add_parser(name); p.add_argument("issue", nargs="?")
    p = sub.add_parser("render"); p.add_argument("issue", nargs="?"); p.add_argument("--out")
    p = sub.add_parser("covers"); p.add_argument("issue", nargs="?"); p.add_argument("--name", default="方向1", help="这个小样叫什么"); p.add_argument("--pdf")
    p = sub.add_parser("check"); p.add_argument("issue", nargs="?"); p.add_argument("--out"); p.add_argument("--pdf")
    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(0 if cmd_check(args) else 1)
    {"init": cmd_init, "doctor": cmd_doctor, "pull": cmd_pull, "covers": cmd_covers, "prepare": cmd_prepare, "show": cmd_show,
     "plan": cmd_plan, "translate": cmd_translate, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
    main()
