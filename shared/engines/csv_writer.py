"""
engines/csv_writer.py — BOM + CRLF + QUOTE_MINIMAL の共通CSVヘルパー

設計準拠: 設計_W3-3_出力変換仕様_20260418.md §4.1

既存アプリ互換の CSV (fishing_data.csv, fishing_muroto_v1.csv, fishing_integrated.csv,
fishing_condition_db.csv, muroto_offshore_current_all.csv) を出力する際の標準インターフェース。

採用理由:
  csv.writer(open(path, 'w', newline='')) は OS 依存の改行変換があり、
  open(path, 'wb') でバイナリモードでバイト列を直接書くのが最も確実。
"""

import csv
import io
import os


def write_csv_bom_crlf(path: str, headers: list, rows: list) -> None:
    """
    UTF-8 BOM + CRLF で CSV を書き出す（既存アプリ互換）。

    Args:
        path: 出力先ファイルパス
        headers: 列名 list[str]
        rows: list[list[str]]（値は事前に文字列化済みであること）

    Output:
        BOM (EF BB BF) + UTF-8 テキスト + 各行末 CRLF (0D 0A)
        最終行にも CRLF を付ける（csv.writer のデフォルト動作）
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    writer.writerows(rows)
    text = buf.getvalue()

    # ディレクトリ作成（存在しない場合）
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")  # UTF-8 BOM
        f.write(text.encode("utf-8"))


def read_csv_bom_crlf(path: str) -> tuple:
    """
    BOM + CRLF の CSV を読み込み、(headers, rows) を返す。
    rows は list[list[str]] で、全値は文字列のまま保持（数値化しない）。
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = [row for row in reader]
    return headers, rows


def read_csv_bom_crlf_as_dicts(path: str) -> tuple:
    """
    BOM + CRLF の CSV を読み込み、(headers, list[dict]) を返す。
    結合処理用。全値は文字列のまま保持。
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader)
        dicts = []
        for row in reader:
            # 長さがヘッダと合わないものは切り詰め or パディング
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            elif len(row) > len(headers):
                row = row[: len(headers)]
            dicts.append(dict(zip(headers, row)))
    return headers, dicts


def format_number_str(value) -> str:
    """
    マスターから来た値を CSV 用文字列にする。
    - None / '' → ''
    - 既に str ならそのまま
    - それ以外は str() で変換（呼び出し側で事前に str 化しておくのが原則）
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    return str(value)
