"""
engines/normalize_instagram.py — インスタOCR/AI変換JSON → 26列スキーマ

設計準拠: 設計_W2-1_Aグループ_20260417.md §3.2

責務:
  KAI インスタ変換プロセスが生成する JSON を Aマスター 26列スキーマに正規化。
  source は `instagram` で固定（内部小文字体系）。

注意:
  既存マスターの 858 行マイグレーションでは本関数を直接呼び出さず、
  scripts/init_master.py が fishing_data.csv の 19 列値を保持しつつ
  record_id / source / entered_at / source_detail / prompt_version を付与する。

  本関数は **新規取り込み** および将来の再取り込みフローで使用する。
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


def normalize_instagram(input_json: dict, prompt_version: str = "pre-v1") -> dict:
    """
    インスタ変換 JSON を 26列スキーマ dict に正規化。

    Args:
        input_json: KAI 変換結果の dict（任意キーを含む）
        prompt_version: 変換に使用したプロンプトの版（デフォルト 'pre-v1'）

    Returns:
        Aマスター 26 列の dict（source='instagram' 固定）
    """
    rec = empty_master_record()
    extra_memo = []

    rec["species"] = _norm_str(input_json.get("species"))
    rec["bait"] = _norm_str(input_json.get("bait"))
    rec["method"] = _norm_str(input_json.get("method"))
    rec["spot"] = _norm_str(input_json.get("spot"))

    rec["date"] = _norm_date(input_json.get("date"))
    rec["time"] = _norm_time(input_json.get("time"))

    rec["size_cm"] = _norm_number_str(input_json.get("size_cm"))
    rec["weight_kg"] = _norm_number_str(input_json.get("weight_kg"))
    rec["count"] = _norm_number_str(input_json.get("count"))
    rec["spot_lat"] = _norm_number_str(input_json.get("spot_lat"))
    rec["spot_lng"] = _norm_number_str(input_json.get("spot_lng"))
    rec["water_temp"] = _norm_number_str(input_json.get("water_temp"))

    tide_raw = _norm_str(input_json.get("tide"))
    rec["tide"] = _restrict_to_set(tide_raw, TIDE_VALUES, extra_memo)
    weather_raw = _norm_str(input_json.get("weather"))
    rec["weather"] = _restrict_to_set(weather_raw, WEATHER_VALUES, extra_memo)

    rec["temp"] = ""
    rec["wind"] = ""

    rec["nearest_station"] = _norm_str(input_json.get("nearest_station"))

    base_memo = _norm_str(input_json.get("memo"))
    if extra_memo:
        suffix = " / ".join(extra_memo)
        rec["memo"] = (base_memo + " / " + suffix) if base_memo else suffix
    else:
        rec["memo"] = base_memo

    # メタ列：source は instagram 固定（W2-1 §2.2）
    rec["source"] = "instagram"
    rec["record_id"] = str(uuid.uuid4())
    rec["entered_at"] = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    # source_detail はインスタ投稿URL or 画像ファイル名
    rec["source_detail"] = _norm_str(
        input_json.get("source_detail") or input_json.get("post_url")
        or input_json.get("image_file")
    )
    rec["prompt_version"] = prompt_version
    # confidence は AI 側が返す場合のみ
    conf = input_json.get("confidence")
    rec["confidence"] = _norm_number_str(conf) if conf is not None else ""

    return rec
