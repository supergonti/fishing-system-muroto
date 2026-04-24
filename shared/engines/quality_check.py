"""
engines/quality_check.py — 必須欠損・値域・重複検出

設計準拠: 設計_W2-1_Aグループ_20260417.md §4

責務:
  - 必須6列欠損検知（§4.1）
  - 値域チェック（§4.1）
  - 重複検出（§4.2 の優先順位4段階、フェーズ1 は 1〜3 を自動処理）
  - 失敗行を data/errors/quarantine_YYYYMMDD.csv に隔離

使い方:
    from engines.quality_check import check_record, check_batch, quarantine
    issues = check_record(rec)
    ok_records, bad_records = check_batch(records)
    if bad_records:
        quarantine(bad_records, "data/errors/")
"""

import os
from datetime import date as _date, datetime
from typing import List, Tuple

from ._schema import REQUIRED_COLUMNS, TIDE_VALUES, WEATHER_VALUES, MASTER_COLUMNS
from .csv_writer import write_csv_bom_crlf


# ---- 単体レコードの検査 -----------------------------------------------------


def _is_empty(value) -> bool:
    return value is None or value == ""


def _check_required(rec: dict) -> list:
    """必須6列の欠損検知（§4.1）。"""
    missing = []
    for col in REQUIRED_COLUMNS:
        if _is_empty(rec.get(col)):
            missing.append(col)
    if missing:
        return [f"required_missing:{','.join(missing)}"]
    return []


def _try_number(value: str):
    """文字列を数値化。失敗なら None。"""
    if _is_empty(value):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _check_ranges(rec: dict) -> list:
    """値域チェック（§4.1）。"""
    issues = []

    # date: 1900-01-01 〜 今日
    d_str = rec.get("date", "")
    if d_str:
        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
            if d < _date(1900, 1, 1) or d > _date.today():
                issues.append(f"date_out_of_range:{d_str}")
        except ValueError:
            issues.append(f"date_format:{d_str}")

    # time: HH:MM
    t_str = rec.get("time", "")
    if t_str:
        try:
            datetime.strptime(t_str, "%H:%M")
        except ValueError:
            issues.append(f"time_format:{t_str}")

    # 数値の値域
    n = _try_number(rec.get("size_cm"))
    if n is not None and (n < 0 or n > 200):
        issues.append(f"size_cm_range:{rec['size_cm']}")
    n = _try_number(rec.get("weight_kg"))
    if n is not None and (n < 0 or n > 100):
        issues.append(f"weight_kg_range:{rec['weight_kg']}")
    n = _try_number(rec.get("count"))
    if n is not None and n < 1:
        issues.append(f"count_range:{rec['count']}")

    # 座標
    lat = _try_number(rec.get("spot_lat"))
    if lat is not None and (lat < -90 or lat > 90):
        issues.append(f"spot_lat_range:{rec['spot_lat']}")
    lng = _try_number(rec.get("spot_lng"))
    if lng is not None and (lng < -180 or lng > 180):
        issues.append(f"spot_lng_range:{rec['spot_lng']}")

    # water_temp 0〜40
    wt = _try_number(rec.get("water_temp"))
    if wt is not None and (wt < 0 or wt > 40):
        issues.append(f"water_temp_range:{rec['water_temp']}")

    # tide / weather 値域（マスターは厳格化方針、既存データは除外）
    tide = rec.get("tide", "")
    if tide and tide not in TIDE_VALUES:
        issues.append(f"tide_out_of_set:{tide}")
    weather = rec.get("weather", "")
    if weather and weather not in WEATHER_VALUES:
        issues.append(f"weather_out_of_set:{weather}")

    # source 体系
    src = rec.get("source", "")
    if src and not _is_known_source(src):
        issues.append(f"source_unknown:{src}")

    return issues


def _is_known_source(src: str) -> bool:
    if src in ("instagram", "manual", "other"):
        return True
    for prefix in ("blog:", "import:", "ocr:"):
        if src.startswith(prefix):
            return True
    return False


