# GitHub'a Release Olarak Push — Tek Tık Kılavuzu

Bu proje `https://github.com/samansarmasik-alt/forcecode` adresine **release** olarak pushlanmaya hazırdır. Aşağıdaki adımlar, benden `githuba pushla / release yap` dediğinde neler olacağını ve senden hangi kodları isteyeceğimi anlatır.

## Benden istersen ne yaparım?

> "ForgeCode'u GitHub'a release olarak pushla" dediğinde:

1. **Git'i bağlarım** — `git remote` yoksa eklerim:
   ```
   git remote add origin https://github.com/samansarmasik-alt/forcecode.git
   ```
   Varsa doğrulayıp mevcut branch'e (main/master) ayarlarım.

2. **Versiyonu kilitlerim** — `forgecode.py` içindeki `VERSION` ile `pyproject.toml` içindeki `version` aynı olmalı (şu an `7.12.10`). Farklıysa eşitlerim.

3. **Gizli anahtar taraması** yaparım — repo içinde `sk-`, `ghp_`, `AKIA` gibi anahtar kalmış mı kontrol ederim. Varsa push'u durdurur, temizlemeni isterim.

4. **Test + derleme** — `python -m py_compile forgecode.py` ve `python -m unittest discover -s tests -v` çalıştırırım. Başarısızsa düzeltirim.

5. **Commit + Tag + Push:**
   ```
   git add .
   git commit -m "chore: release v7.12.10"
   git tag v7.12.10
   git push -u origin main
   git push origin v7.12.10
   ```
   Tag push'ı otomatik olarak GitHub Actions'taki `release.yml` workflow'unu tetikler — testleri tekrar koşar, `dist/*.whl`, `dist/*.tar.gz` ve `ForgeCode-v*.zip` üretir, `SHA256SUMS.txt` ile birlikte GitHub Releases'e ekler.

6. **Doğrulama** — `git ls-remote --tags origin` ile tag'in remote'da göründüğünü teyit ederim.

## Senden hangi kodları isteyebilirim?

GitHub'a push için **yetki** gerekir. İki seçenekten birini isteyeceğim — hangisini verirsen onunla bağlanırım:

### Seçenek A — GitHub Personal Access Token (önerilen, en kolay)
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. `Generate new token (classic)` → scope olarak `repo` işaretle
3. Token'ı kopyala ( `ghp_xxx` veya `github_pat_xxx` ile başlar)
4. Bana şöyle ver (sohbete yapıştır, log'a yazmam):
   ```
   GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   ```
   Alternatif olarak `GITHUB_TOKEN` de diyebilirsin.

Bunu alınca şu komutla push yaparım (token'ı URL'ye gömmeden, güvenli header ile):
```
git -c http.extraHeader="Authorization: Bearer GH_TOKEN" push origin main --tags
```
veya GitHub CLI ile:
```
echo GH_TOKEN | gh auth login --with-token
gh release create v7.12.10 --generate-notes
```

### Seçenek B — `gh auth login` (tarayıcı ile)
Eğer token vermek istemezsen, senden terminalinde şunu çalıştırmanı isterim:
```
gh auth login
```
Tarayıcıda GitHub hesabını onaylarsın, sonra ben `gh` üzerinden push ederim.

### Seçenek C — SSH anahtarı
SSH kullanıyorsan `git@github.com:samansarmasik-alt/forcecode.git` remote'unu kullanırım. Senden `ssh -T git@github.com` ile bağlantıyı doğrulamanı isterim.

## Hızlı tek komut

### Windows (PowerShell — proje kökünde)
```powershell
# Token ile (env veya parametre)
.\scripts\release.ps1 -Version 7.12.10 -Token ghp_xxx
# Token env'den
$env:GITHUB_TOKEN="ghp_xxx"; .\scripts\release.ps1 -Version 7.12.10
# gh zaten login ise (tokensız)
.\scripts\release.ps1 -Version 7.12.10
# Branch belirtme (otomatik algılar)
.\scripts\release.ps1 -Branch main
```

### macOS / Linux (bash — proje kökünde)
```bash
# Token ile
./scripts/release.sh --version 7.12.10 --token ghp_xxx
# Token env'den
GITHUB_TOKEN=ghp_xxx ./scripts/release.sh --version 7.12.10
# gh zaten login ise
./scripts/release.sh --version 7.12.10
# Yetki yoksa hatayı açıkça söyler ve çözüm önerir
```

Her iki script de aynı adımları yapar: remote ekle → versiyon eşitle → gizli anahtar tara → test → commit → tag → **gerçek push** → `git ls-remote` ile doğrula.

> Not: `master` branch'indeysen script otomatik olarak `main`'e taşır (GitHub varsayılanı). Mevcut branch'i korumak için `--branch master` / `-Branch master` ver.

## PowerShell alias tuzağı düzeltildi

Eski sürümde `git ls-remote` PowerShell'de `ls` alias'ı yüzünden `Get-ChildItem-remote` hatası veriyordu. Yeni `release.ps1` doğrudan `git.exe` yolunu kullanır ve `PSNativeCommandUseErrorActionPreference` ile `LF will be replaced by CRLF` uyarılarını yutar — uyarı gerçek hata değilken release durmaz.

## Sık sorulanlar

**"Kod isteyebilirsin" dedin, ne kodu?"**
GitHub token'ı (`ghp_`/`github_pat_`) veya `gh auth` onayı. Kodun kendisini zaten biliyorum — senden sadece GitHub'a yazma izni istiyorum.

**Versiyonu nasıl değiştiririm?**
`forgecode.py` satır 58 ve `pyproject.toml` satır 7 aynı olmalı. Birini değiştirirsem diğerini de değiştiririm ve `CHANGELOG.md`'ye not eklerim.

**Gizli anahtar yanlışlıkla commit'e girdi mi?**
Push öncesi tararım. `.env`, `.forgecode/`, `force-memory-export.json` zaten `.gitignore`'da. Yine de bulursam push'u durdururum.

**Release sonrası nasıl doğrularım?**
`https://github.com/samansarmasik-alt/forcecode/releases/tag/v7.12.10` adresinde `dist` dosyaları ve `SHA256SUMS.txt` görünmeli. Script sonunda indirme linkini ve checksum'ı gösteririm. Ayrıca `git ls-remote --tags origin` ile tag'i görebilirsin.

**Open source mi?**
Evet — MIT lisansı (`LICENSE`) ile public repository. Release workflow `contents: write` izniyle tag'i Releases'e dönüştürür ve `dist/*` + `ForgeCode-v*.zip` + `SHA256SUMS.txt` eklerini herkese açık yayımlar.

---
*Bu dosya release altyapısının parçasıdır. Push'u tetiklemek için sohbette "githuba release pushla" demen yeterli — gerisini ben hallederim.*
