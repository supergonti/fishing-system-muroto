"""
shared/engines/ingest_dropins.py — drop_inbox CSV → master_catch.csv へ統合

責務:
  `areas/<area_id>/drop_inbox/fishing_data_<boat_id>.csv` を取り込み、
  `areas/<area_id>/data/master_catch.csv` (28列) にマージする。

特徴:
  1. **ファイル名から boat_id 抽出**: `fishing_data_muroto2.csv` → boat_id="muroto2"
  2. **uuid5 による決定論的 record_id 生成**: 同じ内容を再 drop しても既存
     master 行と突合 → 重複行は追記されない（冪等化）。
  3. **boats_master.json / areas_master.json でメタ解決**: boat_id → area_id
     を検証し、整合しない drop は拒否する。
  4. **source 正規化**: Manual/Instagram は小文字化、ブログ系はそのまま保持。
  5. **処理済みファイルを _archived/ へ退避**。

CLI:
  python3 -m shared.engines.ingest_dropins <area_id>

終了コード:
  0 = 正常（新規 0 件でも正常扱い）
  1 = 検証失敗（boat_id が boats_master に未登録、area_id 不一致等）
  2 = I/O エラー
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import unicodedata
import uuid
from datetime import datetime, timezone, timedelta

from ._schema import (
    MASTER_COLUMNS,
    MASTER_COLUMNS_V1,
    FISHING_DATA_COLUMNS,
    empty_master_record,
    detect_master_schema,
    upgrade_record_v1_to_v2,
    SOURCE_INTERNAL_MAP,
)
from .csv_writer import write_csv_bom_crlf, read_csv_bom_crlf_as_dicts

JST = timezone(timedelta(hours=9))

# uuid5 名前空間（Muroto システム固有、バイト一致の再現性担保）
NAMESPACE_SEED = "fishing-system-muroto:ingest_dropins:v2.0.0"
NAMESPACE_UUID = uuid.uuid5(uuid.NAMESPACE_URL, NAMESPACE_SEED)

# ファイル名規約: fishing_data_<boat_id>.csv
FILENAME_RE = re.compile(r"^fishing_data_(?P<boat_id>[a-zA-Z0-9_]+)\.csv$")


def load_boats_master(path: str) -> dict:
    """boats_master.json を読み込み、boat_id → boat dict に索引化。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {b["boat_id"]: b for b in data.get("boats", [])}


def load_areas_master(path: str) -> dict:
    """areas_master.json を読み込み、area_id → area dict に索引化。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {a["area_id"]: a for a in data.get("areas", [])}


def normalize_source_value(raw: str) -> str:
    """source 値を内部表現に正規化。

    - "Manual" / "manual" → "manual"
    - "Instagram" / "instagram" → "instagram"
    - "Other" / "other" → "other"
    - それ以外（"室戸2ブログ" 等）はそのまま保持（ブログ系は日本語原文を温存）
    """
    if not raw:
        return ""
    if raw in SOURCE_INTERNAL_MAP:
        return SOURCE_INTERNAL_MAP[raw]
    return raw


def _norm(s: str) -> str:
    """軽量正規化: NFKC + strip（record_id 安定化目的）。"""
    if s is None:
        return ""
    return unicodedata.normalize("NFKC", str(s).strip())


def compute_record_id(boat_id: str, rec: dict) -> str:
    """行内容から決定論的な record_id を生成。

    内容ベース（行順非依存）にすることで、drop_inbox CSV に新規行を追加・並べ替え
    しても既存行の record_id は変わらず、冪等性が保たれる。
    """
    parts = [
        boat_id,
        _norm(rec.get("date")),
        _norm(rec.get("time")),
        _norm(rec.get("species")),
        _norm(rec.get("size_cm")),
        _norm(rec.get("weight_kg")),
        _norm(rec.get("count")),
        _norm(rec.get("bait")),
        _norm(rec.get("method")),
        _norm(rec.get("spot")),
        _norm(rec.get("memo")),
        _norm(rec.get("source")),
    ]
    seed = "|".join(parts)
    return str(uuid.uuid5(NAMESPACE_UUID, seed))


def compute_entered_at(rec: dict) -> str:
    """entered_at の fallback: date があれば {date}T00:00:00+09:00、なければ空。"""
    d = rec.get("date") or ""
    if d:
        return f"{d}T00:00:00+09:00"
    return ""


def read_dropin_csv(path: str) -> list:
    """drop_inbox CSV を読み、19列 dict list を返す。ヘッダは FISHING_DATA_COLUMNS 準拠。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != FISHING_DATA_COLUMNS:
            raise ValueError(
                f"unexpected header in {path}:\n  got={header}\n  expected={FISHING_DATA_COLUMNS}"
            )
        rows = []
        for row in reader:
            # 長さ調整
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            elif len(row) > len(header):
                row = row[: len(header)]
            rows.append(dict(zip(header, row)))
    return rows


def row_to_master_record(
    raw: dict, boat_id: str, area_id: str
) -> dict:
    """19列 dict → 28列 master dict（record_id/entered_at/boat_id/area_id 付与）。"""
    rec = empty_master_record()
    for col in FISHING_DATA_COLUMNS:
        rec[col] = raw.get(col, "") or ""

    rec["source"] = normalize_source_value(rec["source"])
    rec["entered_at"] = compute_entered_at(rec)
    rec["boat_id"] = boat_id
    rec["area_id"] = area_id
    rec["record_id"] = compute_record_id(boat_id, rec)
    return rec


