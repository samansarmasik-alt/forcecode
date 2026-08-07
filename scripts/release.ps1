param(
    [string]$Version = "",
    [string]$Token = "",
    [string]$RemoteUrl = "https://github.com/samansarmasik-alt/forcecode.git",
    [string]$Branch = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) { $PSNativeCommandUseErrorActionPreference = $false }

function Fail($msg) { Write-Host "HATA: $msg" -ForegroundColor Red; exit 1 }
function Info($msg) { Write-Host $msg -ForegroundColor Cyan }
function Ok($msg) { Write-Host $msg -ForegroundColor Green }

# git binary — git.exe kullan, yoksa git (alias tuzağını önler: ls-remote -> Get-ChildItem)
$GitBin = "git"
try {
    $g = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($g) { $GitBin = $g.Source }
    else {
        $g2 = Get-Command git -ErrorAction SilentlyContinue
        if ($g2) { $GitBin = $g2.Source }
    }
} catch {}
Info "Git: $GitBin"

function Invoke-Git {
    param([string[]]$Args, [switch]$AllowFail)
    # native git çağrısı — alias genişletmesi yok çünkü komut değişkende
    $out = & $GitBin @Args 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $out) { Write-Host $line -ForegroundColor DarkGray }
    if (-not $AllowFail -and $code -ne 0) { Fail "git $($Args -join ' ') basarisiz (exit $code)" }
    return $code
}

# 0) Proje kökü
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
Info "Proje kok: $Root"

# 1) Versiyon
if (-not $Version) {
    $pyLine = Select-String -Path "forgecode.py" -Pattern '^VERSION = "([^"]+)"' | Select-Object -First 1
    if (-not $pyLine) { Fail "forgecode.py icinde VERSION bulunamadi" }
    $Version = $pyLine.Matches[0].Groups[1].Value
    Info "Versiyon forgecode.py'den alindi: $Version"
}
$Tag = "v$Version"
# Branch otomatik tespit: parametre boşsa mevcut branch'i kullan (master/main uyumu)
$CurrentBranch = ""
try { $CurrentBranch = (& $GitBin rev-parse --abbrev-ref HEAD 2>$null).Trim() } catch {}
if (-not $Branch -or $Branch -eq "") {
    if ($CurrentBranch -and $CurrentBranch -ne "HEAD") { $Branch = $CurrentBranch }
    else { $Branch = "main" }
}
Info "Tag: $Tag  Branch: $Branch (mevcut: $CurrentBranch)"

# 2) forgecode.py <-> pyproject.toml eşitle
$tomlMatch = Select-String -Path "pyproject.toml" -Pattern '^version = "([^"]+)"' | Select-Object -First 1
$pyMatch   = Select-String -Path "forgecode.py" -Pattern '^VERSION = "([^"]+)"' | Select-Object -First 1
$tomlVer = $tomlMatch.Matches[0].Groups[1].Value
$pyVer   = $pyMatch.Matches[0].Groups[1].Value
if ($pyVer -ne $tomlVer) {
    Info "Versiyon uyusmazligi: forgecode.py=$pyVer  pyproject.toml=$tomlVer -> pyproject.toml guncelleniyor..."
    (Get-Content pyproject.toml -Raw) -replace 'version = "[^"]+"', "version = `"$Version`"" | Set-Content pyproject.toml -NoNewline -Encoding utf8
    Ok "pyproject.toml $Version olarak guncellendi"
}
if ($pyVer -ne $Version) {
    Info "forgecode.py VERSION $pyVer -> $Version olarak guncelleniyor..."
    (Get-Content forgecode.py -Raw) -replace 'VERSION = "[^"]+"', "VERSION = `"$Version`"" | Set-Content forgecode.py -NoNewline -Encoding utf8
    Ok "forgecode.py $Version olarak guncellendi"
}

# 3) Gizli anahtar taraması
Info "Gizli anahtar taramasi..."
$hits = Select-String -Path forgecode.py,pyproject.toml -Pattern '(sk-ant-|sk-proj-|ghp_|github_pat_|AKIA)' 2>$null
if ($hits) { Fail "Olasi gizli anahtar bulundu:`n$($hits | Out-String)" }
Ok "Temiz."

