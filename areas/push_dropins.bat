@echo off
setlocal enabledelayedexpansion
title push_dropins - drop_inbox auto push

REM ========================================================================
REM push_dropins.bat - drop_inbox 配置済の釣果CSVを自動 commit ^& push
REM
REM 配置:    areas/push_dropins.bat
REM 使い方:  drop_inbox に fishing_data_^<boat_id^>.csv を置いてダブルクリック
REM 対応:    areas/*/drop_inbox/fishing_data_*.csv (複数海域 OK)
REM 動作:    [1/5] git add → [2/5] 3層スキャン → [3/5] メッセージ生成
REM          → [4/5] commit → [5/5] push origin HEAD:main
REM
REM 文字コード: Shift-JIS (CP932) で保存。Windows 日本語環境の標準。
REM             chcp 65001 は使わない (UTF-8 ファイルとの混乱回避のため)。
REM ========================================================================

echo.
echo ========================================
echo  drop_inbox 釣果データ自動 push
echo ========================================
echo.

REM スクリプトの親ディレクトリ = areas/、その親 = リポジトリルート
cd /d "%~dp0\.."

echo [1/5] drop_inbox の変更を検出中...
echo.
git add areas/*/drop_inbox/fishing_data_*.csv 2>nul

git diff --staged --quiet
if !errorlevel! == 0 (
  echo ----------------------------------------
  echo 変更がありません。
  echo.
  echo drop_inbox に fishing_data_^<boat_id^>.csv を
  echo 置いてから、もう一度実行してください。
  echo.
  echo 配置先の例:
  echo   areas\muroto\drop_inbox\fishing_data_muroto1.csv
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

echo [2/5] 3層セキュリティスキャン実行中...
echo.

REM bash (Git for Windows) を探して PATH に追加
where bash >nul 2>&1
if !errorlevel! neq 0 (
  if exist "C:\Program Files\Git\bin\bash.exe" (
    set "PATH=%PATH%;C:\Program Files\Git\bin"
  ) else if exist "C:\Program Files\Git\usr\bin\bash.exe" (
    set "PATH=%PATH%;C:\Program Files\Git\usr\bin"
  ) else if exist "C:\Program Files (x86)\Git\bin\bash.exe" (
    set "PATH=%PATH%;C:\Program Files (x86)\Git\bin"
  ) else (
    echo ----------------------------------------
    echo bash (Git for Windows) が見つかりません。
    echo.
    echo Git for Windows をインストールするか、
    echo bash.exe の場所を PATH に追加してください。
    echo.
    echo  https://gitforwindows.org/
    echo ----------------------------------------
    git reset HEAD areas/*/drop_inbox/fishing_data_*.csv > nul 2>&1
    echo.
    pause
    exit /b 1
  )
)

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
  git reset HEAD areas/*/drop_inbox/fishing_data_*.csv > nul 2>&1
  echo.
  pause
  exit /b 1
)

echo.
echo [3/5] コミットメッセージ生成中...

REM ステージングされたファイル名から boat_id を抽出
set BOATS=
for /f "tokens=*" %%f in ('git diff --staged --name-only') do (
  set FNAME=%%~nf
  REM "fishing_data_muroto1" を _ 区切り → tokens=3 が boat_id
  for /f "tokens=3 delims=_" %%b in ("!FNAME!") do (
    REM 重複排除 (前後を / で囲んで部分一致誤検知を避ける)
    echo /!BOATS!/ | findstr /C:"/%%b/" >nul
    if !errorlevel! neq 0 (
      if "!BOATS!"=="" (
        set BOATS=%%b
      ) else (
        set BOATS=!BOATS!/%%b
      )
    )
  )
)

REM 日付取得 (PowerShell 経由で yyyy-MM-dd HH:mm)
for /f "usebackq tokens=*" %%d in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"`) do set TIMESTAMP=%%d

set MSG=feat(catch): drop_inbox 釣果追加 !BOATS! [!TIMESTAMP!]
echo.
echo メッセージ: !MSG!
echo.

echo [4/5] commit 実行中...
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
echo [5/5] push 実行中 (origin HEAD:main)...
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
echo.
echo   本番URL:
echo     https://supergonti.github.io/fishing-system-muroto/
echo.
echo   GitHub Actions 進行状況:
echo     https://github.com/SuperGonti/fishing-system-muroto/actions
echo.
pause
exit /b 0
