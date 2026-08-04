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

import html as html_lib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from collections import Counter

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
# キーマン追跡は投稿数が少なく費用対効果が高いので、キーワード検索より長くさかのぼる
ORG_LOOKBACK_DAYS = int(os.environ.get("ORG_LOOKBACK_DAYS", "14"))
# 主催者1人あたり何ページ取るか。毎日走らせるなら1(最新20件)で足りる。
# 初回の取り戻しだけ 3 などに上げる。
ORG_PAGES = int(os.environ.get("ORG_PAGES", "1"))
# 追跡するアカウント数の上限。1人1回のAPI呼び出しなので、そのままコストになる。
ORG_MAX_HANDLES = int(os.environ.get("ORG_MAX_HANDLES", "40"))
# 自動検出ぶんの追跡を何日かけて一巡させるか。1なら毎日全員、2なら隔日で半分ずつ。
# 手動登録(seed)のキーマンはローテーションせず毎日必ず追跡する。
ORG_ROTATE_DAYS = int(os.environ.get("ORG_ROTATE_DAYS", "2"))
# まだ1件も大会が取れていないキーマンは、深く追いかける。
# 自主大会の告知は1〜3ヶ月前に出ることがあり、通常の追跡窓では届かないため。
DEEP_ORG_LOOKBACK_DAYS = int(os.environ.get("DEEP_ORG_LOOKBACK_DAYS", "120"))
DEEP_ORG_PAGES = int(os.environ.get("DEEP_ORG_PAGES", "3"))

# 解析ロジックのバージョン。ここを上げると、古いバージョンで解析された大会は
# 次回の実行で自動的に取り直して再解析される。
# 「解析を直したのに、既に取得済みの大会には反映されない」という事故を防ぐための仕組み。
# ★解析ロジックを変えたら必ずこの数字を上げること。
PARSER_VERSION = 7

# 収集の各経路がどれだけ成果を出したかの記録。
# 「エラーは出ないのに何も取れていない」という沈黙の故障を検知するために残す。
STATS: dict = {}

# 検索クエリ。Twitter の検索演算子がそのまま使える。
# 「tonamel の URL を含む」×「ポケカ語彙」の掛け算で、余計なゲームの大会を弾く。
SEARCH_QUERIES = [
    'url:tonamel.com (ポケカ OR ポケモンカード) -filter:retweets',
    'url:tonamel.com 自主大会 (ポケカ OR ポケモンカード) -filter:retweets',
    'tonamel.com (ポケカ OR ポケモンカード) 大会 -filter:retweets',
    '(ポケカ OR ポケモンカード) 自主大会 (エントリー OR 募集 OR 参加者募集) -filter:retweets',
    '(ポケカ OR ポケモンカード) 非公認大会 (募集 OR 開催) -filter:retweets',
    # 大型・シリーズ物のイベント。個人主催より規模が大きく、
    # 「自主大会」という語を使わずに告知されることが多いので別枠で拾う。
    '(トレカフェス OR トレカアライブ OR トレフェス) (ポケカ OR ポケモンカード) -filter:retweets',
    'url:tonamel.com (ポケカ OR ポケモンカード) (CS OR 選手権 OR カップ OR 杯) -filter:retweets',
    '(ポケカ OR ポケモンカード) (オープン大会 OR 大型大会 OR 争奪戦) (エントリー OR 募集) -filter:retweets',
]

# ポケカ以外(ポケポケ/ユニアリ等)を弾くためのネガティブ語
NEGATIVE_WORDS = ["ポケポケ", "ポケモンカードアプリ", "ポケモンTCGポケット", "Pocket"]

# Tonamelの大会IDは5文字。ツイート本文が途中で切れて「…/competition/5t」のような
# 断片が混ざることがあるので、長さで弾く（短いIDを拾うと取得失敗が積み上がる）。
# Tonamelの大会URLには2種類ある。主催者が管理画面からコピーすると
#   https://tonamel.com/organize/{主催者ID}/competition/{大会ID}
# の形になり、これを見落としていた（実際にコンソメリーグを取りこぼしていた）。
TONAMEL_RE = re.compile(
    r"tonamel\.com/(?:organize/[A-Za-z0-9_-]+/)?competition/([A-Za-z0-9]{5,12})")
