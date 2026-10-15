# 来源适配器：小红书收藏夹（步骤，暂无脚本）

目标：把自己的小红书收藏抓到 `inbox/xiaohongshu/`，每篇一个文件夹（正文 + 图片），然后 `run.py ingest`。
2026-10-15 调研结论：**没有任何 MCP 能一步把收藏导出成本地文件夹**；能列出自己收藏的 MCP 只有 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 一系（`get_my_profile tab=fav`），但只取首屏不翻页，当前版本还有超时问题。全量落盘要拼两个非 MCP 的开源工具。

## 推荐做法：redbook 取链接 + XHS-Downloader 落盘

1. [lucasygu/redbook](https://github.com/lucasygu/redbook)（npm `@lucasygu/redbook`，读本机 Chrome 的登录态，不用浏览器自动化）：
   ```bash
   npx @lucasygu/redbook favorites --all --json > favorites.json     # 翻页取全部收藏，每页 30 条
   ```
   注意它翻页不带延时，收藏很多时可以分几次。
2. [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)（Python，GPL-3.0）：从 `favorites.json` 取出每条的 `webUrl`，批量喂给它，设置 `note_format=md`、`folder_mode=true`，下载目录指到 `inbox/xiaohongshu/`。每篇得到一个文件夹：正文 `.md` + 无水印图片（视频也能下）。
3. `python3 run.py ingest inbox/`：文件夹里的 `.md` 和同文件夹的图片归成一条，`source` 会是 `file`；想标成 `xiaohongshu`，在 `.md` 开头加一行 `source: xiaohongshu` 即可（或者等有脚本时自动标）。

## 备选

- 只用 XHS-Downloader：它自带的油猴脚本「提取账号收藏作品链接」能在浏览器里滚动取全部链接（README 提示有风控风险），再粘给程序批量下载。一个项目搞定，但取链接要手动。
- 纯 MCP：xpzouying/xiaohongshu-mcp 的 `get_my_profile(tab=fav)` → 逐篇 `get_feed_detail` → AI 自己把 `desc` 写文件、下载 `imageList` 的图。只适合收藏少或只要最近几条；衍生版 [CNQQC/xhs-mcp](https://github.com/CNQQC/xhs-mcp) 还能给视频字幕的纯文本。

## 什么时候写脚本

等实测一次之后：如果上面两步手动做一次就够（一个朋友一本），不写；如果要每周跑，就把第 1、2 步串成 `pull.py`，接口和 `../getnote/pull.py` 一样——输入时间范围，输出 `inbox/` 里的文件。
