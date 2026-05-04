#!/usr/bin/env python3
"""
UK Mortgage Feed Scraper — Guardian Money
For: bestmortgagesforyou.co.uk
Output: feeds/thisismoney_mortgage.xml
"""

import feedparser
import requests
import hashlib
import json
import os
import re
import time
from datetime import datetime
from email.utils import formatdate
from bs4 import BeautifulSoup
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

SOURCE_RSS    = "https://www.theguardian.com/money/mortgages/rss"
FEED_TITLE    = "Best Mortgages For You – UK Mortgage News"
FEED_LINK     = "https://bestmortgagesforyou.co.uk"
FEED_DESC     = "Latest UK mortgage and housing finance news, sourced and rewritten daily."
FEED_LANG     = "en-gb"
OUTPUT_PATH   = "feeds/thisismoney_mortgage.xml"
HASH_FILE     = "feeds/.seen_thisismoney.json"
MAX_ITEMS     = 20
MAX_NEW_PER_RUN = 5
OPENROUTER_KEY   = os.environ.get("OPENROUTER_KEY", "")
OPENROUTER_MODEL = "deepseek/deepseek-chat"
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
SITE_BASE_URL    = "https://bestmortgagesforyou.co.uk"
DEFAULT_IMAGE    = "https://bestmortgagesforyou.co.uk/wp-content/uploads/default-mortgage.jpg"

AUTHORS = [
    "Bambang Setiawan",
    "Nadya Putri Maharani",
    "Rizky Aditya Pratama",
    "Sri Wahyuni Astuti",
]

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def load_seen():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            return json.load(f)
    return {}

def save_seen(seen):
    with open(HASH_FILE, "w") as f:
        json.dump(seen, f, indent=2)

def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()

def get_image_url(entry):
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            if m.get("url"):
                return m["url"]
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        if entry.media_thumbnail[0].get("url"):
            return entry.media_thumbnail[0]["url"]
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if "image" in enc.get("type", ""):
                return enc.get("href", "")
    summary = entry.get("summary", "")
    if summary:
        soup = BeautifulSoup(summary, "lxml")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    return DEFAULT_IMAGE

def fetch_article_body(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        selectors = [
            {"class": "article-body-commercial-selector"},
            {"class": "dcr-article-body"},
            {"itemprop": "articleBody"},
            "article",
        ]
        body = None
        for sel in selectors:
            body = soup.find("div", sel) if isinstance(sel, dict) else soup.find(sel)
            if body:
                break
        if not body:
            return ""
        for tag in body.find_all(["aside", "script", "style", "figure", "figcaption", "iframe", "ins"]):
            tag.decompose()
        return body.get_text(separator=" ", strip=True)[:2500]
    except Exception as e:
        log(f"  [fetch error] {e}")
        return ""

SYSTEM_PROMPT = """You are a UK personal finance journalist writing for bestmortgagesforyou.co.uk.

Rules:
- British English only (colour, favour, realise, whilst, etc.)
- Tone: informative, clear, FCA-safe — never give direct financial advice
- Avoid "you should" — use "homeowners may wish to", "it could be worth", "borrowers might consider"
- Structure: opening paragraph → 2 or 3 H2 sections → short closing paragraph
- Output ONLY the HTML article body. No markdown. No preamble. No explanation.
- Tags to use: <h2>, <p>, <ul>, <li>
- Length: 500–650 words
- Do NOT copy sentences from the source. Rewrite completely in your own words."""

def rewrite(title, body, author):
    user_prompt = (
        f"Rewrite the following UK mortgage/finance news story as a fresh, original article "
        f"for bestmortgagesforyou.co.uk. British English throughout.\n\n"
        f"Original headline: {title}\n\n"
        f"Source content:\n{body}\n\n"
        f"Begin the article with: <p class=\"author\">By {author}</p>"
    )
    try:
        r = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": SITE_BASE_URL,
                "X-Title": "Best Mortgages For You",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 1200,
                "temperature": 0.72,
            },
            timeout=60,
        )
        r.raise_for_status()
        result = r.json()["choices"][0]["message"]["content"].strip()
        result = re.sub(r"^```html\s*", "", result)
        result = re.sub(r"```\s*$", "", result)
        return result.strip()
    except Exception as e:
        log(f"  [openrouter error] {e}")
        return None

def slugify(text):
    s = text.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s[:60].rstrip("-")

def get_categories(title):
    cats = ["Mortgages", "UK Housing", "Guardian Money"]
    keywords = {
        "interest rate": "Interest Rates",
        "bank of england": "Bank of England",
        "first-time buyer": "First Time Buyers",
        "first time buyer": "First Time Buyers",
        "house price": "House Prices",
        "remortgage": "Remortgage",
        "fixed rate": "Fixed Rate Mortgages",
        "buy to let": "Buy to Let",
        "help to buy": "Help to Buy",
        "stamp duty": "Stamp Duty",
        "savings": "Savings",
        "inflation": "Inflation",
    }
    title_lower = title.lower()
    for kw, cat in keywords.items():
        if kw in title_lower and cat not in cats:
            cats.append(cat)
    return cats

