# 书库适配器：书库 MCP（可选）

第 4 步「取书」用。它是一个远程 MCP 服务，agent 直接调它的两个工具，不经过脚本。没接它也能跑：书放进 `books/` 就行，拿不到的书会进 `缺书.md`。

## 接上

把 `mcp.example.json` 里 `books` 那一段抄进你的 agent 的 MCP 配置（Claude Code 是 `.mcp.json`，Codex 是 `~/.codex/config.toml`，Cursor 是 `.cursor/mcp.json`，其余看各自文档），把地址换成你拿到的服务地址。接上后 agent 的工具列表里会多出 `search_books` 和 `get_book`。

## 两个工具

| 工具 | 输入 | 输出 |
|---|---|---|
| `search_books(query)` | 只填书名或原书名，中英文、简繁都行。不能按作者、ISBN、主题搜 | 最多 1 本：`book_id`、书名、作者、语言、格式、`right`；没有合适的就是空 |
| `get_book(book_id)` | 上一步的 `book_id` | 整本原文件的下载链接、`sha256`、大小、`expires_at`。链接一小时内有效，过期重新调一次 |

## 对到 `interfaces/book-source.md`

- `search_books(title, author?, language?)` → `search_books(query=书名)`。它只认书名：中文书用中文名搜，搜不到再用原书名；想要中文版就先用中文名。返回的作者和语言自己核一遍，同名的书不要拿错。
- `fetch_book(id)` → `get_book(book_id)`，把链接下载到 `books/<key>.<格式>`，下完对一下 `sha256`。
- `rights`：返回里的 `right` 是 `publisher authorized`，在 `books.yaml` 里写 `rights: licensed`。
- 没有 `get_book_toc` 和 `get_chapter`，拆章交给 `run.py prepare`。

## 要注意的

- 一次只回一本，不合适就换个书名写法再搜，不要硬用。
- 优先 EPUB；只有扫描版 PDF 的书当作拿不到，记进 `缺书.md`。
- 下载链接带签名，不要写进任何会提交或会打印的文件。

## 拔掉

从 agent 的 MCP 配置里删掉这一段，或者删掉这个目录。流程照常，只是缺的书要读者自己给文件。
