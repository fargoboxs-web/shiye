# 书库 MCP

第 4 步"取书"问它。只定接口，不定实现；书的来源和权利由实现方负责，skill 不自带任何书源。拿到的文件存到 `books/`，在 `books.yaml` 里写 `file:`，后面和本地电子书一样处理。

| 工具 | 输入 | 输出 |
|---|---|---|
| `search_books(title, author?, language?, limit=5)` | 书名（中文或原名）、作者 | `[{id, title, author, year?, language, edition?, formats: ["epub","pdf","txt"], rights, cover_url?}]` |
| `fetch_book(id, format?)` | 候选 id；格式可省，默认 epub | `{path 或 url, format, title, author, year?, rights}`。`path` 是本机文件路径，`url` 是可直接下载的地址 |
| `get_book_toc(id)` | 可选 | `{chapters: [{chapter_id, title, level, word_count, opening?}]}` |
| `get_chapter(id, chapter_id)` | 可选 | `{title, content}`，Markdown。能直接给章节的库可以跳过拆书，把章节存成 `books/<key>.json`（`{"title","author","chapters":[{"title","content"}]}`） |

`rights` 取值：`owned`（读者自己的书）、`public_domain`（公版）、`licensed`（有授权的库）。它会写进 `books.yaml`，印在封底的来源里。

## 取书的顺序

1. `books.yaml` 里写了 `file:` 的，直接用。
2. 没写的，在 `books/` 里按书名找同名文件（EPUB、PDF、TXT、MD、JSON）。
3. 还没有，问书库 MCP：`search_books` → 挑语言和版本最合适的一条 → `fetch_book` → 存到 `books/<key>.<format>`，把路径和 `rights` 写回 `books.yaml`。
4. 都没有：记进缺书清单，继续做其余的书。不编造全文，不用来源不明的文本。

EPUB 优先：拆章、插图、封面都最完整。PDF 靠书签拆章，扫描版不能用。

## 怎么包现有的 zlibrary-mcp

它已有 `search_books` 和 `download_book_to_file`，包一层就能对上：`search_books` 的返回映射成上表的字段（`rights` 由包装层按来源填），`fetch_book` 调 `download_book_to_file` 并返回落盘路径。
