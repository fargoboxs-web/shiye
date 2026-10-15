"""第 3 步后半：AI 编辑从每本书里挑一篇，最多再配两三句导读。

两种跑法，产物都是同一个 selection.json：
  - agent 模式（默认）：在 Claude Code / skill 里运行，由当前会话里的 Claude 读 candidates.md、
    用 `run.py show` 读全文，然后直接写 selection.json。不需要 API key。
  - api 模式：`run.py select --api`，脚本自己调 Claude API（需要 ANTHROPIC_API_KEY），适合放进定时任务。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .parse import size_label

MODEL = "claude-opus-5-5"
MAX_CHARS = 12000       # rules/editor/selection.md：每篇 5000–12000 汉字，超过就要求节选
MAX_WORDS = 6500        # 外文书按英文词数（译成中文约 1.7 字 / 词）
EXCERPT_TARGET = 8000   # 节选目标（汉字）
EXCERPT_TARGET_WORDS = 4500


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
    for f in ("number", "date"):
        if not selection.get("issue", {}).get(f):
            problems.append(f"issue: 缺少 {f}")
    return problems


# ---------------------------------------------------------------- API 模式

PIECE_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter": {"type": "integer"},
        "excerpt_from": {"type": "integer"},
        "excerpt_to": {"type": "integer"},
        "context": {"type": "string"},
        "intro": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "object", "properties": {"term": {"type": "string"}, "note": {"type": "string"}},
                                             "required": ["term", "note"], "additionalProperties": False}},
    },
    "required": ["chapter", "excerpt_from", "excerpt_to", "context", "intro", "notes"],
    "additionalProperties": False,
}

EDITOR_SYSTEM = """你是一本只为一位读者编的个人杂志的编辑。你从一本书里只挑一篇（一章，或一章里的一段连续节选），
标准是：对这位读者此刻最有意义，而且能脱离全书单独读完。读者画像如下，它是唯一的挑选依据：

{profile}

杂志做得很轻：没有卷首语，没有编者按。每本书前有一页扉页，上面两段字：
- "引子"（context）：把引出这本书的那个想法本身直接写出来（三五句），让读者带着问题去读。只写想法，
  不写它来自谁、谁推荐、评价如何（"某博主""书单第几""推荐回来读"这类信息对读者没用）。用"你 / 我们"，不用第三人称转述。
- "本期选读"下面的摘要（intro）：像摘要一样讲清楚选的这一节讲了什么、得出什么结论，两三句到一小段。
  不写保守的话（"没有收录图片""台版译文、用词保留原样"）、不解释为什么选它。每一个字都要对读者读这一章有用。
- 脚注（notes，每篇三到五条，宁少勿多）：term 是正文里原样出现的词，note 是注文。只注读者大概率不认识、不懂又会卡住阅读的东西：
  没介绍就出现的人名和作品、专业术语、典故、台版和大陆不同的译名、中文版明显译错或印错的地方。正文自己已经解释的、常识、
  作者自造并在下文解释的词都不注。注文一两句、六十字以内：先说是什么或是谁，再补和这段文字有关的那一点；外文给原词；不评价不延伸。"""


def _ask(client, system: str, user: str, schema: dict) -> dict:
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"模型拒绝了这次请求：{msg.stop_details}")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)


def select_with_api(books: dict[str, dict], profile: str, issue_meta: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    system = EDITOR_SYSTEM.format(profile=profile)
    pieces = []
    for key, book in books.items():
        overview = json.dumps(chapter_overview(book), ensure_ascii=False, indent=1)
        first = _ask(client, system,
                     f"书：{book.get('title')} / {book.get('author')}\n收藏线索：{book.get('why_saved', '无')}\n\n"
                     f"章节概览（index、标题、篇幅、开头和中段摘录）：\n{overview}\n\n"
                     "先只决定选哪一章：excerpt 填 -1，context 和 intro 填空字符串。",
                     PIECE_SCHEMA)
        idx = first["chapter"]
        full = numbered_chapter(book, idx)
        need_cut = too_long(next(c for c in book["chapters"] if c["index"] == idx))
        piece = _ask(client, system,
                     f"书：{book.get('title')} / {book.get('author')}\n你选了这一章，全文如下（每段前有编号）：\n\n{full}\n\n"
                     + (f"这一章太长，请选一段连续、能独立成篇的节选，约 {EXCERPT_TARGET} 字（外文约 {EXCERPT_TARGET_WORDS} 词），用 excerpt_from/excerpt_to 给出段落编号（含两端）。\n"
                        if need_cut else "不用节选，excerpt_from/excerpt_to 都填 -1。\n")
                     + "然后用中文写 context（引子，不超过 250 字：把收藏线索里引出这本书的那个想法本身写出来，不提出处和评价）"
                       "和 intro（导读，两三句，不超过 150 字，只讲这一章本身：在说什么、关键术语、读时注意什么；"
                       f"不写感想）。chapter 填 {idx}。",
                     PIECE_SCHEMA)
        p = {"book": key, "chapter": idx, "context": piece["context"], "intro": piece["intro"], "notes": piece.get("notes") or []}
        if need_cut and piece["excerpt_from"] >= 0:
            p["excerpt"] = {"from": piece["excerpt_from"], "to": piece["excerpt_to"]}
        pieces.append(p)
    return {"issue": dict(issue_meta), "pieces": pieces}
