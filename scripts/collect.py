#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ポケカ自主大会コレクター
=======================
Twitter(X) を検索して「Tonamel の大会URLが貼られたポケカ自主大会の告知ツイート」を拾い、
Tonamel の大会ページ本体から日時・会場・参加費・定員・景品を取り出して JSON に正規化する。

なぜこの作り方なのか:
  多くの主催者は Tonamel の大会を「検索に出ない設定」にしているが、
  URL を知っていればページ自体は開ける。つまり Twitter が“URLの配布経路”になっている。
  → Twitter から URL を集め、正確な情報は Tonamel ページから取る、という二段構え。

使い方:
  export TWITTERAPI_IO_KEY="xxxxx"
  python scripts/collect.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

# ---------------------------------------------------------------- 設定

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "events.json"
RAW_DIR = DATA_DIR / "raw"          # チューニング用の生HTML置き場

JST = timezone(timedelta(hours=9))

API_BASE = "https://api.twitterapi.io/twitter/tweet/advanced_search"
API_KEY = os.environ.get("TWITTERAPI_IO_KEY", "").strip()

# 何日前までさかのぼって告知ツイートを探すか
# 自主大会は1〜2ヶ月前に告知されるので、3ヶ月先まで拾うには広めに取る
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "45"))
# 開催日が今日から何日先までを掲載対象にするか（3ヶ月＝約92日）
HORIZON_DAYS = int(os.environ.get("HORIZON_DAYS", "95"))
# 1クエリあたり最大何ページ取るか（1ページ ≒ 20件）
MAX_PAGES_PER_QUERY = int(os.environ.get("MAX_PAGES_PER_QUERY", "8"))
# キーマン(主催者)アカウントを from: 検索で追いかけるか
FOLLOW_ORGANIZERS = os.environ.get("FOLLOW_ORGANIZERS", "1") == "1"

# 検索クエリ。Twitter の検索演算子がそのまま使える。
# 「tonamel の URL を含む」×「ポケカ語彙」の掛け算で、余計なゲームの大会を弾く。
SEARCH_QUERIES = [
    'url:tonamel.com (ポケカ OR ポケモンカード) -filter:retweets',
    'url:tonamel.com 自主大会 (ポケカ OR ポケモンカード) -filter:retweets',
    'tonamel.com (ポケカ OR ポケモンカード) 大会 -filter:retweets',
    '(ポケカ OR ポケモンカード) 自主大会 (エントリー OR 募集 OR 参加者募集) -filter:retweets',
    '(ポケカ OR ポケモンカード) 非公認大会 (募集 OR 開催) -filter:retweets',
]

# ポケカ以外(ポケポケ/ユニアリ等)を弾くためのネガティブ語
NEGATIVE_WORDS = ["ポケポケ", "ポケモンカードアプリ", "ポケモンTCGポケット", "Pocket"]

TONAMEL_RE = re.compile(r"https?://tonamel\.com/competition/([A-Za-z0-9_-]+)")
TCO_RE = re.compile(r"https?://t\.co/[A-Za-z0-9]+")

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
# 「東京」「大阪」のように県/都/府なしで書かれるケースの吸収
PREF_ALIASES = {p[:-1] if p not in ("北海道",) else p: p for p in PREFECTURES}
# 主要都市 → 都道府県（会場名に県名が入らないことが多いので補助的に）
CITY_HINTS = {
    "秋葉原": "東京都", "池袋": "東京都", "新宿": "東京都", "渋谷": "東京都", "町田": "東京都",
    "横浜": "神奈川県", "川崎": "神奈川県", "藤沢": "神奈川県",
    "名駅": "愛知県", "栄": "愛知県", "大須": "愛知県",
    "日本橋": "大阪府", "難波": "大阪府", "梅田": "大阪府", "なんば": "大阪府",
    "三宮": "兵庫県", "天神": "福岡県", "博多": "福岡県",
    "仙台": "宮城県", "札幌": "北海道", "那覇": "沖縄県",
}

ONLINE_WORDS = ["オンライン", "リモート", "リモポケカ", "Discord", "ディスコード", "web開催"]

# イベントの種別判定。自主大会だけ見たい人のためにフィルタできるようにする
KOURYU_WORDS = ["交流会", "対戦会", "フリー対戦", "調整会", "もくもく会", "練習会"]
SHOP_WORDS = ["ジムバトル", "トレーナーズリーグ", "店舗大会", "当店", "店内"]

