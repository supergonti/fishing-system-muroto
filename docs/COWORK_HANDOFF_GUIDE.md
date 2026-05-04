# Cowork → sandbox-01 受け渡しガイド

**作成日**: 2026-05-04
**位置付け**: Cowork（ノートPC）で計画を立て、sandbox-01（ミニPC）の Claude Code に実装させる二段階運用の **共通規約**。
**併読**: `C:\Claude\CLAUDE.md`（全プロジェクト共通指示）／ 各プロジェクトの個別計画書

このガイドは「人間への確認や手作業を限りなく前倒しで集約し、実装フェーズでは Claude Code が autonomous に進める」ことを目的とする標準書である。**今後すべての Cowork → sandbox-01 計画書はこのガイドを引用する**。

---

## 1. 役割分担

| レイヤー | 担当 | 主な作業 |
|---|---|---|
| **Cowork（ノートPC・本書を書いている層）** | Claude（Cowork 上） | 要件整理・現状分析・計画書作成・受け渡しプロンプト生成・知見の蓄積 |
| **計画書（docs/plans/YYYYMMDD_*.md）** | Cowork が出力、sandbox-01 が消費 | 実装の手順・依存・検証・ロールバックを記述 |
| **sandbox-01（ミニPC）の Claude Code (auto モード)** | Claude Code（指揮役 + ワーカー） | 計画書を読み、Task tool でワーカー並列起動、commit / push、検証 |
| **GitHub Actions** | Workflow runner | push 連鎖・スケジュール起動・公開ページ反映 |
| **人間（Gonti さん）** | 監督 + Phase 0 のみ | Phase 0（前提整備）と最終承認のみ。実装中は介入しない |

**設計原則**: 人間の介在は **Phase 0** と **完了確認** だけに限定する。途中の確認は Claude Code 内で完結させる。

---

## 2. 標準ワークフロー

```
[Cowork: 計画フェーズ]
  ┌─────────────────────────────┐
  │ ① 要件ヒアリング              │
  │ ② 現状分析（ファイル読み）     │
  │ ③ 依存関係グラフ作成           │
  │ ④ Phase 0 リスト化             │
  │ ⑤ Wave 設計（並列実行可能性）  │
  │ ⑥ 計画書出力                   │
  │   docs/plans/YYYYMMDD_*.md    │
  └─────────────┬───────────────┘
                ▼
[Gonti さん: Phase 0]
  ┌─────────────────────────────┐
  │ 計画書の Phase 0 セクションに │
  │ 列挙された人間作業を実施      │
  │ （SSH 鍵、Secrets、clone 等） │
  └─────────────┬───────────────┘
                ▼
[sandbox-01: 実装フェーズ]
  ┌─────────────────────────────┐
  │ ① 計画書を読む                │
  │ ② COWORK_HANDOFF_GUIDE 確認   │
  │ ③ Wave 1 並列実行             │
  │ ④ Wave 2 並列実行             │
  │ ⑤ 検証 + commit + push        │
  └─────────────┬───────────────┘
                ▼
[Cowork: 確認フェーズ]
  ┌─────────────────────────────┐
  │ Gonti さんが公開ページを確認  │
  │ 知見を本ガイドに追記           │
  └─────────────────────────────┘
```

---

## 3. 環境前提（変化が稀な情報）

これらは **一度確認したら以後は再確認不要**。前提が崩れたときだけ §10 改訂履歴に記載して更新する。

### 3-1. ハードウェア / OS

| 項目 | 値 | 備考 |
|---|---|---|
| ミニPC ホスト名 | `sandbox-01` | BOSGAME P3 PLUS |
| OS | Ubuntu Desktop 26.04 LTS | |
| IP | `192.168.0.50`（静的） | |
| ユーザー | `supergonti` | |
| ノートPC からの接続 | `ssh sandbox-01` | エイリアス済 |

### 3-2. ディレクトリ前提

