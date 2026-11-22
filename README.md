# 拾页 shiye

把一个人的笔记和收藏做成一本可打印的 A5 小册子 PDF：从他想读的书里各挑一篇，每篇前面有一段话告诉他为什么是这一篇。

这是给 AI agent 用的 skill，不绑定哪一家：Claude Code、Codex、Cursor、Gemini CLI，或者别的能读写文件、能跑命令的 agent 都可以。agent 做判断（读懂这个人、定书单、选篇、写导语和脚注、定刊名、设计封面），脚本做确定性的事（拉笔记、拆书、估页数、排版、质检）。

## 怎么用

把这个仓库放到本地，用你的 agent 打开，然后说两句话：

1. **「帮我装好拾页」**（只在第一次）。agent 会问你笔记收藏在哪，比如小红书的主页链接或者 Get笔记，帮你把凭证填好、依赖装好，直到自检通过。
2. **「做一期」**。agent 去拉笔记、定书单、取书、选篇，然后给你一份方案：这一期读哪几篇、各自为什么、大概多少页。你点头之后，它排出一份 PDF。

中间只在方案那里停一次。成品只有一种样子。

## 里面有什么

- `skills/shiye-setup/`：引导。
- `skills/shiye/`：做一期，四步。
- `adapters/`：连接器，往笔记和书两个文件夹里送东西。现在有 Get笔记、小红书公开收藏、书库。加一个新来源就是加一个目录，见 `adapters/README.md`。
- `rules/`：编辑规矩（`editor/`）、版式（`typesetting/`）、验收（`quality/`），一个话题一个文件。
- `run.py`、`zine/`、`templates/`：引擎。
- `examples/`：一份读者画像样例、一份书单样例、一个封面的完整例子。

你的笔记、书和每一期的成品都在你自己的工作目录里，不在这个仓库里。

## 手动跑

agent 跑的就是这些命令，在工作目录里：

```bash
python3 <skill>/run.py init        # 建工作目录
python3 <skill>/run.py doctor      # 自检
python3 <skill>/run.py pull        # 拉笔记
python3 <skill>/run.py prepare books.yaml
python3 <skill>/run.py plan        # → 方案.md
python3 <skill>/run.py render      # → PDF
python3 <skill>/run.py check       # → 检查报告.md
```

## 还没做的

- 内页和封面分成两个文件，另出一张封面展开图（送印要用）。
- 目录后面的编者按。
- 字体下载脚本没有备用地址。
