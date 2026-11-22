"""选篇的辅助：把每本书的章节列成 candidates.md 给 agent 读，校验 agent 写的 selection.json。选篇本身由 agent 做。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .parse import size_label

MAX_CHARS = 12000       # rules/editor/selection.md：每篇 5000–12000 汉字，超过就要求节选
MAX_WORDS = 6500        # 外文书按英文词数（译成中文约 1.7 字 / 词）


def too_long(ch: dict) -> bool:
    return ch.get("chars", 0) > MAX_CHARS if ch.get("chars", 0) > ch.get("words", 0) else ch["words"] > MAX_WORDS


def chapter_overview(book: dict) -> list[dict]:
    chs = [c for c in book["chapters"] if c["kind"] == "main"] or book["chapters"]
    out = []
    for c in chs:
        paras = [b["text"] for b in c["blocks"] if b["type"] == "p"]
        opening = " ".join(paras)[:700]
        mid = paras[len(paras) // 2][:350] if len(paras) > 2 else ""
        out.append({"index": c["index"], "title": c["title"], "words": c["words"], "chars": c.get("chars", 0),
                    "size": size_label(c), "opening": opening, "middle": mid})
    return out


def write_candidates(issue_dir: Path, books: dict[str, dict]) -> Path:
    lines = ["# 本期候选章节", "", f"篇幅按汉字数算（外文书按英文词数）：超过 {MAX_CHARS} 字（外文 {MAX_WORDS} 词）的章节需要节选，在 selection.json 里给 excerpt；"
             "每篇目标 5000–12000 字，短章（两三千字）也可以选，见 rules/editor/selection.md。", ""]
    for key, book in books.items():
        lines += [f"## {key}：{book.get('title')} / {book.get('author', '')}", ""]
        if book.get("why_saved"):
            lines += [f"收藏时的线索：{book['why_saved']}", ""]
        for c in chapter_overview(book):
            lines += [f"### [{c['index']}] {c['title']}（{c['size']}）", "", f"> {c['opening']}…", ""]
            if c["middle"]:
                lines += [f"> （中段）{c['middle']}…", ""]
    p = issue_dir / "candidates.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def numbered_chapter(book: dict, index: int) -> str:
    ch = next(c for c in book["chapters"] if c["index"] == index)
    rows = [f"# {ch['title']}（{size_label(ch)}）"]
    for i, b in enumerate(ch["blocks"]):
        rows.append(f"[{i}] {b['text']}")
    return "\n\n".join(rows)


# ---------------------------------------------------------------- 校验

def _squash(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("_", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def validate(selection: dict, books: dict[str, dict]) -> list[str]:
    problems = []
    for n, piece in enumerate(selection.get("pieces", [])):
        tag = f"pieces[{n}]"
        book = books.get(piece.get("book"))
        if not book:
            problems.append(f"{tag}: book '{piece.get('book')}' 不在本期书单里")
            continue
        ch = next((c for c in book["chapters"] if c["index"] == piece.get("chapter")), None)
        if not ch:
            problems.append(f"{tag}: 章节 {piece.get('chapter')} 不存在")
            continue
        blocks = ch["blocks"]
        ex = piece.get("excerpt")
        if ex:
            a, b = ex.get("from"), ex.get("to")
            if not (isinstance(a, int) and isinstance(b, int) and 0 <= a <= b < len(blocks)):
                problems.append(f"{tag}: excerpt 段落范围 {a}-{b} 越界（共 {len(blocks)} 段）")
                continue
            blocks = blocks[a : b + 1]
        elif too_long(ch):
            problems.append(f"{tag}: 《{ch['title']}》{size_label(ch)}，超过 {MAX_CHARS} 字（外文 {MAX_WORDS} 词），需要给 excerpt")
        intro = piece.get("intro") or ""
        if len(intro) > 320:
            problems.append(f"{tag}: 摘要 {len(intro)} 字，太长了（最多 320 字，扉页要放得下）")
        context = piece.get("context") or ""
        if len(context) > 600:
            problems.append(f"{tag}: 引子 {len(context)} 字，太长了（最多 600 字，扉页要放得下）")
        text = "\n".join(b["text"] for b in blocks if b["type"] != "img")
        for n, note in enumerate(piece.get("notes") or []):
            if not note.get("term") or not note.get("note"):
                problems.append(f"{tag}.notes[{n}]: 要有 term 和 note")
            elif note["term"] not in text:
                problems.append(f"{tag}.notes[{n}]: 正文里找不到「{note['term']}」")
    for f in ("date",):          # 期数可以不填（interfaces/schemas/selection.schema.json）
        if not selection.get("issue", {}).get(f):
            problems.append(f"issue: 缺少 {f}")
    return problems
