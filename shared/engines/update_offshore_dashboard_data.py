#!/usr/bin/env python3
"""
engines/update_offshore_dashboard_data.py
==========================================

室戸沖潮流ダッシュボード用 JS データファイル生成エンジン。

旧 `fishing-system/scripts/update_offshore_dashboard_data.py` を Muroto 新構造
（areas/muroto + shared/）向けに移植したもの。海流CSV を読み、HTML ダッシュボード
が `<script>` 経由でロードできる形式の JavaScript ファイルとして書き出す。

入力（デフォルト）:
  shared/current/muroto/muroto_offshore_current_all.csv
出力（デフォルト）:
  areas/muroto/data/js/muroto_offshore_current_dashboard_data.js

入力パスは `shared/meta/areas_master.json` の `current_csv` フィールドから動的に
取得する（area_id=muroto）。CLI `--csv` / `--js` で上書き可能。

出力 JS の形式（旧版と同一）:
  // 自動生成ファイル ...
  window.MUROTO_CSV_TEXT = `<csv内容>`;

エスケープ処理（旧版と同一）:
  バックスラッシュ `\\` → `\\\\`
  バッククォート ` `` ` → `` \\` ``
  テンプレートリテラル開始 `${` → `\\${`
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path


# リポジトリルート（shared/engines/ から 2階層上）
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_AREA_ID = "muroto"
DEFAULT_AREAS_MASTER = REPO_ROOT / "shared" / "meta" / "areas_master.json"
DEFAULT_JS_PATH = (
    REPO_ROOT
    / "areas"
    / "muroto"
    / "data"
    / "js"
    / "muroto_offshore_current_dashboard_data.js"
)


def resolve_csv_path(
    areas_master_path: Path = DEFAULT_AREAS_MASTER,
    area_id: str = DEFAULT_AREA_ID,
) -> Path:
    """areas_master.json の current_csv から入力CSVパスを解決する。

    見つからない場合や読み込み失敗時は FileNotFoundError / KeyError を伝播させる。
    返すパスはリポジトリルート基準の絶対パス。
    """
    with open(areas_master_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for area in data.get("areas", []):
        if area.get("area_id") == area_id:
            rel = area.get("current_csv")
            if not rel:
                raise KeyError(
                    f"areas_master.json: area_id={area_id} に current_csv が無い"
                )
            return (REPO_ROOT / rel).resolve()
    raise KeyError(f"areas_master.json: area_id={area_id} が見つからない")


def escape_for_template_literal(csv_text: str) -> str:
    """CSV 内容を JS テンプレートリテラル `` ` ... ` `` に埋め込めるようエスケープ。

    旧版と同一の順序・対象（\\, `, ${）。
    """
    return (
        csv_text
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
    )


def build_js_content(csv_text: str) -> str:
    """JS ファイルの最終文字列を組み立てる。"""
    escaped = escape_for_template_literal(csv_text)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "// 自動生成ファイル — shared/engines/update_offshore_dashboard_data.py により作成\n"
        "// 室戸沖潮流ダッシュボード V2.0 / Muroto Offshore Current Dashboard V2.0\n"
        "// このファイルを直接編集しないでください\n"
        f"// 生成日時: {now}\n"
        f"window.MUROTO_CSV_TEXT = `{escaped}`;\n"
    )


def update(csv_path: Path, js_path: Path) -> int:
    """CSV を読み JS を書き出す。書き込んだ行数（ヘッダー除く）を返す。"""
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    with open(csv_path, "r", encoding="utf-8") as f:
        csv_text = f.read()

    row_count = max(0, len(csv_text.strip().splitlines()) - 1)

    js_content = build_js_content(csv_text)

    js_path.parent.mkdir(parents=True, exist_ok=True)
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js_content)

    print(f"[OK] wrote {row_count} rows -> {js_path}")
    return row_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "muroto_offshore_current_all.csv を "
            "muroto_offshore_current_dashboard_data.js に変換する"
        )
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="入力 CSV パス（省略時は areas_master.json の current_csv を使用）",
    )
    parser.add_argument(
        "--js",
        default=str(DEFAULT_JS_PATH),
        help="出力 JS パス（省略時は areas/muroto/data/js/...）",
    )
    parser.add_argument(
        "--areas-master",
        default=str(DEFAULT_AREAS_MASTER),
        help="areas_master.json のパス（--csv 未指定時の解決元）",
    )
    parser.add_argument(
        "--area-id",
        default=DEFAULT_AREA_ID,
        help="対象 area_id（デフォルト: muroto）",
    )
    args = parser.parse_args(argv)

    if args.csv:
        csv_path = Path(args.csv).resolve()
    else:
        try:
            csv_path = resolve_csv_path(
                Path(args.areas_master).resolve(), args.area_id
            )
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
            print(
                f"[ERROR] failed to resolve csv path from areas_master.json: {e}",
                file=sys.stderr,
            )
            return 1

    js_path = Path(args.js).resolve()
    update(csv_path, js_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
