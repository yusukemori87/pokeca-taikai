#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026年8月3日時点で、検索経由で実在を確認できた大会を events.json として書き出す初期データ。
全て Tonamel の実ページを開いて確認したもの。推測項目は null。

※これは「Twitter APIなしでどこまで拾えるか」の実測結果であり、網羅ではありません。
   本番は scripts/collect.py が上書きします。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent

E = lambda **k: k  # noqa: E731

EVENTS = [
    E(id="IN7YC", title="【オーガナイザーイベント】社会人ポケカ研究会【8月】", date="2026-08-07",
      start_time=None, prefecture="東京都", venue="デュエルサロン太陽", fee=None, capacity=None,
      prize=None, format="交流会（レンタルデッキあり）", kind="交流会",
      organizer_handle=None, organizer_name="社会人ポケカ研究会", confidence="medium",
      summary="フリー対戦形式の交流会。レンタルデッキあり。"),

    E(id="JIfgJ", title="⚡️Light-Zing Scrim⚡️特別編", date="2026-08-09",
      start_time="10:00", prefecture="栃木県", venue="宇都宮市雀宮地区市民センター 第1・第2ホール",
      fee="1,000円", capacity=None,
      prize="優勝：ムニキズゼロ2BOX / 準優勝：1BOX / 3-4位：15パック / サイドイベント優勝：1BOX",
      format="スタンダード", kind="自主大会",
      organizer_handle=None, organizer_name="にゃんこ・ともきち", confidence="high",
      summary="スイスドロー最大6回戦＋上位16／17-32位トーナメント。栃木県内では珍しい大型自主大会。"),

    E(id="neVnN", title="第2回すぷりんぴっく（WCS2010）", date="2026-08-09",
      start_time=None, prefecture="東京都", venue=None, fee=None, capacity=None, prize=None,
      format="WCS2010レギュレーション（旧環境再現）", kind="自主大会",
      organizer_handle=None, organizer_name=None, confidence="medium",
      summary="2010年世界大会環境を再現する旧レギュ大会。詳細は主催のnoteに記載。"),

    E(id="mEavl", title="下北沢ポケカCS2026 SUMMER", date="2026-08-11",
      start_time="13:00", prefecture="東京都", venue="北沢タウンホール 3階（下北沢）",
      fee="2,000円", capacity=70,
      prize="1位：ストームエメラルダ3BOX / 2位：2BOX / 3-4位：1BOX / 5-16位：10パック",
      format="スタンダード", kind="自主大会",
      organizer_handle="ohara_las_0123", organizer_name="オハら", confidence="high",
      summary="予選スイスドロー＋決勝トーナメント。同日夜にGLC部門も併催。"),

    E(id="eZcRj", title="下北沢ポケカCS2026［GLC］", date="2026-08-11",
      start_time="18:00", prefecture="東京都", venue="北沢タウンホール（下北沢）",
      fee="200円（本戦参加者は無料）", capacity=32,
      prize="最新弾BOXを全勝者で山分け",
      format="GLC（ジムリーダーチャレンジ）", kind="自主大会",
      organizer_handle="ohara_las_0123", organizer_name="オハら", confidence="high",
      summary="単タイプ・ポケモン1枚制限のGLC3回戦。本戦のあとの夜開催。"),

    E(id="Lb50s", title="【カーデリア池袋店／ポケカ】BOX争奪戦", date="2026-08-12",
      start_time="13:00", prefecture="東京都", venue="カーデリア池袋店",
      fee="500円", capacity=32,
      prize="優勝：選べる1BOX / 2-6位：500円分店内クーポン",
      format="スタンダード", kind="ショップ主催",
      organizer_handle=None, organizer_name="カーデリア池袋店", confidence="high",
      summary="スイスドロー最大5回戦。カードショップ主催の店舗イベント。"),

    E(id="WrDaX", title="U22ブーストしんか", date="2026-08-13",
      start_time="10:00", prefecture="東京都",
      venue="としま区民センター 会議室701・702・703（池袋駅）",
      fee="競技1,000円／観戦500円／保護者・未就学児 無料", capacity=64,
      prize="1位：ストームエメラルダ2BOX / 2位：1BOX",
      format="スタンダード", kind="自主大会",
      organizer_handle="miracle_twin", organizer_name="ミルミル・しゅれ", confidence="high",
      summary="22歳以下限定。予選スイスドロー6回戦BO1、決勝シングルエリミBO3。"),

    E(id="vwluI", title="トレカアライブ 2026 非公認ポケモンカードゲーム予選大会（東京大会Vol.2）",
      date="2026-08-13", start_time="10:00", prefecture="東京都", venue="Zepp DiverCity",
      fee="無料", capacity=252,
      prize="参加者全員に大会オリジナルスリーブ",
      format="スタンダード", kind="自主大会",
      organizer_handle=None, organizer_name="株式会社日本トレカセンター", confidence="high",
      summary="スイスドロー全7回戦＋決勝シングルエリミネーション。参加無料・252名規模。"),

    E(id="N6pT4", title="【オーガナイザーイベント】社会人ポケカ研究会【8月】", date="2026-08-14",
      start_time=None, prefecture="東京都", venue="デュエルサロン太陽", fee=None, capacity=None,
      prize=None, format="交流会", kind="交流会",
      organizer_handle=None, organizer_name="社会人ポケカ研究会", confidence="medium",
      summary="フリー対戦形式の交流会。"),

    E(id="x4Ra5", title="第一回「スタンダード休肝日」", date="2026-08-15",
      start_time="10:00", prefecture="埼玉県", venue="草加市文化会館 3F 第1会議室",
      fee="1,500円", capacity=100,
      prize="優勝：カプ・コケコGX SR / ベスト8：ストームエメラルダ5パック / 参加者全員にオリジナルパック",
      format="エクストラ", kind="自主大会",
      organizer_handle="often330", organizer_name=None, confidence="high",
      summary="エクストラ限定。予選スイスドロー6回戦BO1・25分、決勝シングルエリミBO1。"),

    E(id="KYpP5", title="【第４回】トレコネポケカフェス＠南浦和", date="2026-08-16",
      start_time="10:00", prefecture="埼玉県", venue="さいたま市文化センター",
      fee="2,000円（小学生以下1,000円）", capacity=107,
      prize="1位：2BOX / 2位：1BOX / 3位：20パック / 4位：10パック / ベスト16：1,000円分金券",
      format="スタンダード", kind="自主大会",
      organizer_handle="Toreca_connect", organizer_name="トレカコネクト", confidence="high",
      summary="予選スイスドロー5回戦＋決勝3回戦・各25分。100人超規模でサイドイベントあり。"),

    E(id="z9vh9", title="第4回 かゆ・きぃた杯【エクストラ】", date="2026-08-16",
      start_time="11:30", prefecture="埼玉県", venue="寄居町中央公民館 会議室C",
      fee="1,000円（高校生以下・CL2026愛知エクストラ入賞者は500円）", capacity=52,
      prize="1-4位に未開封BOX＋サプライ、主催セレクトのプレイマット（選択制）",
      format="エクストラ", kind="自主大会",
      organizer_handle="kayu_key_gx", organizer_name="かゆ・きぃた杯", confidence="medium",
      summary="エクストラ専門の自主大会。予選スイスドロー5回戦・25分＋上位8名決勝。"),

    E(id="AqBf3", title="第２回 ななせ杯", date="2026-08-16",
      start_time="13:50", prefecture="東京都",
      venue="としま区民センター 601・602会議室（豊島区東池袋）",
      fee="2,000円", capacity=64,
      prize="1位：拡張パック3BOX / 2位：ニャースex(SAR) / 3位：ヒルベルト(SAR) / 4位：メガガルーラex(SAR) / 参加者全員にオリジナルパック",
      format="スタンダード", kind="自主大会",
      organizer_handle="nanase_cup", organizer_name="Team dot.", confidence="medium",
      summary="スイスドロー予選最大6回戦＋上位8名シングルエリミ。ギャラドスシールド協賛。"),

    E(id="HYiLc", title="【オーガナイザーイベント】社会人ポケカ研究会【8月】", date="2026-08-21",
      start_time=None, prefecture="東京都", venue="デュエルサロン太陽", fee=None, capacity=None,
      prize=None, format="交流会", kind="交流会",
      organizer_handle=None, organizer_name="社会人ポケカ研究会", confidence="medium",
      summary="フリー対戦形式の交流会。"),

    E(id="YPWBV", title="第2回 パルテノンみやじ杯", date="2026-08-22",
      start_time="11:40", prefecture="神奈川県",
      venue="カードボックス星白堂矢向店（横浜市鶴見区矢向）",
      fee="2,000円", capacity=102,
      prize="上位入賞者にBOX＋シングル券（1位2,000円相当〜16位3パック）、主催撃破で「みやじオリパ」",
      format="スタンダード", kind="自主大会",
      organizer_handle=None, organizer_name="パルテノンみやじ", confidence="high",
      summary="個人戦。予選スイスドロー6回戦＋決勝トーナメント4回戦。100人超規模。"),

    E(id="gN6yZ", title="第２回 机上論者杯", date="2026-08-22",
      start_time="12:30", prefecture="埼玉県", venue="TSUTAYA レイクタウン",
      fee="1,500円", capacity=32,
      prize="1位：ストームエメラルダ2BOX / 2位：1BOX / 3位：20パック / 4位：10パック / ベスト8：サプライ",
      format="エクストラ", kind="自主大会",
      organizer_handle=None, organizer_name=None, confidence="high",
      summary="エクストラ。予選スイスドロー5回戦＋上位8名シングルエリミネーション。"),

    E(id="B8U3T", title="第三回チームバッフロンWP杯", date="2026-08-23",
      start_time="13:10", prefecture="東京都", venue="カードシークレット池袋店",
      fee="1,200円（200円分の店内ポイント含む）", capacity=None,
      prize="1位：2BOX＋10,000円分金券＋バッフロンex SAR / 2位：1BOX＋5,000円分＋SR / 3位：1BOX＋3,000円分",
      format="スタンダード", kind="自主大会",
      organizer_handle=None, organizer_name="チームバッフロン", confidence="medium",
      summary="予選スイスドロー6回戦固定BO1・25分＋上位8名シングルエリミネーション。景品が非常に厚い。"),

    E(id="vuGL2", title="【オーガナイザーイベント】社会人ポケカ研究会【8月】", date="2026-08-28",
      start_time=None, prefecture="東京都", venue="デュエルサロン太陽", fee=None, capacity=None,
      prize=None, format="交流会", kind="交流会",
      organizer_handle=None, organizer_name="社会人ポケカ研究会", confidence="medium",
      summary="フリー対戦形式の交流会。"),

    E(id="FFTO4", title="コシガヤシティジム vol.20 ～SummerEvent～ ランダム5人チーム戦！",
      date="2026-08-30", start_time="13:00", prefecture="埼玉県", venue="越谷コミュニティセンター",
      fee="500円（20歳以上の懇親会は別途3,500円）", capacity=30,
      prize="優勝チーム：最新弾1BOX / 準優勝：5パック / 個人最多勝：3パック / 参加者全員ビンゴ抽選",
      format="チーム戦", kind="自主大会",
      organizer_handle="koshigym0428", organizer_name="コシガヤシティジム", confidence="medium",
      summary="ランダム5人チーム戦。総当たり・各25分・デッキ変更不可・セルフジャッジ。"),
]

