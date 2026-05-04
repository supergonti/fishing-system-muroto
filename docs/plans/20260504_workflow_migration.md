# 自動更新 Workflow 移植・改修 計画書

**作成日**: 2026-05-04
**対象リポジトリ**: `supergonti/fishing-system-muroto`
**ローカルパス**: `C:\Dev\fishing-system Muroto\`（Windows 側）／ `~/workspace/fishing-system-muroto/`（sandbox-01 側、これから clone）
**実装環境**: ミニPC `sandbox-01` 上の Claude Code（auto モード、Task tool でエージェント並列）
**計画担当**: Cowork Claude（本書を作成）
**実装担当**: sandbox-01 Claude Code（指揮役 + ワーカー）
**併読（必須）**: `docs/COWORK_HANDOFF_GUIDE.md`（共通規約）／ `docs/SESSION_HANDOVER_2026-04-25.md`（前セッション知見）／ `C:\Claude\CLAUDE.md`（プロジェクト共通）

**失敗時の方針（本計画書では方針 C：テスト的）**: 1 ステップでも失敗したら **再試行せず**、その時点の状態を保存して Gonti さんに即座に報告する。今回は Cowork → sandbox-01 受け渡しの初回テストを兼ねるため、暴走防止を優先する。次回以降の計画書では方針 A/B も検討する。

---

## 0. Phase 0: 人間作業集約（Gonti さん）

**ここは Cowork Claude ではなく Gonti さんが手動で実施する**。Phase 0 が完了するまで Claude Code には起動指示を出さない。各項目の完了マーカー □ にチェックが入った状態で初めて実装フェーズに進む。

実施手順は `docs/COWORK_HANDOFF_GUIDE.md §4` に詳述。

### G-1. sandbox-01 にログインできることを確認

**目的**: 以降の全作業の前提。

**実行**:
```bash
ssh sandbox-01
# プロンプトが出れば OK、exit で抜けて次へ
```

**NG 時**: ノートPC の SSH config を確認、ミニPC の電源 / WiFi を確認。

**完了マーカー**: ☐

---

### G-2. fishing-system-muroto を sandbox-01 上で最新化

**目的**: 計画書を含むリポジトリを sandbox-01 で利用可能にする。

**実行**:
```bash
ssh sandbox-01
cd ~/workspace
[ ! -d fishing-system-muroto ] && git clone git@github.com:supergonti/fishing-system-muroto.git
cd fishing-system-muroto
git fetch origin
git checkout main
git pull origin main
```

**確認**:
```bash
ls docs/plans/20260504_workflow_migration.md  # 本計画書
ls docs/COWORK_HANDOFF_GUIDE.md               # 共通ガイド
```

両方が存在すれば OK。Cowork から push されていない場合は Gonti さんがまず Cowork 側で commit + push する：
```cmd
cd "C:\Dev\fishing-system Muroto"
git pull origin main
git add docs/plans/ docs/COWORK_HANDOFF_GUIDE.md
bash "C:/Claude/tools/scan_3layer.sh" "C:/Dev/fishing-system Muroto"
git commit -m "docs: workflow移植計画書と受け渡しガイドを追加"
git push origin main
```

**NG 時**: clone が失敗するなら SSH 鍵が agent にロードされていない（G-4 を先に実施）。

**完了マーカー**: ☐

---

### G-3. SSH 個人鍵 `id_ed25519_github` の存在確認

**目的**: push に使う個人鍵が sandbox-01 にあること。

**実行**:
```bash
ssh sandbox-01
ls -l ~/.ssh/id_ed25519_github ~/.ssh/id_ed25519_github.pub
```

両方表示されれば OK。

**NG 時**: 鍵が無い場合は移行作業が漏れている。`C:\Claude\Mini PC installation steps\` の Phase 1/2 構築手順を再確認、必要なら別途 SSH 鍵セットアップを実施する（**本計画はそこから先には進まない**）。

**完了マーカー**: ☐

---

### G-4. ssh-agent に個人鍵をロード（push 用、一時的）

**目的**: 通常 shelved 状態の個人鍵を、本作業中だけ ssh-agent に追加する。

**実行**:
```bash
ssh sandbox-01
ssh-add ~/.ssh/id_ed25519_github
ssh-add -l   # ed25519 鍵が表示されること
```

**確認**:
```bash
ssh -T git@github.com
# "Hi supergonti! You've successfully authenticated, but GitHub does not provide shell access." が出れば OK
```

**NG 時**: passphrase 入力ミス → 再実行。鍵が認識されない → ファイル権限を `chmod 600` で確認。

**完了マーカー**: ☐

**重要**: 本作業完了後（§9 完了基準まで進んだら）必ず `ssh-add -d ~/.ssh/id_ed25519_github` で外す。

---

### G-5. 旧リポジトリ `fishing-system` を read-only で clone（参照用）

**目的**: sandbox-01 Claude Code が旧 workflow を参照できるようにする。push しないので HTTPS で OK。

**実行**:
```bash
ssh sandbox-01
cd ~/workspace
[ ! -d fishing-system-old ] && \
  git clone https://github.com/supergonti/fishing-system.git fishing-system-old
