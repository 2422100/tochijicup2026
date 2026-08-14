<#
  tochijicup2026 へ安全に持ち込むスクリプト

  共有リポジトリの構造:
      tochijicup2026/
        road-network/   ← ここに入れる（あなたの担当）
        tokyo-3d-map/   ← 他の人の担当。一切触らない

  このフォルダ(C:\claudeProject\tokyoHackthon\project)は共有リポジトリと
  履歴がつながっていない独立リポジトリなので、ここからは push しない。
  共有リポジトリを別の場所へ clone し、ブランチを切ってコピーする。

  commit も push もこのスクリプトはやらない。手順を表示するだけ。

  使い方:
    .\scripts\sync_to_shared.ps1            → 報告のみ（何も変更しない）
    .\scripts\sync_to_shared.ps1 -Apply     → ブランチを切ってコピー
#>
param(
  [string]$Repo    = "https://github.com/2422100/tochijicup2026.git",
  [string]$Prefix  = "road-network",
  [string]$Branch  = "feat/child-evacuation-ui",
  [string]$WorkDir = "C:\claudeProject\shared",
  [switch]$Apply
)
# git は正常時でも stderr に出力する（"Already on main" など）。
# Stop にしていると、それだけでスクリプトが止まってしまうので Continue にし、
# 失敗の判定は $LASTEXITCODE で明示的に行う。
$ErrorActionPreference = "Continue"
if ($PSVersionTable.PSVersion.Major -ge 7) {
  $PSNativeCommandUseErrorActionPreference = $false
}
function Invoke-Git {
  param([string[]]$GitArgs, [switch]$AllowFail)
  & git @GitArgs
  if ($LASTEXITCODE -ne 0 -and -not $AllowFail) {
    Write-Host ("git " + ($GitArgs -join " ") + " が失敗しました (code " + $LASTEXITCODE + ")") -ForegroundColor Red
    exit 1
  }
}
$src = Split-Path -Parent $PSScriptRoot

# ---- 持ち込むファイル（$src からの相対パス。コピー先は $Prefix の下）----
$files = @(
  "index.html", "data_index.html", "child_nav.html", ".nojekyll",
  "README.md", "RESUME.md",
  "scripts\05_network.py", "scripts\07_maps.py", "scripts\08_child.py",
  "scripts\09_child_map.py", "scripts\10_app.py",
  "scripts\config_weights.json", "scripts\fetch_opendata.ps1",
  "scripts\sync_to_shared.ps1",
  "reports\child_access.csv", "reports\child_survey.json",
  "reports\child_mesh.json", "reports\stroller_qc.md",
  "reports\maps\index.html"
)
Get-ChildItem (Join-Path $src "data") -Filter *.json -ErrorAction SilentlyContinue |
  Sort-Object Name | ForEach-Object { $files += "data\" + $_.Name }

# ---- clone --------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$clone = Join-Path $WorkDir "tochijicup2026"

if (Test-Path (Join-Path $clone ".git")) {
  Write-Host "既存のcloneを更新: $clone" -ForegroundColor Cyan
  Invoke-Git @("-C", $clone, "checkout", "main")
  Invoke-Git @("-C", $clone, "pull", "--ff-only")
} else {
  Write-Host "clone: $Repo" -ForegroundColor Cyan
  Invoke-Git @("clone", $Repo, $clone)
}
Write-Host ""
Write-Host ("共有リポジトリのコミット数: " + (git -C $clone rev-list --count HEAD))
Write-Host "直近のコミット:"
git -C $clone log --oneline -8 | ForEach-Object { Write-Host ("   " + $_) }
Write-Host ""

# ---- 分類 ---------------------------------------------------------------
$new = @(); $same = @(); $conflict = @(); $missing = @()
foreach ($f in $files) {
  $s = Join-Path $src $f
  if (-not (Test-Path $s)) { $missing += $f; continue }
  $d = Join-Path $clone (Join-Path $Prefix $f)
  if (-not (Test-Path $d)) { $new += $f; continue }
  if ((Get-FileHash $s).Hash -eq (Get-FileHash $d).Hash) { $same += $f }
  else { $conflict += $f }
}

Write-Host ("● 新規追加: " + $new.Count + " ファイル") -ForegroundColor Green
$new | ForEach-Object { Write-Host ("   + $Prefix\" + $_) }
Write-Host ""
if ($same.Count -gt 0) {
  Write-Host ("● 内容が同じ（コピー不要）: " + $same.Count) -ForegroundColor DarkGray
  $same | ForEach-Object { Write-Host ("   = $Prefix\" + $_) }
  Write-Host ""
}
if ($conflict.Count -gt 0) {
  Write-Host ("★ 共有リポジトリ側と内容が違う: " + $conflict.Count) -ForegroundColor Yellow
  Write-Host "  上書きすると、他の人がこのファイルに加えた変更が" -ForegroundColor Yellow
  Write-Host "  あなたのブランチでは失われます（mainの履歴は無事です）。" -ForegroundColor Yellow
  $conflict | ForEach-Object { Write-Host ("   ! $Prefix\" + $_) }
  Write-Host ""
  Write-Host "  中身を見る:" -ForegroundColor DarkGray
  foreach ($f in $conflict) {
    Write-Host ("    git diff --no-index `"$clone\$Prefix\$f`" `"$src\$f`"") -ForegroundColor DarkGray
  }
  Write-Host ""
}
if ($missing.Count -gt 0) {
  Write-Host ("手元に無いのでスキップ: " + ($missing -join ", ")) -ForegroundColor DarkGray
  Write-Host ""
}

if (-not $Apply) {
  Write-Host "報告のみで終了。何も変更していません。" -ForegroundColor Cyan
  Write-Host "納得したら -Apply を付けて再実行してください。"
  exit 0
}

# ---- ブランチ + コピー ---------------------------------------------------
# rev-parse --verify は「無い」ときにエラー終了するので使わない。
# branch --list は在っても無くても正常終了し、無ければ空文字を返す。
$exists = (& git -C $clone branch --list $Branch) -join ""
if ([string]::IsNullOrWhiteSpace($exists)) {
  Invoke-Git @("-C", $clone, "checkout", "-b", $Branch)
} else {
  Invoke-Git @("-C", $clone, "checkout", $Branch)
}
Write-Host ("ブランチ: " + (git -C $clone rev-parse --abbrev-ref HEAD)) -ForegroundColor Cyan

foreach ($f in ($new + $conflict)) {
  $d = Join-Path $clone (Join-Path $Prefix $f)
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $d) | Out-Null
  Copy-Item (Join-Path $src $f) $d -Force
}
Write-Host ("コピー: " + ($new.Count + $conflict.Count) + " ファイル") -ForegroundColor Green
Write-Host ""
git -C $clone status --short
Write-Host ""
Write-Host "--- 次の手順（差分を確認してから）---" -ForegroundColor Cyan
Write-Host ("  cd `"$clone`"")
Write-Host   "  git diff --stat"
Write-Host   "  git add -A"
Write-Host   "  git commit -m `"road-network: 子連れ避難の統合UIを追加`""
Write-Host  ("  git push -u origin " + $Branch)
Write-Host ""
Write-Host "force push は絶対に使わないこと。" -ForegroundColor Red
