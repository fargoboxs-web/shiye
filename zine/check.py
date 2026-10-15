#!/usr/bin/env python3
"""拾页成品的硬指标检查：对渲染好的一期（PDF + 同名 HTML + selection.json）量数字、对规则。

用法：python3 check.py <期目录> [--out 报告.md] [--tail-lines 5] [--booklet]
  期目录里自动找 拾页-*.pdf、同名 .html、selection.json。
  报告写成 Markdown（默认 <期目录>/检查报告.md；目录只读时用 --out 指到别处），stdout 打印摘要。
  --tail-lines N   篇末页正文少于 N 行算过短（默认 5）
  --booklet        要印骑马钉：总页数不是 4 的倍数算不通过（默认只警告）
退出码：有「不通过」则 1。

只量、不改。依据 rules/typesetting、templates/issue.html 的数值，以及 clreq / CY/T 121—2015 的禁则。
判别字体用 PDF 里的字体名：SongTi=宋、HeiTi*=黑、KaiTi=楷；判别角色用字号和位置。

检查项：
  ① 页面尺寸 A5、总页数（奇数不过、非 4 倍数警告）   ② 字体嵌入、只有宋黑楷三族
  ③ 缺字（U+FFFD、私用区；HTML 汉字 ⊆ PDF 汉字）      ④ 位图 ppi（<150 不过、<300 警告）、超版心、灰底、书影原图像素；④b 章首装饰图
  ⑤ 字号/行距/每行字数/版心/天头 对 rules/typesetting；⑤b 字号表逐项对照
  ⑥ 背题、连续标题                                   ⑦ 孤行寡行
  ⑧ 段末单字成行                                      ⑨ 篇末页行数；⑨b 篇幅（页数、字数、长短比）
  ⑩ 页眉页码位置与文字、页码离边、文字安全区           ⑪ 目录页码/篇名、书签
  ⑫ 「第 N 期」、汉字日期、元数据                      ⑬ 引子/摘要字数、脚注条数、扉页要素、章节标签、译者
  ⑭ 行首行末禁则、行首注码、半角标点、引号/破折号/间隔号体例
  ⑮ 封面底色 L*、纸色对比、透明、封底同色；⑮b 书脊拼合、墨量
  ⑯ 脚注同页、编号、注线                              ⑰ 非篇末页页底空白
  ⑱ 行内空隙（拉宽的空格）                            ⑲ 右边缘齐
  ⑳ 红字位置；⑳b 内页颜色集合                         ㉑ 框线字符、数字零
  ㉒ 篇末 ■ 与节选短线                                ㉓ 页面顺序
  ㉔ 图注、图随文走
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import pdfplumber
from bs4 import BeautifulSoup
from pypdf import PdfReader

MM = 72 / 25.4                      # 1mm = 2.835pt
A5 = (148.0, 210.0)                 # mm
MARGIN = {"top": 20, "bottom": 18, "left": 16, "right": 16}   # mm，rules/typesetting「页面」
LEFT = MARGIN["left"] * MM          # 版心左 45.35pt
RIGHT = (A5[0] - MARGIN["right"]) * MM   # 版心右 374.17pt
TOP = MARGIN["top"] * MM            # 56.69pt
BOT = (A5[1] - MARGIN["bottom"]) * MM    # 地脚线 544.25pt
BODY_PT = 10.5                      # 正文五号
PITCH = BODY_PT * 1.75              # 18.375pt
CPL = 31                            # 每行字数
RIGHT_GLYPH = LEFT + CPL * BODY_PT  # 整行最后一个字的右边 370.85pt（两端对齐只拉空格，纯汉字行到不了 374.17）
HEAD_ZONE = 30                      # top < 30pt 的字是页眉
FN_CALL_MAX = 7.5                   # 注码上标 6.3pt
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
CLOSE = "，。、；：！？」』）》〉”’…"      # 不能在行首
OPEN = "「『（《〈“‘"                   # 不能在行末
FORBID_ISSUE = re.compile(r"第\s*\d+\s*期")
ALLOWED_FAMILIES = {"SongTi", "HeiTi", "KaiTi"}
ACCENT = (0.709804, 0.262745, 0.168627)   # #B5432B 拾页红

# 字号表：rules/typesetting 的数字；rules/typesetting 和模板不一致的地方以模板为准，在 NOTE 里注明
SIZE_TABLE = [
    # (名称, 字体, 期望字号, 备注)
    ("正文", "SongTi", 10.5, ""),
    ("引文（楷体段）", "KaiTi", 10.0, ""),
    ("节标题", "HeiTi", 11.5, ""),
    ("小节标题", "HeiTi", 10.5, ""),
    ("篇名", "HeiTi", 16.0, ""),
    ("扉页书名", "HeiTi", (20.0, 22.0), "rules/typesetting 写 20pt，render.py 按书名长度 20–22pt"),
    ("扉页引子", "KaiTi", 10.5, ""),
    ("扉页摘要", "SongTi", 10.0, ""),
    ("方框栏目", "SongTi", 9.5, ""),
    ("方框标题", "HeiTi", 10.0, ""),
    ("脚注", "SongTi", 9.0, "rules/typesetting 字号表写 8.5pt、「脚注」一节写 9pt；模板 .fn 是 9pt"),
    ("图注", "HeiTi", 8.5, ""),
    ("页眉", "HeiTi", 7.5, ""),
    ("页码", "HeiTi", 8.5, "rules/typesetting 字号表写「反白在小黑框里」，「页面」一节写普通数字；模板是普通数字"),
]


# ---------------------------------------------------------------- 工具

def mm(pt: float) -> float:
    return pt / MM


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def fam(fontname: str) -> str:
    """'LUHEOC+HeiTi-Semi-Bold' → 'HeiTi'"""
    return fontname.split("+")[-1].split("-")[0]


def weight(fontname: str) -> str:
    """'HeiTi-Semi-Bold' → 'Semi-Bold'，没有就 ''"""
    n = fontname.split("+")[-1]
    return n.split("-", 1)[1] if "-" in n else ""


def cn_date(date: str) -> tuple[str, str]:
    """"2026-10-13" → ("二〇二六年", "十月")，照 render.py"""
    digits = "〇一二三四五六七八九"
    y, m = date.split("-")[:2]
    m = int(m)
    month = ("十" if m >= 10 else "") + (digits[m % 10] if m % 10 else "")
    return "".join(digits[int(c)] for c in y) + "年", month + "月"


def hex_to_lab(h: str) -> tuple[float, float, float]:
    """#RRGGBB → CIE L*a*b*（D65），顺便算 WCAG 相对亮度"""
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    L = 116 * f(y) - 16
    a, b = 500 * (f(x) - f(y)), 200 * (f(y) - f(z))
    return round(L, 1), round(y, 3), round(math.hypot(a, b), 1)   # (L*, 相对亮度, 彩度 C*)


def delta_e(h1: str, h2: str) -> float:
    """两色的 CIE76 ΔE（验收 C7 用它量底色对拾页红的距离）"""
    def lab(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
        z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
        f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
        return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))
    a, b = lab(h1), lab(h2)
    return round(math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b))), 1)


def rgb_close(c, target, tol=0.02) -> bool:
    return isinstance(c, (tuple, list)) and len(c) == 3 and all(abs(a - b) < tol for a, b in zip(c, target))


# ---------------------------------------------------------------- 行模型

class Line:
    __slots__ = ("page", "chars", "top", "bottom", "base", "x0", "x1", "text", "font", "size", "style")

    def __init__(self, page_no: int, chars: list[dict], page_h: float):
        self.page = page_no
        self.chars = sorted(chars, key=lambda c: c["x0"])
        solid = [c for c in self.chars if c["text"].strip()] or self.chars
        f = collections.Counter((c["fontname"].split("+")[-1], round(c["size"], 1)) for c in solid).most_common(1)[0][0]
        self.font, self.size = f
        main = [c for c in solid if round(c["size"], 1) == self.size] or solid
        self.top = min(c["top"] for c in main)
        self.bottom = max(c["bottom"] for c in main)
        self.base = page_h - main[0]["matrix"][5]      # 基线（从页顶量）
        self.x0 = min(c["x0"] for c in solid)
        self.x1 = max(c["x1"] for c in solid)
        self.text = "".join(c["text"] for c in self.chars)
        self.style = ""

    @property
    def ncjk(self) -> int:
        return len(CJK.findall(self.text))

    def __repr__(self):
        return f"<第{self.page}页 {self.style} top={mm(self.top):.1f}mm {self.text[:20]!r}>"


def build_lines(page, page_no: int) -> list[Line]:
    """按 top 聚成行（容差 3pt：注码上标、条目的 ■ 和同行文字 top 差 1–2pt）。"""
    chars = sorted(page.chars, key=lambda c: (c["top"], c["x0"]))
    groups, cur, ref = [], [], None
    for c in chars:
        if cur and c["top"] - ref > 3.0:
            groups.append(cur); cur = []
        if not cur:
            ref = c["top"]
        cur.append(c)
    if cur:
        groups.append(cur)
    return [Line(page_no, g, page.height) for g in groups]


def classify(line: Line, role: str) -> str:
    """给行定角色。字体名 + 字号 + 位置，对应模板 CSS 里的各条。"""
    f, s, w = fam(line.font), line.size, weight(line.font)
    t = line.text.strip()
    if line.top < HEAD_ZONE and role in ("article",):
        return "runhead"
    if f == "SongTi":
        if s == 10.5: return "body"
        if s == 9.0 and role == "article" and line.x0 < LEFT + 2: return "fn"
        if s == 9.0: return "toc-b"
        if s == 9.5: return "box"
        if s == 8.0 and t == "■": return "endmark"
        if s == 8.0: return "date"
        if s == 10.0: return "intro"
        if s <= FN_CALL_MAX: return "call"
        return "song-other"
    if f == "KaiTi":
        if s == 10.0: return "quote"
        if s == 10.5: return "lead" if role == "divider" else "epi"
        if s >= 40: return "mast"
        return "kai-other"
    if f == "HeiTi":
        if w == "Bold":
            if s == 16.0: return "h2"
            if s >= 14.0: return "bt"
            if s == 10.0: return "boxtitle"
        if w == "Semi-Bold":
            if s == 11.5: return "h4"
            if s == 10.5: return "pick" if role == "divider" else "h5"
            if s == 9.5: return "bh"
            if s == 11.0: return "toc-h"
            if s == 8.5: return "toc-n"
            if s == 8.0: return "num"
            if s == 7.5: return "lab"
        if w == "Medium" and s == 8.5: return "pageno"
        if w == "":
            if s == 8.0: return "from"
            if s == 8.5: return "by" if role == "divider" else "caption"
            if s == 7.5: return "runhead"
    return "other"


TEXT_STYLES = {"body", "quote", "epi"}          # 算「正文行」的
PARA_STYLES = {"body", "quote", "box"}          # 有段首缩进、要查孤字/孤行的


