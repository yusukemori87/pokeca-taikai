#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tonamel の GraphQL スキーマを読んで「公開大会を検索するクエリ」を特定する。

イントロスペクションが有効だと分かったので、
  1. ルート(PlayerQuery)のフィールド一覧と引数を取る
  2. 大会検索に使えそうなフィールドを絞り込む
  3. Competition 型のフィールド一覧を取る
  4. 実際に叩いてみて結果を保存する
までを自動でやる。
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
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)",
    "Content-Type": "application/json",
}

Q_ROOT = """
query { __type(name: "%s") { name fields {
  name
  description
  args { name defaultValue type { kind name ofType { kind name ofType { kind name } } } }
  type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
} } }
"""

Q_TYPE = """
query { __type(name: "%s") { name kind
  enumValues { name }
  inputFields { name type { kind name ofType { kind name } } }
  fields { name type { kind name ofType { kind name ofType { kind name } } } }
} }
"""


def gql(query: str, sess: requests.Session) -> dict:
    try:
        r = sess.post(EP, json={"query": query}, headers=UA, timeout=30)
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)[:160]}


def unwrap(t: dict | None) -> str:
    """型のラッパー(NON_NULL/LIST)を剥がして名前を出す。"""
    names = []
    while t:
        if t.get("name"):
            names.append(t["name"])
        t = t.get("ofType")
    return names[-1] if names else "?"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    report: dict = {}

    root = gql(Q_ROOT % "PlayerQuery", sess)
    fields = (((root.get("data") or {}).get("__type") or {}).get("fields")) or []
    report["root_fields"] = [
        {"name": f["name"], "returns": unwrap(f.get("type")),
         "args": [{"name": a["name"], "type": unwrap(a.get("type"))} for a in f.get("args") or []],
         "desc": f.get("description")}
        for f in fields
    ]
    print(f"=== PlayerQuery のフィールド {len(fields)}件 ===")
    for f in report["root_fields"]:
        args = ", ".join(f"{a['name']}:{a['type']}" for a in f["args"])
        print(f"  {f['name']}({args}) -> {f['returns']}")

    # 大会検索に使えそうなフィールドを拾う
    KEY = re.compile(r"competition|tournament|event|search", re.I)
    cands = [f for f in report["root_fields"] if KEY.search(f["name"])]
    report["candidates"] = [c["name"] for c in cands]
    print("\n=== 大会検索の候補 ===")
    for c in cands:
        print(" ", c["name"], "->", c["returns"],
              "| args:", [a["name"] for a in c["args"]])

    # 関係しそうな型の中身を見る
    types_to_look = {c["returns"] for c in cands}
    for c in cands:
        for a in c["args"]:
            types_to_look.add(a["type"])
    report["types"] = {}
    for tname in sorted(types_to_look)[:14]:
        if tname in ("String", "Int", "Boolean", "ID", "?"):
            continue
        d = gql(Q_TYPE % tname, sess)
        t = (d.get("data") or {}).get("__type")
        if not t:
            continue
        report["types"][tname] = {
            "kind": t.get("kind"),
            "enumValues": [e["name"] for e in t.get("enumValues") or []][:60],
            "inputFields": [{"name": i["name"], "type": unwrap(i.get("type"))}
                            for i in t.get("inputFields") or []],
            "fields": [{"name": f["name"], "type": unwrap(f.get("type"))}
                       for f in t.get("fields") or []][:60],
        }
        print(f"\n--- 型 {tname} ({t.get('kind')}) ---")
        for k in ("enumValues", "inputFields", "fields"):
            v = report["types"][tname][k]
            if v:
                print(f"   {k}: {json.dumps(v, ensure_ascii=False)[:400]}")

    (OUT / "schema-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("\n書き出し:", OUT / "schema-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
