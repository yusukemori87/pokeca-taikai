#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
取りこぼしの原因を切り分ける診断スクリプト。

(A) Twitter側: クエリの形を変えて、対象の大会が「そもそも検索に出てくるのか」を見る
(B) Tonamel側: 主催者ページ(organization)から大会一覧を辿れるかを見る
    → 辿れるなら、Twitterに頼らず主催者ごとに全大会を取得できる（クレジット消費ゼロ）
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug"
API = "https://api.twitterapi.io/twitter/tweet/advanced_search"
KEY = os.environ.get("TWITTERAPI_IO_KEY", "").strip()
UA = {"User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)"}

# collect.py が実際に投げている形（10人をORでまとめる）が効いているかを検証する。
# 単体の from: は効くのに、ORでまとめると壊れる、という可能性を潰す。
CHUNK10 = ("(from:deregmu_og OR from:deregmu_hobby OR from:tomoshibi_cup OR "
           "from:ISHIKAWAPOKECA OR from:kajipoke OR from:koshigym0428 OR "
           "from:Toreca_connect OR from:ohara_las_0123 OR from:kayu_key_gx OR "
           "from:nanase_cup)")
CHUNK3 = "(from:deregmu_og OR from:deregmu_hobby OR from:tomoshibi_cup)"

QUERIES = ["from:deregmu_og"]


def search(q: str, since: str, pages: int = 2) -> list[dict]:
    out: list[dict] = []
    cursor = ""
    for _ in range(pages):
        p = {"query": f"{q} since:{since}", "queryType": "Latest"}
        if cursor:
            p["cursor"] = cursor
        try:
            r = requests.get(API, params=p, headers={"X-API-Key": KEY}, timeout=40)
        except Exception as e:  # noqa: BLE001
            return out + [{"_error": str(e)[:120]}]
        if r.status_code != 200:
            return out + [{"_status": r.status_code, "_body": r.text[:200]}]
        b = r.json()
        out += b.get("tweets") or []
        if not b.get("has_next_page"):
            break
        cursor = b.get("next_cursor") or ""
        time.sleep(5.5)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    since = os.environ.get("DIAG_SINCE", "2026-04-01")
    report: dict = {"since": since, "twitter": {}, "tonamel_org": {}}

    # ---- (A) Twitter クエリの効き方を比べる
    if KEY:
        for q in QUERIES:
            tws = search(q, since)
            blob = json.dumps(tws, ensure_ascii=False)
            # 短縮表示(display_url)由来の切れたIDを拾わないよう5文字以上に限定
            ids = sorted({i for i in re.findall(
                r"tonamel\.com\\?/competition\\?/([A-Za-z0-9_-]+)", blob) if len(i) >= 5})
            report["twitter"][q] = {
                "tweets": len([t for t in tws if t.get("id")]),
                "tonamel_ids": ids[:40],
                "samples": [
                    {
                        "at": t.get("createdAt"),
                        "by": (t.get("author") or {}).get("userName"),
                        "text": (t.get("text") or "")[:400],
                        "url_fields": sorted(set(re.findall(r'https?://[^\s"\\]+', json.dumps(t, ensure_ascii=False))))[:12],
                        "top_keys": sorted(t)[:20],
                    }
                    for t in tws[:5] if t.get("id")
                ],
                "error": next((t for t in tws if "_error" in t or "_status" in t), None),
            }
            print(f"[{q}] -> {report['twitter'][q]['tweets']}件 / tonamel {len(ids)}件")
            time.sleep(5.5)
    else:
        report["twitter"]["_skipped"] = "TWITTERAPI_IO_KEY 未設定"

    # ---- (A1) ユーザーのタイムラインを取る専用APIが使えるかを確認する。
    if KEY:
        for ep in ["https://api.twitterapi.io/twitter/user/last_tweets",
                   "https://api.twitterapi.io/twitter/user/tweets",
                   "https://api.twitterapi.io/twitter/user/timeline",
                   "https://api.twitterapi.io/twitter/user_tweets"]:
            for pname in ["userName", "username", "screen_name"]:
                try:
                    rr = requests.get(ep, params={pname: "deregmu_og"},
                                      headers={"X-API-Key": KEY}, timeout=30)
                    body = rr.text[:700]
                    n = body.count('"id"')
                    report.setdefault("timeline", []).append(
                        {"ep": ep, "param": pname, "status": rr.status_code,
                         "approx_items": n, "head": body[:350]})
                    print(f"[timeline] {rr.status_code} {ep}?{pname}= -> ~{n}")
                    if rr.status_code == 200 and n:
                        break
                except Exception as e:  # noqa: BLE001
                    report.setdefault("timeline", []).append({"ep": ep, "error": str(e)[:100]})
                time.sleep(5.5)

    # ---- (A2) ツイートIDから直接引く。from: が効かないのは
    #      アカウント名が変わっている可能性があるため、実際の userName を確認する。
    if KEY:
        for tid in ["2066430513003589767"]:
            for ep, param in [
                ("https://api.twitterapi.io/twitter/tweets", "tweet_ids"),
                ("https://api.twitterapi.io/twitter/tweet", "tweet_id"),
            ]:
                try:
                    rr = requests.get(ep, params={param: tid},
                                  headers={"X-API-Key": KEY}, timeout=30)
                    body = rr.text[:1200]
                    report.setdefault("by_id", []).append(
                        {"endpoint": ep, "status": rr.status_code, "body": body})
                    print(f"[by_id] {rr.status_code} {ep}")
                    if rr.status_code == 200:
                        print("   ", body[:500])
                except Exception as e:  # noqa: BLE001
                    report.setdefault("by_id", []).append({"endpoint": ep, "error": str(e)[:120]})
                time.sleep(5.5)

    # ---- (B) Tonamel の主催者ページから大会一覧を辿れるか
    try:
        ev = json.loads((ROOT / "data" / "events.json").read_text("utf-8"))
        org_urls = sorted({e["organizer_url"] for e in ev["events"] if e.get("organizer_url")})
    except Exception:  # noqa: BLE001
        org_urls = []
    report["organizer_url_count"] = len(org_urls)

    for u in org_urls[:3]:
        try:
            r = requests.get(u, headers=UA, timeout=25)
            r.encoding = "utf-8"
            html = r.text
            ids = sorted(set(re.findall(r"/competition/([A-Za-z0-9_-]{4,12})", html)))
            report["tonamel_org"][u] = {
                "status": r.status_code,
                "bytes": len(html),
                "competition_ids_in_html": ids[:40],
                "has_ld_json": "application/ld+json" in html,
            }
            print(f"[org] {u} -> HTMLから大会ID {len(ids)}件")
            (OUT / f"org-{u.rstrip('/').split('/')[-1]}.html").write_text(html, "utf-8")
        except Exception as e:  # noqa: BLE001
            report["tonamel_org"][u] = {"error": str(e)[:150]}
        time.sleep(1.5)

    (OUT / "search-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
    )
    print("\n書き出し:", OUT / "search-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
