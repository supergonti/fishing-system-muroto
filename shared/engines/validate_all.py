"""
validate_all.py — C グループ データ整合性検査ラッパー（W4-3）

検査対象（W2-3 §7.3 / W3-1 §7.5 準拠）:
  C③ CSV : fishing_condition_db.csv
            - 全行が 21 列ちょうどか（**12,497 行目の 41 列化を検出**、修復は W5-1）
            - (日付, 地点名) の重複 0 か
            - 日付が YYYY-MM-DD 形式か
  C③ JSON: fishing_condition_db.json
            - JSON としてパース可能か
            - 末尾が ']' で閉じているか
  C④ CSV : muroto_offshore_current_all.csv
            - 全行が 11 列ちょうどか
            - (date, point) の重複 0 か
  C⑤ JSON: forecast_data.json
            - JSON としてパース可能か
            - updated / rows キーがあるか

使い方:
  python validate_all.py [--condition-csv PATH] [--condition-json PATH]
                         [--current-csv PATH]   [--forecast-json PATH]
                         [--json-output report.json]

終了コード:
  0 : すべての検査がクリア
  1 : 1 件以上の検査が NG（標準出力にレポート、--json-output でレポートファイルも出力可）
  2 : スクリプト自体のエラー（ファイル読み込み不能等）

呼び出し例（GitHub Actions の各ワークフロー完了後に配線する想定）:
  - update-conditions.yml 完了後 → --condition-csv ... --condition-json ...
  - update_data.yml        完了後 → --current-csv ...
  - update-forecast.yml    完了後 → --forecast-json ...
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ====================================================================
# スキーマ定義（W3-3 §3.4 / §3.6 / §3.7 に準拠）
# ====================================================================

CONDITION_CSV_EXPECTED_COLS = 21
CONDITION_CSV_HEADERS = [
    "日付", "地点名", "観測地点名", "県", "緯度", "経度",
    "気温_平均", "気温_最高", "気温_最低",
    "風速_最大", "風向", "降水量",
    "天気コード", "天気", "水温",
    "最大波高", "波向", "波周期",
    "潮汐", "月齢", "月相",
]

CURRENT_CSV_EXPECTED_COLS = 11
CURRENT_CSV_HEADERS = [
    "date", "point", "lat", "lon",
    "u_ms", "v_ms", "speed_ms", "speed_kn", "direction",
    "temp_c", "salinity",
]

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 境界整合チェック用（§7.1〜§7.2）
CONDITION_STATIONS = {"室戸", "高知", "足摺", "宇和島", "松山", "来島", "高松", "阿南"}
CURRENT_POINTS     = {"北西", "西", "室戸沖", "東", "北東"}


# ====================================================================
# レポート構造
# ====================================================================

@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str = ""
    details: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "name": self.name,
            "ok": self.ok,
            "message": self.message,
            "details": self.details[:50],  # 長くなりすぎないよう上位50件に制限
            "total_issues": len(self.details),
        }


@dataclass
class Report:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, r: CheckResult):
        self.results.append(r)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def print_text(self):
        print("=" * 60)
        print(" validate_all.py レポート")
        print("=" * 60)
        for r in self.results:
            mark = "✓" if r.ok else "✗"
            print(f"{mark} [{r.name}] {r.message}")
            for d in r.details[:10]:
                print(f"    - {d}")
            if len(r.details) > 10:
                print(f"    ... 他 {len(r.details) - 10} 件")
        print("-" * 60)
        print(f" 総合判定: {'OK' if self.ok else 'NG'}")
        print("=" * 60)

    def to_dict(self):
        return {
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
        }


# ====================================================================
# 個別チェック関数
# ====================================================================

def check_condition_csv(path: Path) -> CheckResult:
    """C③ fishing_condition_db.csv の整合性検査。"""
    name = "C③ fishing_condition_db.csv"
    if not path.exists():
        return CheckResult(name, False, f"ファイルが見つかりません: {path}")

    issues = []
    seen_keys: set[tuple[str, str]] = set()
    row_count = 0
    wrong_col_rows = []  # (行番号, 列数) のリスト
    bad_date_rows = []

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return CheckResult(name, False, "空ファイルです")

            # ヘッダー検査
            if len(headers) != CONDITION_CSV_EXPECTED_COLS:
                issues.append(
                    f"ヘッダー列数 {len(headers)} (期待 {CONDITION_CSV_EXPECTED_COLS})"
                )
            if headers != CONDITION_CSV_HEADERS:
                issues.append(f"ヘッダー不一致: {headers[:5]}... (期待 {CONDITION_CSV_HEADERS[:5]}...)")

            for lineno, row in enumerate(reader, start=2):
                row_count += 1
                ncol = len(row)
                if ncol != CONDITION_CSV_EXPECTED_COLS:
                    wrong_col_rows.append((lineno, ncol))
                    continue  # 列数不正なら key 抽出しない
                date_str = row[0]
                station  = row[1]
                if not DATE_PATTERN.match(date_str):
                    bad_date_rows.append((lineno, date_str))
                key = (date_str, station)
                if key in seen_keys:
                    issues.append(f"重複キー (日付={date_str}, 地点名={station}) @行{lineno}")
                seen_keys.add(key)

    except Exception as e:
        return CheckResult(name, False, f"読み込み中にエラー: {e}")

    if wrong_col_rows:
        issues.append(
            f"列数不一致 {len(wrong_col_rows)} 行（最初: 行{wrong_col_rows[0][0]} {wrong_col_rows[0][1]}列）"
        )
        # 12,497 行目に特化したメッセージ（W2-3 の既知バグ）
        for (ln, nc) in wrong_col_rows[:5]:
            issues.append(f"    row={ln} cols={nc}")
    if bad_date_rows:
        issues.append(f"不正な日付形式 {len(bad_date_rows)} 行（例: 行{bad_date_rows[0][0]} '{bad_date_rows[0][1]}'）")

    ok = len(issues) == 0
    msg = (
        f"{row_count} 行、列数 OK、重複 0、日付 OK"
        if ok
        else f"{row_count} 行中 {len(issues)} 件の問題"
    )
    return CheckResult(name, ok, msg, issues)


def check_condition_json(path: Path) -> CheckResult:
    """C③ fishing_condition_db.json の整合性検査。"""
    name = "C③ fishing_condition_db.json"
    if not path.exists():
        return CheckResult(name, False, f"ファイルが見つかりません: {path}")

    issues = []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        # 末尾チェック（CRLF / LF / 改行なし、すべて許容するが '[' と ']' で包まれているか）
        stripped = raw.rstrip(b"\r\n")
        if not stripped.startswith(b"["):
            issues.append("先頭が '[' でない")
        if not stripped.endswith(b"]"):
            issues.append("末尾が ']' でない（ファイルが途中で切れている可能性）")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, list):
            issues.append(f"トップレベルが配列ではない (type={type(data).__name__})")
        else:
            record_count = len(data)
    except json.JSONDecodeError as e:
        issues.append(f"JSON パースエラー: {e}")
        record_count = 0
    except Exception as e:
        return CheckResult(name, False, f"読み込み中にエラー: {e}")

    ok = len(issues) == 0
    msg = (
        f"JSON パース OK ({record_count} レコード)"
        if ok
        else f"{len(issues)} 件の問題"
    )
    return CheckResult(name, ok, msg, issues)


def check_current_csv(path: Path) -> CheckResult:
    """C④ muroto_offshore_current_all.csv の整合性検査。"""
    name = "C④ muroto_offshore_current_all.csv"
    if not path.exists():
        return CheckResult(name, False, f"ファイルが見つかりません: {path}")

    issues = []
    seen_keys: set[tuple[str, str]] = set()
    row_count = 0
    wrong_col_rows = []
    bad_date_rows = []
    unexpected_points: set[str] = set()

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return CheckResult(name, False, "空ファイルです")

            if len(headers) != CURRENT_CSV_EXPECTED_COLS:
                issues.append(
                    f"ヘッダー列数 {len(headers)} (期待 {CURRENT_CSV_EXPECTED_COLS})"
                )
            if headers != CURRENT_CSV_HEADERS:
                issues.append(f"ヘッダー不一致: {headers[:5]}... (期待 {CURRENT_CSV_HEADERS[:5]}...)")

            for lineno, row in enumerate(reader, start=2):
                row_count += 1
                ncol = len(row)
                if ncol != CURRENT_CSV_EXPECTED_COLS:
                    wrong_col_rows.append((lineno, ncol))
                    continue
                date_str = row[0]
                point    = row[1]
                if not DATE_PATTERN.match(date_str):
                    bad_date_rows.append((lineno, date_str))
                if point not in CURRENT_POINTS:
                    unexpected_points.add(point)
                key = (date_str, point)
                if key in seen_keys:
                    issues.append(f"重複キー (date={date_str}, point={point}) @行{lineno}")
                seen_keys.add(key)

    except Exception as e:
        return CheckResult(name, False, f"読み込み中にエラー: {e}")

    if wrong_col_rows:
        issues.append(
            f"列数不一致 {len(wrong_col_rows)} 行（最初: 行{wrong_col_rows[0][0]} {wrong_col_rows[0][1]}列）"
        )
    if bad_date_rows:
        issues.append(f"不正な日付 {len(bad_date_rows)} 行")
    if unexpected_points:
        issues.append(f"未知の point 値: {sorted(unexpected_points)}")

    ok = len(issues) == 0
    msg = (
        f"{row_count} 行、列数 OK、重複 0、point 値域 OK"
        if ok
        else f"{row_count} 行中 {len(issues)} 件の問題"
    )
    return CheckResult(name, ok, msg, issues)


def check_forecast_json(path: Path) -> CheckResult:
    """C⑤ forecast_data.json（互換層）の整合性検査。"""
    name = "C⑤ forecast_data.json"
    if not path.exists():
        return CheckResult(name, False, f"ファイルが見つかりません: {path}")

    issues = []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        # BOM 検査（なしが期待、あれば警告）
        if raw.startswith(b"\xef\xbb\xbf"):
            issues.append("BOM が付いています（期待: なし）")

        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            issues.append(f"トップレベルが dict ではない (type={type(data).__name__})")
        else:
            if "updated" not in data:
                issues.append("'updated' キーがありません")
            if "rows" not in data:
                issues.append("'rows' キーがありません")
            elif not isinstance(data["rows"], list):
                issues.append(f"'rows' が配列ではない (type={type(data['rows']).__name__})")
            else:
                rows = data["rows"]
                for i, r in enumerate(rows[:1]):  # 先頭行で主要キーの存在確認
                    for k in ("t", "wave", "wind", "dir"):
                        if k not in r:
                            issues.append(f"rows[0] にキー '{k}' がありません")

    except json.JSONDecodeError as e:
        issues.append(f"JSON パースエラー: {e}")
    except Exception as e:
        return CheckResult(name, False, f"読み込み中にエラー: {e}")

    ok = len(issues) == 0
    row_count = len(data.get("rows", [])) if ok and isinstance(data, dict) else 0
    msg = (
        f"JSON パース OK (rows={row_count})"
        if ok
        else f"{len(issues)} 件の問題"
    )
    return CheckResult(name, ok, msg, issues)


# ====================================================================
# エントリポイント
# ====================================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="C グループ データ整合性検査ラッパー (W4-3)"
    )
    parser.add_argument("--condition-csv",  type=Path, help="fishing_condition_db.csv のパス")
    parser.add_argument("--condition-json", type=Path, help="fishing_condition_db.json のパス")
    parser.add_argument("--current-csv",    type=Path, help="muroto_offshore_current_all.csv のパス")
    parser.add_argument("--forecast-json",  type=Path, help="forecast_data.json のパス")
    parser.add_argument("--json-output",    type=Path, help="レポートを JSON として出力するパス（任意）")

    args = parser.parse_args(argv)

    # どれも指定が無ければ全チェックを現行既定パスで実行する運用を想定していないため
    # 何も指定が無ければヘルプを出して終了
    if not any([args.condition_csv, args.condition_json, args.current_csv, args.forecast_json]):
        parser.print_help()
        return 2

    report = Report()

    if args.condition_csv:
        report.add(check_condition_csv(args.condition_csv))
    if args.condition_json:
        report.add(check_condition_json(args.condition_json))
    if args.current_csv:
        report.add(check_current_csv(args.current_csv))
    if args.forecast_json:
        report.add(check_forecast_json(args.forecast_json))

    report.print_text()

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