# 各地で継続的に自主大会を主催している「キーマン」。
# 直近の開催予定が拾えていない人も、フォロー先として価値があるので載せる。
ORGANIZERS = [
    dict(handle="deregmu_og", name="ディレグム", area="富山県", region="中部",
         note="富山の自主大会シーンの中心人物。「ディレグム杯EX」を主催し、小矢部市で120人規模を実施。射水市の大門総合会館も会場に使用。",
         alt_handle="deregmu_hobby"),
    dict(handle="tomoshibi_cup", name="ともしび杯", area="石川県金沢市", region="中部",
         note="北陸最大級の自主大会シリーズ。第4回・第5回は約130人規模。第7回は2周年記念の「メガともしび杯」。"),
    dict(handle="ISHIKAWAPOKECA", name="石川ポケカCS", area="石川県", region="中部",
         note="「石川ポケカCS」「ビギナー🔰杯」「BOX争奪戦」を継続開催。主会場は北国書林松任店（白山市）。"),
    dict(handle="kajipoke", name="かじ", area="広島県東広島市", region="中国・四国",
         note="「きんのたま杯」主催。自主大会の立ち上げ方をnoteで解説しており、これから主催したい人の参考になる。"),
    dict(handle="koshigym0428", name="コシガヤシティジム", area="埼玉県越谷市", region="関東",
         note="越谷コミュニティセンターで月1〜2回のペースでvol.番号付き連番開催。over30cup、ファミリースタジアム、チーム戦など企画型が多い。"),
    dict(handle="Toreca_connect", name="トレカコネクト", area="埼玉県さいたま市", region="関東",
         note="「トレコネポケカフェス」を第4回まで開催。100人規模でジュニア料金設定あり。"),
    dict(handle="ohara_las_0123", name="オハら", area="東京都下北沢", region="関東",
         note="「下北沢ポケカCS」シリーズ。本戦（スタンダード）＋夜のGLCという2部構成を毎回組んでいる。"),
    dict(handle="kayu_key_gx", name="かゆ・きぃた杯", area="埼玉県寄居町", region="関東",
         note="エクストラレギュレーション専門の自主大会を第4回まで開催。50人規模。"),
    dict(handle="nanase_cup", name="ななせ杯（Team dot.）", area="東京都池袋", region="関東",
         note="としま区民センターで64人規模の個人戦。ギャラドスシールド協賛。"),
    dict(handle="miracle_twin", name="ミルミル", area="東京都池袋", region="関東",
         note="しゅれ(@shure_poke)と共同で22歳以下限定大会「U22ブーストしんか」を主催。", alt_handle="shure_poke"),
    dict(handle="hokkaidoPTCG", name="北海道ポケカ自主大会まとめ", area="北海道", region="北海道・東北",
         note="北海道の自主大会情報をまとめて発信しているアカウント。道内を探すならまずここ。"),
    dict(handle="torepoinfo", name="トレポ｜自主大会交流会まとめ", area="全国", region="全国",
         note="全国の自主大会・交流会をまとめて発信しているアカウント。"),
    dict(handle="SHIMA_PCG", name="しま", area="広島県", region="中国・四国",
         note="「ならくのうらもん杯」主催。"),
    dict(handle="OP01_soda", name="そだ", area="東京都秋葉原", region="関東",
         note="「ポケカ×そだ杯」主催。会場はカードショップポンポコ。"),
]

now = datetime.now(JST)
events = []
for e in EVENTS:
    e = dict(e)
    e.update(
        url=f"https://tonamel.com/competition/{e['id']}",
        online=False,
        source_tweet_url=None,
        tweeted_at=None,
        collected_at=now.isoformat(),
        source="web-search-seed",
    )
    events.append(e)

events.sort(key=lambda x: (x["date"], x["start_time"] or "99:99"))

out = ROOT / "data" / "events.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    "generated_at": now.isoformat(),
    "count": len(events),
    "coverage_note": "2026-08-03時点。Twitter API未接続のため、検索エンジン経由で実在確認できた分のみ。関東に大きく偏っています。",
    "events": events,
    "organizers": ORGANIZERS,
}, ensure_ascii=False, indent=2), "utf-8")
print(f"実データ {len(events)}件 / キーマン {len(ORGANIZERS)}人 を書き出しました: {out}")
