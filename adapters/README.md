# 适配器

主线只认两样东西：`inbox/` 里的笔记，`books/` 里的书。适配器是往这两个文件夹里送东西的插件，一个目录一个，互不依赖主线，主线也不依赖它们。

```bash
python3 run.py adapters      # 列出现在装了哪些、哪些能用、缺什么
```

| 目录 | 送什么 | 需要 |
|---|---|---|
| `getnote/` | Get笔记 最近的笔记和收藏 → `inbox/` | `GETNOTE_API_KEY`、`GETNOTE_CLIENT_ID` |
| `xiaohongshu/` | 一个人公开的小红书收藏 → `inbox/` | `TIKHUB_API_KEY`，加上 `getnote/`；或者只要 `APIFY_TOKEN` |
| `books-mcp/` | 按书名取整本书 → `books/` | agent 接上书库 MCP |

## 可拔插是什么意思

- **不用的不用管。** 缺凭证的适配器只会在 `run.py adapters` 里显示「没接」，流程不报错。
- **拔掉：** 删掉那个目录。
- **插一个新的：** 新建 `adapters/<名字>/`，放一个 `adapter.json` 和一份 `README.md`。笔记类的再放一个脚本，把东西写成 `inbox/<名字>-<日期>.jsonl`（一行一条，字段见 `interfaces/inbox.md`）；书类的把文件存进 `books/`，或者按 `interfaces/book-source.md` 提供工具。主线代码不用改。

## adapter.json

```json
{
  "name": "目录名",
  "title": "给人看的名字",
  "kind": "notes 或 books",
  "does": "一句话：它送来什么",
  "needs_env": ["要哪些环境变量；凭证只从环境变量读，不写进文件，不打印"],
  "needs_adapters": ["依赖的其他适配器，可省"],
  "needs_tools": ["要 agent 手上有哪些 MCP 工具，可省"],
  "run": "怎么跑",
  "writes": "写到哪里",
  "costs": "要不要花钱，可省",
  "account_changes": "会不会改用户账号里的东西；会的话，跑之前必须先告诉用户"
}
```
