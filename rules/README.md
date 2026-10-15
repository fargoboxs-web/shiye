# 规则索引

一个话题一个文件。AI 只读当前步骤需要的那一个；人要改哪条规则，就改哪个文件，不用动代码。

| 步骤 | 读哪个文件 |
|---|---|
| 1 收笔记 | `../interfaces/inbox.md` |
| 2 读者画像 | `editor/reader-profile.md` |
| 3 书单 | `editor/booklist.md` |
| 4 取书 | `../interfaces/book-source.md` |
| 6 选篇与写作 | `editor/selection.md`、`editor/context.md`、`editor/summary.md`、`editor/footnotes.md`；写任何字之前先读 `editor/language.md` |
| 7 翻译 | `editor/translation.md` |
| 8 刊名与封面 | `editor/title.md`、`editor/cover.md` |
| 9 排版 | `typesetting/`（代码已实现，改版式时才读） |
| 10 质检 | `quality/验收.md` |

三层：**固定**（代码和模板保证，每期一样）、**约束**（规则给边界，AI 在边界里判断）、**自由**（AI 全权，规则只讲风格）。哪条属于哪层见 `quality/验收.md` 第一节。

- `editor/` 是判断题，写的是风格和边界，不是模板。相信 AI。
- `typesetting/` 是说明和依据，数值已在 `templates/issue.html` 和 `zine/render.py` 里实现。改版式先改这里，再改代码，不在成品上破例。
- `quality/验收.md` 既是设计原则也是验收标准，`zine/check.py` 按它的 2.1 节逐条查。
