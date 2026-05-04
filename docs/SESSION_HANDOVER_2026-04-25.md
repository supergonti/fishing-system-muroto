# Session Handover - fishing-system-muroto
## 2026-04-25 セッション引継ぎ書

このドキュメントは、2026-04-25 セッションで実施した内容と、次セッションで取り組むべきタスクの引継ぎ用です。新しいセッションで Claude にこのファイルを読ませることで、即座に作業継続できるよう設計されています。

---

## 0. システム概要（前提知識）

**fishing-system-muroto** は室戸沖の遊漁船 (muroto1/2/3) の釣果データを管理する Web システムです。

- **本番URL**: https://supergonti.github.io/fishing-system-muroto/
- **GitHub**: https://github.com/SuperGonti/fishing-system-muroto
- **ローカル本物リポジトリ**: `C:\Dev\fishing-system Muroto\` （日常運用はここ）
- **ユーザー**: Gonti さん（GUI 主体、ダブルクリック完結を好む、コマンドライン苦手）

### システム構成

```
[人]                                  [GitHub Actions = 自動]
─────────────────────              ─────────────────────────
①19列CSV を成形                  →   ②ingest_dropins.yml
   fishing_data_<boat_id>.csv          master_catch.csv (28列) に統合
③drop_inbox/ に保存               →   _archived/ に元CSV を退避
④push_dropins.bat ダブルクリック  →  ⑤sync_after_master_push.yml
                                       派生CSV3本を再生成
                                  →   HTML が派生CSV を fetch して表示
