"""
engines/ — 釣果データ新アーキテクチャ エンジン群

設計準拠: 設計_W3-3_出力変換仕様_20260418.md / 設計_W2-1_Aグループ_20260417.md

モジュール一覧:
- csv_writer.py       : BOM + CRLF + QUOTE_MINIMAL の共通CSVヘルパー
- json_writer.py      : B/C系 JSON出力の4パターン共通ヘルパー
- normalize_manual.py : 手動入力（collector.html送信JSON）→ 26列スキーマ
- normalize_instagram.py : インスタOCR/AI変換JSON → 26列スキーマ
- normalize_import_csv.py: CSV取込 → 26列スキーマ
- normalize_blog.py   : 将来用ブログ正規化（骨格のみ）
- quality_check.py    : 必須欠損・値域・重複検出
- emit_fishing_data.py       : 26列→19列 互換CSV
- emit_fishing_muroto_v1.py  : 26列×C④2点→42列 互換CSV
- emit_fishing_integrated.py : 26列×C③→34列 互換CSV
- emit_all.py         : 3本一括実行CLIエントリポイント

原則:
- 原則7: 既存アプリが読むファイルは `cmp -b` で既存行1バイト不変。
- 空値は全て空文字列。null/None/N/A を書かない。
- 数値は文字列として保持し、表示揺れを防ぐ。
"""

__version__ = "0.1.0"
