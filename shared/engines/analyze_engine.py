#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
釣果データ解析エンジン v2.0
設計書 v1.0 に準拠した3DB結合版

DB① fishing_muroto_v1.csv           -- メイン釣果テーブル（室戸沖釣果DB V2.0が生成）
DB② muroto_offshore_current_all.csv -- 5地点海流詳細（CMEMS）
DB③ fishing_condition_db.csv        -- 気象・潮汐・波高（Open-Meteo）

出力: analysis_result.json（index.html が fetch で読み込む本番JSON）
"""

import argparse, csv, json, math, os, re
from datetime import datetime, timedelta
from collections import defaultdict

# ─── 設定（ファイル名のみ変更可） ───────────────────────────
DB1_CSV  = "data/fishing_muroto_v1.csv"            # DB① メイン釣果（室戸沖釣果DB V2.0 が生成するファイル名）
DB2_CSV  = "data/muroto_offshore_current_all.csv"  # DB② 5地点海流
DB3_CSV  = "data/fishing_condition_db.csv"         # DB③ 気象・潮汐
DB3_STATION = "室戸"                           # DB③ 解析対象地点

# 本番ワークフロー（2026-04-17 確定 → W6-3 / 2026-04-19 で統合リポ向けに更新）:
#   - 統合リポ fishing-system では development.html / index.html は廃止され、
#     `muroto_fishing_analysis.html` 1ファイルに統合済（W5-3 で統一）。
#   - analyze_engine.py は analysis_result.json を書き、同 HTML の
#     window.ANALYSIS_DATA 埋め込みブロックを毎回最新化する。
#   - 後方互換のため DEV_HTML / INDEX_HTML が共に存在しても同 HTML を指す。
#     旧スタンドアロン構成（development.html / index.html）が併存する環境では
#     ファイル存在チェックで安全にスキップする。
OUTPUT_JSON    = "data/analysis/analysis_result.json"   # 本番JSON（fetch 用 / CI 出力）
DEV_HTML       = "muroto_fishing_analysis.html"  # v2.1 解析ソフト本体（埋め込みデータ更新対象）
INDEX_HTML     = "muroto_fishing_analysis.html"  # 同一ファイル（旧 INDEX_HTML 互換シム）

# ─── 解析対象の数値カラム（DB①） ──────────────────────────
NUMERIC_COLS = [
    "室戸沖_流速kn", "室戸沖_流向", "室戸沖_水温", "室戸沖_塩分",
    "北西_流速kn",   "北西_流向",   "北西_水温",   "北西_塩分",
    "気温_平均", "気温_最高", "気温_最低",
    "風速_最大", "降水量",
    "水温(Open-Meteo)", "最大波高", "波周期", "月齢",
]

# ─── 数学ユーティリティ ───────────────────────────────────
def safe_float(v):
    try: return float(v)
    except: return None

def mean_(v):
    v = [x for x in v if x is not None]
    return sum(v)/len(v) if v else None

def median_(v):
    v = sorted(x for x in v if x is not None)
    n = len(v)
    if not n: return None
    return v[n//2] if n%2 else (v[n//2-1]+v[n//2])/2

def std_(v):
    v = [x for x in v if x is not None]
    if len(v)<2: return None
    m = mean_(v)
    return math.sqrt(sum((x-m)**2 for x in v)/len(v))

def pct_(v, p):
    v = sorted(x for x in v if x is not None)
    if not v: return None
    idx = (len(v)-1)*p/100
    lo = int(idx)
    return v[lo]*(lo+1-idx)+v[lo+1]*(idx-lo) if lo+1<len(v) else v[lo]

def r2(v): return round(v,2) if v is not None else None

def stats_(vals):
    v = [x for x in vals if x is not None]
    if not v: return {"n":0}
    return {"n":len(v),"mean":r2(mean_(v)),"median":r2(median_(v)),
            "std":r2(std_(v)),"min":r2(min(v)),"max":r2(max(v)),
            "p25":r2(pct_(v,25)),"p75":r2(pct_(v,75))}

def freq_(vals):
    total = sum(1 for v in vals if v)
    if not total: return {}
    cnt = defaultdict(int)
    for v in vals:
        if v: cnt[v] += 1
    return {k:round(c/total*100,1) for k,c in sorted(cnt.items(),key=lambda x:-x[1])}

# ─── DB① 読み込み ─────────────────────────────────────────
def load_db1(path, boat_ids=None):
    """fishing_muroto_v1.csv を読み込む。

    Args:
      path: CSV パス
      boat_ids: 絞り込む boat_id の集合 (set) / None なら全件
    """
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try: row["_date"] = datetime.strptime(row["date"].strip(),"%Y-%m-%d").date()
            except: row["_date"] = None
            for c in NUMERIC_COLS:
                row[c] = safe_float(row.get(c,""))
            if boat_ids is not None:
                if row.get("boat_id", "") not in boat_ids:
                    continue
            rows.append(row)
    rows.sort(key=lambda r: r["_date"] or datetime.min.date())
    return rows

# ─── DB② 読み込み（5地点×日付） ──────────────────────────
def load_db2(path):
    """返り値: {(date, point): row}"""
    db = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try: d = datetime.strptime(row["date"].strip(),"%Y-%m-%d").date()
            except: continue
            pt = row.get("point","").strip()
            for c in ["u_ms","v_ms","speed_ms","speed_kn","direction","temp_c","salinity"]:
                row[c] = safe_float(row.get(c,""))
            db[(d, pt)] = row
    return db

# ─── DB③ 読み込み（地点×日付） ────────────────────────────
def load_db3(path):
    """返り値: {(date, 地点名): row}"""
    db = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try: d = datetime.strptime(row["日付"].strip(),"%Y-%m-%d").date()
            except: continue
            st = row.get("地点名","").strip()
            for c in ["気温_平均","気温_最高","気温_最低","風速_最大","降水量",
                       "水温","最大波高","波周期","月齢"]:
                row[c] = safe_float(row.get(c,""))
            db[(d, st)] = row
    return db

# ─── 水温トレンド計算（DB③ 室戸データから） ──────────────
def build_temp_trend(db3, station=DB3_STATION):
    temp_by_date = {}
    for (d, st), row in db3.items():
        if st == station:
            wt = row.get("水温")
            if wt is not None:
                temp_by_date[d] = wt

    trend = {}
    for d, wt in temp_by_date.items():
        p1 = temp_by_date.get(d - timedelta(days=1))
        p7 = temp_by_date.get(d - timedelta(days=7))
        win = [temp_by_date.get(d - timedelta(days=j)) for j in range(7)]
        win = [x for x in win if x is not None]
        ma7 = round(sum(win)/len(win),2) if win else None
        d7  = round(wt - p7, 2) if p7 is not None else None
        if   d7 is None:   lbl = "不明"
        elif d7 >= 1.5:    lbl = "急上昇"
        elif d7 >= 0.5:    lbl = "上昇"
        elif d7 <= -1.5:   lbl = "急下降"
        elif d7 <= -0.5:   lbl = "下降"
        else:              lbl = "安定"
        trend[d] = {
            "水温": wt,
            "水温前日差": r2(round(wt-p1,2) if p1 is not None else None),
            "水温7日差":  d7,
            "水温7日MA":  ma7,
            "水温トレンド": lbl,
        }
    return trend

# ─── 海流トレンド計算（DB② 室戸沖ポイントから） ──────────
def build_current_trend(db2, point="室戸沖"):
    speed_by_date = {}
    dir_by_date   = {}
    for (d, pt), row in db2.items():
        if pt == point:
            sp = row.get("speed_kn")
            dr = row.get("direction")
            if sp is not None: speed_by_date[d] = sp
            if dr is not None: dir_by_date[d]   = dr

    trend = {}
    for d in speed_by_date:
        sp = speed_by_date[d]
        p7 = speed_by_date.get(d - timedelta(days=7))
        win = [speed_by_date.get(d - timedelta(days=j)) for j in range(7)]
        win = [x for x in win if x is not None]
        ma7 = round(sum(win)/len(win),3) if win else None
        d7  = round(sp - p7, 3) if p7 is not None else None
        if   d7 is None:    lbl = "不明"
        elif d7 >= 0.2:     lbl = "流速増加"
        elif d7 <= -0.2:    lbl = "流速減少"
        else:               lbl = "流速安定"
        trend[d] = {
            "流速kn": sp,
            "流向": dir_by_date.get(d),
            "流速7日MA": ma7,
            "流速トレンド": lbl,
        }
    return trend

# ─── 方位角 → 8方位 ───────────────────────────────────────
COMPASS8 = ["N","NE","E","SE","S","SW","W","NW"]
def deg_to_compass(deg):
    if deg is None: return None
    return COMPASS8[int((deg+22.5)/45)%8]

# ─── 魚種別プロファイル生成 ───────────────────────────────
def analyze_species(sp_name, db1_rows, temp_trend, current_trend, db2, db3):
    rows = [r for r in db1_rows if r.get("species","") == sp_name]
    if not rows: return None

    catch_dates = sorted(set(r["_date"] for r in rows if r["_date"]))
    if len(catch_dates) < 2: return None

    # ── 数値統計（DB①）
    num_stats = {c: stats_([r[c] for r in rows]) for c in NUMERIC_COLS}

    # ── カテゴリ統計（DB①）
    tide_dist    = freq_([r.get("潮汐","") for r in rows])
    weather_dist = freq_([r.get("天気","") for r in rows])
    moon_dist    = freq_([r.get("月相","") for r in rows])
    method_dist  = freq_([r.get("method","") for r in rows])

    # ── 月別釣果数
    month_cnt = defaultdict(int)
    for r in rows:
        if r["_date"]:
            month_cnt[r["_date"].month] += int(safe_float(r.get("count","")) or 1)
    month_dist = {str(m): month_cnt[m] for m in range(1,13)}

    # ── 水温帯分布（2℃刻み）
    wt_bins = defaultdict(int)
    for r in rows:
        wt = r.get("室戸沖_水温") or r.get("水温(Open-Meteo)")
        if wt is not None:
            lo = int(wt//2)*2
            wt_bins[f"{lo}〜{lo+2}℃"] += 1
    wt_bin_dist = dict(sorted(wt_bins.items(),key=lambda x:x[0]))

    # ── 流速帯分布
    cs_bins = defaultdict(int)
    for r in rows:
        cs = r.get("室戸沖_流速kn")
        if cs is not None:
            if   cs < 0.3:  k = "弱(0〜0.3kn)"
            elif cs < 0.6:  k = "中(0.3〜0.6kn)"
            elif cs < 1.0:  k = "強(0.6〜1.0kn)"
            else:           k = "激流(1.0kn+)"
            cs_bins[k] += 1
    cs_bin_dist = dict(cs_bins)

    # ── 流向分布（DB①流向数値 → 8方位）
    dir_bins = defaultdict(int)
    for r in rows:
        dr = r.get("室戸沖_流向")
        if dr is not None:
            dir_bins[deg_to_compass(dr)] += 1
    total_dir = sum(dir_bins.values())
    dir_dist  = {k:round(v/total_dir*100,1) for k,v in
                 sorted(dir_bins.items(),key=lambda x:-x[1])} if total_dir else {}

    # ── DB② 5地点海流プロファイル（釣果日のみ）
    db2_profiles = {}
    for pt in ["室戸沖","北西","西","東","北東"]:
        speeds = []; dirs = []; temps = []; sals = []
        for d in catch_dates:
            row2 = db2.get((d, pt))
            if row2:
                if row2["speed_kn"] is not None: speeds.append(row2["speed_kn"])
                if row2["direction"] is not None: dirs.append(row2["direction"])
                if row2["temp_c"]    is not None: temps.append(row2["temp_c"])
                if row2["salinity"]  is not None: sals.append(row2["salinity"])
        if speeds or temps:
            db2_profiles[pt] = {
                "流速stats": stats_(speeds),
                "水温stats": stats_(temps),
                "塩分stats": stats_(sals),
                "流向分布": freq_([deg_to_compass(d) for d in dirs]),
            }

    # ── 水温トレンド分布（釣果日）
    trend_vals = [temp_trend.get(d,{}).get("水温トレンド") for d in catch_dates]
    trend_dist = freq_(trend_vals)

    # ── 流速トレンド分布（釣果日）
    cs_trend_vals = [current_trend.get(d,{}).get("流速トレンド") for d in catch_dates]
    cs_trend_dist = freq_(cs_trend_vals)

    # ── サイズ・重量統計
    sizes   = [safe_float(r.get("size_cm"))  for r in rows]
    weights = [safe_float(r.get("weight_kg")) for r in rows]
    counts  = [safe_float(r.get("count"))     for r in rows]

    return {
        "species":           sp_name,
        "total_records":     len(rows),
        "catch_days":        len(catch_dates),
        "catch_date_range":  {"first": str(catch_dates[0]),  "last": str(catch_dates[-1])},
        "size_stats":        stats_(sizes),
        "weight_stats":      stats_(weights),
        "count_stats":       stats_(counts),
        "numeric_stats":     num_stats,
        "tide_dist":         tide_dist,
        "weather_dist":      weather_dist,
        "moon_dist":         moon_dist,
        "method_dist":       method_dist,
        "month_dist":        month_dist,
        "water_temp_bins":   wt_bin_dist,
        "current_speed_bins":cs_bin_dist,
        "current_dir_dist":  dir_dist,
        "water_temp_trend_dist":    trend_dist,
        "current_speed_trend_dist": cs_trend_dist,
        "db2_5point_profiles":      db2_profiles,
    }

# ─── ベースライン統計 ──────────────────────────────────────
def build_baseline(db1_rows, db3, station=DB3_STATION):
    bl = {c: stats_([r[c] for r in db1_rows]) for c in NUMERIC_COLS}
    bl["潮汐"] = freq_([r.get("潮汐","") for r in db1_rows])
    bl["天気"]  = freq_([r.get("天気","")  for r in db1_rows])

    # DB③ 全期間の室戸水温ベースライン
    db3_wt = [row["水温"] for (d,st),row in db3.items()
              if st==station and row.get("水温") is not None]
    bl["DB③_室戸水温"] = stats_(db3_wt)
    return bl

# ─── 直近30日予測スコア ────────────────────────────────────
def predict_recent(db3, db2, temp_trend, current_trend, profiles, station=DB3_STATION):
    db3_dates = sorted(set(d for (d,st) in db3 if st==station))
    if not db3_dates: return {}
    latest = db3_dates[-1]
    start  = latest - timedelta(days=29)
    result = {}

    for i in range(30):
        d = start + timedelta(days=i)
        cond3 = db3.get((d, station), {})
        cond2 = db2.get((d, "室戸沖"), {})
        tt    = temp_trend.get(d, {})
        ct    = current_trend.get(d, {})

        wt    = cond3.get("水温")
        wave  = cond3.get("最大波高")
        tide  = cond3.get("潮汐","")
        moon  = cond3.get("月齢")
        trend = tt.get("水温トレンド","不明")
        cs    = cond2.get("speed_kn") or 0

        day_scores = {}
        for sp, prof in profiles.items():
            if not prof: continue
            score = 0

            # 1. 水温スコア（最大40pt）
            ns = prof["numeric_stats"].get("室戸沖_水温") or prof["numeric_stats"].get("水温(Open-Meteo)",{})
            if wt is not None and ns.get("mean") and ns.get("std"):
                z = abs(wt - ns["mean"]) / max(ns["std"], 0.5)
                score += max(0, 40 - z*15)
            elif wt is not None and ns.get("p25") and ns.get("p75"):
                if ns["p25"] <= wt <= ns["p75"]: score += 30

            # 2. 水温トレンドスコア（最大20pt）
            tp = prof.get("water_temp_trend_dist",{}).get(trend, 0)
            score += round(tp/100*20, 1)

            # 3. 潮汐スコア（最大20pt）
            tidep = prof.get("tide_dist",{}).get(tide, 0)
            score += round(tidep/100*20, 1)

            # 4. 月齢スコア（最大10pt）
            mns = prof["numeric_stats"].get("月齢",{})
            if moon is not None and mns.get("mean") and mns.get("std"):
                z2 = abs(moon - mns["mean"]) / max(mns["std"],1.0)
                score += max(0, 10 - z2*4)

            # 5. 波高スコア（最大10pt）
            wns = prof["numeric_stats"].get("最大波高",{})
            if wave is not None and wns.get("p75"):
                if wave <= wns["p75"]: score += 10

            day_scores[sp] = {
                "score": round(score, 1),
                "水温": r2(wt),
                "潮汐": tide,
                "水温トレンド": trend,
                "流速kn": r2(cond2.get("speed_kn")),
                "波高": r2(wave),
                "水温前日差": r2(tt.get("水温前日差")),
                "水温7日差":  r2(tt.get("水温7日差")),
            }
        result[str(d)] = day_scores

    return result

# ─── 水温+釣果 タイムライン ────────────────────────────────
def build_timeseries(db3, temp_trend, current_trend, db1_rows, db2, station=DB3_STATION):
    db3_dates = sorted(set(d for (d,st) in db3 if st==station))

    # 釣果マップ（日付→魚種リスト）
    catch_map = defaultdict(list)
    for r in db1_rows:
        if r["_date"]: catch_map[r["_date"]].append(r["species"])

    # 魚種別の重量上位20%しきい値を計算
    sp_weights = defaultdict(list)
    for r in db1_rows:
        w  = safe_float(r.get("weight_kg", ""))
        sp = r.get("species", "")
        if w is not None and sp:
            sp_weights[sp].append(w)
    sp_thresh = {}
    for sp, ws in sp_weights.items():
        ws_sorted = sorted(ws)
        sp_thresh[sp] = ws_sorted[int(len(ws_sorted) * 0.8)]

    # 日付 → 「大物」に該当する魚種リスト
    big_date_species = defaultdict(set)
    for r in db1_rows:
        if not r["_date"]: continue
        sp = r.get("species", "")
        w  = safe_float(r.get("weight_kg", ""))
        thr = sp_thresh.get(sp)
        if sp and w is not None and thr is not None and w >= thr:
            big_date_species[r["_date"]].add(sp)

    series = []
    for d in db3_dates:
        cond3  = db3.get((d, station), {})
        tt     = temp_trend.get(d, {})
        ct     = current_trend.get(d, {})
        db2row = db2.get((d, "室戸沖"), {})   # DB② 室戸沖の流向
        series.append({
            "date":         str(d),
            "水温":         r2(cond3.get("水温")),
            "水温7日MA":    r2(tt.get("水温7日MA")),
            "水温トレンド": tt.get("水温トレンド"),
            "水温前日差":   r2(tt.get("水温前日差")),
            "流速kn":       r2(ct.get("流速kn")),
            "流向":         r2(db2row.get("direction")),   # 追加：流向（度）
            "流速7日MA":    r2(ct.get("流速7日MA")),
            "流速トレンド": ct.get("流速トレンド"),
            "月齢":         r2(safe_float(cond3.get("月齢",""))),  # 追加：月齢
            "月相":         cond3.get("月相",""),                  # 追加：月相
            "釣果":         list(set(catch_map.get(d,[]))),
            "大物魚種":     sorted(big_date_species.get(d, set())), # 追加：魚種別大物リスト
        })
    return series, {sp: r2(thr) for sp, thr in sp_thresh.items()}

# ─── DB② 月次サマリー（全期間） ──────────────────────────
def build_monthly_summary(db2):
    monthly = defaultdict(lambda: defaultdict(list))
    for (d, pt), row in db2.items():
        key = (d.year, d.month, pt)
        if row.get("speed_kn")  is not None: monthly[key]["speed_kn"].append(row["speed_kn"])
        if row.get("temp_c")    is not None: monthly[key]["temp_c"].append(row["temp_c"])
        if row.get("salinity")  is not None: monthly[key]["salinity"].append(row["salinity"])
        if row.get("direction") is not None: monthly[key]["direction"].append(row["direction"])

    result = []
    for (year, month, pt), vals in sorted(monthly.items()):
        result.append({
            "year": year, "month": month, "point": pt,
            "avg_speed_kn":  r2(mean_(vals.get("speed_kn",[]))),
            "avg_temp_c":    r2(mean_(vals.get("temp_c",[]))),
            "avg_salinity":  r2(mean_(vals.get("salinity",[]))),
            "avg_direction": r2(mean_(vals.get("direction",[]))),
            "days": len(vals.get("speed_kn",[])),
        })
    return result

# ─── スタンドアロンHTML生成 ────────────────────────────────
def generate_standalone_html(result_data, template_path, output_path):
    """テンプレートHTMLのfetch処理をwindow.ANALYSIS_DATAに置き換えて出力"""
    json_str = json.dumps(result_data, ensure_ascii=False)

    with open(template_path, encoding="utf-8") as f:
        html = f.read()

    # fetch ブロックを data-inline ブロックに差し替え
    inline_script = f"""<script>
