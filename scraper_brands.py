import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]

# seen_products.json yapısı:
# {
#   "active": {"ASIN": "label", ...},   ← şu an listede olanlar
#   "inactive": {"ASIN": timestamp, ...} ← listeden düşenler (tekrar girerse bildir)
# }
STOCK_FILE = "seen_products.json"

BRAND_URLS = {
    "🍎 Apple":       "https://www.amazon.com.tr/s?k=apple&i=warehouse-deals&srs=44219324031",
    "🎵 Sony":        "https://www.amazon.com.tr/s?k=sony&i=warehouse-deals&srs=44219324031",
    "🎮 SteelSeries": "https://www.amazon.com.tr/s?k=steelseries&i=warehouse-deals&srs=44219324031",
    "💡 Hue":         "https://www.amazon.com.tr/s?k=Hue&i=warehouse-deals&srs=44219324031",
    "🖱 Logitech":    "https://www.amazon.com.tr/s?k=Logitech&i=warehouse-deals&srs=44219324031",
    "🔧 Bosch Home":  "https://www.amazon.com.tr/s?k=Bosch+Home&i=warehouse-deals&srs=44219324031",
}


def load_stock():
    if os.path.exists(STOCK_FILE):
        with open(STOCK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Eski format uyumluluğu (düz set ise sıfırla)
            if isinstance(data, list):
                return {"active": {}, "inactive": {}}
            return data
    return {"active": {}, "inactive": {}}


def save_stock(stock: dict):
    with open(STOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(stock, f, ensure_ascii=False, indent=2)


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
        "h2 a span", "h2 span",
        ".a-size-medium.a-color-base.a-text-normal",
        ".a-size-base-plus.a-color-base.a-text-normal",
        "[data-cy='title-recipe'] span",
    ]
    for sel in selectors:
        tag = item.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if text and len(text) > 3:
                return text
    return None


def extract_link(item, asin):
    for sel in ["h2 a", "a.a-link-normal.s-no-outline", "a[href*='/dp/']"]:
        tag = item.select_one(sel)
        if tag and tag.get("href"):
            href = tag["href"]
            return href if href.startswith("http") else "https://www.amazon.com.tr" + href
    return f"https://www.amazon.com.tr/dp/{asin}"


def scrape_page(label: str, target_url: str) -> list:
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
        print(f"[Scraper] {label} çekilemedi: {e}")
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
        products.append({
            "asin": asin,
            "name": name,
            "link": extract_link(item, asin),
            "label": label,
        })

    print(f"[{label}] {len(products)} ürün bulundu.")
    return products


def format_message(product: dict, is_restock: bool = False) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    status = "🔄 <b>Tekrar Stoğa Girdi!</b>" if is_restock else "🆕 <b>Yeni Amazon Depo Ürünü!</b>"
    return (
        f"{status}\n"
        f"📂 <b>{product['label']}</b>\n\n"
        f"📦 {product['name'][:120]}\n\n"
        f"🔗 <a href=\"{product['link']}\">Ürüne Git → Fiyatı Gör</a>\n\n"
        f"🕐 {now}"
    )


def main():
    print(f"\n{'='*50}")
    print(f"Marka Takip – {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")

    stock = load_stock()
    previously_active = set(stock.get("active", {}).keys())
    inactive = stock.get("inactive", {})

    # Tüm sayfaları tara
    all_products = []
    for label, url in BRAND_URLS.items():
        products = scrape_page(label, url)
        all_products.extend(products)

    # Şu an listede olan benzersiz ürünler
    current = {p["asin"]: p for p in all_products if p["asin"]}
    current_asins = set(current.keys())

    # Yeni stok: şu an var ama daha önce active'de yoktu
    new_asins = current_asins - previously_active
    # Tekrar stok: şu an var, daha önce inactive'deydi
    restock_asins = current_asins & set(inactive.keys())
    # Stoktan düşenler: daha önce active'deydi, şimdi yok
    dropped_asins = previously_active - current_asins

    print(f"[Sistem] Aktif: {len(current_asins)} | Yeni: {len(new_asins)} | Tekrar: {len(restock_asins)} | Düşen: {len(dropped_asins)}")

    # Bildirimleri gönder
    notified = 0
    for asin in new_asins:
        product = current[asin]
        send_telegram(format_message(product, is_restock=False))
        notified += 1
        time.sleep(1)

    for asin in restock_asins:
        product = current[asin]
        send_telegram(format_message(product, is_restock=True))
        # inactive'den çıkar
        inactive.pop(asin, None)
        notified += 1
        time.sleep(1)

    # Stoktan düşenleri inactive'e taşı
    for asin in dropped_asins:
        inactive[asin] = datetime.now().isoformat()

    # Stoku kaydet
    stock = {
        "active": {asin: current[asin]["label"] for asin in current_asins},
        "inactive": inactive,
    }
    save_stock(stock)

    print(f"[Sistem] {notified} bildirim gönderildi.")


if __name__ == "__main__":
    main()