def para_geom(style: str):
    """各类段落的左边、首行缩进后的左边、整行右边（pt）。"""
    if style == "body":   # 条目行 x0 在 LEFT+2em 右边更远，另算
        return LEFT, LEFT + 2 * BODY_PT, RIGHT_GLYPH
    if style == "quote":  # 左缩 2 字右缩 1 字，首行再缩 2 字（10pt）
        return LEFT + 20, LEFT + 40, RIGHT - 10 - 0.5
    if style == "box":    # 框内 padding 4.5mm + 0.5pt 边，9.5pt
        l = LEFT + 0.5 + 4.5 * MM
        return l, l + 19, RIGHT - 0.5 - 4.5 * MM
    return None


# ---------------------------------------------------------------- 检查结果

class Report:
    def __init__(self):
        self.items = []     # (编号, 名称, 状态, 要点, 证据行)
        self.notes = []

    def add(self, no: str, name: str, status: str, summary: str, evidence: list[str] | None = None):
        self.items.append((no, name, status, summary, evidence or []))

    @property
    def failed(self) -> bool:
        return any(s == "不通过" for _, _, s, _, _ in self.items)


# ---------------------------------------------------------------- 主体

class Issue:
    def __init__(self, issue_dir: Path):
        self.dir = issue_dir
        pdfs = sorted(issue_dir.glob(f"*-{issue_dir.name}.pdf")) or sorted(issue_dir.glob("*.pdf"))
        if not pdfs:
            sys.exit(f"{issue_dir} 里没有排好的 PDF（先跑 run.py render）")
        self.pdf_path = pdfs[-1]
        self.html_path = self.pdf_path.with_suffix(".html")
        self.sel_path = issue_dir / "selection.json"
        self.html = self.html_path.read_text(encoding="utf-8") if self.html_path.exists() else ""
        self.soup = BeautifulSoup(self.html, "html.parser") if self.html else None
        self.sel = json.loads(self.sel_path.read_text(encoding="utf-8")) if self.sel_path.exists() else {}
        self.pdf = pdfplumber.open(str(self.pdf_path))
        self.reader = PdfReader(str(self.pdf_path))
        self.n = len(self.pdf.pages)
        self.text_pages = run(["pdftotext", str(self.pdf_path), "-"]).split("\f")
        self.lines: dict[int, list[Line]] = {}
        self.roles: dict[int, str] = {}
        self._structure()

    # ---- 页面角色：封面、目录、扉页、正文、笔记页、封底。扉页和正文首页从书签拿，没书签再按字体猜
    def _structure(self):
        n = self.n
        for p in range(1, n + 1):
            self.lines[p] = build_lines(self.pdf.pages[p - 1], p)
        outline = []
        def walk(items, depth):
            for it in items:
                if isinstance(it, list):
                    walk(it, depth + 1)
                else:
                    try:
                        outline.append((depth, it.title, self.reader.get_destination_page_number(it) + 1))
                    except Exception:
                        pass
        try:
            walk(self.reader.outline, 1)
        except Exception:
            pass
        self.outline = outline
        # WeasyPrint 按标题级别做书签：扉页的 h2「《书名》」和正文的 h2「篇名」都在第 1 级，h4 第 2 级、h5 第 3 级。
        # 扉页 = 第 1 级且题目是「《…》」的；该篇正文首页 = 紧随其后的第 1 级书签页（没有就扉页 + 1）
        lvl1 = [(pg, t) for d, t, pg in outline if d == 1]
        dividers, starts = [], []
        for i, (pg, t) in enumerate(lvl1):
            if re.fullmatch(r"《.+》", t.strip()):
                dividers.append(pg)
                nxt = lvl1[i + 1] if i + 1 < len(lvl1) else None
                starts.append((nxt[0], nxt[1]) if nxt and not re.fullmatch(r"《.+》", nxt[1].strip()) else (pg + 1, ""))
        if not dividers:   # 没书签：扉页 = 无页眉、有大黑体书名的页
            for p in range(2, n):
                ls = self.lines[p]
                if ls and not any(l.top < HEAD_ZONE for l in ls) and any(fam(l.font) == "HeiTi" and l.size >= 19 for l in ls):
                    dividers.append(p)
            starts = [(p + 1, "") for p in dividers]
        self.dividers = dividers
        # 笔记页：没有字、只有横线的页（封底前）
        notes = [p for p in range(2, n) if not self.pdf.pages[p - 1].chars and len(self.pdf.pages[p - 1].rects) > 5]
        self.note_pages = notes
        last_body = n - 1
        while last_body in notes:
            last_body -= 1
        self.articles = []   # [(序号, 起页, 止页, 篇名)]
        for i, (s, t) in enumerate(starts):
            e = (dividers[i + 1] - 1) if i + 1 < len(dividers) else last_body
            self.articles.append((i + 1, s, e, t))
        for p in range(1, n + 1):
            if p == 1: r = "cover"
            elif p == n: r = "back"
            elif p == 2: r = "contents"
            elif p in dividers: r = "divider"
            elif p in notes: r = "notes"
            elif any(s <= p <= e for _, s, e, _ in self.articles): r = "article"
            else: r = "other"
            self.roles[p] = r
            for l in self.lines[p]:
                l.style = classify(l, r)
        self.article_of = {}
        for k, s, e, _ in self.articles:
            for p in range(s, e + 1):
                self.article_of[p] = k
        self.last_pages = {e for _, _, e, _ in self.articles}
        self.first_pages = {s for _, s, _, _ in self.articles}

    def article_pages(self):
        return [p for p in range(1, self.n + 1) if self.roles[p] == "article"]

    def book_title(self, k: int) -> str:
        """第 k 篇的书名（从正文首页的出处行「《书名》作者」取）"""
        s = self.articles[k - 1][1]
        for l in self.lines[s]:
            if l.style == "from":
                m = re.match(r"《(.+?)》", l.text)
                if m: return m.group(1)
        return ""

    def local_image(self, src: str) -> Path | None:
        """HTML 里 file:// 路径 → 本机路径；渲染机和检查机路径前缀可能不同，退回到期目录 books/ 下按相对路径找"""
        p = Path(unquote(urlparse(src).path))
        if p.exists():
            return p
        if "/books/" in p.as_posix():
            q = self.dir / "books" / p.as_posix().split("/books/", 1)[1]
            if q.exists():
                return q
        return None


# ---------------------------------------------------------------- 各项检查

def check_pages(iss: Issue, rep: Report, booklet: bool):
    """① 页面尺寸 A5、总页数、4 的倍数"""
    bad = []
    for i, p in enumerate(iss.reader.pages, 1):
        w, h = mm(float(p.mediabox.width)), mm(float(p.mediabox.height))
        rot = p.get("/Rotate") or 0
        if abs(w - A5[0]) > 0.5 or abs(h - A5[1]) > 0.5 or rot:
            bad.append(f"第 {i} 页 {w:.1f}×{h:.1f}mm rotate={rot}")
    rep.add("①a", "页面尺寸 A5（148×210mm ± 0.5）", "不通过" if bad else "通过",
            f"{iss.n} 页" + ("，不合格：" + "；".join(bad[:5]) if bad else "，全部 148.0×210.0mm，无旋转"), bad)
    n = iss.n
    ev = [f"总页数 {n}：封面 1、目录 1、扉页 {len(iss.dividers)}、正文 {len(iss.article_pages())}、笔记页 {len(iss.note_pages)}、封底 1"]
    if n % 4 == 0:
        st, s = "通过", f"{n} 页，是 4 的倍数，可直接做骑马钉小册子"
    elif n % 2 == 1:
        st, s = "不通过", f"{n} 页是奇数：双面印时封底落在最后一张纸的正面、背面是白纸；差 {4 - n % 4} 页到 4 的倍数（补笔记页，放在最后一篇后、封底前）"
    else:
        st, s = ("不通过" if booklet else "警告"), f"{n} 页是偶数但不是 4 的倍数，骑马钉要补 {4 - n % 4} 页笔记页"
    rep.add("①b", "总页数", st, s, ev)


def check_fonts(iss: Issue, rep: Report):
    """② 字体全部嵌入、只用宋黑楷三族"""
    rows = [l for l in run(["pdffonts", str(iss.pdf_path)]).splitlines()[2:] if l.strip()]
    bad, fams = [], set()
    for r in rows:
        parts = r.split()
        name = parts[0]
        emb, sub, uni = parts[-5], parts[-4], parts[-3]   # 末尾是 emb sub uni objID gen（type 列「CID TrueType」有空格，只能从右数）
        fams.add(fam(name))
        if emb != "yes" or uni != "yes":
            bad.append(f"{name} emb={emb} sub={sub} uni={uni}")
    extra = fams - ALLOWED_FAMILIES
    st = "不通过" if bad or extra else "通过"
    rep.add("②", "字体嵌入与字体族", st,
            f"{len(rows)} 个字体，族 {sorted(fams)}" + ("，未嵌入/无 ToUnicode：" + "；".join(bad) if bad else "，全部嵌入、子集化、带 ToUnicode")
            + ("，规则外字体族：" + "、".join(sorted(extra)) if extra else ""),
            [r for r in rows])


def check_missing_glyphs(iss: Issue, rep: Report):
    """③ 缺字：U+FFFD、私用区；HTML 里的汉字 PDF 文本里都找得到"""
    hits = []
    for i, pg in enumerate(iss.text_pages, 1):
        bad = sorted({c for c in pg if c == "�" or 0xE000 <= ord(c) <= 0xF8FF})
        if bad:
            hits.append(f"第 {i} 页 {bad}")
    missing = set()
    if iss.soup:
        html_cjk = set(CJK.findall(iss.soup.body.get_text() if iss.soup.body else iss.soup.get_text()))
        pdf_cjk = set(CJK.findall("".join(iss.text_pages)))
        missing = html_cjk - pdf_cjk
    st = "不通过" if hits or missing else "通过"
    rep.add("③", "缺字", st,
            (f"U+FFFD/私用区字符 {len(hits)} 页" if hits else "无 U+FFFD、无私用区字符") +
            (f"；HTML 有 {len(html_cjk)} 个不同汉字，PDF 里找不到 {len(missing)} 个：{''.join(sorted(missing))[:40]}" if iss.soup and missing
             else (f"；HTML 的 {len(html_cjk)} 个不同汉字全部出现在 PDF 文本里" if iss.soup else "；没有 HTML，跳过汉字对照")),
            hits)