cd fishing-system-old && git pull origin main
```

**確認**:
```bash
ls ~/workspace/fishing-system-old/.github/workflows/
# update-forecast.yml / update_data.yml / sync_after_current_update.yml /
# rebuild_master.yml / sync_after_master_push.yml の 5 本が見えること
```

**NG 時**: 名前を間違えていないか確認。`fishing-system-old` という名前で clone する点に注意（`fishing-system` だと Muroto の親ディレクトリと衝突する可能性）。

**完了マーカー**: ☐

---

### G-6. CMEMS Secrets を `fishing-system-muroto` に投入（Web UI 経由）

**目的**: `update_data.yml`（海流データ自動取得）が動くために必要。値は GitHub の仕様上 **コピー不可**（一度設定すると読み取りできない）ので毎回投入が必要。

**前提**: `data.marine.copernicus.eu` のユーザー ID とログインパスワードが手元にあること。これらが `CMEMS_USERNAME` / `CMEMS_PASSWORD` の値そのもの（外部発行のトークンなどは不要）。

**手順（Web UI、第一選択）**:

1. ブラウザで以下を開く（GitHub にログインした状態で）:
   ```
   https://github.com/supergonti/fishing-system-muroto/settings/secrets/actions
   ```

2. 画面右上の **「New repository secret」** ボタンを押す

3. **`CMEMS_USERNAME` を投入**:
   - **Name**: `CMEMS_USERNAME`
   - **Secret**: data.marine.copernicus.eu のユーザー ID を貼り付け
   - **Add secret** ボタン

4. もう一度 **「New repository secret」** ボタンを押す

5. **`CMEMS_PASSWORD` を投入**:
   - **Name**: `CMEMS_PASSWORD`
   - **Secret**: data.marine.copernicus.eu のログインパスワードを貼り付け
   - **Add secret** ボタン

6. 一覧画面で **両方が表示されている** ことを確認（値は表示されない、これは仕様）。

**確認（任意、gh CLI 認証済みなら）**:
```bash
gh secret list -R supergonti/fishing-system-muroto
# CMEMS_PASSWORD と CMEMS_USERNAME の 2 行が出れば OK
```

**注意・セキュリティ**:
- パスワードはチャット履歴・ターミナル履歴・スクリーンショットに残さない
- 誤って漏らした場合は Copernicus Marine 側でパスワードを変更してから再投入
- これら 2 つの Secret は repository scope（このリポジトリでのみ参照される）

**NG 時**:
- ボタンが見つからない: GitHub にログインしているか・リポジトリの管理者権限があるか確認
- 投入後にも一覧に出てこない: 名前のスペル誤り（半角・大文字、`CMEMS_USERNAME` / `CMEMS_PASSWORD` 完全一致）

**代替手順（gh CLI、対話入力推奨）**:

シェル履歴に値を残したくないので `--body` は使わず対話入力で：
```bash
gh secret set CMEMS_USERNAME -R supergonti/fishing-system-muroto
# プロンプトでユーザー ID を入力
gh secret set CMEMS_PASSWORD -R supergonti/fishing-system-muroto
# プロンプトでパスワードを入力
```

**完了マーカー**: ☐

---

### G-7. Claude Code が起動できることを確認

**目的**: 実装フェーズで使うツールの稼働確認。

**実行**:
```bash
ssh sandbox-01
which claude       # /home/supergonti/.local/bin/claude が出ること
claude --version   # 2.1.126 以上
```

**NG 時**: PATH 設定確認、必要なら再インストール。

**完了マーカー**: ☐

---

### Phase 0 完了確認

すべての完了マーカーにチェックが入ったら、次のメッセージを Claude Code（auto モード）の最初のプロンプトに **§5-3 のテンプレート** と一緒に渡す：

> Phase 0 完了。実装に進んでください。

---

## 1. 背景と目的

### 1-1. 問題

`fishing-system-muroto` の公開ページで、4 画面の表示日付が古いまま更新されていない（2026-05-04 時点）：

| 画面 | 表示中の日付 | 経過 |
|---|---|---|
| 釣果DB | 2026-04-14（最終更新） | 約20日前 |
| 解析DB | 2026-04-24 23:38（生成） | 約10日前 |
| 潮流DB | 2026-04-23（最終取得） | 約11日前 |
| 出船判断 | 4/27 04:47（データ更新） | 約1週間前 |

### 1-2. 根本原因

旧リポジトリ `fishing-system` には自動更新用の GitHub Actions workflow が **5 本** 存在するが、`fishing-system-muroto` への再構成時に **4 本が移植されず**、さらに残った 1 本（`sync_after_master_push.yml`）も気象差分取得と解析再生成のステップが TODO 状態で未実装のため、自動パイプラインが断絶している。

### 1-3. ゴール

1. 旧 `fishing-system` の自動更新機能を `fishing-system-muroto` の構造（areas/* / shared/*）に適合させて完全移植する
2. `sync_after_master_push.yml` の TODO ステップを実装する
3. 4 画面が自動的に最新化される状態に復帰する
4. 検証（workflow_dispatch + 公開ページ確認）まで完了する

---

## 2. 現状分析

### 2-1. Workflow の比較

| Workflow | fishing-system（旧） | fishing-system-muroto（新） | 対応 |
|---|---|---|---|
| `update-forecast.yml` | ✅ 5回/日 | ❌ | **新規作成** |
| `update_data.yml`（海流） | ✅ 06:30 JST | ❌ | **新規作成** |
| `sync_after_current_update.yml` | ✅ workflow_run 連鎖 | ❌ | **新規作成** |
| `rebuild_master.yml`（週次検査） | ✅ 月曜09:00 | ❌ | **新規作成** |
| `sync_after_master_push.yml` | ✅ 完全実装 | ⚠️ TODO 残 | **改修** |
| `ingest_dropins.yml` | ❌ | ✅ Muroto 専用 | （触らない） |

### 2-2. Script の比較

| Script | 旧 | 新 | 対応 |
|---|---|---|---|
| `fetch_forecast.py` | `scripts/` | `shared/engines/`（既存） | パス検証 |
| `main.py`（海流取得） | `scripts/` | `shared/engines/`（既存） | OUTPUT_DIR パラメトリック化 |
| `sync_condition_db.py` | `scripts/` | `shared/engines/`（既存） | 動作確認のみ |
| `sync_current_db.py` | `scripts/` | `shared/engines/`（既存） | 動作確認のみ |
| `analyze_engine.py` | `scripts/` | `shared/engines/`（既存） | パス引数検証 |
| `validate_all.py` | `scripts/` | `shared/engines/`（既存） | 動作確認のみ |
| `update_offshore_dashboard_data.py` | `scripts/` | **❌ 存在せず** | **新規作成** |
| `config.py` の OUTPUT_DIR | `"data"`（ハードコード） | `"data"`（ハードコード） | **パラメトリック化** |

### 2-3. パス対応表

| 旧 fishing-system | fishing-system-muroto |
|---|---|
| `data/master_catch.csv` | `areas/muroto/data/master_catch.csv` |
| `data/fishing_condition_db.csv` | `shared/weather/fishing_condition_db.csv` |
| `data/muroto_offshore_current_all.csv` | `shared/current/muroto/muroto_offshore_current_all.csv` |
| `data/forecast_data.json` | `areas/muroto/data/forecast_data.json` |
| `data/analysis/*.json` | `areas/muroto/data/analysis/*.json` |
| `data/js/*` | `areas/muroto/data/js/*` |
| `scripts/*.py` | `shared/engines/*.py` |
| Python module `engines.emit_all` | `shared.engines.emit_all` |

`shared/meta/areas_master.json` に各パスがメタデータとして登録されているので、可能な限りそこから読む（ハードコード禁止）。

---

## 3. タスク分解と Wave 設計

### 3-1. 全体構造

```
[Wave 1] 前提整備（並列度 4）
 ├ T-F: config.py パラメトリック化
 ├ T-G: fetch_forecast.py 動作確認
 ├ T-H: analyze_engine.py 動作確認
 └ T-I: update_offshore_dashboard_data.py 新規作成

[Wave 2] Workflow 作成・改修（並列度 4）
 ├ T-A: update-forecast.yml 新規作成（G 依存）
 ├ T-B: update_data.yml 新規作成（F, I 依存）
 ├ T-D: sync_after_master_push.yml 改修（H 依存）
 └ T-E: rebuild_master.yml 新規作成（独立、ただし golden は別途）

[Wave 3] 連鎖と検証（並列度 1）
 ├ T-C: sync_after_current_update.yml 新規作成（B, H 依存）
 └ T-V: 統合検証（workflow_dispatch で発火 → 結果確認）

[Wave 4] 人間作業
 └ Gonti さん: GitHub Secrets 設定（CMEMS_USERNAME / CMEMS_PASSWORD）
```

### 3-2. 各タスクの詳細

#### T-F: `shared/engines/config.py` パラメトリック化

**目的**: `main.py` 経由の海流データ出力先を Muroto 構造（`shared/current/muroto/`）に向ける。

**現状**:
```python
# shared/engines/config.py:71-72
OUTPUT_DIR    = "data"
OUTPUT_PREFIX = "muroto_offshore_current"
```

**改修方針**:
- 環境変数 `MUROTO_CURRENT_OUTPUT_DIR` で上書き可能にする
- 環境変数が未設定なら `shared/current/muroto` をデフォルトにする（後方互換のため `data` も検討、ただし Muroto 構造優先）
- 例:
  ```python
  import os
  OUTPUT_DIR    = os.environ.get("MUROTO_CURRENT_OUTPUT_DIR", "shared/current/muroto")
  OUTPUT_PREFIX = "muroto_offshore_current"
  ```

**検証**: `python -m shared.engines.main --check` が新しいパス配下を見ること。

**完了条件**: config.py 修正済み、`grep -r "data/muroto_offshore_current" shared/engines/` でハードコード残存ゼロ。

---

#### T-G: `shared/engines/fetch_forecast.py` 動作確認

**目的**: 出船判断用 forecast_data.json を `areas/muroto/data/forecast_data.json` に書き出せることを保証。

**現状**: `--output` 引数で出力先を指定可能（既存対応済み）。デフォルト `PROJECT_ROOT / "data" / "forecast_data.json"` は旧構造のまま。

**改修方針**:
- デフォルト出力先を `areas/muroto/data/forecast_data.json` に変更（または areas_master.json から動的取得）
- 既存の `--output` 引数経路は維持
- areas_master.json に `forecast_json` キーを追加することも検討（areas/muroto/data/forecast_data.json）

**検証**:
```bash
cd ~/workspace/fishing-system-muroto
PYTHONIOENCODING=utf-8 python -m shared.engines.fetch_forecast \
    --output areas/muroto/data/forecast_data.json
# → JSON が更新され、forecast_date が今日付近になること
```

**完了条件**: 上記コマンドが exit 0、JSON 内 `data_date` が当日 or 翌日。

---

#### T-H: `shared/engines/analyze_engine.py` 動作確認

**目的**: 解析エンジンが `--db1/--db2/--db3/--out` で完全パラメトリック動作することを保証。

**現状**: 既存対応済みと推定（引継ぎ書 SESSION_HANDOVER §2-3 で 4本実行コマンド確認済）。デフォルト定数 `DB1_CSV = "data/fishing_muroto_v1.csv"` 等は旧構造のまま残置。

**改修方針**:
- デフォルト定数を Muroto 構造に更新（`areas/muroto/data/derived/all/fishing_muroto_v1.csv` 等）
- CLI 引数経路は維持

**検証**:
```bash
PYTHONIOENCODING=utf-8 python -m shared.engines.analyze_engine \
    --db1 areas/muroto/data/derived/all/fishing_muroto_v1.csv \
    --db2 shared/current/muroto/muroto_offshore_current_all.csv \
    --db3 shared/weather/fishing_condition_db.csv \
    --out areas/muroto/data/analysis/analysis_result.json \
    --no-html
```

**完了条件**: exit 0、`analysis_result.json` の `生成` タイムスタンプが当日。

---

#### T-I: `shared/engines/update_offshore_dashboard_data.py` 新規作成

**目的**: 海流CSV を Muroto 構造の JS データファイルに変換するスクリプトを Muroto 用に新規作成。

**入力**: `shared/current/muroto/muroto_offshore_current_all.csv`
**出力**: `areas/muroto/data/js/muroto_offshore_current_dashboard_data.js`

**実装方針**:
- 旧 `fishing-system/scripts/update_offshore_dashboard_data.py` をベースに移植
- パスは `shared/meta/areas_master.json` の `current_csv` から動的取得（または CLI 引数 `--csv` `--js`）
- バッククォート / バックスラッシュ / `${` のエスケープ処理は旧版と同一
- 出力 JS は `window.MUROTO_CSV_TEXT = \`<csv>\`;` 形式

**検証**:
```bash
python -m shared.engines.update_offshore_dashboard_data
# → areas/muroto/data/js/muroto_offshore_current_dashboard_data.js が更新
# → ファイルサイズが旧版と同等オーダー（数MB）
```

**完了条件**: スクリプト存在、上記コマンド exit 0、JS が生成される。

---

#### T-A: `.github/workflows/update-forecast.yml` 新規作成

**ベース**: 旧 `fishing-system/.github/workflows/update-forecast.yml`

**改修方針**:
- スケジュール: `cron: '0 21,0,3,6,9 * * *'`（JST 6/9/12/15/18時）維持
- `python3 scripts/fetch_forecast.py` → `python3 -m shared.engines.fetch_forecast --output areas/muroto/data/forecast_data.json`
- `git add data/forecast_data.json` → `git add areas/muroto/data/forecast_data.json`
- workflow_dispatch も維持

**完了条件**: yml 構文エラーなし（`act` か GH Actions 上で workflow_dispatch 実行成功）、`forecast_data.json` が更新される。

---

#### T-B: `.github/workflows/update_data.yml` 新規作成

**ベース**: 旧 `fishing-system/.github/workflows/update_data.yml`

**改修方針**:
- スケジュール: `cron: '30 21 * * *'`（JST 06:30）維持
- 環境変数 `MUROTO_CURRENT_OUTPUT_DIR=shared/current/muroto` を設定（T-F 経由）
- `python scripts/main.py` → `python -m shared.engines.main`
- `python scripts/update_offshore_dashboard_data.py` → `python -m shared.engines.update_offshore_dashboard_data`
- `git add` のパスを Muroto 構造に変更
- CMEMS Secrets 参照は維持
- 失敗ガード（CMEMS認証失敗 / 取得成功0件）も維持
- W6-3-fix の JST `yesterday` 計算ロジックも維持
- `target_date` / `collect_all` の workflow_dispatch inputs も維持

**Secrets 設定**: 別途 Gonti さん手動。手順を本計画書 §6 にまとめる。

**完了条件**: yml 構文 OK、CMEMS Secrets 設定済みなら workflow_dispatch で前日海流 CSV 更新成功。

---

#### T-C: `.github/workflows/sync_after_current_update.yml` 新規作成

**ベース**: 旧 `fishing-system/.github/workflows/sync_after_current_update.yml`

**改修方針**:
- `workflow_run` トリガーの workflows 名を T-B の `name:` と一致させる
- `push` トリガーの paths を Muroto 構造に変更
  - `data/muroto_offshore_current_all.csv` → `shared/current/muroto/muroto_offshore_current_all.csv`
  - `data/js/muroto_offshore_current_dashboard_data.js` → `areas/muroto/data/js/muroto_offshore_current_dashboard_data.js`
- ステップ:
  1. `python -m shared.engines.sync_condition_db --master areas/muroto/data/master_catch.csv --condition shared/weather/fishing_condition_db.csv`
  2. `python -m shared.engines.emit_all --master ... --c3 ... --c4 ... --out-dir areas/muroto/data/derived/all`（既存 sync_after_master_push.yml と同じパターン）
  3. `python -m shared.engines.analyze_engine`（4本: result + muroto1/2/3）
- 不明行検出ガード（nearest_station="不明"）も維持
- `[skip ci]` 付き commit で無限ループ回避

**完了条件**: T-B 成功後にチェーン発火、analysis_*.json が更新される。

---

#### T-D: `.github/workflows/sync_after_master_push.yml` 改修

**現状**: emit_all のみ実行。sync_condition_db / analyze_engine が TODO 状態。

**改修方針**:
- 既存の emit_all ステップの **前** に `sync_condition_db` を追加
- 既存の emit_all ステップの **後** に `analyze_engine` 4本実行を追加
- T-C と重複しないよう、`concurrency.group` を分けて運用（既に `sync-after-master-push` で分かれている）

**完了条件**: 釣果データを drop_inbox 経由で投入 → master 更新 → 気象差分 → 派生CSV → 解析 まで一気通貫。

---

#### T-E: `.github/workflows/rebuild_master.yml` 新規作成

**ベース**: 旧 `fishing-system/.github/workflows/rebuild_master.yml`

**改修方針**:
- スケジュール: `cron: '0 0 * * 1'`（月曜 09:00 JST）維持
- emit_all のパス引数を Muroto 構造に変更
- `tests/golden_match_test.py` の有無を確認（**Muroto に未整備の可能性大、その場合は本タスクは Phase 2 に延期**）
- `validate_all.py` のパス引数も Muroto 構造に変更

**注意**: golden test が未整備なら、本タスクは「workflow yml の雛形だけ作成、golden 整備は別タスク」として完了させる。

**完了条件**: yml 雛形作成 + 月曜09:00 自動発火確認 OR golden 整備が必要なことを明記して Phase 2 に引き継ぐ。

---

#### T-V: 統合検証

**手順**（順番に実行）:

1. T-A: `gh workflow run update-forecast.yml -R supergonti/fishing-system-muroto`
   → 完了確認 → 公開ページ「出船判断」の日付更新確認
2. T-D: drop_inbox にダミー CSV を投入（あるいは既存 CSV の force re-ingest）→ ingest_dropins → sync_after_master_push 連鎖確認
3. T-B: `gh workflow run update_data.yml -R supergonti/fishing-system-muroto`（CMEMS Secrets 設定後）
4. T-C: T-B 完了後、自動的にチェーン発火 → 解析が更新されること確認
5. 公開ページ全 4 画面の日付が最新化されていることを目視確認

**完了条件**: 4 画面の日付が当日 or 前日になっている。

---

## 4. 並列実行計画（指揮役 + ワーカー）

### 4-1. アーキテクチャ

```
[ Supervisor Agent ]
    ├ 計画書を読む（本書）
    ├ Wave 1: 4 ワーカー並列起動 → 完了待ち → 各ワーカー成果を検証
    ├ Wave 2: 4 ワーカー並列起動（Wave 1 成果を前提）→ 完了待ち → 検証
    ├ Wave 3: T-C 単独 → 検証
    ├ コミット & push（layer ごとに分ける、後述）
    └ T-V: 統合検証 → ユーザーに報告
```

### 4-2. コミット粒度

各ワーカーは個別ブランチではなく、Supervisor が以下の単位で合算コミットする：

| コミット | 内容 |
|---|---|
| #1 | `chore(scripts): config パラメトリック化 + Muroto パス対応 (T-F/G/H/I)` |
| #2 | `feat(workflows): forecast 自動更新を新規追加 (T-A)` |
| #3 | `feat(workflows): 海流データ自動更新を新規追加 (T-B)` |
| #4 | `feat(workflows): master push 後の連鎖に condition + analyze を追加 (T-D)` |
| #5 | `feat(workflows): 海流更新後の自動同期を新規追加 (T-C)` |
| #6 | `feat(workflows): 週次整合性検査を新規追加 (T-E)`（golden 未整備なら skip） |

push は **各 Wave 完了時に 1 回** にまとめる。

### 4-3. 安全装置

- **必ず `bash "C:/Claude/tools/scan_3layer.sh" "<repo>"` を push 前に実行**（CLAUDE.md ルール）
- 実装前に `git pull origin main` で本物の最新を取り込む
- 実装中は worktree か feature ブランチで作業し、検証完了後に main に merge → push
- どこかで失敗したら、その Wave の全変更を `git restore` で巻き戻して再試行

---

## 5. sandbox-01 上での実行手順

### 5-1. 事前準備

→ **Phase 0（§0 G-1 〜 G-7）を完了させる**。Phase 0 完了確認後にここから先に進む。

### 5-2. Claude Code の起動と Supervisor プロンプト

```bash
ssh sandbox-01
cd ~/workspace/fishing-system-muroto
claude --dangerously-skip-permissions
```

Claude Code の最初のプロンプトに **§5-3 のテンプレート** を貼り付けて実行させる。

### 5-3. Supervisor プロンプトテンプレート（コピペ用）

```
あなたは fishing-system-muroto の自動更新 workflow 移植・改修プロジェクトの指揮役です。

Phase 0（人間作業）は完了済みの前提でこのプロンプトを受け取っています。
Phase 0 が未完なら作業を中止して Gonti さんに報告してください。

【必読資料（順序通り）】
1. docs/COWORK_HANDOFF_GUIDE.md  ← 共通規約。鍵運用・Secrets・標準コマンドの拠り所
2. docs/plans/20260504_workflow_migration.md  ← 本計画書、§0 〜 §10 すべて
3. C:/Claude/CLAUDE.md（sandbox-01 上では /home/supergonti/Claude/CLAUDE.md 等の
   実体パスに読み替えてください）  ← scan_3layer.sh と JST タイムスタンプの規則
4. ~/workspace/fishing-system-old/.github/workflows/  ← 旧 workflow を参照用

【作業の進め方】
本計画書 §3 のタスク T-A 〜 T-V を、§4 の Wave 設計に従って実行する。

Wave 1（並列度 4）:
  Task tool で 4 つのワーカーエージェントを同時起動し、以下を担当させる：
    Worker 1: T-F (config.py パラメトリック化)
    Worker 2: T-G (fetch_forecast.py 動作確認・必要に応じてデフォルトパス更新)
    Worker 3: T-H (analyze_engine.py デフォルトパス更新)
    Worker 4: T-I (update_offshore_dashboard_data.py 新規作成)
  各ワーカーには本計画書 §3-2 の該当節を渡すこと（§5-4 のテンプレート使用）。
  全員完了したら、各成果物を `python -m ...` で検証する。
  問題なければコミット #1 として一括コミット（push はまだしない）。

Wave 2（並列度 4）:
  Wave 1 が成功したら、4 つのワーカーを並列起動：
    Worker 1: T-A (update-forecast.yml)
    Worker 2: T-B (update_data.yml)
    Worker 3: T-D (sync_after_master_push.yml 改修)
    Worker 4: T-E (rebuild_master.yml — golden 未整備なら yml 雛形のみ)
  yml の構文チェックは python -c "import yaml; yaml.safe_load(open('<file>'))" で。
  完了後、コミット #2〜#6 として種類ごとに分割コミット。

Wave 3:
  T-C (sync_after_current_update.yml) を作成（依存が解決したので最後）。

【push 前の必須チェック】
1. JST タイムスタンプを使う（CLAUDE.md §1.5）
2. bash "<scan_3layer.sh のパス>" "$(pwd)" で 3 層スキャン → exit 0 を確認
3. exit 0 なら git push origin main
4. push 後、gh workflow list -R supergonti/fishing-system-muroto で 5 本の
   workflow が登録されていることを確認

【検証フェーズ】（T-V）
1. gh workflow run update-forecast.yml -R supergonti/fishing-system-muroto
   → 1 分待つ → gh run list -R supergonti/fishing-system-muroto -L 3 で success 確認
   → 公開ページ https://supergonti.github.io/fishing-system-muroto/ の
     出船判断画面の日付更新確認
2. update_data.yml も同様に手動発火 → success 確認（CMEMS Secrets は Phase 0
   §G-6 で設定済前提）
3. 全 workflow の手動発火結果と、公開ページの全 4 画面の日付状況を最終レポートする

【失敗時の方針: 方針 C - テスト的（一切の再試行なし）】
今回は Cowork → sandbox-01 受け渡しの初回テストなので、暴走防止を最優先します。
1 ステップでも失敗したら：
1. その時点で全作業を停止する（再試行しない）
2. 状態を保存（`git status` `git diff` `git log --oneline -10` をログに残す）
3. 失敗の詳細（どのタスク、どの Wave、何が起きたか）を Gonti さんへの報告として
   出力する
4. ユーザー判断を待つ

【出力】
- 各 Wave 完了時に進捗サマリ（どのタスクが完了、何コミットしたか）
- 全完了時に最終レポート（成果物一覧、検証結果、残タスク）
- 失敗時は §失敗時の方針 に従った報告

【最後の片付け】
全完了したら、本計画書 §9 の完了基準にチェックを入れ、本計画書末尾に
実施結果サマリ（実施日時 JST、コミット SHA、検証結果）を追記してください。
ssh-agent からの個人鍵削除は Gonti さんが手動で行うので、報告内に
「`ssh-add -d ~/.ssh/id_ed25519_github` で個人鍵を外してください」を含めてください。

それでは作業を開始してください。最初に必読資料 1〜4 を読み、計画書の理解を
ユーザーに 200 字以内で報告してから Wave 1 に入ること。
```

### 5-4. ワーカープロンプトの組み立て方（指揮役向け）

各ワーカーには Task tool で次のフォーマットを使う：

```
あなたは fishing-system-muroto の workflow 移植プロジェクトのワーカーです。
担当タスク: T-X (タスク名)

【参照資料】
- docs/plans/20260504_workflow_migration.md §3-2 の T-X 節を熟読してください
- 旧リポジトリ ~/workspace/fishing-system-old/ を参考に、Muroto 構造に適合させてください

【作業内容】
（§3-2 T-X の改修方針をそのまま貼る）

【完了条件】
（§3-2 T-X の完了条件をそのまま貼る）

【出力】
- 変更したファイルのリスト
- 検証コマンドの実行結果
- 問題があれば詳細を報告（勝手に判断せず指揮役に上げる）
```

---

## 6. CMEMS Secrets 設定手順

→ **Phase 0 §G-6 に移動**。Phase 0 の段階で設定が完了している前提で実装フェーズを進める。

**重要事実**: GitHub の Secrets は API/CLI/Web UI のいずれでも **値の読み取りができない**（一度設定すると取り出せない）。旧 `fishing-system` リポジトリに設定されている値を `fishing-system-muroto` に「コピー」することは概念的に不可能で、Gonti さんが別経路（パスワードマネージャー / .env / Copernicus 再ログイン）から値を提供する必要がある。詳細は §G-6 参照。

---

## 7. 既知のリスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| `sync_after_master_push` と `sync_after_current_update` の同時発火 | 派生CSV / analysis の競合書き込み | 別 `concurrency.group` 設定済み（旧 fishing-system も同様）。万一同時起動しても処理は冪等 |
| GITHUB_TOKEN による push が他 workflow をトリガーしない | チェーン断絶 | `sync_after_current_update.yml` は `workflow_run` トリガーで対応（旧 W6-4 で確立済） |
| CMEMS 認証失敗の silent failure | データ取得 0 件のまま success | `grep "I forgot my username"` で検出 → exit 1 |
| Muroto 側 `master_catch.csv` の date 形式不揃い | 気象 JOIN 失敗 | 別タスク 🥇（引継ぎ書 §5）で `ingest_dropins.py` に date 正規化を追加予定 |
| golden test 未整備で `rebuild_master.yml` が失敗 | 月曜の通知が常に Failed | T-E は yml 雛形のみ作成 + コメントで「golden 整備は別タスク」と明記 |
| Phase 2 Deploy Key の権限が `sandbox-01-config` 専用 | この repo に push できない | sandbox-01 では個人鍵を一時的に ssh-agent に追加（`ssh-add ~/.ssh/id_ed25519_github`）。作業完了後は `ssh-add -d` で外す |

---

## 8. ロールバック手順

### 8-1. Wave 単位でのロールバック

各 Wave のコミットに対応する revert：

```bash
# Wave 3 のロールバック
git revert <T-C コミットSHA>

# Wave 2 のロールバック（複数コミット）
git revert <T-A SHA> <T-B SHA> <T-D SHA> <T-E SHA>

# Wave 1 のロールバック
git revert <T-F/G/H/I 統合コミット SHA>
```

### 8-2. 全面ロールバック

最後の安全コミット（このプロジェクト開始前の `master_catch_2026-04-25_233859_jst.csv` バックアップが取られた直後）まで戻す：

```bash
git log --oneline | grep "ingest_dropins: 2026-04-25T14:38:59Z"
# そのコミット SHA を確認
git revert HEAD..<safe_sha>
git push origin main
```

### 8-3. 公開ページへの影響

GitHub Pages は `main` の最新を配信するので、revert すれば自動的に旧状態に戻る。データファイルは Timeshift（sandbox-01 ローカル）+ 月次 cold-backup から復元可能。

---

## 9. 完了基準

本計画書の完了は **以下すべてを満たす** ことで判定：

### 9-1. Phase 0（Gonti さん）

- ☐ G-1 〜 G-7 全完了マーカーにチェック

### 9-2. 実装フェーズ（sandbox-01 Claude Code）

- ☐ Wave 1 全タスク (T-F/G/H/I) 完了、検証コマンド全て exit 0
- ☐ Wave 2 全タスク (T-A/B/D/E) 完了、yml 構文チェック OK
- ☐ Wave 3 (T-C) 完了
- ☐ scan_3layer.sh で全 push が exit 0 通過

### 9-3. 検証フェーズ

- ☐ T-V 統合検証で全 workflow が手動発火 success
- ☐ 公開ページ 4 画面の日付が当日 or 前日に更新

### 9-4. 片付け（Gonti さん）

- ☐ ssh-agent から `id_ed25519_github` を削除（`ssh-add -d`）
- ☐ Claude Code を `/exit` で終了
- ☐ 本計画書末尾に実施結果サマリを追記
- ☐ 横展開可能な知見を `docs/COWORK_HANDOFF_GUIDE.md §9` に追記

---

## 10. 関連資料

| 資料 | パス |
|---|---|
| 引継ぎ書 | `docs/SESSION_HANDOVER_2026-04-25.md` |
| 共通 CLAUDE.md | `C:\Claude\CLAUDE.md` |
| Timeshift 判断記録 | `C:\Claude\Mini PC installation steps\Timeshift設定_判断記録_2026-05-02_改訂版.md` |
| ミニPC 構築手順書 | `C:\Claude\Mini PC installation steps\ミニPC安全実験環境_構築手順書_V3.md` |
| 旧 workflow 群 | `C:\Dev\fishing-system\.github\workflows\` |

---

**末尾メモ**: 本計画書は Cowork（ノートPC）で作成された。実装は sandbox-01 の Claude Code（auto モード）に委譲する。実装完了後、本ファイルの §9 完了基準にチェックを入れて結果を本ファイル末尾に追記すること。
