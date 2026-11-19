#!/usr/bin/env python3
"""可选的来源适配器：小红书主页链接 → 公开收藏 → Get笔记 转写 → inbox/。

  python3 adapters/xiaohongshu/pull.py <主页链接或用户ID> [--max 0] [--inbox inbox/]
  python3 adapters/xiaohongshu/pull.py --favs favs.jsonl   # 复用 tikhub.py 存下的列表，跳过第 1 步
  python3 adapters/xiaohongshu/pull.py --ids ids.txt       # 只有笔记 ID 时

1. TikHub 收藏列表（tikhub.py，一页约 6 条，每页约 $0.01，要充值余额）。
   也可以 --favs favs.jsonl 复用上次拿到的列表，不再花钱。
2. 每条 https://www.xiaohongshu.com/explore/<id> 交给 Get笔记 建链接笔记（不需要 xsec_token），
   轮询任务，取 note/detail 的 web_page.content：完整正文 + 视频逐字稿 + 全部配图。
   这一步会在 Get笔记 账号里新建带「小红书收藏」标签的链接笔记，默认留着不动。
   加 --delete-after 才会在抓完后把这次自己建的那几条移入回收站（只按这次的 note_id 删，不碰别的笔记）。
凭证只从环境变量读：TIKHUB_API_KEY、GETNOTE_API_KEY、GETNOTE_CLIENT_ID，不打印。
输出：inbox/xiaohongshu-<日期>.jsonl（notes.jsonl 的格式），图片下载到 inbox/xiaohongshu/<id>/。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE.parent / "getnote"))   # 放后面：那边也有个 pull.py，别盖住本目录的

try:
    import getnote  # noqa: E402
except ImportError:
    sys.exit("这个适配器要用 adapters/getnote/ 做转写，那个目录不在。换 pull_apify.py，或者把 getnote 适配器放回来。")
from tikhub import favorites  # noqa: E402

TAG = "小红书收藏"
CST = dt.timezone(dt.timedelta(hours=8))
_raw_request = getnote._request


def _request(*a, **kw):
    # 代理偶尔断连，重试几次；业务错误（GetNoteError）不重试
    for attempt in range(5):
        try:
            return _raw_request(*a, **kw)
        except getnote.GetNoteError:
            raise
        except OSError as e:
            if attempt == 4:
                raise
            print(f"  网络断了，重试（{e}）", file=sys.stderr)
            time.sleep(2 ** attempt * 2)


getnote._request = _request
RUN = str(int(time.time()))   # 幂等键带上本次运行，删过的笔记下次还能重建
TOPIC = re.compile(r"#[^#]*?\[话题\]#")
SHORT = 200   # 去掉话题标签后正文不到这么多字，就当作内容在图里
IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def submit(nid: str) -> str | None:
    try:
        r = getnote._request("POST", "/resource/note/save", body={
            "note_type": "link", "link_url": f"https://www.xiaohongshu.com/explore/{nid}",
            "tags": [TAG], "client_request_id": f"xhs-{nid}-{RUN}"})
        return (r.get("tasks") or [{}])[0].get("task_id")
    except getnote.GetNoteError as e:
        print(f"  提交失败 {nid}：{e}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", nargs="?", help="小红书主页链接或用户 ID")
    ap.add_argument("--ids", help="每行一个笔记 ID 的文件，代替第 1 步")
    ap.add_argument("--favs", help="tikhub.py 存下的 favs.jsonl，代替第 1 步")
    ap.add_argument("--skip", type=int, default=0, help="跳过列表前多少条（分批跑）")
    ap.add_argument("--batch", type=int, default=20, help="同时在 Get笔记 里处理的最多条数")
    ap.add_argument("--max", type=int, default=0, help="最多取多少条收藏（0 = 全部）")
    ap.add_argument("--inbox", default=str(HERE.parents[1] / "inbox"))
    ap.add_argument("--timeout", type=int, default=1200, help="单条等 Get笔记 处理的最长秒数")
    ap.add_argument("--delete-after", action="store_true", help="抓完把这次在 Get笔记 里建的笔记移入回收站（默认不删）")
    args = ap.parse_args()
    if not (args.profile or args.ids or args.favs):
        ap.error("给主页链接，或者 --favs / --ids")

    t0 = time.time()
    if args.ids:
        favs = [{"id": line.split()[0]} for line in Path(args.ids).read_text().splitlines() if line.strip()]
    elif args.favs:
        favs = [json.loads(line) for line in Path(args.favs).read_text().splitlines() if line.strip()]
    else:
        favs = favorites(args.profile, args.max)
        if not favs:
            sys.exit("列表是空的：收藏可能没设成公开")
    favs = favs[args.skip:][:args.max] if args.max else favs[args.skip:]
    print(f"① 收藏 {len(favs)} 条")

    inbox = Path(args.inbox); inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"xiaohongshu-{dt.date.today().isoformat()}.jsonl"
    # 已经写进 inbox 的跳过：中途断了重跑同一条命令就能接着来
    done = {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()} if path.exists() else set()
    todo = [f for f in favs if f"xhs:{f['id']}" not in done]
    if done:
        print(f"  inbox 里已有 {len(done)} 条，这次处理剩下的 {len(todo)} 条")

    # 同时最多 batch 条在 Get笔记 里处理：做完一条就取内容，再补一条。
    # 中途断了，Get笔记 里最多留 batch 条；处理太久的不丢下不管，超过 timeout 才放弃并记下来
    ok = deleted = 0
    queue, flying = list(todo), {}          # nid -> (task_id, 提交时间, fav)
    while queue or flying:
        while queue and len(flying) < args.batch:
            fav = queue.pop(0)
            if (t := submit(fav["id"])):
                flying[fav["id"]] = (t, time.time(), fav)
        time.sleep(15)
        for nid, (task, t1, fav) in list(flying.items()):
            r = getnote._request("POST", "/resource/note/task/progress", body={"task_id": task})
            if r.get("status") == "success":
                flying.pop(nid)
                row = fetch(fav, r["note_id"], inbox)
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                ok += 1
                # 只删这次自己建的笔记（按 note_id），不碰账号里别的笔记；删除是移入回收站
                if args.delete_after:
                    try:
                        getnote._request("POST", "/resource/note/delete", body={"note_id": r["note_id"]})
                        deleted += 1
                    except getnote.GetNoteError as e:
                        print(f"  Get笔记 删除失败 {r['note_id']}：{e}", file=sys.stderr)
            elif r.get("status") == "failed":
                flying.pop(nid)
                print(f"  Get笔记 处理失败 {nid}：{r.get('error_msg')}", file=sys.stderr)
            elif time.time() - t1 > args.timeout:
                flying.pop(nid)
                print(f"  等了 {args.timeout} 秒还没好，放弃 {nid}（task {task}，之后在 Get笔记 里可能会冒出来，要手动删）",
                      file=sys.stderr)
        print(f"② 已写入 {ok}，Get笔记 已删 {deleted}，处理中 {len(flying)}，排队 {len(queue)}", flush=True)

    print(f"✓ 这次 {ok}/{len(todo)} 条 → {path}（{int(time.time() - t0)} 秒）")


def fetch(fav: dict, note_id: str, inbox: Path) -> dict:
    nid = fav["id"]
    n = getnote._request("GET", "/resource/note/detail", params={"id": note_id})["note"]
    web = n.get("web_page") or {}
    content = web.get("content") or ""
    att = (n.get("attachments") or [{}])[0]
    # 图片在 Get笔记 的存储上，删笔记前先落到本地
    folder = inbox / "xiaohongshu" / nid
    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for j, u in enumerate(IMG.findall(content), 1):
        p = folder / f"{j:02d}.jpg"
        try:
            if not p.exists():
                with urllib.request.urlopen(u, timeout=60) as r:
                    p.write_bytes(r.read())
            images.append(str(p.relative_to(inbox.parent)))
        except Exception as e:  # noqa: BLE001
            print(f"  图片下载失败 {nid} #{j}：{e}", file=sys.stderr)
    text = IMG.sub("", content).strip()
    summary = n.get("content") or ""
    if fav.get("type") != "video" and summary and len(TOPIC.sub("", text).strip()) < SHORT:
        # 内容在图里的笔记：Get笔记 不给原始 OCR 文字，只有基于图片的 AI 整理，拿它补上
        text += "\n\n【图片内容（Get笔记 AI 整理，非原文）】\n" + summary
    return {
        "id": f"xhs:{nid}", "source": "xiaohongshu",
        "kind": "video" if fav.get("type") == "video" else "post",
        "time": dt.datetime.fromtimestamp(fav["published"], CST).isoformat() if fav.get("published") else None,
        "fav_rank": fav.get("fav_rank"), "title": att.get("title") or fav.get("display_title") or n.get("title"),
        "url": web.get("url") or f"https://www.xiaohongshu.com/explore/{nid}",
        "text": text, "images": images,
        "tags": re.findall(r"#([^#\[\s]+)\[话题\]#", content),
        "author": fav.get("author"), "summary": summary,
    }


if __name__ == "__main__":
    main()
