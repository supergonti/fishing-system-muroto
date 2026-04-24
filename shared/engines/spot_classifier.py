"""
spot_classifier.py — Bグループ分類エンジン

役割:
  raw spot（Aグループ A.spot の自由記述）を canonical_spot に正規化し、
  lat/lng から気象8地点・海流5地点を Haversine で割当てる。
  閾値外は "その他" / null に退避する。

設計準拠:
  - 設計_W2-2_Bグループ_20260417.md §3, §4
  - 設計_W3-1_統合アーキ_20260417.md §4.1, §4.2, §4.7
  - 設計_W3-2_物理実装方式_20260418.md §3.2

4段正規化パイプライン:
  1) NFKC Unicode正規化
  2) 空白記号除去（半/全角空白、タブ、括弧）
  3) 県名プレフィックス除去（残余が空にならない場合のみ）
  4) 別名辞書（spot_canonical_rules.json の rules）

閾値:
  - 気象  WEATHER_DISTANCE_THRESHOLD_KM = 300 → 超過で "その他"
  - 海流  CURRENT_DISTANCE_THRESHOLD_KM =  50 → 超過で null

タイブレーク:
  - 距離（小数6桁）＞ マスター定義順 ＞ UTF-8バイト順
"""

from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ============================================================
# 閾値定数（W2-2 §3.3）
# ============================================================
WEATHER_DISTANCE_THRESHOLD_KM = 300.0
CURRENT_DISTANCE_THRESHOLD_KM = 50.0

# "その他" sentinel（W3-1 §4.7 案3：B対応表では "その他"）
OTHER_SENTINEL = "その他"

# "不明" sentinel（W7-1 §1, 2026-04-20 追加）
# 自動分類不能（現時点では座標欠落 ＋ 非空 canonical）で、人レビューが必要な状態。
# "その他"（座標ありで閾値超過 = 分類として正解）と区別するための第二の sentinel。
# CI パイプラインの「不明行検出ガード」が nearest_station=="不明" の行を検出したら
# push をブロックする設計（W7-1 §4-2, §4-3）。
UNKNOWN_SENTINEL = "不明"

# 地球半径（km）
EARTH_RADIUS_KM = 6371.0


# ============================================================
# 結果型
# ============================================================
@dataclass
class ClassifyResult:
    """分類結果。lat/lng が None の場合は station/point は None のまま返す。"""

    raw_spot: str
    canonical_spot: str
    nearest_station: Optional[str]  # 気象地点短名 / "その他" / None（座標不明）
    distance_km: Optional[float]
    current_point: Optional[str]  # 海流地点名 / None
    current_distance_km: Optional[float]


