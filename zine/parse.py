"""第 3 步前半：把一本书拆成章节。

统一输出：
  {"title", "author", "chapters": [{"title", "blocks": [{"type": "p"|"quote"|"li"|"box"|"verse"|"h"|"img", "text"}], "words", "kind"}]}
block type：p 正文段、quote 引文（楷体）、li 条目、box 方框栏目里的一段、verse 诗行、h 小标题（带 level）、img 插图
kind = "main" | "front" | "back"，挑选时只看 main（front 只在没有 main 时兜底）。
"""
from __future__ import annotations

import difflib
import html
import json
import posixpath
import re
from pathlib import Path

BACK = re.compile(r"\b(acknowledge?ments?|about the author|dedication|copyright|title page|notes?|glossary|index|appendix|appendices|bibliography|footnotes|license|contents|transcriber)\b", re.I)
FRONT = re.compile(r"\b(preface|introduction|foreword|prologue|editor'?s note|translator)\b", re.I)
BACK_ZH = re.compile(r"版权|致谢|后记|附录|目录|索引|注释|参考文献|范例|书封|盗书者")
FRONT_ZH = re.compile(r"序|前言|引言|导论|赞誉|推荐|作者简介|译者")
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


# 竖排标点（台版电子书常见）换回横排
VERTICAL = str.maketrans("﹁﹂﹃﹄︽︾︿﹀︵︶︱︹︺︻︼", "「」『』《》〈〉（）|〔〕【】")


def count_words(text: str) -> int:
    """英文按词数；中文按"两个汉字约等于一个英文词"折算，读起来的时间大致相当。"""
    return len(CJK.sub(" ", text).split()) + len(CJK.findall(text)) // 2


MOJIBAKE = {"A\u2020": "Æ", "A(R)": "î"}


def kind_of(title: str) -> str:
    if BACK.search(title) or BACK_ZH.search(title):
        return "back"
    if FRONT.search(title) or FRONT_ZH.search(title):
        return "front"
    return "main"


def inline(text: str) -> str:
    """纯文本里的 _斜体_ / =粗体= 转成 HTML，其余转义。"""
    t = text.replace("--", "\u2014")
    t = re.sub(r'(^|[\s(\[\u2014])"', "\\1\u201c", t).replace('"', "\u201d")
    t = re.sub(r"(^|[\s(\[\u2014])'", "\\1\u2018", t).replace("'", "\u2019")
    t = html.escape(t, quote=False)
    t = re.sub(r"_([^_\n]+?)_", r"<em>\1</em>", t)
    t = re.sub(r"=([^=\n]+?)=", r"<strong>\1</strong>", t)
    return t


def _norm(s: str) -> str:
    s = re.sub(r"^\s*((chapter|book|part)\s+)?([ivxlcdm]+|\d+)[.:)\s]+", "", s.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9一-鿿]+", " ", s.lower()).strip()


_CJK_GAP = re.compile(r"(?<=[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef])\s+(?=[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef])")
_ZH_HEADING = re.compile(r"^[\u3400-\u9fff\uf900-\ufaff]{2,12}$|^[A-Z][A-Z0-9 ,&'’:-]{2,60}$")   # 几个汉字无标点，或整行英文大写

# 段落的角色：出版社电子书各有各的 class 名，这里按常见命名猜。猜不出就是普通段落。
_QUOTE_CLS = re.compile(r"blockquote|quote|kaiti|fangsong|fei2|yinwen|cite|epigraph|indent-3em", re.I)   # 引文（纸书通常换楷体/仿宋）
_LIST_CLS = re.compile(r"\bbli\b|fei3|\blist|\bli\b|\bitem", re.I)                                      # 条目
_BOX_CLS = re.compile(r"\bbox|focus|xiaoshiyan|choice|lanmu|sidebar|column", re.I)                           # 方框栏目
_HEAD_CLS = re.compile(r"heading|title|biaoti", re.I)                                                        # 小标题
_SUBHEAD_CLS = re.compile(r"indent-6em", re.I)                                                                # 更低一级的小标题
_HEAD_SPAN = re.compile(r"\bLR\b|gfont|\bsans|\bhei|bold|strong", re.I)                                      # 整段套在黑体/横排 span 里的短句也是小标题
_LIST_ANC = re.compile(r"indent-[12]em|\blist", re.I)                                                        # 整块缩进的条目
_BULLET = re.compile(r"^\s*[·•■●◆▪◎○※]\s*")
_NUMBERED = re.compile(r"^\s*(?:[❶-❿①-⑩⑴-⑽]|\d{1,2}[．.、]|[（(]\d{1,2}[）)])\s*")