| パス | 用途 |
|---|---|
| `~/workspace/` | sandbox-01 の作業ディレクトリ（200GB の `/home` 内） |
| `~/workspace/<repo>/` | プロジェクトリポジトリ（`git clone` でセットアップ） |
| `~/workspace/<repo>-old/` | 旧リポジトリの read-only 参照（必要時のみ clone） |
| `~/.local/bin/claude` | Claude Code 本体（v2.1.126） |
| `~/.ssh/id_ed25519_github` | GitHub 個人鍵（Phase 2: 通常は ssh-agent から外して shelved） |
| `~/.ssh/id_ed25519_deploy` | Deploy Key（`sandbox-01-config` 専用、自動運用） |
| `/snapshots/` | Timeshift（V18: `/snapshots/**` exclude 必須）+ rsync workspace-backup |

### 3-3. ツール前提

| ツール | パス | 備考 |
|---|---|---|
| Claude Code | `~/.local/bin/claude` | auto モード起動: `claude --dangerously-skip-permissions` |
| 3層スキャン | `C:/Claude/tools/scan_3layer.sh` | push 前に必ず実行（CLAUDE.md §138） |
| gitleaks | `C:/Claude/tools/gitleaks_linux` | scan_3layer.sh 内部で利用 |
| check_secrets | `C:/Claude/tools/check_secrets.py` | 同上 |
| gh CLI | sandbox-01 / ノートPC とも導入済み前提 | `gh auth status` で確認 |

### 3-4. 認証 / 鍵運用

| 鍵 | 状態 | 必要時のみロード |
|---|---|---|
| `id_ed25519_github`（個人鍵） | shelved（agent 外） | push が必要な作業の前に `ssh-add ~/.ssh/id_ed25519_github`、完了後に `ssh-add -d` で外す |
| `id_ed25519_deploy`（Deploy Key） | systemd user service で常時 agent ロード | 触らない、`sandbox-01-config` 専用 |

### 3-5. GitHub Secrets

**重要事実**: GitHub の Secrets は **一度設定したら値の読み取りができない**（API/CLI/Web UI 全て不可、セキュリティ仕様）。リポジトリ間でのコピーはできず、毎回元の値（パスワードマネージャー等）から再投入が必要。

Secret が必要な workflow の例：
- CMEMS（海流データ）: `CMEMS_USERNAME` / `CMEMS_PASSWORD`
- 他: 必要に応じて追記

---

## 4. Phase 0 設計原則

### 4-1. Phase 0 とは

計画書の **§0**（最初のセクション）として、人間にしかできない作業を **すべて** 列挙する。実装フェーズ開始前にここを完了させる。

### 4-2. Phase 0 に入るべき項目

- **SSH 鍵 / agent 操作**（一時的に shelved 解除する等）
- **GitHub Secrets の設定**（値が必要なもの）
- **ブラウザ操作・SSO 認証**（OAuth 含む）
- **物理デバイス操作**（外付け HDD 接続等）
- **クレデンシャル取得**（パスワードマネージャー / 2FA）
- **大量データの初期 clone**（時間がかかるもの）
- **新リポジトリ作成、権限変更**
- **本番に影響する設定変更**

### 4-3. Phase 0 のフォーマット

各項目は次の構造で記述：

```markdown
### G-N. <項目名>

**目的**: なぜ必要か（1〜2 行）
**実行コマンド** または **手動操作手順**:
```bash
コマンド例
```
**確認方法**:
```bash
確認コマンド例
# 期待される出力
```
**NG 時の対処**: 失敗したらどうするか
**完了マーカー**: チェックリストでチェックを入れる
```

### 4-4. Phase 0 が完了するまで実装フェーズに進まない

計画書の §0 末尾に「全て完了したら Claude Code に対して『Phase 0 完了。実装に進んでください』と伝える」と明記する。

---

## 5. 計画書フォーマット規約

### 5-1. ファイル名