FORMAT_WORDS = {
    "スタンダード": ["スタンダード", "スタン"],
    "エクストラ": ["エクストラ"],
    "レギュ限定": ["レギュレーション限定", "殿堂", "旧レギュ", "ハーフデッキ", "シティ落ち"],
    "その他": [],
}

UA = {"User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +自主大会情報の集約)"}


# ---------------------------------------------------------------- ユーティリティ

def log(msg: str) -> None:
    print(f"[{datetime.now(JST):%H:%M:%S}] {msg}", flush=True)


def norm(text: str) -> str:
    """全角記号などを揃えて検索しやすくする。"""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------- Twitter 検索

def search_twitter(query: str, since: datetime) -> list[dict]:
    """twitterapi.io の advanced search を叩いてツイートを集める。"""
    if not API_KEY:
        raise RuntimeError(
            "環境変数 TWITTERAPI_IO_KEY が未設定です。"
            "twitterapi.io で取得したキーを設定してください。"
        )

    full_query = f"{query} since:{since:%Y-%m-%d}"
    tweets: list[dict] = []
    cursor = ""

    for page in range(MAX_PAGES_PER_QUERY):
        params = {"query": full_query, "queryType": "Latest"}
        if cursor:
            params["cursor"] = cursor

        try:
            r = requests.get(
                API_BASE,
                params=params,
                headers={"X-API-Key": API_KEY},
                timeout=30,
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log(f"  !! 検索失敗 ({query[:30]}...): {e}")
            break

        body = r.json()
        batch = body.get("tweets") or []
        tweets.extend(batch)

        if not body.get("has_next_page") or not batch:
            break
        cursor = body.get("next_cursor") or ""
        if not cursor:
            break
        time.sleep(0.4)

    log(f"  検索「{query[:36]}…」 → {len(tweets)}件")
    return tweets


def expand_tco(url: str) -> str:
    """t.co の短縮URLを展開する（失敗したら元のまま返す）。"""
    try:
        r = requests.head(url, allow_redirects=True, timeout=10, headers=UA)
        return r.url
    except Exception:  # noqa: BLE001
        return url


def extract_tonamel_ids(tweet: dict) -> set[str]:
    """ツイート本文・entities から Tonamel の大会IDを抜き出す。"""
    ids: set[str] = set()
    blob = tweet.get("text") or ""

    # entities に展開済みURLが入っていればそちらを優先（t.co を叩かずに済む）
    entities = tweet.get("entities") or {}
    for u in entities.get("urls") or []:
        for key in ("expanded_url", "unwound_url", "url"):
            if u.get(key):
                blob += " " + u[key]

    ids.update(TONAMEL_RE.findall(blob))

    # まだ見つからず t.co が残っているなら展開してみる
    if not ids:
        for tco in TCO_RE.findall(blob)[:3]:
            expanded = expand_tco(tco)
            ids.update(TONAMEL_RE.findall(expanded))

    return ids


def looks_like_pokeca(text: str) -> bool:
    t = norm(text)
    if any(w in t for w in NEGATIVE_WORDS):
        # ポケポケ等の言及があっても「ポケモンカードゲーム」明記があれば通す
        if "ポケモンカードゲーム" not in t and "ポケカ" not in t:
            return False
    return ("ポケカ" in t) or ("ポケモンカード" in t) or ("ポケモンTCG" in t)


# ---------------------------------------------------------------- Tonamel ページ解析

def fetch_tonamel(comp_id: str) -> tuple[str, str] | None:
    """大会ページのHTMLを取得。(html, url) を返す。"""
    url = f"https://tonamel.com/competition/{comp_id}"
    try:
        r = requests.get(url, headers=UA, timeout=25)
        if r.status_code != 200:
            log(f"  - {comp_id}: HTTP {r.status_code} (削除 or 非公開)")
            return None
        return r.text, url
    except Exception as e:  # noqa: BLE001
        log(f"  - {comp_id}: 取得失敗 {e}")
        return None


def _meta(html: str, prop: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']*)["\']',
        html, re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(prop)}["\']',
        html, re.I,
    )
    return m.group(1) if m else ""


def _strip_tags(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"[ \t　]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _embedded_json(html: str) -> dict:
    """Next.js / Nuxt が埋め込む状態JSONがあれば拾う（サイト構造変更への保険）。"""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S
    )
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            pass
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S
    ):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and obj.get("@type") in ("Event", "SportsEvent"):
                return {"jsonld": obj}
        except Exception:  # noqa: BLE001
            continue
    return {}