def load_existing_items():
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        parsed = feedparser.parse(raw)
        items = []
        for e in parsed.entries:
            tags = [t.term for t in e.get("tags", [])]
            full_content = ""
            if hasattr(e, "content") and e.content:
                full_content = e.content[0].get("value", "")
            if not full_content:
                full_content = e.get("summary", "")
            image_url = DEFAULT_IMAGE
            if hasattr(e, "media_content") and e.media_content:
                image_url = e.media_content[0].get("url", DEFAULT_IMAGE)
            items.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "guid": e.get("id", e.get("link", "")),
                "pubDate": e.get("published", formatdate(localtime=False)),
                "content": full_content,
                "author": e.get("author", AUTHORS[0]),
                "categories": tags,
                "image_url": image_url,
            })
        return items
    except Exception as e:
        log(f"  [load existing error] {e}")
        return []

def wrap_with_image(html_content, image_url):
    img_tag = f'<p><img src="{image_url}" style="max-width:100%;" /></p>'
    return f'{img_tag}\n<div class="entry-content">\n{html_content}\n</div>'

def build_xml(items):
    rss = Element("rss")
    rss.set("version", "2.0")
    rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
    rss.set("xmlns:media", "http://search.yahoo.com/mrss/")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = FEED_TITLE
    SubElement(channel, "link").text = FEED_LINK
    SubElement(channel, "description").text = FEED_DESC
    SubElement(channel, "language").text = FEED_LANG
    SubElement(channel, "lastBuildDate").text = formatdate(localtime=False)
    SubElement(channel, "generator").text = "GitHub Actions Scraper (bestmortgages_uk)"

    for item in items:
        entry = SubElement(channel, "item")
        SubElement(entry, "title").text = item["title"]
        SubElement(entry, "link").text = item["link"]
        guid_el = SubElement(entry, "guid")
        guid_el.set("isPermaLink", "true")
        guid_el.text = item["guid"]
        SubElement(entry, "pubDate").text = item["pubDate"]
        SubElement(entry, "author").text = item["author"]
        full_html = wrap_with_image(item.get("content", ""), item.get("image_url", DEFAULT_IMAGE))
        SubElement(entry, "description").text = full_html
        ce = SubElement(entry, "content:encoded")
        ce.text = full_html
        for cat in item.get("categories", []):
            SubElement(entry, "category").text = cat
        image_url = item.get("image_url", DEFAULT_IMAGE)
        if image_url:
            mc = SubElement(entry, "media:content")
            mc.set("url", image_url)
            mc.set("medium", "image")

    raw = tostring(rss, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    lines = [l for l in pretty.split("\n") if l.strip() and not l.startswith("<?xml")]
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + "\n".join(lines)

def main():
    os.makedirs("feeds", exist_ok=True)
    log("=== UK Mortgage Scraper START ===")
    if not OPENROUTER_KEY:
        log("ERROR: OPENROUTER_KEY not set.")
        return

    seen = load_seen()
    existing_items = load_existing_items()
    new_items = []
    author_idx = len(existing_items) % len(AUTHORS)

    log(f"Fetching RSS: {SOURCE_RSS}")
    feed = feedparser.parse(SOURCE_RSS)
    log(f"Found {len(feed.entries)} entries in RSS")

    for entry in feed.entries:
        if len(new_items) >= MAX_NEW_PER_RUN:
            break
        url = entry.get("link", "").strip()
        title = entry.get("title", "").strip()
        h = url_hash(url)
        if h in seen:
            log(f"  SKIP (seen): {title[:70]}")
            continue
        log(f"  PROCESS: {title[:70]}")
        image_url = get_image_url(entry)
        body_text = fetch_article_body(url)
        if not body_text:
            body_text = entry.get("summary", "")
        if not body_text:
            log("  No body text, skipping")
            continue
        author = AUTHORS[author_idx % len(AUTHORS)]
        rewritten = rewrite(title, body_text, author)
        if not rewritten:
            log("  Rewrite failed, skipping")
            continue
        slug = slugify(title)
        new_guid = f"{SITE_BASE_URL}/mortgage-news/{slug}-{h[:8]}/"
        pub_date = entry.get("published", formatdate(localtime=False))
        new_items.append({
            "title": title,
            "link": new_guid,
            "guid": new_guid,
            "pubDate": pub_date,
            "content": rewritten,
            "author": author,
            "categories": get_categories(title),
            "image_url": image_url,
        })
        seen[h] = datetime.now().isoformat()
        author_idx += 1
        log(f"  OK — author: {author}")
        time.sleep(2)

    all_items = (new_items + existing_items)[:MAX_ITEMS]
    xml_out = build_xml(all_items)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(xml_out)
    save_seen(seen)
    log(f"=== DONE — {len(new_items)} new / {len(all_items)} total ===")

if __name__ == "__main__":
    main()
