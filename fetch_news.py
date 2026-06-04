import feedparser
import json
import os
import re
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import anthropic
import urllib.request

RSS_SOURCES = [
    { "name": "Smashing Magazine",        "url": "https://www.smashingmagazine.com/feed/",               "category": "ui"       },
    { "name": "Creative Bloq",            "url": "https://www.creativebloq.com/feed",                    "category": "general"  },
    { "name": "It's Nice That",           "url": "https://www.itsnicethat.com/rss",                      "category": "general"  },
    { "name": "Fast Company – Co.Design", "url": "https://www.fastcompany.com/co-design/rss",            "category": "general"  },
    { "name": "UX Collective",            "url": "https://uxdesign.cc/feed",                             "category": "ui"       },
    { "name": "Brand New",                "url": "https://www.underconsideration.com/brandnew/index.rdf","category": "branding" },
]

ITEMS_PER_SOURCE = 4
OUTPUT_FILE = Path("news_data.json")

CATEGORY_LABELS = {
    "ui":       "UI/UX",
    "tools":    "Software & Tools",
    "ai":       "KI & Bildrechte",
    "branding": "Branding & Typo",
    "motion":   "Motion & Plugins",
    "general":  "Design",
}

# Kategori bazlı fallback görseller
FALLBACK_IMAGES = {
    "ui":       "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=600&q=80",
    "tools":    "https://images.unsplash.com/photo-1618788372246-79faff0c3742?w=600&q=80",
    "ai":       "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=600&q=80",
    "branding": "https://images.unsplash.com/photo-1634084462412-b54873c0a56d?w=600&q=80",
    "motion":   "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=600&q=80",
    "general":  "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&q=80",
}

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]

def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
               .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ") \
               .replace("&#8220;", '"').replace("&#8221;", '"').replace("&#8217;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]

def extract_image(entry, source_name: str) -> str | None:
    """RSS entry'den görsel URL'si çıkar — çok katmanlı arama."""

    # 1. media:content
    media = getattr(entry, "media_content", [])
    for m in media:
        url = m.get("url", "")
        if url and any(url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return url
        if m.get("medium") == "image" and url:
            return url

    # 2. media:thumbnail
    thumbs = getattr(entry, "media_thumbnail", [])
    if thumbs:
        return thumbs[0].get("url")

    # 3. enclosure
    for enc in getattr(entry, "enclosures", []):
        t = enc.get("type", "")
        if t.startswith("image"):
            return enc.get("href") or enc.get("url")

    # 4. İçerik / özet içindeki ilk <img>
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    if not content:
        content = getattr(entry, "summary", "") or ""

    img_match = re.search(
        r'<img[^>]+src=["\']([^"\']+)["\']',
        content, re.IGNORECASE
    )
    if img_match:
        url = img_match.group(1)
        if url.startswith("http") and not url.endswith(".gif"):
            return url

    # 5. og:image — sadece Smashing Magazine için (diğerleri yavaşlatır)
    if source_name == "Smashing Magazine":
        link = getattr(entry, "link", "")
        if link:
            try:
                req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    html = r.read(8000).decode("utf-8", errors="ignore")
                og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
                if not og:
                    og = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
                if og:
                    return og.group(1)
            except Exception:
                pass

    return None

def parse_feed(source: dict) -> list[dict]:
    print(f"  → {source['name']} okunuyor...")
    try:
        req = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; ZDiFaldo/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        feed = feedparser.parse(raw)

        items = []
        for entry in feed.entries[:ITEMS_PER_SOURCE]:
            summary_raw = ""
            if hasattr(entry, "content") and entry.content:
                summary_raw = entry.content[0].get("value", "")
            if not summary_raw:
                summary_raw = getattr(entry, "summary", "") or ""

            image = extract_image(entry, source["name"])

            items.append({
                "id":               make_id(entry.get("link", entry.get("id", ""))),
                "title":            entry.get("title", "").strip(),
                "summary_original": strip_html(summary_raw),
                "image":            image,
                "url":              entry.get("link", ""),
                "source":           source["name"],
                "category":         source["category"],
                "published_raw":    entry.get("published", ""),
            })

        found_img = sum(1 for i in items if i["image"])
        print(f"     {len(items)} haber, {found_img} gorsel bulundu.")
        return items

    except Exception as e:
        print(f"     HATA: {e}")
        return []

def translate_batch(items: list[dict], client: anthropic.Anthropic) -> list[dict]:
    if not items:
        return items

    blocks = []
    for i, item in enumerate(items):
        blocks.append(f"[{i}]\nTITLE: {item['title']}\nSUMMARY: {item['summary_original'][:300]}")
    combined = "\n\n".join(blocks)

    prompt = f"""Du bist ein professioneller Design-Redakteur.
Uebersetze die folgenden Nachrichtentitel und Zusammenfassungen ins Deutsche.
Schreibe natuerliches, journalistisches Deutsch. Behalte Eigennamen bei (Figma, Adobe, CSS, UX, etc.).
Antworte NUR mit einem JSON-Array. Kein weiterer Text, keine Markdown-Backticks, kein Kommentar.

Exaktes Format (array mit {len(items)} objekten):
[{{"title": "...", "summary": "..."}}]

Nachrichten:
{combined}
"""

    print(f"  → {len(items)} haber cevrilliyor...")
    try:
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
        # Sadece JSON array kısmını al
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        translations = json.loads(raw)

        for i, item in enumerate(items):
            if i < len(translations):
                item["title_de"]   = translations[i].get("title", item["title"])
                item["summary_de"] = translations[i].get("summary", item["summary_original"])
            else:
                item["title_de"]   = item["title"]
                item["summary_de"] = item["summary_original"]
        print(f"     Ceviri tamam.")
    except Exception as e:
        print(f"     Ceviri HATASI: {e}")
        for item in items:
            item["title_de"]   = item["title"]
            item["summary_de"] = item["summary_original"]
    return items

def load_existing(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated_at": "", "items": []}

def merge(existing: list, new_items: list) -> list:
    existing_ids = {item["id"] for item in existing}
    added = [item for item in new_items if item["id"] not in existing_ids]
    return (added + existing)[:80]

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY bulunamadi.")

    client = anthropic.Anthropic(api_key=api_key)
    print(f"=== ZDiFaldo Haber Botu — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    all_raw = []
    for source in RSS_SOURCES:
        all_raw.extend(parse_feed(source))
        time.sleep(1)

    print(f"\nToplam {len(all_raw)} ham haber.\n")

    # Çeviriyi 15'er haberlik batch'lere böl (token limiti için)
    translated = []
    batch_size = 15
    for i in range(0, len(all_raw), batch_size):
        batch = all_raw[i:i+batch_size]
        translated.extend(translate_batch(batch, client))
        if i + batch_size < len(all_raw):
            time.sleep(2)

    # Görseli olmayan haberlere fallback ekle
    for item in translated:
        if not item.get("image"):
            item["image"] = FALLBACK_IMAGES.get(item["category"], FALLBACK_IMAGES["general"])

    existing = load_existing(OUTPUT_FILE)
    merged   = merge(existing.get("items", []), translated)

    output = {
        "updated_at":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_count":    len(RSS_SOURCES),
        "item_count":      len(merged),
        "category_labels": CATEGORY_LABELS,
        "items":           merged,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ {OUTPUT_FILE} guncellendi — {len(merged)} haber.")

if __name__ == "__main__":
    main()
