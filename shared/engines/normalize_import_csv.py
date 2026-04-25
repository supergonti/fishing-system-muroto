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
    input_row: dict,
    mapping: dict,
    source_label: str = "import:csv_v5.5",
    entered_at: str | None = None,
) -> dict:
    """
    CSV 1行を 26列スキーマ dict に正規化。

    Args:
        input_row: 元 CSV 1行（dict, 列名→値）
        mapping: 元列名 → マスター列名 のマッピング辞書
                 例: {"釣行日": "date", "魚種": "species", ...}
        source_label: source 列に書く識別子（デフォルト 'import:csv_v5.5'）
        entered_at: バッチ共通のISO8601 JSTタイムスタンプ。
                    None の場合は呼び出し時刻を使う（後方互換）。
                    バッチ内で同一値を渡せば再取込時のバイト一致が保ちやすい。

    Returns:
        Aマスター 26 列の dict
    """
    rec = empty_master_record()
    extra_memo = []

    # マスター列名 → 入力列名 の逆引き辞書を1回だけ構築（O(M)）。
    # 旧実装の _get() 内ループを廃し、O(N×M) → O(N+M) に短縮。
    # 重複 dst がある場合の挙動は旧実装（最初に一致した src）と同等
    # （Python 3.7+ の dict 挿入順保持で再現性あり）。
    inv_mapping = {dst: src for src, dst in mapping.items()}

    def _get(master_col: str):
        src = inv_mapping.get(master_col)
        return input_row.get(src) if src is not None else None

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
    rec["entered_at"] = entered_at or datetime.now(JST).strftime(
        "%Y-%m-%dT%H:%M:%S+09:00"
    )
    rec["source_detail"] = _norm_str(_get("source_detail"))
    rec["prompt_version"] = ""
    rec["confidence"] = ""

    return rec