# 4) Syntax + test
Info "Syntax kontrol..."
$py = $null
foreach ($c in @("py -3","python","python3")) {
    try { Invoke-Expression "$c -m py_compile forgecode.py" 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
}
if (-not $py) {
    try { python -m py_compile forgecode.py; if ($LASTEXITCODE -ne 0) { Fail "py_compile basarisiz" } ; $py="python" } catch { Fail "Python bulunamadi — https://www.python.org/downloads/" }
}
Ok "py_compile OK ($py)"

if (-not $SkipTests) {
    Info "Testler calistiriliyor..."
    Invoke-Expression "$py -m unittest discover -s tests -v"
    if ($LASTEXITCODE -ne 0) { Fail "Testler basarisiz — push durduruldu" }
    Ok "Testler OK"
} else {
    Info "Testler atlandi (--SkipTests)"
}

# 5) Git hazırla
try { & $GitBin --version | Out-Null } catch { Fail "git bulunamadi" }
if (-not (Test-Path ".git")) {
    Info "Git repo yok -> git init"
    & $GitBin init | Out-Null
    & $GitBin branch -M $Branch | Out-Null
}
# branch ismini düzelt: master üzerindeysek ve main isteniyorsa main'e çevir ya da mevcutta kal
if ($CurrentBranch -eq "master" -and $Branch -eq "main") {
    # master var, main isteniyor — master'ı main olarak push edeceğiz, yerel branch'i de main yap
    Info "Yerel branch master -> main'e geciliyor"
    & $GitBin branch -M main 2>&1 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
    $Branch = "main"
    $CurrentBranch = "main"
}
$remote = & $GitBin remote 2>$null
if (-not ($remote -match "origin")) {
    Info "Remote ekleniyor: origin -> $RemoteUrl"
    & $GitBin remote add origin $RemoteUrl | Out-Null
} else {
    $cur = & $GitBin remote get-url origin 2>$null
    Info "Mevcut remote origin: $cur"
    if ($cur -ne $RemoteUrl) {
        Info "Remote guncelleniyor -> $RemoteUrl"
        & $GitBin remote set-url origin $RemoteUrl | Out-Null
    }
}

# Token env fallback
if (-not $Token) {
    if ($env:GITHUB_TOKEN) { $Token = $env:GITHUB_TOKEN; Info "Token GITHUB_TOKEN env'den alindi" }
    elseif ($env:GH_TOKEN) { $Token = $env:GH_TOKEN; Info "Token GH_TOKEN env'den alindi" }
}

# 6) Commit
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $GitBin add . 2>&1 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
$addCode = $LASTEXITCODE
$ErrorActionPreference = $prevPref
if ($addCode -ne 0) { Fail "git add basarisiz (exit $addCode)" }
& $GitBin diff --cached --quiet 2>$null; $code = $LASTEXITCODE
if ($code -ne 0) {
    $msg = "chore: release $Tag"
    Info "Commit: $msg"
    & $GitBin commit -m $msg 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Fail "git commit basarisiz" }
    Ok "Commit OK"
} else {
    Info "Commit edilecek degisiklik yok — var olan commit kullanilacak"
}

# 7) Tag
$existingTag = & $GitBin tag --list $Tag 2>$null
if ($existingTag) {
    Info "Tag $Tag zaten var — yeniden olusturuluyor"
    & $GitBin tag -d $Tag 2>$null | Out-Null
}
& $GitBin tag $Tag 2>&1 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) { Fail "git tag basarisiz" }
Ok "Tag olusturuldu: $Tag"

# 8) Push
Info "Push ediliyor: $Branch + $Tag  -> $RemoteUrl"
$env:GIT_TERMINAL_PROMPT = "0"
if ($Token) {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$Token"))
    & $GitBin -c http.extraHeader="Authorization: Basic $b64" push -u origin $Branch 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Fail "git push $Branch basarisiz — token yetkisini kontrol et (repo scope)." }
    & $GitBin -c http.extraHeader="Authorization: Basic $b64" push origin $Tag 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Fail "git push tag basarisiz" }
} else {
    # gh veya credential helper uzerinden
    & $GitBin push -u origin $Branch 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "" -ForegroundColor Yellow
        Write-Host "git push basarisiz — kimlik dogrulanamadi." -ForegroundColor Yellow
        Write-Host "Cozumlerden birini yap:" -ForegroundColor Yellow
        Write-Host "  1) .\scripts\release.ps1 -Token ghp_xxx            (token ile)" -ForegroundColor White
        Write-Host "  2) `$env:GITHUB_TOKEN='ghp_xxx'; .\scripts\release.ps1" -ForegroundColor White
        Write-Host "  3) gh auth login  (tarayici ile giris) sonra tekrar dene" -ForegroundColor White
        Fail "git push $Branch basarisiz — auth gerekli"
    }
    & $GitBin push origin $Tag 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Fail "git push tag basarisiz" }
}
Ok "Push OK"

# 9) Doğrulama — ls-remote alias tuzağı olmadan
Info "Dogrulama: git ls-remote --tags origin"
& $GitBin ls-remote --tags origin 2>&1 | Select-String $Tag | ForEach-Object { Write-Host $_ }
& $GitBin ls-remote --heads origin 2>&1 | Select-String $Branch | ForEach-Object { Write-Host $_ -ForegroundColor Green }

$releaseUrl = "https://github.com/samansarmasik-alt/forcecode/releases/tag/$Tag"
$repoUrl    = "https://github.com/samansarmasik-alt/forcecode/tree/$Branch"
Ok ""
Ok "Tamamlandi!"
Write-Host "  Repo   : $repoUrl" -ForegroundColor White
Write-Host "  Release: $releaseUrl" -ForegroundColor White
Write-Host "  Actions: https://github.com/samansarmasik-alt/forcecode/actions" -ForegroundColor White
Write-Host ""
Write-Host "GitHub Actions 'Release' workflow tag'i gorunce otomatik calisir ve dist/*.whl + ForgeCode-v*.zip'i Releases'e ekler." -ForegroundColor Gray
Write-Host "Bitti demeden once Actions'in yesil oldugunu kontrol et." -ForegroundColor Gray
