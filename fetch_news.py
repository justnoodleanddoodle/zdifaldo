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
    # Motion Design & After Effects
    { "name": "Motionographer",      "url": "https://motionographer.com/feed/",                         "category": "motion"     },
    { "name": "aescripts",           "url": "https://aescripts.com/rss/",                               "category": "motion"     },
    { "name": "School of Motion",    "url": "https://www.motiondesign.school/blog/feed/",               "category": "motion"     },
    # 3D & Blender
    { "name": "Blender.org",         "url": "https://www.blender.org/feed/",                            "category": "visual"     },
    { "name": "BlenderNation",       "url": "https://www.blendernation.com/feed/",                      "category": "visual"     },
    # Branding & Logo
    { "name": "Brand New",           "url": "https://www.underconsideration.com/brandnew/atom.xml",     "category": "branding"   },
    { "name": "The Dieline",         "url": "https://www.thedieline.com/feed",                          "category": "branding"   },
    # Tipografi
    { "name": "I Love Typography",   "url": "https://ilovetypography.com/feed/",                       "category": "typography" },
    { "name": "Fonts In Use",        "url": "https://fontsinuse.com/feed",                              "category": "typography" },
    # AI & Kreativ Teknoloji
    { "name": "Adobe Blog",          "url": "https://blog.adobe.com/en/topics/creativity/feed",         "category": "ai"         },
    { "name": "The Verge Design",    "url": "https://www.theverge.com/rss/design/index.xml",            "category": "ai"         },
    # UI/UX
    { "name": "Smashing Magazine",   "url": "https://www.smashingmagazine.com/feed/",                  "category": "ui"         },
    { "name": "UX Collective",       "url": "https://uxdesign.cc/feed",                                 "category": "ui"         },
    # Genel Design & Ilham
    { "name": "Designboom",          "url": "https://www.designboom.com/feed/",                         "category": "general"    },
    { "name": "It's Nice That",      "url": "https://www.itsnicethat.com/feed.rss",                     "category": "general"    },
    { "name": "Creative Boom",       "url": "https://www.creativeboom.com/feed/",                       "category": "general"    },
    { "name": "Abduzeedo",           "url": "https://abduzeedo.com/rss.xml",                            "category": "general"    },
    { "name": "PAGE Online",         "url": "https://page-online.de/feed/",                             "category": "general"    },
    { "name": "Slanted",             "url": "https://slanted.de/feed/",                                 "category": "general"    },
]

ITEMS_PER_SOURCE = 3
OUTPUT_FILE = Path("news_data.json")

CATEGORY_LABELS = {
    "ui":         "UI/UX",
    "ai":         "KI & Adobe",
    "branding":   "Branding & Logo",
    "motion":     "Motion & AE",
    "typography": "Typografie",
    "visual":     "3D & Blender",
    "general":    "Inspiration",
}

FALLBACK_IMAGES = {
    "ui":         "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=600&q=80",
    "ai":         "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=600&q=80",
    "branding":   "https://images.unsplash.com/photo-1634084462412-b54873c0a56d?w=600&q=80",
    "motion":     "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=600&q=80",
    "typography": "https://images.unsplash.com/photo-1563206767-5b18f218e8de?w=600&q=80",
    "visual":     "https://images.unsplash.com/photo-1617791160536-598cf32026fb?w=600&q=80",
    "general":    "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=600&q=80",
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
               .replace("&#8220;", '"').replace("&#8221;", '"').replace("&#8217;", "'") \
               .replace("&#8230;", "...")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def translate_google(text: str) -> str:
    """Google Translate resmi olmayan ama stabil endpoint — limit yok."""
    if not text or not text.strip():
        return text
    # 800 karakterlik parçalara böl
    max_len = 800
    if len(text) <= max_len:
        chunks = [text]
    else:
        # Cümle sınırlarından böl
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current = ""
        for s in sentences:
            if len(current) + len(s) < max_len:
                current += s + " "
            else:
                if current:
                    chunks.append(current.strip())
                current = s + " "
        if current:
            chunks.append(current.strip())

    translated = []
    for chunk in chunks[:6]:  # Max 6 parça
        try:
            params = urllib.parse.urlencode({
                "client": "gtx",
                "sl":     "auto",
                "tl":     "de",
                "dt":     "t",
                "q":      chunk
            })
            url = f"https://translate.googleapis.com/translate_a/single?{params}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
                result = ""
                for item in data[0]:
                    if item[0]:
                        result += item[0]
                if result:
                    translated.append(result.strip())
                else:
                    translated.append(chunk)
            time.sleep(0.2)
        except Exception as e:
            translated.append(chunk)
    return " ".join(translated)

def extract_image(entry) -> str | None:
    # 1. media:content
    for m in getattr(entry, "media_content", []):
        url = m.get("url", "")
        if url and any(url.lower().endswith(x) for x in [".jpg", ".jpeg", ".png", ".webp"]):
            return url
        if m.get("medium") == "image" and url:
            return url
    # 2. media:thumbnail
    thumbs = getattr(entry, "media_thumbnail", [])
    if thumbs:
        return thumbs[0].get("url")
    # 3. enclosure
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image"):
            return enc.get("href") or enc.get("url")
    # 4. img in content/summary
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    if not content:
        content = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE)
    if m:
        url = m.group(1)
        if url.startswith("http") and not url.endswith(".gif"):
            return url
    return None

