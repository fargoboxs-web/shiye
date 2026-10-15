# 拾页 shiye

把一个人的笔记和收藏做成一本可打印的 A5 杂志 PDF。这是一个 Claude Code skill：AI 做判断（读懂这个人、找出书、选篇、写引子摘要脚注、定刊名封面），脚本做确定性的事（拆书、排版、质检）。

- 入口：`SKILL.md`（11 步，每步指向一个规则文件）
- 规则：`rules/`（编辑判断 `editor/`、版式 `typesetting/`、验收 `quality/`），一个话题一个文件
- 接口：`interfaces/`（收件箱 `inbox/`、笔记来源 MCP、书库 MCP，以及中间产物的 JSON Schema）
- 代码：`run.py` + `zine/`（拆书、排版、质检、收件箱）、`templates/issue.html`
- 适配器（可选）：`adapters/`（Get笔记 批量存入 inbox 的脚本；小红书收藏夹的导出步骤）
- 示例：`examples/2026-10-13/`（一期的 selection.json、cover.json、检查报告；读者画像是匿名样例）

## 安装

```bash
python3 -m pip install -r requirements.txt
bash scripts/fetch-fonts.sh        # 三种开源字体（Noto Serif SC、Noto Sans SC、霞鹜文楷）下载到 fonts/
```

## 跑一期

在 Claude Code 里打开这个仓库，把读者的笔记放进 `inbox/`（有电子书放进 `books/`），说"做一期杂志"。AI 会按 `SKILL.md` 走完全程。手动也行：

```bash
python3 run.py ingest inbox/                       # 收件箱 → work/notes.jsonl、work/notes-digest.md
#   AI：写 reader.md、books.yaml
python3 run.py prepare books.yaml --issue issues/<日期>   # 拿书、拆章节 → candidates.md；缺书写进 缺书.md
#   AI：读候选，用 run.py show 看全文，写 issues/<日期>/selection.json
python3 run.py translate issues/<日期>            # 列出非中文的篇，AI 翻译
#   AI：写 issues/<日期>/cover.json（刊名两个字、配色、图案）
python3 run.py render issues/<日期>               # → <刊名>-<日期>.pdf
python3 run.py check issues/<日期>                # 硬指标 → 检查报告.md
```

## 要改什么，改哪里

| 想改 | 文件 |
|---|---|
| 选篇、引子、摘要、脚注的写法 | `rules/editor/` 对应文件 |
| 刊名、封面的风格 | `rules/editor/title.md`、`cover.md` |
| 字体、字号、页面、脚注版式、封面版式 | `rules/typesetting/` 先改说明，再改 `templates/issue.html`、`zine/render.py` |
| 验收什么、不过怎么办 | `rules/quality/验收.md`，脚本 `zine/check.py` |
| 这一期的刊名、配色 | `issues/<日期>/cover.json` |
| 这一期选了什么 | `issues/<日期>/selection.json` |

## 书从哪里来

skill 不自带任何书源。书来自读者自己的电子书（放 `books/`）、公版书（`books.yaml` 写 `gutenberg_id` 或 `url`），或读者自己接的书库 MCP（接口见 `interfaces/book-source.md`）。来源与 `rights` 印在封底。杂志仅供读者个人阅读。

## 不进仓库的东西

`inbox/`、`work/`、`issues/`、`books/`、`reader.md`、`fonts/`、`*.pdf`、`.env`——笔记是隐私，书有版权，字体另下，密钥只在环境变量里。见 `.gitignore`。
