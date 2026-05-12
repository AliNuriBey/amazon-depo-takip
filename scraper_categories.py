from dotenv import load_dotenv
load_dotenv('/opt/scraper/.env')

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STOCK_FILE = "/opt/scraper/stock_categories.json"

# Kaç gün sonra "tekrar stok" sayılsın?
RESTOCK_DAYS = 30
# Fiyat düşüşü bildirimi için minimum yüzde
PRICE_DROP_THRESHOLD = 5  # %5 düşüş
# Kaç kez görünmeyince "düştü" sayılsın?
MISS_THRESHOLD = 3
# Kategori başına maksimum sayfa
MAX_PAGES = 20

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

HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
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
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
    },
]


def load_stock():
    """
    Format:
    {
        "active": {
            "ASIN": {
                "label": "...",
                "miss_count": 0,
                "first_seen": "2026-01-01T00:00:00",
                "first_price": 1234.56,
                "last_price": 1234.56,
                "lowest_price": 1000.00
            }
        },
        "inactive": {
            "ASIN": {
                "label": "...",
                "dropped_at": "2026-01-01T00:00:00",
                "last_price": 1234.56,
                "lowest_price": 1000.00
            }
        }
    }
    """
    if os.path.exists(STOCK_FILE):
        with open(STOCK_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, dict) and "active" in data:
                    # Eski format dönüştür
                    for asin, val in data["active"].items():
                        if isinstance(val, str):
                            data["active"][asin] = {
                                "label": val,
                                "miss_count": 0,
                                "first_seen": datetime.now().isoformat(),
                                "first_price": None,
                                "last_price": None,
                                "lowest_price": None,
                            }
                        else:
                            # Eksik alanları tamamla
                            val.setdefault("first_seen", datetime.now().isoformat())
                            val.setdefault("first_price", None)
                            val.setdefault("last_price", None)
                            val.setdefault("lowest_price", None)
                    for asin, val in data.get("inactive", {}).items():
                        if isinstance(val, str):
                            data["inactive"][asin] = {
                                "label": "",
                                "dropped_at": val,
                                "last_price": None,
                                "lowest_price": None,
                            }
                        else:
                            val.setdefault("dropped_at", datetime.now().isoformat())
                            val.setdefault("last_price", None)
                            val.setdefault("lowest_price", None)
                    return data
            except:
                pass
    return {"active": {}, "inactive": {}}


def save_stock(stock: dict):
    with open(STOCK_FILE, "w", encoding="utf-8") as f:
        json.dump(stock, f, ensure_ascii=False, indent=2)


def parse_price(price_str: str):
    """Fiyat stringini float'a çevir. '1.234,56 TL' → 1234.56"""
    if not price_str:
        return None
    try:
        cleaned = re.sub(r'[^\d,.]', '', price_str)
        # Türkçe format: nokta binlik ayırıcı, virgül ondalık
        if ',' in cleaned and '.' in cleaned:
            cleaned = cleaned.replace('.', '').replace(',', '.')
        elif ',' in cleaned:
            cleaned = cleaned.replace(',', '.')
        return float(cleaned)
    except:
        return None


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


def extract_price_str(item):
    full_text = item.get_text(" ", strip=True)
    match = re.search(r'seçenekleri[:\s]+([\d.,]+\s*TL)', full_text)
    if match:
        return match.group(1).strip()
    matches = re.findall(r'([\d]{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\s*TL)', full_text)
    if matches:
        return matches[0].strip()
    return None


def extract_link(item, asin):
    for sel in ["h2 a", "a.a-link-normal.s-no-outline", "a[href*='/dp/']"]:
        tag = item.select_one(sel)
        if tag and tag.get("href"):
            href = tag["href"]
            return href if href.startswith("http") else "https://www.amazon.com.tr" + href
    return f"https://www.amazon.com.tr/dp/{asin}"


def scrape_page(label: str, target_url: str) -> list:
    headers = random.choice(HEADERS_LIST)
    try:
        time.sleep(random.uniform(1, 3))
        r = requests.get(target_url, headers=headers, timeout=20)
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
        price_str = extract_price_str(item)
        if not price_str:
            continue
        products.append({
            "asin": asin,
            "name": name,
            "price_str": price_str,
            "price": parse_price(price_str),
            "link": extract_link(item, asin),
            "label": f"🗂 {label}",
        })

    return products


def scrape_category(category: str, node: str) -> list:
    all_products = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{BASE}&rh=n%3A44219324031%2Cn%3A{node}"
        if page > 1:
            url += f"&page={page}"
        products = scrape_page(category, url)
        if not products:
            print(f"[{category}] Sayfa {page} boş, duruyorum.")
            break
        all_products.extend(products)
        print(f"[{category}] Sayfa {page}: {len(products)} ürün")
    print(f"[{category}] Toplam: {len(all_products)} ürün")
    return all_products


def format_new_message(product: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🆕 <b>Yeni Amazon Depo Ürünü!</b>\n"
        f"📂 <b>{product['label']}</b>\n\n"
        f"📦 {product['name'][:120]}\n\n"
        f"💰 <b>{product['price_str']}</b>\n\n"
        f"🔗 <a href=\"{product['link']}\">Ürüne Git</a>\n\n"
        f"🕐 {now}"
    )


