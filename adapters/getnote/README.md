# 来源适配器：Get笔记（可选）

主线不依赖它。它只是把 Get笔记 最近的收藏批量存进 `inbox/`，省得 AI 一条条搬：

```bash
export GETNOTE_API_KEY=…  GETNOTE_CLIENT_ID=…     # 只放环境变量，不写进文件
python3 adapters/getnote/pull.py --days 30 --full   # → inbox/getnote-<日期>.jsonl
python3 run.py ingest inbox/                         # → work/notes.jsonl
```

`getnote.py` 直接调官方 REST（三个函数：`list_items(since)`、`get_item(id)`、`search_items(q)`），不经过官方 MCP。下面是 2026-10-12 的接口调研。

---

# Get笔记 接口调研（2026-10-12）

## 结论

Get笔记 官方 Open API 已经够用，不需要它再加接口。我们这边只用 3 个端点，剩下的（时间筛选、按类型筛选）在你的 MCP 里用几行代码补上。

## 官方现状

- 官方 MCP：npm 包 `@getnote/mcp`（1.8.0，发布者 getnote，邮箱在 luojilab.com），源码仓库 iswalle/getnote-mcp。**只支持 stdio（本机 npx 运行），没有 HTTP 传输，所以不能直接当 claude.ai 连接器用。**
- 底层 REST：`https://openapi.biji.com/open/api/v1`，Bearer 鉴权，用 API Key + Client ID，在 https://www.biji.com/openapi 创建应用后生成。报错时会带会员购买链接，Open API 很可能需要得到大脑会员（这一点我没能打开文档页核实）。
- 官方 CLI：pypi `getnotes-cli`，同一套 API，另有 `download` 可把全部笔记落成本地 Markdown，适合做第一次全量导入。
- 配额：`GET /resource/rate-limit/quota` 返回 read / write 的日、月额度。具体数字没查到，接上后先调一次看。

## 我们用到的 3 个端点

| 用途 | 端点 | 关键参数 / 返回 |
|---|---|---|
| 列笔记 | `GET /resource/note/list` | 只有 `cursor`，每页固定 20 条，`has_more`、`cursor`、`total`。每条：`id`（字符串，超出 JS 安全整数）、`title`、`content`（**AI 摘要，不是原文**）、`note_type`、`source`、`tags[]`、`created_at`、`updated_at` |
| 读原文 | `GET /resource/note/detail?id=` | 原文按类型取：文字笔记 `note.content`；链接笔记 `note.web_page.content`（另有 `web_page.url`、`domain`、`excerpt`）；录音 `note.audio.original`。官方 MCP 的 `get_note_original` 就是这个逻辑 |
| 语义搜索 | `POST /resource/recall` | `query`，`top_k` ≤ 10；返回 `note_id`、`title`、`content`、`created_at` |

## 和 mcp-spec.md 的对应

| 我要的 | Get笔记 有的 | 差的部分，在你的 MCP 里补 |
|---|---|---|
| `list_items(since)` 按时间取本周条目 | `note/list` 只能按游标翻页，没有时间参数 | 从最新一页往前翻，`created_at` 早于 `since` 就停。一周的量通常两三页，开销可以忽略 |
| `kind`（post / video / note…） | `note_type` + `source` | 直接映射，顺便把 `source` 原样带上 |
| `excerpt` | `content` 就是 AI 摘要 | 不用处理，正好 |
| `url` 原始链接 | 列表项里没有，详情里 `web_page.url` 才有 | 要么取详情时补，要么列表接口先不给 |
| `get_item(id)` 原文 | `note/detail` 三选一 | 按 `note_type` 取对字段，别把 AI 摘要当原文 |
| `search_items` | `recall` | 直接映射 |

已核实（2026-10-12 接上真接口）：`note/list` 按创建时间倒序返回，翻页到时间截止的逻辑成立。连续快速调 `note/detail` 会被限流（HTTP 429，code 10202），代码里已加退避重试；配额是读 2 万次/天、20 万次/月。

## 建议的接法

你的统一 MCP 里 Get笔记 这一块只需要三个函数，各自调一个端点，再加上面说的翻页截止逻辑。不要再套一层官方 MCP，直接打 REST 更简单，也不用在服务器上跑 Node。

接上之后第一次跑：
1. `list_items(since=14 天前)` 看看笔记里有多少条和书有关、是什么形态（链接笔记居多还是语音居多），决定提书名时主要看摘要还是必须读原文。
2. 同一批笔记我顺手写一版 reader.md 读者画像，替换现在的草稿。
