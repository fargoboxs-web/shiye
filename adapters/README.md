# 连接器

主线只认两个文件夹：工作目录里的 `inbox/`（笔记）和 `books/`（书）。连接器是往这两个文件夹里送东西的插件，一个目录一个。主线不依赖任何一个连接器，连接器之间除了声明的依赖也互不相干。

| 目录 | 送什么 |
|---|---|
| `getnote/` | Get笔记 最近的笔记和收藏 → `inbox/` |
| `xiaohongshu/` | 一个人公开的小红书收藏 → `inbox/` |
| `books-mcp/` | 按书名取整本书 → `books/` |

一个都不接也能做书：用户把笔记文件放进 `inbox/`、电子书放进 `books/`。

## 它们怎么被用到

- **引导**（`skills/shiye-setup/`）读每个连接器的 `ask`，问用户要这些值，写进工作目录的 `.env`。
- **`run.py doctor`** 看每个连接器的值填没填；有 `test` 的再试连一次。
- **`run.py pull`** 把值都填了的笔记连接器挨个跑一遍。

所以加一个新来源，就是加一个目录：引导会自动多问几项，`pull` 会自动多拉一处。主线代码和两个 skill 都不用改。

## 加一个连接器

新建 `adapters/<名字>/`，放：

1. `adapter.json`（下面的格式）。
2. `README.md`：它送什么、要什么、花不花钱、会不会动用户的账号。
3. 笔记类：一个拉取脚本，接受 `--inbox <目录>`，把东西写成 `<目录>/<名字>-<日期>.jsonl`，一行一条，字段见 `interfaces/inbox.md`。凭证用 `adapters/env.py` 读（见 `getnote/getnote.py` 开头两行），不打印。
4. 书类：把文件存进 `books/`，或者按 `interfaces/book-source.md` 提供工具。

```json
{
  "name": "目录名",
  "title": "给用户看的名字",
  "kind": "notes 或 books",
  "does": "一句话：它送来什么",
  "ask": [
    {"env": "环境变量名", "prompt": "问用户要什么", "how": "去哪拿", "optional": false}
  ],
  "test": "试连脚本的文件名，成功退出 0（可省）",
  "test_by_agent": "脚本试不了时，告诉 agent 自己怎么试（可省）",
  "pull": ["拉取脚本的文件名", "固定参数…"],
  "costs": "要花多少钱（可省）",
  "account_changes": "会不会改用户账号里的东西；会的话引导时必须先告诉用户"
}
```

拔掉一个连接器：删掉它的目录。