# Tonamelのページ内リンクに現れる「大会IDではない語」。ゴミIDとして積むと
# 取得失敗が積み上がるので弾く（実際に "index" や "_competitionId" が混入した）。
NOT_AN_ID = {"index", "create", "search", "detail", "edit", "admin", "login",
             "entry", "result", "results", "about", "terms", "privacy",
             "organize", "organization", "competition", "competitions"}
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
# 会場名に県名が書かれないことは非常に多い（「池袋」「大須」だけ、など）。
# 地名・駅名から都道府県を推定するための辞書。ここを厚くするほど「?」が減る。
CITY_HINTS = {
    # 東京
    "秋葉原": "東京都", "池袋": "東京都", "新宿": "東京都", "渋谷": "東京都", "町田": "東京都",
    "上野": "東京都", "浅草": "東京都", "錦糸町": "東京都", "北千住": "東京都", "蒲田": "東京都",
    "中野": "東京都", "高田馬場": "東京都", "御茶ノ水": "東京都", "神保町": "東京都",
    "五反田": "東京都", "品川": "東京都", "立川": "東京都", "八王子": "東京都", "吉祥寺": "東京都",
    "下北沢": "東京都", "としま区民": "東京都", "豊島区": "東京都", "江戸川区": "東京都",
    "板橋": "東京都", "練馬": "東京都", "足立区": "東京都", "葛飾": "東京都", "大田区": "東京都",
    "府中": "東京都", "調布": "東京都", "三鷹": "東京都", "国分寺": "東京都",
    # 神奈川
    "横浜": "神奈川県", "川崎": "神奈川県", "藤沢": "神奈川県", "相模原": "神奈川県",
    "本厚木": "神奈川県", "厚木": "神奈川県", "小田原": "神奈川県", "鶴見": "神奈川県",
    "武蔵小杉": "神奈川県", "平塚": "神奈川県", "戸塚": "神奈川県", "青葉台": "神奈川県",
    "矢向": "神奈川県", "上大岡": "神奈川県", "大和市": "神奈川県",
    # 埼玉
    "大宮": "埼玉県", "浦和": "埼玉県", "川口": "埼玉県", "所沢": "埼玉県", "越谷": "埼玉県",
    "春日部": "埼玉県", "川越": "埼玉県", "熊谷": "埼玉県", "草加": "埼玉県", "レイクタウン": "埼玉県",
    "寄居": "埼玉県", "上尾": "埼玉県", "朝霞": "埼玉県",
    # 千葉
    "船橋": "千葉県", "柏駅": "千葉県", "柏市": "千葉県", "松戸": "千葉県", "海浜幕張": "千葉県",
    "幕張": "千葉県", "津田沼": "千葉県", "市川": "千葉県",
    # 北関東
    "宇都宮": "栃木県", "小山": "栃木県", "前橋": "群馬県", "高崎": "群馬県", "太田": "群馬県",
    "水戸": "茨城県", "つくば": "茨城県", "土浦": "茨城県",
    # 中部
    "名駅": "愛知県", "栄駅": "愛知県", "大須": "愛知県", "金山": "愛知県", "岡崎": "愛知県",
    "名古屋": "愛知県",
    "豊橋": "愛知県", "刈谷": "愛知県", "一宮": "愛知県", "春日井": "愛知県",
    "岐阜": "岐阜県", "大垣": "岐阜県", "静岡": "静岡県", "浜松": "静岡県", "沼津": "静岡県",
    "金沢": "石川県", "松任": "石川県", "白山": "石川県", "小松": "石川県",
    "富山": "富山県", "高岡": "富山県", "射水": "富山県", "小矢部": "富山県",
    "福井": "福井県", "新潟": "新潟県", "長岡": "新潟県", "松本": "長野県", "長野駅": "長野県",
    "甲府": "山梨県",
    # 近畿
    "日本橋": "大阪府", "難波": "大阪府", "梅田": "大阪府", "なんば": "大阪府",
    "心斎橋": "大阪府", "天王寺": "大阪府", "堺市": "大阪府", "新大阪": "大阪府", "京橋": "大阪府",
    "三宮": "兵庫県", "神戸": "兵庫県", "姫路": "兵庫県", "西宮": "兵庫県", "尼崎": "兵庫県",
    "河原町": "京都府", "四条": "京都府", "京都駅": "京都府",
    "奈良": "奈良県", "大津": "滋賀県", "草津": "滋賀県", "和歌山": "和歌山県",
    "四日市": "三重県", "津駅": "三重県",
    # 中国・四国
    "岡山": "岡山県", "倉敷": "岡山県", "広島": "広島県", "福山": "広島県", "東広島": "広島県",
    "西条": "広島県", "山口": "山口県", "下関": "山口県", "鳥取": "鳥取県", "松江": "島根県",
    "高松": "香川県", "松山": "愛媛県", "徳島": "徳島県", "高知": "高知県",
    # 九州・沖縄
    "天神": "福岡県", "博多": "福岡県", "小倉": "福岡県", "久留米": "福岡県", "北九州": "福岡県",
    "佐賀": "佐賀県", "長崎": "長崎県", "諫早": "長崎県", "佐世保": "長崎県",
    "熊本": "熊本県", "大分": "大分県", "宮崎": "宮崎県", "鹿児島": "鹿児島県",
    "那覇": "沖縄県", "沖縄市": "沖縄県", "石垣市": "沖縄県", "宜野湾": "沖縄県", "浦添": "沖縄県",
    "鹿屋": "鹿児島県", "霧島": "鹿児島県", "八代": "熊本県", "別府": "大分県",
    "流山": "千葉県", "我孫子": "千葉県", "浦安": "千葉県", "木更津": "千葉県", "成田": "千葉県",
    "土岐": "岐阜県", "各務原": "岐阜県", "四條畷": "大阪府", "八尾": "大阪府", "枚方": "大阪府",
    "東大阪": "大阪府", "吹田": "大阪府", "豊中": "大阪府", "河内長野": "大阪府", "高槻": "大阪府",
    "明石": "兵庫県", "加古川": "兵庫県", "宝塚": "兵庫県", "伊丹": "兵庫県",
    "太宰府": "福岡県", "飯塚": "福岡県", "佐世保": "長崎県", "諫早": "長崎県",
    "上越": "新潟県", "三条": "新潟県", "上田": "長野県", "飯田": "長野県", "諏訪": "長野県",
    "富士": "静岡県", "藤枝": "静岡県", "掛川": "静岡県", "豊田": "愛知県", "安城": "愛知県",
    "宇治": "京都府", "彦根": "滋賀県", "橿原": "奈良県", "米子": "鳥取県", "出雲": "島根県",
    "津山": "岡山県", "呉市": "広島県", "宇部": "山口県", "丸亀": "香川県", "今治": "愛媛県",
    # 北海道・東北
    "仙台": "宮城県", "札幌": "北海道", "旭川": "北海道", "函館": "北海道", "帯広": "北海道",
    "青森": "青森県", "弘前": "青森県", "盛岡": "岩手県", "秋田": "秋田県",
    "山形": "山形県", "福島": "福島県", "郡山": "福島県", "いわき": "福島県",
}

ONLINE_WORDS = ["オンライン", "リモート", "リモポケカ", "Discord", "ディスコード", "web開催"]

# イベントの種別判定。自主大会だけ見たい人のためにフィルタできるようにする
KOURYU_WORDS = ["交流会", "対戦会", "フリー対戦", "調整会", "もくもく会", "練習会"]
SHOP_WORDS = ["ジムバトル", "トレーナーズリーグ", "店舗大会", "当店", "店内",
              "ハレツー", "デイリー", "パックバトル", "シールド戦", "無料バトル"]
# 主催者名がカードショップかどうかの判定
SHOP_NAME_RE = (
    r"(店$|店\s|カードショップ|カードラボ|トレカ|晴れる屋|TSUTAYA|ドラゴンスター|"
    r"フルコンプ|イエローサブマリン|ホビーステーション|らしんばん|駿河屋|万代|"
    r"ブックオフ|GEO|ゲオ|トイコンプ|カードキングダム|遊々亭|ミント|MINT)"
)

FORMAT_WORDS = {
    "スタンダード": ["スタンダード", "スタン"],
    "エクストラ": ["エクストラ"],
    "レギュ限定": ["レギュレーション限定", "殿堂", "旧レギュ", "ハーフデッキ", "シティ落ち"],
    "その他": [],
}

# HTTPヘッダは latin-1 しか通らない。日本語を入れると全リクエストが落ちるので ASCII のみ。
UA = {"User-Agent": "Mozilla/5.0 (compatible; PokecaJishuBot/1.0; +pokeca-taikai)"}


# ---------------------------------------------------------------- ユーティリティ