# ============================================================
# エンジン本体
# ============================================================
class SpotClassifier:
    """釣り場名と座標から気象/海流地点を分類するエンジン。"""

    def __init__(
        self,
        stations_master_path: str | Path,
        canonical_rules_path: str | Path,
        spot_station_map_path: str | Path | None = None,
    ) -> None:
        """
        Args:
            stations_master_path: stations_master.json のパス
            canonical_rules_path: spot_canonical_rules.json のパス
            spot_station_map_path:
                spot_station_map.json のパス（optional、W7-4 で追加）。
                与えられた場合、spots[].canonical_spot → sea_area のルックアップを構築し
                classify() の海流マッチで sea_area フィルタとして使う。
                None の場合はフラット最近傍（W7-4 以前の後方互換挙動）。
        """
        self._stations_master_path = Path(stations_master_path)
        self._canonical_rules_path = Path(canonical_rules_path)

        with self._stations_master_path.open(encoding="utf-8") as f:
            self._stations = json.load(f)
        with self._canonical_rules_path.open(encoding="utf-8") as f:
            self._rules_doc = json.load(f)

        # マスター定義順を保持したまま配列として持つ（タイブレーク用）
        self._weather_stations: list[dict] = list(self._stations.get("weather_stations", []))
        self._current_points: list[dict] = list(self._stations.get("current_points", []))

        # 別名辞書（from 正規化キー → to canonical）
        self._aliases: dict[str, str] = {
            r["from"]: r["to"]
            for r in self._rules_doc.get("rules", [])
            if r.get("type") == "alias"
        }

        stopwords = self._rules_doc.get("stopwords", {})
        # 長い方から剥離するため長さ降順
        self._prefixes: list[str] = sorted(
            stopwords.get("prefixes", []), key=len, reverse=True
        )
        self._whitespace: list[str] = list(stopwords.get("whitespace", []))
        self._brackets: list[str] = list(stopwords.get("brackets", []))

        # W7-2: substring fallback 用データ
        # 否定リスト（誤マッチ抑制）。初期は空配列、将来 {"contains": "...", "reason": "..."} を追記
        self._negatives: list[dict] = list(self._rules_doc.get("negatives", []))
        # 地点名長さ降順でソート（substring マッチの優先度：長い名前を優先）
        self._stations_by_length: list[dict] = sorted(
            self._weather_stations,
            key=lambda s: len(s["name"]),
            reverse=True,
        )

        # W7-4: 海域階層化
        # canonical_spot → sea_area の lookup。spot_station_map.json の spots[] から構築。
        # 与えられていない場合は空 dict で、classify() は海流マッチをフラット最近傍にフォールバック。
        self._canonical_to_sea_area: dict[str, Optional[str]] = {}
        if spot_station_map_path is not None:
            ssm_path = Path(spot_station_map_path)
            with ssm_path.open(encoding="utf-8") as f:
                ssm = json.load(f)
            for e in ssm.get("spots", []):
                canonical = e.get("canonical_spot")
                sea_area = e.get("sea_area")
                if canonical:
                    self._canonical_to_sea_area[canonical] = sea_area

    # ------------------------------------------------------------
    # 正規化
    # ------------------------------------------------------------
    def normalize_spot_name(self, raw_spot: str) -> str:
        """
        4段正規化パイプライン。

          Step1: NFKC Unicode正規化
          Step2: 空白・括弧除去
          Step3: 県名プレフィックス除去（残余が空にならない場合のみ）
          Step4: 別名辞書で完全一致変換

        空/None 入力 → "" を返す。
        """
        if raw_spot is None:
            return ""
        s = str(raw_spot)

        # Step1: NFKC
        s = unicodedata.normalize("NFKC", s)

        # Step2: 空白・括弧除去
        for ws in self._whitespace:
            s = s.replace(ws, "")
        for br in self._brackets:
            s = s.replace(br, "")

        if s == "":
            return ""

        # Step3: 県名プレフィックス除去（残余が空にならない場合のみ）
        for pref in self._prefixes:
            if s.startswith(pref) and len(s) > len(pref):
                s = s[len(pref):]
                break  # 一度だけ剥離

        # Step4: 別名辞書
        if s in self._aliases:
            s = self._aliases[s]

        return s

    # ------------------------------------------------------------
    # 距離計算
    # ------------------------------------------------------------
    @staticmethod
    def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Haversineで2点間の大円距離（km）を返す。"""
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lng2 - lng1)
        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_KM * c

    # ------------------------------------------------------------
    # 最寄り検索（タイブレーク対応）
    # ------------------------------------------------------------
    def _nearest(
        self, lat: float, lng: float, points: list[dict]
    ) -> tuple[str, float]:
        """
        points から最近傍を返す。タイブレーク規則：
          1. 距離（小数6桁丸め）で小さい方
          2. マスター定義順（先に出現）
          3. 名前のUTF-8バイト順
        """
        best_idx = -1
        best_dist_round = math.inf
        best_raw_dist = math.inf

        for idx, p in enumerate(points):
            d = self.haversine_km(lat, lng, p["lat"], p["lng"])
            d_round = round(d, 6)
            if d_round < best_dist_round:
                best_idx = idx
                best_dist_round = d_round
                best_raw_dist = d
                continue
            if d_round == best_dist_round:
                # タイブレーク2: 既存の方がマスター定義順で先 → 維持
                # （idx は昇順に走査しているので、単に continue で維持される）
                # ただし、名前のUTF-8バイト順も考慮（普通は到達しない）
                cur_name = points[best_idx]["name"].encode("utf-8")
                new_name = p["name"].encode("utf-8")
                if new_name < cur_name:
                    # 万一定義順が逆になっても決定的にする
                    best_idx = idx
                    best_raw_dist = d

        return points[best_idx]["name"], best_raw_dist

    # ------------------------------------------------------------
    # Substring fallback（W7-2, 2026-04-20 追加）
    # ------------------------------------------------------------
    def _substring_match(self, canonical: str) -> Optional[str]:
        """
        canonical に weather_stations の name が含まれる場合、最も長い station name を返す。

        挙動:
          - self._stations_by_length（名前長さ降順）で走査し、最初にヒットした name を採用
          - ただし self._negatives に登録された contains 文字列が canonical に
            含まれていた場合、その station マッチはブロックされ、次の station を試す
          - どれにもヒットしなければ None

        注意:
          - 距離計算は一切行わない（distance_km は呼び出し側で None にする）
          - 座標の有無とは独立な純粋文字列マッチング
        """
        for station in self._stations_by_length:
            name = station["name"]
            if name not in canonical:
                continue
            # 否定リストチェック：canonical に該当 contains が含まれていればブロック
            blocked = False
            for neg in self._negatives:
                contains = neg.get("contains")
                if contains and contains in canonical:
                    blocked = True
                    break
            if blocked:
                continue
            return name
        return None

    # ------------------------------------------------------------
    # メイン分類
    # ------------------------------------------------------------
    def classify(
        self,
        raw_spot: str,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
    ) -> ClassifyResult:
        """
        raw_spot を canonical に正規化し、lat/lng から最近傍を割り当てる。

        戻り値 nearest_station の判定境界（W7-2 §4-1 以降の表）：
          - raw が空文字列 / None                 : None        （空は空のまま扱う）
          - raw あり＋座標あり＋>300km            : "その他"    （閾値超過、分類として正解）
          - raw あり＋座標あり＋≤300km            : station 名
          - raw あり＋座標欠落＋substring hit     : station 名 （W7-2 新、distance_km は None）
          - raw あり＋座標欠落＋substring miss    : "不明"     （W7-1 経由：人レビュー必要）

        戻り値 current_point の判定境界（W7-4 §3-5 sea_area 階層化）：
          - 座標なし                                       : None
          - 座標あり＋canonical → sea_area lookup hit     : sea_area フィルタ後で最近傍
          - 座標あり＋lookup miss（後方互換）              : 全 current_points フラット最近傍
          - 該当海域の current_points が空 or 閾値超過     : None
        """
        canonical = self.normalize_spot_name(raw_spot)

        # 空入力は早期 return（None のまま返す、UNKNOWN にはしない）
        if canonical == "":
            return ClassifyResult(
                raw_spot=raw_spot if raw_spot is not None else "",
                canonical_spot="",
                nearest_station=None,
                distance_km=None,
                current_point=None,
                current_distance_km=None,
            )

        # 座標欠落：haversine が不能なので substring fallback を試す（W7-2）。
        # ヒットすれば station 名を返し、ヒットしなければ UNKNOWN_SENTINEL を返す。
        # 注意: ここに来た時点で座標なし → 海流地点（current_point）は決定不能なので None のまま
        if lat is None or lng is None:
            ss = self._substring_match(canonical)
            if ss is not None:
                return ClassifyResult(
                    raw_spot=raw_spot,
                    canonical_spot=canonical,
                    nearest_station=ss,
                    distance_km=None,  # substring match では距離計算していない
                    current_point=None,
                    current_distance_km=None,
                )
            return ClassifyResult(
                raw_spot=raw_spot,
                canonical_spot=canonical,
                nearest_station=UNKNOWN_SENTINEL,
                distance_km=None,
                current_point=None,
                current_distance_km=None,
            )

        # 気象8地点
        w_name, w_dist = self._nearest(lat, lng, self._weather_stations)
        if w_dist > WEATHER_DISTANCE_THRESHOLD_KM:
            nearest_station = OTHER_SENTINEL
        else:
            nearest_station = w_name

        # 海流地点（W7-4 で sea_area 階層化）
        # canonical → sea_area lookup が hit した場合は該当海域の current_points のみで最近傍、
        # hit しない場合はフラット最近傍（W7-4 以前の後方互換挙動）
        sea_area = self._canonical_to_sea_area.get(canonical)
        if sea_area:
            filtered_current = [
                p for p in self._current_points
                if p.get("sea_area") == sea_area
            ]
        else:
            filtered_current = self._current_points

        if not filtered_current:
            # 該当海域に 1 点も無い（例: sea_area='足摺沖' だが stations_master に足摺沖
            # current_point が未登録など）→ 海流割当不能
            current_point: Optional[str] = None
            current_distance_km: Optional[float] = None
        else:
            c_name, c_dist = self._nearest(lat, lng, filtered_current)
            if c_dist > CURRENT_DISTANCE_THRESHOLD_KM:
                current_point = None
                current_distance_km = None
            else:
                current_point = c_name
                current_distance_km = c_dist

        return ClassifyResult(
            raw_spot=raw_spot,
            canonical_spot=canonical,
            nearest_station=nearest_station,
            distance_km=w_dist,
            current_point=current_point,
            current_distance_km=current_distance_km,
        )


# ============================================================
# CLI（動作確認用）
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SpotClassifier 単発テスト")
    parser.add_argument("--stations", required=True, help="stations_master.json のパス")
    parser.add_argument("--rules", required=True, help="spot_canonical_rules.json のパス")
    parser.add_argument(
        "--spot-map",
        default=None,
        help="spot_station_map.json のパス（optional、W7-4 sea_area フィルタ用）",
    )
    parser.add_argument("--spot", required=True, help="raw spot 文字列")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lng", type=float, default=None)
    args = parser.parse_args()

    clf = SpotClassifier(args.stations, args.rules, spot_station_map_path=args.spot_map)
    r = clf.classify(args.spot, args.lat, args.lng)
    print(
        "raw={raw!r}\n"
        "canonical={can!r}\n"
        "nearest_station={st!r} (dist={wd})\n"
        "current_point={cp!r} (dist={cd})".format(
            raw=r.raw_spot,
            can=r.canonical_spot,
            st=r.nearest_station,
            wd=r.distance_km,
            cp=r.current_point,
            cd=r.current_distance_km,
        )
    )