def _role(tag, text: str) -> str:
    """p / quote / li / box / h / h5"""
    cls = " ".join(tag.get("class", []))
    anc = " ".join(" ".join(a.get("class", [])) for a in tag.find_parents(["div", "section", "aside", "ul", "ol"]))
    if _BOX_CLS.search(cls) or _BOX_CLS.search(anc):
        return "box"
    if tag.name != "li" and len(text) <= 40:
        if _SUBHEAD_CLS.search(cls):
            return "h5"
        if _HEAD_CLS.search(cls):
            return "h"
        span = tag.find("span", class_=_HEAD_SPAN) if tag.name == "p" else None
        if span is not None and span.get_text(" ", strip=True) == text and not re.search(r"[。；]", text):
            return "h"
    quoteish = tag.name == "blockquote" or tag.find_parent("blockquote") is not None or _QUOTE_CLS.search(cls)
    if tag.name == "li" or tag.find_parent(["li", "ul", "ol"]) is not None or _LIST_CLS.search(cls) or _LIST_ANC.search(anc) \
            or _BULLET.match(text) or (quoteish and _NUMBERED.match(text)):
        return "li"
    return "quote" if quoteish else "p"


def _tidy_cjk(ch: dict) -> None:
    """电子书里 <span>/<em> 拼接留下的空格（"最大化者 （maximiser）"）去掉；
    只有几个汉字、没有任何标点的独立段落，当作小标题（中文电子书常用 <p class="..."> 做小标题）。"""
    for b in ch["blocks"]:
        if b["type"] == "img":
            continue
        if b["type"] != "verse":
            b["text"] = _CJK_GAP.sub("", re.sub(r"\s*\[\d{1,3}\]", "", b["text"]))   # 去掉 [1] 这类脚注标记
        if b["type"] == "p" and _ZH_HEADING.match(b["text"].strip()):
            b["type"], b["level"] = "h", 5


def _finish(chapters: list[dict]) -> list[dict]:
    out = []
    for ch in chapters:
        _tidy_cjk(ch)
        ch["words"] = sum(count_words(b["text"]) for b in ch["blocks"] if b["type"] not in ("h", "img"))
        ch.setdefault("kind", kind_of(ch["title"]))
        if ch["words"] >= 150:
            out.append(ch)
    for i, ch in enumerate(out):
        ch["index"] = i
    return out


# ---------------------------------------------------------------- 纯文本

def strip_gutenberg(text: str) -> tuple[str, dict]:
    meta = {}
    head = text[:5000]
    for key in ("Title", "Author"):
        m = re.search(rf"^{key}:\s*(.+)$", head, re.M)
        if m:
            meta[key.lower()] = m.group(1).strip()
    s = re.search(r"^\*\*\*\s*START OF.*?\*\*\*\s*$", text, re.M | re.I)
    e = re.search(r"^\*\*\*\s*END OF.*$", text, re.M | re.I)
    body = text[s.end() if s else 0 : e.start() if e else len(text)]
    end = re.search(r"^\s*End of (the )?Project Gutenberg", body, re.M | re.I)
    if end:
        body = body[: end.start()]
    return body, meta


def _paragraphs(lines: list[str]) -> list[dict]:
    blocks, cur = [], []

    def flush():
        if not cur:
            return
        raw = [l.rstrip() for l in cur]
        indented = sum(1 for l in raw if re.match(r"\s{4,}\S", l))
        if indented >= max(1, len(raw) * 0.6):
            blocks.append({"type": "verse", "text": "\n".join(l.strip() for l in raw)})
        else:
            blocks.append({"type": "p", "text": re.sub(r"\s+", " ", " ".join(l.strip() for l in raw)).strip()})
        cur.clear()

    for l in lines:
        if l.strip():
            cur.append(l)
        else:
            flush()
    flush()
    return blocks


