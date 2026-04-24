"""
scripts/sync_condition_db.py — V5.5 push 後 V6.0 自動同期パイプラインの第1ステップ

W6-2（2026-04-19）で新設。`master_catch.csv` に新規日付が追加されたとき、
`fishing_condition_db.csv` に不足分の気象データを Open-Meteo Archive / Forecast から
取得して追記し、最後に keep-last 重複排除を行う。

設計準拠:
  - 指示書_W6-2_V6.0自動同期_20260419.md §3-2
  - 既存 scripts/update-conditions.js の Node.js 実装をPythonに移植（観測8地点・URL・列定義・集計ロジックは同一）
  - 既存 scripts/fetch_forecast.py のリトライ＋ログパターンを踏襲

入出力:
  --master   : master_catch.csv のパス
  --condition: fishing_condition_db.csv のパス（上書き）
  戻り値     : 取得した(日付×地点)件数を stdout、エラー時 exit 1

CLI例:
  python scripts/sync_condition_db.py \
      --master    data/master_catch.csv \
      --condition data/fishing_condition_db.csv
  python scripts/sync_condition_db.py --check-only

注意:
  - 観測地点8地点は四国ぐるりの V6.0系 (auto-memory: project_fishing_observation_points.md)
  - 重複排除は (日付, 地点名) で keep-last（後に現れた行を保持）。
    fix_condition_db.py §Step B と同じポリシー
  - Open-Meteo Archive endpoint は5日前まで。最近の日付は forecast endpoint で補完
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 定数（update-conditions.js と完全一致）
# ---------------------------------------------------------------------------
STATIONS = [
    {"name": "室戸",   "lat": 33.29, "lng": 134.18, "pref": "高知県"},
    {"name": "高知",   "lat": 33.56, "lng": 133.54, "pref": "高知県"},
    {"name": "足摺",   "lat": 32.72, "lng": 132.72, "pref": "高知県"},
    {"name": "宇和島", "lat": 33.22, "lng": 132.56, "pref": "愛媛県"},
    {"name": "松山",   "lat": 33.84, "lng": 132.77, "pref": "愛媛県"},
    {"name": "来島",   "lat": 34.12, "lng": 132.99, "pref": "愛媛県"},
    {"name": "高松",   "lat": 34.35, "lng": 134.05, "pref": "香川県"},
    {"name": "阿南",   "lat": 33.92, "lng": 134.66, "pref": "徳島県"},
]

CSV_HEADER = [
    "日付", "地点名", "観測地点名", "県", "緯度", "経度",
    "気温_平均", "気温_最高", "気温_最低",
    "風速_最大", "風向", "降水量",
    "天気コード", "天気",
    "水温", "最大波高", "波向", "波周期",
    "潮汐", "月齢", "月相",
]
EXPECTED_COLS = len(CSV_HEADER)  # 21

# 集計対象時刻（update-conditions.js TARGET_HOURS と一致）
TARGET_HOURS = [0, 6, 12, 18]

# Open-Meteo は5日前まで archive、それ以降は forecast を使う
ARCHIVE_LAG_DAYS = 5

USER_AGENT = "muroto-sync-condition/1.0 (W6-2 fishing-system)"
TIMEOUT_SEC = 30
MAX_RETRIES = 3
API_DELAY_SEC = 1.2  # update-conditions.js の API_DELAY と同水準

LOG_PREFIX = "[sync_condition_db]"


# ---------------------------------------------------------------------------
# ログ
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{LOG_PREFIX} [{ts}] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# HTTP fetch（指数バックオフ・リトライ）
# ---------------------------------------------------------------------------
def fetch_json(url: str) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            backoff = 2 ** attempt
            log(f"取得失敗 attempt={attempt}/{MAX_RETRIES} url={url} err={e!r} → {backoff}秒後に再試行")
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
    raise RuntimeError(f"Open-Meteo 取得失敗: {last_err!r} url={url}")


# ---------------------------------------------------------------------------
# Open-Meteo URL ビルダ（update-conditions.js と同一形式）
# ---------------------------------------------------------------------------
def weather_archive_url(lat: float, lng: float, from_date: str, to_date: str) -> str:
    return (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,precipitation,weather_code"
        "&timezone=Asia%2FTokyo"
        f"&start_date={from_date}&end_date={to_date}"
    )


def weather_forecast_url(lat: float, lng: float, from_date: str, to_date: str) -> str:
    return (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,precipitation,weather_code"
        "&timezone=Asia%2FTokyo"
        f"&start_date={from_date}&end_date={to_date}&past_days=0"
    )


def marine_url(lat: float, lng: float, from_date: str, to_date: str, params: str) -> str:
    return (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lng}&{params}"
        f"&timezone=Asia%2FTokyo&start_date={from_date}&end_date={to_date}"
    )


# ---------------------------------------------------------------------------
# 集計ヘルパ（update-conditions.js と同一）
# ---------------------------------------------------------------------------
def _avg(xs: list[float]) -> float | None:
    if not xs:
        return None
    return round(sum(xs) / len(xs) * 10) / 10


def _max(xs: list[float]) -> float | None:
    if not xs:
        return None
    return round(max(xs) * 10) / 10


def _min(xs: list[float]) -> float | None:
    if not xs:
        return None
    return round(min(xs) * 10) / 10


def _sum(xs: list[float]) -> float | None:
    if not xs:
        return None
    return round(sum(xs) * 10) / 10


def wind_dir_str(deg: float | None) -> str:
    if deg is None:
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]


WEATHER_DESC_MAP = {
    0: "快晴", 1: "晴れ", 2: "一部曇り", 3: "曇り",
    45: "霧", 48: "着氷霧",
    51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨",
    56: "着氷霧雨(弱)", 57: "着氷霧雨(強)",
    61: "弱い雨", 63: "雨", 65: "強い雨",
    66: "着氷雨(弱)", 67: "着氷雨(強)",
    71: "弱い雪", 73: "雪", 75: "強い雪", 77: "霧雪",
    80: "弱いにわか雨", 81: "にわか雨", 82: "激しいにわか雨",
    85: "弱いにわか雪", 86: "強いにわか雪",
    95: "雷雨", 96: "雷雨(雹弱)", 99: "雷雨(雹強)",
}


def weather_desc(code: int | None) -> str:
    if code is None:
        return ""
    return WEATHER_DESC_MAP.get(code, f"code{code}")


def _group_hourly(time_arr, data_keys, data_arrays):
    """update-conditions.js groupHourlyByDate のPython版"""
    by_date: dict[str, list[dict]] = {}
    for i, t in enumerate(time_arr):
        if not t or len(t) < 13:
            continue
        date_str = t[:10]
        try:
            hour = int(t[11:13])
        except ValueError:
            continue
        if hour not in TARGET_HOURS:
            continue
        if date_str not in by_date:
            by_date[date_str] = []
        entry = {"hour": hour}
        for key in data_keys:
            entry[key] = data_arrays[key][i] if i < len(data_arrays[key]) else None
        by_date[date_str].append(entry)
    return by_date


def parse_weather_json(payload: dict) -> dict[str, dict]:
    h = payload.get("hourly") or {}
    if not h.get("time"):
        return {}
    keys = ["temperature_2m", "wind_speed_10m",
            "wind_direction_10m", "precipitation", "weather_code"]
    arrays = {k: (h.get(k) or []) for k in keys}
    by_date = _group_hourly(h["time"], keys, arrays)
    result: dict[str, dict] = {}
    for d, entries in by_date.items():
        temps = [e["temperature_2m"] for e in entries if e["temperature_2m"] is not None]
        precips = [e["precipitation"] for e in entries if e["precipitation"] is not None]
        codes = [int(e["weather_code"]) for e in entries if e["weather_code"] is not None]
        max_wind = None
        max_wind_dir = None
        for e in entries:
            ws = e["wind_speed_10m"]
            if ws is None:
                continue
            if max_wind is None or ws > max_wind:
                max_wind = ws
                max_wind_dir = e["wind_direction_10m"]
        result[d] = {
            "気温_平均": _avg(temps),
            "気温_最高": _max(temps),
            "気温_最低": _min(temps),
            "風速_最大": (round(max_wind * 10) / 10) if max_wind is not None else None,
            "風向":     wind_dir_str(max_wind_dir) if max_wind_dir is not None else "",
            "降水量":    _sum(precips),
            "天気コード": (max(codes) if codes else None),
            "天気":      (weather_desc(max(codes)) if codes else ""),
        }
    return result


def parse_marine_json(payload: dict) -> dict[str, dict]:
    h = payload.get("hourly") or {}
    if not h.get("time"):
        return {}
    keys = ["wave_height", "wave_direction", "wave_period"]
    arrays = {k: (h.get(k) or []) for k in keys}
    by_date = _group_hourly(h["time"], keys, arrays)
    result: dict[str, dict] = {}
    for d, entries in by_date.items():
        heights = [e["wave_height"] for e in entries if e["wave_height"] is not None]
        dirs = [e["wave_direction"] for e in entries if e["wave_direction"] is not None]
        periods = [e["wave_period"] for e in entries if e["wave_period"] is not None]
        result[d] = {
            "最大波高": _max(heights),
            "波向":     (wind_dir_str(_avg(dirs)) if dirs else ""),
            "波周期":   _avg(periods),
        }
    return result


def parse_water_json_hourly(payload: dict) -> dict[str, dict]:
    h = payload.get("hourly") or {}
    if not h.get("time") or not h.get("sea_surface_temperature"):
        return {}
    keys = ["sea_surface_temperature"]
    arrays = {"sea_surface_temperature": h["sea_surface_temperature"]}
    by_date = _group_hourly(h["time"], keys, arrays)
    result: dict[str, dict] = {}
    for d, entries in by_date.items():
        temps = [e["sea_surface_temperature"] for e in entries
                 if e["sea_surface_temperature"] is not None]
        if temps:
            result[d] = {"水温": _avg(temps)}
    return result


def parse_water_json_daily(payload: dict) -> dict[str, dict]:
    d = payload.get("daily") or {}
    if not d.get("time"):
        return {}
    means = d.get("sea_surface_temperature_mean") or []
    result: dict[str, dict] = {}
    for i, t in enumerate(d["time"]):
        if i >= len(means):
            continue
        v = means[i]
        if v is None:
            continue
        result[t] = {"水温": round(float(v) * 10) / 10}
    return result


# ---------------------------------------------------------------------------
# 月齢・潮汐（update-conditions.js と同一）
# ---------------------------------------------------------------------------
def calc_moon_age(date_str: str) -> float:
    y, m, d = (int(x) for x in date_str.split("-"))
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + (A // 4)
    JD = (math.floor(365.25 * (y + 4716))
          + math.floor(30.6001 * (m + 1))
          + d + B - 1524.5)
    new_moon_jd = 2451550.1
    synodic = 29.530588853
    age = (JD - new_moon_jd) % synodic
    if age < 0:
        age += synodic
    return round(age * 10) / 10


def moon_phase_name(age: float) -> str:
    if age < 1.85:  return "新月"
    if age < 5.55:  return "三日月"
    if age < 9.25:  return "上弦"
    if age < 12.95: return "十日夜"
    if age < 16.65: return "満月"
    if age < 20.35: return "十六夜"
    if age < 24.05: return "下弦"
    if age < 27.75: return "二十六夜"
    return "晦日"


def tide_type(age: float) -> str:
    if age <= 2 or age >= 28: return "大潮"
    if age <= 5:  return "中潮"
    if age <= 8:  return "小潮"
    if age <= 10: return "長潮"
    if age <= 12: return "若潮"
    if age <= 16: return "大潮"
    if age <= 19: return "中潮"
    if age <= 22: return "小潮"
    if age <= 24: return "長潮"
    if age <= 26: return "若潮"
    return "中潮"


# ---------------------------------------------------------------------------
# 入出力ヘルパ
# ---------------------------------------------------------------------------
def read_master_dates(path: Path) -> set[str]:
    """master_catch.csv の date 列から unique 日付を取り出す"""
    if not path.exists():
        raise FileNotFoundError(f"master not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "date" not in (reader.fieldnames or []):
            raise ValueError("master_catch.csv に date 列がない")
        return {row["date"] for row in reader if row.get("date")}


def read_existing_per_station(path: Path) -> dict[str, set[str]]:
    """fishing_condition_db.csv から (地点名 → set(日付)) のマップを返す"""
    out: dict[str, set[str]] = {s["name"]: set() for s in STATIONS}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return out
        for row in reader:
            if len(row) < 2:
                continue
            d, st = row[0], row[1]
            if not d or not st:
                continue
            out.setdefault(st, set()).add(d)
    return out


def append_rows(path: Path, rows: list[list[str]]) -> None:
    """fishing_condition_db.csv の末尾に追記。BOM/CRLF/UTF-8 を維持"""
    if not rows:
        return
    has_bom = True  # 既存DBはUTF-8 BOM付き。新規作成時もBOM付きで開始する
    newline_bytes = b"\r\n"
    if path.exists():
        with path.open("rb") as f:
            head = f.read(3)
        has_bom = head == b"\xef\xbb\xbf"
        # 改行コードは既存末尾に倣う（簡易検出）
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size > 0:
                f.seek(max(0, size - 4096))
                tail = f.read()
                if b"\r\n" in tail:
                    newline_bytes = b"\r\n"
                elif b"\n" in tail:
                    newline_bytes = b"\n"
    else:
        # ヘッダから書き始める
        body = io.StringIO()
        w = csv.writer(body, lineterminator=newline_bytes.decode("ascii"))
        w.writerow(CSV_HEADER)
        out_bytes = body.getvalue().encode("utf-8")
        with path.open("wb") as f:
            if has_bom:
                f.write(b"\xef\xbb\xbf")
            f.write(out_bytes)

    # 既存ファイルが末尾改行で終わっているかを確認し、無ければ補う
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        needs_lead_newline = False
        if size > 0:
            f.seek(max(0, size - 2))
            tail = f.read()
            if not tail.endswith(b"\n"):
                needs_lead_newline = True

    body = io.StringIO()
    writer = csv.writer(body, lineterminator=newline_bytes.decode("ascii"))
    for r in rows:
        writer.writerow(r)
    payload = body.getvalue().encode("utf-8")

    with path.open("ab") as f:
        if needs_lead_newline:
            f.write(newline_bytes)
        f.write(payload)


def dedupe_keep_last(path: Path) -> int:
    """(日付, 地点名) で keep-last 重複排除。fix_condition_db.py と同ロジック"""
    if not path.exists():
        return 0
    with path.open("rb") as f:
        raw = f.read()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    newline_bytes = b"\r\n" if b"\r\n" in raw else b"\n"
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        return 0
    rows = list(reader)
    last_idx: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows):
        if len(row) < 2:
            continue
        last_idx[(row[0], row[1])] = i
    kept = []
    dropped = 0
    for i, row in enumerate(rows):
        if len(row) < 2:
            kept.append(row)
            continue
        if last_idx.get((row[0], row[1])) == i:
            kept.append(row)
        else:
            dropped += 1
    if dropped == 0:
        return 0
    out = io.StringIO()
    w = csv.writer(out, lineterminator=newline_bytes.decode("ascii"))
    w.writerow(header)
    for row in kept:
        w.writerow(row)
    body = out.getvalue().encode("utf-8")
    if has_bom:
        body = b"\xef\xbb\xbf" + body
    with path.open("wb") as f:
        f.write(body)
    return dropped


# ---------------------------------------------------------------------------
# 1地点分の取得
# ---------------------------------------------------------------------------
def _group_contiguous(sorted_dates: list[str], max_days: int = 60) -> list[tuple[str, str]]:
    """連続日付を max_days 以内のチャンクにまとめる"""
    if not sorted_dates:
        return []
    chunks: list[tuple[str, str]] = []
    start = sorted_dates[0]
    end = sorted_dates[0]
    count = 1
    for d in sorted_dates[1:]:
        prev = datetime.fromisoformat(end).date() + timedelta(days=1)
        if d == prev.isoformat() and count < max_days:
            end = d
            count += 1
        else:
            chunks.append((start, end))
            start = d
            end = d
            count = 1
    chunks.append((start, end))
    return chunks


def fetch_weather_for_station(station: dict, from_date: str, to_date: str) -> dict[str, dict]:
    """archive と forecast を境界で分割して両方取り、合算"""
    five_days_ago = (date.today() - timedelta(days=ARCHIVE_LAG_DAYS)).isoformat()
    result: dict[str, dict] = {}

    # archive 区間
    if from_date <= five_days_ago:
        arc_end = to_date if to_date <= five_days_ago else five_days_ago
        try:
            url = weather_archive_url(station["lat"], station["lng"], from_date, arc_end)
            payload = fetch_json(url)
            result.update(parse_weather_json(payload))
        except Exception as e:
            log(f"  archive 天気取得失敗 {station['name']} {from_date}〜{arc_end}: {e}")
        time.sleep(API_DELAY_SEC)

    # forecast 区間
    if to_date > five_days_ago:
        fc_start = from_date if from_date > five_days_ago \
            else (datetime.fromisoformat(five_days_ago).date()
                  + timedelta(days=1)).isoformat()
        try:
            url = weather_forecast_url(station["lat"], station["lng"], fc_start, to_date)
            payload = fetch_json(url)
            result.update(parse_weather_json(payload))
        except Exception as e:
            log(f"  forecast 天気取得失敗 {station['name']} {fc_start}〜{to_date}: {e}")

    return result


def fetch_marine_for_station(station: dict, from_date: str, to_date: str) -> dict[str, dict]:
    url = marine_url(station["lat"], station["lng"], from_date, to_date,
                     "hourly=wave_height,wave_direction,wave_period")
    payload = fetch_json(url)
    return parse_marine_json(payload)


def fetch_water_for_station(station: dict, from_date: str, to_date: str) -> dict[str, dict]:
    # まず時間別 → 失敗時は日別フォールバック
    try:
        url = marine_url(station["lat"], station["lng"], from_date, to_date,
                         "hourly=sea_surface_temperature")
        payload = fetch_json(url)
        result = parse_water_json_hourly(payload)
        if result:
            return result
    except Exception as e:
        log(f"  hourly 水温失敗 → 日別フォールバック: {e}")
    url2 = marine_url(station["lat"], station["lng"], from_date, to_date,
                      "daily=sea_surface_temperature_mean")
    payload = fetch_json(url2)
    return parse_water_json_daily(payload)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def build_row(date_str: str, station: dict, w: dict, wt: dict, m: dict) -> list[str]:
    age = calc_moon_age(date_str)
    return [
        date_str,
        station["name"],
        station["name"],
        station["pref"],
        str(station["lat"]),
        str(station["lng"]),
        "" if w.get("気温_平均") is None else str(w["気温_平均"]),
        "" if w.get("気温_最高") is None else str(w["気温_最高"]),
        "" if w.get("気温_最低") is None else str(w["気温_最低"]),
        "" if w.get("風速_最大") is None else str(w["風速_最大"]),
        w.get("風向") or "",
        "" if w.get("降水量") is None else str(w["降水量"]),
        "" if w.get("天気コード") is None else str(w["天気コード"]),
        w.get("天気") or "",
        "" if wt.get("水温") is None else str(wt["水温"]),
        "" if m.get("最大波高") is None else str(m["最大波高"]),
        m.get("波向") or "",
        "" if m.get("波周期") is None else str(m["波周期"]),
        tide_type(age),
        str(age),
        moon_phase_name(age),
    ]


def sync(master_path: Path, condition_path: Path, check_only: bool = False) -> int:
    log(f"開始 master={master_path} condition={condition_path}")

    master_dates = read_master_dates(master_path)
    log(f"master_catch.csv: unique 日付 {len(master_dates)} 件")

    existing_per_station = read_existing_per_station(condition_path)
    for s in STATIONS:
        log(f"  {s['name']}: 既存 {len(existing_per_station.get(s['name'], set()))} 件")

    # toDate は前日まで（API 安定性、update-conditions.js 同様）
    today_jst = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # master の日付のうち、各地点で欠損している日付を抽出
    # ただし toDate（前日）以前のもののみ
    plan: dict[str, list[str]] = {}
    for s in STATIONS:
        existing = existing_per_station.get(s["name"], set())
        missing = sorted(d for d in master_dates if d not in existing and d <= yesterday)
        plan[s["name"]] = missing
        log(f"  {s['name']}: 欠損 {len(missing)} 件")

    total_missing = sum(len(v) for v in plan.values())
    if total_missing == 0:
        log("変更なし。すべての地点で master の日付がカバーされています")
        return 0

    if check_only:
        log(f"--check-only 指定。{total_missing} 件の不足を検出（取得は行わない）")
        return total_missing

    # 取得＆追記
    new_rows: list[list[str]] = []
    for s in STATIONS:
        dates = plan[s["name"]]
        if not dates:
            log(f"📍 {s['name']} スキップ（欠損なし）")
            continue
        chunks = _group_contiguous(dates, max_days=60)
        log(f"📍 {s['name']} {len(dates)}件 → {len(chunks)}チャンク")
        for from_d, to_d in chunks:
            log(f"  チャンク {from_d}〜{to_d}")
            try:
                w = fetch_weather_for_station(s, from_d, to_d)
                log(f"    天気: {len(w)} 日分")
            except Exception as e:
                log(f"    天気取得失敗: {e}")
                raise

            time.sleep(API_DELAY_SEC)
            try:
                wt = fetch_water_for_station(s, from_d, to_d)
                log(f"    水温: {len(wt)} 日分")
            except Exception as e:
                log(f"    水温取得失敗: {e}")
                raise

            time.sleep(API_DELAY_SEC)
            try:
                m = fetch_marine_for_station(s, from_d, to_d)
                log(f"    波浪: {len(m)} 日分")
            except Exception as e:
                log(f"    波浪取得失敗: {e}")
                raise

            time.sleep(API_DELAY_SEC)

            # 欠損日のみ書き出す（取得 API が範囲内の他日付も含むので絞り込む）
            target_set = set(dates)
            for d in sorted(target_set):
                if d < from_d or d > to_d:
                    continue
                row = build_row(d, s, w.get(d, {}), wt.get(d, {}), m.get(d, {}))
                new_rows.append(row)

    log(f"追記対象レコード: {len(new_rows)} 件")
    if new_rows:
        append_rows(condition_path, new_rows)
        dropped = dedupe_keep_last(condition_path)
        log(f"keep-last 重複排除: {dropped} 件削除")

    log("完了")
    return len(new_rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="V5.5 push 後の V6.0 自動同期：master_catch.csv に追加された日付の気象データを Open-Meteo から差分取得"
    )
    p.add_argument("--master", type=Path, required=True,
                   help="data/master_catch.csv のパス")
    p.add_argument("--condition", type=Path, required=True,
                   help="data/fishing_condition_db.csv のパス（上書き）")
    p.add_argument("--check-only", action="store_true",
                   help="不足件数を計算するのみで API 呼び出し・追記を行わない")
    args = p.parse_args(argv)

    try:
        n = sync(args.master, args.condition, check_only=args.check_only)
        # 取得件数を stdout（CI 観測用）
        print(f"sync_condition_db: {n} new rows")
        return 0
    except Exception as e:  # noqa: BLE001
        log(f"FATAL {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
