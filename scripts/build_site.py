#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
events.json を読み込んで、単体で動く docs/index.html を書き出す。
データをHTMLに埋め込むので、ファイルをダブルクリックするだけでも見られる。

  python scripts/build_site.py           # data/events.json を使う
  python scripts/build_site.py --sample  # data/events.sample.json を使う（デモ用）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "template.html"
OUT = ROOT / "docs" / "index.html"
PLACEHOLDER = "/*__EVENTS_JSON__*/"


def main() -> int:
    use_sample = "--sample" in sys.argv
    src = ROOT / "data" / ("events.sample.json" if use_sample else "events.json")

    if not src.exists():
        print(f"データがありません: {src}")
        print("先に scripts/collect.py を実行するか、--sample を付けてください。")
        return 1

    data = json.loads(src.read_text("utf-8"))
    data["sample"] = bool(use_sample)

    html = TEMPLATE.read_text("utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # </script> がデータ内に現れてもHTMLが壊れないようにエスケープ
    payload = payload.replace("</", "<\\/")

    # プレースホルダ直後のダミー既定値ごと置き換える
    idx = html.index(PLACEHOLDER)
    end = html.index("\n", idx)
    html = html[:idx] + payload + ";" + html[end:]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, "utf-8")
    print(f"書き出しました: {OUT}  （{data.get('count', len(data.get('events', [])))}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
