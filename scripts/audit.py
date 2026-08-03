#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
収集結果を自分で点検して、怪しいところを洗い出す。

「ユーザーに指摘されてから直す」のをやめるための仕組み。
毎回の収集後に走り、下のような“におい”を検出して data/audit.json に書き出す。
GitHub Actions のログにも出るので、放置していても異常に気づける。

検出するもの:
  - 都道府県が取れていない大会
  - 会場名に県名があるのにオンライン判定になっている（＝誤判定の典型）
  - 景品や参加費が明らかにおかしい（助詞始まり、長すぎる、否定文）
  - 定員に対して極端な値
  - 取得に失敗し続けている大会（pending に溜まりっぱなし）
  - 追跡しているのに1件も大会が取れていないキーマン（ハンドル間違いの疑い）
  - 主要地域で件数がゼロ（＝その地域を丸ごと取りこぼしている疑い）
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JST = timezone(timedelta(hours=9))

REGIONS = {
    "北海道・東北": ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "甲信越": ["新潟県", "山梨県", "長野県"],
    "北陸": ["富山県", "石川県", "福井県"],
    "東海": ["岐阜県", "静岡県", "愛知県", "三重県"],
    "近畿": ["滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
    "九州・沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
}
P2R = {p: r for r, ps in REGIONS.items() for p in ps}
PREF_RE = re.compile("|".join(P2R))


def main() -> int:
    try:
        d = json.loads((DATA / "events.json").read_text("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"events.json を読めません: {e}")
        return 0
    E = d.get("events", [])
    orgs = d.get("organizers", [])
    findings: list[dict] = []

    def add(level: str, kind: str, msg: str, ids: list[str] | None = None) -> None:
        findings.append({"level": level, "kind": kind, "message": msg,
                         "ids": (ids or [])[:20], "count": len(ids or [])})

    # --- 1. 都道府県が取れていない
    noloc = [e["id"] for e in E if not e.get("prefecture")]
    if noloc:
        add("warn", "地域未判定",
            f"{len(noloc)}件の大会で都道府県が判定できていません。"
            f"CITY_HINTS に地名を足すか、会場名の書き方を確認してください。", noloc)

    # --- 2. オンライン判定なのに会場に県名がある（誤判定の典型）
    bad_online = [e["id"] for e in E if e.get("online")
                  and PREF_RE.search(f"{e.get('venue') or ''}{e.get('address') or ''}")]
    if bad_online:
        add("error", "オンライン誤判定",
            f"{len(bad_online)}件が、会場に県名があるのにオンライン扱いになっています。", bad_online)

    # --- 3. 景品・参加費がおかしい
    bad_prize = [e["id"] for e in E if (p := e.get("prize")) and (
        re.match(r"^(優勝：)?[はがのをにでとも、。)）\]】>＞]", p)
        or re.search(r"(ございません|ありません)", p)
        or len(p) > 70)]
    if bad_prize:
        add("warn", "景品の抽出ミス", f"{len(bad_prize)}件の景品が不自然です。", bad_prize)

    bad_fee = [e["id"] for e in E if (f := e.get("fee")) and (
        len(f) > 24 or re.match(r"^[はがのをにでとも、。)）]", f))]
    if bad_fee:
        add("warn", "参加費の抽出ミス", f"{len(bad_fee)}件の参加費が不自然です。", bad_fee)

    # --- 4. 定員が極端
    odd_cap = [e["id"] for e in E if (c := e.get("capacity")) and not (2 <= c <= 2000)]
    if odd_cap:
        add("warn", "定員が不自然", f"{len(odd_cap)}件の定員が極端な値です。", odd_cap)

    # --- 5. pending に溜まりっぱなし
    try:
        pend = json.loads((DATA / "pending.json").read_text("utf-8"))
        if len(pend) >= 5:
            add("warn", "取得に失敗し続けている",
                f"{len(pend)}件がTonamelから取得できないまま残っています。"
                f"削除済み・IDの誤抽出・アクセス制限のいずれかです。", list(pend))
    except Exception:  # noqa: BLE001
        pass

    # --- 6. 追跡しているのに1件も取れていないキーマン（ハンドル違いの疑い）
    got = Counter(e.get("organizer_handle") or e.get("announced_by") for e in E)
    try:
        seeds = json.loads((DATA / "organizers.seed.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        seeds = []
    silent = [s["handle"] for s in seeds if s.get("handle") and not got.get(s["handle"])]
    if silent:
        add("info", "登録キーマンの成果ゼロ",
            f"{len(silent)}人の登録キーマンから大会が1件も取れていません。"
            f"ハンドル違い、開催が先、または告知が別アカウントの可能性。", silent)

    # --- 7. 地域まるごとゼロ（取りこぼしの疑い）
    reg = Counter(P2R.get(e.get("prefecture") or "") for e in E)
    empty = [r for r in REGIONS if not reg.get(r)]
    if empty:
        add("warn", "地域まるごとゼロ",
            f"{'・'.join(empty)} の大会が0件です。実際に無いのか、取りこぼしかを確認してください。")

    # --- 8. 直近の追加が止まっていないか
    today = datetime.now(JST).strftime("%Y-%m-%d")
    recent = sum(1 for e in E if (e.get("collected_at") or "")[:10] == today)
    if E and recent == 0:
        add("info", "本日の新規ゼロ", "今日の実行で新しく取得された大会がありません。")

    report = {
        "generated_at": datetime.now(JST).isoformat(),
        "events": len(E),
        "organizers": len(orgs),
        "by_region": {r: reg.get(r, 0) for r in REGIONS},
        "findings": findings,
    }
    (DATA / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    print("=" * 60)
    print(f"自己点検: 大会 {len(E)}件 / キーマン {len(orgs)}人")
    print("地域別:", ", ".join(f"{r}{reg.get(r, 0)}" for r in REGIONS))
    if not findings:
        print("問題なし")
    for f in findings:
        mark = {"error": "!!", "warn": "! ", "info": "  "}[f["level"]]
        print(f"{mark} [{f['kind']}] {f['message']}")
        if f["ids"]:
            print(f"     例: {', '.join(f['ids'][:8])}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
