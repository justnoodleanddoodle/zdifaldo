# ZDiFaldo – Design Nachrichten Bot

Her gün 6 RSS kaynağından design haberlerini otomatik çeken, Claude API ile Almancaya çeviren ve GitHub Pages'de yayınlayan proje.

## Dosya Yapısı

```
zdifaldo/
├── fetch_news.py                    # RSS okuma + Claude çeviri + JSON yazma
├── news_data.json                   # Otomatik güncellenen haber verisi
├── index.html                       # React + Tailwind arayüzü
├── requirements.txt                 # Python bağımlılıkları
└── .github/workflows/haber_botu.yml # GitHub Actions otomasyonu
```

## Kurulum (5 adım)

### 1. Repoyu GitHub'a yükle
```bash
git init
git add .
git commit -m "init: ZDiFaldo kurulumu"
git remote add origin https://github.com/KULLANICI/zdifaldo.git
git push -u origin main
```

### 2. Anthropic API anahtarını ekle
- GitHub repo → **Settings** → **Secrets and variables** → **Actions**
- **New repository secret** → Name: `ANTHROPIC_API_KEY` → Value: `sk-ant-...`

### 3. GitHub Pages'i aç
- GitHub repo → **Settings** → **Pages**
- Source: **Deploy from a branch** → Branch: `main` → Folder: `/ (root)`
- Kaydet → birkaç dakika sonra `https://KULLANICI.github.io/zdifaldo` adresinde yayında

### 4. İlk çalıştırma
- GitHub repo → **Actions** → **ZDiFaldo Haber Botu** → **Run workflow**
- Workflow tamamlanınca `news_data.json` güncellenecek

### 5. Otomatik zamanlama
Workflow her gün **09:00 Almanya saatinde** otomatik çalışır (cron: `0 7 * * *`).

## RSS Kaynakları

| Kaynak | Kategori |
|--------|----------|
| Smashing Magazine | UI/UX |
| Creative Bloq | Design |
| It's Nice That | Design |
| Fast Company – Co.Design | Design |
| UX Collective | UI/UX |
| Brand New (UnderConsideration) | Branding |

## Yerel Test

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
python fetch_news.py
# Sonra index.html'i bir local server ile aç:
python -m http.server 8000
```
