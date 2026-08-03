#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel が裏で叩いていそうなAPIエンドポイントを総当たりで探す。
SPAは必ずどこかからJSONを取っているので、それを直接叩ければ
JS実行（Playwright）なしで正確な構造化データが手に入る。

  python scripts/debug_api.py [大会ID]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug"
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
    "Accept": "application/json, text/plain, */*",
}

CID = sys.argv[1] if len(sys.argv) > 1 else "mEavl"

CANDIDATES = [
    f"https://tonamel.com/api/competition/{CID}",
    f"https://tonamel.com/api/competitions/{CID}",
    f"https://tonamel.com/api/v1/competition/{CID}",
    f"https://tonamel.com/api/v1/competitions/{CID}",
    f"https://api.tonamel.com/competition/{CID}",
    f"https://api.tonamel.com/v1/competition/{CID}",
    f"https://tonamel.com/competition/{CID}.json",
    f"https://tonamel.com/_next/data/latest/competition/{CID}.json",
]


def looks_useful(text: str) -> dict:
    """返ってきた中身に、欲しい情報が入っていそうかを判定する。"""
    keys = ["title", "start", "date", "venue", "place", "entry", "capacity", "prize"]
    return {
        "json": text.lstrip().startswith(("{", "[")),
        "hit_keys": [k for k in keys if f'"{k}' in text.lower()],
        "jp_chars": len(re.findall(r"[ぁ-んァ-ヶ一-龥]", text)),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []

    # 1) 素直な候補を順に叩く
    for url in CANDIDATES:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            info = {"url": url, "status": r.status_code, "bytes": len(r.text)}
            if r.status_code == 200:
                info.update(looks_useful(r.text))
                (OUT / f"api-{url.split('/')[-1][:40]}.txt").write_text(r.text[:200000], "utf-8")
        except Exception as e:  # noqa: BLE001
            info = {"url": url, "error": str(e)[:120]}
        results.append(info)
        print(json.dumps(info, ensure_ascii=False))

    # 2) HTML内のJSバンドルからAPIらしきパスを拾う（当てずっぽうより確実）
    try:
        html = requests.get(
            f"https://tonamel.com/competition/{CID}", headers=UA, timeout=25
        ).text
        paths = sorted(set(re.findall(r'["\'](/api/[A-Za-z0-9_\-/{}$.]+)["\']', html)))
        scripts = sorted(set(re.findall(r'src="(/_next/static/[^"]+\.js)"', html)))[:6]
        for s in scripts:
            try:
                js = requests.get("https://tonamel.com" + s, headers=UA, timeout=25).text
                paths += re.findall(r'["\'](/api/[A-Za-z0-9_\-/{}$.]+)["\']', js)
                paths += re.findall(r'["\'](https://[a-z0-9.\-]*tonamel[^"\']*api[^"\']*)["\']', js)
            except Exception:  # noqa: BLE001
                continue
        found = sorted(set(paths))
        print("\n--- JS内で見つかったAPIらしきパス ---")
        for p in found[:60]:
            print("  ", p)
        results.append({"discovered_api_paths": found[:60], "scripts_scanned": scripts})
    except Exception as e:  # noqa: BLE001
        results.append({"discovery_error": str(e)[:200]})

    (OUT / "api-report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), "utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
