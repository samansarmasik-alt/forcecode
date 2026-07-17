$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "ForgeCode"
$app = Join-Path $root "app"
$bin = Join-Path $root "bin"
$launcher = Join-Path $bin "Force.cmd"

if (Test-Path -LiteralPath $launcher) {
    Remove-Item -LiteralPath $launcher -Force
}
if (Test-Path -LiteralPath $app) {
    Remove-Item -LiteralPath $app -Recurse -Force
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$entries = @($userPath -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ine $bin.TrimEnd("\") })
[Environment]::SetEnvironmentVariable("Path", ($entries -join ";"), "User")
Write-Host "Force komutu ve uygulama dosyaları kaldırıldı. Kullanıcı ayarlarınız $root içinde korundu." -ForegroundColor Green