def check_images(iss: Issue, rep: Report):
    """④ 位图有效分辨率、是否超出版心、高度上限；书影原图像素；灰底图"""
    ev, fail, warn = [], [], []
    pdf_imgs = run(["pdfimages", "-list", str(iss.pdf_path)]).splitlines()[2:]
    ppi_tab = {}
    for r in pdf_imgs:
        p = r.split()
        if len(p) > 13 and p[0].isdigit():
            ppi_tab.setdefault(int(p[0]), []).append((int(p[3]), int(p[4]), int(p[12]), int(p[13])))
    src_map = {}   # (页, 序) → HTML 里的 img 路径，按出现顺序对应
    if iss.soup:
        srcs = [img.get("src", "") for img in iss.soup.select("section.divider img, section.article img")]
    else:
        srcs = []
    k = 0
    for p in range(1, iss.n + 1):
        role = iss.roles[p]
        for im in iss.pdf.pages[p - 1].images:
            w, h = im["x1"] - im["x0"], im["bottom"] - im["top"]
            sw, sh = im.get("srcsize") or (0, 0)
            ppi = sw / (w / 72) if w else 0
            src = srcs[k] if k < len(srcs) else ""
            k += 1
            kind = "书影" if role == "divider" else "插图"
            line = f"第 {p} 页 {kind} {sw}×{sh}px → {mm(w):.1f}×{mm(h):.1f}mm，有效 {ppi:.0f} ppi"
            # 分辨率
            if ppi < 150:
                fail.append(line + "（< 150 不过）")
            elif ppi < 300:
                warn.append(line + "（< 300 警告）")
            # 版心：扉页书影带 4.8mm 阴影边，允许出头
            pad = 4.8 * MM if role == "divider" else 0
            out = []
            if im["x0"] < LEFT - pad - 1: out.append(f"左出 {mm(LEFT - im['x0']):.1f}mm")
            if im["x1"] > RIGHT + pad + 1: out.append(f"右出 {mm(im['x1'] - RIGHT):.1f}mm")
            if im["top"] < TOP - pad - 1: out.append(f"上出 {mm(TOP - im['top']):.1f}mm")
            if im["bottom"] > BOT + pad + 1: out.append(f"下出 {mm(im['bottom'] - BOT):.1f}mm")
            if out:
                fail.append(f"第 {p} 页 {kind} 超出版心：{'、'.join(out)}")
            if role == "article" and h > 86 * MM + 1:   # 验收 F2：高 ≤ 86mm（版心 1/2）；模板 max-height 同值
                fail.append(f"第 {p} 页 插图高 {mm(h):.1f}mm > 86mm 上限")
            if role == "divider" and abs(h - 65.6 * MM) > 0.5 * MM:
                warn.append(f"第 {p} 页 书影高 {mm(h):.1f}mm（含阴影边应为 65.6mm）")
            # 原图检查（需要本机能找到图）
            local = iss.local_image(src) if src else None
            if local and role == "divider":
                stem = local.name.replace(".shadow.png", "")
                orig = [q for q in local.parent.glob(stem + ".*") if "shadow" not in q.name]
                if orig:
                    try:
                        from PIL import Image
                        ow, oh = Image.open(orig[0]).size
                        if oh < 660:
                            fail.append(f"第 {p} 页 书影原图 {orig[0].name} 只有 {ow}×{oh}px，56mm 高下不足 300dpi（要 ≥ 660px）")
                        else:
                            line += f"；原图 {ow}×{oh}px"
                    except Exception as e:
                        warn.append(f"第 {p} 页 书影原图读不了：{e}")
            if local and role == "article":
                try:
                    from PIL import Image, ImageStat
                    imo = Image.open(local).convert("RGB")
                    px_mm = imo.width / mm(w)        # 每 mm 像素
                    b = max(1, int(1.5 * px_mm))
                    W, H = imo.size
                    edge = Image.new("L", (W, H), 0)
                    from PIL import ImageDraw
                    d = ImageDraw.Draw(edge)
                    d.rectangle([0, 0, W - 1, H - 1], outline=255, width=b)
                    g = imo.convert("L")
                    mean = ImageStat.Stat(g, mask=edge).mean[0]
                    area = mm(w) * mm(h) / 100   # cm²
                    rgb = ImageStat.Stat(imo).mean
                    sat = max(rgb) - min(rgb)
                    line += f"；四边亮度 {mean:.0f}/255，{area:.0f}cm²，RGB 差 {sat:.1f}"
                    if mean < 235:
                        (fail if area > 30 else warn).append(
                            f"第 {p} 页 插图不是白底（四边亮度 {mean:.0f} < 245），面积 {area:.0f}cm²" + ("，> 30cm² 的灰底图不进内页" if area > 30 else "，去底或缩到 25cm² 以内"))
                    elif mean < 245:   # 接近白：多半是图自带的框线
                        warn.append(f"第 {p} 页 插图四边亮度 {mean:.0f}，不纯白（图自带框线或浅灰边），面积 {area:.0f}cm²")
                except Exception as e:
                    warn.append(f"第 {p} 页 插图原图读不了：{e}")
            ev.append(line)
    n_img = len(ev)
    st = "不通过" if fail else ("警告" if warn else "通过")
    rep.add("④", "位图分辨率、位置、底色", st,
            f"{n_img} 张位图：{len(fail)} 项不过、{len(warn)} 项警告" + ("；" + "；".join(fail[:3]) if fail else ""),
            ["不过：" + x for x in fail] + ["警告：" + x for x in warn] + ev)
    # 章首装饰图：正文第一个块就是没有图注的图
    if iss.soup:
        deco = []
        for i, art in enumerate(iss.soup.select("section.article"), 1):
            body = art.select_one(".body")
            kids = [c for c in body.children if getattr(c, "name", None) and c.name not in ("div",)] if body else []
            if kids and kids[0].name == "figure" and not kids[0].find("figcaption"):
                deco.append(f"第 {i} 篇（第 {iss.articles[i-1][1]} 页）正文第一个块是无图注的图，像电子书的章首装饰图")
        rep.add("④b", "章首装饰图", "警告" if deco else "通过",
                "；".join(deco) if deco else "没有一篇以无图注的图开头", deco)


def body_lines_on(iss: Issue, p: int) -> list[Line]:
    return [l for l in iss.lines[p] if l.style in TEXT_STYLES]


def check_layout(iss: Issue, rep: Report):
    """⑤ 正文版式：字号、行距、每行字数、版心四边，和 rules/typesetting 的数值比"""
    pages = iss.article_pages()
    size_cnt, pitch_cnt, cpl_cnt, x0_cnt, x1_cnt, firsttop = [collections.Counter() for _ in range(6)]
    lowest = 0.0
    for p in pages:
        for c in iss.pdf.pages[p - 1].chars:
            if c["top"] >= HEAD_ZONE and fam(c["fontname"]) == "SongTi" and CJK.match(c["text"]):
                size_cnt[round(c["size"], 1)] += 1
        body = [l for l in iss.lines[p] if l.style == "body"]
        for a, b in zip(body, body[1:]):
            d = round(b.base - a.base, 1)
            if d < 30: pitch_cnt[d] += 1
        for l in body:
            if l.x0 < LEFT + 1 or abs(l.x0 - (LEFT + 2 * BODY_PT)) < 1:   # 段落行（条目另有缩进）
                x0_cnt[round(min(l.x0, LEFT + 2 * BODY_PT) if l.x0 >= LEFT + 2 * BODY_PT - 1 else l.x0, 1)] += 1
                if l.x1 >= RIGHT_GLYPH - 1:
                    cpl_cnt[len([c for c in l.chars if c["text"].strip()])] += 1
                    x1_cnt[round(l.x1, 1)] += 1
        if p not in iss.first_pages:
            ls = [l for l in iss.lines[p] if l.style not in ("runhead",)]
            pg = iss.pdf.pages[p - 1]
            above = [im for im in pg.images if ls and im["top"] < ls[0].top] + \
                    [r for r in pg.rects if ls and r["height"] > 20 and r["width"] < pg.width - 1 and r["top"] < ls[0].top]   # 整页白底矩形不算
            if ls and ls[0].style == "body" and not above:     # 页顶是图或方框的页不算
                firsttop[round(ls[0].base, 1)] += 1
        for l in iss.lines[p]:
            if l.style not in ("runhead",):
                lowest = max(lowest, l.bottom)
    ev, bad = [], []
    tot = sum(size_cnt.values()) or 1
    share = size_cnt[10.5] / tot
    ev.append(f"正文宋体汉字 {tot} 个，10.5pt 占 {share:.1%}；其它字号：{ {k: v for k, v in size_cnt.items() if k != 10.5} }（9pt 是脚注、9.5pt 是方框、10pt 扉页摘要）")
    if share < 0.85: bad.append(f"10.5pt 正文占比 {share:.0%} 偏低")
    pm = pitch_cnt.most_common(1)[0][0] if pitch_cnt else 0
    ev.append(f"正文行距众数 {pm}pt（期望 {PITCH:.1f}，= {pm / BODY_PT:.2f} 倍字号）；分布 {pitch_cnt.most_common(4)}")
    if abs(pm - PITCH) > 0.3: bad.append(f"行距 {pm}pt 不是 {PITCH:.1f}")
    cm = cpl_cnt.most_common(1)[0][0] if cpl_cnt else 0
    ev.append(f"整行字数众数 {cm}（期望 {CPL}）；整行 {sum(cpl_cnt.values())} 行，分布 {cpl_cnt.most_common(4)}")
    if not (26 <= cm <= 33): bad.append(f"每行 {cm} 字超出 26–33")
    elif cm != CPL: bad.append(f"每行 {cm} 字不是 rules/typesetting 的 {CPL}")
    lefts = sorted(x0_cnt.items(), key=lambda kv: -kv[1])
    l0 = min(x0_cnt) if x0_cnt else 0
    ev.append(f"正文左边 x0 = {mm(l0):.2f}mm（期望 {MARGIN['left']}mm）；段首缩进 x0 分布 {[(round(mm(k), 1), v) for k, v in lefts[:3]]}")
    if abs(mm(l0) - MARGIN["left"]) > 0.5: bad.append(f"左边距 {mm(l0):.1f}mm")
    r1 = max(x1_cnt) if x1_cnt else 0
    ev.append(f"整行右边 x1 最大 {mm(r1):.2f}mm（版心右线 {A5[0] - MARGIN['right']}mm；纯汉字整行到 {mm(RIGHT_GLYPH):.1f}mm）")
    if r1 > RIGHT + 1: bad.append(f"右边出版心 {mm(r1 - RIGHT):.1f}mm")
    # 天头：首行基线往上推半行距和字体上伸（Noto Serif SC 上伸 1.151em、下伸 0.286em），得到行框顶
    if firsttop:
        fb = firsttop.most_common(1)[0][0]
        box_top = fb - (PITCH - 1.437 * BODY_PT) / 2 - 1.151 * BODY_PT
        ev.append(f"非首页正文首行基线 {mm(fb):.1f}mm（{len(firsttop)} 种值：{[(round(mm(k), 1), v) for k, v in firsttop.most_common(3)]}），折算行框顶 {mm(box_top):.1f}mm（期望天头 {MARGIN['top']}mm）")
        if abs(mm(box_top) - MARGIN["top"]) > 1.0: bad.append(f"天头 {mm(box_top):.1f}mm")
        if len(firsttop) > 1: bad.append(f"正文页首行位置有 {len(firsttop)} 种")
    ev.append(f"正文页最低字底 {mm(lowest):.1f}mm（地脚线 {A5[1] - MARGIN['bottom']}mm）")
    if lowest > BOT + 1: bad.append(f"文字压到地脚 {mm(lowest - BOT):.1f}mm")
    # 扉页：书影顶 = 天头 − 4.8mm 阴影边
    dv = []
    for p in iss.dividers:
        ims = iss.pdf.pages[p - 1].images
        if ims: dv.append(round(mm(ims[0]["top"]) + 4.8, 1))
    if dv:
        ev.append(f"扉页书影顶 + 4.8mm 阴影边 = {sorted(set(dv))}mm（期望 {MARGIN['top']}mm）")
        if any(abs(v - MARGIN["top"]) > 0.5 for v in dv): bad.append("扉页天头不对")
    rep.add("⑤", "正文版式（字号/行距/每行字数/版心）", "不通过" if bad else "通过",
            "；".join(bad) if bad else f"10.5pt 占 {share:.1%}，行距 {pm}pt，每行 {cm} 字，左 {mm(l0):.1f}mm、天头 {mm(box_top) if firsttop else 0:.1f}mm，全部在容差内", ev)
    # 字号表对照
    found = collections.Counter()
    for p in range(1, iss.n + 1):
        for l in iss.lines[p]:
            if l.style == "runhead":   # 页码和页眉文字同一行，按字分：Medium 8.5 是页码、Regular 7.5 是页眉
                for c in l.chars:
                    if c["text"].strip():
                        found[("pageno" if c["text"].isdigit() else "runhead", fam(c["fontname"]), round(c["size"], 1))] += 1
                continue
            found[(l.style, fam(l.font), l.size)] += 1
    style_of = {"正文": "body", "引文（楷体段）": "quote", "节标题": "h4", "小节标题": "h5", "篇名": "h2", "扉页书名": "bt",
                "扉页引子": "lead", "扉页摘要": "intro", "方框栏目": "box", "方框标题": "boxtitle", "脚注": "fn", "图注": "caption",
                "页眉": "runhead", "页码": "pageno"}
    tev, tbad = [], []
    for name, f, exp, note in SIZE_TABLE:
        st = style_of[name]
        got = sorted({s for (sty, ff, s) in found if sty == st and ff == f})
        exps = exp if isinstance(exp, tuple) else (exp,)
        ok = bool(got) and all(any(abs(g - e) < 0.05 for e in exps) for g in got)
        tev.append(f"{name}：rules/typesetting {f} {exp}pt → 成品 {got or '未出现'}" + (f"（{note}）" if note else "") + ("" if ok else "  ← 不一致"))
        if got and not ok: tbad.append(name)
    unknown = [(k, v) for k, v in found.items() if k[0] in ("other", "song-other", "kai-other")]
    if unknown: tev.append(f"字号表之外的字：{unknown}")
    rep.add("⑤b", "字号表对照（rules/typesetting ↔ 成品）", "警告" if tbad or unknown else "通过",
            ("不一致：" + "、".join(tbad)) if tbad else "成品各处字号都在 rules/typesetting 的表里" + ("；但有表外字号，见证据" if unknown else ""), tev)


