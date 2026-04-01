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

# Amazon Türkiye – Amazon Depo tüm kategoriler, en yeni ürünler önce
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


def scrape_page(target_url: str) -> list:
    """ScraperAPI üzerinden Amazon sayfasını çek."""
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

    items = soup.select("div[data-asin]")
    print(f"[Scraper] {len(items)} öğe parse edildi.")

    for item in items:
        asin = item.get("data-asin", "").strip()
        if not asin:
            continue

        name_tag = item.select_one("h2 a span")
        name = name_tag.get_text(strip=True) if name_tag else "İsim bulunamadı"

        price_tag = item.select_one(".a-price .a-offscreen")
        price = price_tag.get_text(strip=True) if price_tag else "Fiyat yok"

        link_tag = item.select_one("h2 a")
        link = (
            "https://www.amazon.com.tr" + link_tag["href"]
            if link_tag and link_tag.get("href")
            else f"https://www.amazon.com.tr/dp/{asin}"
        )

        products.append({
            "asin": asin,
            "name": name,
            "price": price,
            "link": link,
        })

    print(f"[Scraper] {len(products)} geçerli ürün bulundu.")
    return products


def format_message(product: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🏷️ <b>Yeni Amazon Depo Ürünü!</b>\n\n"
        f"📦 <b>{product['name'][:100]}</b>\n"
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

    # Tekrar edenleri temizle
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
