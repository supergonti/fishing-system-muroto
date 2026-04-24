"""
engines/emit_fishing_integrated.py — master_catch.csv × C③ → fishing_integrated.csv (34列)

設計準拠:
  設計_W3-3_出力変換仕様_20260418.md §3.3
  設計_W2-1_Aグループ_20260417.md §5.7.3

出力仕様:
  - パス: fishing_integrated.csv（V6.0 リポ直下）
  - UTF-8 BOM + CRLF + QUOTE_MINIMAL
  - 34列（fishing_data 19列 + C③ 由来 15 列）
  - `_計測` サフィックス4列のみ（潮汐_計測, 天気_計測, 水温_計測, 風向_計測）
  - 他 11 列はそのまま（気温_平均, 気温_最高, 気温_最低, 風速_最大, 降水量,
    天気コード, 最大波高, 波向, 波周期, 月齢, 月相）

34列構成（実検証で確定、W3-3 §3.3.2）:
  [0..18]  fishing_data 19列
  [19..21] 気温_平均, 気温_最高, 気温_最低
  [22]     風速_最大
  [23]     風向_計測              (C③ "風向" に _計測 サフィックス)
  [24]     降水量
  [25]     天気コード
  [26]     天気_計測              (C③ "天気")
  [27]     水温_計測              (C③ "水温")
  [28..30] 最大波高, 波向, 波周期
  [31]     潮汐_計測              (C③ "潮汐")
  [32..33] 月齢, 月相

結合ロジック:
  - A全行を保持（LEFT JOIN）
  - キー (date, nearest_station) で C③ と JOIN
  - C③ 欠損時は15列すべて空（`nearest_station='その他'` 含む）
"""

import argparse
import os
import sys

from ._schema import FISHING_DATA_COLUMNS, MASTER_COLUMNS, restore_source_case
from .csv_writer import write_csv_bom_crlf, read_csv_bom_crlf_as_dicts
from .emit_fishing_muroto_v1 import _load_c3_index, C3_COLUMNS


# 36列ヘッダ（W3-3 §3.3.2 基本 + Muroto 拡張2列 boat_id/area_id を末尾追加）
INTEGRATED_COLUMNS = FISHING_DATA_COLUMNS + [
    "気温_平均", "気温_最高", "気温_最低",
    "風速_最大", "風向_計測",
    "降水量", "天気コード", "天気_計測", "水温_計測",
    "最大波高", "波向", "波周期",
    "潮汐_計測", "月齢", "月相",
    "boat_id", "area_id",
]


def build_row(master_rec: dict, c3_index: dict) -> list:
    """1件のマスター行から integrated の 36 列リストを作る（末尾 boat_id/area_id 付き）。"""
    out = []
    for col in FISHING_DATA_COLUMNS:
        v = master_rec.get(col, "")
        if col == "source":
            v = restore_source_case(v)
        out.append(v if v is not None else "")

    key = (master_rec.get("date", ""), master_rec.get("nearest_station", ""))
    c3 = c3_index.get(key)

    def g(k):
        return c3.get(k, "") if c3 else ""

    # C③ 由来 15列（_計測 サフィックス4列を含む）
    out.extend([
        g("気温_平均"), g("気温_最高"), g("気温_最低"),
        g("風速_最大"),
        g("風向"),      # → 風向_計測
        g("降水量"),
        g("天気コード"),
        g("天気"),      # → 天気_計測
        g("水温"),      # → 水温_計測
        g("最大波高"), g("波向"), g("波周期"),
        g("潮汐"),      # → 潮汐_計測
        g("月齢"), g("月相"),
    ])

    # Muroto 拡張: boat_id, area_id を末尾に追加
    out.extend([
        master_rec.get("boat_id", ""),
        master_rec.get("area_id", ""),
    ])

    return out


def emit(master_path: str, c3_path: str, out_path: str) -> int:
    """master × C③ で fishing_integrated.csv を生成。"""
    headers, master_records = read_csv_bom_crlf_as_dicts(master_path)
    if headers != MASTER_COLUMNS:
        raise ValueError(f"unexpected master header: {headers}")

    c3_index = _load_c3_index(c3_path)

    rows = [build_row(r, c3_index) for r in master_records]
    write_csv_bom_crlf(out_path, INTEGRATED_COLUMNS, rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="master_catch.csv × C③ → fishing_integrated.csv を生成"
    )
    parser.add_argument("--master", default="data/master_catch.csv")
    parser.add_argument("--c3", default="data/fishing_condition_db.csv")
    parser.add_argument("--out", default="data/fishing_integrated.csv")
    args = parser.parse_args()

    n = emit(args.master, args.c3, args.out)
    print(f"[OK] wrote {n} records to {args.out}")


if __name__ == "__main__":
    main()
