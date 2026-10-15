# 笔记来源 MCP（可选）

不是必需。有 `inbox/` 文件夹就能跑（见 `inbox.md`）。做成 MCP 是为了"读者开放收藏夹，程序自己去拿"这一步。只定接口，不定实现；任何来源（Get笔记、小红书、Notion、本地文件夹）实现这四个工具就能接。

原则：先看列表再取全文，省 token；每条带稳定 `id` 和原始 `url`，能追溯；正文统一 Markdown。

| 工具 | 输入 | 输出 |
|---|---|---|
| `list_sources()` | 无 | `[{id, name, kind, item_count, last_synced}]` |
| `list_items(since?, until?, sources?, kinds?, limit=50, cursor?)` | 时间窗口和筛选，都可省 | `{items: [摘要条目], next_cursor?}`。条目：`id, source, kind, title?, creator?, url?, saved_at?, excerpt, tags?, my_note?` |
| `get_item(id)` | 条目 id | 全文：以上字段加 `content`（Markdown；视频给完整字幕）、`images?` |
| `search_items(query, since?, sources?, limit=20)` | 全文检索 | 同 `list_items` |

对应到 `notes.jsonl`：`saved_at` → `time`，`content`（没有就 `excerpt`）→ `text`，`my_note` → `note`，其余同名。

## 已知来源

- **Get笔记**：官方 Open API 够用，三个端点（列表、原文、语义搜索），细节和限流经验见 `../adapters/getnote/README.md`。密钥只从环境变量读，任何输出不打印密钥值。
- **小红书收藏夹**（2026-10-15 调研）：能列出自己收藏的 MCP 只有 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 一系（`get_my_profile` 的 fav 页），但只取首屏不翻页，当前版本有超时问题。要全量落盘得拼两个非 MCP 工具：[lucasygu/redbook](https://github.com/lucasygu/redbook) 的 `favorites --all --json` 翻页取全部收藏链接，再用 [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader) 下正文和图片到 `inbox/`。步骤见 `../adapters/xiaohongshu/README.md`。
- **Notion、Obsidian、飞书**等：导出成 Markdown 放进 `inbox/` 即可，不需要适配器。
