#!/usr/bin/env python3
"""events.json の「中身」の指紋を出す。時刻だけの変化は無視する。"""
import hashlib, json, sys

# 実行するたびに必ず変わるので、比較から外す項目
SKIP = {"collected_at", "tweeted_at", "pv"}

def fingerprint(path):
    d = json.load(open(path, encoding="utf-8"))
    rows = []
    for e in sorted(d.get("events", []), key=lambda x: x.get("id") or ""):
        rows.append({k: v for k, v in sorted(e.items()) if k not in SKIP})
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()

if __name__ == "__main__":
    print(fingerprint(sys.argv[1]))