```
docs/plans/YYYYMMDD_<task_name>.md
```

例: `docs/plans/20260504_workflow_migration.md`

### 5-2. 必須セクション

```markdown
# <タイトル>

**作成日**: YYYY-MM-DD
**対象リポジトリ**: <repo>
**実装環境**: sandbox-01 Claude Code (auto モード)
**併読**: docs/COWORK_HANDOFF_GUIDE.md  ← 必須引用

## 0. Phase 0: 人間作業集約（Gonti さん）
（§4 規約に従って列挙）

## 1. 背景と目的

## 2. 現状分析

## 3. タスク分解と Wave 設計

## 4. 並列実行計画（指揮役 + ワーカー）

## 5. sandbox-01 上での実行手順

## 6. （タスク固有の補足）

## 7. 既知のリスクと対策

## 8. ロールバック手順

## 9. 完了基準

## 10. 関連資料
```

### 5-3. Wave 設計の規約

```
[Wave N: 説明]（並列度 X）
 ├ T-X1: タスク1
 ├ T-X2: タスク2
 └ ...
```

各タスクは「目的 / 改修方針 / 検証コマンド / 完了条件」を含める。

### 5-4. コミット粒度

各 Wave 内で関連するタスクを 1 コミットにまとめる。push は Wave 完了時に 1 回。コミットメッセージの prefix は Conventional Commits 準拠：
- `feat:` 機能追加
- `fix:` バグ修正
- `chore:` メンテナンス
- `docs:` ドキュメント
- `refactor:` リファクタ

---

## 6. 標準コマンド集

### 6-0. 実行環境ラベル規約（必須、L-008 / L-010）

**目的**: 「どこで実行するコマンドか」が一目で分かるようにし、ノートPC か SSH 接続先か取り違える事故を防ぐ。

#### 6-0-1. 環境の種類

| 環境ラベル | 意味 | プロンプトの見え方 |
|---|---|---|
| **🖥️ ノートPC（PowerShell）で実行** | Windows のスタートメニュー → PowerShell で開いた黒い画面 | `PS C:\...> ` |
| **🖥️ ノートPC（cmd）で実行** | Windows のスタートメニュー → コマンドプロンプトで開いた黒い画面 | `C:\...> ` |
| **🐧 ノートPCでSSHで実行** | PowerShell から `ssh sandbox-01` で接続した状態。物理的にはノートPCで打っているが、コマンドは sandbox-01 上で実行される | `supergonti@sandbox-01:~$ ` |
| **🤖 Claude Code（対話プロンプト）に入力** | sandbox-01 上で `claude --dangerously-skip-permissions` を起動後の対話欄 | （Claude Code の UI） |
| **🌐 GitHub Web UI で操作** | ブラウザで github.com を開いて画面操作 | （ブラウザ） |

**重要な考え方（L-013）**: ラベルは「ユーザーが物理的にどこで操作しているか」を基準にする。SSH で sandbox-01 に繋がっていても、ユーザー自身はノートPC のキーボードを叩いているので「**ノートPCでSSHで実行**」と表現する。これにより初心者でも「いま自分がどの画面に向かっているか」と一致して直感的に分かる。

#### 6-0-2. 書き方フォーマット（必須）

**コードブロックの「外」にラベルを置く**。ラベルは説明であり、コピペ対象ではない。コードブロック（黒い枠）の **中身だけ** がコピペ対象。

````markdown
🖥️ **ノートPC（PowerShell）で実行**

```powershell
cd "C:\Dev\fishing-system Muroto"
git status
```

→ コピペするのは `cd ...` と `git status` の 2 行だけ。「🖥️ ノートPC（PowerShell）で実行」はコピペしない。
````

#### 6-0-3. 初心者向け重要ルール（L-010）

**コピペするのは黒い枠（コードブロック）の中身だけ**。これを徹底する。