def check_headings(iss: Issue, rep: Report):
    """⑥ 背题：页末是标题、下面没正文；标题后同页正文 < 2 行；HTML 里连续标题之间没有正文"""
    fail, warn = [], []
    HEADS = {"h4", "h5", "boxtitle", "bh", "h2"}
    for p in iss.article_pages():
        ls = [l for l in iss.lines[p] if l.style not in ("runhead", "fn", "endmark", "call")]
        if not ls: continue
        if ls[-1].style in HEADS:
            fail.append(f"第 {p} 页末行是标题「{ls[-1].text.strip()[:16]}」，下面没有正文")
        for i, l in enumerate(ls):
            if l.style in ("h4", "h5"):
                after = [x for x in ls[i + 1:] if x.style in TEXT_STYLES | {"box"}]
                if 0 < len(after) < 2:
                    warn.append(f"第 {p} 页标题「{l.text.strip()[:16]}」后本页只有 {len(after)} 行正文")
    if iss.soup:
        for i, art in enumerate(iss.soup.select("section.article"), 1):
            body = art.select_one(".body")
            kids = [c for c in body.children if getattr(c, "name", None)] if body else []
            for a, b in zip(kids, kids[1:]):
                if a.name in ("h4", "h5") and b.name in ("h4", "h5"):
                    fail.append(f"第 {i} 篇 HTML 里标题「{a.get_text()[:16]}」紧接标题「{b.get_text()[:16]}」，中间 0 行正文：parse.py 把短句判成了标题")
    rep.add("⑥", "背题 / 标题后无正文", "不通过" if fail else ("警告" if warn else "通过"),
            f"页末标题 {len([f for f in fail if '页末' in f])} 处，连续标题 {len([f for f in fail if 'HTML' in f])} 处，标题后不足 2 行 {len(warn)} 处",
            fail + warn)


def para_flags(iss: Issue, p: int):
    """给一页里 body/quote/box 行标 段首/段末。返回 [(line, is_start, is_end)]"""
    ls = [l for l in iss.lines[p] if l.style in PARA_STYLES]
    out = []
    for i, l in enumerate(ls):
        g = para_geom(l.style)
        base, ind, right = g
        is_list = l.style == "body" and (any(c["text"] == "■" and c["size"] < 8 for c in l.chars) or l.x0 > ind + 5)
        numbered = l.style == "body" and abs(l.x0 - ind) < 1 and re.match(r"^\d{1,2}．", l.text.strip())
        is_start = (abs(l.x0 - ind) < 1.5 and not is_list) or bool(numbered) or (is_list and any(c["text"] == "■" and c["size"] < 8 for c in l.chars))
        nxt = ls[i + 1] if i + 1 < len(ls) else None
        full = l.x1 >= right - 0.5 * l.size
        if nxt is None:
            is_end = not full
        else:
            ng = para_geom(nxt.style)
            n_is_list = nxt.style == "body" and (any(c["text"] == "■" and c["size"] < 8 for c in nxt.chars) or nxt.x0 > ng[1] + 5)
            n_start = (abs(nxt.x0 - ng[1]) < 1.5 and not n_is_list) or bool(re.match(r"^\d{1,2}．", nxt.text.strip())) or (n_is_list and any(c["text"] == "■" and c["size"] < 8 for c in nxt.chars))
            is_end = n_start or nxt.style != l.style or (nxt.base - l.base) > 1.6 * PITCH or not full and (nxt.x0 > l.x0 + 5)
            if not full and not is_end and is_list and nxt.x0 < l.x0 - 5:
                is_end = True
        out.append((l, is_start, is_end, full, is_list))
    return out


def check_widows(iss: Issue, rep: Report):
    """⑦ 孤行寡行：页首一行是上一段的末行；页末一行是新段的首行且段落没完"""
    fail = []
    pages = iss.article_pages()
    for p in pages:
        flags = para_flags(iss, p)
        if not flags: continue
        if p not in iss.first_pages and iss.roles.get(p - 1) == "article":
            l, st, en, full, _ = flags[0]
            prev = para_flags(iss, p - 1)
            prev_open = bool(prev) and prev[-1][3] and not prev[-1][2]   # 上页末行是整行且段没完
            # 页首第一个块必须是正文行（前面没有标题/图）
            first_block = next((x for x in iss.lines[p] if x.style not in ("runhead", "call")), None)
            if first_block is l and not st and en and prev_open:
                fail.append(f"第 {p} 页页首寡行：「{l.text.strip()[:18]}」是上一页段落的末行")
        if p not in iss.last_pages:
            l, st, en, full, _ = flags[-1]
            last_block = next((x for x in reversed(iss.lines[p]) if x.style not in ("runhead", "fn", "call", "endmark")), None)
            if last_block is l and st and full and not en:
                fail.append(f"第 {p} 页页末孤行：「{l.text.strip()[:18]}」是新段的首行，段落在下一页继续")
    rep.add("⑦", "孤行寡行", "不通过" if fail else "通过",
            f"{len(fail)} 处" if fail else f"{len(pages)} 个正文页，页首无寡行、页末无孤行", fail)


def check_short_last_line(iss: Issue, rep: Report):
    """⑧ 段末单字成行：段末行只有 1 个汉字加标点（2 个汉字只警告）"""
    one, two = [], []
    for p in iss.article_pages():
        for l, st, en, full, is_list in para_flags(iss, p):
            if not en or st: continue      # 单行段不算
            n = len(CJK.findall(l.text))
            latin = re.sub(r"[\s\W]", "", CJK.sub("", l.text))
            if n + (1 if latin else 0) <= 1:
                one.append(f"第 {p} 页「{l.text.strip()}」")
            elif n == 2 and not latin:
                two.append(f"第 {p} 页「{l.text.strip()}」")
    rep.add("⑧", "段末单字成行", "不通过" if one else ("警告" if two else "通过"),
            f"1 字行 {len(one)} 处，2 字行 {len(two)} 处",
            ["1 字：" + x for x in one] + ["2 字：" + x for x in two])


def check_tail_pages(iss: Issue, rep: Report, min_lines: int):
    """⑨ 篇末页过短：正文行（不含 ■、脚注、方框）少于 N 行；顺带报每篇页数和字数"""
    fail, ev, chars_of = [], [], []
    for k, s, e, title in iss.articles:
        body = body_lines_on(iss, e)
        box = [l for l in iss.lines[e] if l.style == "box"]
        lowest = max([l.bottom for l in iss.lines[e] if l.style not in ("runhead", "fn", "endmark", "call")] + [0])
        chars = 0
        for p in range(s, e + 1):
            for l in iss.lines[p]:
                if l.style in TEXT_STYLES | {"box"}:
                    chars += l.ncjk
        chars_of.append(chars)
        line = f"第 {k} 篇「{title or iss.book_title(k)}」第 {s}–{e} 页共 {e - s + 1} 页、正文约 {chars} 字；篇末第 {e} 页正文 {len(body)} 行" + (f"、方框 {len(box)} 行" if box else "") + f"，内容到 {mm(lowest):.0f}mm（版心底 {A5[1] - MARGIN['bottom']}mm）"
        ev.append(line)
        if len(body) < min_lines:
            fail.append(f"第 {e} 页（第 {k} 篇末页）正文只有 {len(body)} 行" + ("，整页只剩方框" if box and not body else ""))
    rep.add("⑨", f"篇末页正文 ≥ {min_lines} 行", "不通过" if fail else "通过",
            "；".join(fail) if fail else f"{len(iss.articles)} 篇篇末页正文都 ≥ {min_lines} 行", fail + ev)
    # 篇幅（rules/editor/selection.md、验收 W9）：篇数 3–6；每篇 5000–12000 汉字；全期 ≤ 96 页。「6–20 页」「长短比」W9 已删
    lens = [(k, e - s + 1, cnt) for (k, s, e, _), cnt in zip(iss.articles, chars_of)]
    if lens:
        w = [f"第 {k} 篇 {v} 页 {c} 字" for k, v, c in lens]
        warn = []
        if not 3 <= len(lens) <= 6: warn.append(f"篇数 {len(lens)}，超出 3–6")
        if iss.n > 96: warn.append(f"全期 {iss.n} 页 > 96")
        for k, v, c in lens:
            if not 5000 <= c <= 12000: warn.append(f"第 {k} 篇正文约 {c} 字，超出 5000–12000 字")
        rep.add("⑨b", "篇幅（篇数 3–6、每篇 5000–12000 字、全期 ≤ 96 页）", "警告" if warn else "通过",
                "；".join(warn) if warn else f"{len(lens)} 篇、{iss.n} 页，每篇字数都在 5000–12000", w)


