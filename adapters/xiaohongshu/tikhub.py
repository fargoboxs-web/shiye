#!/usr/bin/env python3
"""TikHub 拿小红书公开收藏列表（替代 Apify 那一步）。

  python3 adapters/xiaohongshu/tikhub.py <主页链接或用户ID> [--max 0] [--out favs.jsonl]

接口：/api/v1/xiaohongshu/app_v2/get_user_faved_notes，一页约 6 条，每次请求扣费（约 $0.01）。
只能用充值余额，不吃注册送的免费额度。凭证只从环境变量 TIKHUB_API_KEY 读，不打印。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import sys as _sys; from pathlib import Path as _P; _sys.path.append(str(_P(__file__).resolve().parents[1]))
import env as _env; _env.load()  # 仓库根的 .env
API = "https://api.tikhub.io/api/v1/xiaohongshu/app_v2/get_user_faved_notes"


def user_id(profile: str) -> str:
    m = re.search(r"profile/([0-9a-f]{24})", profile) or re.fullmatch(r"([0-9a-f]{24})", profile.strip())
    if not m:
        sys.exit(f"认不出用户 ID：{profile}（要主页链接或 24 位 ID）")
    return m.group(1)


def page(uid: str, cursor: str) -> dict:
    key = os.environ.get("TIKHUB_API_KEY")
    if not key:
        sys.exit("缺 TIKHUB_API_KEY 环境变量")
    q = urllib.parse.urlencode({"user_id": uid, **({"cursor": cursor} if cursor else {})})
    req = urllib.request.Request(f"{API}?{q}", headers={"Authorization": f"Bearer {key}", "User-Agent": "curl/8.5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)["data"]["data"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code in (401, 402, 403):
                try:
                    body = json.loads(body)["detail"]["message_zh"]
                except Exception:  # noqa: BLE001
                    body = body[:200]
                sys.exit(f"TikHub 拒绝（{e.code}）：{body}")
            err = f"{e.code} {body[:200]}"
        except Exception as e:  # noqa: BLE001
            err = str(e)
        print(f"  TikHub 第 {attempt + 1} 次失败：{err}", file=sys.stderr)
        time.sleep(3 * (attempt + 1))
    sys.exit("TikHub 连续失败，停在这里")


def favorites(profile: str, limit: int = 0, cursor: str = "", rank: int = 0) -> list[dict]:
    """返回 [{id, type: video|post, display_title, xsec_token, author, published, fav_rank}]，按收藏顺序。"""
    uid, out, seen, n = user_id(profile), [], set(), 0
    while True:
        d = page(uid, cursor); n += 1
        # 接口偶尔中途回一页空的、说没有更多了，其实还有：同一个 cursor 再问两次确认
        for _ in range(2):
            if d.get("notes") or not cursor:
                break
            time.sleep(2)
            d = page(uid, cursor); n += 1
        for x in d.get("notes") or []:
            if x["id"] in seen:
                continue
            seen.add(x["id"])
            out.append({"id": x["id"], "type": "video" if x.get("type") == "video" else "post",
                        "display_title": x.get("display_title") or x.get("title") or "",
                        "xsec_token": x.get("xsec_token"), "author": (x.get("user") or {}).get("nickname"),
                        # create_time 是笔记发布时间；接口不给收藏时间，只有顺序（第 1 条是最近收藏的）
                        "published": x.get("create_time"), "fav_rank": rank + len(out) + 1})
        print(f"  第 {n} 页，累计 {len(out)} 条", flush=True)
        nxt = d.get("cursor") or ""
        if not d.get("has_more") or not nxt or nxt == cursor or (limit and len(out) >= limit):
            break
        cursor = nxt
    print(f"  TikHub 共请求 {n} 次")
    return out[:limit] if limit else out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--out", default="favs.jsonl")
    a = ap.parse_args()
    favs = favorites(a.profile, a.max)
    with open(a.out, "w", encoding="utf-8") as f:
        for x in favs:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"✓ {len(favs)} 条 → {a.out}")