def load_master(path: str) -> tuple:
    """既存 master_catch.csv を読み込み、28列 dict list を返す。なければ空。

    Returns:
      (records, existing_record_ids) — records は MASTER_COLUMNS 順の dict list、
      existing_record_ids は重複検知用の set。
    """
    if not os.path.exists(path):
        return [], set()

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        src_rows = [row for row in reader]

    schema = detect_master_schema(header)
    if schema == "unknown":
        raise ValueError(f"unknown master schema in {path}: {header}")

    records = []
    existing_ids = set()
    cols = MASTER_COLUMNS if schema == "2.0.0" else MASTER_COLUMNS_V1
    for row in src_rows:
        if len(row) < len(cols):
            row = row + [""] * (len(cols) - len(row))
        elif len(row) > len(cols):
            row = row[: len(cols)]
        rec = dict(zip(cols, row))
        if schema == "1.0.0":
            rec = upgrade_record_v1_to_v2(rec)
        records.append(rec)
        if rec.get("record_id"):
            existing_ids.add(rec["record_id"])
    return records, existing_ids


def write_master(path: str, records: list) -> None:
    """28列 master_catch.csv を BOM+CRLF で書き出し。"""
    rows = [[r.get(col, "") for col in MASTER_COLUMNS] for r in records]
    write_csv_bom_crlf(path, MASTER_COLUMNS, rows)


def ingest_area(
    area_id: str,
    repo_root: str,
    dry_run: bool = False,
) -> dict:
    """指定 area の drop_inbox を取り込み、master_catch.csv を更新。

    Returns:
      {"scanned": n, "added": m, "skipped_dup": k, "archived": [...], "errors": [...]}
    """
    shared_dir = os.path.join(repo_root, "shared")
    boats = load_boats_master(os.path.join(shared_dir, "meta", "boats_master.json"))
    areas = load_areas_master(os.path.join(shared_dir, "meta", "areas_master.json"))

    if area_id not in areas:
        raise ValueError(f"unknown area_id: {area_id} (not in areas_master.json)")
    area = areas[area_id]

    area_dir = os.path.join(repo_root, "areas", area_id)
    inbox_dir = os.path.join(area_dir, "drop_inbox")
    archive_dir = os.path.join(inbox_dir, "_archived")
    master_path = os.path.join(area_dir, "data", "master_catch.csv")
    os.makedirs(archive_dir, exist_ok=True)
    os.makedirs(os.path.dirname(master_path), exist_ok=True)

    # 既存 master 読み込み
    existing_records, existing_ids = load_master(master_path)

    # drop_inbox の対象ファイル列挙
    candidates = []
    for name in sorted(os.listdir(inbox_dir)):
        full = os.path.join(inbox_dir, name)
        if not os.path.isfile(full):
            continue
        if name.startswith("_"):
            continue
        m = FILENAME_RE.match(name)
        if not m:
            continue
        candidates.append((name, m.group("boat_id"), full))

    result = {
        "area_id": area_id,
        "scanned": len(candidates),
        "added": 0,
        "skipped_dup": 0,
        "archived": [],
        "errors": [],
    }

    new_records = []
    seen_in_batch = set()  # このバッチ内での重複

    for fname, boat_id, path in candidates:
        if boat_id not in boats:
            result["errors"].append(
                f"{fname}: boat_id '{boat_id}' not in boats_master.json"
            )
            continue
        boat = boats[boat_id]
        if boat["area_id"] != area_id:
            result["errors"].append(
                f"{fname}: boat '{boat_id}' belongs to area "
                f"'{boat['area_id']}', not '{area_id}'"
            )
            continue

        try:
            raw_rows = read_dropin_csv(path)
        except Exception as e:
            result["errors"].append(f"{fname}: read failed: {e}")
            continue

        file_added = 0
        file_dup = 0
        for raw in raw_rows:
            rec = row_to_master_record(raw, boat_id, area_id)
            rid = rec["record_id"]
            if rid in existing_ids or rid in seen_in_batch:
                file_dup += 1
                continue
            new_records.append(rec)
            seen_in_batch.add(rid)
            file_added += 1

        result["added"] += file_added
        result["skipped_dup"] += file_dup

        if not dry_run:
            shutil.move(path, os.path.join(archive_dir, fname))
            result["archived"].append(fname)

    if new_records and not dry_run:
        merged = existing_records + new_records
        write_master(master_path, merged)

    result["total_master_rows"] = len(existing_records) + len(new_records)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="drop_inbox CSV を master_catch.csv に取り込む"
    )
    parser.add_argument("area_id", help="対象海域 ID（例: muroto）")
    parser.add_argument(
        "--repo-root",
        default=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        help="リポジトリのルートパス（デフォルト: このスクリプトから2階層上）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="実ファイル書換をせず結果だけ表示"
    )
    args = parser.parse_args()

    try:
        result = ingest_area(args.area_id, args.repo_root, args.dry_run)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(2)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["errors"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
