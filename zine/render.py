"""第 4 步：拼装成杂志 PDF（A5，骑马钉友好：总页数补成 4 的倍数）。

版式是中文优先的：正文宋体、首行缩进两字、小标题黑体。英文选篇必须先经过 translate 这一步。
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import translate
from .parse import CJK, inline, normalize_zh

ROOT = Path(__file__).resolve().parent.parent


_LATIN_PAREN = re.compile(r"（([^）]*[A-Za-z][^）]*)）")


_CJK_LAT = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?=[\u3400-\u4dbf\u4e00-\u9fff])")


def _spacing(html: str) -> str:
    """中西文间距：汉字和字母、数字之间留 1/4 字宽（clreq 3.2.2）。WeasyPrint 不支持 text-autospace，用定宽空盒子代替。"""
    return _CJK_LAT.sub('<span class="g"></span>', html)


def _no_stretch(html: str) -> str:
    """中文段落两端对齐时，括号里英文名的空格会被拉得很开（WeasyPrint 连 nbsp 也会拉）；换成定宽的空盒子就不会。"""
    return _LATIN_PAREN.sub(lambda m: "（" + m.group(1).replace(" ", '<span class="sp"></span>') + "）", html)


_CAPTION = re.compile(r"^(图|圖|Figure|Fig\.?)\s*[\d一二三四五六七八九十]")
_ATTRIB = re.compile(r"^[\u2014\u2500\-]{1,2}\s*")


def _norm_title(t: str) -> str:
    return re.sub(r"[\s\d０-９一二三四五六七八九十第章节.．、:：|]+", "", t)


_NUM_ITEM = re.compile(r"^\s*(?:[❶-❿①-⑩⑴-⑽]|\d{1,2}[．.、]|[（(]\d{1,2}[）)])")
_LATIN_ONLY = re.compile(r"^[A-Za-z0-9 ,.&'’:!-]+$")


def _shape(blocks: list[dict], chapter_title: str) -> list[dict]:
    """给段落定角色：开头重复的章名去掉；章首的短段当题记（后面紧跟的"——某某"或几个字的署名是出处）；
    img 块配上前后的"图 x-x"说明文字；连续的条目并成一个 list；连续的方框段（夹着的插图一起）并成一个 box。"""
    out = [dict(b) for b in blocks]
    if out and out[0]["type"] in ("p", "quote") and _norm_title(out[0]["text"]) == _norm_title(chapter_title):
        out.pop(0)
    if out and out[0]["type"] in ("p", "quote") and len(out[0]["text"]) <= 90:
        out[0]["type"] = "epi"
        if len(out) > 1 and out[1]["type"] in ("p", "quote") and (_ATTRIB.match(out[1]["text"]) or len(out[1]["text"]) <= 12):
            out[1] = {"type": "epi-by", "text": _ATTRIB.sub("", out[1]["text"])}
    shaped, i = [], 0
    while i < len(out):
        b = out[i]
        if b["type"] in ("p", "box") and _CAPTION.match(b["text"]) and i + 1 < len(out) and out[i + 1]["type"] == "img":
            shaped.append({**out[i + 1], "caption": b["text"]}); i += 2; continue
        if b["type"] == "img" and i + 1 < len(out) and out[i + 1]["type"] in ("p", "box") and _CAPTION.match(out[i + 1]["text"]):
            shaped.append({**b, "caption": out[i + 1]["text"]}); i += 2; continue
        shaped.append(b); i += 1
    grouped, i = [], 0
    while i < len(shaped):
        b = shaped[i]
        if b["type"] == "li":
            j = i
            while j < len(shaped) and shaped[j]["type"] == "li":
                j += 1
            grouped.append({"type": "list", "items": shaped[i:j]}); i = j; continue
        if b["type"] == "box":
            j = i
            while j < len(shaped) and shaped[j]["type"] in ("box", "img"):
                j += 1
            while j - 1 > i and shaped[j - 1]["type"] == "img" and j - 2 > i and shaped[j - 2]["type"] == "img":
                j -= 1   # 方框后面连着的多张图不算方框的
            items = shaped[i:j]
            # 框标题：开头的短句；英文大写的标题行（"MY RECIPE"）后面若跟着中文标题就只留中文
            if len(items) > 1 and items[0]["type"] == "box" and _LATIN_ONLY.match(items[0]["text"]) and items[1]["type"] == "box" and len(items[1]["text"]) <= 16:
                items = items[1:]
            title = None
            if items and items[0]["type"] == "box" and len(items[0]["text"]) <= 16 and not re.search(r"[。！？；]", items[0]["text"]):
                title, items = items[0]["text"], items[1:]
            grouped.append({"type": "box", "title": title, "items": items}); i = j; continue
        grouped.append(b); i += 1
    return grouped


INK = "#1E1D1A"
PAPER = "#F3EEE2"      # cover.json 没写 paper 时的封面底色


def cn_date(date: str) -> tuple[str, str]:
    """"2026-10-13" → ("二〇二六年", "十月")"""
    digits = "〇一二三四五六七八九"
    y, m = date.split("-")[:2]
    m = int(m)
    month = ("十" if m >= 10 else "") + (digits[m % 10] if m % 10 else "")
    return "".join(digits[int(c)] for c in y) + "年", month + "月"


SHADOW_PAD_MM = 4.8   # 阴影图四周留的边（显示时用负 margin 抵掉，封面本身的大小不变）


def _squeeze(html: str) -> str:
    """标点挤压：收尾的标点后面紧跟另一个标点时（「挺好的」。），前一个只占半个字宽。扉页的两段话用，和设计稿的折行一致。"""
    return re.sub(r"([」』）》，。、；：！？])(?=[「『（《」』）》，。、；：！？])", r'<span style="margin-right: -.5em">\1</span>', html)


def shadowed(src: Path, paper: str = "#FFFFFF") -> Path:
    """给书影加一圈柔和的阴影，直接画进图片里（PDF 里就是一张普通位图，打印一定出得来）。
    输出高 820px = 封面 700px + 上下各 60px 边；按 12.5px/mm 显示（高 65.6mm，封面本身 56mm）。"""
    from PIL import Image, ImageDraw, ImageFilter

    tag = "" if paper.upper() == "#FFFFFF" else "-" + paper.lstrip("#").lower()   # 扉页色块上的书影，底色跟着色块走
    out = src.with_name(src.name.rsplit(".", 1)[0] + f".shadow{tag}.png")
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    im = Image.open(src).convert("RGB")
    im = im.resize((max(1, round(im.width * 700 / im.height)), 700), Image.LANCZOS)
    pad = 60
    W, H = im.width + 2 * pad, im.height + 2 * pad
    canvas = Image.new("RGB", (W, H), paper)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rectangle([pad + 8, pad + 14, pad + 8 + im.width, pad + 14 + im.height], fill=80)
    mask = mask.filter(ImageFilter.GaussianBlur(13))
    canvas.paste(Image.new("RGB", (W, H), "#000000"), mask=mask)
    canvas.paste(im, (pad, pad))
    ImageDraw.Draw(canvas).rectangle([pad, pad, pad + im.width - 1, pad + im.height - 1], outline="#CFC9BE", width=1)
    canvas.save(out)
    return out


def _tidy_heading(text: str) -> str:
    """小标题里的 "1.1 | 可能性空间" 去掉竖线；"问题一赢家…" 这种序号和标题之间补一个全角空格。"""
    t = re.sub(r"\s*\|\s*", "\u3000", text.strip())
    t = re.sub(r"^((?:问题|步骤|原则|方法|策略|秘诀|第)\s*[一二三四五六七八九十\d]+[章节条步]?)(?=[^\s\u3000，。：:、])", "\\1\u3000", t)
    return re.sub(r"^(\d+(?:\.\d+)*)(?=[\u3400-\u9fff])", "\\1\u3000", t)


def _tidy_num(text: str) -> str:
    """条目开头的 "1." / "1、" 统一成全角 "1．"，❶ 这类保留。"""
    return re.sub(r"^\s*(\d{1,2})[．.、]\s*", r"\1．", text)


def _walk(html_blocks: list[dict]):
    """所有带 html 的叶子（list / box 里的也算）。"""
    for hb in html_blocks:
        if hb["type"] in ("list", "box"):
            yield from _walk(hb["items"])
        elif "html" in hb:
            yield hb


def _footnotes(html_blocks: list[dict], notes: list[dict]) -> None:
    """脚注：在正文第一次出现 term 的地方，紧跟着插一个 float: footnote 的 span。"""
    for n in notes or []:
        term, note = inline(n["term"]), _spacing(_no_stretch(inline(n["note"])))   # 注文里的西文词间空格也不拉伸
        for hb in _walk(html_blocks):
            if term not in hb["html"]:
                continue
            hb["html"] = hb["html"].replace(term, f'{term}<span class="fn">{note}</span>', 1)
            break


_CN_NUM = {c: i for i, c in enumerate("〇一二三四五六七八九")}


def _cn2int(s: str) -> int:
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, b = s.split("十", 1)
        return (_CN_NUM[a] if a else 1) * 10 + (_CN_NUM[b] if b else 0)
    return _CN_NUM[s]


def _chapter_label(title: str) -> str:
    """扉页「本期选读」的章节标签统一成「第 N 章　章名」（rules/typesetting；check ⑬）：
    "05 xxx" / "第五章xxx" / "第4章 xxx" / "Chapter 4: xxx" 都归到一个体例；认不出章号的原样保留。"""
    t = re.sub(r"[\u3000\u2003\s]+", " ", title).strip()
    m = (re.match(r"^第\s*([〇一二三四五六七八九十]+|\d{1,3})\s*[章讲回篇]\s*[、．.:：|｜]?\s*(.*)$", t)
         or re.match(r"^(?:chapter|ch\.?)\s*(\d{1,3})\s*[.:：]?\s*(.*)$", t, re.I)
         or re.match(r"^0*(\d{1,3})\s*[、．.:：|｜]\s*(.*)$|^0*(\d{1,3})\s+(.*)$", t))
    if not m:
        return t
    g = [x for x in m.groups() if x is not None]
    try:
        n = _cn2int(g[0])
    except KeyError:
        return t
    rest = g[1].strip() if len(g) > 1 else ""
    return f"第 {n} 章" + (f"\u3000{rest}" if rest else "")


def prepared_image(src: Path) -> tuple[Path, int, int]:
    """插图进版前的两件事（rules/typesetting：内页白底、位图 ≥ 150ppi）：
    1. 灰底扫描图（四边中位亮度 < 245、近乎无彩）按边缘亮度拉到纸白，存成 *.white.png；彩图和白底图不动。
    2. 返回原图像素，排版时按 150ppi 限制置入宽度。"""
    from PIL import Image
    im = Image.open(src)
    w, h = im.size
    rgb = im.convert("RGB")
    bw, bh = max(1, w * 3 // 100), max(1, h * 3 // 100)
    px = [q for part in (rgb.crop((0, 0, w, bh)), rgb.crop((0, h - bh, w, h)), rgb.crop((0, 0, bw, h)), rgb.crop((w - bw, 0, w, h)))
          for q in part.getdata()]
    lum = sorted(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px)
    med = lum[len(lum) // 2]
    chroma = max(abs(r - g) + abs(g - b) for r, g, b in px[:: max(1, len(px) // 3000)])
    if med >= 245 or chroma > 40:                       # 白底不动；彩图不动
        return src, w, h
    # 灰底是哪一级灰：取四边亮度的 25 分位（灰色面板至少占四边的 1/4）；它低于 150 说明是黑框或反白图，不碰
    white = lum[len(lum) // 4]
    if white < 150:
        white = med
    if white < 150:
        return src, w, h
    out = src.with_name(src.name.rsplit(".", 1)[0] + ".white.png")
    if not (out.exists() and out.stat().st_mtime >= src.stat().st_mtime):
        lut = [min(255, round(v * 255 / white)) for v in range(256)]   # 灰底拉到纸白，线条按比例提亮
        rgb.convert("L").point(lut).save(out)
    return out, w, h


def _piece_view(piece: dict, book: dict, zh: dict | None, issue_dir: Path) -> dict:
    ch, blocks, _, _ = translate.selected(piece, book)
    title = ch["title"]
    if zh:
        # 译文按段对应，type 以原文为准（原文解析可能后来把某段识别成了小标题）
        blocks = [{**o, "text": normalize_zh(z["text"])} for o, z in zip(blocks, zh["blocks"])]
        title = normalize_zh(zh.get("title") or title)
    piece = {**piece, "context": normalize_zh(piece.get("context") or ""), "intro": normalize_zh(piece.get("intro") or ""),
             "notes": [{**n, "note": normalize_zh(n["note"])} for n in piece.get("notes") or []]}
    chars = sum(len(CJK.findall(b["text"])) for b in blocks)
    top = min((b.get("level", 5) for b in blocks if b["type"] == "h"), default=5)   # 本篇最高一级小标题

    def view(b: dict) -> dict:
        if b["type"] == "verse":
            return {"type": "verse", "html": "<br>".join(inline(l) for l in b["text"].split("\n"))}
        if b["type"] == "img":
            path = prepared_image(issue_dir / "books" / b["src"])[0]      # 灰底扫描图先拉到纸白
            # 图宽按像素数定：最多放大到 170 ppi，再大就糊了；小图不撑满版心，也少把半页正文挤到下一页
            try:
                from PIL import Image
                with Image.open(path) as im:
                    w_mm = min(116.0, im.width / 170 * 25.4)
            except Exception:
                w_mm = 116.0
            return {"type": "img", "src": path.resolve().as_uri(), "w": round(w_mm, 1),
                    "caption": _spacing(inline(b["caption"])) if b.get("caption") else ""}
        if b["type"] == "list":
            return {"type": "list", "items": [{"type": "li", "num": bool(_NUM_ITEM.match(it["text"])),
                                               "html": _spacing(_no_stretch(inline(_tidy_num(it["text"]))))} for it in b["items"]]}
        if b["type"] == "box":
            items = []
            for it in b["items"]:
                if it["type"] == "img":
                    items.append(view(it))
                elif _NUM_ITEM.match(it["text"]):
                    items.append({"type": "li", "num": True, "html": _spacing(_no_stretch(inline(_tidy_num(it["text"]))))})
                elif len(it["text"]) <= 16 and not re.search(r"[。！？；，]", it["text"]):
                    items.append({"type": "h", "html": _spacing(inline(it["text"]))})
                else:
                    items.append({"type": "p", "html": _spacing(_no_stretch(inline(it["text"])))})
            return {"type": "box", "title": _spacing(inline(b["title"])) if b.get("title") else "", "items": items}
        if b["type"] == "h":
            return {"type": "h", "sub": b.get("level", 5) > top, "html": _spacing(inline(_tidy_heading(b["text"])))}
        return {"type": b["type"], "html": _spacing(_no_stretch(inline(b["text"])))}

    html_blocks = [view(b) for b in _shape(blocks, ch["title"])]
    _footnotes(html_blocks, piece.get("notes"))
    excerpted = bool(piece.get("excerpt"))
    # 「本期选读」下面那行章节名：默认用原书的章名；太长的在 selection.json 这一篇里写 label 换成短的
    # 没给 label 时把各种写法（"05 xxx"、"Chapter 4: xxx"、"第五章xxx"）归成「第 N 章　章名」；给了 label 就照 label
    chapter_label = (piece.get("label") or _chapter_label(title if zh else ch["title"])).replace("\u3000", " ").replace("\u2003", " ")
    chapter_label = re.sub(r"^0*(\d{1,2})\s+", lambda m: f"第 {m.group(1)} 章 ", chapter_label)   # "05 xxx" → "第 5 章 xxx"
    chapter_label = re.sub(r"^第\s*(\d{1,2})\s*章\s*", lambda m: f"第 {m.group(1)} 章 ", chapter_label)   # "第4章xxx" → "第 4 章 xxx"
    chapter_label = re.sub(r"^(第\s*[\d一二三四五六七八九十]+\s*[章篇部分]+)[：:]\s*", r"\1 ", chapter_label)   # 「第一章： 妈妈测试」→「第一章 妈妈测试」
    # 「第一章 妈妈测试」「第 9 章 迈向公司科学」：章号和章名之间用一个全角空格
    chapter_label = re.sub(r"^(第\s*[\d一二三四五六七八九十]+\s*(?:章|篇|部分))\s+", "\\1\u3000", chapter_label)
    if excerpted:
        chapter_label += "（节选）"
    book_title = book.get("display_title") or book.get("title")
    # 扉页上的大书名：长书名在"与/和"之后换行，再长就缩小字号，免得在不该断的地方断
    title_html, title_pt = inline(book_title), 22
    if len(book_title) > 7 and (m := re.search(r"[与和及：]", book_title)) and 2 <= m.end() <= len(book_title) - 2:
        title_html = inline(book_title[: m.end()]) + "<br>" + inline(book_title[m.end():])
    else:
        title_pt = max(14, min(22, int(59 / (len(book_title) + 2) / 0.3528)))   # 书名栏宽 60mm，连书名号排成一行
    return {
        **piece,
        "book_title": book_title,
        "title_html": title_html,
        "title_pt": title_pt,
        "original_title": book.get("original_title"),
        "author": book.get("author", ""),
        "year": book.get("year"),
        "source": book.get("source", ""),
        "chapter_title": piece.get("title") or title,
        # 篇名带冒号的拆成主、副两行（扉页和正文首页都这样排）；目录和页眉仍用整条
        "title_main": re.split(r"[：:]", piece.get("title") or title, maxsplit=1)[0],
        "title_sub": (re.split(r"[：:]", piece.get("title") or title, maxsplit=1) + [""])[1].strip(),
        "original_chapter": ch["title"],
        "chapter_label": chapter_label,
        "translator": book.get("translator"),
        "context_html": _squeeze(_spacing(inline(piece.get("context") or ""))),
        "intro_html": _squeeze(_spacing(inline(piece.get("intro") or ""))),
        "cover_path": (issue_dir / "books" / book["cover"]).resolve() if book.get("cover") else None,
        "cover_url": shadowed((issue_dir / "books" / book["cover"]).resolve()).as_uri() if book.get("cover") else None,
        "excerpted": excerpted,
        "translated": bool(zh),
        "chars": chars,
        "blocks": html_blocks,
    }


def _lum(c: str) -> float:
    r, g, b = (int(c.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _label_color(c: str) -> str:
    """「本期选读」四个字的颜色：这一篇的地层色压暗；本来就深的层直接用墨色"""
    import colorsys
    if _lum(c) < 0.25:
        return "#1E2A30"
    r, g, b = (int(c.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, 0.33, min(1.0, max(sat, 0.4)))
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


# 扉页色块的波浪边（divider_edge: wave 时用）：「底下」那一期设计稿里的三条曲线（坐标是 420×595.5 的画布），七篇按 1、2、3 轮着用，
# 最后一篇和第 3 篇同一条。照原稿逐点抄的，不要改成随机生成。
_WAVES = [
    "M 0 19.5 C 90.75 7.5 180.75 25.5 263.25 15 C 345.75 4.5 375.75 6 420 18 L 420 294 C 353.25 310.5 270.75 288 188.25 298.5 C 105.75 309 68.25 313.5 0 295.5 L 0 19.5 Z",
    "M 0 16.5 C 98.25 27 180.75 6 263.25 16.5 C 345.75 27 368.25 28.5 420 13.5 L 420 295.5 C 345.75 285 263.25 309 180.75 297 C 98.25 285 75.75 288 0 301.5 L 0 16.5 Z",
    "M 0 18 C 90.75 28.5 188.25 9 270.75 16.5 C 353.25 24 375.75 28.5 420 15 L 420 292.5 C 353.25 309 263.25 289.5 180.75 300 C 98.25 310.5 68.25 310.5 0 297 L 0 18 Z"
]


_STRAIGHT = "M 0 17 L 420 17 L 420 297 L 0 297 Z"


def _divider_art(k: int, color: str, prev: str, edge: str = "straight") -> str:
    """扉页上半的色块：页顶露一条上一篇的颜色。色块的边默认是直的；cover.json 里 divider_edge 写 wave 时
    上下两条边是波浪线（「底下」那一期的地层，见 examples/cover-strata/）。"""
    d = _WAVES[2 if k == 6 else k % 3] if edge == "wave" else _STRAIGHT
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 595.5" preserveAspectRatio="none" width="148mm" height="210mm">'
            f'<rect x="0" y="0" width="420" height="45" fill="{prev}"/><path d="{d}" fill="{color}"/></svg>')


def _toc_layout(lengths: list[int], top: float = 36.0, total: float = 153.7, least: float = 14.5) -> list[dict]:
    """目录左边那条色带：一篇一段，段高严格按这一篇的页数分（和 Claude Design 原稿一致），条目对着各段的上沿。
    只有当某一篇短到放不下两行字（< least）时，才给每段垫一个底再按页数分剩下的。"""
    n, pages = len(lengths), sum(lengths) or 1
    base = 0.0
    if min(lengths) * total / pages < least:
        base = (least * pages - total * min(lengths)) / (pages - n * min(lengths)) if pages > n * min(lengths) else total / n
    spare = total - n * base
    out, y = [], top
    for L in lengths:
        h = base + spare * L / pages
        out.append({"top": round(y, 2), "h": round(h, 2)})
        y += h
    return out


PX_MM = 25.4 / 96          # WeasyPrint 内部用 CSS px
BODY_TOP, BODY_BOT = 20.0, 192.0   # 版心上下沿（mm），和模板的 @page margin 一致
# 注码和注文不在同一页时，对那一段依次试的办法（哪个管用因页而异，试到管用为止）
NUDGES = ['style="orphans: 1; widows: 1"', 'class="fnline"', 'class="fnline" style="orphans: 1; widows: 1"',
          'style="margin-top: 6.5mm"', 'style="margin-top: 13mm"', 'style="break-before: page"']
PGAPS = [0.8, 0.6, 0.9, 0.5, 0.75, 0.65, 1.0, 0.85, 0.55, 0.45, 1.2]  # 依次试的段间距（em），默认 0.7


def _apply_fix(pieces: list[dict], op: list) -> None:
    kind, k = op[0], op[1]
    bl = pieces[k]["blocks"]
    if kind == "swap0":           # 同 swap，另把换上来的那一块的脚注微调清掉
        bl[op[2] + 1].pop("nudge", None)
        kind = "swap"
    if kind == "swap":            # 图和它后面那一块换位
        i = op[2]
        bl[i], bl[i + 1] = bl[i + 1], bl[i]
    elif kind == "pull":          # 把一串图后面的那一段提到这串图前面
        bl.insert(op[2], bl.pop(op[3]))
    elif kind == "scale":         # 图缩小
        b = bl[op[2]]
        b["w"] = round(b["w"] * op[3], 1)
        b["cum"] = b.get("cum", 1.0) * op[3]
    elif kind == "pgap":
        pieces[k]["pgap"] = op[2]
    elif kind == "nudge":         # 带脚注的那一段往下让一两行，或者干脆另起一页（见 _layout_fixes）
        bl[op[2]]["nudge"] = op[3]


def _page_metrics(doc):
    """每页正文排到多低（mm，不算脚注和页眉）；每张带 id 的插图在哪一页、多高、离页顶多远；
    哪些段落的注码和注文不在同一页（返回这些段落的 id）"""
    from weasyprint.formatting_structure import boxes
    bottoms, figs, calls, notes, nlines = {}, {}, {}, {}, {}
    for pn, page in enumerate(doc.pages, 1):
        low = 0.0
        stack = [(c, isinstance(c, boxes.FootnoteAreaBox), None) for c in page._page_box.children if not isinstance(c, boxes.MarginBox)]
        while stack:
            b, in_fn, blk = stack.pop()
            el = getattr(b, "element", None)
            eid = (el.get("id") or "") if el is not None and hasattr(el, "get") else ""
            if eid.startswith("n-"):
                blk = eid
            if in_fn:
                if el is not None and "fn" in (el.get("class") or "").split():
                    notes.setdefault(id(el), pn)
            else:
                if str(getattr(b, "element_tag", "") or "").endswith("::footnote-call") and el is not None:
                    calls.setdefault(id(el), (pn, blk))
                if getattr(b, "element_tag", None) == "figure" and eid.startswith("f-") and eid not in figs:
                    figs[eid] = (pn, b.position_y * PX_MM, b.margin_height() * PX_MM)
                if isinstance(b, (boxes.LineBox, boxes.ReplacedBox)):
                    low = max(low, (b.position_y + b.height) * PX_MM)
                if isinstance(b, boxes.LineBox) and getattr(b, "element_tag", None) in ("p", "li"):
                    nlines[pn] = nlines.get(pn, 0) + 1
            stack.extend((c, in_fn, blk) for c in (getattr(b, "children", ()) or ()))
        bottoms[pn] = low
    fn_bad = sorted({(pn, blk) for e, (pn, blk) in calls.items() if notes.get(e) != pn and blk})
    return bottoms, figs, fn_bad, nlines


def _layout_fixes(doc, pieces: list[dict], starts: list[int], last: int, tried: dict) -> list[list]:
    """看排好的页面，每篇最多给一条修法（先修最靠前的那处，后面的会跟着变，下一遍再看）"""
    bottoms, figs, fn_bad, nlines = _page_metrics(doc)
    out = []
    for k, p in enumerate(pieces):
        first, end = starts[k] + 1, (starts[k + 1] if k + 1 < len(starts) else last) - 1
        bl = p["blocks"]
        op = None
        ids = sorted((i for i in figs if i.startswith(f"f-{k}-")), key=lambda i: int(i.split("-")[2]))
        for fid in ids:
            j = int(fid.split("-")[2])
            pn, top, h = figs[fid]
            if j == 0 or pn <= first or top > BODY_TOP + 3:
                continue                                   # 不是「被挤到下一页页首」的图
            gap = BODY_BOT - bottoms.get(pn - 1, BODY_BOT)
            if gap < 17:                                   # 上一页页底空不到两行半，不算毛病
                continue
            n_try = tried.get((k, id(bl[j])), 0)
            if n_try >= 6:
                continue
            tried[(k, id(bl[j]))] = n_try + 1
            room, cum = gap - 7, bl[j].get("cum", 1.0)     # 图上下各留的空；这张图已经缩过多少
            e = j
            while e + 1 < len(bl) and bl[e + 1]["type"] == "img":
                e += 1
            if room >= h * 0.75 and cum * room / h >= 0.6:
                op = ["scale", k, j, round(room / h, 3)]   # 缩小不到四分之一就塞得回去
            elif e + 1 < len(bl) and bl[e + 1]["type"] != "h":
                op = ["pull", k, j, e + 1]                 # 让后面那段先排，把页底填上
            elif room >= h * 0.55 and cum * room / h >= 0.5:
                op = ["scale", k, j, round(room / h, 3)]
            if op:
                break
        if not op and end > first and not tried.get(("final", k)):
            # 图都摆好之后，篇末页还不到五行、或者还有页底空着：换一个段间距重排，挑毛病最少的
            score = ((2 if nlines.get(end, 0) < 5 else 0)
                     + sum(1 for q in range(first, end) if BODY_BOT - bottoms.get(q, BODY_BOT) >= 17))
            seen = tried.setdefault(("pgap", k), {})
            cur = p.get("pgap", 0.7)
            seen.setdefault(cur, score)
            rest = [v for v in PGAPS if v not in seen]
            if score and rest:
                op = ["pgap", k, rest[0]]
            else:
                best = min(seen, key=lambda v: (seen[v], abs(v - 0.7)))
                tried[("final", k)] = True
                if best != cur:
                    op = ["pgap", k, best]
        if not op and tried.get(("final", k)):
            # 最后收拾脚注：WeasyPrint 有时把注文甩到注码的下一页（多半和页底的孤行寡行回退有关，没查到确切原因）。
            # 对那一段依次试 NUDGES 里的办法，试到注码和注文回到同一页为止；都不行就留着，验收 ⑯ 会报出来。
            for pn, blk in fn_bad:
                _, kk, j = blk.split("-")
                if int(kk) != k:
                    continue
                if tried.get(("fn-giveup", blk)):
                    continue
                lv = bl[int(j)].get("nudge", 0)
                if lv < len(NUDGES):
                    op = ["nudge", k, int(j), lv + 1]
                elif bl[int(j)].get("nudge") == len(NUDGES) and int(j) > 0 and bl[int(j) - 1]["type"] == "img" and not bl[int(j)].get("swapped"):
                    bl[int(j)]["swapped"] = True      # 这一段前面紧挨着一张图时容易出这个毛病：让图排到这一段后面
                    op = ["swap0", k, int(j) - 1]
                else:                       # 都不管用：撤掉最后试的那个（另起一页），免得白白空出半页
                    tried[("fn-giveup", blk)] = True
                    op = ["nudge", k, int(j), 0]
                break
            # 挪动之后篇末页又短了的话，再挑一次段间距（只再来一次，免得来回折腾）
            if not op and nlines.get(end, 0) < 5 and not tried.get(("again", k)):
                tried[("again", k)] = True
                tried[("final", k)] = False
                tried[("pgap", k)] = {}
        if op:
            out.append(op)
    return out


def render(selection: dict, books: dict[str, dict], out_pdf: Path, config: dict, issue_dir: Path | None = None) -> int:
    from weasyprint import HTML

    # 刊名每期换成本期的两个字（issue.name，run.py 从 cover.json 的 title 抄进来）；封面、页眉、封底落款都跟着换。没写就用 config 里的。
    if selection["issue"].get("name"):
        config = {**config, "name": selection["issue"]["name"]}
    issue_dir = issue_dir or out_pdf.parent   # 译文、封面、插图都在期目录里；--out 另存时要单独给
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("issue.html")
    pieces = [_piece_view(p, books[p["book"]], translate.load(issue_dir, p, books[p["book"]]), issue_dir)
              for p in selection["pieces"]]
    cover = dict(config.get("cover") or {})                      # cover.json：刊名、配色、图案（run.py 读进来的）
    date = str(selection["issue"]["date"])
    paper = cover.get("paper") or selection["issue"].get("paper") or PAPER
    ctx = {"issue": selection["issue"], "pieces": pieces, "cfg": config, "fonts": (ROOT / "fonts").as_uri(),
           "paper": paper, "cover": cover,
           "cn_date": cn_date(str(selection["issue"]["date"]))}

    # 每期的封面单独设计、和内容呼应：期目录里放 封面.html / 封底.html（<section> 里面的内容，可用模板变量）
    # 和 封面.css（接在样式表最后，可改 @page cover / back 的底色）。没有这些文件时才退回默认的扇形图案。
    for key, name in (("cover_html", "封面.html"), ("back_html", "封底.html"), ("cover_css", "封面.css")):
        f = issue_dir / name
        ctx[key] = env.from_string(f.read_text(encoding="utf-8")).render(**ctx) if f.exists() else ""

    # 单独设计的封面：cover.json 写了 paper 就先把封面、封底的底色设成它，封面.css 里再写 @page 可以盖掉
    if ctx["cover_html"] and selection["issue"].get("paper"):
        ctx["cover_css"] = "@page cover { background: %s; }\n@page back { background: %s; }\n" % ((selection["issue"]["paper"],) * 2) + ctx["cover_css"]

    # 扉页和目录的颜色：issue.layers（run.py 从 cover.json 抄进来）给每篇一个颜色（一般就是封面上那几层的颜色），没给就用封面底色
    layers = list(selection["issue"].get("layers") or [])
    paper0 = paper
    for k, p in enumerate(pieces):
        c = layers[k % len(layers)] if layers else paper
        prev = (layers[(k - 1) % len(layers)] if k else paper0) if layers else paper0
        labs = selection["issue"].get("label_colors") or []      # 「本期选读」的颜色：有就用，没有把这一篇的颜色压暗
        p.update(color=c, dark=_lum(c) < 0.47, label_color=labs[k] if k < len(labs) else _label_color(c), art=_divider_art(k, c, prev, selection["issue"].get("divider_edge") or "straight"))
        if p.get("cover_path"):
            p["cover_url"] = shadowed(p["cover_path"], c).as_uri()     # 色块上的书影，阴影画在图里
        m = p["title_main"]
        if len(m) > 9 and "，" in m[2:-2]:      # 太长的篇名在逗号后面折行
            i = m.index("，", 2)
            p["title_main_html"] = m[: i + 1] + "<br>" + m[i + 1:]
        else:
            p["title_main_html"] = m
        # 篇名默认 25.5pt；篇名排到离书影不足 9mm 时降到 22.5pt（书影右沿 132.8mm、高 50.2mm，宽随封面比例）
        p["pt_small"] = False
        if p.get("cover_path"):
            from PIL import Image as _I
            with _I.open(p["cover_path"]) as im:
                cw = 50.2 * im.width / im.height
            longest = max(len(x) for x in p["title_main_html"].split("<br>"))
            p["pt_small"] = 14 + longest * 25.5 * 25.4 / 72 > 132.8 - cw - 8.9

    # 排若干遍。第一遍拿到每篇的起始页，才知道目录色带各段多高、扉页的页码印在左边还是右边；
    # 之后每一遍看一眼排出来的页面，修两种毛病（见 _layout_fixes），直到没有可修的：
    #   · 一张图放不下、整块挪到下一页，把上一页的页底挤空 → 图和后面的段落换位，或把图缩小一点塞回去
    #   · 一篇的最后一页只剩三四行 → 微调这一篇的段间距，把它收回上一页或撑到五行以上
    # 修法记在期目录的 版面微调.json 里，下次直接照做，不用再试。
    # config 里 pad_to_4: true 时再补空白笔记页凑成 4 的倍数（骑马钉印刷需要），默认不补。
    import hashlib
    key = hashlib.md5(json.dumps([[p.get("book"), p.get("chapter"), p.get("excerpt"), len(p["blocks"])] for p in pieces],
                                 ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    fix_file = issue_dir / "版面微调.json"
    ops = []
    if fix_file.exists():
        saved = json.loads(fix_file.read_text(encoding="utf-8"))
        if saved.get("key") == key:
            ops = saved.get("ops", [])
    replayed = bool(ops)          # 照着记下来的修法排，不再接着试（接着试会把已经排好的版面又搅乱）
    for op in ops:
        _apply_fix(pieces, op)
    tried: dict = {}
    pad, starts = 0, None
    for _ in range(120):
        n_p = len(pieces)
        if starts:
            ends = starts[1:] + [last]
            lengths = [e - b for b, e in zip(starts, ends)]
        else:
            lengths = [1] * n_p
        for k, p in enumerate(pieces):
            p["odd"] = (starts[k] % 2 == 1) if starts else True
        html = tpl.render(**ctx, note_pages=pad, toc=_toc_layout(lengths), nudges=NUDGES)
        doc = HTML(string=html, base_url=str(ROOT)).render()
        n = len(doc.pages)
        found = {}
        for i, pg in enumerate(doc.pages, 1):
            for name in pg.anchors:
                if name.startswith("piece-"):
                    found.setdefault(int(name.split("-")[1]), i)
        new = [found.get(k + 1, 0) for k in range(n_p)]
        last = n - pad            # 封底那一页（前面是笔记页）
        need_pad = bool(config.get("pad_to_4")) and n % 4 != 0
        more = _layout_fixes(doc, pieces, new, last, tried) if config.get("layout_fixes", True) and not replayed else []
        if more:
            for op in more:
                _apply_fix(pieces, op)
            ops += more
            starts = new
            continue
        if new == starts and not need_pad:
            break
        starts = new
        if need_pad:
            pad += 4 - n % 4
    if config.get("layout_fixes", True) and not replayed:
        fix_file.write_text(json.dumps({"key": key, "ops": ops}, ensure_ascii=False, indent=1), encoding="utf-8")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    (out_pdf.with_suffix(".html")).write_text(html, encoding="utf-8")
    doc.write_pdf(str(out_pdf))
    return len(doc.pages)
