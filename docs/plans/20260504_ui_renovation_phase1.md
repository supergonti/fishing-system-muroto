# UI 改修 Phase 1 計画書

**作成日**: 2026-05-04
**対象リポジトリ**: `supergonti/fishing-system-muroto`
**実装環境**: sandbox-01 Claude Code (auto モード)
**併読**: `docs/COWORK_HANDOFF_GUIDE.md`

**失敗時の方針**: D（自己回復・標準）。同一エラー最大 5 回まで自走。戦略判断や人間限定作業が必要なら停止して報告。

---

## 1. 背景と目的

自動更新 workflow 移植プロジェクト（前計画 `20260504_workflow_migration.md`）が完了し、4 画面が当日 or 前日のデータで自動更新される状態になった。次フェーズとして UI 改修 Phase 1 で 4 画面に運用上の改善を入れる：

- **viewer.html**（船選択画面）: 初期表示で全船選択になっており、室戸1（メイン船）に絞った導線にしたい
- **fishingdata.html**（釣果DB）: 魚種・釣り場ドロップダウンを解析DB と同じグループ式に揃えたい
- **muroto_fishing_analysis.html**（解析DB）: 魚種解析の積み上げ化、TL 系タブの期間指定統一など複合改修
- **muroto_offshore_current.html**（潮流DB）: ダッシュボードを初期折りたたみにして縦長を抑える

---

## 2. 現状分析

### 2-1. 対象ファイル

| 画面 | ファイル |
|---|---|
| 船選択 | `viewer.html`（リポジトリ直下） |
| 釣果DB | `areas/muroto/ui/fishingdata.html` |
| 解析DB | `areas/muroto/ui/muroto_fishing_analysis.html` |
| 潮流DB | `areas/muroto/ui/muroto_offshore_current.html` |

### 2-2. 共通参照

- グループ式ドロップダウンの参照元は `muroto_fishing_analysis.html` 内の SPECIES_GROUPS / SPOT_GROUPS / buildGroupedCBList 関数
- CSS は `.cb-group / .cb-group-header / .cb-group-arrow / .cb-group-toggle / .cb-group-count / .cb-group-chips / .cb-chip`

---

## 3. タスク分解と Wave 設計

### Wave 1: HTML 4 ファイル改修（並列度 4）

| Worker | タスク | ファイル |
|---|---|---|
| W1 | T-1: 初期選択を室戸1限定 + 確定ボタン | `viewer.html` |
| W2 | T-2: 魚種・釣り場 DDL をグループ式に | `areas/muroto/ui/fishingdata.html` |
| W3 | T-3: 魚種解析 + TL 系タブの大規模改修（内部シーケンシャル） | `areas/muroto/ui/muroto_fishing_analysis.html` |
| W4 | T-4: ダッシュボードを初期折りたたみ | `areas/muroto/ui/muroto_offshore_current.html` |

ワーカープロンプトは本セッション内で組み立てる（仕様詳細はユーザープロンプトを引用）。

---

## 4. T-1 仕様（viewer.html）

- line 174 付近 `initSelectedBoats()` の selectedBoatIds 初期化を変更
  - 変更前: `selectedBoatIds = new Set(boats.map(b => b.boat_id));`
  - 変更後: `const defaultBoat = boats.find(b => b.boat_id === 'muroto1') || boats[0];`
           `selectedBoatIds = new Set(defaultBoat ? [defaultBoat.boat_id] : []);`
- ② パネル内 `boat-summary` 直下に確定ボタンを追加
  - HTML / CSS / JS は本プロンプト「Wave 1 詳細」に明記したコード片をそのまま採用
  - `goToCatchDB()` は ID `nav-fishingdata` の href へ遷移

---

## 5. T-2 仕様（fishingdata.html）

