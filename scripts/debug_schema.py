#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel の GraphQL スキーマから「公開大会を検索するクエリ」を特定する。

__type(name:) と __schema.queryType.fields はどちらも空を返したが、
__schema.types { name fields { name args } } の形だけは通ることが分かっている。
そこで全型を一度に取得し、その中からルート型(PlayerQuery)と大会関連の型を探す。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug"
EP = "https://tonamel.com/graphql"
UA = {"User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
      "Content-Type": "application/json"}

Q = """
query { __schema {
  queryType { name }
  types {
    name kind
    fields { name args { name type { kind name ofType { kind name } } }
             type { kind name ofType { kind name ofType { kind name } } } }
    inputFields { name type { kind name ofType { kind name } } }
    enumValues { name }
  } } }
"""


def unwrap(t):
    names = []
    while t:
        if t.get("name"):
            names.append(t["name"])
        t = t.get("ofType")
    return names[-1] if names else "?"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.post(EP, json={"query": Q}, headers=UA, timeout=60)
        body = r.json()
    except Exception as e:  # noqa: BLE001
        (OUT / "schema-report.json").write_text(
            json.dumps({"error": str(e)[:200]}, ensure_ascii=False), "utf-8")
        print("失敗:", e)
        return 0

    if body.get("errors"):
        print("GraphQLエラー:", body["errors"][:2])
    sch = (body.get("data") or {}).get("__schema") or {}
    types = sch.get("types") or []
    print("取得した型数:", len(types))

    by_name = {t["name"]: t for t in types if t.get("name")}
    root_name = (sch.get("queryType") or {}).get("name") or "PlayerQuery"
    root = by_name.get(root_name) or {}
    rfields = root.get("fields") or []

    report = {
        "queryType": root_name,
        "root_fields": [
            {"name": f["name"],
             "args": [{"name": a["name"], "type": unwrap(a.get("type"))} for a in f.get("args") or []],
             "returns": unwrap(f.get("type"))}
            for f in rfields
        ],
        "type_count": len(types),
    }
    print(f"=== {root_name} のフィールド {len(rfields)}件 ===")
    for f in report["root_fields"]:
        print(f"  {f['name']}({', '.join(a['name']+':'+a['type'] for a in f['args'])}) -> {f['returns']}")

    KEY = re.compile(r"competition|tournament|event|search|public|list", re.I)
    cands = [f for f in report["root_fields"] if KEY.search(f["name"])]
    report["candidates"] = cands
    print("\n=== 大会検索の候補 ===")
    for c in cands:
        print(" ", c["name"], "->", c["returns"], "| args:", [a["name"] for a in c["args"]])

    # 候補の戻り値・引数の型の中身
    want = {c["returns"] for c in cands} | {a["type"] for c in cands for a in c["args"]}
    report["types"] = {}
    for n in sorted(want):
        t = by_name.get(n)
        if not t:
            continue
        report["types"][n] = {
            "kind": t.get("kind"),
            "fields": [{"name": f["name"], "type": unwrap(f.get("type"))} for f in t.get("fields") or []][:60],
            "inputFields": [{"name": f["name"], "type": unwrap(f.get("type"))} for f in t.get("inputFields") or []],
            "enumValues": [e["name"] for e in t.get("enumValues") or []][:60],
        }
        print(f"\n--- {n} ({t.get('kind')}) ---")
        for k in ("inputFields", "enumValues", "fields"):
            v = report["types"][n][k]
            if v:
                print(f"   {k}: {json.dumps(v, ensure_ascii=False)[:420]}")

    report["all_type_names"] = [t["name"] for t in types if not t["name"].startswith("__")]
    (OUT / "schema-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("\n書き出し:", OUT / "schema-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
