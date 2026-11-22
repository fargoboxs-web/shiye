"""把不是中文的选篇翻成中文。读者只读中文：原文是中文就原样用，不是就由 agent 翻译。

`run.py translate <期>` 把待译段落写成 issues/<日期>/zh/<book>.<章节号>.src.json，agent 翻译后写成同名的 .json（去掉 .src）：
  {"book", "chapter", "from", "to", "title", "blocks": [{"type", "text"}, ...]}
blocks 和所选段落一一对应（数量、顺序、type 都不变）。render 看到这个文件就用它替换原文。规矩见 rules/editor/translation.md。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .parse import CJK, count_words

def cjk_ratio(text: str) -> float:
    letters = len(re.findall(r"[A-Za-z]", text))
    cjk = len(CJK.findall(text))
    return cjk / (cjk + letters) if cjk + letters else 1.0


def selected(piece: dict, book: dict) -> tuple[dict, list[dict], int, int]:
    ch = next(c for c in book["chapters"] if c["index"] == piece["chapter"])
    ex = piece.get("excerpt")
    a, b = (ex["from"], ex["to"]) if ex else (0, len(ch["blocks"]) - 1)
    return ch, ch["blocks"][a : b + 1], a, b


def zh_path(issue_dir: Path, piece: dict, src: bool = False) -> Path:
    return issue_dir / "zh" / f"{piece['book']}.{piece['chapter']}{'.src' if src else ''}.json"


def load(issue_dir: Path, piece: dict, book: dict) -> dict | None:
    """已有且和当前所选段落对得上的译文；对不上（节选范围改过）就当没有。"""
    p = zh_path(issue_dir, piece)
    if not p.exists():
        return None
    zh = json.loads(p.read_text(encoding="utf-8"))
    _, blocks, a, b = selected(piece, book)
    if zh.get("from") != a or zh.get("to") != b or len(zh.get("blocks") or []) != len(blocks):
        return None
    return zh


def pending(issue_dir: Path, selection: dict, books: dict[str, dict]) -> list[dict]:
    out = []
    for piece in selection["pieces"]:
        book = books[piece["book"]]
        _, blocks, _, _ = selected(piece, book)
        if cjk_ratio(" ".join(b["text"] for b in blocks)) < 0.5 and load(issue_dir, piece, book) is None:
            out.append(piece)
    return out


def write_src(issue_dir: Path, piece: dict, book: dict) -> Path:
    ch, blocks, a, b = selected(piece, book)
    p = zh_path(issue_dir, piece, src=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"book": piece["book"], "chapter": piece["chapter"], "from": a, "to": b,
                             "title": ch["title"], "blocks": blocks}, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def run(issue_dir: Path, selection: dict, books: dict[str, dict]) -> list[Path]:
    """返回还没译完的 src 文件。"""
    return [write_src(issue_dir, piece, books[piece["book"]]) for piece in pending(issue_dir, selection, books)]
