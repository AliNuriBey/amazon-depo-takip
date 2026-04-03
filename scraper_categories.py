import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]

# Kategoriler için ayrı dosya
STOCK_FILE = "stock_categories.json"

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


def load_stock():
    if os.path.exists(STOCK_FILE):
        with open(STOCK_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, dict) and "active" in data:
                    return data
            except:
                pass
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
            "label": f"🗂 {label}",
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
    print(f"Kategori Takip – {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")

    stock = load_stock()
    previously_active = set(stock["active"].keys())
    inactive = stock["inactive"]
    print(f"[Sistem] Önceki aktif: {len(previously_active)} | İnaktif: {len(inactive)}")

    all_products = []
    for category, node in CATEGORIES.items():
        for page in range(1, 3):
            url = f"{BASE}&rh=n%3A44219324031%2Cn%3A{node}"
            if page > 1:
                url += f"&page={page}"
            products = scrape_page(category, url)
            all_products.extend(products)

    current = {p["asin"]: p for p in all_products if p["asin"]}
    current_asins = set(current.keys())

    new_asins = current_asins - previously_active - set(inactive.keys())
    restock_asins = current_asins & set(inactive.keys())
    dropped_asins = previously_active - current_asins

    print(f"[Sistem] Yeni: {len(new_asins)} | Tekrar: {len(restock_asins)} | Düşen: {len(dropped_asins)}")

    notified = 0
    for asin in new_asins:
        send_telegram(format_message(current[asin], is_restock=False))
        notified += 1
        time.sleep(1)

    for asin in restock_asins:
        send_telegram(format_message(current[asin], is_restock=True))
        inactive.pop(asin, None)
        notified += 1
        time.sleep(1)

    for asin in dropped_asins:
        inactive[asin] = datetime.now().isoformat()

    save_stock({
        "active": {asin: current[asin]["label"] for asin in current_asins},
        "inactive": inactive,
    })

    print(f"[Sistem] {notified} bildirim gönderildi.")


if __name__ == "__main__":
    main()
