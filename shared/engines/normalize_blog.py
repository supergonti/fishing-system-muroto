"""
engines/normalize_blog.py — ブログ記事 → 26列スキーマ（フェーズ2 で実装）

設計準拠: 設計_W2-1_Aグループ_20260417.md §3.3

責務（予約）:
  ブログ記事HTML / RSSフィードから魚種・日付・場所を抽出して
  Aマスター 26 列スキーマに整形する。

現状: 受け口インターフェースのみ確保。実装はフェーズ2 送り。
"""

from typing import Any


def normalize_blog(input_data: Any, blog_name: str = ""):
    """
    将来用ブログ正規化（骨格のみ）。

    フェーズ2 でブログ自動収集を実装するときに本関数を完成させる。
    source = `blog:<blog_name>` で識別する設計（W2-1 §3.3）。
    """
    raise NotImplementedError("normalize_blog はフェーズ2 で実装する（W2-1 §3.3）")
