"""
engines/normalize_manual.py — 手動入力（collector.html送信JSON）→ 26列スキーマ

設計準拠: 設計_W2-1_Aグループ_20260417.md §3.1

責務:
  collector.html フォーム送信ペイロード（JSON）を受け取り、
  Aマスター 26列スキーマの dict に正規化して返す。

注意:
  既存マスターの 858 行マイグレーションでは本関数は使わない。
  既存値はバイト不変保持が原則のため、scripts/init_master.py で
  fishing_data.csv の 19 列値をそのままマスターに書き込む。

  本関数は **新規入力** に対する将来の正規化ルートとして実装する。
"""

import unicodedata
import uuid
from datetime import datetime, timezone, timedelta

from ._schema import (
    empty_master_record, TIDE_VALUES, WEATHER_VALUES, SOURCE_INTERNAL_MAP,
)

JST = timezone(timedelta(hours=9))


def _norm_str(value) -> str:
    """前後空白削除 + NFKC 正規化。"""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s)


def _norm_number_str(value) -> str:
    """
    数値文字列を保持（型変換しない）。
    マスターは文字列保持が原則（W3-3 §4.4）。表示揺れ防止のため float 化しない。
    None / 空 → ''
    """
    if value is None or value == "":
        return ""
    s = str(value).strip()
    return s


def _norm_date(value) -> str:
    """YYYY-MM-DD 形式に正規化。失敗時は元文字列そのまま返す。"""
    s = _norm_str(value)
    if not s:
        return ""
    # よくあるフォーマットを試す
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def _norm_time(value) -> str:
    """HH:MM 形式に正規化。空可。"""
    s = _norm_str(value)
    if not s:
        return ""
    for fmt in ("%H:%M", "%H:%M:%S", "%H時%M分"):
        try:
            return datetime.strptime(s, fmt).strftime("%H:%M")
        except ValueError:
            pass
    return s


def _restrict_to_set(value: str, allowed: set, fallback_memo: list) -> str:
    """
    値が allowed に含まれていなければ空にし、元値を memo に退避。
    fallback_memo はミューテーションされる（呼び出し側でメモを連結する用）。
    """
    if not value:
        return ""
    if value in allowed:
        return value
    fallback_memo.append(value)
    return ""


def normalize_manual(input_json: dict) -> dict:
    """
    collector.html 送信 JSON を 26列スキーマ dict に正規化。

    Args:
        input_json: フォーム送信ペイロード（任意のキーを含む dict）

    Returns:
        Aマスター 26 列の dict（全値文字列）
    """
    rec = empty_master_record()
    extra_memo = []

    # 文字列系
    rec["species"] = _norm_str(input_json.get("species"))
    rec["bait"] = _norm_str(input_json.get("bait"))
    rec["method"] = _norm_str(input_json.get("method"))
    rec["spot"] = _norm_str(input_json.get("spot"))

    # 日付・時刻
    rec["date"] = _norm_date(input_json.get("date"))
    rec["time"] = _norm_time(input_json.get("time"))

    # 数値系（文字列保持）
    rec["size_cm"] = _norm_number_str(input_json.get("size_cm"))
    rec["weight_kg"] = _norm_number_str(input_json.get("weight_kg"))
    rec["count"] = _norm_number_str(input_json.get("count"))
    rec["spot_lat"] = _norm_number_str(input_json.get("spot_lat"))
    rec["spot_lng"] = _norm_number_str(input_json.get("spot_lng"))
    rec["water_temp"] = _norm_number_str(input_json.get("water_temp"))

    # tide / weather: 値域チェック、範囲外は memo に退避
    tide_raw = _norm_str(input_json.get("tide"))
    rec["tide"] = _restrict_to_set(tide_raw, TIDE_VALUES, extra_memo)
    weather_raw = _norm_str(input_json.get("weather"))
    rec["weather"] = _restrict_to_set(weather_raw, WEATHER_VALUES, extra_memo)

    # temp / wind: マスター上は常に空（W3-3 §3.1.3）
    rec["temp"] = ""
    rec["wind"] = ""

    # nearest_station: B側計算結果を受け取る場合のみ。原則は空 → quality_check が
    # B連携処理を起動する。collector.html が直接 nearest_station を送る現行
    # 仕様も尊重する。
    rec["nearest_station"] = _norm_str(input_json.get("nearest_station"))

    # memo: 元 memo + 値域違反退避
    base_memo = _norm_str(input_json.get("memo"))
    if extra_memo:
        suffix = " / ".join(extra_memo)
        rec["memo"] = (base_memo + " / " + suffix) if base_memo else suffix
    else:
        rec["memo"] = base_memo

    # メタ列
    rec["source"] = SOURCE_INTERNAL_MAP.get("Manual", "manual")
    rec["record_id"] = str(uuid.uuid4())
    rec["entered_at"] = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    rec["source_detail"] = _norm_str(input_json.get("source_detail"))
    rec["prompt_version"] = ""
    rec["confidence"] = ""

    return rec