[人]
─────────────
⑥ analyze_engine.py を手動実行 → analysis_*.json (解析画面用)
⑦ forecast_data.json 手動更新 → 出船判断画面用
```

### 主要画面 4つ

| 画面 | データソース | 更新方法 |
|---|---|---|
| 釣果DB | `derived/all/fishing_integrated.csv` | drop_inbox 経由で自動 |
| 解析DB | `data/analysis/analysis_*.json` | analyze_engine.py 手動実行 |
| 潮流DB | `shared/current/muroto/...csv` | 別途運用 |
| 出船判断 | `data/forecast/forecast_data.json` | fetch_forecast.py 手動実行 |

---

## 1. 本セッションで完了したこと

### 1-A. 残骸削除 + push 用 bat 作成（前半フェーズ）

**コミット**: `9e1f56d` `6921ddf`

- リポジトリトップに残置されていた `fishing_data*.csv` 3本（`_archived/` と sha256 完全一致の取込済残骸）を `git rm` で削除
- `areas/push_dropins.bat` を新規作成（ダブルクリックで git add → 3層スキャン → commit → push まで完結）

### 1-B. bat の改修（複数の罠を踏んで対処）

**コミット**: `55d2b4a` `e4a6f75` `37dcdc7`

| 罠 | 対処 |
|---|---|
| UTF-8 で日本語が文字化け | **CP932 (Shift-JIS) + CRLF** で保存（`chcp 65001` 不可） |
| `bash` が PATH に無い | Git for Windows の標準パス3か所を自動検出 |
| `git push` が worktree のフィーチャーブランチで失敗 | `git push origin HEAD:main` で固定化 |
| `else if` の cmd 非互換 | `goto` でフラット化 |
| `if/for/if` の3段ネスト parse error | サブルーチン化（`call :label`/`exit /b`） |
| `check_secrets.py` の cp932 絵文字 UnicodeEncodeError | `set PYTHONIOENCODING=utf-8` |

### 1-C. bat の最終配置

`areas/push_dropins.bat` → **`areas/muroto/push_dropins.bat`** に移設（muroto 海域専用化、将来別海域追加時はその海域配下に複製）

### 1-D. replace（全置換）モードの実装

**コミット**: `47c4caf` `2c8a45f` `27c6de9` `9eca2b9`

`ingest_dropins.py` に boat_id 単位の全置換モードを追加。3 コミット構成：

1. **`shared/engines/ingest_dropins.py`** に新規ヘルパー4関数 + `ingest_area()` 改修
   - `backup_master()` / `filter_master_excluding_boats()` / `detect_replace_markers()` / `check_row_count_ratio()`
   - `--mode {add|replace}` / `--force` オプション追加
2. **`.github/workflows/ingest_dropins.yml`** にマーカー検出ステップ追加
3. **`areas/muroto/push_dropins.bat`** に `[1] add / [2] replace / [3] cancel` モード選択 + 50% 警告 + 削除プレビュー追加

### 1-E. muroto1 の全置換テスト + date 罠の発覚と修復

**コミット**: `bdfe9c4`（add 投入で重複発生）→ `f04237e`（replace 投入）→ `e1ac3a0`（date 修復）

ユーザーが Excel で編集した CSV を投入 → date が `YYYY/M/D` 形式に化け、condition_db (ハイフン形式) との JOIN が外れて天気データが全部空欄になる事故。

**復旧**: master_catch.csv の muroto1 行 858 件の date / entered_at を Python スクリプトで一括正規化。

### 1-F. muroto2/3 ダミーデータ削除

**コミット**: `f04237e` ＋ CI force=true 再実行 → `6748c3b`（master 更新）

muroto2/3 はダミーデータだったため、最古行1件だけ残した CSV を生成 → bat で全置換。CI 50% ガード fail（想定通り）→ `gh workflow run ... -f force=true` で再実行 → 成功。

**結果**: master 1203行 → 860行（muroto1=858 / muroto2=1 / muroto3=1）

### 1-G. 派生CSV / analysis / forecast の最終化

- `sync_after_master_push.yml` 手動発火 → 派生CSV3本を 861 行に再生成
- `analyze_engine.py` を 4本実行（合算 + 船別3）→ analysis_*.json 全更新（**コミット `96768c6`**）
- `fetch_forecast.py` 手動実行 → `forecast_data.json` 更新（出船判断画面の日付が 2026-04-24 → 最新化）

---

## 2. 完成したシステムの運用手順（ユーザー向け）

### 2-1. 釣果データを **追加** したい時

1. 19列 CSV を `areas/muroto/drop_inbox/fishing_data_<boat_id>.csv` に保存
   - **必ずメモ帳/VSCode で編集**（Excel/Google Sheets 厳禁、日付が壊れる）
   - date 列は **`YYYY-MM-DD`** 形式
2. `areas/muroto/push_dropins.bat` をダブルクリック
3. `[1]`（追記のみ）を選択 → Enter
4. 自動で commit & push → CI 完了まで 3〜5 分待つ
5. 本番URL リロード

### 2-2. 釣果データを **全置換** したい時（テストデータ削除等）

1. 同上で CSV を保存（**最新全件**を入れる）
2. bat ダブルクリック → `[2]`（全置換）を選択
3. 50% 警告が出たら判断（意図通りなら y）
4. 削除予定 record_id プレビューを確認 → 最終 y で実行
5. CI で 50%ガード fail する場合 → Claude に「force で再実行して」と依頼
6. その後の sync 手動発火 + analyze_engine 実行も Claude 依頼

### 2-3. 解析画面の更新（analyze_engine 手動実行）

```bash
cd "C:/Dev/fishing-system Muroto"
rm -f areas/muroto/data/analysis/*.json
for target in "result --boats=" "muroto1 --boats=muroto1" "muroto2 --boats=muroto2" "muroto3 --boats=muroto3"; do
  name="${target%% *}"
  boats="${target#* }"
  PYTHONIOENCODING=utf-8 python -m shared.engines.analyze_engine \
    --db1 "C:/Dev/fishing-system Muroto/areas/muroto/data/derived/all/fishing_muroto_v1.csv" \
    --db2 "C:/Dev/fishing-system Muroto/shared/current/muroto/muroto_offshore_current_all.csv" \
    --db3 "C:/Dev/fishing-system Muroto/shared/weather/fishing_condition_db.csv" \
    --out "C:/Dev/fishing-system Muroto/areas/muroto/data/analysis/analysis_$name.json" \
    $([ "${boats#--boats=}" != "" ] && echo "$boats") \
    --no-html
done
git add areas/muroto/data/analysis/ && git commit -m "..." && git push origin main
```

### 2-4. 出船判断の更新（fetch_forecast 手動実行）

`fetch_forecast.py` を実行して `forecast_data.json` を更新 → commit & push。

---

## 3. CI ワークフローの仕様

### 3-1. `ingest_dropins.yml`（drop_inbox → master）

- **トリガー**: `areas/**/drop_inbox/fishing_data_*.csv` または `.replace_*` の push
- **mode 自動判定**: drop_inbox に `.replace_<boat_id>` マーカーがあれば `replace`、無ければ `add`
- **workflow_dispatch inputs**: `area_id` / `force` (50%ガード override 用)

### 3-2. `sync_after_master_push.yml`（master → 派生CSV3本）

- **トリガー**: `areas/**/data/master_catch.csv` の push
- **⚠ 重要な制約**: GitHub の `GITHUB_TOKEN` 仕様で **CI 自動コミットでは発火しない**
  → `ingest_dropins.yml` の自動 commit 後は **手動発火が必要**
- **手動発火**: `gh workflow run sync_after_master_push.yml -R supergonti/fishing-system-muroto -f area_id=muroto`

### 3-3. CI 化されていないもの（手動実行が必要）

- `analyze_engine.py` → `analysis_*.json` 4本
- `fetch_forecast.py` → `forecast_data.json`

---

## 4. 既知の罠（次セッションで覚えておくべき）

### 4-1. CSV 編集ツールの罠

| ツール | 安全性 | 備考 |
|---|---|---|
| メモ帳 | ✅ | テキストとして扱う |
| VSCode | ✅ | UTF-8 BOM 保持 |
| サクラエディタ | ✅ | |
| **Excel** | ❌ | **日付列を `YYYY/M/D` に勝手に変換 → 天気 JOIN 失敗** |
| Google Sheets | ❌ | 同上 |

### 4-2. cmd / bat の罠

- **bat ファイルは CP932 + CRLF で保存**（`chcp 65001` を最初に置いても遅い）
- **`else if` は cmd 非互換**（`goto` でフラット化）
- **3段以上の if/for ネストは parse error**（サブルーチン化）
- **`git push` 引数なしは worktree フィーチャーブランチで失敗**（`git push origin HEAD:main` で固定）

### 4-3. cp932 絵文字 UnicodeEncodeError

- `check_secrets.py` の `🔍`、`analyze_engine.py` の `✅` で発生
- **回避**: `PYTHONIOENCODING=utf-8` 環境変数

### 4-4. CI 連鎖の制約

- `actions/checkout@v4` 経由の CI 自動 push は別 workflow を起動しない（GITHUB_TOKEN 仕様）
- `ingest_dropins` 完了後は `sync_after_master_push` を **手動発火**

### 4-5. ファイルロック

- `analyze_engine.py` で既存 JSON への上書き時に `PermissionError` 発生
- **回避**: 実行前に `rm -f areas/muroto/data/analysis/*.json`

---

## 5. 次セッションで取り組むべきタスク（優先度順）

### 🥇 タスク1: `ingest_dropins.py` に date 自動正規化を追加（最優先）

**Why**: 本セッションで最大の事故（天気データ消失）の根本原因を断つ。Excel 編集ユーザーでも安全に運用できる。

**実装場所**: `shared/engines/ingest_dropins.py::read_dropin_csv()` または `row_to_master_record()`

**ロジック**:
```python
def normalize_date(s: str) -> str:
    """YYYY/M/D, YYYY-M-D 等を YYYY-MM-DD に正規化"""
    if not s: return s
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$", s.strip())
    if m:
        y, mo, da = m.groups()
        return f"{y}-{int(mo):02d}-{int(da):02d}"
    return s
```

**追加検討**: time 列の正規化（`9:20` → `09:20`）も同時実装するか判断。

**テスト**:
- 既存の muroto1 の date は ISO 8601 のままなので record_id が変わらないことを確認（uuid5 一致）
- Excel 由来の `2026/3/31` を投入 → 自動的に `2026-03-31` に変換されて取り込まれる

### 🥈 タスク2: `forecast_data.json` の CI 化

**Why**: 出船判断画面が現在「人が手動で更新」状態。毎日 06:00 等で自動更新したい。

**実装案**: `.github/workflows/forecast_update.yml` を新設
- スケジュール: `cron: "0 21 * * *"` (UTC 21:00 = JST 06:00)
- `python fetch_forecast.py` 実行
- `forecast_data.json` を commit & push

**注意**: `GITHUB_TOKEN` 制約で別 workflow が連鎖しないが、forecast はそれ単体で完結するので問題なし。

### 🥉 タスク3: `ingest_dropins.yml` 内で `emit_all` を統合呼び出し

**Why**: `sync_after_master_push.yml` の手動発火を不要にする。CI 連鎖の制約を回避。

**実装案**: `ingest_dropins.yml` の最後に `emit_all` を呼ぶステップを追加（master 更新があれば派生CSV も同一 workflow 内で再生成）。

**メリット**: ユーザー / Claude の手動発火操作が消える。
**デメリット**: ワークフローが肥大化。代替案として共通スクリプト化も検討。

### 4位: `analyze_engine.py` の CI 化

**Why**: master 更新時に解析画面も自動最新化。

**実装場所**: `sync_after_master_push.yml` の最後に analyze_engine の 4本実行ステップを追加（または独立 workflow）。

**注意**: 1 本あたり数秒で完了するが、合算 + 船別3 で4本実行 → 30秒程度。

### 5位: 絵文字の ASCII 化

**Why**: cp932 環境での UnicodeEncodeError を恒久解消。`PYTHONIOENCODING=utf-8` ワークアラウンドを撤廃可能。

**対象**:
- `C:\Claude\tools\check_secrets.py` の `🔍` → `[scan]`
- `shared/engines/analyze_engine.py` の `✅` → `[OK]`

**注意**: `check_secrets.py` は別リポジトリ管理（C:\Claude\tools\）。修正は別タスク扱い。

### 6位: docs/ の整備

本セッションで「文書化は今回しない」方針だったが、運用が確立したので運用手順書（このファイル含む）の整備が次の自然な流れ。

---

## 6. 重要なコミット履歴（main ブランチ）

```
96768c6 chore(analysis): muroto2/3 ダミー削除と date 修復後の analysis_*.json 再生成
xxxxxxx forecast_data.json 更新（最新化）
6748c3b ingest_dropins: 2026-04-25T14:38:59Z (CI 自動、muroto2/3 ダミー削除後)
f04237e feat(catch): drop_inbox 全置換 [replace] muroto2 /muroto3
ce01b18 emit派生CSV再生成 (Muroto)
e1ac3a0 fix(data): muroto1 行の date / entered_at を ISO 8601 に正規化
xxxxxxx ingest_dropins (CI 自動、muroto1 force replace 後)
6fba270 feat(catch): drop_inbox 全置換 [replace] muroto1
9eca2b9 fix(bat): cmd 入れ子限界対策で push_dropins.bat をサブルーチン化
27c6de9 feat(bat): push_dropins.bat に replace モードプロンプトと安全装置を追加
2c8a45f ci(ingest): replace マーカー検出と mode/force 引数渡しを追加
47c4caf feat(ingest): drop_inbox 全置換モードを追加（boat_id 単位 + 安全装置）
37dcdc7 chore(ops): push_dropins.bat を areas/muroto/ 配下に移設
e4a6f75 fix(ops): bash 検出を else if → goto に変更
55d2b4a fix(ops): push_dropins.bat に bash 自動検出と main 直接 push を追加
6921ddf feat(ops): drop_inbox 釣果データ自動 push 用 bat を追加
9e1f56d chore: 取込済残骸 fishing_data*.csv を削除
7905fd8 最終チェック Phase 1: 13ファイル品質改善（前回セッション最終コミット）
```

---

## 7. メモリファイル一覧（次セッションで自動読込される）

`C:\Users\super\.claude\projects\C--Dev-fishing-system-Muroto\memory\` 配下：

| ファイル | 種別 | 内容 |
|---|---|---|
| `MEMORY.md` | index | 一覧 |
| `user_profile.md` | user | Gonti さんの作業スタイル |
| `feedback_push_workflow.md` | feedback | main 直接 push 慣習 |
| `feedback_windows_bat.md` | feedback | bat は CP932 + CRLF |
| `reference_check_secrets_bug.md` | reference | cp932 絵文字問題（analyze_engine も同種追記） |
| `project_replace_mode_operation.md` | project | replace モード完全運用フロー |
| `feedback_csv_excel_pitfall.md` | feedback | Excel 編集禁止 |
| `project_forecast_manual_update.md` | project | forecast の手動更新手順 |

これらは Claude が自動的に読み込むため、新セッションを開始するだけで本セッションのコンテキストが復元されます。

---

## 8. ライフログ

`C:\Claude\LifeLog\daily_mix\20260425_all_1759.md` に本セッションの全体サマリが記録されています（[IT] カテゴリで2セクション）。

---

## 9. 推奨：次セッション開始時の最初のアクション

1. このファイル `docs/SESSION_HANDOVER_2026-04-25.md` を Claude に読ませる
2. 本物のリポジトリの状態を確認:
   ```bash
   cd "C:/Dev/fishing-system Muroto"
   git pull origin main
   git log --oneline -5
   ```
3. 取り組むタスクを「🥇 ingest_dropins.py に date 自動正規化を追加」から指定する

---

## 10. ファイル / ディレクトリ参照

### 改修対象（次タスク）

- `shared/engines/ingest_dropins.py` — date 正規化追加
- `shared/engines/_schema.py` — 必要なら定数追加（FISHING_DATA_COLUMNS は変更不要）
- `.github/workflows/ingest_dropins.yml` — emit_all 統合ステップ追加検討
- 新規: `.github/workflows/forecast_update.yml` — forecast 自動更新

### 参照のみ

- `shared/engines/csv_writer.py` — BOM/CRLF 読み書き
- `shared/engines/emit_all.py` / `emit_fishing_*.py` — 派生CSV生成
- `shared/engines/analyze_engine.py` — 解析エンジン（絵文字 ASCII 化対象）
- `shared/meta/boats_master.json` / `areas_master.json` — メタ情報
- `areas/muroto/push_dropins.bat` — ユーザー操作の入口
- `C:\Claude\tools\check_secrets.py` — 別リポジトリ（絵文字 ASCII 化対象）

### データファイル

- `areas/muroto/data/master_catch.csv` — マスター 28列 (現在 860 行)
- `areas/muroto/data/derived/all/*.csv` — 派生3本 (861 行)
- `areas/muroto/data/analysis/analysis_*.json` — 解析4本（最新: 2026-04-25 23:48）
- `areas/muroto/data/_backups/master_catch_*.csv` — replace 時の自動バックアップ
- `areas/muroto/drop_inbox/_archived/` — 取込済CSV履歴
- `data/forecast/forecast_data.json` — 出船判断データ

---

**次セッションの方、よろしくお願いします！**
**作業効率のため、まず「タスク1（date 自動正規化）から進めます」と言って始めるのが推奨です。**
