# 收件箱 inbox/ 与 notes.jsonl

## inbox/：软约定

把手头有的东西放进去，格式不限：`.md` `.txt` `.json` `.jsonl` `.csv` `.html`，一个文件一条或一个文件很多条都行；子文件夹也行（小红书下载工具每篇一个文件夹，文件夹里的正文和图片算一条）。文件名里有日期（`2026-10-01`、`20261001`）就当作时间，没有也行。图片放旁边，同名或同文件夹就配对。

AI 可以直接读 `inbox/`。`python3 run.py ingest inbox/` 是帮手：把能认出来的都归成 `work/notes.jsonl`，并写一份 `work/notes-digest.md`（每条一两行）给 AI 扫；认不出来的文件列出来，AI 自己看。笔记是隐私，`inbox/` 和 `work/` 都不进仓库。

## notes.jsonl：唯一硬格式

一行一条 JSON，后面所有步骤都读它：

```json
{"id": "xhs:6512ab", "source": "xiaohongshu", "kind": "post", "time": "2026-10-08T22:14:00+08:00",
 "title": "这本书改变了我对时间的看法", "url": "https://www.xiaohongshu.com/explore/…",
 "text": "正文或字幕全文", "images": ["inbox/xiaohongshu/6512ab/1.jpg"], "tags": ["读书"], "note": "收藏时自己写的一句"}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 稳定、唯一；来源前缀加原始 id（`getnote:123`、`xhs:6512ab`、`file:<哈希>`） |
| `source` | 是 | `getnote`、`xiaohongshu`、`notion`、`file`…… 任意字符串 |
| `text` | 是 | 正文、字幕或原文，纯文本或 Markdown |
| `kind` | 否 | `post`、`video`、`note`、`article`、`book_highlight`、`other` |
| `time` | 否 | ISO 8601；没有就空 |
| `title`、`url`、`images`、`tags`、`note` | 否 | 有就带上，引子要回原文看、封底要追溯来源都靠 `url` |

JSON Schema：`schemas/notes.schema.json`。`ingest` 认的别名：`content`/`body`/`desc` → `text`，`created_at`/`saved_at`/`date` → `time`，`link` → `url`，`my_note`/`comment` → `note`。
