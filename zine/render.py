"""第 9 步：拼装成杂志 PDF（A5）。封面封底按 cover.json 画，版式见 rules/typesetting/。

版式是中文优先的：正文宋体、首行缩进两字、小标题黑体。英文选篇必须先经过 translate 这一步。
"""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import translate
from .parse import CJK, inline, normalize_zh

ROOT = Path(__file__).resolve().parent.parent


_LATIN_PAREN = re.compile(r"（([^）]*[A-Za-z][^）]*)）")


# 字体组合：正文 / 标题 / 引文（题记、诗句、引子）。见 排版.md
FONT_COMBOS = {
    "A": ("SongTi", "HeiTi", "SongTi"),
    "B": ("SongTi", "HeiTi", "KaiTi"),
    "C": ("SongTi", "SongTi", "KaiTi"),
    "D": ("KaiTi", "HeiTi", "KaiTi"),
}

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


# 封面配色：每期换一组。cover.json 的 palette 可以是名字、序号或 {field, shapes}；没有就按 seed 轮着用。
# field 是底色，shapes 是"纸"的三种颜色。见 rules/typesetting/covers.md
# 纸色固定三样（rules/quality/验收.md C6）：墨黑 #1E1D1A（与内页同一个值）、米白 #FBF8F1、拾页红 #D94F2B；不用蓝
INK, CREAM, RED = "#1E1D1A", "#FBF8F1", "#D94F2B"
PALETTES = [
    {"name": "淡紫", "field": "#D9D4E7", "shapes": [INK, CREAM, RED], "ink": INK},
    {"name": "芥末黄", "field": "#E6B93F", "shapes": [INK, CREAM, RED], "ink": INK},
    {"name": "灰绿", "field": "#DCE5DF", "shapes": ["#1F3D2B", CREAM, RED], "ink": INK},
    {"name": "淡粉", "field": "#F0D9D0", "shapes": [INK, CREAM, RED], "ink": INK},
]
MAST_FONTS = {"kai": "KaiTi", "song": "SongTi", "hei": "HeiTi"}


def palette(seed: int, config: dict) -> dict:
    p = (config.get("cover") or {}).get("palette", config.get("palette"))
    if isinstance(p, dict):
        shapes = list(p.get("shapes") or [])
        if len(shapes) < 3:
            raise ValueError("自定义调色板要给 field 和三个 shapes 颜色")
        return {"name": p.get("name", "自定义"), "field": p["field"], "shapes": shapes[:3], "ink": p.get("ink", INK)}
    if isinstance(p, str):
        for pal in PALETTES:
            if pal["name"] == p:
                return pal
        if not p.isdigit():
            raise ValueError(f"不认识的调色板 {p!r}；可用：{'、'.join(x['name'] for x in PALETTES)}，或 {{field, shapes}}")
        p = int(p)
    if isinstance(p, int):
        return PALETTES[p % len(PALETTES)]
    return PALETTES[(int(seed) - 1) % len(PALETTES)]


def cover_art(seed: int, pal: dict, mirror: bool = False, motif: str = "fan", svg: str | None = None) -> str:
    """封面图案。motif：fan 十张纸从左下角扇形展开；stack 八张纸叠在左下；scatter 十张纸散落下半页；svg 自写片段。
    seed 做随机种子，同一期每次生成都一样。mirror=True 是封底：左右翻转，摊开来前后封面在书脊处拼起来。"""
    import random
    rnd = random.Random(int(seed))
    sh = pal["shapes"]
    parts = []
    if motif == "svg" and svg:
        body = svg
    elif motif == "stack":
        for i in range(8):
            x, y, a = 14 + i * 2.2 + rnd.uniform(-1, 1), 150 - i * 3.6 + rnd.uniform(-1, 1), rnd.uniform(-5, 5)
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="56" height="78" fill="{sh[i % 3]}" '
                         f'transform="rotate({a:.1f} {x + 28:.1f} {y + 39:.1f})"/>')
        body = "".join(parts)
    elif motif == "scatter":
        for i in range(10):
            x, y, a = rnd.uniform(4, 96), rnd.uniform(96, 168), rnd.uniform(-40, 40)
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="30" height="42" fill="{sh[i % 3]}" '
                         f'transform="rotate({a:.1f} {x + 15:.1f} {y + 21:.1f})"/>')
        body = "".join(parts)
    else:
        cx, cy, n, w, h = 26, 232, 10, 44, 150   # 扇子的轴心在页面左下角外面一点
        for i in range(n):
            a = -24 + i * (96 / (n - 1)) + rnd.uniform(-1.2, 1.2)
            parts.append(f'<rect x="{cx}" y="{cy - h}" width="{w}" height="{h}" fill="{sh[i % 3]}" '
                         f'fill-opacity="0.9" transform="rotate({a:.1f} {cx} {cy})"/>')
        body = "".join(parts)
    if mirror:
        body = f'<g transform="translate(148 0) scale(-1 1)">{body}</g>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 148 210" width="148mm" height="210mm">{body}</svg>'