def _heading_candidates(lines: list[str], start: int) -> list[int]:
    out = []
    for i in range(max(start, 1), len(lines) - 1):
        l = lines[i].strip()
        if 0 < len(l) <= 70 and not lines[i - 1].strip() and not lines[i + 1].strip() and not l.endswith((",", ";")):
            out.append(i)
    return out


def _toc_entries(lines: list[str]) -> tuple[list[str], int]:
    for i, l in enumerate(lines[:1500]):
        if re.fullmatch(r"\s*(table of )?contents\.?\s*", l, re.I):
            entries, blanks, j = [], 0, i + 1
            while j < len(lines) and blanks < 4:
                s = lines[j].strip()
                if not s:
                    blanks += 1
                else:
                    if len(s) > 80:
                        break
                    blanks = 0
                    s = re.sub(r"\s+\d+$", "", s)              # 页码
                    s = re.sub(r"^=|=$", "", s)
                    entries.append(s)
                j += 1
            if len(entries) >= 3:
                return entries, j
    return [], 0


def chapters_from_text(text: str) -> list[dict]:
    lines = text.splitlines()
    entries, toc_end = _toc_entries(lines)
    heads: list[tuple[int, str]] = []
    if entries:
        # 每个目录条目可能在正文里匹配到多处；取"条目顺序与行号同时递增"的最长链，
        # 避免像 NOTES 这种排在目录最前、正文却在书末的条目把后面全吃掉。
        cands = _heading_candidates(lines, toc_end)
        pairs = []
        for ei, entry in enumerate(entries):
            ne = _norm(entry)
            if not ne:
                continue
            for li in cands:
                nl = _norm(lines[li])
                if nl and (nl == ne or (ne in nl and len(nl) - len(ne) < 8)
                           or difflib.SequenceMatcher(None, nl, ne).ratio() > 0.85):
                    pairs.append((ei, li))
        best: list[list[tuple[int, int]]] = []
        for k, (ei, li) in enumerate(pairs):
            prev = [best[j] for j in range(k) if pairs[j][0] < ei and pairs[j][1] < li]
            best.append(max(prev, key=len, default=[]) + [(ei, li)])
        chain = max(best, key=len, default=[])
        heads = [(li, entries[ei]) for ei, li in chain]
    if len(heads) < 3:  # 没有可用目录：用标题行的样子来猜
        pat = re.compile(r"^\s*((CHAPTER|BOOK|PART|LETTER|ESSAY)\b.*|[IVXLC]+\.?\s+[A-Z].*|[A-Z][A-Z0-9 ,.'’:;-]{3,60})\s*$")
        heads = [(i, lines[i].strip()) for i in _heading_candidates(lines, 0) if pat.match(lines[i])]
    if not heads:
        return [{"title": "全文", "blocks": _paragraphs(lines)}]

    chapters = []
    for n, (i, title) in enumerate(heads):
        j = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = lines[i + 1 : j]
        # 去掉紧跟在标题前后的单独罗马数字行
        blocks = _paragraphs(body)
        # 去掉章首残留的罗马数字行和全大写的重复标题行
        while blocks and (re.fullmatch(r"[IVXLC]+\.?", blocks[0]["text"].strip())
                          or blocks[0]["text"].isupper() and len(blocks[0]["text"]) < 80):
            blocks.pop(0)
        while blocks and re.fullmatch(r"[IVXLC]+\.?", blocks[-1]["text"].strip()):
            blocks.pop()
        chapters.append({"title": _titlecase(title), "blocks": blocks})
    return chapters


def _titlecase(s: str) -> str:
    s = re.sub(r"^=|=$", "", s.strip())
    s = re.sub(r"^([IVXLC]+|\d+)\.?\s+(?=\S)", "", s) or s
    if not s.isupper():
        return s
    small = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
    words = s.lower().split()
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(words))


def parse_txt(path: Path) -> dict:
    data = path.read_bytes()
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:  # 老的 Gutenberg 文本常是 Latin-1 / cp1252
        raw = data.decode("cp1252", errors="replace")
    for bad, good in MOJIBAKE.items():  # 旧版 Gutenberg 文本里常见的转码残留
        raw = raw.replace(bad, good)
    raw = raw.replace("\r\n", "\n").replace("﻿", "")
    body, meta = strip_gutenberg(raw)
    return {**meta, "chapters": _finish(chapters_from_text(body))}


# ---------------------------------------------------------------- EPUB

