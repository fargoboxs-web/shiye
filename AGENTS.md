# 给 agent 的说明

这个仓库是一个 skill：把一个人的笔记和收藏做成一本可打印的 A5 杂志 PDF。

用户说「做一期杂志」「从收藏夹做一本书」「拾页」之类的话时，读 `SKILL.md`，从第 1 步做到第 11 步。每一步只读它指向的那一个规则文件。

- 需要的能力：读写本目录的文件、运行 `python3`。不需要任何特定厂商的工具。
- 读者的东西（`inbox/`、`work/`、`issues/`、`books/`、`reader.md`、`books.yaml`）都被 `.gitignore` 排除，不要提交。
- 不要改 `zine/` 和 `templates/` 来凑结果；版面不对先查 `rules/typesetting/`，确实是引擎的问题再改，并告诉用户。
