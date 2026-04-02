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

BASE = "https://www.amazon.com.tr/s?srs=44219324031&bbn=44219324031&s=date-desc-rank&fs=true"
CATEGORIES = {
    "Bahçe":                 "21324944031",
    "Bilgisayar":            "12466439031",
    "Elektronik":            "12466496031",
    "Ev ve Yaşam":           "12466667031",
    "Moda":                  "12466553031",
    "Mutfak":                "12466781031",
    "Ofis ve Kırtasiye":     "12467009031",
    "Oyuncak":               "12467126031",
    "Spor ve Outdoor":       "12467068031",
    "Video Oyunu ve Konsol": "12467183031",
    "Yapı Market":           "12466724031",
}

def build_urls():
    urls = []
    for category, node in CATEGORIES.items():
        for page in range(1, 3):
            url = f"{BASE}&rh=n%3A44219324031%2Cn%3A{node}"
            if page > 1:
                url += f"&page={page}"
            urls.append((category, url))
    return urls


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
    selectors = [
        "h2 a span",
        "h2 span",
        ".a-size-medium.a-color-base.a-text-normal",
        ".a-size-base-plus.a-color-base.a-text-normal",
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
    """
    Amazon Depo ürünlerinde fiyat farklı yerlerde olabilir.
    Tüm olası yerleri sırayla dene.
    """
    # 1. Standart fiyat
    for sel in [
        ".a-price .a-offscreen",
        ".a-price-whole",
        "[data-cy='price-recipe'] .a-offscreen",
        ".s-price-instructions-style .a-offscreen",
    ]:
        tag = item.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if text and len(text) > 1:
                return text

    # 2. "Diğer satın alma seçenekleri" altındaki fiyat (Depo ürünlerine özgü)
    for sel in [
        ".a-color-secondary .a-size-base",
        ".s-secondary-view-with-details .a-price .a-offscreen",
        ".a-section.a-spacing-none.a-spacing-top-micro .a-color-secondary",
    ]:
        tag = item.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            # TL içeriyorsa fiyattır
            if "TL" in text or ("," in text and any(c.isdigit() for c in text)):
                return text

    # 3. Tüm fiyat benzeri metinleri tara (son çare)
    for tag in item.find_all(class_=lambda c: c and "price" in c.lower()):
        text = tag.get_text(strip=True)
        if text and "TL" in text and any(c.isdigit() for c in text):
            return text

    return None


def extract_link(item, asin):
    for sel in ["h2 a", "a.a-link-normal.s-no-outline", "a[href*='/dp/']"]:
        tag = item.select_one(sel)
        if tag and tag.get("href"):
            href = tag["href"]
            return href if href.startswith("http") else "https://www.amazon.com.tr" + href
    return f"https://www.amazon.com.tr/dp/{asin}"


def scrape_page(category: str, target_url: str) -> list:
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "country_code": "tr",
        "render": "false",
    }
    try:
        time.sleep(1)
        r = requests.get("https://api.scraperapi.com", params=params, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"[Scraper] {category} çekilemedi: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    for item in soup.select("div[data-asin]"):
        asin = item.get("data-asin", "").strip()
        if not asin:
            continue
        name = extract_name(item)
        if not name:
            continue

        price = extract_price(item)
        print(f"  ASIN: {asin[:10]} | Fiyat: {price} | {name[:40]}")

        products.append({
            "asin": asin,
            "name": name,
            "price": price or "—",
            "link": extract_link(item, asin),
            "category": category,
        })

    print(f"[{category}] {len(products)} ürün bulundu.")
    return products


def format_message(product: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🏷️ <b>Yeni Amazon Depo Ürünü!</b>\n"
        f"📂 <b>{product['category']}</b>\n\n"
        f"📦 {product['name'][:120]}\n"
        f"💰 <b>{product['price']}</b>\n"
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
    for category, url in build_urls():
        products = scrape_page(category, url)
        all_products.extend(products)

    unique = list({p["asin"]: p for p in all_products if p["asin"]}.values())
    new_products = [p for p in unique if p["asin"] not in seen]

    print(f"\n[Sistem] Toplam benzersiz ürün: {len(unique)}")
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
    print(f"[Sistem] {len(new_products)} yeni ürün bildirildi.")


if __name__ == "__main__":
    main()
