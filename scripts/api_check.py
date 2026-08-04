#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
twitterapi.io が使える状態かを1時間ごとに確認する。

いま起きている症状は「HTTP 200 で成功と返るのに中身が空」。
エラーにならないので、実際にデータが返るかどうかで判定する。

判定に使うのは、投稿が多く確実に結果が返るはずのアカウントと、
ヒットして当然の一般的なキーワード。両方とも空なら異常とみなす。

結果は data/api_status.json に残す。
「異常 → 正常」に変わったときだけ .trigger を更新して収集を自動再開する。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JST = timezone(timedelta(hours=9))
KEY = os.environ.get("TWITTERAPI_IO_KEY", "").strip()
SEARCH = "https://api.twitterapi.io/twitter/tweet/advanced_search"
TIMELINE = "https://api.twitterapi.io/twitter/user/last_tweets"
BY_ID = "https://api.twitterapi.io/twitter/tweets"

# 復旧確認に使う「必ず結果が返るはず」の対象
PROBE_HANDLE = "deregmu_og"          # 以前は40件返っていた
PROBE_QUERY = "ポケモンカード"          # 一般的すぎて0件はありえない
PROBE_TWEET = "2081303514899456480"  # 実在が確実なツイート


def probe() -> dict:
    since = (datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")
    out: dict = {"checked_at": datetime.now(JST).isoformat()}

    def get(url, params):
        try:
            r = requests.get(url, params=params, headers={"X-API-Key": KEY}, timeout=30)
            return r.status_code, (r.json() if r.headers.get(
                "content-type", "").startswith("application/json") else {})
        except Exception as e:  # noqa: BLE001
            return None, {"_err": str(e)[:120]}

    st, b = get(SEARCH, {"query": f"{PROBE_QUERY} since:{since}", "queryType": "Latest"})
    out["search"] = {"status": st, "n": len(b.get("tweets") or [])}
    time.sleep(6)

    st, b = get(TIMELINE, {"userName": PROBE_HANDLE})
    tws = (b.get("data") or {}).get("tweets") if isinstance(b.get("data"), dict) else None
    out["timeline"] = {"status": st, "n": len(tws or b.get("tweets") or [])}
    time.sleep(6)

    st, b = get(BY_ID, {"tweet_ids": PROBE_TWEET})
    out["by_id"] = {"status": st, "n": len(b.get("tweets") or [])}

    # 検索かタイムラインのどちらかが結果を返せば「使える」とみなす
    out["ok"] = bool(out["search"]["n"] or out["timeline"]["n"])
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    if not KEY:
        print("APIキーが未設定のため確認できません")
        return 0

    prev = {}
    try:
        prev = json.loads((DATA / "api_status.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        pass

    cur = probe()
    was_ok = bool(prev.get("ok"))
    cur["previous_ok"] = was_ok
    cur["recovered"] = (not was_ok) and cur["ok"]
    (DATA / "api_status.json").write_text(
        json.dumps(cur, ensure_ascii=False, indent=2), "utf-8")

    mark = "正常" if cur["ok"] else "異常（成功応答だが中身が空）"
    print(f"[{cur['checked_at'][:16]}] twitterapi.io: {mark}")
    print(f"  検索={cur['search']} タイムライン={cur['timeline']} ID直引き={cur['by_id']}")

    if cur["recovered"]:
        print("★ 復旧を検出しました。収集を自動的に再開します。")
        (ROOT / ".trigger").write_text(
            f"auto: api recovered at {cur['checked_at']}\n", "utf-8")
    elif not cur["ok"]:
        print("  まだ復旧していません。1時間後に再確認します。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