def check_runheads(iss: Issue, rep: Report):
    """⑩ 页眉页码：正文页有页码、位置按单双页；页眉文字双页「刊名」单页本篇书名；其余页没有页眉"""
    fail, ev = [], []
    name = ""
    if iss.soup:
        m = iss.soup.select_one("section.cover .mast")
        name = m.get_text("", strip=True) if m else ""
    for p in range(1, iss.n + 1):
        hdr = [c for c in iss.pdf.pages[p - 1].chars if c["top"] < HEAD_ZONE]
        role = iss.roles[p]
        if role != "article":
            if hdr:
                fail.append(f"第 {p} 页（{role}）不该有页眉，却有「{''.join(c['text'] for c in hdr)}」")
            continue
        nums = [c for c in hdr if c["text"].isdigit()]
        txt = "".join(c["text"] for c in hdr if not c["text"].isdigit()).strip()
        num = "".join(c["text"] for c in sorted(nums, key=lambda c: c["x0"]))
        if num != str(p):
            fail.append(f"第 {p} 页页码印的是「{num}」")
            continue
        nx0, nx1 = min(c["x0"] for c in nums), max(c["x1"] for c in nums)
        if p % 2 == 0:   # 双页：页码左上、刊名
            if nx0 > 60: fail.append(f"第 {p} 页（双页）页码在右边 x={mm(nx0):.1f}mm")
            if name and txt != name: fail.append(f"第 {p} 页（双页）页眉应是「{name}」，印的是「{txt}」")
        else:            # 单页：页码右上、本篇书名
            if nx1 < iss.pdf.pages[p - 1].width - 60: fail.append(f"第 {p} 页（单页）页码在左边 x={mm(nx0):.1f}mm")
            bt = iss.book_title(iss.article_of[p])
            if bt and txt != bt: fail.append(f"第 {p} 页（单页）页眉应是「{bt}」，印的是「{txt}」")
        edge = min(nx0, iss.pdf.pages[p - 1].width - nx1)
        ev.append((p, round(mm(edge), 1), round(mm(min(c["top"] for c in nums)), 1)))
    edges = sorted({e for _, e, _ in ev}); tops = sorted({t for _, _, t in ev})
    warn = []
    if edges and edges[0] < 7:
        warn.append(f"页码离外切口最近 {edges[0]}mm < 7mm（骑马钉爬移 2mm 后贴边）")
    # 文字安全区：内页所有字离纸边 ≥ 5mm（打印机不可打印区 3–5mm）
    tight = []
    for p in range(2, iss.n):
        pg = iss.pdf.pages[p - 1]
        for c in pg.chars:
            d = min(c["x0"], pg.width - c["x1"], c["top"], pg.height - c["bottom"])
            if d < 5 * MM and c["text"].strip():
                tight.append(f"第 {p} 页「{c['text']}」离纸边 {mm(d):.1f}mm"); break
    if tight: warn.append(f"{len(tight)} 页有字离纸边 < 5mm：" + "；".join(tight[:3]))
    rep.add("⑩", "页眉页码、文字安全区", "不通过" if fail else ("警告" if warn else "通过"),
            (f"{len(fail)} 处不对" if fail else f"{len(ev)} 个正文页页码、位置、页眉文字全对；封面/目录/扉页/封底无页眉") +
            f"；页码离外切口 {edges}mm、离天头 {tops}mm" + ("；" + "；".join(warn) if warn else "；内页文字离纸边都 ≥ 5mm"),
            fail + warn)


def check_toc(iss: Issue, rep: Report):
    """⑪ 目录页码 = 各篇扉页页码；目录篇名 = 正文首页篇名；书签页码同"""
    fail, ev = [], []
    entries = []
    for l in iss.lines[2]:
        m = re.match(r"^(\d{2})(.+?)(\d+)$", l.text.strip())
        if m and fam(l.font) == "HeiTi":
            entries.append((int(m.group(1)), m.group(2).strip(), int(m.group(3))))
    if len(entries) != len(iss.articles):
        fail.append(f"目录 {len(entries)} 条，篇数 {len(iss.articles)}")
    for (i, title, pg), (k, s, e, t) in zip(entries, iss.articles):
        div = iss.dividers[k - 1] if k - 1 < len(iss.dividers) else None
        h2 = next((l.text.strip() for l in iss.lines[s] if l.style == "h2"), "")
        ev.append(f"目录 {i:02d}「{title}」→ 第 {pg} 页；扉页第 {div} 页、正文第 {s} 页篇名「{h2}」")
        if pg != div: fail.append(f"目录第 {i} 条页码 {pg}，扉页在第 {div} 页")
        if title != h2: fail.append(f"目录第 {i} 条篇名「{title}」≠ 正文「{h2}」")
    for d, t, pg in iss.outline:   # 第 1 级书签：「《书名》」要指向扉页，篇名要指向正文首页
        if d == 1 and re.fullmatch(r"《.+》", t.strip()) and pg not in iss.dividers:
            fail.append(f"书签「{t}」指向第 {pg} 页，不是扉页")
        if d == 1 and not re.fullmatch(r"《.+》", t.strip()) and pg not in iss.first_pages:
            fail.append(f"书签「{t}」指向第 {pg} 页，不是正文首页")
    rep.add("⑪", "目录页码与篇名", "不通过" if fail else "通过",
            "；".join(fail) if fail else f"{len(entries)} 条目录页码都等于扉页页码，篇名与正文一致；书签 {len(iss.outline)} 条", ev)


def check_forbidden_words(iss: Issue, rep: Report):
    """⑫ 「第 N 期」不出现在页面、元数据、书签；日期是汉字"""
    fail, ev = [], []
    for i, pg in enumerate(iss.text_pages, 1):
        for m in FORBID_ISSUE.finditer(pg):
            fail.append(f"第 {i} 页正文出现「{m.group()}」")
    title = str((iss.reader.metadata or {}).get("/Title", ""))
    if FORBID_ISSUE.search(title):
        fail.append(f"PDF 元数据 Title=「{title}」")
    for d, t, pg in iss.outline:
        if FORBID_ISSUE.search(t):
            fail.append(f"书签「{t}」")
    meta = dict(iss.reader.metadata or {})
    ev.append(f"元数据：{meta}")
    warn = []
    lack = [k for k in ("/Title", "/Author", "/CreationDate") if not meta.get(k)]
    if lack: warn.append(f"元数据缺 {', '.join(k[1:] for k in lack)}（Title 应为刊名 + 汉字日期、Author 刊名、CreationDate 出刊日）")
    lang = iss.reader.trailer.get("/Root", {}).get("/Lang")
    ev.append(f"/Lang = {lang}")
    if str(lang or "").lower() not in ("zh-cn", "zh-hans", "zh"): warn.append(f"/Lang 是 {lang}，应为 zh-CN")
    date = str(iss.sel.get("issue", {}).get("date", ""))
    if date:
        y, mth = cn_date(date)
        for p, nm in ((1, "封面"), (iss.n, "封底")):
            t = "".join(l.text for l in iss.lines[p])
            if y not in t or mth not in t:
                fail.append(f"{nm}没有汉字日期「{y}{mth}」，印的是「{t}」")
            if re.search(r"\d", t):
                fail.append(f"{nm}出现阿拉伯数字：「{t}」")
            ev.append(f"{nm}文字：「{t}」")
    rep.add("⑫", "禁用字样「第 N 期」、汉字日期、元数据", "不通过" if fail else ("警告" if warn else "通过"),
            "；".join(fail + warn) if fail or warn else "页面、元数据、书签都没有「第 N 期」；封面封底是汉字日期；元数据三项齐", fail + warn + ev)


def check_divider_text(iss: Issue, rep: Report):
    """⑬ 扉页文字：引子 ≤ 600 字、摘要 ≤ 320 字；脚注每篇 3–5 条（只警告）；章节标签体例"""
    fail, warn, ev = [], [], []
    for i, pc in enumerate(iss.sel.get("pieces", []), 1):
        ctx = re.sub(r"\s", "", pc.get("context") or "")
        intro = re.sub(r"\s", "", pc.get("intro") or "")
        notes = pc.get("notes") or []
        ev.append(f"第 {i} 篇 {pc.get('book')}：引子 {len(ctx)} 字、摘要 {len(intro)} 字、脚注 {len(notes)} 条")
        if len(ctx) > 600: fail.append(f"第 {i} 篇引子 {len(ctx)} 字 > 600")
        if len(intro) > 320: fail.append(f"第 {i} 篇摘要 {len(intro)} 字 > 320")
        if not 3 <= len(notes) <= 5: warn.append(f"第 {i} 篇脚注 {len(notes)} 条（宜 3–5）")
    # 扉页要素与章节标签（HTML）
    if iss.soup:
        kinds, no_tr = set(), []
        for i, d in enumerate(iss.soup.select("section.divider"), 1):
            need = {"书影": d.select_one(".top img"), "序号": d.select_one(".num"), "书名": d.select_one(".bt"),
                    "作者年份": d.select_one(".by"), "引子": d.select_one("p.lead"), "本期选读": d.select_one(".lab"),
                    "章节": d.select_one(".pick"), "摘要": d.select_one(".sec:last-child p")}
            miss = [k for k, v in need.items() if v is None]
            if miss: fail.append(f"第 {i} 篇扉页缺 {miss}")
            pick = need["章节"].get_text(strip=True) if need["章节"] else ""
            m = re.match(r"^第\s*(\d+|[一二三四五六七八九十]+)\s*章\s*(.*)$", pick)
            kinds.add("阿拉伯" if m and m.group(1).isdigit() else ("汉字" if m else "不合式"))
            ev.append(f"第 {i} 篇章节标签「{pick}」")
            by = need["作者年份"]
            if by is not None and by.find("br") is not None and "译" not in by.get_text():   # 有原书名 = 译本，by 行该有译者
                no_tr.append(str(i))
        if len(kinds) > 1 or "不合式" in kinds:
            warn.append(f"章节标签体例不一：{sorted(kinds)}（统一成「第 N 章　章名」）")
        if no_tr: warn.append(f"第 {'、'.join(no_tr)} 篇是译本（by 行有原书名）但没写译者")
    rep.add("⑬", "扉页文字长度、脚注条数、扉页要素", "不通过" if fail else ("警告" if warn else "通过"),
            "；".join(fail + warn) if fail or warn else "引子 ≤ 600、摘要 ≤ 320，每篇脚注 3–5 条，扉页 8 项要素齐", ev)


