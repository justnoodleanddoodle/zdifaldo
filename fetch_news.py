import feedparser
import json
import os
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import anthropic

# ── Ayarlar ──────────────────────────────────────────────────────────────────

RSS_SOURCES = [
    {
        "name": "Smashing Magazine",
        "url": "https://www.smashingmagazine.com/feed/",
        "category": "ui",
    },
    {
        "name": "Creative Bloq",
        "url": "https://www.creativebloq.com/feed",
        "category": "general",
    },
    {
        "name": "It's Nice That",
        "url": "https://www.itsnicethat.com/rss",
        "category": "general",
    },
    {
        "name": "Fast Company – Co.Design",
        "url": "https://www.fastcompany.com/co-design/rss",
        "category": "general",
    },
    {
        "name": "UX Collective",
        "url": "https://uxdesign.cc/feed",
        "category": "ui",
    },
    {
        "name": "Brand New",
        "url": "https://www.underconsideration.com/brandnew/index.rdf",
        "category": "branding",
    },
]

# Her kaynaktan kaç haber alınsın
ITEMS_PER_SOURCE = 4

# Çıktı dosyası
OUTPUT_FILE = Path("news_data.json")

# Kategori etiketleri (Almanca)
CATEGORY_LABELS = {
    "ui":       "UI/UX",
    "tools":    "Design-Tools",
    "ai":       "KI & Design",
    "branding": "Branding",
    "motion":   "Motion",
    "general":  "Design",
}

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def make_id(url: str) -> str:
    """URL'den kısa benzersiz ID üret."""
    return hashlib.md5(url.encode()).hexdigest()[:10]


def parse_feed(source: dict) -> list[dict]:
    """RSS/Atom feed'ini parse et, ham haberleri döndür."""
    print(f"  → {source['name']} okunuyor...")
    try:
        feed = feedparser.parse(source["url"])
        items = []
        for entry in feed.entries[: ITEMS_PER_SOURCE]:
            # Özeti düzleştir (HTML tag'lerini temizle)
            summary_raw = getattr(entry, "summary", "") or ""
            # Basit HTML temizleme
            import re
            summary_clean = re.sub(r"<[^>]+>", "", summary_raw).strip()
            summary_clean = summary_clean[:400]  # Çok uzun olmasın

            items.append(
                {
                    "id": make_id(entry.get("link", entry.get("id", ""))),
                    "title": entry.get("title", "").strip(),
                    "summary_original": summary_clean,
                    "url": entry.get("link", ""),
                    "source": source["name"],
                    "category": source["category"],
                    "published_raw": entry.get("published", ""),
                }
            )
        print(f"     {len(items)} haber bulundu.")
        return items
    except Exception as e:
        print(f"     HATA: {e}")
        return []


def translate_batch(items: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """
    Claude API ile başlık ve özeti Almancaya çevir.
    Tüm haberleri tek bir API çağrısında gönder (maliyet ve hız için).
    """
    if not items:
        return items

    # API'ye gönderilecek metin bloğunu hazırla
    blocks = []
    for i, item in enumerate(items):
        blocks.append(
            f"[{i}]\nTITLE: {item['title']}\nSUMMARY: {item['summary_original']}"
        )
    combined = "\n\n".join(blocks)

    prompt = f"""Du bist ein professioneller Design-Redakteur. 
Übersetze die folgenden Nachrichtentitel und Zusammenfassungen ins Deutsche.
Schreibe natürliches, journalistisches Deutsch. Behalte Eigennamen (Figma, Adobe etc.) bei.
Antworte NUR mit einem JSON-Array, kein weiterer Text, keine Markdown-Backticks.

Format:
[{{"title": "...", "summary": "..."}}]

Nachrichten:
{combined}
"""

    print(f"  → {len(items)} haber Claude ile çevriliyor...")
    try:
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Olası ```json ``` temizle
        import re
        raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
        translations = json.loads(raw)

        for i, item in enumerate(items):
            if i < len(translations):
                item["title_de"] = translations[i].get("title", item["title"])
                item["summary_de"] = translations[i].get("summary", item["summary_original"])
            else:
                item["title_de"] = item["title"]
                item["summary_de"] = item["summary_original"]
        print(f"     Çeviri tamamlandı.")
    except Exception as e:
        print(f"     Çeviri HATASI: {e} — orijinal metin kullanılıyor.")
        for item in items:
            item["title_de"] = item["title"]
            item["summary_de"] = item["summary_original"]

    return items


def load_existing(path: Path) -> dict:
    """Mevcut JSON'u yükle (varsa)."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated_at": "", "items": []}


def merge(existing_items: list, new_items: list) -> list:
    """
    Yeni haberleri mevcut listeyle birleştir.
    Tekrarları ID ile önle. En yeni 60 haberi tut.
    """
    existing_ids = {item["id"] for item in existing_items}
    added = [item for item in new_items if item["id"] not in existing_ids]
    merged = added + existing_items
    return merged[:60]


# ── Ana akış ──────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY bulunamadı. "
            "GitHub Secrets'a ekledin mi?"
        )

    client = anthropic.Anthropic(api_key=api_key)

    print("=== ZDiFaldo Haber Botu başlatıldı ===")
    print(f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    # 1. RSS'leri oku
    all_raw = []
    for source in RSS_SOURCES:
        items = parse_feed(source)
        all_raw.extend(items)
        time.sleep(1)  # Kaynakları boğma

    print(f"\nToplam {len(all_raw)} ham haber toplandı.\n")

    # 2. Çeviri (toplu)
    all_translated = translate_batch(all_raw, client)

    # 3. Mevcut JSON ile birleştir
    existing_data = load_existing(OUTPUT_FILE)
    merged_items = merge(existing_data.get("items", []), all_translated)

    # 4. JSON'u yaz
    output = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_count": len(RSS_SOURCES),
        "item_count": len(merged_items),
        "category_labels": CATEGORY_LABELS,
        "items": merged_items,
    }
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ {OUTPUT_FILE} güncellendi — {len(merged_items)} haber kayıt edildi.")


if __name__ == "__main__":
    main()
