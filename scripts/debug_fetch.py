#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel の大会ページを数件だけ取得して、生HTMLと構造の要約を debug/ に書き出す。
「取れているのにパースできない」のか「そもそも中身が返ってきていない」のかを切り分けるため。

  python scripts/debug_fetch.py [大会ID ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug"
UA = {"User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)"}

# 既知の大会（seed由来なので実在が確実なもの）
DEFAULT_IDS = ["mEavl", "KYpP5", "YPWBV"]


def main() -> int:
    ids = sys.argv[1:] or DEFAULT_IDS
    OUT.mkdir(parents=True, exist_ok=True)
    report = []

    for cid in ids:
        url = f"https://tonamel.com/competition/{cid}"
        try:
            r = requests.get(url, headers=UA, timeout=30)
        except Exception as e:  # noqa: BLE001
            report.append({"id": cid, "error": str(e)})
            continue

        html = r.text
        (OUT / f"{cid}.html").write_text(html, "utf-8")

        # 中身の当たりをつけるための指標
        info = {
            "id": cid,
            "status": r.status_code,
            "bytes": len(html),
            "has__NEXT_DATA__": "__NEXT_DATA__" in html,
            "has__NUXT__": "__NUXT__" in html,
            "has_ld_json": "application/ld+json" in html,
            "has_apollo": "__APOLLO_STATE__" in html,
            "script_ids": re.findall(r'<script[^>]+id="([^"]+)"', html)[:10],
            "og_title": (re.search(r'property="og:title"[^>]*content="([^"]*)"', html) or [None, None])[1]
            if re.search(r'property="og:title"[^>]*content="([^"]*)"', html) else None,
            "og_desc_len": len(
                (re.search(r'property="og:description"[^>]*content="([^"]*)"', html) or ["", ""])[1]
            ),
            # 日本語らしい文字が本文にどれくらいあるか（SPAの殻だけなら極端に少ない）
            "jp_chars": len(re.findall(r"[ぁ-んァ-ヶ一-龥]", re.sub(r"<[^>]+>", " ", html))),
            "has_kaisai": "開催日時" in html or "開催日" in html,
            "has_kaijou": "会場" in html,
            "has_sankahi": "参加費" in html,
        }
        report.append(info)
        print(json.dumps(info, ensure_ascii=False))

    (OUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
    )
    print(f"\n書き出し: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
