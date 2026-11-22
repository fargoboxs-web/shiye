# 取书

出方案时用。书只有两个来路，按这个顺序找：

1. **用户自己的电子书。** `books.yaml` 里写了 `file:` 的直接用；没写的，`prepare` 会在 `books/` 里按书名找同名文件（EPUB、PDF、TXT、MD，繁简通用，中译本优先于原版）。
2. **书库。** 接了书库连接器就按 `../adapters/books-mcp/README.md` 取：搜书名，下载到 `books/<key>.<格式>`，把 `file:` 和 `rights` 写回 `books.yaml`。

两处都没有：不管它，`prepare` 会把这本书记进 `缺书.md`，方案里会列出来请用户补。不编造全文，不用来源不明的文本。

EPUB 优先：拆章、插图、书影都最完整。PDF 靠书签拆章，扫描版不能用。

`books.yaml` 里的 `rights` 会印在封底的来源里，取值：`owned`（用户自己的书）、`public_domain`（公版）、`licensed`（书库里有授权的书）。