DATE_PATTERNS = [
    re.compile(r"(20\d{2})[年/\-\.](\d{1,2})[月/\-\.](\d{1,2})"),
    re.compile(r"(?<!\d)(\d{1,2})[月/](\d{1,2})日?"),
]
TIME_RE = re.compile(r"(\d{1,2})[:：](\d{2})")


def parse_datetime(text: str, posted_at: datetime) -> tuple[str | None, str | None]:
    """本文から開催日(YYYY-MM-DD)と開始時刻(HH:MM)を推定する。"""
    t = norm(text)
    date_str = None

    # 「開催日時」ラベル周辺を優先的に見る
    label = re.search(r"(開催日時|開催日|日時|イベント日時)[^\n]{0,80}", t)
    scopes = [label.group(0)] if label else []
    scopes.append(t[:1200])

    for scope in scopes:
        m = DATE_PATTERNS[0].search(scope)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                date_str = f"{y:04d}-{mo:02d}-{d:02d}"
                break
            except ValueError:
                pass
        m = DATE_PATTERNS[1].search(scope)
        if m:
            mo, d = (int(x) for x in m.groups())
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            year = posted_at.year
            # 告知より前の日付になる場合は翌年扱い（12月に1月の大会を告知するケース）
            try:
                cand = datetime(year, mo, d, tzinfo=JST)
            except ValueError:
                continue
            if cand < posted_at - timedelta(days=30):
                year += 1
            date_str = f"{year:04d}-{mo:02d}-{d:02d}"
            break

    time_str = None
    tm_scope = label.group(0) if label else t[:800]
    tm = TIME_RE.search(tm_scope)
    if tm:
        h, mi = int(tm.group(1)), int(tm.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            time_str = f"{h:02d}:{mi:02d}"

    return date_str, time_str


def parse_place(text: str) -> tuple[str | None, str | None, bool]:
    """会場名・都道府県・オンラインかどうかを推定する。"""
    t = norm(text)
    is_online = any(w in t for w in ONLINE_WORDS) and "会場" not in t[:400]

    venue = None
    m = re.search(r"(会場|開催場所|場所)[\s:：]*([^\n]{2,60})", t)
    if m:
        venue = m.group(2).strip(" 　:：-")

    pref = None
    for p in PREFECTURES:
        if p in t:
            pref = p
            break
    if not pref:
        for alias, p in PREF_ALIASES.items():
            if re.search(rf"{alias}(?:市|区|駅|県|都|府)", t):
                pref = p
                break
    if not pref:
        for city, p in CITY_HINTS.items():
            if city in t:
                pref = p
                break

    if is_online:
        pref = pref or "オンライン"

    return venue, pref, is_online


def parse_money(text: str) -> str | None:
    t = norm(text)
    m = re.search(r"(参加費|エントリー費|参加料)[\s:：]*([^\n]{1,40})", t)
    if m:
        return m.group(2).strip(" 　:：-")[:40]
    m = re.search(r"([0-9,]{3,7})\s*円", t)
    return f"{m.group(1)}円" if m else None


def parse_capacity(text: str) -> int | None:
    t = norm(text)
    m = re.search(r"(定員|募集人数|参加人数|上限)[^\d]{0,10}(\d{1,4})\s*(?:人|名)", t)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d{1,4})\s*(?:人|名)\s*(?:限定|募集|定員)", t)
    return int(m.group(1)) if m else None


def parse_prize(text: str) -> str | None:
    t = norm(text)
    m = re.search(r"(賞品|景品|参加賞|優勝賞品)[\s:：]*([^\n]{2,120})", t)
    if m:
        return m.group(2).strip(" 　:：-")[:120]
    return None


def parse_kind(title: str, text: str) -> str:
    """自主大会 / 交流会 / ショップ主催 のどれかに分類する。"""
    t = norm(f"{title}\n{text[:900]}")
    if any(w in t for w in SHOP_WORDS):
        return "ショップ主催"
    if any(w in t for w in KOURYU_WORDS) and "杯" not in title:
        return "交流会"
    return "自主大会"


