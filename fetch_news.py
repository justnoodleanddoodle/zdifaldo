import feedparser
import json
import os
import re
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.parse

RSS_SOURCES = [
    { "name": "Smashing Magazine",        "url": "https://www.smashingmagazine.com/feed/",               "category": "ui"       },
    { "name": "Creative Bloq",            "url": "https://www.creativebloq.com/feed",                    "category": "general"  },
    { "name": "Fast Company - Co.Design", "url": "https://www.fastcompany.com/co-design/rss",            "category": "general"  },
    { "name": "UX Collective",            "url": "https://uxdesign.cc/feed",                             "category": "ui"       },
    { "name": "It's Nice That",           "url": "https://www.itsnicethat.com/feed.rss",                 "category": "general"  },
    { "name": "Brand New",                "url": "https://www.underconsideration.com/brandnew/atom.xml", "category": "branding" },
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
    return text

def translate_mymemory(text: str) -> str:
    if not text or not text.strip():
        return text
    # 500 karakterlik parçalara böl
    chunks = [text[i:i+500] for i in range(0, min(len(text), 3000), 500)]
    translated_chunks = []
    for chunk in chunks:
        try:
            params = urllib.parse.urlencode({"q": chunk, "langpair": "en|de"})
            url = f"https://api.mymemory.translated.net/get?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
                t = data.get("responseData", {}).get("translatedText", "")
                if t and t != "INVALID LANGUAGE PAIR":
                    translated_chunks.append(t)
                else:
                    translated_chunks.append(chunk)
            time.sleep(0.3)
        except Exception as e:
            translated_chunks.append(chunk)
    return " ".join(translated_chunks)

def fetch_full_content(url: str) -> str:
    """Makale sayfasından tam içeriği çek — trafilatura ile."""
    try:
        import trafilatura
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and len(text) > 200:
            return text[:4000]  # Max 4000 karakter
    except Exception as e:
        print(f"     Icerik cekme hatasi: {e}")
    return ""

def extract_image(entry) -> str | None:
    media = getattr(entry, "media_content", [])
    for m in media:
        url = m.get("url", "")
        if url and any(url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return url
        if m.get("medium") == "image" and url:
            return url

    thumbs = getattr(entry, "media_thumbnail", [])
    if thumbs:
        return thumbs[0].get("url")

    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image"):
            return enc.get("href") or enc.get("url")

    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    if not content:
        content = getattr(entry, "summary", "") or ""

    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
    if img_match:
        url = img_match.group(1)
        if url.startswith("http") and not url.endswith(".gif"):
            return url
    return None

def parse_feed(source: dict) -> list[dict]:
    print(f"  -> {source['name']} okunuyor...")
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

            image = extract_image(entry)
            items.append({
                "id":               make_id(entry.get("link", entry.get("id", ""))),
                "title":            entry.get("title", "").strip(),
                "summary_original": strip_html(summary_raw)[:500],
                "full_content":     "",
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

def enrich_and_translate(items: list[dict]) -> list[dict]:
    print(f"\n  -> {len(items)} haber icin tam icerik cekiliyor ve cevriliyor...")
    for i, item in enumerate(items):
        print(f"\n  [{i+1}/{len(items)}] {item['title'][:60]}")

        # 1. Tam içerik çek
        full = fetch_full_content(item["url"])
        if not full:
            full = item["summary_original"]
        item["full_content_original"] = full

        # 2. Başlık çevir
        item["title_de"] = translate_mymemory(item["title"])
        print(f"     Baslik: {item['title_de'][:60]}")

        # 3. Özet çevir
        item["summary_de"] = translate_mymemory(item["summary_original"])

        # 4. Tam içerik çevir (paragraflara bölerek)
        if full and full != item["summary_original"]:
            paragraphs = [p.strip() for p in full.split("\n") if p.strip()]
            translated_paragraphs = []
            for p in paragraphs[:20]:  # Max 20 paragraf
                tp = translate_mymemory(p)
                translated_paragraphs.append(tp)
            item["full_content_de"] = "\n\n".join(translated_paragraphs)
        else:
            item["full_content_de"] = item["summary_de"]

        print(f"     Icerik: {len(item['full_content_de'])} karakter")
        time.sleep(0.5)

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
    print(f"=== ZDiFaldo Haber Botu - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    all_raw = []
    for source in RSS_SOURCES:
        all_raw.extend(parse_feed(source))
        time.sleep(1)

    print(f"\nToplam {len(all_raw)} ham haber.")

    all_enriched = enrich_and_translate(all_raw)

    for item in all_enriched:
        if not item.get("image"):
            item["image"] = FALLBACK_IMAGES.get(item["category"], FALLBACK_IMAGES["general"])

    existing = load_existing(OUTPUT_FILE)
    merged   = merge(existing.get("items", []), all_enriched)

    output = {
        "updated_at":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_count":    len(RSS_SOURCES),
        "item_count":      len(merged),
        "category_labels": CATEGORY_LABELS,
        "items":           merged,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ {OUTPUT_FILE} guncellendi - {len(merged)} haber.")

if __name__ == "__main__":
    main()