// データ埋め込み済み（standalone生成）
window.ANALYSIS_DATA = {json_str};
</script>"""

    # </head> 直前にデータを注入
    html = html.replace("</head>", inline_script + "\n</head>", 1)

    # fetch() 呼び出し部分を window.ANALYSIS_DATA 参照に置き換え
    old_fetch = """  fetch('analysis_result.json')
    .then(r => { if (!r.ok) throw new Error('not found'); return r.json(); })
    .then(data => initApp(data))
    .catch(() => {
      document.getElementById('load-status').textContent = 'analysis_result.json が見つかりません。「データ読込」タブからファイルを選択してください。';
      setTimeout(() => {
        document.getElementById('loading-overlay').style.display = 'none';
        switchTab('load');
      }, 1500);
    });"""

    new_fetch = """  // データ埋め込み済み
  if (window.ANALYSIS_DATA) {
    initApp(window.ANALYSIS_DATA);
  } else {
    fetch('analysis_result.json')
      .then(r => { if (!r.ok) throw new Error('not found'); return r.json(); })
      .then(data => initApp(data))
      .catch(() => {
        document.getElementById('load-status').textContent = 'analysis_result.json が見つかりません。「データ読込」タブからファイルを選択してください。';
        setTimeout(() => {
          document.getElementById('loading-overlay').style.display = 'none';
          switchTab('load');
        }, 1500);
      });
  }"""

    html = html.replace(old_fetch, new_fetch)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

# ─── HTML 内の埋め込みデータ更新（development.html / index.html 共通） ───
# 対象HTMLには window.ANALYSIS_DATA = {...}; が1行で埋め込まれている。
# その行だけを最新の解析結果で置換し、他の行（UI/JS/CSS）はそのまま維持する。
# development.html: 屋外/ローカル file:// 運用（オフラインでも埋め込みで完結）
# index.html:       GitHub Pages 配信用（公開版も埋め込み型で自己完結、fetch不要）
def update_embedded_analysis_data(html_path, result_obj):
    if not os.path.exists(html_path):
        return False
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_json_str = json.dumps(result_obj, ensure_ascii=False, default=str)
        new_line = f"window.ANALYSIS_DATA = {new_json_str};\n"
        replaced = False
        for i, line in enumerate(lines):
            # 「window.ANALYSIS_DATA = 」で始まる行を唯一のマーカーとする
            if line.startswith("window.ANALYSIS_DATA "):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            return False
        with open(html_path, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        print(f"⚠  {os.path.basename(html_path)} 更新中にエラー: {e}")
        return False

# ─── メイン ───────────────────────────────────────────────
def main():
    # Muroto 拡張: CLI 引数でパスを上書き可能にする。引数なしの場合は従来通り
    # base = scripts/ の親（リポジトリルート）を基点にした相対パスを使う。
    parser = argparse.ArgumentParser(description="釣果データ解析エンジン")
    parser.add_argument("--db1", default=None, help="DB① fishing_muroto_v1.csv のパス")
    parser.add_argument("--db2", default=None, help="DB② 海流5地点 CSV のパス")
    parser.add_argument("--db3", default=None, help="DB③ 気象DB CSV のパス")
    parser.add_argument("--out", default=None, help="出力 analysis_result.json のパス")
    parser.add_argument("--html", default=None,
                        help="埋込更新する HTML のパス（指定しなければ既定 or スキップ）")
    parser.add_argument("--no-html", action="store_true",
                        help="HTML 埋込更新をスキップ")
    parser.add_argument("--boats", default=None,
                        help="カンマ区切り boat_id で DB① を絞り込む（例: muroto1,muroto2）")
    args = parser.parse_args()

    boat_filter = None
    if args.boats:
        boat_filter = set(b.strip() for b in args.boats.split(",") if b.strip())

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db1_path  = args.db1 or os.path.join(base, DB1_CSV)
    db2_path  = args.db2 or os.path.join(base, DB2_CSV)
    db3_path  = args.db3 or os.path.join(base, DB3_CSV)
    out_json  = args.out or os.path.join(base, OUTPUT_JSON)
    html_override = args.html  # None なら従来どおり DEV_HTML/INDEX_HTML を見る
    skip_html = args.no_html
    # 出力ディレクトリ（data/analysis/）が存在しない場合は作成（CI 初回実行対応）
    os.makedirs(os.path.dirname(out_json), exist_ok=True)

    print("=" * 50)
    print("  室戸沖 釣果データ解析エンジン v2.0")
    print("=" * 50)

    print("\n[1/7] DB① 釣果データ読み込み中...")
    if boat_filter:
        print(f"      → boat_id フィルタ: {sorted(boat_filter)}")
    db1 = load_db1(db1_path, boat_ids=boat_filter)
    print(f"      → {len(db1)} レコード")

    print("[2/7] DB② 5地点海流データ読み込み中...")
    db2 = load_db2(db2_path)
    pts = sorted(set(pt for (_,pt) in db2))
    print(f"      → {len(db2)} 件 ／ 地点: {pts}")

    print("[3/7] DB③ 気象・潮汐データ読み込み中...")
    db3 = load_db3(db3_path)
    sts = sorted(set(st for (_,st) in db3))
    db3_dates = sorted(set(d for (d,st) in db3 if st==DB3_STATION))
    print(f"      → {len(db3)} 件 ／ 地点: {sts}")
    print(f"      → 室戸: {db3_dates[0]} 〜 {db3_dates[-1]} ({len(db3_dates)}日)")

    print("[4/7] 水温・海流トレンド計算中...")
    temp_trend    = build_temp_trend(db3)
    current_trend = build_current_trend(db2)
    print(f"      → 水温トレンド: {len(temp_trend)}日 ／ 海流トレンド: {len(current_trend)}日")

    print("[5/7] 魚種別プロファイル解析中...")
    all_sp = sorted(set(r["species"] for r in db1 if r.get("species")))
    baseline = build_baseline(db1, db3)
    profiles = {}
    for sp in all_sp:
        p = analyze_species(sp, db1, temp_trend, current_trend, db2, db3)
        if p: profiles[sp] = p
    print(f"      → {len(profiles)} 魚種のプロファイル生成完了")

    print("[6/7] 直近30日 釣れ予測計算中...")
    predictions = predict_recent(db3, db2, temp_trend, current_trend, profiles)
    pred_dates  = sorted(predictions.keys())
    if pred_dates:
        print(f"      → 予測期間: {pred_dates[0]} 〜 {pred_dates[-1]}")

    print("[7/7] タイムライン・月次サマリー生成中...")
    timeseries, sp_thresh = build_timeseries(db3, temp_trend, current_trend, db1, db2)
    monthly    = build_monthly_summary(db2)
    big_days = sum(1 for r in timeseries if r.get("大物魚種"))
    print(f"      → 魚種別大物しきい値算出完了（大物フラグあり: {big_days}日）")

    # ── 生レコード（フィルター用） ──
    RECORD_COLS = [
        "室戸沖_流速kn","室戸沖_流向","室戸沖_水温","室戸沖_塩分",
        "北西_流速kn","北西_流向","北西_水温","北西_塩分",
        "気温_平均","風速_最大","最大波高","波周期",
        "水温(Open-Meteo)","月齢",
    ]
    records = []
    for r in db1:
        if not r.get("species") or not r["_date"]: continue
        rec = {
            "date":    str(r["_date"]),
            "species": r.get("species",""),
            "spot":    r.get("spot",""),
            "method":  r.get("method",""),
            "count":   safe_float(r.get("count")) or 1,
            "size_cm": safe_float(r.get("size_cm")),
            "weight_kg": safe_float(r.get("weight_kg")),
            "潮汐": r.get("潮汐",""),
            "月相": r.get("月相",""),
            "天気": r.get("天気",""),
            "_wt_trend": temp_trend.get(r["_date"],{}).get("水温トレンド","不明"),
        }
        for c in RECORD_COLS:
            rec[c] = r.get(c)
        records.append(rec)

    # 釣り場・釣法の選択肢リスト
    all_spots   = sorted(set(r["spot"]   for r in records if r["spot"]))
    all_methods = sorted(set(r["method"] for r in records if r["method"]))

    # ── 結果オブジェクト組立 ──
    result = {
        "version": "2.1",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "db_info": {
            "db1_records":     len(db1),
            "db2_records":     len(db2),
            "db3_records":     len(db3),
            "db3_date_range":  {"first": str(db3_dates[0]), "last": str(db3_dates[-1])},
            "condition_days":  len(db3_dates),
        },
        "species_count":   len(profiles),
        "all_species":     list(all_sp),
        "all_spots":       all_spots,
        "all_methods":     all_methods,
        "baseline":        baseline,
        "species_profiles":profiles,
        "predictions":     predictions,
        "temp_timeseries":      timeseries,
        "sp_big_thresholds":    sp_thresh,   # 魚種別大物しきい値（kg）
        "monthly_summary":    monthly,
        "records":            records,
    }

    # JSON 保存（index.html が fetch で読み込む本番JSON）
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ JSON出力: {out_json}")

    # HTML 埋込更新（--no-html でスキップ、--html で明示指定、無指定時は既定パス）
    if skip_html:
        print("ℹ  --no-html 指定のため HTML 埋込更新をスキップ")
    else:
        if html_override:
            html_targets = [("HTML", html_override)]
        else:
            html_targets = [("DEV_HTML", os.path.join(base, DEV_HTML)),
                            ("INDEX_HTML", os.path.join(base, INDEX_HTML))]
        seen: set[str] = set()
        for label, path in html_targets:
            if path in seen:
                continue
            seen.add(path)
            if not os.path.exists(path):
                print(f"ℹ  {label} ({path}) は存在しないためスキップ")
                continue
            ok = update_embedded_analysis_data(path, result)
            if ok:
                print(f"✅ {label} 埋め込みデータ更新: {path}")
            else:
                print(f"⚠  {label} を更新できませんでした（パス/マーカー不一致）: {path}")

    # dashboard.html 生成は 2026-04-17 に廃止（development.html / index.html 共に埋め込み型に移行）。
    # generate_standalone_html 関数自体は将来再利用の可能性を考慮しデッドコードとして残置。

    print("\n" + "="*50)
    print(f"  解析完了！ development.html をブラウザで開いてください（最新データ埋め込み済み）")
    print("="*50)

if __name__ == "__main__":
    main()
