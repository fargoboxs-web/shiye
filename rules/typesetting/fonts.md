# 字体

宋、黑、楷三种，都是开源字体（SIL OFL），不进仓库。第一次运行 `bash scripts/fetch-fonts.sh` 下载到 `fonts/`；模板按文件名找：`NotoSerifSC[wght].ttf`、`NotoSansSC[wght].ttf`、`LXGWWenKai-Regular.ttf`。

- 正文宋体（Noto Serif SC），标题黑体（Noto Sans SC），引文楷体（霞鹜文楷 LXGW WenKai）。纸书通行的搭配：宋体耐读，黑体醒目分层级，引文换楷体一眼能看出"这段是引的"。
- 楷体只用在：章首题记和它的署名、扉页的引子、书里本来就是引文/场景/例子的段落（电子书里标成 blockquote、kaiti、fangsong 之类的段）。正文里不用。
- 刊名默认楷体（封面两字竖排 58pt，封底落款小字）；`cover.json` 的 `mast` 可换成宋或黑。
- 西文和数字用同一字体的拉丁部分，不另配西文字体。
- `run.py render --fonts A|B|C|D` 换搭配（正文｜标题｜引文）：A 宋｜黑｜宋，B 宋｜黑｜楷（默认），C 宋｜宋｜楷，D 楷｜黑｜楷。实现在 `zine/render.py` 的 `FONT_COMBOS`。
