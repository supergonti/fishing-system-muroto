"""
engines/normalize_import_csv.py — CSV取込 → 26列スキーマ

設計準拠: 設計_W2-1_Aグループ_20260417.md §3.4

責務:
  V5.5 以前の古い CSV や他ユーザから受領した CSV の 1行 dict を
  Aマスター 26 列に正規化。マッピング表は YAML で別管理（呼び出し側が
  事前に dict にして渡す）。
"""

import uuid
from datetime import datetime, timezone, timedelta

from ._schema import (
    empty_master_record, TIDE_VALUES, WEATHER_VALUES,
)
from .normalize_manual import (
    _norm_str, _norm_date, _norm_time, _norm_number_str, _restrict_to_set,
)

JST = timezone(timedelta(hours=9))


def normalize_import_csv(
    input_row: dict, mapping: dict, source_label: str = "import:csv_v5.5"
) -> dict:
    """
    CSV 1行を 26列スキーマ dict に正規化。

    Args:
        input_row: 元 CSV 1行（dict, 列名→値）
        mapping: 元列名 → マスター列名 のマッピング辞書
                 例: {"釣行日": "date", "魚種": "species", ...}
        source_label: source 列に書く識別子（デフォルト 'import:csv_v5.5'）

    Returns:
        Aマスター 26 列の dict
    """
    # mapping を逆引き：マスター列名 → 入力列名
    rec = empty_master_record()
    extra_memo = []

    def _get(master_col: str):
        # マスター列名から、対応する入力列名を探す
        for src, dst in mapping.items():
            if dst == master_col:
                return input_row.get(src)
        # マッピングなし
        return None

    rec["species"] = _norm_str(_get("species"))
    rec["bait"] = _norm_str(_get("bait"))
    rec["method"] = _norm_str(_get("method"))
    rec["spot"] = _norm_str(_get("spot"))
    rec["date"] = _norm_date(_get("date"))
    rec["time"] = _norm_time(_get("time"))
    rec["size_cm"] = _norm_number_str(_get("size_cm"))
    rec["weight_kg"] = _norm_number_str(_get("weight_kg"))
    rec["count"] = _norm_number_str(_get("count"))
    rec["spot_lat"] = _norm_number_str(_get("spot_lat"))
    rec["spot_lng"] = _norm_number_str(_get("spot_lng"))
    rec["water_temp"] = _norm_number_str(_get("water_temp"))

    tide_raw = _norm_str(_get("tide"))
    rec["tide"] = _restrict_to_set(tide_raw, TIDE_VALUES, extra_memo)
    weather_raw = _norm_str(_get("weather"))
    rec["weather"] = _restrict_to_set(weather_raw, WEATHER_VALUES, extra_memo)

    rec["temp"] = ""
    rec["wind"] = ""

    rec["nearest_station"] = _norm_str(_get("nearest_station"))

    base_memo = _norm_str(_get("memo"))
    if extra_memo:
        suffix = " / ".join(extra_memo)
        rec["memo"] = (base_memo + " / " + suffix) if base_memo else suffix
    else:
        rec["memo"] = base_memo

    rec["source"] = source_label
    rec["record_id"] = str(uuid.uuid4())
    rec["entered_at"] = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    rec["source_detail"] = _norm_str(_get("source_detail"))
    rec["prompt_version"] = ""
    rec["confidence"] = ""

    return rec
