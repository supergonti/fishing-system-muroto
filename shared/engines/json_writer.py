"""
engines/json_writer.py — JSON出力の4パターン共通ヘルパー

設計準拠: 設計_W3-3_出力変換仕様_20260418.md §4.2 / §4.3

A グループではこの json_writer は直接使わないが、将来の B / C 系モジュールが
共通利用できるよう本リポジトリに配置する（W4-2 / W4-3 での共有）。

4パターン:
  1) B系 JSON (stations_master.json 等)
     BOMなし + LF + indent=2 + sort_keys
  2) C③派生 JSON (fishing_condition_db.json)
     BOMなし + CRLF + indent=2 + 挿入順 + 全値文字列
  3) C⑤互換層 JSON (forecast_data.json)
     BOMなし + 改行なし + コンパクト + デフォルト区切り (': ', ', ')
  4) C⑤発行別 JSON (forecast_archive/YYYYMMDDTHHMM.json)
     BOMなし + LF + indent=2 + 挿入順
  5) JSONL 追記 (forecast_archive.jsonl)
     1行1JSONオブジェクト、BOMなし、LF区切り
"""

import json
import os


def _ensure_dir(path: str) -> None:
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)


def write_json_bmaster(path: str, data) -> None:
    """B系 JSON: BOMなし + LF + indent=2 + sort_keys + 末尾LF"""
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
    _ensure_dir(path)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
        f.write(b"\n")


def write_json_condition_db(path: str, data) -> None:
    """
    C③派生 JSON (fishing_condition_db.json): BOMなし + CRLF + indent=2 + 挿入順

    注意: 標準 json.dump(indent=2) は LF。手動で '\n' → '\r\n' に置換する必要あり。
    """
    text = json.dumps(data, indent=2, ensure_ascii=False)  # sort_keys しない
    text = text.replace("\n", "\r\n")
    _ensure_dir(path)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
        # 末尾改行は現行仕様に合わせる（W5-1 採取時に確認）


def write_json_forecast_compact(path: str, data) -> None:
    """
    C⑤互換層 JSON (forecast_data.json): BOMなし + 改行なし + コンパクト

    デフォルト区切り (': ', ', ') を使う。separators=(':',',')で圧縮しない。
    """
    text = json.dumps(data, ensure_ascii=False)  # デフォルト separators=(', ', ': ')
    _ensure_dir(path)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
        # 末尾改行は付けない


def write_json_forecast_archive(path: str, data) -> None:
    """
    C⑤発行別 JSON (forecast_archive/YYYYMMDDTHHMM.json): BOMなし + LF + indent=2

    上書き禁止: 既存ファイルがあれば例外送出（不変アーカイブ）。
    """
    if os.path.exists(path):
        raise FileExistsError(
            f"forecast archive is immutable: {path} already exists"
        )
    text = json.dumps(data, indent=2, ensure_ascii=False)
    _ensure_dir(path)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
        f.write(b"\n")


def append_jsonl(path: str, records) -> None:
    """
    JSONL 追記 (forecast_archive.jsonl): BOMなし + 1行1JSONオブジェクト + LF区切り

    records は iterable[dict]。
    """
    _ensure_dir(path)
    with open(path, "ab") as f:
        for rec in records:
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            f.write(line.encode("utf-8"))
