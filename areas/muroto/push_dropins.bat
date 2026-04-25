@echo off
setlocal enabledelayedexpansion
title push_dropins (muroto) - drop_inbox auto push

REM ========================================================================
REM areas/muroto/push_dropins.bat - muroto 海域 drop_inbox 専用
REM
REM 配置:    areas/muroto/push_dropins.bat
REM 使い方:  drop_inbox に fishing_data_^<boat_id^>.csv を置いてダブルクリック
REM 対応:    areas/muroto/drop_inbox/fishing_data_*.csv (muroto1/2/3)
REM 動作:    [1/6] モード選択 → [2/6] git add → [3/6] replace事前検証
REM          → [4/6] 3層スキャン → [5/6] commit → [6/6] push origin HEAD:main
REM
REM モード:
REM   [1] 追記のみ (add)     - 投入CSVから新規行のみ master に追加 (既存挙動)
REM   [2] 全置換 (replace)   - boat_id 単位で master を入れ替え (削除+追加)
REM
REM 文字コード: Shift-JIS (CP932) で保存。Windows 日本語環境の標準。
REM             chcp 65001 は使わない (UTF-8 ファイルとの混乱回避のため)。
REM ========================================================================

echo.
echo ========================================
echo  drop_inbox 釣果データ自動 push (muroto)
echo ========================================
echo.

REM スクリプトの3階層上: areas/muroto/ → areas/ → リポジトリルート
cd /d "%~dp0\..\.."

echo [1/6] モード選択
echo.
echo   [1] 追記のみ（既存挙動）
echo   [2] 全置換（boat_id 単位で master を入れ替え）
echo   [3] キャンセル
echo.
set MODE=
set /p MODE_CHOICE=選択 (1/2/3):

if "!MODE_CHOICE!"=="1" set MODE=add
if "!MODE_CHOICE!"=="2" set MODE=replace
if "!MODE_CHOICE!"=="3" goto cancelled
if "!MODE!"=="" (
  echo.
  echo 不正な入力です。1/2/3 のいずれかを選択してください。
  pause
  exit /b 1
)

echo モード: !MODE!
echo.

echo [2/6] drop_inbox の変更を検出中...
echo.
git add areas/muroto/drop_inbox/fishing_data_*.csv 2>nul

git diff --staged --quiet
if !errorlevel! == 0 (
  echo ----------------------------------------
  echo 変更がありません。
  echo.
  echo drop_inbox に fishing_data_^<boat_id^>.csv を
  echo 置いてから、もう一度実行してください。
  echo.
  echo 配置先:
  echo   areas\muroto\drop_inbox\fishing_data_muroto1.csv
  echo   areas\muroto\drop_inbox\fishing_data_muroto2.csv
  echo   areas\muroto\drop_inbox\fishing_data_muroto3.csv
  echo ----------------------------------------
  echo.
  pause
  exit /b 0
)

echo ----------------------------------------
echo 追加されるファイル:
echo ----------------------------------------
git diff --staged --name-only
echo.

REM ステージされたファイルから boat_id 一覧を抽出
set STAGED_BOATS=
for /f "tokens=*" %%f in ('git diff --staged --name-only') do (
  set FNAME=%%~nf
  for /f "tokens=3 delims=_" %%b in ("!FNAME!") do (
    echo /!STAGED_BOATS!/ | findstr /C:"/%%b/" >nul
    if !errorlevel! neq 0 (
      if "!STAGED_BOATS!"=="" (
        set STAGED_BOATS=%%b
      ) else (
        set STAGED_BOATS=!STAGED_BOATS! %%b
      )
    )
  )
)

REM ============================================
REM [3/6] replace モード時の事前検証
REM ============================================
if "!MODE!"=="replace" (
  echo [3/6] 全置換モードのプレビュー
  echo.

  set WARN=
  set MASTER_PATH=areas/muroto/data/master_catch.csv

  for %%b in (!STAGED_BOATS!) do (
    REM master_catch.csv の該当 boat_id 行数（27列目=boat_id）
    for /f %%n in ('powershell -NoProfile -Command "if (Test-Path '!MASTER_PATH!') { (Get-Content '!MASTER_PATH!' -Encoding UTF8 | Select-Object -Skip 1 | Where-Object { ($_ -split ',')[26] -eq '%%b' }).Count } else { 0 }"') do set EXIST_COUNT=%%n
    REM 投入 CSV の行数（ヘッダー除く）
    for /f %%n in ('powershell -NoProfile -Command "(Get-Content 'areas/muroto/drop_inbox/fishing_data_%%b.csv' -Encoding UTF8 | Select-Object -Skip 1).Count"') do set NEW_COUNT=%%n

    echo   %%b: 既存!EXIST_COUNT!行 -^> 投入!NEW_COUNT!行

    set /a HALF=!EXIST_COUNT! / 2
    if !NEW_COUNT! lss !HALF! (
      echo   *** WARNING: 投入が既存の50%%未満です ***
      set WARN=1
    )
    if !NEW_COUNT! equ 0 (
      echo   *** ERROR: 投入が0行 -^> replace 中止 ***
      goto cancel_stage
    )
  )

  echo.
  if "!WARN!"=="1" (
    set CONFIRM=
    set /p CONFIRM=このまま replace を続行しますか? (y/N):
    if /i not "!CONFIRM!"=="y" goto cancel_stage
    echo.
  )

  REM 削除予定 record_id プレビュー（最初5件）
  echo === 削除予定 record_id (最初5件) ===
  for %%b in (!STAGED_BOATS!) do (
    echo   [%%b]
    powershell -NoProfile -Command "if (Test-Path '!MASTER_PATH!') { Get-Content '!MASTER_PATH!' -Encoding UTF8 | Select-Object -Skip 1 | Where-Object { ($_ -split ',')[26] -eq '%%b' } | Select-Object -First 5 | ForEach-Object { '    ' + ($_ -split ',')[0] } }"
  )
  echo.

  set FINAL=
  set /p FINAL=最終確認: 上記を削除して新規行で置換します。実行? (y/N):
  if /i not "!FINAL!"=="y" goto cancel_stage
  echo.

  REM マーカーファイル生成 + git add
  for %%b in (!STAGED_BOATS!) do (
    type nul > "areas\muroto\drop_inbox\.replace_%%b"
    git add "areas/muroto/drop_inbox/.replace_%%b"
    echo マーカー作成: .replace_%%b
  )
  echo.
)