def log(msg: str) -> None:
    print(f"[{datetime.now(JST):%H:%M:%S}] {msg}", flush=True)


def norm(text: str) -> str:
    """全角記号などを揃えて検索しやすくする。"""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------- Twitter 検索

# 無料プランは 0.2 QPS（5秒に1回）なので、呼び出し間隔を自前で守る。
# 有料プランに上げたら QPS_INTERVAL を 0.4 くらいまで下げてよい。
QPS_INTERVAL = float(os.environ.get("QPS_INTERVAL", "5.5"))
_last_call = [0.0]


def _throttle() -> None:
    wait = QPS_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def api_get(params: dict) -> dict | None:
    """レート制限を守りつつ叩く。429なら待って最大3回リトライ。"""
    for attempt in range(3):
        _throttle()
        try:
            r = requests.get(
                API_BASE, params=params, headers={"X-API-Key": API_KEY}, timeout=40
            )
        except Exception as e:  # noqa: BLE001
            log(f"    通信エラー({attempt + 1}/3): {e}")
            time.sleep(5)
            continue

        if r.status_code == 429:
            back = 15 * (attempt + 1)
            log(f"    レート制限。{back}秒待って再試行 ({attempt + 1}/3)")
            time.sleep(back)
            continue
        if r.status_code == 402:
            log("    !! クレジット残高が不足しています")
            return None
        if r.status_code != 200:
            log(f"    HTTP {r.status_code}: {r.text[:160]}")
            return None
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return None
    return None


USER_TL_ENDPOINTS = [
    "https://api.twitterapi.io/twitter/user/last_tweets",
    "https://api.twitterapi.io/twitter/user/tweets",
]


def fetch_user_tweets(handle: str, pages: int = 1) -> list[dict]:
    """
    指定アカウントの投稿を「タイムライン専用エンドポイント」から取る。

    検索演算子の from: は、動いていたのに突然すべて0件を返すようになった
    （既知の成功例で対照実験して確認）。検索は仕様変更の影響を受けやすいので、
    主催者の追跡は専用エンドポイントを主、検索を予備として使う。
    """
    out: list[dict] = []
    for ep in USER_TL_ENDPOINTS:
        cursor = ""
        got_any = False
        for _ in range(pages):
            params = {"userName": handle}
            if cursor:
                params["cursor"] = cursor
            _throttle()
            try:
                r = requests.get(ep, params=params,
                                 headers={"X-API-Key": API_KEY}, timeout=40)
            except Exception:  # noqa: BLE001
                break
            if r.status_code != 200:
                break
            try:
                b = r.json()
            except Exception:  # noqa: BLE001
                break
            tws = (b.get("data") or {}).get("tweets") if isinstance(b.get("data"), dict) else None
            tws = tws or b.get("tweets") or []
            if not tws:
                break
            out.extend(tws)
            got_any = True
            if not b.get("has_next_page"):
                break
            cursor = b.get("next_cursor") or ""
            if not cursor:
                break
        if got_any:
            return out
    return out


def search_twitter(query: str, since: datetime, pages: int | None = None) -> list[dict]:
    """twitterapi.io の advanced search を叩いてツイートを集める。"""
    if not API_KEY:
        raise RuntimeError(
            "環境変数 TWITTERAPI_IO_KEY が未設定です。"
            "twitterapi.io で取得したキーを設定してください。"
        )

    full_query = f"{query} since:{since:%Y-%m-%d}"
    tweets: list[dict] = []
    cursor = ""

    for page in range(pages or MAX_PAGES_PER_QUERY):
        params = {"query": full_query, "queryType": "Latest"}
        if cursor:
            params["cursor"] = cursor

        body = api_get(params)
        if body is None:
            break

        batch = body.get("tweets") or []
        tweets.extend(batch)

        if not body.get("has_next_page") or not batch:
            break
        cursor = body.get("next_cursor") or ""
        if not cursor:
            break

    log(f"  検索「{query[:36]}…」 → {len(tweets)}件")
    STATS.setdefault("search_results", []).append({"q": query[:50], "n": len(tweets)})
    return tweets


def expand_tco(url: str) -> str:
    """t.co の短縮URLを展開する（失敗したら元のまま返す）。"""
    try:
        r = requests.head(url, allow_redirects=True, timeout=10, headers=UA)
        return r.url
    except Exception:  # noqa: BLE001
        return url


def extract_tonamel_ids(tweet: dict) -> set[str]:
    """
    ツイートから Tonamel の大会IDを抜き出す。

    APIが返すJSONのどこにURLが入るかは仕様変更で変わりうる（text / entities.urls /
    extendedEntities / note_tweet など）。決め打ちで掘ると取りこぼすので、
    ツイートのJSON全体を文字列にして探す。多少雑だが、これが一番取りこぼさない。
    """
    ids: set[str] = set()
    try:
        blob = json.dumps(tweet, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        blob = str(tweet)
    # JSON内では "/" が "\/" とエスケープされることがあるので両方を許す
    ids.update(
        i for i in re.findall(
            r"tonamel\.com\\?/(?:organize\\?/[A-Za-z0-9_-]+\\?/)?competition\\?/([A-Za-z0-9]{5,12})", blob
        )
    )

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
        r.encoding = "utf-8"   # 明示しないと文字化けする
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


def extract_jsonld(html: str) -> dict:
    """
    Tonamel は schema.org の Event を JSON-LD で埋め込んでいる。
    ページ本体は Nuxt の SPA なので素のHTTPでは本文が取れないが、
    この JSON-LD には開催日時・住所・定員・主催者・説明文が構造化されて入っている。
    ここを読むのが一番正確で速い。
    """
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S
    ):
        try:
            obj = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, list):
            obj = next((o for o in obj if isinstance(o, dict)
                        and o.get("@type") in ("Event", "SportsEvent")), None)
        if isinstance(obj, dict) and obj.get("@type") in ("Event", "SportsEvent"):
            return obj
    return {}


