"""
scripts/sync_current_db.py — V5.5 push 後 v2.1 自動同期パイプラインの第1ステップ（海流側）

W6-3（2026-04-19）で新設。`master_catch.csv` に新規日付が追加されたとき、
`muroto_offshore_current_all.csv` に不足分の海流データ（5地点 × 1日）を CMEMS から
取得して追記する薄いラッパー。実体は既存 `scripts/main.py --date <date>` を順次呼ぶ。

設計準拠:
  - 指示書_W6-3_v2.1自動同期_20260419.md §3-3
  - sync_condition_db.py（W6-2）と同じ CLI パターン（--check-only 対応）
  - 既存 update_data.yml と同じ CMEMS 認証フロー（環境変数自動処理）
  - main.py 内の `skip_existing` ロジックに任せず、ラッパー側で日付差分を計算

入出力:
  --master  : data/master_catch.csv のパス
  --current : data/muroto_offshore_current_all.csv のパス（main.py が上書き追記する）
  戻り値    : 取得した日付件数を stdout、エラー時 exit 1

CLI例:
  python scripts/sync_current_db.py \
      --master  data/master_catch.csv \
      --current data/muroto_offshore_current_all.csv
  python scripts/sync_current_db.py --check-only \
      --master  data/master_catch.csv \
      --current data/muroto_offshore_current_all.csv

注意:
  - CMEMS は当日分の海流データを提供しない（前日分まで）。
    したがって today 以降の master 日付は除外する（翌日 06:30 JST の update_data.yml が補充）。
  - 重複追記対策：main.py は collect_range() で skip_existing=True がデフォルトのため
    既に存在する日付は内部スキップされる（ラッパー側でも明示的に欠損のみ要求）。
  - 1日ずつ subprocess で呼ぶ（main.py 内のチャンク処理に任せず逐次実行）。
    これにより1日失敗してもその日だけ exit 1 が立ち、Actions ログで切り分けやすい。
  - 認証情報（COPERNICUSMARINE_SERVICE_USERNAME / PASSWORD）は親プロセスから引き継ぐ
    （subprocess.run はデフォルトで env を継承する）。
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_PREFIX = "[sync_current_db]"


# ---------------------------------------------------------------------------
# ログ
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{LOG_PREFIX} [{ts}] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CSV 読み取り
# ---------------------------------------------------------------------------
def read_master_dates(path: Path) -> set[str]:
    """master_catch.csv の date 列から unique 日付を取り出す"""
    if not path.exists():
        raise FileNotFoundError(f"master not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "date" not in (reader.fieldnames or []):
            raise ValueError("master_catch.csv に date 列がない")
        return {row["date"] for row in reader if row.get("date")}


def read_current_dates(path: Path) -> set[str]:
    """muroto_offshore_current_all.csv の date 列から unique 日付を取り出す"""
    if not path.exists():
        # 初回起動時は空集合を返す（main.py が新規作成する）
        log(f"current CSV not found（初回扱い）: {path}")
        return set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "date" not in (reader.fieldnames or []):
            raise ValueError("muroto_offshore_current_all.csv に date 列がない")
        return {row["date"] for row in reader if row.get("date")}


# ---------------------------------------------------------------------------
# 日付フィルタ
# ---------------------------------------------------------------------------
def compute_missing_dates(master_dates: set[str], current_dates: set[str]) -> list[str]:
    """master のうち current に未登録、かつ <= 前日 の日付を sort して返す"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    missing = sorted(d for d in (master_dates - current_dates) if d <= yesterday)
    return missing


# ---------------------------------------------------------------------------
# main.py への薄いラッパー（1日ずつ subprocess 起動）
# ---------------------------------------------------------------------------
def fetch_one_date(target_date: str, scripts_dir: Path) -> int:
    """scripts/main.py --date <target_date> を起動。戻り値: subprocess の returncode"""
    cmd = [sys.executable, str(scripts_dir / "main.py"), "--date", target_date]
    log(f"  CMEMS 取得: {target_date} (cmd={' '.join(cmd)})")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def sync(master_path: Path, current_path: Path, check_only: bool = False) -> int:
    log(f"開始 master={master_path} current={current_path}")

    master_dates = read_master_dates(master_path)
    current_dates = read_current_dates(current_path)
    log(f"master_catch.csv: unique 日付 {len(master_dates)} 件")
    log(f"muroto_offshore_current_all.csv: unique 日付 {len(current_dates)} 件")

    missing = compute_missing_dates(master_dates, current_dates)
    log(f"欠損 {len(missing)} 件（today 以降は除外済）")
    if missing:
        head = ", ".join(missing[:5])
        tail = ", ".join(missing[-3:])
        log(f"  先頭: {head}")
        if len(missing) > 5:
            log(f"  末尾: {tail}")

    if not missing:
        log("変更なし。海流データの不足はありません")
        return 0

    if check_only:
        log(f"--check-only 指定。{len(missing)} 件の不足を検出（取得は行わない）")
        return len(missing)

    # 取得実行（1日ずつ）
    scripts_dir = Path(__file__).resolve().parent
    failed: list[str] = []
    succeeded: list[str] = []
    for d in missing:
        rc = fetch_one_date(d, scripts_dir)
        if rc == 0:
            succeeded.append(d)
        else:
            log(f"  ⚠ {d} 取得失敗 (returncode={rc})")
            failed.append(d)

    log(f"取得完了: 成功 {len(succeeded)} 件 / 失敗 {len(failed)} 件")
    if failed:
        log(f"失敗日付: {', '.join(failed)}")
        # 部分成功でも exit 1（後続 emit_all で気付ける）
        return 1 if not succeeded else 1

    log("完了")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "V5.5 push 後の v2.1 自動同期：master_catch.csv に追加された日付の海流データを "
            "CMEMS から差分取得（main.py の薄いラッパー）"
        )
    )
    p.add_argument("--master", type=Path, required=True,
                   help="data/master_catch.csv へのパス")
    p.add_argument("--current", type=Path, required=True,
                   help="data/muroto_offshore_current_all.csv へのパス")
    p.add_argument("--check-only", action="store_true",
                   help="不足日付を検出するのみ（取得は行わない）")
    args = p.parse_args(argv)

    try:
        rc = sync(args.master, args.current, check_only=args.check_only)
    except Exception as e:
        log(f"FATAL: {e!r}")
        return 1

    # check-only モードは件数を返したいが exit code は 0/1 の範囲に収める
    if args.check_only:
        # 件数自体は stdout で出したい場合は print する（CI 上でログ可視化）
        print(rc)
        return 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
