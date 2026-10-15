"""第 1 步的来源之一：Get笔记（得到大脑）Open API。

直接调 REST，不经过官方 MCP。凭证从环境变量读：GETNOTE_API_KEY、GETNOTE_CLIENT_ID。
对外只暴露三个函数，和 mcp-spec.md 里的来源接口一一对应：
  list_items(since)  -> 本周条目的摘要列表
  get_item(id)       -> 一条笔记的原文（按类型取对字段）
  search_items(q)    -> 语义搜索
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("GETNOTE_API_URL", "https://openapi.biji.com/open/api/v1")
TIMEOUT = 30


class GetNoteError(Exception):
    pass


def _creds() -> tuple[str, str]:
    key, cid = os.environ.get("GETNOTE_API_KEY"), os.environ.get("GETNOTE_CLIENT_ID")
    if not key or not cid:
        raise GetNoteError("缺少环境变量 GETNOTE_API_KEY / GETNOTE_CLIENT_ID")
    return key, cid


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    key, cid = _creds()
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "X-Client-ID": cid,
        "Content-Type": "application/json",
        "User-Agent": "book-zine/0.1",
    })
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read().decode()
            break
        except urllib.error.HTTPError as e:
            # 实测并发调 note/detail 会触发 429（code 10202），退避重试即可
            if e.code == 429 and attempt < 5:
                time.sleep(2 ** attempt)
                continue
            raise GetNoteError(f"{method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    # 笔记 id 超过 JS 安全整数，但 Python 的 int 没这个问题；统一转成字符串即可
    payload = json.loads(raw, parse_int=lambda s: s)
    # Open API 可能包一层 {code, data} 或 {success, data}
    if isinstance(payload, dict) and "data" in payload and ("code" in payload or "success" in payload):
        if payload.get("success") is False or payload.get("code") not in (None, 0, "0", 200):
            err = payload.get("error") or {}
            raise GetNoteError(f"{path}: {err.get('reason') or payload.get('reason') or '-'} "
                               f"{err.get('message') or payload.get('message') or ''} (request_id {payload.get('request_id')})")
        return payload["data"]
    return payload


def _parse_time(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            t = dt.datetime.fromtimestamp(int(s) / (1000 if len(str(s)) > 10 else 1), dt.timezone.utc)
        except (ValueError, TypeError):
            return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))


KIND = {"plain_text": "note", "link": "article", "img_text": "note", "audio": "podcast", "local_audio": "podcast",
        "meeting": "podcast", "class": "podcast"}


def _item(n: dict) -> dict:
    return {
        "id": str(n["id"]),
        "source": "getnote",
        "kind": KIND.get(n.get("note_type", ""), n.get("note_type", "note")),
        "note_type": n.get("note_type"),
        "origin": n.get("source"),
        "title": n.get("title") or "",
        "excerpt": (n.get("content") or "")[:600],   # 列表里的 content 是 AI 摘要
        "tags": [t.get("name") for t in n.get("tags") or [] if t.get("name")],
        "saved_at": n.get("created_at"),
    }


def list_items(since: dt.datetime, max_pages: int = 50) -> list[dict]:
    """从最新一页往前翻，created_at 早于 since 就停（2026-10-12 实测：列表按创建时间倒序）。"""
    items, cursor = [], None
    for _ in range(max_pages):
        page = _request("GET", "/resource/note/list", {"cursor": cursor})
        notes = page.get("notes") or []
        for n in notes:
            t = _parse_time(n.get("created_at"))
            if t and t < since:
                return items
            items.append(_item(n))
        cursor = page.get("cursor") or page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
    return items


def get_item(note_id: str) -> dict:
    note = _request("GET", "/resource/note/detail", {"id": note_id}).get("note") or {}
    web, audio = note.get("web_page") or {}, note.get("audio") or {}
    original = web.get("content") or audio.get("original") or note.get("content") or ""
    out = _item(note)
    out.update({"content": original, "summary": note.get("content") or "", "url": web.get("url"),
                "domain": web.get("domain"), "my_note": note.get("quick_note")})
    return out


def search_items(query: str, top_k: int = 10) -> list[dict]:
    res = _request("POST", "/resource/recall", body={"query": query, "top_k": min(top_k, 10)})
    return [{"id": str(r["note_id"]), "source": "getnote", "kind": r.get("note_type"), "title": r.get("title"),
             "excerpt": (r.get("content") or "")[:600], "saved_at": r.get("created_at")} for r in res.get("results") or []]


def quota() -> dict:
    return _request("GET", "/resource/rate-limit/quota")


def write_digest(items: list[dict], path) -> None:
    """把本周条目写成一份 Markdown，给 AI 编辑读，从中找书名、更新读者画像。"""
    lines = [f"# 本周收藏（{len(items)} 条）", ""]
    for it in items:
        lines += [f"## [{it['id']}] {it['title'] or '（无标题）'}",
                  f"类型：{it['kind']} · 来源：{it.get('origin') or '-'} · 时间：{it.get('saved_at') or '-'}"
                  + (f" · 标签：{', '.join(it['tags'])}" if it.get("tags") else ""), "",
                  f"> {it['excerpt']}" if it.get("excerpt") else "> （无摘要）", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
