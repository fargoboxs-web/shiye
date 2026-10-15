# 书单 books.yaml

从笔记里找书。读者不用给书单；读者说了想读什么，就并进来，一样走后面的流程。

## 怎么找

- 读 `work/notes.jsonl` 全部条目；摘要不够就读原文。书名、作者、"那本讲 X 的书"都算线索；英文书名要认出来，查出通行中译名。
- 每本书记：`title`（中文通行译名）、`original_title`（外文原名，有就写）、`author`、`why_saved`（笔记原话，一两句，带笔记 id）。
- 排序按 `reader-profile.md`「怎么判断真的在意」。一期 3–6 本；多了砍掉只提了一句的。
- 读者直接说想读的书排最前。

## 不选

- 读者已经在读的（`reader.md` 在读与读过）。
- 只有书名、没有任何上下文、读者画像里也找不到关联的。
- 教材、工具书、整本都是清单的书：选不出能单独读的一篇。

## 格式

见 `interfaces/schemas/books.schema.json`。每本：`title`、`original_title?`、`author`、`year?`、`file?`（本地文件路径）、`why_saved`、`rights?`（owned、public_domain、licensed）。

取不到书的留在书单里，`file` 空。`run.py prepare` 会报缺书，其余照常；缺书清单进检查报告。
