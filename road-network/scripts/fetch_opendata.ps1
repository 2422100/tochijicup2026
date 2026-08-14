# 東京都オープンデータ 一括取得（CC BY / 出典明記のこと）
# 実行: PowerShell で  .\scripts\fetch_opendata.ps1
$ErrorActionPreference = "Stop"
$dst = Join-Path $PSScriptRoot "..\20_external\tokyo_child"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
$items = @(
  @{ f="bousai_tyousa_822_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_822_1" }
  @{ f="bousai_tyousa_822_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_822_2" }
  @{ f="bousai_tyousa_831_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_831_1" }
  @{ f="bousai_tyousa_831_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_831_2" }
  @{ f="bousai_tyousa_832.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_832" }
  @{ f="bousai_tyousa_849.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_849" }
  @{ f="bousai_tyousa_850_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_850_1" }
  @{ f="bousai_tyousa_850_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_850_2" }
  @{ f="bousai_tyousa_851_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_851_1" }
  @{ f="bousai_tyousa_851_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_851_2" }
  @{ f="bousai_tyousa_852_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_852_1" }
  @{ f="bousai_tyousa_852_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_852_2" }
  @{ f="bousai_tyousa_853_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_853_1" }
  @{ f="bousai_tyousa_853_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_853_2" }
  @{ f="bousai_tyousa_854_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_854_1" }
  @{ f="bousai_tyousa_854_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_854_2" }
  @{ f="bousai_tyousa_855_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_855_1" }
  @{ f="bousai_tyousa_855_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_855_2" }
  @{ f="bousai_tyousa_856_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_856_1" }
  @{ f="bousai_tyousa_856_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_856_2" }
  @{ f="bousai_tyousa_857_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_857_1" }
  @{ f="bousai_tyousa_857_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_857_2" }
  @{ f="bousai_tyousa_858_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_858_1" }
  @{ f="bousai_tyousa_858_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_858_2" }
  @{ f="bousai_tyousa_859_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_859_1" }
  @{ f="bousai_tyousa_859_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_859_2" }
  @{ f="bousai_tyousa_860_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_860_1" }
  @{ f="bousai_tyousa_860_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_860_2" }
  @{ f="bousai_tyousa_861_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_861_1" }
  @{ f="bousai_tyousa_861_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_861_2" }
  @{ f="bousai_tyousa_862_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_862_1" }
  @{ f="bousai_tyousa_862_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_862_2" }
  @{ f="bousai_tyousa_863_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_863_1" }
  @{ f="bousai_tyousa_863_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_863_2" }
  @{ f="bousai_tyousa_864_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_864_1" }
  @{ f="bousai_tyousa_864_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_864_2" }
  @{ f="bousai_tyousa_865_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_865_1" }
  @{ f="bousai_tyousa_865_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_865_2" }
  @{ f="bousai_tyousa_866_1.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_866_1" }
  @{ f="bousai_tyousa_866_2.csv"; u="https://www.fukushi.metro.tokyo.lg.jp/documents/d/fukushi/bousai_tyousa_866_2" }
  @{ f="130001_evacuation_center.csv"; u="https://www.opendata.metro.tokyo.lg.jp/soumu/130001_evacuation_center.csv" }
  @{ f="130001_evacuation_area.csv"; u="https://www.opendata.metro.tokyo.lg.jp/soumu/130001_evacuation_area.csv" }
  @{ f="130001_evacuation_center-area_spec.xlsx"; u="https://www.opendata.metro.tokyo.lg.jp/soumu/R4/130001_evacuation_center-area_spec.xlsx" }
)
$ok = 0; $ng = @()
foreach ($i in $items) {
  $out = Join-Path $dst $i.f
  if ((Test-Path $out) -and ((Get-Item $out).Length -gt 0)) { $ok++; continue }
  try {
    Invoke-WebRequest -Uri $i.u -OutFile $out -UserAgent $ua -TimeoutSec 60
    Write-Host ("OK   " + $i.f + "  (" + (Get-Item $out).Length + " bytes)")
    $ok++
  } catch {
    Write-Host ("FAIL " + $i.f + "  " + $_.Exception.Message) -ForegroundColor Red
    $ng += $i.f
  }
  Start-Sleep -Milliseconds 300
}
Write-Host ""
Write-Host ("取得成功 " + $ok + " / " + $items.Count)
if ($ng.Count -gt 0) { Write-Host "失敗:"; $ng | ForEach-Object { Write-Host ("  " + $_) } }
Write-Host ("保存先: " + (Resolve-Path $dst))