def _from_jsonld(ld: dict) -> dict:
    """JSON-LD から、そのまま信用してよい項目を取り出す。"""
    out: dict = {}

    # 開催日時（タイムゾーン付きISO。年の推測が不要になるので一番効く）
    start = ld.get("startDate")
    if isinstance(start, str) and len(start) >= 10:
        out["date"] = start[:10]
        m = re.search(r"T(\d{2}):(\d{2})", start)
        if m and m.group(0) != "T00:00":
            out["start_time"] = f"{m.group(1)}:{m.group(2)}"

    loc = ld.get("location") or {}
    if isinstance(loc, dict):
        if loc.get("name"):
            out["venue"] = str(loc["name"])[:80]
        addr = loc.get("address")
        if isinstance(addr, dict):
            addr = " ".join(str(v) for v in addr.values() if isinstance(v, str))
        if isinstance(addr, str) and addr:
            out["address"] = addr
        # 会場名と住所を取り違えて登録している主催者が実在するので、両方から探す
        for cand in (addr, loc.get("name")):
            if not isinstance(cand, str) or not cand:
                continue
            p = _pref_from(norm(cand))
            if p:
                out["prefecture"] = p
                break

    mode = str(ld.get("eventAttendanceMode") or "")
    if "Online" in mode:
        out["online"] = True

    cap = ld.get("maximumAttendeeCapacity")
    if isinstance(cap, int) and 0 < cap < 10000:
        out["capacity"] = cap

    org = ld.get("organizer") or {}
    if isinstance(org, dict):
        if org.get("name"):
            out["organizer_name"] = str(org["name"])[:60]
        if org.get("url"):
            out["organizer_url"] = str(org["url"])

    if ld.get("name"):
        out["title"] = str(ld["name"]).strip()
    if ld.get("description"):
        # 説明文は "&amp;gt;" のように二重エスケープされていることがあるので戻す
        desc = str(ld["description"])
        for _ in range(2):
            desc = html_lib.unescape(desc)
        out["description"] = desc

    return out


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


# 郵便番号の上3桁は都道府県とほぼ1対1で対応する。
# 会場名や地名の辞書と違って取りこぼしが無いので、住所があるときは一番確実。
ZIP_RANGES = [
    (1, 9, "北海道"), (10, 19, "秋田県"), (20, 29, "岩手県"), (30, 39, "青森県"),
    (40, 99, "北海道"), (100, 208, "東京都"), (210, 259, "神奈川県"), (260, 299, "千葉県"),
    (300, 319, "茨城県"), (320, 329, "栃木県"), (330, 369, "埼玉県"), (370, 379, "群馬県"),
    (380, 399, "長野県"), (400, 409, "山梨県"), (410, 439, "静岡県"), (440, 498, "愛知県"),
    (500, 509, "岐阜県"), (510, 519, "三重県"), (520, 529, "滋賀県"), (530, 599, "大阪府"),
    (600, 629, "京都府"), (630, 639, "奈良県"), (640, 649, "和歌山県"), (650, 679, "兵庫県"),
    (680, 689, "鳥取県"), (690, 699, "島根県"), (700, 719, "岡山県"), (720, 739, "広島県"),
    (740, 759, "山口県"), (760, 769, "香川県"), (770, 779, "徳島県"), (780, 789, "高知県"),
    (790, 799, "愛媛県"), (800, 839, "福岡県"), (840, 849, "佐賀県"), (850, 859, "長崎県"),
    (860, 869, "熊本県"), (870, 879, "大分県"), (880, 889, "宮崎県"), (890, 899, "鹿児島県"),
    (900, 909, "沖縄県"), (910, 919, "福井県"), (920, 929, "石川県"), (930, 939, "富山県"),
    (940, 959, "新潟県"), (960, 979, "福島県"), (980, 989, "宮城県"), (990, 999, "山形県"),
]


def _pref_from_zip(text: str) -> str | None:
    m = re.search(r"〒?\s*(\d{3})-?\d{4}", text)
    if not m:
        return None
    n = int(m.group(1))
    return next((p for lo, hi, p in ZIP_RANGES if lo <= n <= hi), None)


def _pref_from(text: str) -> str | None:
    """1つの文字列から都道府県を判定する（県名 → 県名の略 → 地名ヒント の順）。"""
    if not text:
        return None
    for p in PREFECTURES:
        if p in text:
            return p
    z = _pref_from_zip(text)
    if z:
        return z
    # 「東京 千代田区」のように県名の後ろに空白が入ることがあるので詰めてから判定する
    squashed = re.sub(r"\s+", "", text)
    # 「東京千代田区」のように県名の直後に市区名が続く書き方も拾う
    for alias, p in PREF_ALIASES.items():
        if re.search(rf"{alias}(?:[都道府県駅]|[^\s]{{0,4}}[市区町村])", squashed):
            return p
    for city, p in CITY_HINTS.items():
        if city in text:
            return p
    return None


def parse_place(text: str, title: str = "") -> tuple[str | None, str | None, bool]:
    """
    会場名・都道府県・オンラインかどうかを推定する。

    地名は本文のどこにでも出てくる（「大阪から来る人は…」など）ので、
    会場名 → 会場ラベル周辺 → タイトル → 本文冒頭 の順に、
    確度の高いところから探して最初に当たったものを採用する。
    """
    t = norm(text)
    is_online = any(w in t for w in ONLINE_WORDS) and "会場" not in t[:400]

    venue = None
    m = re.search(r"(会場|開催場所|場所|開催地)[\s:：]*([^\n]{2,60})", t)
    if m:
        venue = m.group(2).strip(" 　:：-") or None

    # 確度の高い順に候補となる文字列を並べる
    scopes = [venue or "", m.group(0) if m else "", norm(title), t[:600]]
    pref = next((p for s in scopes for p in [_pref_from(s)] if p), None)

    if is_online:
        pref = pref or "オンライン"

    return venue, pref, is_online


# Tonamelの説明文は改行が潰されて1行になっており、代わりに装飾記号が区切りに使われる。
# 「参加費: 2,000円◼️メイン: 予選スイス…」のように続くので、ここで切らないと全部拾ってしまう。
SEP_RE = r"[◼◾■□▪▶►◯〇●○※【】\n\r]|(?:[・]{2,})|(?:\s{3,})"
# 「優勝：…準優勝：…」と続くので、次の順位が始まったら切る
NEXT_RANK_RE = r"(?:準優勝|準優|[2-9２-９]位|ベスト\s*\d|🥈|🥉|[2-9]️⃣|参加賞|上位\d)"


def _clip(s: str, limit: int) -> str:
    """最初の区切り記号までで切り、長すぎれば省略する。"""
    s = re.split(SEP_RE, s, maxsplit=1)[0]
    s = s.strip(" 　:：-–—>》」』")
    return (s[: limit - 1] + "…") if len(s) > limit else s