def parse_format(text: str) -> str:
    t = norm(text)
    for name, words in FORMAT_WORDS.items():
        if any(w in t for w in words):
            return name
    return "その他"


def build_event(comp_id: str, html: str, url: str, tweet: dict) -> dict:
    title = _meta(html, "og:title") or _meta(html, "twitter:title") or f"大会 {comp_id}"
    title = re.sub(r"\s*[|｜]\s*Tonamel\s*$", "", title).strip()
    desc_meta = _meta(html, "og:description")
    body = _strip_tags(html)
    haystack = f"{title}\n{desc_meta}\n{body}"

    posted_raw = tweet.get("createdAt") or ""
    posted_at = datetime.now(JST)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            posted_at = datetime.strptime(posted_raw, fmt).astimezone(JST)
            break
        except Exception:  # noqa: BLE001
            continue

    date_str, time_str = parse_datetime(haystack, posted_at)
    venue, pref, is_online = parse_place(haystack)

    author = (tweet.get("author") or {})

    return {
        "id": comp_id,
        "title": title,
        "url": url,
        "date": date_str,
        "start_time": time_str,
        "prefecture": pref,
        "venue": venue,
        "online": is_online,
        "fee": parse_money(haystack),
        "capacity": parse_capacity(haystack),
        "prize": parse_prize(haystack),
        "format": parse_format(haystack),
        "kind": parse_kind(title, haystack),
        "summary": (desc_meta or body[:180]).strip()[:220],
        "source_tweet_url": tweet.get("url"),
        "organizer_handle": author.get("userName"),
        "organizer_name": author.get("name"),
        "tweeted_at": posted_at.isoformat(),
        "collected_at": datetime.now(JST).isoformat(),
    }


# ---------------------------------------------------------------- メイン