def format_restock_message(product: dict, days_gone: int) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🔄 <b>Tekrar Stoğa Girdi!</b> ({days_gone} gün sonra)\n"
        f"📂 <b>{product['label']}</b>\n\n"
        f"📦 {product['name'][:120]}\n\n"
        f"💰 <b>{product['price_str']}</b>\n\n"
        f"🔗 <a href=\"{product['link']}\">Ürüne Git</a>\n\n"
        f"🕐 {now}"
    )


def format_price_drop_message(product: dict, old_price: float, new_price: float, drop_pct: float) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"📉 <b>Fiyat Düştü!</b>\n"
        f"📂 <b>{product['label']}</b>\n\n"
        f"📦 {product['name'][:120]}\n\n"
        f"💰 <s>{old_price:,.2f} TL</s> → <b>{new_price:,.2f} TL</b>\n"
        f"📊 <b>%{drop_pct:.1f} indirim</b>\n\n"
        f"🔗 <a href=\"{product['link']}\">Ürüne Git</a>\n\n"
        f"🕐 {now}"
    )


def main():
    print(f"\n{'='*50}")
    print(f"Kategori Takip – {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")

    stock = load_stock()
    active = stock["active"]
    inactive = stock["inactive"]
    print(f"[Sistem] Aktif: {len(active)} | İnaktif: {len(inactive)}")

    all_products = []
    for category, node in CATEGORIES.items():
        products = scrape_category(category, node)
        all_products.extend(products)

    current = {p["asin"]: p for p in all_products if p["asin"]}
    current_asins = set(current.keys())
    active_asins = set(active.keys())
    inactive_asins = set(inactive.keys())
    now = datetime.now()

    notified = 0

    # 1. Yeni ürünler — hiç görülmemiş
    new_asins = current_asins - active_asins - inactive_asins
    for asin in new_asins:
        product = current[asin]
        send_telegram(format_new_message(product))
        active[asin] = {
            "label": product["label"],
            "miss_count": 0,
            "first_seen": now.isoformat(),
            "first_price": product["price"],
            "last_price": product["price"],
            "lowest_price": product["price"],
        }
        notified += 1
        time.sleep(1)

    # 2. Tekrar stok — 30+ gün önce inactive'e düşmüş
    restock_asins = current_asins & inactive_asins
    for asin in restock_asins:
        product = current[asin]
        inactive_data = inactive[asin]
        dropped_at = datetime.fromisoformat(inactive_data.get("dropped_at", now.isoformat()))
        days_gone = (now - dropped_at).days

        if days_gone >= RESTOCK_DAYS:
            send_telegram(format_restock_message(product, days_gone))
            notified += 1
            time.sleep(1)

        # Her halükarda active'e taşı
        old_lowest = inactive_data.get("lowest_price")
        active[asin] = {
            "label": product["label"],
            "miss_count": 0,
            "first_seen": now.isoformat(),
            "first_price": product["price"],
            "last_price": product["price"],
            "lowest_price": min(filter(None, [old_lowest, product["price"]])) if old_lowest or product["price"] else None,
        }
        del inactive[asin]

    # 3. Mevcut aktif ürünler — fiyat takibi
    still_active = current_asins & active_asins
    for asin in still_active:
        product = current[asin]
        active_data = active[asin]
        new_price = product["price"]
        last_price = active_data.get("last_price")
        lowest_price = active_data.get("lowest_price")

        # Miss count sıfırla
        active[asin]["miss_count"] = 0
        active[asin]["label"] = product["label"]

        if new_price and last_price and new_price < last_price:
            drop_pct = ((last_price - new_price) / last_price) * 100
            if drop_pct >= PRICE_DROP_THRESHOLD:
                send_telegram(format_price_drop_message(product, last_price, new_price, drop_pct))
                notified += 1
                time.sleep(1)

        # Fiyatları güncelle
        if new_price:
            active[asin]["last_price"] = new_price
            if lowest_price is None or new_price < lowest_price:
                active[asin]["lowest_price"] = new_price

    # 4. Görünmeyenlerin miss_count artır
    missing_asins = active_asins - current_asins
    truly_dropped = []
    for asin in missing_asins:
        active[asin]["miss_count"] = active[asin].get("miss_count", 0) + 1
        if active[asin]["miss_count"] >= MISS_THRESHOLD:
            truly_dropped.append(asin)

    for asin in truly_dropped:
        inactive[asin] = {
            "label": active[asin].get("label", ""),
            "dropped_at": now.isoformat(),
            "last_price": active[asin].get("last_price"),
            "lowest_price": active[asin].get("lowest_price"),
        }
        del active[asin]
        print(f"[Sistem] {asin} inactive'e alındı.")

    print(f"[Sistem] Yeni: {len(new_asins)} | Tekrar(30gün+): {len([a for a in restock_asins if (now - datetime.fromisoformat(inactive.get(a, {}).get('dropped_at', now.isoformat()))).days >= RESTOCK_DAYS])} | Düşen: {len(truly_dropped)}")
    print(f"[Sistem] {notified} bildirim gönderildi.")

    save_stock({"active": active, "inactive": inactive})


if __name__ == "__main__":
    main()
