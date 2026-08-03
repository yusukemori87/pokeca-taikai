#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""デモ用のサンプルデータを、実行日を基準に生成する。中身は架空。"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
now = datetime.now(JST)


def d(offset: int) -> str:
    return (now + timedelta(days=offset)).strftime("%Y-%m-%d")


def next_sat(week: int = 0) -> str:
    off = (5 - now.weekday()) % 7 + week * 7
    return d(off)


def next_sun(week: int = 0) -> str:
    off = (6 - now.weekday()) % 7 + week * 7
    return d(off)


SAMPLE = [
    ("第12回 秋葉原ポケカ杯", next_sat(), "10:30", "東京都", "秋葉原カードスタジアム", False,
     "1,500円", 64, "優勝：BOX×2＋オリジナルプレイマット / 参加賞：スリーブ", "スタンダード",
     "スイスドロー5回戦＋決勝トーナメント。初参加の方も歓迎です。デッキシート提出あり。", "akiba_pokeca"),
    ("なにわ自主大会 〜夏の陣〜", next_sat(), "13:00", "大阪府", "日本橋バトルスペース", False,
     "1,000円", 48, "優勝：BOX×1 / 上位8名：パック", "スタンダード",
     "大阪日本橋で開催する自主大会です。当日受付16名まで。会場は駅から徒歩5分。", "naniwa_tcg"),
    ("札幌ポケカフェスタ", next_sun(), "11:00", "北海道", "札幌駅前イベントホール", False,
     "2,000円", 96, "優勝：BOX×3＋トロフィー / 抽選：SAR", "スタンダード",
     "道内最大級の自主大会。物販ブース・フリマスペースも併設しています。", "sapporo_pokeca"),
    ("エクストラ限定！博多杯", next_sun(), "12:30", "福岡県", "天神カードショップ2F", False,
     "1,200円", 32, "優勝：エクストラ用旧カード詰め合わせ", "エクストラ",
     "エクストラレギュレーション限定の自主大会。レンタルデッキの貸出もあります。", "hakata_ex"),
    ("リモートポケカ杯 #38", d(4), "20:00", "オンライン", None, True,
     "無料", 128, "優勝：Amazonギフト券5,000円分", "スタンダード",
     "Discordで開催するオンライン自主大会。全国どこからでも参加できます。", "remote_pokeca"),
    ("名古屋大須ポケカバトル", next_sat(1), "10:00", "愛知県", "大須アメ横ビル イベントスペース", False,
     "1,000円", 40, "優勝：BOX×2 / 参加賞：プロモカード", "スタンダード",
     "大須の常設自主大会。月2回開催、リピーター多数。初心者卓もご用意しています。", "osu_pokeca"),
    ("仙台ポケカ交流会＆ミニ大会", next_sat(1), "14:00", "宮城県", "仙台市青葉区 貸会議室A", False,
     "800円", 24, "優勝：パック10袋", "スタンダード",
     "対戦よりも交流メインのゆるめの会。デッキ相談・調整の時間もあります。", "sendai_pokeca"),
    ("横浜ジュニア＆シニア限定杯", next_sun(1), "10:00", "神奈川県", "横浜産貿ホール", False,
     "500円", 60, "全員に参加賞 / 優勝：BOX×1", "スタンダード",
     "中学生以下限定の自主大会です。保護者の見学スペースあり。", "yokohama_jr"),
    ("広島ポケカ交流杯", next_sun(1), "13:00", "広島県", "広島駅前カードショップ", False,
     "1,000円", 32, "優勝：BOX×1 / 上位入賞：パック", "スタンダード",
     "広島駅から徒歩3分。3ヶ月に1度の開催です。", "hiroshima_tcg"),
    ("ハーフデッキ祭り in 池袋", d(11), "18:30", "東京都", "池袋サンシャイン通り店", False,
     "700円", 24, "優勝：好きなパック5袋", "レギュ限定",
     "30枚デッキの変則ルール大会。平日夜開催なので仕事帰りでも参加しやすい。", "ikebukuro_half"),
    ("那覇ポケカサマーカップ", d(13), "11:00", "沖縄県", "那覇市 県民ひろばイベント室", False,
     "1,500円", 48, "優勝：BOX×2＋沖縄特産品セット", "スタンダード",
     "夏休み特別開催。県外からの参加も歓迎です。", "naha_pokeca"),
    ("京都かわらまち杯", d(16), "12:00", "京都府", "河原町TCGスペース", False,
     "1,000円", 32, "優勝：BOX×1", "スタンダード",
     "月イチ開催の京都の自主大会。落ち着いた雰囲気で対戦できます。", "kyoto_kawara"),
]

events = []
for i, (title, date, t, pref, venue, online, fee, cap, prize, fmt, summary, handle) in enumerate(SAMPLE):
    cid = f"SAMPLE{i:02d}"
    events.append({
        "id": cid,
        "title": title,
        "url": f"https://tonamel.com/competition/{cid}",
        "date": date,
        "start_time": t,
        "prefecture": pref,
        "venue": venue,
        "online": online,
        "fee": fee,
        "capacity": cap,
        "prize": prize,
        "format": fmt,
        "summary": summary,
        "source_tweet_url": f"https://x.com/{handle}/status/1234567890{i:02d}",
        "organizer_handle": handle,
        "organizer_name": title.split("（")[0],
        "tweeted_at": (now - timedelta(days=3)).isoformat(),
        "collected_at": now.isoformat(),
    })

events.sort(key=lambda e: (e["date"], e["start_time"]))
out = ROOT / "data" / "events.sample.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(
    json.dumps({"generated_at": now.isoformat(), "count": len(events), "events": events},
               ensure_ascii=False, indent=2), "utf-8")
print(f"サンプル {len(events)}件を書き出しました: {out}")