- 太字の見出し（🖥️〜で実行）は **コピペしない**
- 黒い枠の外にある日本語の説明文は **コピペしない**
- 黒い枠 1 つにつき、その中身を全部コピーして 1 度に貼り付けて Enter で OK
- プロンプト文字列（`PS C:\Users\super>` や `supergonti@sandbox-01:~$`）はコードブロックの中に書かない（書くと初心者がそれもコピーして実行してしまい、エラーになる）

**やってはいけない書き方の例**:

````markdown
（悪い例：プロンプトを別ブロックに分けると、初心者がプロンプトをコマンドだと
  勘違いして打ってしまう）

```
PS C:\Users\super>
```
```powershell
cd "C:\Dev\..."
```
````

**正しい書き方の例**:

````markdown
🖥️ **ノートPC（PowerShell）で実行**

```powershell
cd "C:\Dev\..."
```
````

#### 6-0-4. 環境が切り替わるとき

手順 1 はノートPC、手順 2 は sandbox-01、というように切り替わるたびに新しいラベルを付け、コードブロックも別々にする。同じ環境で続けて打つコマンドは 1 つのコードブロックにまとめてよい。

#### 6-0-5. ありがちな落とし穴

- Windows 側で打つべきコマンドを SSH 接続先で打って `bash: cd: 'C:\Dev\...': No such file or directory` でハマる
- sandbox-01 側で打つべきコマンドを Windows PowerShell で打って `git: command not found` で混乱する
- ラベル文字列をそのままコマンドとしてコピーして実行してしまいエラーになる（初心者が最も陥りやすい、L-010）
- 手順を読み返したときにどっちで打ったコマンドだったか思い出せない

### 6-1. Cowork 側（ノートPC、PowerShell）— push 手順

PowerShell には `bash` が PATH にない前提で、Git Bash をフルパスで呼ぶ書き方が標準（L-012）。

🖥️ **ノートPC（PowerShell）で実行 — 1. リポジトリ最新化**

```powershell
cd "C:\Dev\<repo>"
git pull origin main
```

🖥️ **ノートPC（PowerShell）で実行 — 2. ステージング**

```powershell
git add docs/plans/<file>.md docs/COWORK_HANDOFF_GUIDE.md
git status
```

→ Changes to be committed に意図したファイルだけ表示されることを確認。

🖥️ **ノートPC（PowerShell）で実行 — 3. 3層スキャン**

```powershell
& "C:\Program Files\Git\bin\bash.exe" "C:/Claude/tools/scan_3layer.sh" "C:/Dev/<repo>"
echo "ExitCode: $LASTEXITCODE"
```

→ ExitCode 0 ならクリア、push に進める。

🖥️ **ノートPC（PowerShell）で実行 — 4. コミット & プッシュ**

```powershell
git commit -m "docs(plan): <タスク名>計画書を追加"
```

```powershell
git push origin main
```

→ `<旧SHA>..<新SHA>  main -> main` が出れば成功。

### 6-2. sandbox-01 側（ミニPC、Phase 0）

```
PS C:\Users\super>
```
```powershell
# まずノートPCから SSH 接続
ssh sandbox-01
```

接続後はプロンプトが切り替わる：

```
supergonti@sandbox-01:~$
```
```bash
# リポジトリ準備
cd ~/workspace
[ ! -d <repo> ] && git clone git@github.com:supergonti/<repo>.git
cd <repo>
git pull origin main
ls docs/plans/  # 最新計画書が見えること

# 旧リポジトリ参照用（必要時のみ）
[ ! -d ~/workspace/<old-repo> ] && \
  git clone https://github.com/supergonti/<old-repo>.git ~/workspace/<old-repo>

# ssh-agent に個人鍵を追加（push が必要な作業の前）
ssh-add ~/.ssh/id_ed25519_github
ssh-add -l  # 鍵がロードされたこと確認

# Claude Code 起動（auto モード）
claude --dangerously-skip-permissions
```

### 6-3. sandbox-01 側（実装完了後・片付け）

