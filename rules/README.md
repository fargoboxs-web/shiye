# 规则索引

一个话题一个文件。做到哪一步，只读那一步点名的文件；人要改哪条规则，就改哪个文件，不用动代码。步骤见 `../skills/shiye/SKILL.md`。

| 步骤 | 读哪个文件 |
|---|---|
| 1 拿材料 | `editor/reader-profile.md`；笔记的格式见 `../interfaces/inbox.md` |
| 2 出方案 | `editor/booklist.md`、`../interfaces/book-source.md`、`editor/selection.md`、`editor/language.md`、`editor/context.md` |
| 3 做书 | `editor/summary.md`、`editor/footnotes.md`、`editor/translation.md`、`editor/title.md`、`editor/cover.md` |
| 4 质检和交付 | `quality/验收.md`、`typesetting/printing.md` |

- `editor/` 是判断题，写的是风格和边界，不是模板。
- `typesetting/` 是版式的说明和依据，数值已在 `templates/issue.html` 和 `zine/render.py` 里实现，平时不用读。改版式先改这里，再改代码，不在成品上破例。
- `quality/验收.md` 是验收标准，`zine/check.py` 按它逐条查。