def get_best_summary(entry) -> str:
    """RSS entry'den en iyi özeti çıkar — HTML temizlenmiş."""
    # Önce content, sonra summary
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    if not content:
        content = getattr(entry, "summary", "") or ""
    
    clean = strip_html(content)
    
    # Çok kısa veya sadece URL/dosya adıysa boş döndür
    if len(clean) < 50 or re.match(r'^[\w\-]+\.\w{2,4}', clean):
        return ""
    
    return clean[:800]

def parse_feed(source: dict) -> list[dict]:
    print(f"  -> {source['name']} okunuyor...")
    try:
        req = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; ZDiFaldo/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read()
        feed = feedparser.parse(raw)

        items = []
        for entry in feed.entries[:ITEMS_PER_SOURCE]:
            summary = get_best_summary(entry)
            image   = extract_image(entry)

            items.append({
                "id":               make_id(entry.get("link", entry.get("id", ""))),
                "title":            entry.get("title", "").strip(),
                "summary_original": summary,
                "image":            image,
                "url":              entry.get("link", ""),
                "source":           source["name"],
                "category":         source["category"],
                "published_raw":    entry.get("published", ""),
            })

        found_img = sum(1 for i in items if i["image"])
        print(f"     {len(items)} haber, {found_img} gorsel.")
        return items
    except Exception as e:
        print(f"     HATA: {e}")
        return []

def translate_all(items: list[dict]) -> list[dict]:
    print(f"\n  -> {len(items)} haber Google Translate ile cevriliyor...")
    
    # PAGE Online ve Slanted zaten Almanca — onları atla
    german_sources = {"PAGE Online", "Slanted"}
    
    for i, item in enumerate(items):
        if item["source"] in german_sources:
            item["title_de"]            = item["title"]
            item["summary_de"]          = item["summary_original"]
            item["full_content_de"]     = item["summary_original"]
            print(f"     [{i+1}/{len(items)}] (DE) {item['title'][:60]}")
            continue

        item["title_de"]   = translate_google(item["title"])
        item["summary_de"] = translate_google(item["summary_original"]) if item["summary_original"] else ""
        item["full_content_de"] = item["summary_de"]
        print(f"     [{i+1}/{len(items)}] {item['title_de'][:60]}")
        time.sleep(0.3)

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
    return (added + existing)[:100]

def main():
    print(f"=== ZDiFaldo Haber Botu - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    all_raw = []
    for source in RSS_SOURCES:
        all_raw.extend(parse_feed(source))
        time.sleep(0.5)

    print(f"\nToplam {len(all_raw)} ham haber.")

    all_translated = translate_all(all_raw)

    # Görseli olmayanlara fallback ekle
    for item in all_translated:
        if not item.get("image"):
            item["image"] = FALLBACK_IMAGES.get(item["category"], FALLBACK_IMAGES["general"])

    existing = load_existing(OUTPUT_FILE)
    merged   = merge(existing.get("items", []), all_translated)

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
