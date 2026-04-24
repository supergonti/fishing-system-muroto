"""
engines/spot_canonical_editor.py — spot_canonical_rules.json の冪等 append

役割:
  レビュー UI で確定した (canonical, station) ペアを alias として追記する。
  重複は静かにスキップ（冪等）、衝突（同じ from に異なる to が既存）は
  ConflictError で明示し、呼び出し側に commit ブロックを促す。

Note (W7-3, 2026-04-20):
  本モジュールは現時点で W7-3 の主実装フロー（collector.html ブラウザ完結、
  Git Data API 同一 commit push）からは呼ばれない。unit test と将来の
  CLI/バッチ追記の入口として保持される。冪等 append と衝突検出のロジックは
  collector.html の JS 実装と論理的に等価であること（parity）が前提。
  参照: 司令塔5 決裁書 Q2。

設計準拠:
  - 指示書_W7-3_collector_html_レビューUI_20260420.md §4-1
  - 計画書_司令塔5_釣り場分類人機協調改革_20260420.md §3-3（辞書追記の冪等ルール）,
    §3-4（学習の非対称性原則）
  - W7-3_設計案決裁_司令塔5_20260420.md Q2

辞書の既存フォーマット（W2-2 時点）を厳守:
  - 文字コード: UTF-8、BOM なし
  - 改行: LF（\n）
  - インデント: 2 スペース
  - ensure_ascii=False（日本語をそのまま保持）
  - 末尾改行あり
  - 追記時 `version` を patch level で bump（1.0.0 → 1.0.1）
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable


# ============================================================
# 例外
# ============================================================
class ConflictError(Exception):
    """辞書衝突：同じ from キーに異なる to が既存。

    呼び出し側はこれを検知して commit/push を停止し、人が
    spot_canonical_rules.json を手で解決することを期待する。
    """

    pass


# ============================================================
# ISO8601 ヘルパ（JST、秒精度）
# ============================================================
_JST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    """JST・秒精度の ISO8601 文字列を返す（例: 2026-04-20T23:59:00+09:00）."""
    return datetime.now(_JST).isoformat(timespec="seconds")


# ============================================================
# バージョン bump
# ============================================================
def _bump_patch(version: str) -> str:
    """
    semver の patch を 1 上げる。パースできない場合はそのまま返す。

    例: "1.0.0" -> "1.0.1", "1.2.3" -> "1.2.4"
    """
    parts = version.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        parts[2] = str(int(parts[2]) + 1)
        return ".".join(parts)
    return version


# ============================================================
# 保存ヘルパ（既存フォーマット厳守）
# ============================================================
def _save_rules(rules_path: Path, doc: dict) -> None:
    """
    spot_canonical_rules.json を既存フォーマットで保存する。

    既存フォーマット（2026-04-20 時点の実ファイルを目視確認）:
      - UTF-8 / BOM なし
      - LF 改行
      - indent=2
      - ensure_ascii=False
      - 末尾改行あり
    """
    # newline="\n" で json.dump 内の改行が LF 固定、末尾に \n 1個追加。
    with rules_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")


# ============================================================
# 単一追記
# ============================================================
def add_alias(
    rules_path: str | Path,
    from_key: str,
    to_value: str,
    reason: str = "user_review",
    added_by: str = "user_review",
) -> dict:
    """
    spot_canonical_rules.json に (from_key → to_value) alias を追記する（冪等）。

    挙動:
      - from_key == to_value → 自己マッピングは alias として意味がないため skip
      - 既存 rule で from == from_key かつ to == to_value → already_exists として skip
      - 既存 rule で from == from_key だが to が異なる → ConflictError 送出
      - 上記以外 → 新規 append、updated_at と version を更新

    Args:
        rules_path: spot_canonical_rules.json へのパス
        from_key: 4段正規化後の canonical（親計画 §3-3 P2）
        to_value: レビューUI で確定した station 名
        reason: 追記理由の自由記述（デフォルト "user_review"）
        added_by: 追記元（デフォルト "user_review"）

    Returns:
        dict: {"status": "added"|"skipped", "from": ..., "to": ..., [reason]}

    Raises:
        ConflictError: 同じ from に異なる to が既存。
    """
    if from_key == to_value:
        return {
            "status": "skipped",
            "reason": "self-mapping",
            "from": from_key,
            "to": to_value,
        }

    rules_path = Path(rules_path)
    with rules_path.open(encoding="utf-8") as f:
        doc = json.load(f)

    rules = doc.setdefault("rules", [])

    # 既存 from を検索
    for existing in rules:
        if existing.get("from") == from_key:
            if existing.get("to") == to_value:
                return {
                    "status": "skipped",
                    "reason": "already_exists",
                    "from": from_key,
                    "to": to_value,
                }
            raise ConflictError(
                f"from={from_key!r} は既存 to={existing.get('to')!r} と衝突。"
                f"新規 to={to_value!r} は追加されません。"
                f" spot_canonical_rules.json を手で確認してください。"
            )

    # 新規 append
    rules.append(
        {
            "from": from_key,
            "to": to_value,
            "type": "alias",
            "reason": reason,
            "added_at": _now_iso(),
            "added_by": added_by,
        }
    )

    # メタデータ更新
    doc["updated_at"] = _now_iso()
    doc["version"] = _bump_patch(doc.get("version", "1.0.0"))

    _save_rules(rules_path, doc)

    return {"status": "added", "from": from_key, "to": to_value}


# ============================================================
# 一括追記
# ============================================================
def batch_add_aliases(
    rules_path: str | Path,
    pairs: Iterable[tuple[str, str]],
    reason: str = "user_review",
    added_by: str = "user_review",
) -> list[dict]:
    """
    (from_key, to_value) ペアを一括で追記する。

    衝突時は即座に ConflictError を送出する。その前までの分は
    既にファイルに書き込まれている点に注意（ベストエフォート）。

    Args:
        rules_path: spot_canonical_rules.json へのパス
        pairs: [(from_key, to_value), ...]
        reason: 追記理由
        added_by: 追記元

    Returns:
        list[dict]: 各ペアの add_alias() 結果

    Raises:
        ConflictError: 一件でも衝突があれば送出。
    """
    results: list[dict] = []
    for from_key, to_value in pairs:
        results.append(
            add_alias(
                rules_path,
                from_key=from_key,
                to_value=to_value,
                reason=reason,
                added_by=added_by,
            )
        )
    return results


# ============================================================
# CLI（将来の bat/PowerShell からの入口として温存）
# ============================================================
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="spot_canonical_rules.json に alias を追記する（冪等・衝突検出あり）"
    )
    ap.add_argument("--rules", required=True, help="spot_canonical_rules.json のパス")
    ap.add_argument("--from", dest="from_key", required=True, help="正規化後 canonical")
    ap.add_argument("--to", dest="to_value", required=True, help="station 名")
    ap.add_argument("--reason", default="user_review", help="追記理由")
    ap.add_argument("--added-by", default="user_review", help="追記元")
    args = ap.parse_args()

    try:
        result = add_alias(
            args.rules,
            from_key=args.from_key,
            to_value=args.to_value,
            reason=args.reason,
            added_by=args.added_by,
        )
        print(json.dumps(result, ensure_ascii=False))
    except ConflictError as e:
        print(f"CONFLICT: {e}")
        raise SystemExit(2)