def parse_epub(path: Path) -> dict:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": False})
    meta = {}
    for key, dc in (("title", "title"), ("author", "creator")):
        v = book.get_metadata("DC", dc)
        if v:
            meta[key] = v[0][0]

    # 目录（toc）里一级条目对应的文件，作为章节起点；中文电子书常常不用 h 标签，只能靠目录切
    toc = {}  # 文件名 -> (深度, 标题)；同一个文件只记第一个指向它的条目（通常是章标题，后面的是文件内小节）

    def walk(entries, depth):
        for x in entries:
            node, kids = (x[0], x[1]) if isinstance(x, tuple) else (x, [])
            href = (getattr(node, "href", "") or "").split("#")[0]
            if href:
                toc.setdefault(href, (depth, node.title))
            walk(kids, depth + 1)
    walk(book.toc, 0)

    blocks, toc_blocks = [], []  # (level, type, text)
    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        name = item.get_name()
        if name in toc:
            toc_blocks.append((toc[name][0], "toc", toc[name][1]))
        soup = BeautifulSoup(item.get_content(), "html.parser")
        n_before = len(blocks)
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li", "pre", "img", "image"]):
            if tag.name in ("img", "image"):
                src = tag.get("src") or tag.get("xlink:href") or tag.get("href")
                if src and not src.startswith(("http:", "https:", "data:")):
                    blocks.append((9, "img", posixpath.normpath(posixpath.join(posixpath.dirname(name), src))))
                continue
            if tag.name in ("blockquote", "li") and tag.find(["p", "h1", "h2", "h3", "h4", "li"]):
                continue   # 容器：里面的段落会各自出现
            if tag.find_parent("pre") is not None:
                continue
            text = tag.get_text(" " if tag.name != "pre" else "\n", strip=True).translate(VERTICAL)
            if not text or "Project Gutenberg" in text and len(text) < 300:
                continue
            if tag.name[0] == "h":
                blocks.append((int(tag.name[1]), "h", text))
            elif tag.name in ("pre",) or "poem" in " ".join(tag.get("class", [])) or tag.name == "blockquote" and tag.find("br"):
                blocks.append((9, "verse", tag.get_text("\n", strip=True)))
            else:
                role = _role(tag, text)
                if role == "li":
                    text = _BULLET.sub("", text)   # 圆点由排版加，统一样式
                if role in ("h", "h5"):
                    blocks.append((4 if role == "h" else 5, "h", text))
                else:
                    blocks.append((9, role, text))
        title = toc[name][1] if name in toc else None
        toc_blocks += [b for b in blocks[n_before:] if not (b[1] == "h" and title and _norm(b[2]) == _norm(title))]

    # 选一个能把书切成 3 段以上的标题层级
    level = next((lv for lv in (1, 2, 3) if sum(1 for b in blocks if b[0] == lv) >= 3), None)
    chapters, cur = [], None
    for lv, typ, text in blocks:
        if level and lv <= level:
            cur = {"title": text, "blocks": []}
            chapters.append(cur)
        elif cur is None:
            cur = {"title": meta.get("title", "开篇"), "blocks": []}
            chapters.append(cur)
        else:
            cur["blocks"].append({"type": typ, "text": text, **({"level": lv} if typ == "h" else {})})
    # 也按目录切一遍（逐个深度试），哪种切法让更多正文落在长度合适（2000–20000 词）的章节里就用哪种
    def score(chs):
        return sum(c["words"] for c in _finish([dict(c) for c in chs]) if 2000 <= c["words"] <= 20000 and c["kind"] == "main")

    def by_toc(depth):
        chs, cur = [], None
        for lv, typ, text in toc_blocks:
            if typ == "toc" and lv <= depth:
                cur = {"title": text, "blocks": []}
                chs.append(cur)
            elif cur is not None:
                cur["blocks"].append({"type": "h" if typ == "toc" else typ, "text": text,
                                      **({"level": lv} if typ in ("toc", "h") else {})})
        return chs
    if len(toc) >= 3:
        best = max((by_toc(d) for d in range(max(lv for lv, _ in toc.values()) + 1)), key=score)
        if score(best) > score(chapters):
            chapters = best
    for ch in chapters:  # epub 正文已是纯文本，转义以便安全放进 HTML
        for b in ch["blocks"]:
            b["text"] = b["text"].replace("_", "_")
    return {**meta, "chapters": _finish(chapters)}


