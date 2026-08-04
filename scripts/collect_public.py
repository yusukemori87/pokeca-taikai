#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel の「公開されている」ポケカ大会を、一覧ページから全件拾う。

Twitterに流れてこない公開大会を取りこぼさないための経路。
Tonamelの一覧はJavaScript描画なので素のHTTPでは空。ヘッドレスブラウザで
実際に描画し、無限スクロールを最後まで送ってから大会IDを回収する。

Twitterのクレジットは一切使わない。取れたIDは data/pending.json に積むので、
続く collect.py が Tonamel の大会ページから詳細を取得する。

  python scripts/collect_public.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JST = timezone(timedelta(hours=9))

# ポケカの公開大会一覧。パラメータの綴りが変わっても拾えるよう複数試す。
LIST_URLS = [
    "https://tonamel.com/competitions?game=pokemon_card&region=JP",
    "https://tonamel.com/competitions?game=pokemon_card",
    "https://tonamel.com/competitions?game=pokemon_card&region=JP&status=upcoming",
    "https://tonamel.com/competitions",
]
MAX_SCROLL = int(os.environ.get("PUBLIC_MAX_SCROLL", "60"))
# Tonamelのページ内リンクに現れる「大会IDではない語」。ゴミIDとして積むと
# 取得失敗が積み上がるので弾く（実際に "index" や "_competitionId" が混入した）。
NOT_AN_ID = {"index", "create", "search", "detail", "edit", "admin", "login",
             "entry", "result", "results", "about", "terms", "privacy",
             "organize", "organization", "competition", "competitions"}
# Nuxtの動的ルート名 "/competition/_competitionId" を拾わないよう英数字のみに限定する
COMP_RE = re.compile(r"/competition/([A-Za-z0-9]{5,12})")


def log(m: str) -> None:
    print(f"[{datetime.now(JST):%H:%M:%S}] {m}", flush=True)


def collect(page, url: str) -> set[str]:
    ids: set[str] = set()
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:  # noqa: BLE001
        log(f"  読み込み失敗 {url}: {str(e)[:80]}")
        return ids
    page.wait_for_timeout(4000)

    last = -1
    for i in range(MAX_SCROLL):
        found = {c for c in COMP_RE.findall(page.content()) if c.lower() not in NOT_AN_ID}
        # 「もっと見る」系のボタンがあれば押す
        for label in ("もっと見る", "さらに表示", "次へ", "Load more", "More"):
            try:
                b = page.get_by_text(label, exact=False).first
                if b.is_visible(timeout=800):
                    b.click(timeout=2500)
                    page.wait_for_timeout(1800)
            except Exception:  # noqa: BLE001
                pass
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(1400)
        ids |= found
        if len(ids) == last and i > 3:
            break            # 増えなくなったら終わり
        last = len(ids)
    ids |= {c for c in COMP_RE.findall(page.content()) if c.lower() not in NOT_AN_ID}
    log(f"  {url} -> 大会ID {len(ids)}件")
    return ids


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        log("playwright が入っていません。スキップします。")
        return 0

    all_ids: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            locale="ja-JP",
            user_agent="Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
            viewport={"width": 1280, "height": 2000},
        )
        page = ctx.new_page()
        for u in LIST_URLS:
            all_ids |= collect(page, u)
            if len(all_ids) > 400:      # 十分取れたら残りのURLは省く
                break
        browser.close()

    log(f"■ 公開一覧から回収した大会ID: {len(all_ids)}件")
    if not all_ids:
        log("  1件も取れませんでした。一覧ページの構造が変わった可能性があります。")
        return 0

    # 既に持っている大会は除き、未取得ぶんだけ pending に積む
    known: set[str] = set()
    try:
        known = {e["id"] for e in json.loads((DATA / "events.json").read_text("utf-8"))["events"]}
    except Exception:  # noqa: BLE001
        pass
    try:
        pending = json.loads((DATA / "pending.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        pending = {}

    added = 0
    for cid in sorted(all_ids):
        if cid in known or cid in pending:
            continue
        pending[cid] = {"id": None, "text": "", "createdAt": "",
                        "url": None, "author": {}, "_source": "tonamel_public"}
        added += 1
    (DATA / "pending.json").write_text(
        json.dumps(pending, ensure_ascii=False, indent=1), "utf-8")
    log(f"■ 新規 {added}件を pending に追加（既知 {len(all_ids) - added}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
