"""第 1 步：收件箱 inbox/ → work/notes.jsonl。

软约定：认得出的都收，认不出的列出来给 AI 自己看（见 interfaces/inbox.md）。
每条归成同一张表：id, source, kind, time, title, url, text, images, tags, note。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

TEXT_KEYS = ("text", "content", "body", "desc", "description", "transcript", "original", "excerpt")
TIME_KEYS = ("time", "saved_at", "created_at", "date", "published_at", "updated_at")
URL_KEYS = ("url", "link", "href", "web_url", "webUrl")
NOTE_KEYS = ("note", "my_note", "comment", "remark")
TITLE_KEYS = ("title", "name", "subject", "display_title", "displayTitle")
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
TEXT_EXT = {".md", ".txt", ".markdown"}
_DATE = re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})")
_TAG = re.compile(r"<[^>]+>")


def _first(d: dict, keys) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (str, int, float)) and str(v).strip():
            return str(v).strip()
    return None


def _date_in(name: str) -> str | None:
    m = _DATE.search(name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def normalize_item(raw: dict, source: str = "file", fallback_id: str | None = None, time_hint: str | None = None) -> dict | None:
    """任何来源的一条记录 → notes.jsonl 的一行。认不出正文就返回 None。"""
    nested = raw.get("web_page") if isinstance(raw.get("web_page"), dict) else {}
    text = _first(raw, TEXT_KEYS) or _first(nested, TEXT_KEYS)
    if not text:
        return None
    rid = _first(raw, ("id", "note_id", "noteId", "uid"))
    src = _first(raw, ("source",)) or source
    item = {
        "id": f"{src}:{rid}" if rid and ":" not in rid else (rid or fallback_id or f"{src}:{hashlib.md5(text.encode()).hexdigest()[:10]}"),
        "source": src,
        "kind": _first(raw, ("kind", "note_type", "type")) or "note",
        "time": _first(raw, TIME_KEYS) or time_hint,
        "title": _first(raw, TITLE_KEYS),
        "url": _first(raw, URL_KEYS) or _first(nested, URL_KEYS),
        "text": text,
        "images": [str(x) for x in (raw.get("images") or raw.get("imgs") or raw.get("image_list") or []) if x],
        "tags": [str(x) for x in (raw.get("tags") or []) if x],
        "note": _first(raw, NOTE_KEYS),
    }
    return item


def _from_text_file(p: Path, inbox: Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if p.suffix.lower() in (".html", ".htm"):
        text = re.sub(r"\s+\n", "\n", _TAG.sub(" ", text))
    title = None
    m = re.match(r"^#\s+(.+)$", text, re.M)
    if m:
        title = m.group(1).strip()
    imgs = sorted(str(q.relative_to(inbox.parent)) for q in p.parent.iterdir()
                  if q.suffix.lower() in IMG_EXT and (q.stem == p.stem or p.parent != inbox))
    rel = str(p.relative_to(inbox))
    return {"id": f"file:{hashlib.md5(rel.encode()).hexdigest()[:10]}", "source": "file", "kind": "note",
            "time": _date_in(p.name) or _date_in(str(p.parent.name)), "title": title or p.stem, "url": None,
            "text": text, "images": imgs, "tags": [], "note": None}


def _records(p: Path):
    """json / jsonl / csv 文件里的记录，逐条产出 dict。"""
    suf = p.suffix.lower()
    if suf == ".jsonl":
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    elif suf == ".json":
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            for k in ("items", "notes", "data", "results", "list"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if isinstance(data, list):
            for r in data:
                if isinstance(r, dict):
                    yield r
        elif isinstance(data, dict):
            yield data
    elif suf == ".csv":
        with p.open(encoding="utf-8", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                yield r


def ingest(inbox: Path, work: Path) -> dict:
    inbox, work = Path(inbox), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    items, unknown, seen = [], [], set()
    for p in sorted(inbox.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        suf = p.suffix.lower()
        if suf in IMG_EXT:
            continue   # 图片跟正文配对，不单独算一条
        if suf in TEXT_EXT or suf in (".html", ".htm"):
            its = [_from_text_file(p, inbox)]
        elif suf in (".json", ".jsonl", ".csv"):
            src = p.stem.split("-")[0].split("_")[0].lower() if re.match(r"^[A-Za-z]", p.stem) else "file"
            its = [normalize_item(r, source=src, time_hint=_date_in(p.name)) for r in _records(p)]
            its = [i for i in its if i]
        else:
            unknown.append(str(p.relative_to(inbox)))
            continue
        for it in its:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            items.append(it)
    items.sort(key=lambda i: (i.get("time") or ""), reverse=True)
    with (work / "notes.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    lines = [f"# 笔记摘要（{len(items)} 条，按时间倒序）", ""]
    for it in items:
        head = f"- **{it.get('title') or '（无题）'}** · {it['source']} · {it.get('time') or '时间不明'} · `{it['id']}`"
        body = re.sub(r"\s+", " ", it["text"])[:160]
        lines += [head, f"  {body}" + ("…" if len(it["text"]) > 160 else ""), ""]
    if unknown:
        lines += ["## 没认出来的文件（AI 自己看）", ""] + [f"- {u}" for u in unknown]
    (work / "notes-digest.md").write_text("\n".join(lines), encoding="utf-8")
    return {"items": len(items), "unknown": unknown, "notes": work / "notes.jsonl", "digest": work / "notes-digest.md"}
