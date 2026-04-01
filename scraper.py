import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime

# ─────────────────────────────────────────────
# AYARLAR – GitHub Secrets'tan okunur
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
SEEN_FILE = "seen_products.json"

TARGET_URLS = [
    "https://www.amazon.com.tr/s?i=warehouse-deals&srs=44219324031&s=date-desc-rank&fs=true",
    "https://www.amazon.com.tr/s?i=warehouse-deals&srs=44219324031&s=date-desc-rank&fs=true&page=2",
    "https://www.amazon.com.tr/s?i=warehouse-deals&srs=44219324031&s=date-desc-rank&fs=true&page=3",
]


# ─────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[Telegram] Mesaj gönderildi.")
    except Exception as e:
        print(f"[Telegram] Hata: {e}")


def extract_name(item):
    """Ürün adını birden fazla selector ile dene."""
    selectors = [
        "h2 a span",
        "h2 span",
        ".a-size-medium.a-color-base.a-text-normal",
        ".a-size-base-plus.a-color-base.a-text-normal",
        ".a-size-mini .a-color-base",
        "[data-cy='title-recipe'] span",
        ".s-title-instructions-style span",
    ]
    for sel in selectors:
        tag = item.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if text and len(text) > 3:
                return text
    return None


def extract_price(item):
    """Fiyatı birden fazla selector ile dene."""
    selectors = [
        ".a-price .a-offscreen",
        ".a-price-whole",
        ".a-color-price",
        "[data-cy='price-recipe'] .a-offscreen",
        ".s-price-instructions-style .a-offscreen",
    ]
    for sel in selectors:
        tag = item.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if text and ("TL" in text or "," in text or "." in text):
                return text
    return None


def extract_link(item, asin):
    """Ürün linkini çek."""
    selectors = ["h2 a", "a.a-link-normal.s-no-outline", "a[href*='/dp/']"]
    for sel in selectors:
        tag = item.select_one(sel)
        if tag and tag.get("href"):
            href = tag["href"]
            if href.startswith("http"):
                return href
            return "https://www.amazon.com.tr" + href
    return f"https://www.amazon.com.tr/dp/{asin}"


def scrape_page(target_url: str) -> list:
    api_url = "https://api.scraperapi.com"
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "country_code": "tr",
        "render": "false",
    }

    try:
        time.sleep(2)
        r = requests.get(api_url, params=params, timeout=60)
        r.raise_for_status()
        print(f"[Scraper] HTTP {r.status_code} → {target_url[:60]}...")
    except Exception as e:
        print(f"[Scraper] Sayfa çekilemedi: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    products = []
    skipped = 0

    items = soup.select("div[data-asin]")
    print(f"[Scraper] {len(items)} öğe parse edildi.")

    for item in items:
        asin = item.get("data-asin", "").strip()
        if not asin:
            continue

        name = extract_name(item)
        price = extract_price(item)
        link = extract_link(item, asin)

        # İsim bulunamazsa bu ürünü atla (sponsor/reklam kartı olabilir)
        if not name:
            skipped += 1
            continue

        products.append({
            "asin": asin,
            "name": name,
            "price": price or "Fiyat yok",
            "link": link,
        })

    print(f"[Scraper] {len(products)} geçerli, {skipped} atlandı.")
    return products


def format_message(product: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🏷️ <b>Yeni Amazon Depo Ürünü!</b>\n\n"
        f"📦 <b>{product['name'][:120]}</b>\n"
        f"💰 Fiyat: <b>{product['price']}</b>\n"
        f"🔗 <a href=\"{product['link']}\">Ürüne Git</a>\n\n"
        f"🕐 {now}"
    )


# ─────────────────────────────────────────────
# ANA FONKSİYON
# ─────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"Amazon Depo Takip – {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")

    seen = load_seen()
    print(f"[Sistem] Daha önce görülen ürün: {len(seen)}")

    all_products = []
    for url in TARGET_URLS:
        products = scrape_page(url)
        all_products.extend(products)

    unique = list({p["asin"]: p for p in all_products if p["asin"]}.values())
    new_products = [p for p in unique if p["asin"] not in seen]

    print(f"[Sistem] Toplam benzersiz ürün: {len(unique)}")
    print(f"[Sistem] Yeni ürün sayısı: {len(new_products)}")

    if not new_products:
        print("[Sistem] Yeni ürün yok, bekleniyor...")
        return

    for product in new_products:
        msg = format_message(product)
        send_telegram(msg)
        seen.add(product["asin"])
        time.sleep(1)

    save_seen(seen)
    print(f"[Sistem] {len(new_products)} yeni ürün bildirildi ve kaydedildi.")


if __name__ == "__main__":
    main()
