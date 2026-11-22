# 连接器：书库

按书名取整本电子书。它是一个远程 MCP 服务，agent 直接调它的两个工具，不经过脚本。没接它也能做书：用户把电子书放进 `books/`，拿不到的书会列在方案里。

## 接上

先看你的工具列表：已经有 `search_books` 和 `get_book` 就是接好了，跳到「两个工具」。没有再做下面三步。

1. 向给你这个 skill 的人要服务地址和 key（每人一个 key）。写进工作目录的 `.env`：`BOOKS_MCP_URL=`、`BOOKS_MCP_KEY=`。
2. 把它加进你这个 agent 的 MCP 配置：一个 HTTP 类型的服务，地址是 `BOOKS_MCP_URL`，带请求头 `Authorization: Bearer <BOOKS_MCP_KEY>`。各家 agent 的配置文件不同（Claude Code 是 `.mcp.json`，Codex 是 `~/.codex/config.toml`，Cursor 是 `.cursor/mcp.json`），照它自己的文档写。key 用环境变量引用，不要写死在配置文件里。
3. 接上后工具列表里会多出 `search_books` 和 `get_book`。调一次 `search_books` 搜一本书，确认能用。

## 两个工具

| 工具 | 输入 | 输出 |
|---|---|---|
| `search_books(query)` | 只填书名或原书名，中英文、简繁都行。不能按作者、ISBN、主题搜 | 最多 1 本：`book_id`、书名、作者、语言、格式、`right`；没有合适的就是空 |
| `get_book(book_id)` | 上一步的 `book_id` | 整本原文件的下载链接、`sha256`、大小、`expires_at`。链接一小时内有效，过期重新调一次 |

## 怎么用

- 它只认书名：中文书用中文名搜，搜不到再用原书名；想要中文版就先用中文名。返回的作者和语言自己核一遍，同名的书不要拿错。
- 把链接下载到 `books/<key>.<格式>`，下完对一下 `sha256`。在 `books.yaml` 里写 `file:` 和 `rights: licensed`。
- 一次只回一本，而且可能是同名的另一本书（搜「威尼斯之石」可能回一本同名小说）。作者不对就换写法再搜：加原书名、换繁体、换英文名。不要硬用。
- 优先 EPUB。PDF 可能是扫描版，`prepare` 会认出来并记进缺书；也可能没有书签，那样一「段」会是一整页，译的时候要自己按意思重新分段，段数保持不变。
- 下载链接带签名，不要写进任何会提交或会打印的文件。

## 出错时

- 超出限额时工具返回一条错误（`isError: true`），里面有 `"code": "quota_exceeded"`、是哪个限制（`minute` / `day` / `month`）、`reset_at` 和 `"do_not_retry": true`。不要重试，也不要等：把这本书当作拿不到，继续做其余的。
- 连接时就报 HTTP 401，是 key 没带上、填错、被停用或过期。告诉用户去核对，不要反复重连。
- 默认限额：搜书每分钟 20 次、每天 200 次；取书每分钟 5 次、每天 30 本、每月 300 本。只有成功的调用才计数。
