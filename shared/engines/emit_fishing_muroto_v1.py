"""
engines/emit_fishing_muroto_v1.py — master_catch.csv × C③ × C④2点 → fishing_muroto_v1.csv (42列)

設計準拠:
  設計_W3-3_出力変換仕様_20260418.md §3.2
  設計_W2-1_Aグループ_20260417.md §5.7.2

出力仕様:
  - パス: fishing_muroto_v1.csv（V6.0 リポ直下）
  - UTF-8 BOM + CRLF + QUOTE_MINIMAL
  - 42列（fishing_data.csv 19列 + 気象3 + 海流8 + 気象12）

42列構成（実検証で確定、W3-3 §3.2.2）:
  [0..18]  fishing_data 19列
  [19..21] 潮汐 / 月齢 / 月相                   from C③
  [22..25] 室戸沖_流速kn / 流向 / 水温 / 塩分   from C④ (point=室戸沖)
  [26..29] 北西_流速kn / 流向 / 水温 / 塩分      from C④ (point=北西)
  [30..41] 気温_平均 / 気温_最高 / 気温_最低 / 風速_最大 / 風向 /
           降水量 / 天気コード / 天気 /
           水温(Open-Meteo) / 最大波高 / 波向 / 波周期                from C③

結合ロジック:
  - A全行を保持（LEFT JOIN）
  - 気象15列: キー (date, nearest_station) で C③ と LEFT JOIN
            欠損時は15列すべて空
  - 海流8列: spot に "室戸" を部分一致で含む行のみ埋める
           キー (date, "室戸沖") / (date, "北西") で C④ と LEFT JOIN
           含まない行または C④ 欠損は対応 4列が空

v1 仕様の重要ポイント（W3-3 §3.2.5）:
  C③列名は **_計測 サフィックスなし** でそのまま使う。
  （fishing_integrated.csv は _計測 サフィックス4列を付ける、別仕様）

  C③元列名 "水温" → muroto_v1 出力列名 "水温(Open-Meteo)"（実検証確認）
"""

import argparse
import os
import sys

from ._schema import FISHING_DATA_COLUMNS, MASTER_COLUMNS, restore_source_case
from .csv_writer import write_csv_bom_crlf, read_csv_bom_crlf_as_dicts


# 44列ヘッダ（W3-3 §3.2.2 基本42列 + Muroto 拡張2列 boat_id/area_id）
MUROTO_V1_COLUMNS = FISHING_DATA_COLUMNS + [
    "潮汐", "月齢", "月相",
    "室戸沖_流速kn", "室戸沖_流向", "室戸沖_水温", "室戸沖_塩分",
    "北西_流速kn", "北西_流向", "北西_水温", "北西_塩分",
    "気温_平均", "気温_最高", "気温_最低", "風速_最大", "風向",
    "降水量", "天気コード", "天気", "水温(Open-Meteo)",
    "最大波高", "波向", "波周期",
    "boat_id", "area_id",
]

# C③ の列順（21列）— read 時に header を確認する
C3_COLUMNS = [
    "日付", "地点名", "観測地点名", "県", "緯度", "経度",
    "気温_平均", "気温_最高", "気温_最低", "風速_最大", "風向",
    "降水量", "天気コード", "天気", "水温", "最大波高", "波向", "波周期",
    "潮汐", "月齢", "月相",
]

# C④ の列順（11列）
C4_COLUMNS = [
    "date", "point", "lat", "lon", "u_ms", "v_ms",
    "speed_ms", "speed_kn", "direction", "temp_c", "salinity",
]


def _load_c3_index(c3_path: str) -> dict:
    """C③ fishing_condition_db.csv を (日付, 地点名) → dict で索引化。"""
    headers, rows = read_csv_bom_crlf_as_dicts(c3_path)
    if headers != C3_COLUMNS:
        raise ValueError(
            f"unexpected fishing_condition_db.csv header: got {headers}"
        )
    index = {}
    for r in rows:
        key = (r["日付"], r["地点名"])
        index[key] = r
    return index


def _load_c4_index(c4_path: str) -> dict:
    """C④ muroto_offshore_current_all.csv を (date, point) → dict で索引化。"""
    headers, rows = read_csv_bom_crlf_as_dicts(c4_path)
    if headers != C4_COLUMNS:
        raise ValueError(
            f"unexpected muroto_offshore_current_all.csv header: got {headers}"
        )
    index = {}
    for r in rows:
        key = (r["date"], r["point"])
        index[key] = r
    return index


