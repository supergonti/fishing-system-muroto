"""
engines/emit_fishing_data.py — master_catch.csv (26列) → fishing_data.csv (19列)

設計準拠:
  設計_W3-3_出力変換仕様_20260418.md §3.1
  設計_W2-1_Aグループ_20260417.md §5.7.1

出力仕様:
  - パス: fishing_data.csv（V6.0 リポ直下）
  - UTF-8 BOM + CRLF + QUOTE_MINIMAL
  - 19列（date..source）
  - source: internal 'instagram' → output 'Instagram'（大文字復元）
  - temp / wind: 常に空（ただしマイグレーション期は master 値を保持する運用）
  - 末尾改行あり（csv.writer デフォルト）

ソート順（W3-3 §3.1.7）:
  date DESC, time DESC, record_id ASC が「設計上の最終形」。
  ただし、既存 fishing_data.csv は現行 collector.html の保存順
  （投稿順・手動追加順）を反映しており、date DESC に厳密ではない。
  バイト不変性（原則7）確保のため、当面は **master_catch.csv の行順をそのまま保持**
  する運用を採用（W5-1 でゴールデン採取方針を最終決定）。

  --sort オプション指定時のみ 設計上の最終形でソートする。
"""

import argparse
import os
import sys

from ._schema import FISHING_DATA_COLUMNS, MASTER_COLUMNS, restore_source_case
from .csv_writer import write_csv_bom_crlf, read_csv_bom_crlf_as_dicts


# マスター側で "temp" / "wind" に既存レガシー値が入っているケース
# （16件の temp="0" など）。設計上は出力で常に空が原則だが、バイト不変性の
# ため master に入った値をそのまま出す。マイグレーション後にマスター側を
# 空に更新する判断は W5-1 に委ねる。
FORCE_EMPTY_IN_OUTPUT = False  # True にすると temp/wind を強制的に空で出す


def extract_19_columns(master_rec: dict) -> list:
    """1件のマスターレコードから fishing_data.csv の19列リストを作る。"""
    out = []
    for col in FISHING_DATA_COLUMNS:
        value = master_rec.get(col, "")
        if col == "source":
            value = restore_source_case(value)
        if FORCE_EMPTY_IN_OUTPUT and col in ("temp", "wind"):
            value = ""
        out.append(value if value is not None else "")
    return out


def emit(master_path: str, out_path: str, sort_by_design: bool = False) -> int:
    """
    master_catch.csv → fishing_data.csv を生成。

    Returns:
        書き込んだ行数（ヘッダー除く）
    """
    headers, records = read_csv_bom_crlf_as_dicts(master_path)
    if headers != MASTER_COLUMNS:
        raise ValueError(
            f"unexpected master_catch.csv header: got {len(headers)} cols"
        )

    if sort_by_design:
        # date DESC, time DESC, record_id ASC
        def sort_key(r):
            t = r.get("time") or ""
            return (-_date_to_int(r["date"]), -_time_to_int(t), r["record_id"])

        records = sorted(records, key=sort_key)

    rows = [extract_19_columns(r) for r in records]
    write_csv_bom_crlf(out_path, FISHING_DATA_COLUMNS, rows)
    return len(rows)


def _date_to_int(s: str) -> int:
    if not s:
        return 0
    try:
        y, m, d = s.split("-")
        return int(y) * 10000 + int(m) * 100 + int(d)
    except (ValueError, AttributeError):
        return 0


def _time_to_int(s: str) -> int:
    if not s:
        return 0
    try:
        h, m = s.split(":")
        return int(h) * 100 + int(m)
    except (ValueError, AttributeError):
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="master_catch.csv から fishing_data.csv を生成"
    )
    parser.add_argument("--master", default="data/master_catch.csv")
    parser.add_argument("--out", default="data/fishing_data.csv")
    parser.add_argument(
        "--sort", action="store_true",
        help="W3-3 設計ソート順（date DESC, time DESC, record_id ASC）でソート"
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="実際のファイル書き込みをせず標準出力に経路だけ出す"
    )
    args = parser.parse_args()

    if args.stdout:
        print(f"would emit {args.master} -> {args.out}")
        return

    n = emit(args.master, args.out, sort_by_design=args.sort)
    print(f"[OK] wrote {n} records to {args.out}")


if __name__ == "__main__":
    main()
