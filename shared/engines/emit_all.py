"""
engines/emit_all.py — 3本の互換CSVを一括実行するCLIエントリポイント

設計準拠: 指示書_W4-1_Aグループ実装_20260418.md §6.8 / W3-3 §9.4

使い方:
  python3 -m engines.emit_all
  python3 -m engines.emit_all --master data/master_catch.csv --out-dir .
  python3 -m engines.emit_all --skip-muroto  # 特定の1本だけスキップ

実行時の前提:
  - data/master_catch.csv が既に存在すること（なければ python3 -m engines.init_master で作る）
  - fishing_condition_db.csv（C③）が存在すること
  - muroto_offshore_current_all.csv（C④）が存在すること

出力:
  {out_dir}/fishing_data.csv         (19列)
  {out_dir}/fishing_muroto_v1.csv    (42列)
  {out_dir}/fishing_integrated.csv   (34列)
"""

import argparse
import os
import sys

from . import emit_fishing_data, emit_fishing_muroto_v1, emit_fishing_integrated


def main():
    parser = argparse.ArgumentParser(
        description="3本の互換CSV（data/muroto_v1/integrated）を一括生成"
    )
    parser.add_argument("--master", default="data/master_catch.csv")
    parser.add_argument("--c3", default="data/fishing_condition_db.csv")
    parser.add_argument(
        "--c4",
        default="data/muroto_offshore_current_all.csv",
    )
    parser.add_argument("--out-dir", default=".",
                        help="出力ディレクトリ（デフォルト: カレント）")
    parser.add_argument("--skip-data", action="store_true")
    parser.add_argument("--skip-muroto", action="store_true")
    parser.add_argument("--skip-integrated", action="store_true")
    parser.add_argument("--sort", action="store_true",
                        help="fishing_data.csv の出力を W3-3 設計ソート順で並べ替える")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    errors = []

    def _run(name, fn):
        try:
            n = fn()
            print(f"[OK] {name}: {n} records")
        except Exception as e:  # noqa: BLE001
            errors.append((name, str(e)))
            print(f"[FAIL] {name}: {e}")

    if not args.skip_data:
        out = os.path.join(args.out_dir, "fishing_data.csv")
        _run("fishing_data.csv", lambda: emit_fishing_data.emit(
            args.master, out, sort_by_design=args.sort
        ))

    if not args.skip_muroto:
        out = os.path.join(args.out_dir, "fishing_muroto_v1.csv")
        _run("fishing_muroto_v1.csv", lambda: emit_fishing_muroto_v1.emit(
            args.master, args.c3, args.c4, out
        ))

    if not args.skip_integrated:
        out = os.path.join(args.out_dir, "fishing_integrated.csv")
        _run("fishing_integrated.csv", lambda: emit_fishing_integrated.emit(
            args.master, args.c3, out
        ))

    if errors:
        print(f"\n[ERROR] {len(errors)} emit(s) failed:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    print("\n[DONE] all emits completed")


if __name__ == "__main__":
    main()