def build_row(master_rec: dict, c3_index: dict, c4_index: dict) -> list:
    """1件のマスター行から muroto_v1 の 42 列リストを作る。"""
    # 先頭19列: master の値そのまま（source は大文字復元）
    out = []
    for col in FISHING_DATA_COLUMNS:
        v = master_rec.get(col, "")
        if col == "source":
            v = restore_source_case(v)
        out.append(v if v is not None else "")

    # 気象: C③ LEFT JOIN
    # W7-1 note: nearest_station が "不明" の行は、C③（fishing_condition_db.csv）
    # に ("不明") 行が存在しないため、c3_index.get() が None を返し空JOINとなる
    # （気象15列は空文字列）。実害はないが、CI の「不明行検出ガード」で push 前に
    # 弾かれる設計（.github/workflows/sync_after_*.yml 参照）。
    key_c3 = (master_rec.get("date", ""), master_rec.get("nearest_station", ""))
    c3 = c3_index.get(key_c3)

    def g3(c):
        return c3.get(c, "") if c3 else ""

    # 19..21: 潮汐, 月齢, 月相
    out.extend([g3("潮汐"), g3("月齢"), g3("月相")])

    # 海流: spot に "室戸" を含む行のみ
    spot = master_rec.get("spot", "")
    use_current = "室戸" in spot
    if use_current:
        c4_mu = c4_index.get((master_rec.get("date", ""), "室戸沖"))
        c4_hk = c4_index.get((master_rec.get("date", ""), "北西"))
    else:
        c4_mu = None
        c4_hk = None

    def g4(cur, key):
        return cur.get(key, "") if cur else ""

    # 22..25: 室戸沖_流速kn, _流向, _水温, _塩分
    out.extend([
        g4(c4_mu, "speed_kn"),
        g4(c4_mu, "direction"),
        g4(c4_mu, "temp_c"),
        g4(c4_mu, "salinity"),
    ])
    # 26..29: 北西_流速kn, _流向, _水温, _塩分
    out.extend([
        g4(c4_hk, "speed_kn"),
        g4(c4_hk, "direction"),
        g4(c4_hk, "temp_c"),
        g4(c4_hk, "salinity"),
    ])

    # 30..41: 気温_平均〜波周期 (C③ の 水温 は "水温(Open-Meteo)" として出す)
    out.extend([
        g3("気温_平均"), g3("気温_最高"), g3("気温_最低"),
        g3("風速_最大"), g3("風向"), g3("降水量"),
        g3("天気コード"), g3("天気"), g3("水温"),  # これが出力 "水温(Open-Meteo)" 列
        g3("最大波高"), g3("波向"), g3("波周期"),
    ])

    # Muroto 拡張: boat_id, area_id を末尾に追加（42→44列、後方互換）
    out.extend([
        master_rec.get("boat_id", ""),
        master_rec.get("area_id", ""),
    ])

    return out


def emit(
    master_path: str,
    c3_path: str,
    c4_path: str,
    out_path: str,
) -> int:
    """master × C③ × C④ で fishing_muroto_v1.csv を生成。"""
    headers, master_records = read_csv_bom_crlf_as_dicts(master_path)
    if headers != MASTER_COLUMNS:
        raise ValueError(f"unexpected master header: {headers}")

    c3_index = _load_c3_index(c3_path)
    c4_index = _load_c4_index(c4_path)

    rows = [build_row(r, c3_index, c4_index) for r in master_records]
    write_csv_bom_crlf(out_path, MUROTO_V1_COLUMNS, rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="master_catch.csv × C③ × C④2点 → fishing_muroto_v1.csv を生成"
    )
    parser.add_argument("--master", default="data/master_catch.csv")
    parser.add_argument("--c3", default="data/fishing_condition_db.csv")
    parser.add_argument(
        "--c4",
        default="data/muroto_offshore_current_all.csv",
    )
    parser.add_argument("--out", default="data/fishing_muroto_v1.csv")
    args = parser.parse_args()

    n = emit(args.master, args.c3, args.c4, args.out)
    print(f"[OK] wrote {n} records to {args.out}")


if __name__ == "__main__":
    main()
