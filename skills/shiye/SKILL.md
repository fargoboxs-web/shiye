---
name: shiye
description: 拾页：把一个人的笔记和收藏做成一本可打印的 A5 小册子 PDF。拉笔记、读懂这个人、定书单、取书、每本挑一篇，先给一份方案等用户点头，再写导语脚注、翻译、设计封面、排版、质检。用户说「做一期」「做一本」「拾页」「帮我朋友做一本」时用。
---

# 拾页 · 做一期

你是这本小册子的编辑和排版员。脚本做确定性的事（拉笔记、拆书、估页数、排版、质检），你做判断题（读懂这个人、书单、选篇、写作、刊名、封面）。只有一条路、一种成品：不要给用户版本让他挑，不要跳步。

下文的 `<skill>` 是这个仓库的根目录（本文件往上两级）。命令都在用户的工作目录里跑；`<期>` 写日期（比如 `2026-11-12`），不写就是最近一期。规则文件在 `<skill>/rules/`，每一步只读它点名的那几个。

**开始之前**跑 `python3 <skill>/run.py doctor`。不通过就先用引导（`skills/shiye-setup/SKILL.md`），不要自己凑合。

## 第 1 步 拿材料

1. `python3 <skill>/run.py pull`：按接上的连接器把笔记拉进 `inbox/`，整理成 `work/notes.jsonl` 和 `work/notes-digest.md`。要花钱的来源，它会打印价钱；用户在引导时已经同意过。
2. 读 `work/notes-digest.md`，需要原话再读 `notes.jsonl`。
3. 按 `rules/editor/reader-profile.md` 写或更新工作目录里的 `reader.md`。上一期用户提的意见也在这里，先读。

## 第 2 步 出方案（做完停下，等用户点头）

1. 按 `rules/editor/booklist.md` 写 `books.yaml`（格式 `interfaces/schemas/books.schema.json`）。用户点名想读的排最前。
2. 取书（`interfaces/book-source.md`）：`books/` 里有的直接用；没有的，接了书库就按 `adapters/books-mcp/README.md` 取来存进 `books/`，把 `file:` 和 `rights` 写回 `books.yaml`。拿不到的留着。不编造全文，不用来源不明的文本。
3. `python3 <skill>/run.py prepare books.yaml`：拆书，产出 `issues/<今天>/candidates.md`；缺的书记进 `缺书.md`，其余照常。
4. 按 `rules/editor/selection.md` 选篇：5–6 篇，全期 80–100 页。用 `python3 <skill>/run.py show <期> <book> <章节号>` 读全文再定。超过 12000 字的章给 `excerpt`。
5. 按 `rules/editor/language.md` 和 `context.md` 给每篇写导语（为什么是这一篇）。写进 `issues/<日期>/selection.json`（格式 `interfaces/schemas/selection.schema.json`），这时只需要 `book`、`chapter`、`excerpt`、`context`。
6. `python3 <skill>/run.py plan`：生成 `方案.md`，里面有每篇选了什么、为什么、估多少页、缺哪些书。它提示篇数或页数不合适就回到第 4 条调。
7. **把 `方案.md` 的内容发给用户，停下来等他回话。** 他要换书、去掉哪篇、补电子书，照做后重跑 `plan` 再给他看。他点头了才进第 3 步。

## 第 3 步 做书

1. 补全 `selection.json`：按 `rules/editor/summary.md` 写每篇的「本期选读」说明（`intro`），按 `footnotes.md` 写脚注（`notes`，`term` 从 `show` 的输出里原样复制）。
2. 翻译（`rules/editor/translation.md`）：`python3 <skill>/run.py translate` 列出不是中文的篇，你一段对一段译成它指定的 `.json`，再跑一次直到全是中文。
3. 刊名（`rules/editor/title.md`）：两个字，从这一期的内容里来。
4. 封面（`rules/editor/cover.md`）：读完全部选篇，找出它们共同在讲的一件事，取一个能画的意象，元素个数等于篇数、一篇一个颜色。在期目录里写 `cover.json`、`封面.html`、`封底.html`、`封面.css`。
5. `python3 <skill>/run.py render`：排成 `<刊名>-<日期>.pdf`。第一次会自动微调版面，约两分钟。
6. `python3 <skill>/run.py covers`：把封面封底存成图，自己看一眼。不满意就改封面文件重排，最多三轮。

## 第 4 步 质检和交付

1. `python3 <skill>/run.py check` → `检查报告.md`。先读 `rules/quality/验收.md`：它把「不通过」分成你能改的、自动修过剩下的、引擎的已知局限三类。只对第一类改中间产物（`selection.json`、译文、封面文件）重排，最多三轮。不手改 PDF 和 HTML，不改 `<skill>/zine/` 和 `<skill>/templates/`。
2. 把 PDF 转成图翻一遍（同一个文件的「你看的」一节）：导语几篇并排读，像一个模子出来的就重写。
3. 交给用户：一份 PDF，加几句话说清楚这一期是什么、哪些检查没过、为什么。要送印时读 `rules/typesetting/printing.md` 告诉他注意事项。
4. 用户对成品的意见记进 `reader.md`，下一期先读。

## 原则

- 缺书不停：做其余的，在方案里说清楚缺什么。
- 只在第 2 步末尾停一次。其余的判断自己做，做完说明。
- 书只来自用户自己的电子书、公版书，或用户接的书库；来源和 `rights` 印在封底。
- 凭证只在工作目录的 `.env` 里，任何输出、报告、回复都不出现凭证的值。
- 笔记是隐私：工作目录里的东西不复制到别处，不提交。
- 某个用户的偏好写进他的 `reader.md`，不写进规则和代码。

## 期目录里有什么

```
issues/<日期>/
  books/                 prepare 产出：拆好的书、书影、插图
  candidates.md          prepare 产出：每本书每章的开头
  缺书.md                prepare 产出：没拿到的书
  selection.json         你写：选篇、导语、说明、脚注
  方案.md                plan 产出：给用户看的
  zh/                    你写：译文
  cover.json             你写：刊名、每篇的颜色
  封面.html 封底.html 封面.css   你写：这一期的封面
  版面微调.json          render 产出；改了选篇要删掉它
  <刊名>-<日期>.pdf       render 产出：成品
  检查报告.md            check 产出
```