```
supergonti@sandbox-01:~$
```
```bash
# ssh-agent から個人鍵を外す（Phase 2 状態に戻す）
ssh-add -d ~/.ssh/id_ed25519_github
ssh-add -l  # "no identities" or Deploy Key のみ

# Claude Code 終了
# /exit

# SSH セッションも抜ける
exit
```

抜けるとノートPC のプロンプトに戻る：

```
PS C:\Users\super>
```

### 6-4. Secrets 操作

#### 6-4-1. 第一選択肢: Web UI

Secrets の **新規投入は Web UI を第一選択肢** とする（運用方針、L-006）。理由：

- ターミナル履歴に値が残らない
- ペースト操作が直感的（パスワードマネージャーのオートフィル / コピーから直接投入できる）
- 確認画面で投入完了が視覚的に分かる
- 多要素認証など GitHub 側の保護が自然に働く

```
https://github.com/supergonti/<repo>/settings/secrets/actions
```

→ 「New repository secret」→ Name と Secret を入れて Add。

#### 6-4-2. 代替: gh CLI（対話入力）

既存 Secrets の確認や、Web ブラウザを使えない環境で：

```bash
# 一覧（値は表示されない、存在のみ確認）
gh secret list -R supergonti/<repo>

# 設定（対話入力推奨。--body は履歴に残るので避ける）
gh secret set <NAME> -R supergonti/<repo>
# ↑ プロンプトで値を入力

# 削除
gh secret remove <NAME> -R supergonti/<repo>
```

#### 6-4-3. 重要な仕様

- `gh secret view` は存在しない。値の取得は不可能（GitHub 側の暗号化保存仕様）
- リポジトリ間で Secrets を「コピー」する手段は存在しない（毎回元値からの再投入）
- repository scope の Secret はそのリポジトリの workflow からのみ参照可能
- organization scope の Secret は別管理（個人リポジトリでは通常不要）

---

## 7. 鍵運用の標準パターン（Phase 2）

### 7-1. 通常運用

- 個人鍵 `id_ed25519_github`: ssh-agent から外して shelved
- Deploy Key `id_ed25519_deploy`: systemd user service で agent 常駐

### 7-2. 一時的に個人鍵を使う場合

push が必要な作業の **直前** に追加：

```bash
ssh-add ~/.ssh/id_ed25519_github
```

作業完了後に **必ず** 外す：

```bash
ssh-add -d ~/.ssh/id_ed25519_github
```

### 7-3. やってはいけないこと

- 個人鍵を ssh-agent に常駐させる（systemd service 化しない）
- passphrase を `~/.ssh/config` に記載する
- 個人鍵を別のホストにコピーする

---

## 8. 検証 / ロールバック / 片付けの標準

### 8-1. 検証チェックリスト（実装完了時）

- [ ] 全変更ファイルの diff を確認
- [ ] 単体検証コマンド全て exit 0
- [ ] `bash "C:/Claude/tools/scan_3layer.sh" "$(pwd)"` exit 0
- [ ] yml ファイルがある場合は `python -c "import yaml; yaml.safe_load(open('<file>'))"` でパース確認
- [ ] テストがある場合は実行
- [ ] commit メッセージが Conventional Commits 準拠

### 8-2. ロールバック手順

各 Wave のコミットを revert：

```bash
git log --oneline -10        # 該当 SHA を確認
git revert <SHA>             # 単発
git revert <SHA1> <SHA2>     # 複数
git push origin main
```

GitHub Pages は revert 後の main 最新を配信するので公開ページも自動的に旧状態に戻る。

### 8-3. 失敗時の方針

計画書の §1 等で明示する：

- **方針 A（保守的）**: 1 ステップでも失敗したら全 Wave をロールバックして人間判断を仰ぐ
- **方針 B（積極的）**: 失敗したステップだけ最大 N 回まで再試行、それでも駄目なら人間判断を仰ぐ
- **方針 C（テスト的）**: 一切の再試行なし、即座に状態を保存して人間に報告

