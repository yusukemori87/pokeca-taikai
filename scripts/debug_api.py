#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel が裏で叩いているAPIを突き止める。

目的は「Tonamelの公開大会を100%拾う」こと。
公開一覧ページ(/competitions)はJS描画で素のHTTPでは中身が空だが、
SPAである以上どこかからJSONを取っているはず。それを直接叩ければ、
Twitterに一切依存せず公開分を全件取得できる。

  python scripts/debug_api.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug"
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
    "Accept": "application/json, text/plain, */*",
}
CID = "mEavl"          # 実在が確実な大会
ORG = "rnQK9"          # その主催者


def probe(url: str, **kw) -> dict:
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": str(e)[:120]}
    info = {"url": url, "status": r.status_code, "bytes": len(r.text),
            "ctype": r.headers.get("content-type", "")[:60]}
    if r.status_code == 200 and len(r.text) < 400000:
        t = r.text
        info["is_json"] = t.lstrip().startswith(("{", "["))
        info["comp_ids"] = sorted(set(re.findall(r'"(?:id|slug|key)"\s*:\s*"([A-Za-z0-9_-]{5})"', t)))[:20]
        info["jp"] = len(re.findall(r"[ぁ-んァ-ヶ一-龥]", t))
        info["head"] = t[:300]
    return info


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"candidates": [], "discovered": [], "graphql": None}

    # ---- 1) ありがちなREST候補
    cands = [
        f"https://tonamel.com/api/competition/{CID}",
        f"https://tonamel.com/api/competitions/{CID}",
        f"https://tonamel.com/api/v1/competition/{CID}",
        f"https://tonamel.com/api/organization/{ORG}/competitions",
        "https://tonamel.com/api/competitions?game=pokemon_card&region=JP",
        "https://tonamel.com/api/search/competitions?game=pokemon_card",
        "https://api.tonamel.com/competition/" + CID,
        "https://api.tonamel.com/v1/competitions?game=pokemon_card",
    ]
    for u in cands:
        info = probe(u)
        report["candidates"].append(info)
        print(f"  {info.get('status', info.get('error'))}  {u}")
        time.sleep(0.8)

    # ---- 2) JSバンドルを読んでAPIのパスとGraphQLエンドポイントを探す
    try:
        html = requests.get(f"https://tonamel.com/competition/{CID}",
                            headers=UA, timeout=25).text
        scripts = re.findall(r'src="(/nuxt/[^"]+\.js)"', html)
        print(f"\n  JSバンドル {len(scripts)}本を走査")
        paths: set[str] = set()
        gql: set[str] = set()
        for s in scripts[:12]:
            try:
                js = requests.get("https://tonamel.com" + s, headers=UA, timeout=30).text
            except Exception:  # noqa: BLE001
                continue
            paths |= set(re.findall(r'["\'`](/api/[A-Za-z0-9_\-/{}$.:]+)["\'`]', js))
            paths |= set(re.findall(r'["\'`](https://[a-z0-9.\-]*tonamel[a-z0-9.\-]*/[A-Za-z0-9_\-/{}$.:]*api[A-Za-z0-9_\-/{}$.:]*)["\'`]', js))
            gql |= set(re.findall(r'["\'`]([^"\'`]*graphql[^"\'`]*)["\'`]', js))
            gql |= set(re.findall(r'["\'`](https://[a-z0-9.\-]+\.appsync-api\.[^"\'`]+)["\'`]', js))
            gql |= set(re.findall(r'["\'`](https://[a-z0-9]+\.execute-api\.[^"\'`]+)["\'`]', js))
        report["discovered"] = sorted(paths)[:80]
        report["graphql"] = sorted(gql)[:40]
        print("  /api/ らしきパス:", len(paths))
        for p in sorted(paths)[:30]:
            print("     ", p)
        print("  graphql らしき文字列:", len(gql))
        for g in sorted(gql)[:20]:
            print("     ", g[:140])
    except Exception as e:  # noqa: BLE001
        report["discover_error"] = str(e)[:200]

    # ---- 3) 公開一覧ページそのものも保存しておく
    for u in ["https://tonamel.com/competitions?game=pokemon_card&region=JP",
              f"https://tonamel.com/organization/{ORG}"]:
        try:
            r = requests.get(u, headers=UA, timeout=25)
            r.encoding = "utf-8"
            name = re.sub(r"\W+", "-", u.split("tonamel.com/")[-1])[:50]
            (OUT / f"page-{name}.html").write_text(r.text, "utf-8")
        except Exception:  # noqa: BLE001
            pass

    (OUT / "api-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("\n書き出し:", OUT / "api-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
