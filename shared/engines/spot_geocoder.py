"""
spot_geocoder.py — Nominatim 統合 + ローカルキャッシュ

役割:
  canonical_spot / 釣り場名から座標を逆引きする。
  ローカルキャッシュを必ず先に参照し、ヒットしなければ Nominatim API に問い合わせる。

設計準拠:
  - 設計_W2-2_Bグループ_20260417.md §8.1
  - Nominatim Usage Policy: 1 req/sec、カスタム User-Agent 必須

キャッシュ仕様:
  - JSON（BOMなし + LF + indent=2 + sort_keys + ensure_ascii=False）
  - スキーマ: {"version":"1.0.0","entries":{<spot_name>:{"lat":float|null,"lng":float|null,"source":str,"fetched_at":iso,"reason":str|null}}}
  - lat=null/lng=null はヒットなしのネガティブキャッシュ（毎回APIを叩かないため）

実装方針:
  - urllib.request のみ使用（外部依存なし、requests はオプション）
  - User-Agent: "fishing-collector-v6/1.0 (+https://github.com/supergonti/fishing-collector)"
  - タイムアウト 10 秒、失敗時は GeocodeResult(success=False) を返す
  - ネットワーク不在環境でもキャッシュから動作できる（geocode_cache_only=True 指定可）
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# Nominatim の利用規約準拠
NOMINATIM_USER_AGENT = "fishing-collector-v6/1.0 (+https://github.com/supergonti/fishing-collector)"
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
NOMINATIM_RATE_LIMIT_SEC = 1.0
NOMINATIM_TIMEOUT_SEC = 10.0

# JST タイムゾーン
JST = timezone(timedelta(hours=9))


@dataclass
class GeocodeResult:
    """逆引き結果。success=False 時は lat/lng が None。"""

    success: bool
    lat: Optional[float] = None
    lng: Optional[float] = None
    source: str = ""  # "cache" | "nominatim" | "manual"
    reason: Optional[str] = None  # 失敗時のログ用


class SpotGeocoder:
    """Nominatim でのジオコーディング + ローカル JSON キャッシュ。"""

    def __init__(
        self,
        cache_path: str | Path,
        *,
        user_agent: str = NOMINATIM_USER_AGENT,
        rate_limit_sec: float = NOMINATIM_RATE_LIMIT_SEC,
        timeout_sec: float = NOMINATIM_TIMEOUT_SEC,
        cache_only: bool = False,
    ) -> None:
        self._cache_path = Path(cache_path)
        self._user_agent = user_agent
        self._rate_limit_sec = rate_limit_sec
        self._timeout_sec = timeout_sec
        self._cache_only = cache_only

        self._last_request_monotonic: float = 0.0
        self._cache: dict = self._load_cache()

        # 統計（外部から参照可能）
        self.cache_hits = 0
        self.cache_misses = 0
        self.api_calls = 0
        self.api_failures = 0

    # ------------------------------------------------------------
    # キャッシュI/O
    # ------------------------------------------------------------
    def _load_cache(self) -> dict:
        if not self._cache_path.exists():
            return {
                "version": "1.0.0",
                "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
                "entries": {},
            }
        with self._cache_path.open(encoding="utf-8") as f:
            data = json.load(f)
        if "entries" not in data:
            data["entries"] = {}
        if "version" not in data:
            data["version"] = "1.0.0"
        return data

    def save_cache(self) -> None:
        """キャッシュを永続化する（呼び出し側で明示的に呼ぶ）。"""
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache["updated_at"] = datetime.now(JST).isoformat(timespec="seconds")
        with self._cache_path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(
                self._cache,
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            f.write("\n")

    # ------------------------------------------------------------
    # メインAPI
    # ------------------------------------------------------------
    def geocode(self, spot_name: str) -> GeocodeResult:
        """
        spot_name の座標を返す。
        1) キャッシュ確認 → ヒットなら即返す（ネガティブキャッシュも含む）
        2) Nominatim API 呼び出し（1req/秒スロットリング）
        3) 結果をキャッシュに保存（成功/失敗とも）
        """
        if not spot_name:
            return GeocodeResult(success=False, reason="empty_spot_name")

        # 1. キャッシュ確認
        entry = self._cache["entries"].get(spot_name)
        if entry is not None:
            self.cache_hits += 1
            if entry.get("lat") is not None and entry.get("lng") is not None:
                return GeocodeResult(
                    success=True,
                    lat=entry["lat"],
                    lng=entry["lng"],
                    source=entry.get("source", "cache"),
                )
            return GeocodeResult(
                success=False,
                source="cache",
                reason=entry.get("reason", "negative_cache"),
            )

        self.cache_misses += 1

        # キャッシュのみモードではここで諦める
        if self._cache_only:
            return GeocodeResult(success=False, reason="cache_only_miss")

        # 2. Nominatim 呼び出し
        result = self._call_nominatim(spot_name)

        # 3. キャッシュ保存（成否どちらも）
        self._cache["entries"][spot_name] = {
            "lat": result.lat,
            "lng": result.lng,
            "source": result.source,
            "fetched_at": datetime.now(JST).isoformat(timespec="seconds"),
            "reason": result.reason,
        }
        return result

    # ------------------------------------------------------------
    # Nominatim 呼び出し本体
    # ------------------------------------------------------------
    def _call_nominatim(self, spot_name: str) -> GeocodeResult:
        # レート制御
        elapsed = time.monotonic() - self._last_request_monotonic
        if elapsed < self._rate_limit_sec:
            time.sleep(self._rate_limit_sec - elapsed)

        params = {
            "q": spot_name,
            "format": "json",
            "limit": "1",
            "accept-language": "ja",
        }
        url = NOMINATIM_ENDPOINT + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})

        self.api_calls += 1
        self._last_request_monotonic = time.monotonic()

        try:
            with urllib.request.urlopen(req, timeout=self._timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # ネットワーク/パース含む
            self.api_failures += 1
            return GeocodeResult(
                success=False,
                source="nominatim",
                reason=f"api_error:{type(e).__name__}",
            )

        if not payload:
            return GeocodeResult(
                success=False,
                source="nominatim",
                reason="no_hit",
            )

        top = payload[0]
        try:
            lat = float(top["lat"])
            lng = float(top["lon"])
        except (KeyError, ValueError, TypeError):
            return GeocodeResult(
                success=False,
                source="nominatim",
                reason="malformed_response",
            )

        return GeocodeResult(
            success=True,
            lat=lat,
            lng=lng,
            source="nominatim",
        )

    # ------------------------------------------------------------
    # 統計
    # ------------------------------------------------------------
    def stats(self) -> dict:
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "api_calls": self.api_calls,
            "api_failures": self.api_failures,
            "cache_size": len(self._cache.get("entries", {})),
        }


# ============================================================
# CLI（動作確認用）
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SpotGeocoder 単発テスト")
    parser.add_argument("--cache", required=True, help="geocoder_cache.json のパス")
    parser.add_argument("--spot", required=True)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()

    gc = SpotGeocoder(args.cache, cache_only=args.cache_only)
    r = gc.geocode(args.spot)
    print(r)
    gc.save_cache()
    print("stats:", gc.stats())