def parse_money(text: str) -> str | None:
    """参加費。金額そのものを最優先で取る（説明文が続いても巻き込まない）。"""
    t = norm(text)
    # 「参加費：2,000円」「参加費 ¥2,000」など、ラベルの近くにある金額
    # ラベルの後ろ60文字以内に出てくる最初の金額を採る。
    # 「参加費(当日現金払い)▶小学生以下1人/1,000円」のように説明が挟まることが多い。
    m = re.search(r"(参加費|エントリー費|参加料|参加費用)(.{0,60})", t, re.S)
    if m:
        amt = re.search(r"[¥￥]?\s*([0-9][0-9,]{2,6})\s*円?", m.group(2))
        if amt:
            return f"{int(amt.group(1).replace(',', '')):,}円"
    if re.search(r"(参加費|エントリー費)[^。]{0,10}(無料|0円)", t):
        return "無料"
    m = re.search(r"(参加費|エントリー費|参加料)[\s:：]*(.{1,30})", t)
    if m:
        v = _clip(m.group(2), 30)
        if v:
            return v
    m = re.search(r"[¥￥]\s*([0-9][0-9,]{2,6})", t)
    return f"{int(m.group(1).replace(',', '')):,}円" if m else None


def parse_capacity(text: str) -> int | None:
    t = norm(text)
    m = re.search(r"(定員|募集人数|参加人数|上限)[^\d]{0,10}(\d{1,4})\s*(?:人|名)", t)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d{1,4})\s*(?:人|名)\s*(?:限定|募集|定員)", t)
    return int(m.group(1)) if m else None


def parse_prize(text: str) -> str | None:
    """景品。「優勝：〇〇」が一番知りたい情報なので、それを優先して短く出す。"""
    t = norm(text)
    m = re.search(r"(?:🥇|1️⃣|優勝|1位|１位)[\s:：]*(.{2,70})", t)
    if m:
        v = _clip(re.split(NEXT_RANK_RE, m.group(1), maxsplit=1)[0], 46)
        # 「> (変更の可能性あり)・メインイベント優勝:」のような前置きを落とす
        v = re.sub(r"^[>＞\s]+", "", v)
        v = re.sub(r"^\([^)]{0,20}(変更|増加)[^)]{0,20}\)[・\s]*", "", v)
        v = re.sub(r"^(?:メイン(?:イベント)?)?優勝[:：]?\s*", "", v)
        if (v and re.search(r"(BOX|ＢＯＸ|パック|プレイマット|スリーブ|券|カード|円|ギフト|グッズ|プロモ)", v)
                and not re.match(r"^[はがのをにでとも、。)）\]】]", v)
                and not re.search(r"(ございません|ありません|なし|無し)", v)):
            return f"優勝：{v}"
    m = re.search(r"(賞品|景品|参加賞)[\s:：]*(.{2,70})", t)
    if m:
        v = _clip(re.split(NEXT_RANK_RE, m.group(2), maxsplit=1)[0], 46)
        # 「参加賞の配布はございません」のような否定文や助詞始まりを景品として出さない
        if (v and re.search(r"(BOX|ＢＯＸ|パック|プレイマット|スリーブ|券|カード|円|ギフト|グッズ|プロモ)", v)
                and not re.match(r"^[はがのをにでとも、。)）\]】]", v)
                and not re.search(r"(ございません|ありません|なし|無し|該当なし)", v)):
            return v
    return None


# Tonamel自身が持つゲーム種別のスラッグ。ページHTMLに現れるので、これが最も確実。
GAME_SLUG_RE = re.compile(r"pokemon_card(?![A-Za-z_])")
OTHER_GAME_SLUG_RE = re.compile(
    r"pokemon_trading_card_game_pocket|one_piece_card|duel_masters|yu_?gi_?oh|"
    r"shadowverse|union_arena|weiss_schwarz|dragon_ball|digimon_card|"
    r"gundam_card|valorant|apex_legends|splatoon|street_fighter")
# 本文から他ゲームを見分けるための語（ポケカ語彙が無いときだけ効かせる）
OTHER_GAME_WORD_RE = re.compile(
    r"(ARK|Apex|VALORANT|スプラトゥーン|スマブラ|ストリートファイター|"
    r"デュエマ|デュエル・?マスターズ|遊戯王|ワンピースカード|ヴァイス|ヴァンガード|"
    r"ユニオンアリーナ|ガンダムカード|ドラゴンボール|デジモンカード|"
    r"シャドウバース|MTG|マジック:?ザ|ポケポケ|ポケモンカードゲーム\s*ポケット)", re.I)
POCKET_RE = re.compile(r"ポケポケ|ポケモンカードゲーム\s*ポケット|Pokemon\s*TCG\s*Pocket", re.I)
POKECA_WORD_RE = re.compile(r"ポケカ|ポケモンカード|ポケモンTCG|PTCG|Pokemon\s*Card", re.I)


def is_pokeca_event(title: str, desc: str, html: str = "") -> bool:
    """
    その大会が本当にポケカかを判定する。
    Tonamelの公開一覧には他ゲームの大会も混ざる（実際にARKの大会が紛れ込んだ）。

    ★方針: 「ポケカだと言い切れないものを落とす」のではなく
      「他ゲームだと言い切れるものだけを落とす」。
      取りこぼしが最大の問題なので、判断がつかないものは載せる側に倒す。
      （実際、タイトルにも説明にも「ポケモン」が無い大会——コンソメリーグ——を
        以前の判定で取りこぼした。同じ事故を繰り返さないための設計。）
    """
    # 1. Tonamelのページ自身がゲーム種別を持っているなら、それを最優先で信じる
    if html:
        if GAME_SLUG_RE.search(html):
            return True
        if OTHER_GAME_SLUG_RE.search(html):
            return False

    t = norm(f"{title}\n{desc}")[:2000]

    # 2. ポケポケ（アプリ版）は「ポケモンカードゲーム ポケット」という表記なので、
    #    ポケカ語彙の判定より先に弾く必要がある。
    if POCKET_RE.search(t) and not re.search(r"ポケカ", t):
        return False

    # 3. 本文で判断する。ポケカ語彙があれば即採用。
    if POKECA_WORD_RE.search(t):
        return True

    # 4. ポケカ語彙が無い場合、他ゲームだと分かるものだけ落とす。
    #    どちらとも言えないものは載せる（取りこぼしを防ぐため）。
    if OTHER_GAME_WORD_RE.search(t):
        return False
    return True


