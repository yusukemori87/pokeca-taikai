#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel の「主催者ページ」を巡回して、その主催者の大会を全部拾う。

なぜこれが要るのか:
  一度でも掲載できた主催者は、Tonamel上の主催者ページ(organization)が分かっている。
  そのページには、その人が立てた大会が並ぶ。つまり
  「主催者を1人見つけたら、その人の次回以降の大会は自動で拾える」経路になる。

  この経路は Twitter を一切使わない。twitterapi.io が止まっていても動く。
  実際に twitterapi.io が「成功応答なのに中身が空」で止まった際、
  収集が丸ごと止まってしまったので、独立した経路として用意した。

主催者ページもJavaScript描画なので、素のHTTPでは空。ヘッドレスブラウザで描画する。
取れたIDは data/pending.json に積み、続く collect.py が詳細を取得する。

  python scripts/collect_orgs.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JST = timezone(timedelta(hours=9))

# 巡回する主催者ページ数の上限（多すぎると1回の実行が長くなる）
MAX_ORGS = int(os.environ.get("ORG_PAGE_LIMIT", "120"))
# 1ページあたりのスクロール回数。主催者ページは件数が少ないので浅くてよい。
# 100人以上を巡回するので、1人あたりの時間がそのまま実行時間に効く。
MAX_SCROLL = int(os.environ.get("ORG_MAX_SCROLL", "5"))
# 巡回全体の時間予算（秒）。毎日走るので、途中で切り上げても翌日続きが回る。
TIME_BUDGET_SEC = int(os.environ.get("ORG_TIME_BUDGET", "900"))
# Tonamelのページ内リンクに現れる「大会IDではない語」。ゴミIDとして積むと
# 取得失敗が積み上がるので弾く（実際に "index" や "_competitionId" が混入した）。
NOT_AN_ID = {"index", "create", "search", "detail", "edit", "admin", "login",
             "entry", "result", "results", "about", "terms", "privacy",
             "organize", "organization", "competition", "competitions"}
# Nuxtの動的ルート名 "/competition/_competitionId" を拾わないよう英数字のみに限定する
COMP_RE = re.compile(r"/competition/([A-Za-z0-9]{5,12})")
ORG_RE = re.compile(r"tonamel\.com/organization/([A-Za-z0-9]{4,12})")


def log(m: str) -> None:
    print(f"[{datetime.now(JST):%H:%M:%S}] {m}", flush=True)


def org_urls() -> list[str]:
    """掲載済みの大会から主催者ページのURLを集める。よく主催する人を先に回る。"""
    try:
        events = json.loads((DATA / "events.json").read_text("utf-8"))["events"]
    except Exception:  # noqa: BLE001
        return []
    ids: Counter = Counter()
    for e in events:
        m = ORG_RE.search(e.get("organizer_url") or "")
        if m:
            ids[m.group(1)] += 1
    return [f"https://tonamel.com/organization/{i}" for i, _ in ids.most_common(MAX_ORGS)]


def collect(page, url: str) -> set[str]:
    ids: set[str] = set()
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
    except Exception as e:  # noqa: BLE001
        log(f"  読み込み失敗 {url}: {str(e)[:70]}")
        return ids
    page.wait_for_timeout(2500)

    last = -1
    for i in range(MAX_SCROLL):
        ids |= {c for c in COMP_RE.findall(page.content()) if c.lower() not in NOT_AN_ID}
        # 「もっと見る」を探す処理は当たらないと待ち時間だけ食う。
        # 100人以上を巡回するので、増えなくなったときだけ試す。
        if len(ids) == last:
            try:
                b = page.get_by_text("もっと見る", exact=False).first
                if b.is_visible(timeout=400):
                    b.click(timeout=1500)
                    page.wait_for_timeout(1200)
            except Exception:  # noqa: BLE001
                pass
        page.mouse.wheel(0, 16000)
        page.wait_for_timeout(800)
        if len(ids) == last and i > 1:
            break
        last = len(ids)
    ids |= {c for c in COMP_RE.findall(page.content()) if c.lower() not in NOT_AN_ID}
    return ids


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        log("playwright が入っていません。スキップします。")
        return 0

    urls = org_urls()
    if not urls:
        log("主催者ページのURLが1件もありません。events.json を確認してください。")
        return 0
    log(f"■ 主催者ページを {len(urls)}件 巡回します")

    all_ids: set[str] = set()
    empty = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(
            locale="ja-JP",
            user_agent="Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
            viewport={"width": 1280, "height": 2000},
        )
        page = ctx.new_page()
        started = time.monotonic()
        done = 0
        for n, u in enumerate(urls, 1):
            # 全体の時間予算。1人あたりが遅いと全体が何時間にもなりうるので、
            # 決めた時間で必ず切り上げる。残りは翌日の実行に回る（毎日走るので問題ない）。
            if time.monotonic() - started > TIME_BUDGET_SEC:
                log(f"  時間の上限({TIME_BUDGET_SEC}秒)に達したので"
                    f"{n - 1}/{len(urls)}人で切り上げます。残りは次回に回します。")
                break
            got = collect(page, u)
            done = n
            if not got:
                empty += 1
            all_ids |= got
            if n % 20 == 0:
                log(f"  {n}/{len(urls)}件 巡回 … 累計 大会ID {len(all_ids)}件")
        browser.close()
    urls = urls[:done] if done else urls

    log(f"■ 主催者ページから回収した大会ID: {len(all_ids)}件"
        f"（1件も取れなかった主催者 {empty}/{len(urls)}）")
    # 全滅は「ページ構造が変わった」サイン。黙って0件で終わらせない。
    if empty == len(urls):
        log("  ★異常: すべての主催者ページで0件でした。ページ構造が変わった可能性があります。")
        return 0

    known: set[str] = set()
    try:
        known = {e["id"] for e in json.loads(
            (DATA / "events.json").read_text("utf-8"))["events"]}
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
                        "url": None, "author": {}, "_source": "tonamel_org"}
        added += 1
    (DATA / "pending.json").write_text(
        json.dumps(pending, ensure_ascii=False, indent=1), "utf-8")
    log(f"■ 新規 {added}件を pending に追加（既知 {len(all_ids) - added}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