def export_images(path: Path, book: dict, out_dir: Path, rel_prefix: str) -> int:
    """把章节里引用的插图从 EPUB 里取出来存到 out_dir，img 块加上 src（相对 issue/books/ 的路径）。
    反复出现的小图（装饰、图标）不要；取不到的 img 块直接删掉。"""
    import collections
    import io

    import ebooklib
    from ebooklib import epub
    from PIL import Image

    bk = epub.read_epub(str(path), options={"ignore_ncx": True})
    items = {i.get_name(): i for i in bk.get_items_of_type(ebooklib.ITEM_IMAGE)}

    def find(href):
        return items.get(href) or next((v for k, v in items.items() if k.endswith(posixpath.basename(href))), None)

    uses = collections.Counter(b["text"] for ch in book["chapters"] for b in ch["blocks"] if b["type"] == "img")
    keep = {}
    for href, n in uses.items():
        it = find(href)
        if not it or n >= 3:
            continue
        data = it.get_content()
        try:
            w, h = Image.open(io.BytesIO(data)).size
        except Exception:
            continue
        if w < 150 or h < 100 or len(data) < 4000:   # 图标、花边
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        fn = posixpath.basename(href)
        (out_dir / fn).write_bytes(data)
        keep[href] = f"{rel_prefix}/{fn}"
    for ch in book["chapters"]:
        ch["blocks"] = [({**b, "src": keep[b["text"]]} if b["type"] == "img" else b)
                        for b in ch["blocks"] if b["type"] != "img" or b["text"] in keep]
    return len(keep)


# ---------------------------------------------------------------- PDF

def parse_pdf(path: Path) -> dict:
    from pypdf import PdfReader

    r = PdfReader(str(path))
    meta = {}
    if r.metadata:
        if r.metadata.title:
            meta["title"] = r.metadata.title
        if r.metadata.author:
            meta["author"] = r.metadata.author
    pages = [p.extract_text() or "" for p in r.pages]

    # 有书签就按书签切
    try:
        top = [o for o in r.outline if not isinstance(o, list)]
        marks = [(r.get_destination_page_number(o), o.title) for o in top]
    except Exception:
        marks = []
    marks = sorted({m for m in marks if m[0] is not None})
    if len(marks) >= 3:
        chapters = []
        for n, (pg, title) in enumerate(marks):
            end = marks[n + 1][0] if n + 1 < len(marks) else len(pages)
            text = "\n".join(pages[pg:end])
            chapters.append({"title": title, "blocks": _paragraphs(text.splitlines())})
        return {**meta, "chapters": _finish(chapters)}
    return {**meta, "chapters": _finish(chapters_from_text("\n".join(pages)))}


# ---------------------------------------------------------------- Markdown / HTML / JSON（MCP 返回的内容）

def _split_by_headings(blocks: list[tuple[int, str, str]], meta: dict) -> dict:
    level = next((lv for lv in (1, 2, 3, 4) if sum(1 for b in blocks if b[0] == lv) >= 3), None)
    chapters, cur = [], None
    for lv, typ, text in blocks:
        if level and lv <= level:
            cur = {"title": text, "blocks": []}
            chapters.append(cur)
        else:
            if cur is None:
                cur = {"title": meta.get("title", "开篇"), "blocks": []}
                chapters.append(cur)
            cur["blocks"].append({"type": typ, "text": text})
    return {**meta, "chapters": _finish(chapters)}


def parse_markdown(text: str, meta: dict | None = None) -> dict:
    blocks, para = [], []

    def flush():
        if para:
            blocks.append((9, "p", re.sub(r"\s+", " ", " ".join(para)).strip()))
            para.clear()

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        if m:
            flush()
            blocks.append((len(m.group(1)), "h", m.group(2).strip()))
        elif not line.strip():
            flush()
        else:
            para.append(re.sub(r"\*\*|__", "", line.strip()))
    flush()
    if sum(1 for b in blocks if b[1] == "h") < 3:  # 没有 Markdown 标题：当纯文本处理
        return {**(meta or {}), "chapters": _finish(chapters_from_text(text))}
    return _split_by_headings(blocks, meta or {})


