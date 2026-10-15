"""第 3.5 步：把不是中文的选篇翻成中文。

读者只读中文：原文是中文就原样用，不是就翻译。产物放在 issues/<日期>/zh/<book>.<章节号>.json：
  {"book", "chapter", "from", "to", "title", "blocks": [{"type", "text"}, ...]}
blocks 和所选段落一一对应（数量、顺序、type 都不变）。render 看到这个文件就用它替换原文。

两种跑法：
  - agent 模式（默认）：`run.py translate <issue>` 把待译段落写成 zh/<book>.<章节号>.src.json，
    由会话里的 Claude 翻译后写成同名的 .json（去掉 .src）。
  - api 模式：`run.py translate <issue> --api`，脚本分段调 Claude API（需要 ANTHROPIC_API_KEY）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .parse import CJK, count_words

MODEL = "claude-opus-5-5"
CHUNK_WORDS = 1200      # api 模式每次翻多少词

TRANSLATOR_SYSTEM = """你是一位把英文书译成简体中文的文学译者。逐段翻译给你的段落，要求：
- 译文是自然、准确的书面中文，像一本认真出版的译著，不要翻译腔，也不要擅自删改或概括。
- 输出的段落数量、顺序和输入完全一致，一段对一段。
- 人名、书名、专有名词第一次出现时在括号里保留原文，之后只用中文。
- 原文里残留的脚注编号（句末孤立的数字，如 " 16"）直接去掉。
- 诗句、引文的分行保留。
- 不要加译注、不要加标题、不要加任何解释。"""


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


# ---------------------------------------------------------------- API 模式

def _chunks(blocks: list[dict]) -> list[list[int]]:
    groups, cur, words = [], [], 0
    for i, b in enumerate(blocks):
        w = count_words(b["text"])
        if cur and words + w > CHUNK_WORDS:
            groups.append(cur)
            cur, words = [], 0
        cur.append(i)
        words += w
    if cur:
        groups.append(cur)
    return groups


def translate_api(title: str, blocks: list[dict]) -> tuple[str, list[dict]]:
    import anthropic

    client = anthropic.Anthropic()
    schema = {"type": "object", "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
              "required": ["paragraphs"], "additionalProperties": False}
    out = [None] * len(blocks)
    for idx in _chunks(blocks):
        src = [blocks[i]["text"] for i in idx]
        user = f"书的章节标题：{title}\n\n请翻译下面 {len(src)} 段，按顺序返回同样多的段落：\n\n" + \
            json.dumps(src, ensure_ascii=False, indent=1)
        for attempt in range(3):
            with client.beta.messages.stream(
                model=MODEL, max_tokens=16000, system=TRANSLATOR_SYSTEM,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
            paras = json.loads(next(b.text for b in msg.content if b.type == "text"))["paragraphs"]
            if len(paras) == len(src):
                break
        else:
            raise RuntimeError(f"翻译后段落数对不上：要 {len(src)} 段，得到 {len(paras)} 段")
        for i, t in zip(idx, paras):
            out[i] = {"type": blocks[i]["type"], "text": t}
    title_schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"],
                    "additionalProperties": False}
    with client.beta.messages.stream(
        model=MODEL, max_tokens=200, system=TRANSLATOR_SYSTEM,
        messages=[{"role": "user", "content": f"把这个章节标题译成中文，去掉编号：{title}"}],
        output_config={"format": {"type": "json_schema", "schema": title_schema}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    title_zh = json.loads(next(b.text for b in msg.content if b.type == "text"))["title"]
    return title_zh, out


def run(issue_dir: Path, selection: dict, books: dict[str, dict], api: bool = False) -> list[Path]:
    """返回还没译完的 src 文件（agent 模式）；api 模式跑完返回空列表。"""
    todo = pending(issue_dir, selection, books)
    left = []
    for piece in todo:
        book = books[piece["book"]]
        ch, blocks, a, b = selected(piece, book)
        if api:
            title_zh, zh_blocks = translate_api(ch["title"], blocks)
            zh_path(issue_dir, piece).parent.mkdir(parents=True, exist_ok=True)
            zh_path(issue_dir, piece).write_text(json.dumps(
                {"book": piece["book"], "chapter": piece["chapter"], "from": a, "to": b, "title": title_zh,
                 "blocks": zh_blocks}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"✓ 已翻译 {piece['book']} 第 {piece['chapter']} 章（{len(blocks)} 段）")
        else:
            left.append(write_src(issue_dir, piece, book))
    return left
