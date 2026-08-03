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

QUERIES = [
    "from:deregmu_og",
    "from:deregmu_hobby",
    "ディレグム",
    "ディレグム 大会",
    "富山 ポケカ 大会",
    "富山 ポケカ 自主大会",
    "tonamel.com 富山",
    "url:tonamel.com 富山",
]


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
            ids = sorted(set(re.findall(r"tonamel\.com/competition/([A-Za-z0-9_-]+)", blob)))
            report["twitter"][q] = {
                "tweets": len([t for t in tws if t.get("id")]),
                "tonamel_ids": ids[:40],
                "samples": [
                    {
                        "at": t.get("createdAt"),
                        "by": (t.get("author") or {}).get("userName"),
                        "text": (t.get("text") or "")[:200],
                    }
                    for t in tws[:3] if t.get("id")
                ],
                "error": next((t for t in tws if "_error" in t or "_status" in t), None),
            }
            print(f"[{q}] -> {report['twitter'][q]['tweets']}件 / tonamel {len(ids)}件")
            time.sleep(5.5)
    else:
        report["twitter"]["_skipped"] = "TWITTERAPI_IO_KEY 未設定"

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
