#!/usr/bin/env python3
"""可选的来源适配器（备用路线，不经过 Get笔记）：小红书主页链接 → 这个人的公开收藏 → inbox/。

  python3 adapters/xiaohongshu/pull_apify.py <主页链接或用户ID> [--max 50] [--inbox inbox/] [--whisper medium]

前提：对方在小红书里把收藏设成公开；环境变量 APIFY_TOKEN（不打印）。
1. Apify toolzerhub/rednote-xiaohongshu-favorites-scraper：收藏列表（ID、类型、视频 mp4）
2. Apify toolzerhub/rednote-xiaohongshu-post-scraper：逐条取完整正文和全部原图（列表里的正文是截断的）
3. 视频：mp4 → faster-whisper 本地转写（不花钱，CPU 上约 1 分钟视频转 1 分钟）
输出：inbox/xiaohongshu-<日期>.jsonl（notes.jsonl 的格式）+ inbox/xiaohongshu/<id>/ 里的图片。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.apify.com/v2"
FAV_ACTOR = "toolzerhub~rednote-xiaohongshu-favorites-scraper"
POST_ACTOR = "toolzerhub~rednote-xiaohongshu-post-scraper"
CST = dt.timezone(dt.timedelta(hours=8))


def apify(actor: str, inp: dict, timeout: int = 300) -> list[dict]:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("缺 APIFY_TOKEN 环境变量")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    req = urllib.request.Request(f"{API}/acts/{actor}/runs?waitForFinish={min(timeout, 60)}",
                                 data=json.dumps(inp).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=90) as r:
        run = json.load(r)["data"]
    while run["status"] in ("READY", "RUNNING"):
        with urllib.request.urlopen(urllib.request.Request(
                f"{API}/actor-runs/{run['id']}?waitForFinish=60", headers=headers), timeout=90) as r:
            run = json.load(r)["data"]
    msg = run.get("statusMessage") or ""
    if "limit" in msg.lower():
        # 免费账号每个 Actor 累计只给 25 条，到了就静默停下，这里必须喊出来
        print(f"⚠ Apify 额度到顶（{actor}）：{msg}", file=sys.stderr)
    with urllib.request.urlopen(urllib.request.Request(
            f"{API}/datasets/{run['defaultDatasetId']}/items?clean=1", headers=headers), timeout=90) as r:
        return json.load(r)


def detail(note_id: str, kind: str) -> dict | None:
    for attempt in range(2):
        try:
            items = apify(POST_ACTOR, {"post_id_or_url": note_id,
                                       "content_type": "video" if kind == "video" else "image"})
            if items:
                return items[0]
        except Exception as e:  # noqa: BLE001
            print(f"  详情取不到 {note_id}（第 {attempt + 1} 次）：{e}", file=sys.stderr)
            time.sleep(3)
    return None


def video_url(*notes: dict) -> str | None:
    for n in notes:
        stream = (((n or {}).get("video_info_v2") or {}).get("media") or {}).get("stream") or {}
        for codec in ("h264", "h265"):
            for s in stream.get(codec) or []:
                if s.get("master_url"):
                    return s["master_url"]
    return None


def download(url: str, path: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            path.write_bytes(r.read())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  图片下载失败 {path.name}：{e}", file=sys.stderr)
        return False


class Transcriber:
    def __init__(self, model: str):
        self.name, self.model = model, None

    def __call__(self, url: str) -> str:
        import numpy as np
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.name, device="cpu", compute_type="int8")
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", url, "-vn", "-ac", "1", "-ar", "16000",
                              "-f", "s16le", "-"], capture_output=True, check=True, timeout=600).stdout
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
        segs, _ = self.model.transcribe(audio, language="zh", vad_filter=True,
                                        initial_prompt="以下是普通话的句子，使用简体中文。")
        return "\n".join(s.text.strip() for s in segs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", help="小红书主页链接或用户 ID")
    ap.add_argument("--max", type=int, default=50, help="最多取多少条收藏（0 = 全部）")
    ap.add_argument("--inbox", default=str(Path(__file__).resolve().parents[2] / "inbox"))
    ap.add_argument("--whisper", default="medium", help="faster-whisper 模型；none = 不转写")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    inbox = Path(args.inbox).resolve()
    img_root = inbox / "xiaohongshu"
    img_root.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    favs = apify(FAV_ACTOR, {"profile_id_or_url": args.profile, "maxItems": args.max})
    print(f"① 收藏列表 {len(favs)} 条（视频 {sum(f.get('type') == 'video' for f in favs)}）")
    if not favs:
        sys.exit("列表是空的：收藏没设成公开，或者 Apify 额度到顶（看上面有没有 ⚠）")

    with ThreadPoolExecutor(args.workers) as pool:
        details = list(pool.map(lambda f: detail(f["id"], f.get("type", "")), favs))
    print(f"② 详情 {sum(d is not None for d in details)}/{len(favs)} 条")

    tx = Transcriber(args.whisper) if args.whisper != "none" else None
    rows = []
    for i, (fav, det) in enumerate(zip(favs, details), 1):
        n = det or fav
        nid, kind = fav["id"], ("video" if fav.get("type") == "video" else "post")
        folder = img_root / nid
        folder.mkdir(exist_ok=True)
        images = []
        for j, im in enumerate(n.get("images_list") or [], 1):
            p = folder / f"{j:02d}.webp"
            if p.exists() or download(im.get("url_size_large") or im.get("url"), p):
                images.append(str(p.relative_to(inbox.parent)))
        text = (n.get("desc") or "").strip()
        transcript = ""
        if kind == "video" and tx:
            url = video_url(det, fav)
            try:
                transcript = tx(url) if url else ""
            except Exception as e:  # noqa: BLE001
                print(f"  转写失败 {nid}：{e}", file=sys.stderr)
        if transcript:
            text += "\n\n【视频逐字稿】\n" + transcript
        ts = n.get("time") or fav.get("create_time")
        share = ((det or {}).get("share_info") or {}).get("link") or ""
        token_url = ((det or {}).get("mini_program_info") or {}).get("webpage_url")
        rows.append({
            "id": f"xhs:{nid}", "source": "xiaohongshu", "kind": kind,
            "time": dt.datetime.fromtimestamp(ts, CST).isoformat() if ts else None,
            "title": n.get("title") or fav.get("title") or fav.get("display_title") or "",
            "url": token_url or share or f"https://www.xiaohongshu.com/explore/{nid}",
            "text": text, "images": images,
            "tags": [t["name"] for t in (n.get("hash_tag") or []) if t.get("name")],
            "author": ((n.get("user") or {}).get("nickname")),
            "full_text": det is not None, "transcribed": bool(transcript),
        })
        print(f"③ {i}/{len(favs)} {kind} {rows[-1]['title'][:20]} · 图 {len(images)} · 逐字稿 {len(transcript)} 字",
              flush=True)

    path = inbox / f"xiaohongshu-{dt.date.today().isoformat()}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✓ {len(rows)} 条 → {path}（{int(time.time() - t0)} 秒）；接着跑 python3 run.py ingest {inbox}")


if __name__ == "__main__":
    main()
