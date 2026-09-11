# Mission Control

Mission Control, ForceCode 8'in hedef odaklı çalışma yüzeyidir. Yeni bir planner veya execution engine değildir; mevcut `GoalStore`, `TaskQueueStore`, ForceFlow, VibeCode ve verification katmanlarını tek bir akışta birleştirir.

## Komutlar

```text
/mission <hedef>          Doğrulanan normal bir ForceFlow başlatır
/mission long <hedef>     Checkpoint'li uzun VibeCode çalışması başlatır
/mission                  Aktif mission durumunu gösterir
/mission list             Bilinen mission'ları listeler
/mission show <flow-id>   Seçilen mission'ın görev grafiğini gösterir
/mission resume [flow-id] Aynı flow ve checkpoint üzerinden sürdürür
```

## Durum ve veri sahipliği

Mission kimliği, `TaskQueueStore` içindeki mevcut `flow_id` değeridir. Görev, kanıt ve ilerleme bilgisi başka bir dosyaya kopyalanmaz:

- Üst hedef ve mission bağlantısı: `.forcecode/goals.json`
- Sıralı görevler, durumlar ve verification kanıtları: `.forcecode/tasks.json`
- Uzun çalışma checkpoint'i: `.forcecode/vibe-session.json`

Görünür durum görevlerden türetilir: `failed` → `blocked`, `running` → `running`, `paused` → `paused`, `pending` → `queued`; bütün görevler doğrulanmışsa `completed`, tamamı terminal durumda fakat en az biri atlanmışsa `stopped` olur.

Görev grafiği ilk sürümde ForceFlow'un gerçek çalışma sözleşmesiyle aynıdır: görevler sıralıdır ve her görev kendinden önceki göreve bağlıdır. `/mission resume`, yalnızca seçilen `flow_id` içindeki görevleri çalıştırır; başka mission'lardaki bekleyen görevleri tüketmez.

Planlama görevler diske yazılmadan önce kesilirse mission bağlantısı hedefte kalır ve `resume` aynı kimlikle planlamayı yeniden başlatır. Tek VibeCode checkpoint deposu bulunduğu için duraklatılmış bir uzun mission varken yenisi sessizce başlatılmaz; kullanıcı önce mevcut mission'ı sürdürmeli veya açıkça durdurmalıdır.

## Kanıt ve güvenlik

Mission görünümü değişen dosyaları ve eksik verification kapılarını mevcut task receipt'lerinden okur. Yeni bir başarı skoru üretmez ve doğrulanmamış işi tamamlanmış göstermez. Kalıcı yazımlar mevcut atomik store yardımcılarından geçer; prompt, API anahtarı veya gizli reasoning için yeni bir kayıt alanı açılmaz.

`_forcecode_mission.MissionView` immutable ve boyutları sınırlı bir read-model'dir. `to_dict()` çıktısı bugün terminal görünümünü, ileride ise native Studio gibi yerel istemcileri aynı execution state'i çoğaltmadan besleyebilir.