def check_punct(iss: Issue, rep: Report):
    """⑭ 标点：HTML 正文里半角标点紧挨汉字；PDF 行首闭标点、行末开标点；注码在行首；体例混用"""
    fail, warn, ev = [], [], []
    if iss.soup:
        for i, art in enumerate(iss.soup.select("section.article"), 1):
            body = art.select_one(".body")
            txt = body.get_text() if body else ""
            for m in re.finditer(r"[一-鿿][,.;:?!]|[,.;:?!][一-鿿]|[一-鿿]\(|\)[一-鿿]", txt):
                s = max(0, m.start() - 6)
                fail.append(f"第 {i} 篇半角标点挨着汉字：「…{txt[s:m.end() + 6]}…」")
            quotes = (len(re.findall(r"[「」]", txt)), len(re.findall(r"[“”]", txt)))
            dash = (txt.count("——"), txt.count("──"))
            dot = (txt.count("·"), len(re.findall(r"(?<=[一-鿿])．(?=[一-鿿])", txt)))
            ev.append(f"第 {i} 篇：「」{quotes[0]} / “”{quotes[1]}；破折号 —— {dash[0]} / 制表线 ── {dash[1]}；间隔号 · {dot[0]} / 全角句点 ． {dot[1]}")
            if quotes[0] and quotes[1]: warn.append(f"第 {i} 篇两种引号并用（「」{quotes[0]}、“”{quotes[1]}）")
            if dash[1]: warn.append(f"第 {i} 篇破折号用了制表线 ── {dash[1]} 处")
            if dot[1]: warn.append(f"第 {i} 篇译名间隔号用了全角句点 ． {dot[1]} 处")
        whole = "".join(a.get_text() for a in iss.soup.select("section.article"))
        if len(re.findall(r"[「」]", whole)) and len(re.findall(r"[“”]", whole)):
            warn.append("全刊两种引号并存，应只用一种（rules/typesetting 定的是「」）")
    for p in iss.article_pages():
        for l in iss.lines[p]:
            if l.style in ("runhead", "call", "endmark"): continue
            t = l.text.strip()
            if not t: continue
            if t[0] in CLOSE and not t.startswith(("——", "……")):
                fail.append(f"第 {p} 页行首闭标点：「{t[:14]}」")
            if t[-1] in OPEN:
                fail.append(f"第 {p} 页行末开标点：「{t[-14:]}」")
            if t[0] in CIRCLED and l.style != "fn":
                fail.append(f"第 {p} 页注码落在行首：「{t[:14]}」")
    rep.add("⑭", "标点禁则与体例", "不通过" if fail else ("警告" if warn else "通过"),
            f"行首闭标点/行末开标点/行首注码 {len([f for f in fail if '页' in f])} 处，半角标点 {len([f for f in fail if '篇' in f])} 处" + (f"；体例 {len(warn)} 条警告" if warn else ""),
            fail + warn + ev)


def check_cover(iss: Issue, rep: Report):
    """⑮ 封面底色亮度：L* ≥ 75（家用打印机大面积深色易发花）；封面封底同色"""
    field = None
    m = re.search(r"@page cover\s*\{[^}]*background:\s*(#[0-9A-Fa-f]{6})", iss.html)
    if m: field = m.group(1).upper()
    rects = [r for r in iss.pdf.pages[0].rects if r["width"] > 400 and r["height"] > 580]
    pdf_field = None
    if rects and rects[0].get("non_stroking_color"):
        c = rects[0]["non_stroking_color"]
        if isinstance(c, (tuple, list)) and len(c) == 3:
            pdf_field = "#%02X%02X%02X" % tuple(round(v * 255) for v in c)
    field = field or pdf_field
    ev = [f"HTML 底色 {m.group(1) if m else '—'}，PDF 第 1 页满版色块 {pdf_field}"]
    back = [r for r in iss.pdf.pages[-1].rects if r["width"] > 400 and r["height"] > 580]
    back_field = None
    if back and isinstance(back[0].get("non_stroking_color"), (tuple, list)):
        back_field = "#%02X%02X%02X" % tuple(round(v * 255) for v in back[0]["non_stroking_color"])
    fail, warn = [], []
    if not field:
        rep.add("⑮", "封面底色亮度", "警告", "找不到封面底色", ev); return
    L, y, _ = hex_to_lab(field)
    ev.append(f"底色 {field}：L* = {L}，相对亮度 {y:.2f}")
    if L < 75: warn.append(f"底色 {field} L* = {L} < 75，家用打印机大面积深色易发花")
    if back_field and back_field != field: fail.append(f"封底底色 {back_field} ≠ 封面 {field}")
    # 三纸色对底色的对比：黑 ≥ 7:1、米白 ΔL* ≥ 18、第三色对比 ≥ 2.5:1；纸不该透明
    svg = re.search(r'<section class="cover">(.*?)</section>', iss.html, re.S)
    if svg:
        fills = []
        for f in re.findall(r'fill="(#[0-9A-Fa-f]{6})"', svg.group(1)):
            if f.upper() not in fills: fills.append(f.upper())
        ops = {o for o in re.findall(r'fill-opacity="([\d.]+)"', svg.group(1))}
        for f in fills:
            Lf, yf, Cf = hex_to_lab(f)
            ratio = (max(y, yf) + 0.05) / (min(y, yf) + 0.05)
            kind = "深色纸" if Lf < 40 and Cf < 20 else ("浅色纸" if Lf > 85 and Cf < 20 else "彩色纸")
            ev.append(f"纸色 {f}（{kind}）：L* {Lf}、彩度 {Cf}，与底色 ΔL* {abs(L - Lf):.0f}，对比 {ratio:.1f}:1，ΔE {delta_e(f, field)}")
            if kind == "深色纸" and ratio < 7: warn.append(f"深色纸 {f} 对底色对比 {ratio:.1f}:1 < 7")
            if kind == "浅色纸" and abs(L - Lf) < 18: warn.append(f"浅色纸 {f} 与底色 ΔL* 只有 {abs(L - Lf):.0f} < 18，印出来会和底色混在一起")
            if kind == "彩色纸" and delta_e(f, field) < 30:   # 验收 C7：底色对拾页红 ΔE（CIE76）≥ 30
                warn.append(f"彩色纸 {f} 与底色 ΔE 只有 {delta_e(f, field)} < 30，纸和底色分不开")
        if not any(abs(hex_to_lab(f)[0] - hex_to_lab("#B5432B")[0]) < 12 and hex_to_lab(f)[2] > 40 and int(f[1:3], 16) > int(f[5:7], 16) for f in fills):
            warn.append("封面三纸色里没有拾页红（内页 accent #B5432B，封面可用 #D94F2B）：封面和内页没有共同的一色")
        if any(float(o) < 1 for o in ops):
            warn.append(f"封面图案 fill-opacity={sorted(ops)}，纸是半透明的：叠色处多出第 5、6 种颜色，送厂要拍平透明")
        ev.append(f"封面 {len(re.findall('<rect', svg.group(1)))} 张纸、{len(fills)} 种纸色 {fills}")
    # 封面上只许有刊名和日期
    cover_txt = "".join(l.text for l in iss.lines[1]).strip()
    if len(cover_txt) > 10 or iss.pdf.pages[0].images:
        warn.append(f"封面字符 {len(cover_txt)} 个、图 {len(iss.pdf.pages[0].images)} 张（应 ≤ 10 字、0 图）")
    rep.add("⑮", "封面底色亮度与封面封底", "不通过" if fail else ("警告" if warn else "通过"),
            "；".join(fail + warn) if fail or warn else f"底色 {field} L* = {L} ≥ 75；封底同色；封面只有 {len(cover_txt)} 个字、0 张图", ev)