- 魚種ドロップダウン / 釣り場ドロップダウンを解析DB と同じ「折りたたみ + グループ一括 + 個別」式に変更
- 参照元: `muroto_fishing_analysis.html`
  - SPECIES_GROUPS（line 993-1010 付近）
  - SPOT_GROUPS（line 796-803 付近）
  - buildGroupedCBList 関数（line 857 付近）
  - 関連 CSS（.cb-group 系）
- **既存のフィルタ / 検索 JS ロジックは温存**、UI 部分のみ差し替え
- 並び順は SPECIES_GROUPS / SPOT_GROUPS の順序通り

---

## 6. T-3 仕様（muroto_fishing_analysis.html）

### 6-1. 魚種解析タブ
- 複数魚種選択時（2 種以上）:
  - 「フィルター適用中＊＊件」下の「釣果日数 / 釣果記録」指標群をタブ最下部へ移動
  - 棒グラフを「積み上げ」表示に変更（横並び廃止）
- グラフ並び順:
  月別釣果数 → 水温帯別釣果分布 → 水温トレンド → 潮汐別釣果分布 → 流速帯別釣果分布 → 流れの方向別釣果分布 → 以下変更なし

### 6-2. 水温TLタブ
- 期間指定方式を全面変更:
  - 旧: 期間 YYYY/MM/DD ～ YYYY/MM/DD + プリセット + □流速も表示
  - 新: 日付 YYYY/MM/DD から以前の [期間表示▼] + □流速も表示
- 動作: 日付ピッカー 1 個。指定日からさかのぼって選択期間分を表示
- 期間表示: 1か月 / 3か月 / 6か月 / 1年 / 2年 / 3年 / 4年（7 段）
- 初期: 日付=今日（システム日付、データ無しでも空グラフでOK）、期間=1年

### 6-3. 潮流TLタブ / 月齢TLタブ / 潮汐TLタブ
- 同じ期間指定機構に統一
- 月齢TL タブの位置を「潮汐TLタブの右」へ移動
- 潮汐TLタブの「潮汐種別×月齢帯 釣果分布」グラフを「釣果」と「大物」の積み上げ棒グラフに変更（既に積み上げなら何もしない）

---

## 7. T-4 仕様（muroto_offshore_current.html）

- line 375 付近 sectionOpen を変更
  - 変更前: `const sectionOpen = { dashboard: true, viewer: true, missing: true };`
  - 変更後: `const sectionOpen = { dashboard: false, viewer: true, missing: true };`
- line 239 付近の dashboard セクションヘッダ `aria-expanded` を `"true"` → `"false"`
- line 241 付近のトグル表示を初期 `▶ 展開` に
- dashboardBody の class に `collapsed` を初期付与（または applySectionState で初期確実化）

---

## 8. 検証フェーズ

1. 各 HTML の構文チェック: `python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('<file>').read()); print('OK')"`
2. 4 個別コミット + 計画書/ガイドコミットの計 5 コミットを作成
3. `bash /home/supergonti/security/scan_3layer.sh "$(pwd)"` 実行（無ければ skip 可）
4. `git push origin main`
5. ~90 秒待機（GitHub Pages 自動デプロイ）
6. curl で公開ページに改修内容が反映されているか grep
7. 反映漏れがあれば方針 D で再修正

---

## 9. 完了基準

- ☐ T-1 viewer.html: 室戸1 限定 + 確定ボタン反映
- ☐ T-2 fishingdata.html: 魚種/釣り場 DDL グループ式
- ☐ T-3 muroto_fishing_analysis.html: 5 タブの仕様反映
- ☐ T-4 muroto_offshore_current.html: ダッシュボード初期折りたたみ
- ☐ 5 コミット push 済 + scan_3layer.sh exit 0
- ☐ 公開ページ 4 画面で改修内容を curl 検証
- ☐ 計画書 §11 に実施結果サマリ追記
- ☐ ssh-agent から個人鍵削除

---

## 10. 関連資料

- 自動更新 workflow 移植: `docs/plans/20260504_workflow_migration.md`
- 共通規約: `docs/COWORK_HANDOFF_GUIDE.md`

---
