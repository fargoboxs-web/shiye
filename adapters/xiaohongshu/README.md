# 连接器：小红书公开收藏

给一个小红书主页链接，把这个人**公开**的收藏存进 `inbox/`：正文、配图、视频逐字稿。

- 要什么（写在工作目录的 `.env` 里）：
  - `XHS_PROFILE`：主页链接。小红书 App 里「我」→ 右上角分享 → 复制链接。要先在 设置 → 隐私设置 里把收藏设成公开。
  - `TIKHUB_API_KEY`：https://tikhub.io 注册、充值后生成。注册送的额度不能用于这个接口。
  - `GETNOTE_API_KEY`、`GETNOTE_CLIENT_ID`：用 Get笔记 把帖子和视频转成文字，所以也要 `../getnote/`。
- 怎么跑：`python3 <skill>/run.py pull` 会自动调它，默认取最近收藏的 50 条。
- 花费：TikHub 每 6 条约 0.01 美元。
- **它会在用户的 Get笔记 账号里新建笔记**（带「小红书收藏」标签），默认留着。单独跑 `pull.py` 时加 `--delete-after`，会在抓完后把这次建的那几条移入回收站，只按这次的笔记 id 删，不碰别的。接这个连接器之前要把这件事告诉用户。

## 细节

- 接口不给收藏时间，只有顺序（第 1 条是最近收藏的）。
- 中途断了重跑会接着来，已经写进 `inbox/` 的跳过。
- 想省钱：`python3 <skill>/adapters/xiaohongshu/tikhub.py <主页链接> --out favs.jsonl` 存下列表，之后 `pull.py --favs favs.jsonl` 反复跑不再花 TikHub 的钱。
- 内容全在图里的帖子，Get笔记 不给原始 OCR，只有它基于图片的 AI 整理，脚本会标明「非原文」。
- 只能取公开的收藏。