def check_cover_bitmap(iss: Issue, rep: Report):
    """⑮b 封面封底摊平成一把扇子：书脊两侧 2mm 像素列颜色序列一致率 ≥ 95%（只对 fan 图案；stack / scatter / svg 的封底是镜像，不要求接续）；封面墨量（家用打印）"""
    import tempfile
    from PIL import Image
    fail, warn, ev = [], [], []
    motif = "fan"
    if (iss.dir / "cover.json").exists():
        try:
            motif = json.loads((iss.dir / "cover.json").read_text(encoding="utf-8")).get("motif") or "fan"
        except Exception:
            pass
    with tempfile.TemporaryDirectory() as td:
        for tag, pg in (("c", 1), ("b", iss.n)):
            subprocess.run(["pdftoppm", "-r", "40", "-f", str(pg), "-l", str(pg), "-png", str(iss.pdf_path), f"{td}/{tag}"], capture_output=True)
        try:
            a = Image.open(next(Path(td).glob("c-*.png"))).convert("RGB")
            b = Image.open(next(Path(td).glob("b-*.png"))).convert("RGB")
        except StopIteration:
            rep.add("⑮b", "封面封底拼合与墨量", "警告", "pdftoppm 没渲染出封面", []); return
    W, H = a.size
    px_mm = W / A5[0]
    n = max(1, int(2 * px_mm))
    # 封面是右页、书脊在左；封底是左页、书脊在右。各取靠书脊 2mm 的列，逐像素比
    pa = [a.getpixel((x, y)) for y in range(H) for x in range(n)]
    pb = [b.getpixel((W - 1 - x, y)) for y in range(H) for x in range(n)]
    same = sum(1 for u, v in zip(pa, pb) if max(abs(i - j) for i, j in zip(u, v)) < 24) / len(pa)
    ev.append(f"书脊两侧各 2mm 的像素列：封面左缘与封底右缘颜色一致率 {same:.0%}（40dpi 渲染）")
    if same < 0.95 and motif == "fan":
        fail.append(f"书脊两侧颜色序列一致率 {same:.0%} < 95%：摊平后前后封面在书脊处接不上，不是一整把扇子")
    elif motif != "fan":
        ev.append(f"图案是 {motif}，封底是封面的镜像，不要求书脊处接续")
    # 墨量：简单 RGB→CMYK 取 (C+M+Y+K)/4 的均值；深色面积 = 亮度 < 25% 的像素占比
    def cmyk(r, g, b):
        k = 1 - max(r, g, b) / 255
        if k >= 1: return 1.0
        c, m, y = ((1 - r / 255 - k) / (1 - k), (1 - g / 255 - k) / (1 - k), (1 - b / 255 - k) / (1 - k))
        return (c + m + y + k) / 4
    small = a.resize((W // 2, H // 2))
    data = list(small.get_flattened_data()) if hasattr(small, "get_flattened_data") else list(small.getdata())
    ink = sum(cmyk(*q) for q in data) / len(data)
    dark = sum(1 for q in data if 0.299 * q[0] + 0.587 * q[1] + 0.114 * q[2] < 64) / len(data)
    ev.append(f"封面平均墨量约 {ink:.0%}（(C+M+Y+K)/4 均值），亮度 < 25% 的深色面积 {dark:.0%}")
    if ink > 0.30: warn.append(f"封面平均墨量 {ink:.0%} > 30%，80g 纸喷墨会卷、透到目录页；封面用 ≥ 120g 纸")
    if dark > 0.25: warn.append(f"封面深色面积 {dark:.0%} > 25%")
    rep.add("⑮b", "封面封底拼合与墨量", "不通过" if fail else ("警告" if warn else "通过"),
            "；".join(fail + warn) if fail or warn else (f"书脊处颜色一致率 {same:.0%}，摊平是一把扇子；墨量 {ink:.0%}" if motif == "fan" else f"图案 {motif}；墨量 {ink:.0%}"), fail + warn + ev)


# ---- 以下是硬指标里能顺手量的几条（审稿时发现的硬伤）

def check_footnotes(iss: Issue, rep: Report):
    """⑯ 脚注：注文与注码同页；每篇从 ① 递增；注线 = 版心 1/4 左齐；注文字号"""
    fail, ev = [], []
    per_art = collections.defaultdict(list)
    for p in iss.article_pages():
        calls = [c["text"] for l in iss.lines[p] for c in l.chars
                 if c["text"] in CIRCLED and c["size"] <= FN_CALL_MAX and c["top"] >= HEAD_ZONE]
        notes = [l.text.strip()[0] for l in iss.lines[p] if l.style == "fn" and l.text.strip() and l.text.strip()[0] in CIRCLED]
        per_art[iss.article_of[p]].extend(calls)
        for c in calls:
            if c not in notes:
                fail.append(f"第 {p} 页注码 {c} 的注文不在本页" + (f"（在第 {p + 1} 页）" if any(l.style == 'fn' and l.text.strip().startswith(c) for l in iss.lines.get(p + 1, [])) else ""))
        for c in notes:   # 注文在本页、注码在上页的，上一页已经报过，不重复
            prev_calls = [cc["text"] for l in iss.lines.get(p - 1, []) for cc in l.chars if cc["text"] in CIRCLED and cc["size"] <= FN_CALL_MAX and cc["top"] >= HEAD_ZONE]
            if c not in calls and c not in prev_calls:
                fail.append(f"第 {p} 页注文 {c} 在本页，注码不在本页也不在上页")
        rules = [r for r in iss.pdf.pages[p - 1].rects if r["height"] < 1 and r["width"] > 50 and abs(r["x0"] - LEFT) < 1]
        if notes:
            if not rules: fail.append(f"第 {p} 页有注文没有注线")
            else:
                w = mm(rules[0]["width"])
                if abs(w - mm(RIGHT - LEFT) / 4) > 1: fail.append(f"第 {p} 页注线 {w:.1f}mm，应为版心 1/4 = {mm(RIGHT - LEFT) / 4:.1f}mm")
        if calls or notes:
            ev.append(f"第 {p} 页注码 {''.join(calls) or '—'}，注文 {''.join(notes) or '—'}" + (f"，注线 {mm(rules[0]['width']):.0f}mm" if rules else ""))
    for k, seq in sorted(per_art.items()):
        exp = CIRCLED[:len(seq)]
        if "".join(seq) != exp:
            fail.append(f"第 {k} 篇注码顺序 {''.join(seq)}，应为 {exp}")
    total = sum(len(v) for v in per_art.values())
    rep.add("⑯", "脚注同页、编号、注线", "不通过" if fail else "通过",
            f"{total} 条脚注，{len(fail)} 处问题" if fail else f"{total} 条脚注全部与注码同页，每篇从 ① 递增，注线 {mm(RIGHT - LEFT) / 4:.0f}mm 左齐", fail + ev)


def check_bottom_gap(iss: Issue, rep: Report):
    """⑰ 非篇末页页底空白：最后一个文字/图/框到版心底线（有脚注时到注线上 4mm）≤ 2.5 行"""
    fail, warn, ev = [], [], []
    for p in iss.article_pages():
        if p in iss.last_pages: continue
        page = iss.pdf.pages[p - 1]
        content = [l.bottom for l in iss.lines[p] if l.style not in ("runhead", "fn", "call")]
        content += [im["bottom"] for im in page.images]
        content += [r["bottom"] for r in page.rects if r["height"] > 20 and r["width"] < page.width - 1]
        if not content: continue
        low = max(content)
        rule = [r for r in page.rects if r["height"] < 1 and r["width"] > 50 and abs(r["x0"] - LEFT) < 1 and r["top"] > 300]
        limit = (rule[0]["top"] - 4 * MM) if rule else BOT
        gap = limit - low
        if gap > 2.5 * PITCH:
            nxt = iss.pdf.pages[p]
            why = "下一页开头是图" if nxt.images and nxt.images[0]["top"] < 80 else ("下一页开头是方框" if any(r["height"] > 20 and r["top"] < 80 and r["width"] < nxt.width - 1 for r in nxt.rects) else "")
            line = f"第 {p} 页页底空 {mm(gap):.0f}mm ≈ {gap / PITCH:.1f} 行"
            if why:   # 图/方框整块挪走、正文不回填：不通过
                fail.append(line + f"（{why}，整块挪走、正文不回填）")
            elif gap > 3.5 * PITCH:
                fail.append(line)
            else:     # 2.5–3.5 行、下一页是整段或标题：orphans/widows 2 把 3 行的段整段推走，只警告
                warn.append(line + "（下一页开头是整段或标题，孤行寡行规则推走的）")
        ev.append((p, round(mm(gap), 1)))
    rep.add("⑰", "非篇末页页底空白 ≤ 2.5 行", "不通过" if fail else ("警告" if warn else "通过"),
            (f"{len(fail)} 页不齐底" + (f"，另 {len(warn)} 页 2.5–3.5 行" if warn else "")) if fail or warn else f"{len(ev)} 个非篇末页页底空白都 ≤ 2.5 行（最大 {max(g for _, g in ev) if ev else 0}mm）", fail + warn)


def check_gaps(iss: Issue, rep: Report):
    """⑱ 行内空隙：同一行相邻两个字之间的空隙 > 0.5 字（两端对齐把真空格拉宽了）"""
    fail = []
    for p in iss.article_pages():
        for l in iss.lines[p]:
            if l.style not in ("body", "quote", "box", "fn", "epi"): continue
            cs = [c for c in l.chars if (c["text"].strip() or c["text"] == "　") and c["text"] != "■"]
            for a, b in zip(cs, cs[1:]):
                if "　" in (a["text"], b["text"]):   # 全角空（❶　明确愿望、图 5-1　标题）是有意排的，不算
                    continue
                g = b["x0"] - a["x1"]
                if g > 0.5 * l.size and not (a["text"] in CIRCLED and l.style == "fn"):
                    fail.append(f"第 {p} 页「{a['text']}」和「{b['text']}」之间空 {g:.1f}pt（{g / l.size:.2f} 字）：…{l.text[max(0, l.text.find(a['text']) - 5):l.text.find(a['text']) + 8]}…")
                    break
    rep.add("⑱", "行内空隙 ≤ 0.5 字", "不通过" if fail else "通过",
            f"{len(fail)} 行有被拉宽的空格" if fail else "没有一行的字间空隙超过 0.5 字", fail)


def check_ragged(iss: Issue, rep: Report):
    """⑲ 右边缘齐：非段末正文行右端短于整行 ≥ 0.5 字的比例 ≤ 2%，短 ≥ 1 字的 0 行"""
    short_half, short_one, total = [], [], 0
    for p in iss.article_pages():
        for l, st, en, full, is_list in para_flags(iss, p):
            if l.style != "body" or en or is_list: continue
            total += 1
            d = RIGHT_GLYPH - l.x1
            if d >= BODY_PT - 0.5: short_one.append(f"第 {p} 页短 {d / BODY_PT:.1f} 字：「…{l.text[-10:]}」")
            elif d >= 0.5 * BODY_PT: short_half.append(p)
    n = len(short_half) + len(short_one)
    ratio = n / total if total else 0
    st = "不通过" if short_one or ratio > 0.02 else "通过"
    rep.add("⑲", "正文右边缘齐", st,
            f"{total} 行非段末正文行，右端短 ≥ 0.5 字的 {n} 行（{ratio:.1%}），短 ≥ 1 字的 {len(short_one)} 行",
            short_one[:30] + ([f"短 0.5–1 字的在第 {sorted(set(short_half))} 页"] if short_half else []))


def check_red(iss: Issue, rep: Report):
    """⑳ 红只出现在结构位：10.5pt 正文红字 0；每页红字符 ≤ 12"""
    fail, warn = [], []
    for p in range(1, iss.n + 1):
        reds = [c for c in iss.pdf.pages[p - 1].chars if rgb_close(c.get("non_stroking_color"), ACCENT)]
        if not reds: continue
        if any(round(c["size"], 1) == 10.5 for c in reds):
            fail.append(f"第 {p} 页有 10.5pt 的红字：「{''.join(c['text'] for c in reds if round(c['size'], 1) == 10.5)[:10]}」")
        if len(reds) > 12:
            warn.append(f"第 {p} 页红字符 {len(reds)} 个")
    rep.add("⑳", "红字只在结构位", "不通过" if fail else ("警告" if warn else "通过"),
            "；".join(fail + warn) if fail or warn else "正文无红字，每页红字符 ≤ 12", fail + warn)
    # 内页文字颜色集合：只许墨 #1E1D1A、灰 #6F685D、红 #B5432B（封面封底的字另算）
    cols = collections.Counter()
    for p in range(2, iss.n):
        for c in iss.pdf.pages[p - 1].chars:
            col = c.get("non_stroking_color")
            cols["#%02X%02X%02X" % tuple(round(v * 255) for v in col) if isinstance(col, (tuple, list)) and len(col) == 3 else str(col)] += 1
    allowed = {"#1E1D1A", "#6F685D", "#B5432B"}
    extra = {k: v for k, v in cols.items() if k not in allowed}
    ev = [f"{k}：{v} 字" for k, v in cols.most_common()]
    rep.add("⑳b", "内页文字颜色集合", "警告" if extra else "通过",
            (f"墨/灰/红之外还有 {len(extra)} 种：" + "、".join(f"{k}（{v} 字）" for k, v in extra.items()) + "，家用打印机分不出、徒增不一致") if extra else "内页文字只有墨、灰、红三色", ev)


def check_charset(iss: Issue, rep: Report):
    """㉑ 字符规范：破折号不用框线字符 U+2500；年份零用 〇 不用 ○"""
    warn = []
    box_pages = sorted({i for i, pg in enumerate(iss.text_pages, 1) if re.search(r"[─-╿]", pg)})
    if box_pages: warn.append(f"破折号用了框线字符 U+2500（──），在第 {box_pages} 页；应为 ——（U+2014×2）")
    circ_pages = sorted({i for i, pg in enumerate(iss.text_pages, 1) if re.search(r"[一二三四五六七八九]○|○[一二三四五六七八九年]", pg)})
    if circ_pages: warn.append(f"年份里的零用了 ○（U+25CB），在第 {circ_pages} 页；应为 〇（U+3007）")
    rep.add("㉑", "字符规范（破折号、数字零）", "警告" if warn else "通过", "；".join(warn) if warn else "没有框线字符，年份零都是 〇", warn)


def check_endmarks(iss: Issue, rep: Report):
    """㉒ 篇末 ■ 右齐；节选短线只在节选篇"""
    fail, ev = [], []
    for k, s, e, _ in iss.articles:
        em = [l for l in iss.lines[e] if l.style == "endmark"]
        if not em: fail.append(f"第 {k} 篇篇末第 {e} 页没有 ■")
        elif abs(em[0].x1 - RIGHT) > 1: fail.append(f"第 {k} 篇 ■ 没有右齐（x1 = {mm(em[0].x1):.1f}mm）")
        cut = [r for r in iss.pdf.pages[e - 1].rects if r["height"] < 1 and abs(r["width"] - 12 * MM) < 1]
        pieces = iss.sel.get("pieces") or []
        exc = bool(pieces[k - 1].get("excerpt")) if k - 1 < len(pieces) else None   # selection 里没有这篇就不比
        ev.append(f"第 {k} 篇篇末第 {e} 页：■ {'有' if em else '无'}，短线 {len(cut)} 条，selection 里 excerpt {'有' if exc else '无'}")
        if exc is not None and bool(cut) != exc:
            fail.append(f"第 {k} 篇节选短线{'有' if cut else '无'}，与 selection 的 excerpt {'有' if exc else '无'}不符")
    rep.add("㉒", "篇末 ■ 与节选短线", "不通过" if fail else "通过", "；".join(fail) if fail else f"{len(iss.articles)} 篇都以 ■ 右齐收尾，短线只在节选篇", fail + ev)


def check_figures(iss: Issue, rep: Report):
    """㉔ 图注与图随文走：有编号的图要有模板排的图注；图在引用段的同页或下一页，不在引用之前"""
    if not iss.soup:
        rep.add("㉔", "图注与图随文走", "警告", "没有 HTML，跳过", []); return
    fail, warn, ev = [], [], []
    norm = lambda s: re.sub(r"\s", "", s)
    pages_norm = [norm(t) for t in iss.text_pages]
    # 正文里的位图按出现顺序和 HTML 的 figure 一一对应
    pdf_figs = [(p, im) for p in iss.article_pages() for im in iss.pdf.pages[p - 1].images]
    figs = iss.soup.select("section.article figure")
    if len(figs) != len(pdf_figs):
        warn.append(f"HTML 有 {len(figs)} 个 figure，PDF 正文页有 {len(pdf_figs)} 张位图，对不上，图随文走只按能对上的部分查")
    for i, fg in enumerate(figs):
        if i >= len(pdf_figs): break
        p, im = pdf_figs[i]
        cap = fg.find("figcaption")
        cap_txt = norm(cap.get_text()) if cap else ""
        # 引用段：figure 前最近的一个文字块
        prev = fg.find_previous_sibling(lambda t: t.name in ("p", "h4", "h5", "ul", "aside", "div") and t.get_text(strip=True))
        if prev is None and fg.parent.name == "aside":
            prev = fg.parent.find_previous_sibling(lambda t: t.name in ("p", "h4", "h5", "ul") and t.get_text(strip=True))
        ref_page = None
        if prev is not None:
            key = norm(prev.get_text())[-16:]   # 用段尾 16 字找页（段首可能在上一页）
            ref_page = next((k + 1 for k, t in enumerate(pages_norm) if key and key in t), None)
        num = re.search(r"图\s*([\d.．\-–]+)", cap_txt or (norm(prev.get_text()) if prev is not None else ""))
        line = f"第 {p} 页图{'「' + cap_txt[:14] + '」' if cap_txt else '（无图注）'}：引用段在第 {ref_page or '?'} 页"
        if cap_txt and len(cap_txt) > 90: warn.append(f"第 {p} 页图注 {len(cap_txt)} 字 > 90")
        if not cap_txt and prev is not None and re.search(r"图\s*\d", prev.get_text()):
            fail.append(f"第 {p} 页前文提到「{re.search(r'图\s*[\d.．\-–]+', prev.get_text()).group()}」，图却没有模板排的图注（图注大概烧在位图里）")
        if ref_page is not None:
            if p < ref_page: fail.append(f"第 {p} 页图排在引用段（第 {ref_page} 页）之前")
            elif p - ref_page > 1: fail.append(f"第 {p} 页图离引用段（第 {ref_page} 页）超过 1 页")
        ev.append(line)
    nocap = [p for (p, _), fg in zip(pdf_figs, figs) if not fg.find("figcaption")]
    ev.append(f"无图注的图 {len(nocap)} 张（第 {nocap} 页）：图里有没有图号、繁体、水印要靠看图")
    rep.add("㉔", "图注与图随文走", "不通过" if fail else ("警告" if warn else "通过"),
            "；".join(fail + warn) if fail or warn else f"{len(figs)} 张图都在引用段同页或下一页；有编号的图都有图注", fail + warn + ev)


def check_sequence(iss: Issue, rep: Report):
    """㉓ 页面顺序：封面→目录→（扉页→正文）×N→笔记页→封底；笔记页 ≤ 3"""
    seq = [iss.roles[p] for p in range(1, iss.n + 1)]
    fail = []
    exp = ["cover", "contents"]
    for _ in iss.articles:
        exp += ["divider", "article*"]
    pat = "^cover contents (divider article+ )+(notes ){0,3}back$"
    s = " ".join(seq) + ""
    s = re.sub(r"(article )+", "article+ ", s + " ")
    s = s.strip()
    if not re.match(pat.replace("article+", r"article\+"), s):
        fail.append(f"页型序列：{s}")
    if "other" in seq: fail.append(f"有认不出角色的页：{[p for p in range(1, iss.n + 1) if iss.roles[p] == 'other']}")
    if len(iss.note_pages) > 3: fail.append(f"笔记页 {len(iss.note_pages)} 页 > 3")
    rep.add("㉓", "页面顺序", "不通过" if fail else "通过", "；".join(fail) if fail else f"封面→目录→（扉页→正文）×{len(iss.articles)}→笔记页 {len(iss.note_pages)}→封底", fail)


# ---------------------------------------------------------------- 报告

def write_report(iss: Issue, rep: Report, out: Path, args):
    cnt = collections.Counter(s for _, _, s, _, _ in rep.items)
    L = [f"# 拾页 {iss.sel.get('issue', {}).get('date', '')} 硬指标检查报告", "",
         f"- 文件：`{iss.pdf_path.name}`（{iss.n} 页）、`{iss.html_path.name}`、`selection.json`",
         f"- 检查时间：{datetime.now():%Y-%m-%d %H:%M}；脚本 `check.py`，参数 --tail-lines {args.tail_lines}" + ("，--booklet" if args.booklet else ""),
         f"- 结果：**不通过 {cnt['不通过']} 项、警告 {cnt['警告']} 项、通过 {cnt['通过']} 项**（共 {len(rep.items)} 项）",
         f"- 页面角色：封面第 1 页、目录第 2 页、扉页第 {iss.dividers} 页、正文 {[(s, e) for _, s, e, _ in iss.articles]}、笔记页 {iss.note_pages or '无'}、封底第 {iss.n} 页",
         "", "## 总表", "", "| # | 检查 | 结果 | 要点 |", "|---|---|---|---|"]
    for no, name, st, summ, _ in rep.items:
        mark = {"通过": "通过", "不通过": "**不通过**", "警告": "警告"}[st]
        L.append(f"| {no} | {name} | {mark} | {summ} |")
    L += ["", "## 各项证据", ""]
    for no, name, st, summ, ev in rep.items:
        L += [f"### {no} {name} — {st}", "", summ, ""]
        for e in ev:
            L.append(f"- {e}" if isinstance(e, str) else f"- {e}")
        L.append("")
    if rep.notes:
        L += ["## 说明", ""] + [f"- {n}" for n in rep.notes]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("issue_dir")
    ap.add_argument("--out", help="报告路径（默认 <期目录>/检查报告.md）")
    ap.add_argument("--tail-lines", type=int, default=5, help="篇末页正文最少行数（默认 5）")
    ap.add_argument("--booklet", action="store_true", help="骑马钉：页数不是 4 的倍数算不通过")
    args = ap.parse_args()
    iss = Issue(Path(args.issue_dir))
    rep = Report()
    check_pages(iss, rep, args.booklet)
    check_fonts(iss, rep)
    check_missing_glyphs(iss, rep)
    check_images(iss, rep)
    check_layout(iss, rep)
    check_headings(iss, rep)
    check_widows(iss, rep)
    check_short_last_line(iss, rep)
    check_tail_pages(iss, rep, args.tail_lines)
    check_runheads(iss, rep)
    check_toc(iss, rep)
    check_forbidden_words(iss, rep)
    check_divider_text(iss, rep)
    check_punct(iss, rep)
    check_cover(iss, rep)
    check_cover_bitmap(iss, rep)
    check_footnotes(iss, rep)
    check_bottom_gap(iss, rep)
    check_gaps(iss, rep)
    check_ragged(iss, rep)
    check_red(iss, rep)
    check_charset(iss, rep)
    check_endmarks(iss, rep)
    check_sequence(iss, rep)
    check_figures(iss, rep)
    rep.notes += [
        "「不通过」是量出来的数字过了线，「警告」是过线但不一定要改（或规则本身是「宜」），「通过」是全部在线内。退出码：有不通过则 1。",
        "坐标全从 PDF 的字符框量（pdfplumber），版心按 rules/typesetting 的 16/20/18mm；行距、每行字数取众数；页码按 PDF 页码（封面是第 1 页）。",
        "脚本量不到的，要看图或翻纸：图里的字是不是繁体、竖排，图上有没有水印、印章、折痕，书影是不是正文所据版本；封面缩略后认不认得出；跨页灰度匀不匀；题记判没判错。",
        "上下标、着重号在成品 HTML 里已经没有标签（parse 阶段丢了），脚本查不出「丢了多少」，只能在翻译源文件阶段查。",
        "rules/typesetting 与模板不一致的三处（脚注 8.5/9pt、页码反白/普通、扉页书名 20/20–22pt）按模板数值检查，见 ⑤b 的备注。",
    ]
    out = Path(args.out) if args.out else iss.dir / "检查报告.md"
    write_report(iss, rep, out, args)
    cnt = collections.Counter(s for _, _, s, _, _ in rep.items)
    print(f"{iss.pdf_path.name}：{iss.n} 页；不通过 {cnt['不通过']}、警告 {cnt['警告']}、通过 {cnt['通过']}")
    for no, name, st, summ, _ in rep.items:
        print(f"[{st}] {no} {name}：{summ}")
    print(f"报告：{out}")
    sys.exit(1 if rep.failed else 0)


if __name__ == "__main__":
    main()