echo [4/6] 3層セキュリティスキャン実行中...
echo.

REM bash (Git for Windows) を探して PATH に追加
where bash >nul 2>&1
if !errorlevel! == 0 goto scan_run

if exist "C:\Program Files\Git\bin\bash.exe" (
  set "PATH=%PATH%;C:\Program Files\Git\bin"
  goto scan_run
)
if exist "C:\Program Files\Git\usr\bin\bash.exe" (
  set "PATH=%PATH%;C:\Program Files\Git\usr\bin"
  goto scan_run
)
if exist "C:\Program Files (x86)\Git\bin\bash.exe" (
  set "PATH=%PATH%;C:\Program Files (x86)\Git\bin"
  goto scan_run
)

echo ----------------------------------------
echo bash (Git for Windows) が見つかりません。
echo.
echo Git for Windows をインストールするか、
echo bash.exe の場所を PATH に追加してください。
echo.
echo  https://gitforwindows.org/
echo ----------------------------------------
goto cancel_stage

:scan_run
REM check_secrets.py の cp932 不具合 (絵文字 UnicodeEncodeError) 回避
set PYTHONIOENCODING=utf-8

bash "C:/Claude/tools/scan_3layer.sh" "%CD%"
if !errorlevel! neq 0 (
  echo.
  echo ----------------------------------------
  echo セキュリティスキャンで検出 / ツール不備
  echo push を中止します。
  echo ステージングを取り消しました。
  echo ----------------------------------------
  goto cancel_stage
)

echo.
echo [5/6] コミットメッセージ生成中...

REM 日付取得 (PowerShell 経由で yyyy-MM-dd HH:mm)
for /f "usebackq tokens=*" %%d in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"`) do set TIMESTAMP=%%d

REM スラッシュ区切り boat_id 文字列を作成（コミットメッセージ用）
set BOATS=
for %%b in (!STAGED_BOATS!) do (
  if "!BOATS!"=="" (
    set BOATS=%%b
  ) else (
    set BOATS=!BOATS!/%%b
  )
)

if "!MODE!"=="replace" (
  set MSG=feat^(catch^): drop_inbox 全置換 [replace] !BOATS! [!TIMESTAMP!]
) else (
  set MSG=feat^(catch^): drop_inbox 釣果追加 !BOATS! [!TIMESTAMP!]
)
echo.
echo メッセージ: !MSG!
echo.

echo commit 実行中...
git commit -m "!MSG!"
if !errorlevel! neq 0 (
  echo.
  echo ----------------------------------------
  echo commit に失敗しました。
  echo.
  echo git config が未設定の可能性があります:
  echo   git config user.name "your-name"
  echo   git config user.email "your-email@example.com"
  echo ----------------------------------------
  echo.
  pause
  exit /b 1
)

echo.
echo [6/6] push 実行中 (origin HEAD:main)...
git push origin HEAD:main
if !errorlevel! neq 0 (
  echo.
  echo ----------------------------------------
  echo push に失敗しました。
  echo 認証エラーまたはネットワーク不調の可能性があります。
  echo 認証情報を確認後、再実行してください。
  echo (commit は完了しているため、push のみで再試行可)
  echo ----------------------------------------
  echo.
  pause
  exit /b 1
)

echo.
echo ========================================
echo  完了
echo ========================================
echo.
echo CI が完了するまで 3?5 分かかります。
if "!MODE!"=="replace" (
  echo.
  echo replace モードのバックアップ:
  echo   areas\muroto\data\_backups\master_catch_^<JST^>.csv
  echo   ^(CI が同一コミット内で生成^)
)
echo.
echo   本番URL:
echo     https://supergonti.github.io/fishing-system-muroto/
echo.
echo   GitHub Actions 進行状況:
echo     https://github.com/SuperGonti/fishing-system-muroto/actions
echo.
pause
exit /b 0

:cancel_stage
echo.
echo 操作をキャンセルしました。ステージとマーカーを解除します。
git reset HEAD areas/muroto/drop_inbox/fishing_data_*.csv > nul 2>&1
git reset HEAD areas/muroto/drop_inbox/.replace_* > nul 2>&1
for %%f in (areas\muroto\drop_inbox\.replace_*) do del "%%f" 2>nul
echo.
pause
exit /b 0

:cancelled
echo.
echo キャンセルされました。
pause
exit /b 0
