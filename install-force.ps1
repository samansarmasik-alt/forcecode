$ErrorActionPreference = "Stop"

$root = Join-Path $env:LOCALAPPDATA "ForgeCode"
$app = Join-Path $root "app"
$bin = Join-Path $root "bin"
$launcher = Join-Path $bin "Force.cmd"
$sourceFiles = @(
    "forgecode.bat",
    "forgecode.py",
    "_forgecode_mission.py",
    "forgecode_base.py",
    "forgecode_config.py",
    "forgecode_stores.py",
    "forgecode_providers.py",
    "forgecode_queues.py",
    "forgecode_workspace.py",
    "forgecode_sandbox.py",
    "forgecode_skills.py",
    "forgecode_mcp.py",
    "forgecode_context.py"
)

foreach ($name in $sourceFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name))) {
        throw "ForgeCode kurulum dosyası bulunamadı: $name"
    }
}

New-Item -ItemType Directory -Path $app -Force | Out-Null
New-Item -ItemType Directory -Path $bin -Force | Out-Null
foreach ($name in $sourceFiles) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $app $name) -Force
}
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
