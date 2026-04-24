"""
室戸沖 出船判断システム — 予報データ取得スクリプト

GitHub Actions または Gonti さんのローカルから実行され、
Open-Meteo Marine API + Forecast API から最新予報を取得して
forecast_data.json を生成する。

W5-3 改善 (2026-04-18):
  - 出力先を --output 引数で指定可能（既定は data/forecast_data.json）
  - urlopen に timeout=30 を明示
  - 取得失敗時は最大3回まで再試行（指数バックオフ 2/4/8 秒）
  - 各イベントを stderr に時刻つきでログ出力
  - logs/forecast.log にも追記（フォルダが無ければ自動作成）
  - 例外時は exit 1（CI で失敗を検知できるよう）

変更履歴:
  - wave_direction（波向き）追加
  - wind_wave_height（風波）追加
  - W5-3: CLI 化、再試行、ログ強化
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LAT, LON, DAYS = 33.2, 134.2, 5
TARGET_HOURS = [0, 6, 12, 18]
USER_AGENT = "muroto-forecast/1.1"
TIMEOUT_SEC = 30
MAX_RETRIES = 3

# プロジェクトルート（このファイルの親の親 = 統合リポ root）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "forecast_data.json"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "forecast.log"


def log(msg: str) -> None:
    """stderr と logs/forecast.log の両方に時刻つきで書き出す。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        # ログ書き込み失敗は本処理を止めない
        pass


def fetch_json(url: str) -> dict:
    """Open-Meteo から JSON を取得。最大 MAX_RETRIES 回再試行。"""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            backoff = 2 ** attempt  # 2, 4, 8
            log(f"取得失敗 (attempt {attempt}/{MAX_RETRIES}): {e!r} — {backoff}秒後に再試行")
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
    # 全試行失敗
    raise RuntimeError(f"Open-Meteo から取得できませんでした: {last_err!r}")


def build_rows(marine: dict, weather: dict) -> list[dict]:
    """marine + weather を 6時間刻みで突合し、forecast 行を構築。"""
    m_times    = marine["hourly"]["time"]
    m_wave     = marine["hourly"]["wave_height"]
    m_wavedir  = marine["hourly"]["wave_direction"]
    m_windwave = marine["hourly"].get("wind_wave_height")
    w_wind     = weather["hourly"]["wind_speed_10m"]
    w_dir      = weather["hourly"]["wind_direction_10m"]
    w_rain     = weather["hourly"]["precipitation"]
    wmap       = {t: i for i, t in enumerate(weather["hourly"]["time"])}

    rows: list[dict] = []
    for i, t in enumerate(m_times):
        if int(t[11:13]) not in TARGET_HOURS:
            continue
        wi = wmap.get(t)
        if wi is None:
            continue
        wave = m_wave[i]
        wind = w_wind[wi]
        if wave is None or wind is None:
            continue

        waveDir  = m_wavedir[i]
        windWave = m_windwave[i] if m_windwave else None
        rows.append({
            "t":        t,
            "wave":     round(float(wave), 2),
            "wind":     round(float(wind), 1),
            "dir":      int(w_dir[wi] or 0),
            "waveDir":  int(waveDir)   if waveDir  is not None else None,
            "windWave": round(float(windWave), 2) if windWave is not None else None,
            "rain":     round(float(w_rain[wi] or 0), 1),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="室戸沖 出船判断システム — Open-Meteo 予報データ取得"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"出力先パス（既定: {DEFAULT_OUTPUT}）",
    )
    args = parser.parse_args(argv)
    out_path: Path = args.output

    log(f"開始: 出力先 = {out_path}")
    try:
        log("Marine API 取得中...")
        marine = fetch_json(
            "https://marine-api.open-meteo.com/v1/marine"
            f"?latitude={LAT}&longitude={LON}"
            "&hourly=wave_height,wave_direction,wind_wave_height"
            f"&timezone=Asia/Tokyo&forecast_days={DAYS}"
        )

        log("Weather API 取得中...")
        weather = fetch_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            "&hourly=wind_speed_10m,wind_direction_10m,precipitation"
            f"&wind_speed_unit=ms&timezone=Asia/Tokyo&forecast_days={DAYS}"
        )

        rows = build_rows(marine, weather)
        if not rows:
            log("WARN: 行が0件です。出力はしますが内容を確認してください。")

        output = {
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rows": rows,
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False)

        log(f"OK: {len(rows)} 件保存完了 → {out_path}")
        return 0

    except Exception as e:  # noqa: BLE001
        log(f"FATAL: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