def parse_kind(title: str, text: str, organizer: str | None = None) -> str:
    """自主大会 / 交流会 / ショップ主催 のどれかに分類する。"""
    t = norm(f"{title}\n{text[:900]}")
    # 主催者名が店名なら、まずショップ主催の定例イベントとみなす。
    # （「晴れる屋2 なんば店」「TSUTAYA大垣店」などが自主大会に混ざるのを防ぐ）
    if organizer and re.search(SHOP_NAME_RE, norm(organizer)):
        return "ショップ主催"
    if any(w in t for w in SHOP_WORDS):
        return "ショップ主催"
    # 交流会かどうかはタイトルで判断する。本文には「サブイベントのGLC交流会」のように
    # 部分的な言及が混ざるので、本文で判定すると大会まで交流会になってしまう。
    nt = norm(title)
    if any(w in nt for w in ("杯", "カップ", "CUP", "CS", "選手権", "大会")):
        return "自主大会"
    if any(w in nt for w in KOURYU_WORDS):
        return "交流会"
    return "自主大会"


def parse_format(text: str) -> str:
    t = norm(text)
    for name, words in FORMAT_WORDS.items():
        if any(w in t for w in words):
            return name
    return "その他"


def build_event(comp_id: str, html: str, url: str, tweet: dict) -> dict:
    ld = _from_jsonld(extract_jsonld(html))

    title = ld.get("title") or _meta(html, "og:title") or f"大会 {comp_id}"
    title = re.sub(r"\s*[-|｜]\s*Tonamel\s*$", "", title).strip()
    desc = ld.get("description") or _meta(html, "og:description") or ""
    body = "" if desc else _strip_tags(html)
    haystack = f"{title}\n{desc}\n{body}\n{ld.get('address', '')}"

    posted_raw = tweet.get("createdAt") or ""
    posted_at = datetime.now(JST)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            posted_at = datetime.strptime(posted_raw, fmt).astimezone(JST)
            break
        except Exception:  # noqa: BLE001
            continue

    # JSON-LD にある項目はそれを信用し、無いものだけ本文から推測する
    date_str, time_str = parse_datetime(haystack, posted_at)
    venue, pref, is_online = parse_place(haystack, title)
    date_str = ld.get("date") or date_str
    time_str = ld.get("start_time") or time_str
    venue = ld.get("venue") or venue
    pref = ld.get("prefecture") or pref
    # オンライン判定は「会場の都道府県が取れなかったとき」だけ採用する。
    # 説明文に「オンライン対戦の練習に」等が混ざるだけでオンライン扱いされ、
    # 実在の会場(福井県)がオンラインに化けた事故があったため。
    # 会場から都道府県が特定できたなら、それが現地開催の何よりの証拠。
    # Tonamel側の開催形式(eventAttendanceMode)が Online のままになっている
    # 大会が実在する（設定し忘れ）ので、住所・会場名の判定を優先する。
    is_online = ld.get("online", is_online)
    if pref and pref != "オンライン":
        is_online = False
    if is_online and not pref:
        pref = "オンライン"

    author = (tweet.get("author") or {})
    org_name = ld.get("organizer_name") or author.get("name")

    return {
        "id": comp_id,
        "title": title,
        "url": url,
        "date": date_str,
        "start_time": time_str,
        "prefecture": pref,
        "venue": venue,
        "address": ld.get("address"),
        "online": bool(is_online),
        "fee": parse_money(haystack),
        "capacity": ld.get("capacity") or parse_capacity(haystack),
        "prize": parse_prize(haystack),
        "format": parse_format(haystack),
        "kind": parse_kind(title, haystack, org_name),
        "organizer_url": ld.get("organizer_url"),
        "summary": re.sub(r"\s+", " ", desc or body)[:200].strip(),
        "source_tweet_url": tweet.get("url"),
        # organizer_name は Tonamel(JSON-LD)の主催者。これが正。
        # ツイート主は「そのURLを流した人」でしかなく、主催者とは限らないので分ける。
        "organizer_handle": author.get("userName") if not ld.get("organizer_name") else None,
        "announced_by": author.get("userName"),
        "organizer_name": org_name,
        "pv": PARSER_VERSION,
        "tweeted_at": posted_at.isoformat(),
        "collected_at": datetime.now(JST).isoformat(),
    }


# ---------------------------------------------------------------- メイン

