"""第 2 步：拿到书。

输入是 books.yaml 里的一条记录，输出是一个本地文件路径（txt / epub / pdf / html）。
只走合法来源，按顺序尝试：
  1. file:          用户自己提供的电子书文件
  2. url:           直接给出的公版书全文链接
  3. gutenberg_id:  Project Gutenberg 编号
  4. 只有书名时：   用 Gutendex（Gutenberg 的公开检索 API）按书名+作者找公版版本
找不到就明确报错，不去找来源不明的全文。
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "book-zine/0.1 (personal reading digest)"}
TIMEOUT = 30


class BookNotFound(Exception):
    pass


def _get(url: str, timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _suffix_for(url: str, data: bytes) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".epub", ".pdf", ".txt", ".html", ".htm"):
        if path.endswith(ext):
            return ext
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:2] == b"PK":
        return ".epub"
    return ".txt"


def download(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    hits = list(cache_dir.glob(f"{key}.*"))
    if hits:
        return hits[0]
    data = _get(url)
    out = cache_dir / f"{key}{_suffix_for(url, data)}"
    out.write_bytes(data)
    return out


def gutenberg_urls(gid: int) -> list[str]:
    # EPUB 优先（章节结构最干净），纯文本兜底
    return [
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}-images.epub",
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.epub",
        f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt",
    ]


def gutendex_search(title: str, author: str | None = None) -> dict | None:
    q = title if not author else f"{title} {author.split()[-1]}"
    url = "https://gutendex.com/books/?" + urllib.parse.urlencode({"search": q, "languages": "en,zh"})
    results = json.loads(_get(url)).get("results", [])
    if not results:
        return None
    t = _norm(title)
    # 书名最接近、下载量最高的版本
    results.sort(key=lambda b: (t not in _norm(b.get("title", "")), -b.get("download_count", 0)))
    return results[0]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", " ", s.lower()).strip()


def resolve(book: dict, cache_dir: Path, base_dir: Path) -> tuple[Path, str]:
    """返回 (本地文件, 来源说明)。"""
    errors = []
    if book.get("file"):
        p = Path(book["file"]).expanduser()
        if not p.is_absolute():
            p = base_dir / p
        if p.exists():
            return p, "读者自备电子书"
        errors.append(f"file 不存在：{p}")

    urls: list[tuple[str, str]] = []
    gid = book.get("gutenberg_id")
    if book.get("url"):
        urls.append((book["url"], book.get("source_label") or (f"Project Gutenberg #{gid}" if gid else "公版书")))
    if book.get("gutenberg_id"):
        gid = int(book["gutenberg_id"])
        urls += [(u, f"Project Gutenberg #{gid}") for u in gutenberg_urls(gid)]

    for url, label in urls:
        try:
            return download(url, cache_dir), label
        except Exception as e:  # 网络被拦或 404，继续试下一个
            errors.append(f"{url}: {e}")

    if not urls:
        try:
            hit = gutendex_search(book["title"], book.get("author"))
        except Exception as e:
            hit = None
            errors.append(f"gutendex: {e}")
        if hit:
            for url in gutenberg_urls(hit["id"]):
                try:
                    return download(url, cache_dir), f"Project Gutenberg #{hit['id']}"
                except Exception as e:
                    errors.append(f"{url}: {e}")

    raise BookNotFound(
        f"《{book['title']}》没有找到合法全文。请在 books.yaml 里给它加 file:（自己的电子书）"
        f"或 url:/gutenberg_id:（公版书）。\n  " + "\n  ".join(errors)
    )


def lookup_metadata(title: str, author: str | None) -> dict:
    """Open Library 查作者、首版年份、封面。拿不到就返回空，不影响主流程。"""
    try:
        params = {"title": title, "limit": 1, "fields": "title,author_name,first_publish_year,cover_i"}
        if author:
            params["author"] = author
        docs = json.loads(_get("https://openlibrary.org/search.json?" + urllib.parse.urlencode(params), 10)).get("docs", [])
        if not docs:
            return {}
        d = docs[0]
        meta = {"author": (d.get("author_name") or [None])[0], "year": d.get("first_publish_year")}
        if d.get("cover_i"):
            meta["cover_url"] = f"https://covers.openlibrary.org/b/id/{d['cover_i']}-L.jpg"
        return {k: v for k, v in meta.items() if v}
    except Exception:
        return {}