def cn_date(date: str) -> tuple[str, str]:
    """"2026-10-13" → ("二〇二六年", "十月")"""
    digits = "〇一二三四五六七八九"
    y, m = date.split("-")[:2]
    m = int(m)
    month = ("十" if m >= 10 else "") + (digits[m % 10] if m % 10 else "")
    return "".join(digits[int(c)] for c in y) + "年", month + "月"


SHADOW_PAD_MM = 4.8   # 阴影图四周留的边（显示时用负 margin 抵掉，封面本身的大小不变）


def shadowed(src: Path, paper: str = "#FFFFFF") -> Path:
    """给书影加一圈柔和的阴影，直接画进图片里（PDF 里就是一张普通位图，打印一定出得来）。
    输出高 820px = 封面 700px + 上下各 60px 边；按 12.5px/mm 显示（高 65.6mm，封面本身 56mm）。"""
    from PIL import Image, ImageDraw, ImageFilter

    out = src.with_name(src.name.rsplit(".", 1)[0] + ".shadow.png")
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


def _img_view(path: Path, caption: str, box: bool = False) -> dict:
    src, w, h = prepared_image(path)
    max_w = min(116, w / 152 * 25.4)                   # 置入宽 ≤ 原图像素 ÷ 152 × 25.4mm → 有效分辨率 > 150ppi（留一点余量）
    return {"type": "img", "src": src.resolve().as_uri(), "style": f"max-width: {max_w:.1f}mm",   # 加在 figure 上，方框里不超出
            "caption": _spacing(inline(caption)) if caption else ""}


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


def _piece_view(piece: dict, book: dict, zh: dict | None, issue_dir: Path) -> dict:
    ch, blocks, _, _ = translate.selected(piece, book)
    title = ch["title"]
    if zh:
        # 译文按段对应，type 以原文为准（原文解析可能后来把某段识别成了小标题）；译文也过一遍字符体例
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
            return _img_view(issue_dir / "books" / b["src"], b.get("caption") or "")
        if b["type"] == "list":
            return {"type": "list", "items": [{"type": "li", "num": bool(_NUM_ITEM.match(it["text"])),
                                               "html": _spacing(_no_stretch(inline(_tidy_num(it["text"]))))} for it in b["items"]]}
        if b["type"] == "box":
            items = []
            for it in b["items"]:
                if it["type"] == "img":
                    items.append(_img_view(issue_dir / "books" / it["src"], it.get("caption") or "", box=True))
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
    chapter_label = _chapter_label(title if zh else ch["title"])
    if excerpted:
        sub = piece.get("title")
        chapter_label += f"（节选：{sub}）" if sub and sub not in ch["title"] else "（节选）"
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
        "translator": book.get("translator"),
        "year": book.get("year"),
        "source": book.get("source", ""),
        "chapter_title": piece.get("title") or title,
        "original_chapter": ch["title"],
        "chapter_label": chapter_label,
        "context_html": _spacing(inline(piece.get("context") or "")),
        "intro_html": _spacing(inline(piece.get("intro") or "")),
        "cover_url": shadowed((issue_dir / "books" / book["cover"]).resolve()).as_uri() if book.get("cover") else None,
        "excerpted": excerpted,
        "translated": bool(zh),
        "chars": chars,
        "blocks": html_blocks,
    }


def render(selection: dict, books: dict[str, dict], out_pdf: Path, config: dict, issue_dir: Path | None = None) -> int:
    from weasyprint import HTML

    issue_dir = issue_dir or out_pdf.parent   # 译文、封面、插图都在期目录里；--out 另存时要单独给
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("issue.html")
    pieces = [_piece_view(p, books[p["book"]], translate.load(issue_dir, p, books[p["book"]]), issue_dir)
              for p in selection["pieces"]]
    cover = dict(config.get("cover") or {})
    date = str(selection["issue"]["date"])
    seed = int(cover.get("seed") or selection["issue"].get("number") or (int(re.sub(r"\D", "", date) or 1) % 9973))
    pal = palette(seed, config)
    motif, svg = cover.get("motif") or "fan", cover.get("svg")
    ctx = {"issue": selection["issue"], "pieces": pieces, "cfg": config, "fonts": (ROOT / "fonts").as_uri(),
           "F": FONT_COMBOS.get(config.get("fonts") or "B", FONT_COMBOS["B"]),
           "pal": pal, "cover": cover, "mast_font": MAST_FONTS.get(cover.get("mast") or "kai", "KaiTi"),
           "cover_svg": cover_art(seed, pal, motif=motif, svg=svg),
           "back_svg": cover_art(seed, pal, mirror=True, motif=motif, svg=svg),
           "cn_date": cn_date(date)}

    # 默认不补页。config 里 pad_to_4: true 时，补空白笔记页凑成 4 的倍数（骑马钉印刷需要）
    pad = 0
    for _ in range(2 if config.get("pad_to_4") else 1):
        html = tpl.render(**ctx, note_pages=pad)
        doc = HTML(string=html, base_url=str(ROOT)).render()
        n = len(doc.pages)
        if not config.get("pad_to_4") or n % 4 == 0:
            break
        pad += 4 - n % 4
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    (out_pdf.with_suffix(".html")).write_text(html, encoding="utf-8")
    doc.write_pdf(str(out_pdf))
    return len(doc.pages)