def parse_html(raw: str, meta: dict | None = None) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    blocks = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote"]):
        text = tag.get_text(" ", strip=True)
        if text:
            blocks.append((int(tag.name[1]), "h", text) if tag.name[0] == "h" else (9, "p", text))
    return _split_by_headings(blocks, meta or {})


def parse_json(raw: str) -> dict:
    """MCP 常见的结构化返回：{"title", "author", "chapters": [{"title", "content"}]}，字段名宽松匹配。"""
    data = json.loads(raw)
    if isinstance(data, list):
        data = {"chapters": data}
    meta = {k: data[k] for k in ("title", "author") if isinstance(data.get(k), str)}
    chs = data.get("chapters") or data.get("toc") or data.get("sections")
    if isinstance(chs, list) and chs and isinstance(chs[0], dict):
        chapters = []
        for c in chs:
            body = c.get("content") or c.get("text") or c.get("body") or ""
            title = c.get("title") or c.get("name") or f"第 {len(chapters) + 1} 章"
            inner = parse_markdown(body) if "<" not in body[:200] else parse_html(body)
            blocks = [b for ch in inner["chapters"] for b in ch["blocks"]] or _paragraphs(body.splitlines())
            chapters.append({"title": title, "blocks": blocks})
        return {**meta, "chapters": _finish(chapters)}
    body = data.get("content") or data.get("text") or ""
    return parse_markdown(body, meta)


def parse(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext in (".md", ".markdown"):
        return parse_markdown(path.read_text(encoding="utf-8"))
    if ext in (".html", ".htm"):
        return parse_html(path.read_text(encoding="utf-8", errors="replace"))
    if ext == ".json":
        return parse_json(path.read_text(encoding="utf-8"))
    if ext == ".epub":
        return parse_epub(path)
    if ext == ".pdf":
        return parse_pdf(path)
    return parse_txt(path)


# ---------------------------------------------------------------- 封面、繁简

def extract_cover(path: Path) -> tuple[bytes, str] | None:
    """从 EPUB 里找封面图：先看标成 cover 的项，再看 <meta name=cover>，再看名字带 cover 的图，
    再看第一个文档里的第一张图，最后退回第一张图。返回 (图片字节, 扩展名)。"""
    if path.suffix.lower() != ".epub":
        return None
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    items = list(book.get_items())
    cand = [i for i in items if i.get_type() == ebooklib.ITEM_COVER]
    if not cand:
        ids = {m[1].get("content") for m in book.get_metadata("OPF", "cover") if isinstance(m[1], dict)}
        cand = [i for i in items if i.get_id() in ids]
    if not cand:
        cand = [i for i in items if i.get_type() == ebooklib.ITEM_IMAGE and "cover" in (i.get_name() + i.get_id()).lower()]
    if not cand:
        for idref, _ in book.spine[:3]:
            it = book.get_item_with_id(idref)
            if not it or it.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            img = BeautifulSoup(it.get_content(), "html.parser").find(["img", "image"])
            src = img and (img.get("src") or img.get("xlink:href") or img.get("href"))
            if src:
                hit = book.get_item_with_href(posixpath.normpath(posixpath.join(posixpath.dirname(it.get_name()), src)))
                if hit:
                    cand = [hit]
                    break
    if not cand:
        cand = [i for i in items if i.get_type() == ebooklib.ITEM_IMAGE][:1]
    if not cand:
        return None
    return cand[0].get_content(), (Path(cand[0].get_name()).suffix.lower() or ".jpg")


def maybe_simplify(book: dict) -> bool:
    """繁体中文的书转成简体（只转字，不改词：台版译法原样保留）。改动了返回 True。"""
    try:
        from opencc import OpenCC
    except ImportError:
        return False
    cc = OpenCC("t2s")
    sample = " ".join(b["text"] for ch in book["chapters"][:4] for b in ch["blocks"])[:4000]
    if not sample or sum(a != b for a, b in zip(sample, cc.convert(sample))) < len(sample) * 0.03:
        return False
    for ch in book["chapters"]:
        ch["title"] = cc.convert(ch["title"])
        for b in ch["blocks"]:
            b["text"] = cc.convert(b["text"])
    for k in ("title", "author"):
        if book.get(k):
            book[k] = cc.convert(book[k])
    book["simplified_from"] = "繁体"
    return True
