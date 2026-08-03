#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel の GraphQL を調べる。

JSバンドルから /graphql, /graphql/competition/ などのエンドポイントが見つかったので、
(1) イントロスペクションが有効か
(2) 無効なら、JSに埋まっているクエリ本文を回収できるか
を確認する。狙いは「公開されている大会を検索して全件取る」クエリを見つけること。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug"
BASE = "https://tonamel.com"
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
    "Content-Type": "application/json",
    "Accept": "*/*",
}
ENDPOINTS = ["/graphql", "/graphql/competition/", "/graphql/competition"]

INTROSPECT = {
    "query": """
    query I { __schema { queryType { name }
      types { name kind fields { name args { name type { name kind ofType { name } } } } } } }
    """
}
# 型名だけの軽いイントロスペクション（フル版が弾かれる場合の保険）
INTROSPECT_LIGHT = {"query": "query { __schema { queryType { name } } }"}


def post(ep: str, payload: dict, sess: requests.Session) -> dict:
    url = BASE + ep
    try:
        r = sess.post(url, json=payload, headers=UA, timeout=30)
    except Exception as e:  # noqa: BLE001
        return {"ep": ep, "error": str(e)[:140]}
    out = {"ep": ep, "status": r.status_code, "bytes": len(r.text)}
    try:
        j = r.json()
        out["keys"] = list(j)[:6]
        if "errors" in j:
            out["errors"] = [str(e.get("message"))[:160] for e in j["errors"]][:4]
        if "data" in j and j["data"]:
            out["data_head"] = json.dumps(j["data"], ensure_ascii=False)[:400]
    except Exception:  # noqa: BLE001
        out["text_head"] = r.text[:250]
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"introspection": [], "gql_in_js": {}, "operation_names": []}

    sess = requests.Session()
    # CSRFトークンが要るかもしれないので先に取っておく
    try:
        t = sess.get(BASE + "/api/csrf_token", headers={"User-Agent": UA["User-Agent"]}, timeout=20)
        report["csrf"] = {"status": t.status_code, "head": t.text[:120]}
        m = re.search(r'"?(?:csrf_?token|token)"?\s*[:=]\s*"([^"]+)"', t.text)
        if m:
            UA["X-CSRF-Token"] = m.group(1)
            report["csrf"]["captured"] = True
    except Exception as e:  # noqa: BLE001
        report["csrf"] = {"error": str(e)[:120]}

    for ep in ENDPOINTS:
        report["introspection"].append(post(ep, INTROSPECT_LIGHT, sess))
        report["introspection"].append(post(ep, INTROSPECT, sess))

    # ---- JSバンドルからクエリ本文を回収
    try:
        html = sess.get(f"{BASE}/competition/mEavl",
                        headers={"User-Agent": UA["User-Agent"]}, timeout=25).text
        scripts = re.findall(r'src="(/nuxt/[^"]+\.js)"', html)
        ops: set[str] = set()
        found: dict[str, str] = {}
        for s in scripts[:16]:
            try:
                js = sess.get(BASE + s, headers={"User-Agent": UA["User-Agent"]}, timeout=30).text
            except Exception:  # noqa: BLE001
                continue
            # gqlテンプレートやクエリ文字列の断片
            for m in re.finditer(r"(query|mutation)\s+([A-Za-z0-9_]+)\s*[\(\{]", js):
                ops.add(f"{m.group(1)} {m.group(2)}")
            # 大会検索に関係しそうな語を含む箇所を切り出す
            for kw in ("competitions(", "searchCompetition", "publicCompetition",
                       "competitionList", "CompetitionSearch", "games(", "competition("):
                i = js.find(kw)
                if i > 0 and kw not in found:
                    found[kw] = js[max(0, i - 300): i + 700]
        report["operation_names"] = sorted(ops)[:80]
        report["gql_in_js"] = found
        print("見つかった operation 名:", len(ops))
        for o in sorted(ops)[:40]:
            print("   ", o)
    except Exception as e:  # noqa: BLE001
        report["js_error"] = str(e)[:200]

    (OUT / "graphql-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    for r in report["introspection"]:
        print(f"  {r.get('status', r.get('error'))} {r['ep']} "
              f"{r.get('errors') or r.get('data_head', '')[:120]}")
    print("\n書き出し:", OUT / "graphql-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