PREF_TO_REGION = {}
# 地域区分は「探す人の感覚」に合わせて細かめにする。
# 中部だと広すぎて（富山と静岡が同じ枠）実用にならないので、甲信越/北陸/東海に割る。
for _region, _prefs in {
    "北海道・東北": ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"],
    "関東": ["茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"],
    "甲信越": ["新潟県", "山梨県", "長野県"],
    "北陸": ["富山県", "石川県", "福井県"],
    "東海": ["岐阜県", "静岡県", "愛知県", "三重県"],
    "近畿": ["滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県"],
    "中国": ["鳥取県", "島根県", "岡山県", "広島県", "山口県"],
    "四国": ["徳島県", "香川県", "愛媛県", "高知県"],
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
        # 表示上の主催者は organizer_name(JSON-LD)だが、追跡すべきは
        # 「そのURLを流しているアカウント」。announced_by も拾う。
        h = e.get("organizer_handle") or e.get("announced_by")
        if not h:
            continue
        # キーマンは「自主大会を継続して開いている人」。
        # ショップの定例イベントは件数が多くなりがちなので数えない。
        if e.get("kind") and e["kind"] != "自主大会":
            continue
        if e.get("organizer_name") and re.search(SHOP_NAME_RE, norm(e["organizer_name"])):
            continue
        s = stats.setdefault(h, {"count": 0, "name": None, "prefs": {}})
        s["count"] += 1
        s["name"] = s["name"] or e.get("organizer_name") or e.get("organizer_handle")
        if e.get("prefecture"):
            s["prefs"][e["prefecture"]] = s["prefs"].get(e["prefecture"], 0) + 1

    for handle, s in stats.items():
        top_pref = max(s["prefs"], key=s["prefs"].get) if s["prefs"] else None
        # 複数県をまたいで開催している主催者を、1県だけの人と同じに見せない
        area_label = f"{top_pref}ほか" if top_pref and len(s["prefs"]) > 1 else top_pref
        if handle in seeds:
            seeds[handle].setdefault("area", area_label or "不明")
            continue
        if s["count"] < 2:          # 1回だけの主催はキーマン扱いしない
            continue
        seeds[handle] = {
            "handle": handle,
            "name": s["name"],
            "area": area_label or "不明",
            "region": PREF_TO_REGION.get(top_pref or "", "全国"),
            "note": f"直近3ヶ月で{s['count']}件の大会を主催しています。",
            "auto": True,
        }

    for o in seeds.values():
        o.setdefault("region", PREF_TO_REGION.get(o.get("area", "")[:4], "全国"))

    return sorted(seeds.values(), key=lambda o: (o.get("region", ""), o.get("name") or ""))


PENDING_PATH = DATA_DIR / "pending.json"


def load_pending() -> dict[str, dict]:
    """Twitterで見つけたがTonamel取得がまだ/失敗している大会IDの控え。"""
    if not PENDING_PATH.exists():
        return {}
    try:
        return json.loads(PENDING_PATH.read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_pending(pending: dict[str, dict]) -> None:
    PENDING_PATH.write_text(
        json.dumps(pending, ensure_ascii=False, indent=1), "utf-8"
    )


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    since = datetime.now(JST) - timedelta(days=LOOKBACK_DAYS)

    # SKIP_TWITTER=1 なら検索を丸ごと飛ばし、前回見つけた大会IDの取得だけをやり直す。
    # クレジットを1も使わずにリトライできるので、取得失敗した時の再実行用。
    skip_twitter = os.environ.get("SKIP_TWITTER") == "1"

    all_tweets: dict[str, dict] = {}
    if skip_twitter:
        log("■ SKIP_TWITTER=1: 検索は行わず、前回の未取得分だけ処理します")
    else:
        log(f"■ Twitter を検索します（{since:%Y-%m-%d} 以降 / {len(SEARCH_QUERIES)}クエリ）")
        for q in SEARCH_QUERIES:
            for tw in search_twitter(q, since):
                if tw.get("id"):
                    all_tweets[tw["id"]] = tw

    # 第2パス: 既知のキーマンの投稿を直接追う。
    # 「ポケカ」「自主大会」と書かずに告知する主催者を取りこぼさないための保険で、
    # これが件数と精度に一番効く。
    if FOLLOW_ORGANIZERS and not skip_twitter:
        seeds = load_seed_organizers()
        handles = [o["handle"] for o in seeds if o.get("handle")]
        handles += [o["alt_handle"] for o in seeds if o.get("alt_handle")]
        # 前回の収集で自動検出されたキーマンも追跡対象に加える。
        # 走らせるほど追跡対象が増えて、取りこぼしが減っていく。
        if OUT_PATH.exists():
            try:
                prev = json.loads(OUT_PATH.read_text("utf-8"))
                handles += [o["handle"] for o in prev.get("organizers", []) if o.get("handle")]
                handles += [e["announced_by"] for e in prev.get("events", []) if e.get("announced_by")]
            except Exception:  # noqa: BLE001
                pass
        # 重複除去（seedを優先して先頭に残す）
        handles = list(dict.fromkeys(h for h in handles if h))
        # 追跡アカウントが増えるほどコストが上がるので上限を設ける。
        # seedに手で登録した人は必ず追跡し、残りは「告知回数が多い順」に採る。
        seed_h = {o["handle"] for o in seeds if o.get("handle")}
        seed_h |= {o["alt_handle"] for o in seeds if o.get("alt_handle")}
        if len(handles) > ORG_MAX_HANDLES:
            freq: dict[str, int] = {}
            try:
                for e in json.loads(OUT_PATH.read_text("utf-8")).get("events", []):
                    a = e.get("announced_by")
                    if a:
                        freq[a] = freq.get(a, 0) + 1
            except Exception:  # noqa: BLE001
                pass
            others = sorted((h for h in handles if h not in seed_h),
                            key=lambda h: -freq.get(h, 0))
            keep = [h for h in handles if h in seed_h] + others
            handles = keep[:ORG_MAX_HANDLES]

        # ローテーション: seed以外は日替わりで一部だけ追う（コスト削減）
        if ORG_ROTATE_DAYS > 1:
            day = datetime.now(JST).timetuple().tm_yday % ORG_ROTATE_DAYS
            rotated = [h for h in handles if h in seed_h]
            others = [h for h in handles if h not in seed_h]
            rotated += [h for i, h in enumerate(others) if i % ORG_ROTATE_DAYS == day]
            handles = rotated
        log(f"■ 追跡アカウント {len(handles)}件"
            f"（手動登録 {len(seed_h & set(handles))}件 / {ORG_ROTATE_DAYS}日で一巡）")
        log(f"■ キーマン {len(handles)}アカウントの投稿を追跡します")
        # ★重要★ ここは1アカウントずつ投げる。理由は2つ。
        #  1) "tonamel.com" をAND条件に足すと結果がほぼゼロになる。
        #     本文のリンクは t.co に短縮されていて、本文に "tonamel.com" は存在しない。
        #  2) (from:A OR from:B ...) とまとめると、1クエリの取得枠(20件/ページ)を
        #     全員で分け合うことになり、投稿の多い人に埋もれて他の人が取れない。
        #     実測: 単体なら6大会取れるアカウントが、10人まとめると全体で4大会だった。
        # 主催者は投稿頻度が低く、毎日走らせるので1ページ(最新20件)で十分追える。
        org_since = datetime.now(JST) - timedelta(days=ORG_LOOKBACK_DAYS)
        # 大会が1件も取れていないキーマンは、期間もページ数も広げて深く追う。
        # 「登録したのに成果ゼロ」を放置しないための自己修復。
        # 告知は1〜3ヶ月前に出ることがあり、通常の追跡窓(14日)では届かないため。
        productive: set[str] = set()
        try:
            for e in json.loads(OUT_PATH.read_text("utf-8")).get("events", []):
                for k in ("organizer_handle", "announced_by"):
                    if e.get(k):
                        productive.add(e[k])
        except Exception:  # noqa: BLE001
            pass
        deep_since = datetime.now(JST) - timedelta(days=DEEP_ORG_LOOKBACK_DAYS)

        for h in handles:
            deep = h not in productive
            since_h = deep_since if deep else org_since
            pages_h = DEEP_ORG_PAGES if deep else ORG_PAGES
            tl = fetch_user_tweets(h, pages=pages_h)
            if tl:
                STATS["org_via_timeline"] = STATS.get("org_via_timeline", 0) + 1
            else:
                tl = search_twitter(f"from:{h}", since_h, pages=pages_h)
                if tl:
                    STATS["org_via_search"] = STATS.get("org_via_search", 0) + 1
                else:
                    STATS["org_no_result"] = STATS.get("org_no_result", 0) + 1
            for tw in tl:
                if tw.get("id"):
                    # 既知の主催者の投稿は「ポケカ」表記が無くても通す
                    tw["_trusted"] = True
                    all_tweets[tw["id"]] = tw

    log(f"■ 重複除去後のツイート数: {len(all_tweets)}")
    STATS["tweets_total"] = len(all_tweets)
    STATS["tweets_from_organizers"] = sum(
        1 for t in all_tweets.values() if t.get("_trusted"))

    # 大会ID → その大会を告知していたツイート（最も古いもの＝一次告知を採用）
    id_to_tweet: dict[str, dict] = {}
    for tw in all_tweets.values():
        if not tw.get("_trusted") and not looks_like_pokeca(tw.get("text", "")):
            continue
        for comp_id in extract_tonamel_ids(tw):
            prev = id_to_tweet.get(comp_id)
            if prev is None or (tw.get("createdAt", "") < prev.get("createdAt", "")):
                id_to_tweet[comp_id] = tw
    log(f"■ 今回の検索で見つかった Tonamel 大会: {len(id_to_tweet)}件")

    # 前回やり残した分と合流させ、すぐ控えに保存する。
    # ここで保存しておけば、この先で落ちても Twitter を叩き直さずに再開できる。
    pending = load_pending()
    for comp_id, tw in id_to_tweet.items():
        pending.setdefault(comp_id, tw)
    save_pending(pending)
    id_to_tweet = pending
    log(f"■ 未取得ぶんと合わせた処理対象: {len(id_to_tweet)}件")

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

    # FORCE_REFETCH=1 のときは、取得済みの大会も Tonamel から取り直して解析し直す。
    # 解析ロジックを改善したあとに、Twitterのクレジットを1も使わずに全件を作り直せる。
    force_refetch = os.environ.get("FORCE_REFETCH") == "1"
    if force_refetch:
        for comp_id, ev in existing.items():
            id_to_tweet.setdefault(comp_id, {
                "url": ev.get("source_tweet_url"),
                # 「8月23日」のような年なし表記の年推定に使うので、元の告知日時を引き継ぐ
                "createdAt": ev.get("tweeted_at") or "",
                "author": {
                    "userName": ev.get("organizer_handle"),
                    "name": ev.get("organizer_name"),
                },
            })
        log(f"■ FORCE_REFETCH=1: 取得済みを含む {len(id_to_tweet)}件を再解析します")

    # 解析ロジックが更新されていたら、取得済みの大会も対象に戻す（自己修復）
    stale_ids = [i for i, e in existing.items() if e.get("pv") != PARSER_VERSION]
    if stale_ids and not force_refetch:
        log(f"■ 解析バージョンが古い {len(stale_ids)}件を再解析対象にします")
        for comp_id in stale_ids:
            ev = existing[comp_id]
            id_to_tweet.setdefault(comp_id, {
                "url": ev.get("source_tweet_url"),
                "createdAt": ev.get("tweeted_at") or "",
                "author": {"userName": ev.get("announced_by") or ev.get("organizer_handle"),
                           "name": ev.get("organizer_name")},
            })

    log("■ Tonamel の大会ページから詳細を取得します")
    ok = miss = 0
    for i, (comp_id, tw) in enumerate(list(id_to_tweet.items()), 1):
        stale = existing.get(comp_id, {}).get("pv") != PARSER_VERSION
        if (not force_refetch and not stale
                and comp_id in existing and existing[comp_id].get("date")):
            pending.pop(comp_id, None)
            continue
        got = fetch_tonamel(comp_id)
        if not got:
            miss += 1
            continue
        html, url = got
        if save_raw:
            (RAW_DIR / f"{comp_id}.html").write_text(html, "utf-8")
        ev = build_event(comp_id, html, url, tw)
        # Twitter以外（公開一覧・Web検索）から拾ったものは、
        # ポケカ以外の大会が混ざるのでここで弾く。
        if tw.get("_source") in ("tonamel_public", "tonamel_org", "web_search") \
                and not is_pokeca_event(
                ev.get("title") or "", ev.get("summary") or "", html):
            pending.pop(comp_id, None)
            STATS["ポケカ以外として除外"] = STATS.get("ポケカ以外として除外", 0) + 1
            log(f"     ポケカ以外のためスキップ: {ev.get('title','')[:30]}")
            continue
        events[comp_id] = ev
        pending.pop(comp_id, None)     # 取れたので控えから外す
        ok += 1
        log(f"  {i:>3}/{len(id_to_tweet)}. {ev['date'] or '日付不明'} "
            f"{ev['prefecture'] or '?'} {ev['title'][:34]}")
        time.sleep(1.0)  # 相手サーバに優しく

    save_pending(pending)
    log(f"■ 取得成功 {ok}件 / 失敗・スキップ {miss}件 / 未処理の控え {len(pending)}件")

    # 終わった大会を落とし、掲載範囲（今日〜HORIZON_DAYS先）に絞る
    today = datetime.now(JST).strftime("%Y-%m-%d")
    horizon = (datetime.now(JST) + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%d")
    upcoming = [
        e for e in events.values()
        if not e.get("date") or (today <= e["date"] <= horizon)
    ]
    upcoming.sort(key=lambda e: (e.get("date") or "9999-99-99", e.get("start_time") or "99:99"))

    # 会場情報からどうしても都道府県が分からない大会は、
    # 同じ主催者の他の大会から推定して埋める（主催者はたいてい同じ地域で開催する）。
    infer_src: dict[str, Counter] = {}
    for e in upcoming:
        key = e.get("organizer_url") or e.get("organizer_name")
        if key and e.get("prefecture") and e["prefecture"] != "オンライン":
            infer_src.setdefault(key, Counter())[e["prefecture"]] += 1
    inferred = 0
    for e in upcoming:
        if e.get("prefecture"):
            continue
        key = e.get("organizer_url") or e.get("organizer_name")
        c = infer_src.get(key)
        if c:
            e["prefecture"] = c.most_common(1)[0][0]
            e["prefecture_inferred"] = True    # 推定であることを残す
            inferred += 1
    if inferred:
        log(f"■ 主催者の他大会から地域を推定: {inferred}件")

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
    STATS["events_total"] = len(upcoming)
    (DATA_DIR / "collect_stats.json").write_text(
        json.dumps(STATS, ensure_ascii=False, indent=2), "utf-8")

    log(f"■ 完了: {OUT_PATH} に {len(upcoming)}件 / キーマン{len(organizers)}人 を保存しました")
    log(f"   掲載期間: {today} 〜 {horizon}")
    log(f"   地域内訳: {', '.join(f'{k}{v}' for k, v in list(by_pref.items())[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
