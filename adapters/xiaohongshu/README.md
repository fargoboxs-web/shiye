# 来源适配器：小红书公开收藏（可选）

给一个小红书主页链接，把这个人**公开**的收藏存进 `inbox/`：正文、配图、视频逐字稿。对方要先在小红书的隐私设置里把收藏设成公开。主线不依赖它。

## 主路线：TikHub 取列表，Get笔记 取全文

```bash
export TIKHUB_API_KEY=…  GETNOTE_API_KEY=…  GETNOTE_CLIENT_ID=…   # 只放环境变量
python3 adapters/xiaohongshu/pull.py <主页链接或用户ID> --max 50      # → inbox/xiaohongshu-<日期>.jsonl、inbox/xiaohongshu/<id>/
python3 run.py ingest inbox/
```

- 第 1 步 `tikhub.py`：收藏列表，一页约 6 条，每页约 0.01 美元，只能用充值余额。接口不给收藏时间，只有顺序（第 1 条是最近收藏的）。想省钱可以先 `python3 adapters/xiaohongshu/tikhub.py <主页链接> --out favs.jsonl` 存下列表，之后用 `--favs favs.jsonl` 反复跑。
- 第 2 步：每条链接交给 Get笔记 建一条链接笔记，等它处理完，取回完整正文、视频逐字稿和配图。所以要用到 `../getnote/`。
- **它会在你的 Get笔记 账号里新建笔记**（带「小红书收藏」标签），默认留着。不想留就加 `--delete-after`，抓完把这次建的那几条移入回收站，只按这次的笔记 id 删，不碰别的。agent 跑之前要把这件事告诉用户。
- 中途断了重跑同一条命令会接着来，已经写进 `inbox/` 的跳过。
- 内容全在图里的笔记，Get笔记 不给原始 OCR，只有它基于图片的 AI 整理，会标明「非原文」。

## 备用路线：Apify，不经过 Get笔记

```bash
export APIFY_TOKEN=…
python3 adapters/xiaohongshu/pull_apify.py <主页链接> --max 50
```

视频用本机 faster-whisper 转写（要装 `faster-whisper` 和 `ffmpeg`，CPU 上约 1 分钟视频转 1 分钟）。Apify 免费账号每个 Actor 累计只给 25 条，到顶会静默停下，脚本会喊出来。

## 取自己不公开的收藏

上面两条路线都只能取公开的。要取自己没公开的收藏，得用本机浏览器的登录态，下面是 2026-10-15 的调研，没有做成脚本。

目标：把自己的小红书收藏抓到 `inbox/xiaohongshu/`，每篇一个文件夹（正文 + 图片），然后 `run.py ingest`。
2026-10-15 调研结论：**没有任何 MCP 能一步把收藏导出成本地文件夹**；能列出自己收藏的 MCP 只有 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 一系（`get_my_profile tab=fav`），但只取首屏不翻页，当前版本还有超时问题。全量落盘要拼两个非 MCP 的开源工具。

### redbook 取链接 + XHS-Downloader 落盘

1. [lucasygu/redbook](https://github.com/lucasygu/redbook)（npm `@lucasygu/redbook`，读本机 Chrome 的登录态，不用浏览器自动化）：
   ```bash
   npx @lucasygu/redbook favorites --all --json > favorites.json     # 翻页取全部收藏，每页 30 条
   ```
   注意它翻页不带延时，收藏很多时可以分几次。
2. [JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)（Python，GPL-3.0）：从 `favorites.json` 取出每条的 `webUrl`，批量喂给它，设置 `note_format=md`、`folder_mode=true`，下载目录指到 `inbox/xiaohongshu/`。每篇得到一个文件夹：正文 `.md` + 无水印图片（视频也能下）。
3. `python3 run.py ingest inbox/`：文件夹里的 `.md` 和同文件夹的图片归成一条，`source` 会是 `file`；想标成 `xiaohongshu`，在 `.md` 开头加一行 `source: xiaohongshu` 即可（或者等有脚本时自动标）。

### 备选

- 只用 XHS-Downloader：它自带的油猴脚本「提取账号收藏作品链接」能在浏览器里滚动取全部链接（README 提示有风控风险），再粘给程序批量下载。一个项目搞定，但取链接要手动。
- 纯 MCP：xpzouying/xiaohongshu-mcp 的 `get_my_profile(tab=fav)` → 逐篇 `get_feed_detail` → AI 自己把 `desc` 写文件、下载 `imageList` 的图。只适合收藏少或只要最近几条；衍生版 [CNQQC/xhs-mcp](https://github.com/CNQQC/xhs-mcp) 还能给视频字幕的纯文本。
