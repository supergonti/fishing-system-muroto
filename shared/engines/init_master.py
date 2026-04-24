"""
engines/init_master.py — 既存 fishing_data.csv 858行 → master_catch.csv (26列) 初期化

設計準拠:
  設計_W3-3_出力変換仕様_20260418.md §9.6（W5-1 マイグレーション仕様を先取り実装）
  設計_W2-1_Aグループ_20260417.md §2.1 / §2.2

ポリシー（**重要**: バイト不変保持）:
  1. 既存 fishing_data.csv の 19列値は **一切正規化しない**。
     - tide="潮動かず"（値域外）のような自由記述もそのまま保持
     - temp="0" の 16件もそのまま保持
     - 空値もそのまま空で保持
  2. 既存の行順を **完全保持**。UUID を付与する順序もこの順。
  3. source 値は内部小文字化: "Instagram" → "instagram"
  4. 新設メタ列（record_id / canonical_spot / sea_area / entered_at /
     source_detail / prompt_version / confidence）を付与:
     - record_id: UUID v4 新規生成（決定論的に固定するためシード付き uuid5 を使う場合は記述）
     - entered_at: 時刻情報がないため、`{date}T00:00:00+09:00` を fallback 採用
     - canonical_spot / sea_area: 空（B側で W4-2 以降に補完）
     - source_detail / prompt_version / confidence: 空（インスタメタ情報がマスター化時には残っていない）

CLI:
  python3 -m engines.init_master [--force]
"""

import argparse
import csv
import os
import sys
import uuid

from ._schema import MASTER_COLUMNS, FISHING_DATA_COLUMNS, empty_master_record
from .csv_writer import write_csv_bom_crlf


def init_master_from_fishing_data(
    src_path: str, dst_path: str, seed_namespace: str = None
) -> int:
    """
    既存 fishing_data.csv から master_catch.csv を生成する。

    Args:
        src_path: 既存 fishing_data.csv のパス
        dst_path: 生成する master_catch.csv のパス
        seed_namespace: UUID v5 のネームスペース文字列（決定論的生成用、任意）

    Returns:
        書き込んだレコード数
    """
    with open(src_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        src_rows = [row for row in reader]

    # header 整合確認
    if header != FISHING_DATA_COLUMNS:
        raise ValueError(
            f"unexpected fishing_data.csv header: got {header} != "
            f"expected {FISHING_DATA_COLUMNS}"
        )

    # UUID 決定論的生成（将来の再生成時もバイト一致するため）
    ns = None
    if seed_namespace:
        ns = uuid.uuid5(uuid.NAMESPACE_URL, seed_namespace)

    master_rows = []
    for i, row in enumerate(src_rows):
        rec = empty_master_record()
        # 19列値を一切改変せずコピー
        for j, col in enumerate(FISHING_DATA_COLUMNS):
            rec[col] = row[j] if j < len(row) else ""

        # source 内部小文字化
        if rec["source"] == "Instagram":
            rec["source"] = "instagram"
        # Manual / Other はそのまま小文字化
        elif rec["source"] in ("Manual", "Other"):
            rec["source"] = rec["source"].lower()

        # record_id: 決定論的 UUID v5（再生成時のバイト一致用）
        if ns is not None:
            seed = f"fishing_data#{i:04d}:{rec['date']}|{rec['time']}|{rec['species']}|{rec['spot']}"
            rec["record_id"] = str(uuid.uuid5(ns, seed))
        else:
            rec["record_id"] = str(uuid.uuid4())

        # entered_at: 既存データには時刻情報がないため date + 00:00:00 JST
        if rec["date"]:
            rec["entered_at"] = f"{rec['date']}T00:00:00+09:00"
        else:
            rec["entered_at"] = ""  # 欠損は quality_check で検出される

        # B 側で補完する列 / 予約列は空のまま
        master_rows.append(rec)

    # write
    out_rows = [[r[col] for col in MASTER_COLUMNS] for r in master_rows]
    write_csv_bom_crlf(dst_path, MASTER_COLUMNS, out_rows)
    return len(out_rows)


def main():
    parser = argparse.ArgumentParser(
        description="既存 fishing_data.csv から data/master_catch.csv を初期化"
    )
    parser.add_argument(
        "--src", default="data/fishing_data.csv",
        help="入力 fishing_data.csv のパス（デフォルト: data/ 配下）"
    )
    parser.add_argument(
        "--dst", default="data/master_catch.csv",
        help="出力 master_catch.csv のパス"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="既存 master_catch.csv を上書き"
    )
    parser.add_argument(
        "--seed", default="fishing-collector-v6.0",
        help="UUID v5 シード（決定論的生成、再実行でバイト一致確保）"
    )
    args = parser.parse_args()

    if os.path.exists(args.dst) and not args.force:
        print(f"[ERROR] {args.dst} already exists. Use --force to overwrite.")
        sys.exit(1)

    n = init_master_from_fishing_data(args.src, args.dst, args.seed)
    print(f"[OK] wrote {n} records to {args.dst}")


if __name__ == "__main__":
    main()