PREF_TO_REGION = {}
for _region, _prefs in {
    "北海道・東北": ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "中部": ["新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県"],
    "近畿": ["三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国・四国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県"],
    "九州・沖縄": ["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
}.items():
    for _p in _prefs:
        PREF_TO_REGION[_p] = _region


def load_seed_organizers() -> list[dict]:
    """手で育てるキーマンのリスト。data/organizers.seed.json を編集すれば増やせる。"""
    path = DATA_DIR / "organizers.seed.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return []


def build_organizers(events: list[dict]) -> list[dict]:
    """
    キーマン一覧を作る。
    ・data/organizers.seed.json に手で書いた人（＝開催予定が無くても載せたい人）
    ・収集結果の中で2回以上主催している人（＝自動で見つかったキーマン）
    をマージする。
    """
    seeds = {o["handle"]: dict(o) for o in load_seed_organizers() if o.get("handle")}

    stats: dict[str, dict] = {}
    for e in events:
        h = e.get("organizer_handle")
        if not h:
            continue
        s = stats.setdefault(h, {"count": 0, "name": None, "prefs": {}})
        s["count"] += 1
        s["name"] = s["name"] or e.get("organizer_name") or e.get("organizer_handle")
        if e.get("prefecture"):
            s["prefs"][e["prefecture"]] = s["prefs"].get(e["prefecture"], 0) + 1

    for handle, s in stats.items():
        top_pref = max(s["prefs"], key=s["prefs"].get) if s["prefs"] else None
        if handle in seeds:
            seeds[handle].setdefault("area", top_pref or "不明")
            continue
        if s["count"] < 2:          # 1回だけの主催はキーマン扱いしない
            continue
        seeds[handle] = {
            "handle": handle,
            "name": s["name"],
            "area": top_pref or "不明",
            "region": PREF_TO_REGION.get(top_pref or "", "全国"),
            "note": f"直近3ヶ月で{s['count']}件の大会を主催しています。",
            "auto": True,
        }

    for o in seeds.values():
        o.setdefault("region", PREF_TO_REGION.get(o.get("area", "")[:4], "全国"))

    return sorted(seeds.values(), key=lambda o: (o.get("region", ""), o.get("name") or ""))


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    since = datetime.now(JST) - timedelta(days=LOOKBACK_DAYS)

    log(f"■ Twitter を検索します（{since:%Y-%m-%d} 以降 / {len(SEARCH_QUERIES)}クエリ）")
    all_tweets: dict[str, dict] = {}
    for q in SEARCH_QUERIES:
        for tw in search_twitter(q, since):
            if tw.get("id"):
                all_tweets[tw["id"]] = tw

    # 第2パス: 既知のキーマンの投稿を直接追う。
    # 「ポケカ」「自主大会」と書かずに告知する主催者を取りこぼさないための保険で、
    # これが件数と精度に一番効く。
    if FOLLOW_ORGANIZERS:
        handles = [o["handle"] for o in load_seed_organizers() if o.get("handle")]
        handles += [o["alt_handle"] for o in load_seed_organizers() if o.get("alt_handle")]
        log(f"■ キーマン {len(handles)}アカウントの投稿を追跡します")
        # from:a OR from:b … は1クエリにまとめられる（長すぎるので10人ずつ）
        for i in range(0, len(handles), 10):
            chunk = " OR ".join(f"from:{h}" for h in handles[i:i + 10])
            for tw in search_twitter(f"({chunk}) tonamel.com", since):
                if tw.get("id"):
                    # 既知の主催者の投稿は「ポケカ」表記が無くても通す
                    tw["_trusted"] = True
                    all_tweets[tw["id"]] = tw

    log(f"■ 重複除去後のツイート数: {len(all_tweets)}")

    # 大会ID → その大会を告知していたツイート（最も古いもの＝一次告知を採用）
    id_to_tweet: dict[str, dict] = {}
    for tw in all_tweets.values():
        if not tw.get("_trusted") and not looks_like_pokeca(tw.get("text", "")):
            continue
        for comp_id in extract_tonamel_ids(tw):
            prev = id_to_tweet.get(comp_id)
            if prev is None or (tw.get("createdAt", "") < prev.get("createdAt", "")):
                id_to_tweet[comp_id] = tw
    log(f"■ 見つかった Tonamel 大会: {len(id_to_tweet)}件")

    # 既存データを読み、取得済みの大会は再取得をスキップ（APIとサーバへの負荷を減らす）
    existing: dict[str, dict] = {}
    if OUT_PATH.exists():
        try:
            existing = {e["id"]: e for e in json.loads(OUT_PATH.read_text("utf-8"))["events"]}
        except Exception:  # noqa: BLE001
            existing = {}

    events: dict[str, dict] = dict(existing)
    save_raw = os.environ.get("SAVE_RAW_HTML") == "1"
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)

    log("■ Tonamel の大会ページから詳細を取得します")
    for i, (comp_id, tw) in enumerate(id_to_tweet.items(), 1):
        if comp_id in existing and existing[comp_id].get("date"):
            continue
        got = fetch_tonamel(comp_id)
        if not got:
            continue
        html, url = got
        if save_raw:
            (RAW_DIR / f"{comp_id}.html").write_text(html, "utf-8")
        ev = build_event(comp_id, html, url, tw)
        events[comp_id] = ev
        log(f"  {i:>3}. {ev['date'] or '日付不明'} {ev['prefecture'] or '?'} {ev['title'][:34]}")
        time.sleep(1.0)  # 相手サーバに優しく

    # 終わった大会を落とし、掲載範囲（今日〜HORIZON_DAYS先）に絞る
    today = datetime.now(JST).strftime("%Y-%m-%d")
    horizon = (datetime.now(JST) + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%d")
    upcoming = [
        e for e in events.values()
        if not e.get("date") or (today <= e["date"] <= horizon)
    ]
    upcoming.sort(key=lambda e: (e.get("date") or "9999-99-99", e.get("start_time") or "99:99"))

    organizers = build_organizers(upcoming)
    by_pref: dict[str, int] = {}
    for e in upcoming:
        by_pref[e.get("prefecture") or "不明"] = by_pref.get(e.get("prefecture") or "不明", 0) + 1

    OUT_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(JST).isoformat(),
                "count": len(upcoming),
                "horizon": horizon,
                "by_prefecture": dict(sorted(by_pref.items(), key=lambda kv: -kv[1])),
                "events": upcoming,
                "organizers": organizers,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    log(f"■ 完了: {OUT_PATH} に {len(upcoming)}件 / キーマン{len(organizers)}人 を保存しました")
    log(f"   掲載期間: {today} 〜 {horizon}")
    log(f"   地域内訳: {', '.join(f'{k}{v}' for k, v in list(by_pref.items())[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