各計画書では A/B/C のどれかを明示する。

---

## 9. 知見・教訓ログ（追記式）

ここには Cowork → sandbox-01 の運用で得られた **転用可能な学び** を時系列で追記する。プロジェクト固有の知見は各プロジェクトの引継ぎ書に書き、本セクションには **横展開可能なもの** だけを残す。

### 2026-05-04（V1 初版）

- **L-001**: GitHub Secrets は値の読み取り不可。リポジトリ間で「コピー」は概念的に存在しない。元の値は人間が別経路（パスワードマネージャー等）から提供する必要がある
- **L-002**: Cowork のサンドボックス bash には gh CLI が認証されていない。Secret 一覧確認は sandbox-01 か Gonti さんの環境で行う
- **L-003**: `mcp__cowork__request_cowork_directory` で再マウントしないと、Glob は通っても Read/Grep が通らない事象がある（マウント不完全状態）。Cowork 側はファイル名だけでなく内容アクセスも確認すること
- **L-004**: ノートPC ↔ sandbox-01 の rsync / scp は Phase 2 鍵運用と相性が悪いので、デフォルトは GitHub 経由で受け渡す（計画書 push → sandbox-01 git pull）
- **L-005**: Phase 0 を計画書冒頭に置くだけで、実装フェーズ中の人間介入が大幅に減る（特に Secrets / SSH 鍵関連）
- **L-006**: Secrets の **新規投入は Web UI を第一選択肢** とする（履歴に値が残らない、パスワードマネージャーから直接ペーストできる、視覚的に確認できる）。Phase 0 の手順としても Web UI 経路を最初に書く。gh CLI は既存確認や CI 環境向けの代替として §6-4-2 に残す
- **L-007**: CMEMS（Copernicus Marine Service）の場合、外部発行 API キーや別アカウントは不要で、`data.marine.copernicus.eu` の Web ログインに使うユーザー ID とパスワードがそのまま `CMEMS_USERNAME` / `CMEMS_PASSWORD` の値になる（`copernicusmarine` Python ライブラリの仕様）
- **L-008**: コマンド提示時は **実行環境ラベルを必ず付ける**（`PS C:\Users\super>` / `supergonti@sandbox-01:~$` / `(claude code)` / `(github web ui)` 等）。ラベルが無いとノートPC か SSH 接続先かが見分けられず事故る。詳細は §6-0 規約。Cowork Claude は計画書出力時も会話の手順提示時もこの規約を守る
- **L-009**: Cowork が同じリポジトリをマウントした状態でサンドボックス側から `git status` を打つと、`core.autocrlf` 未設定により Windows 改行ファイルが「全行変更」扱いで大量検知される。実体差分ではないので無視してよいが、誤って `git add -A` しないこと。push は Windows 側（autocrlf=true 効いている）で行う原則
- **L-010**: 初心者向けに重要：プロンプト文字列（`PS C:\Users\super>` 等）を **コードブロックの中** に書くと、初心者がコマンドだと勘違いして実行してしまう事故が起きる（実例: 2026-05-04、`PS : 名前 "C:\Users\super>" のプロセスが見つかりません` エラー）。ラベルは **コードブロックの外** に「🖥️ ノートPC（PowerShell）で実行」のような太字の見出しとして書き、コピペ対象は黒い枠の中身だけにする。詳細は §6-0-3
- **L-011**: PowerShell に複数コマンドを 1 度に貼り付けると、最後のコマンドだけ Enter 待ちで実行されない事象が起きる（実例: 2026-05-04、`echo "ExitCode: $LASTEXITCODE"` が貼り付けたまま実行されず）。Cowork からコマンドを提示するときは **1 コマンド 1 コードブロック** で分けるか、まとめる場合は「貼り付け後に Enter を 1 回押してください」と添える
- **L-012**: PowerShell の PATH に `bash` が無い場合、`& "C:\Program Files\Git\bin\bash.exe" "<script>" "<args>"` の形式で呼ぶ。3 標準候補のうち実用は `C:\Program Files\Git\bin\bash.exe`（Git Bash）。`scan_3layer.sh` 等を PowerShell から実行するときの定番パターン
- **L-013**: 環境ラベルは「ユーザーが物理的にどこで操作しているか」基準で表現する。SSH で sandbox-01 に繋いでいても、ノートPC のキーボードを叩いているなら「**ノートPCでSSHで実行**」と書く（実例: 2026-05-04、当初「sandbox-01 で実行」と書いていたが、ユーザーから「ノートPCでSSHで実行」に変更要望）。コマンドの実行場所（sandbox-01 上）と、ユーザーの操作場所（ノートPC）が違うため、後者で統一すると初心者にとって直感的
- **L-014**: GitHub の Secrets 設定ページの **「New repository secret」ボタンは状態によって位置が変わる**：未設定（空）のときはセクション中央の大きな緑ボタン、既に 1 個以上ある状態では右上の小さなボタン。指示を書くときは「画面中央」「画面右上」と固定的に書かず、「`New repository secret` ボタンをクリック」と書いて UI 状態に依存しない方が安全（実例: 2026-05-04、未設定状態に対して「右上」と案内したらユーザーから中央であると指摘を受けた）
- **L-015**: GitHub Actions の `actions/setup-python@v5` で `cache: 'pip'` を指定すると、依存リストファイル（`requirements.txt` か `pyproject.toml`）の **存在が必須**。無いとセットアップ段階で `Error: No file matched to ... requirements.txt` で失敗する（実例: 2026-05-04、Muroto への workflow 移植時に `update_data.yml` / `sync_after_current_update.yml` / `rebuild_master.yml` の 3 本でこの失敗を踏んだ）。**対策**: リポジトリ直下に `requirements.txt` を 1 つ置く（依存ゼロでも空ファイルで OK、ただし workflow 内に `pip install -r requirements.txt` ステップがあるならその時必要なパッケージは記述しておく）。Python を使う workflow を移植・新設するときは setup-python のキャッシュ依存を最初に確認する習慣にすること
- **L-017**: GitHub Actions 等で `python -m パッケージ.モジュール` のようにモジュール形式で実行する場合、対象モジュール内の同一パッケージ間の import は相対 import（`from .X import ...`）が必須。絶対 import（`from X import ...`）は `python script.py` のようなスクリプト形式実行では動くが、`python -m パッケージ.モジュール` 形式では `ModuleNotFoundError` で失敗する（実例: 2026-05-04、Muroto 移植時に `shared/engines/main.py` / `downloader.py` / `processor.py` の 5 箇所がこれを踏んだ）。**対策**: workflow で `python -m` 呼び出しに切り替えるとき、または既存スクリプトを `-m` で呼ぶ前提で配置するとき、必ず内部 import を相対形式に変換する。Claude Code は方針 D で 1 試行で発見・修正できた良い反復事例。

---

## 10. 改訂履歴

| 改訂日 | 版 | 内容 |
|---|---|---|
| 2026-05-04 | V1 | 初版作成。fishing-system-muroto の workflow 移植プロジェクトを契機に整備 |

---

## 11. このガイドの更新ルール

- **更新タイミング**: 各プロジェクトの実装完了後、横展開可能な知見が出たとき
- **更新者**: Cowork Claude（Gonti さんの了承を得て）
- **更新場所**: §9 知見ログに L-NNN 形式で追記、§10 改訂履歴に版を立てる
- **大改訂**: §3〜§8 の規約に変更がある場合、版を上げる（V1 → V2）

---

**末尾**: 本ガイドは Cowork（ノートPC）で運用される。sandbox-01 上の Claude Code は本ガイドを **読み取り専用** で参照する（編集は Cowork 経由で行う）。