def check_record(rec: dict) -> list:
    """1レコードの全品質チェックを実施。問題リストを返す（空なら問題なし）。"""
    issues = []
    issues.extend(_check_required(rec))
    issues.extend(_check_ranges(rec))
    return issues


# ---- 重複検出 ---------------------------------------------------------------


def detect_duplicates(records: list) -> dict:
    """
    重複検出（§4.2）。優先順位:
      1. record_id 一致 → 完全重複
      2. source_detail 一致 → ソース起因の再取り込み
      3. (date, time, species, size_cm, spot, source) 全一致 → 疑似重複
      4. (date, species, spot) 一致 かつ size_cm 差 ±2cm 以内 → 近似重複

    Returns:
        dict: {'complete': [(i,j), ...], 'source': [...], 'pseudo': [...], 'near': [...]}
    """
    result = {"complete": [], "source": [], "pseudo": [], "near": []}

    # 1. record_id
    by_rid = {}
    for i, r in enumerate(records):
        rid = r.get("record_id", "")
        if rid:
            if rid in by_rid:
                result["complete"].append((by_rid[rid], i))
            else:
                by_rid[rid] = i

    # 2. source_detail
    by_sd = {}
    for i, r in enumerate(records):
        sd = r.get("source_detail", "")
        if sd:
            if sd in by_sd:
                result["source"].append((by_sd[sd], i))
            else:
                by_sd[sd] = i

    # 3. 疑似重複
    by_key = {}
    for i, r in enumerate(records):
        key = (r.get("date", ""), r.get("time", ""), r.get("species", ""),
               r.get("size_cm", ""), r.get("spot", ""), r.get("source", ""))
        if all(key):  # 全要素非空
            if key in by_key:
                result["pseudo"].append((by_key[key], i))
            else:
                by_key[key] = i

    # 4. 近似重複
    by_dsp = {}
    for i, r in enumerate(records):
        key = (r.get("date", ""), r.get("species", ""), r.get("spot", ""))
        if all(key):
            by_dsp.setdefault(key, []).append(i)
    for key, idxs in by_dsp.items():
        if len(idxs) < 2:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                sa = _try_number(records[i].get("size_cm"))
                sb = _try_number(records[j].get("size_cm"))
                if sa is not None and sb is not None and abs(sa - sb) <= 2:
                    # 疑似重複で既に検出済みならスキップ
                    if (i, j) not in result["pseudo"]:
                        result["near"].append((i, j))

    return result


# ---- バッチ検査 -------------------------------------------------------------


def check_batch(records: list) -> Tuple[List[dict], List[dict]]:
    """
    レコード群を (ok, bad) に分割。bad は '_issues' キーに問題リストを追加。
    """
    ok, bad = [], []
    for r in records:
        issues = check_record(r)
        if issues:
            r_copy = dict(r)
            r_copy["_issues"] = "|".join(issues)
            bad.append(r_copy)
        else:
            ok.append(r)
    return ok, bad


def quarantine(bad_records: list, errors_dir: str) -> str:
    """
    失敗レコードを data/errors/quarantine_YYYYMMDD.csv に隔離。
    Returns: 書き出したファイルパス。
    """
    if not bad_records:
        return ""
    today = datetime.now().strftime("%Y%m%d")
    os.makedirs(errors_dir, exist_ok=True)
    path = os.path.join(errors_dir, f"quarantine_{today}.csv")

    # 26列 + _issues
    headers = list(MASTER_COLUMNS) + ["_issues"]
    rows = []
    for r in bad_records:
        row = [str(r.get(c, "")) for c in MASTER_COLUMNS]
        row.append(str(r.get("_issues", "")))
        rows.append(row)

    # 既存があれば追記、無ければ新規
    if os.path.exists(path):
        # 既存にレコードを追加（ヘッダは再書き出ししない）
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerows(rows)
        with open(path, "ab") as f:
            f.write(buf.getvalue().encode("utf-8"))
    else:
        write_csv_bom_crlf(path, headers, rows)

    return path
