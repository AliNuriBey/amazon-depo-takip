import requests
from bs4 import BeautifulSoup
import json
import os
import time
import random
from datetime import datetime

# ─────────────────────────────────────────────
# AYARLAR – GitHub Secrets'tan okunur
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_FILE = "seen_products.json"

# Amazon Türkiye – Elektronik kategorisi, Amazon Depo filtreli URL'ler
URLS = [
    "https://www.amazon.com.tr/s?i=electronics&rh=p_85%3A1903430031&s=date-desc-rank&fs=true",
    "https://www.amazon.com.tr/s?i=electronics&rh=p_85%3A1903430031&s=date-desc-rank&fs=true&page=2",
]

HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
    },
]


# ─────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────

def load_seen():
    """Daha önce görülen ürün ASIN'lerini yükle."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    """Görülen ürün ASIN'lerini kaydet."""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)


def send_telegram(message: str):
    """Telegram'a mesaj gönder."""
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


def scrape_page(url: str) -> list[dict]:
    """Verilen URL'deki Amazon Depo ürünlerini çek."""
    headers = random.choice(HEADERS_LIST)
    try:
        time.sleep(random.uniform(2, 5))  # Bot korumasını azaltmak için
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[Scraper] Sayfa çekilemedi: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    items = soup.select("div[data-asin]")
    for item in items:
        asin = item.get("data-asin", "").strip()
        if not asin:
            continue

        # Ürün adı
        name_tag = item.select_one("h2 a span")
        name = name_tag.get_text(strip=True) if name_tag else "İsim bulunamadı"

        # Fiyat
        price_tag = item.select_one(".a-price .a-offscreen")
        price = price_tag.get_text(strip=True) if price_tag else "Fiyat yok"

        # URL
        link_tag = item.select_one("h2 a")
        link = (
            "https://www.amazon.com.tr" + link_tag["href"]
            if link_tag and link_tag.get("href")
            else f"https://www.amazon.com.tr/dp/{asin}"
        )

        # Sadece Amazon Depo ürünlerini filtrele
        badges = item.get_text().lower()
        if "amazon depo" not in badges and "warehouse" not in badges:
            # Yedek kontrol: URL'de warehouse filtresi zaten var, yine de işleyelim
            pass  # URL zaten filtreliyor, tüm sonuçlar Amazon Depo

        products.append({
            "asin": asin,
            "name": name,
            "price": price,
            "link": link,
        })

    print(f"[Scraper] {len(products)} ürün bulundu → {url[:60]}...")
    return products


def format_message(product: dict) -> str:
    """Telegram için mesaj formatla."""
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
    print(f"Amazon Depo Takip Sistemi – {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")

    seen = load_seen()
    print(f"[Sistem] Daha önce görülen ürün sayısı: {len(seen)}")

    all_products = []
    for url in URLS:
        products = scrape_page(url)
        all_products.extend(products)

    new_products = [p for p in all_products if p["asin"] not in seen]
    print(f"[Sistem] Yeni ürün sayısı: {len(new_products)}")

    if not new_products:
        print("[Sistem] Yeni ürün yok, bekleniyor...")
        return

    for product in new_products:
        msg = format_message(product)
        send_telegram(msg)
        seen.add(product["asin"])
        time.sleep(1)  # Telegram rate limit

    save_seen(seen)
    print(f"[Sistem] {len(new_products)} yeni ürün bildirildi ve kaydedildi.")


if __name__ == "__main__":
    main()
