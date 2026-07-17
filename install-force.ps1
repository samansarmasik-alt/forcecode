$ErrorActionPreference = "Stop"

$root = Join-Path $env:LOCALAPPDATA "ForgeCode"
$app = Join-Path $root "app"
$bin = Join-Path $root "bin"
$launcher = Join-Path $bin "Force.cmd"
$sourceBat = Join-Path $PSScriptRoot "forgecode.bat"
$sourcePython = Join-Path $PSScriptRoot "forgecode.py"

if (-not (Test-Path -LiteralPath $sourceBat) -or -not (Test-Path -LiteralPath $sourcePython)) {
    throw "forgecode.bat veya forgecode.py kurulum dosyası bulunamadı."
}

New-Item -ItemType Directory -Path $app -Force | Out-Null
New-Item -ItemType Directory -Path $bin -Force | Out-Null
Copy-Item -LiteralPath $sourceBat -Destination (Join-Path $app "forgecode.bat") -Force
Copy-Item -LiteralPath $sourcePython -Destination (Join-Path $app "forgecode.py") -Force
$installedBat = Join-Path $app "forgecode.bat"
$content = "@echo off`r`ncall `"$installedBat`" `"%CD%`" %*`r`n"
[System.IO.File]::WriteAllText($launcher, $content, [System.Text.UTF8Encoding]::new($false))

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$entries = @($userPath -split ";" | Where-Object { $_ })
if (-not ($entries | Where-Object { $_.TrimEnd("\") -ieq $bin.TrimEnd("\") })) {
    $newPath = (($entries + $bin) -join ";")
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
}

Write-Host ""
Write-Host "ForgeCode global komutu kuruldu." -ForegroundColor Green
Write-Host "Uygulama: $app" -ForegroundColor DarkGray
Write-Host "Kullanıcı ayarları: $root" -ForegroundColor DarkGray
Write-Host "Yeni bir CMD veya PowerShell penceresi açın, ardından herhangi bir klasörde:" -ForegroundColor Cyan
Write-Host "  Force" -ForegroundColor White
Write-Host ""
Write-Host "Komut o an bulunduğunuz klasörü proje kökü olarak açacaktır."
