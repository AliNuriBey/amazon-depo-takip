from dotenv import load_dotenv
load_dotenv('/opt/scraper/.env')

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STOCK_FILE = "/opt/scraper/stock_mediamarkt.json"

# Koşul 1: İndirim yüzdesi eşiği
DISCOUNT_PCT_THRESHOLD = 30.0

# Koşul 2: Sepette indirim / ürün fiyatı eşiği
BASKET_DISCOUNT_RATIO_THRESHOLD = 30.0

CATEGORIES = {
    "📱 Telefon":            "https://www.mediamarkt.com.tr/tr/category/telefon-465595.html",
    "💻 Bilgisayar":         "https://www.mediamarkt.com.tr/tr/category/bilgisayar-504925.html",
    "📺 TV, Görüntü ve Ses": "https://www.mediamarkt.com.tr/tr/category/tv-goruntu-ve-ses-678536.html",
    "📷 Foto & Drone":       "https://www.mediamarkt.com.tr/tr/category/foto-kamera-drone-465682.html",
    "🏠 Beyaz Eşya":         "https://www.mediamarkt.com.tr/tr/category/beyaz-esya-465707.html",
    "🔧 Ev Aletleri":        "https://www.mediamarkt.com.tr/tr/category/ev-aletleri-yasam-465737.html",
    "💄 Kişisel Bakım":      "https://www.mediamarkt.com.tr/tr/category/kisisel-bakim-465820.html",
    "⚽ Spor & Outdoor":     "https://www.mediamarkt.com.tr/tr/category/spor-outdoor-465862.html",
    "🌿 Bahçe & Yapı":       "https://www.mediamarkt.com.tr/tr/category/bahce-yapi-market-90394.html",
    "🎮 Hobi & Eğlence":     "https://www.mediamarkt.com.tr/tr/category/hobi-eglence-90527.html",
    "❄️ Isıtma & Soğutma":  "https://www.mediamarkt.com.tr/tr/category/isitma-sogutma-465751.html",
    "🎧 Aksesuar":           "https://www.mediamarkt.com.tr/tr/category/aksesuar-640513.html",
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
]


def load_stock():
    if os.path.exists(STOCK_FILE):
        with open(STOCK_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                pass
    return {}


def save_stock(stock):
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


def parse_price(s):
    """'5.249' veya '5249' → 5249.0"""
    if not s:
        return None
    try:
        cleaned = re.sub(r'[^\d,.]', '', s.strip())
        # Türkçe format: nokta binlik, virgül ondalık
        if ',' in cleaned and '.' in cleaned:
            cleaned = cleaned.replace('.', '').replace(',', '.')
        elif ',' in cleaned:
            cleaned = cleaned.replace(',', '.')
        return float(cleaned)
    except:
        return None


def parse_discount_pct(s):
    """'-%37,39' → 37.39"""
    if not s:
        return None
    try:
        cleaned = re.sub(r'[^\d,.]', '', s.strip())
        cleaned = cleaned.replace(',', '.')
        return float(cleaned)
    except:
        return None


def scrape_category(cat_name, url):
    """Kategori sayfasını scrape et, uygun ürünleri döndür."""
    headers = random.choice(HEADERS_LIST)
    try:
        time.sleep(random.uniform(2, 4))
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        print(f"[{cat_name}] HTTP {r.status_code}")
    except Exception as e:
        print(f"[{cat_name}] Çekilemedi: {e}")
        return []

    html = r.text

    # Ürün adlarını JSON'dan çek
    names = re.findall(r'"name":"([^"]+)"', html)
    # Fiyatları JSON'dan çek
    prices_raw = re.findall(r'"price":(\d+(?:\.\d+)?)', html)
    # Ürün linklerini HTML'den çek (tekrarları temizle)
    links_raw = re.findall(r'href="(/tr/product/[^"]+\.html)"', html)
    # Tekrar eden linkleri sırayla al (her ürün 2 kez çıkıyor)
    links_unique = list(dict.fromkeys(links_raw))

    # İndirim yüzdesi badge'lerini çek: -%37,39 formatında
    discount_pcts_raw = re.findall(r'<span>-(% *\d+[,.]?\d*)</span>', html)
    # Alternatif format
    if not discount_pcts_raw:
        discount_pcts_raw = re.findall(r'-%(\d+[,.]?\d*)', html)

    # Sepette indirim tutarlarını çek
    # Format: <span>-400,</span><span>–</span><span> ₺</span>
    basket_discounts_raw = re.findall(r'>-(\d+(?:\.\d{3})*),</span>', html)

    print(f"[{cat_name}] Ad: {len(names)}, Fiyat: {len(prices_raw)}, Link: {len(links_unique)}, İndirim%: {len(discount_pcts_raw)}, SepetteIndirim: {len(basket_discounts_raw)}")

    # BeautifulSoup ile daha detaylı parse
    soup = BeautifulSoup(html, "html.parser")
    products = []

    # JSON'dan ürün verilerini çek
    # Her ürünün name ve price'ını eşleştir
    product_blocks = []

    # Script taglarındaki JSON'u bul
    scripts = soup.find_all('script')
    json_data = None
    for script in scripts:
        if script.string and '"products"' in script.string:
            # JSON bloğunu bul
            match = re.search(r'"products"\s*:\s*(\[.*?\])', script.string, re.DOTALL)
            if match:
                try:
                    product_blocks = json.loads(match.group(1))
                    break
                except:
                    pass

    # Eğer JSON parse başarısız olduysa regex ile devam et
    if not product_blocks:
        # names ve prices ve links'i eşleştir
        min_len = min(len(names), len(prices_raw), len(links_unique))
        for i in range(min_len):
            price = parse_price(prices_raw[i])
            if not price:
                continue

            # İndirim yüzdesi
            discount_pct = None
            if i < len(discount_pcts_raw):
                discount_pct = parse_discount_pct(discount_pcts_raw[i])

            # Sepette indirim
            basket_discount = None
            if i < len(basket_discounts_raw):
                basket_discount = parse_price(basket_discounts_raw[i])

            link = "https://www.mediamarkt.com.tr" + links_unique[i]

            product_blocks.append({
                "name": names[i],
                "price": price,
                "discount_pct": discount_pct,
                "basket_discount": basket_discount,
                "link": link,
                "category": cat_name,
            })

    # Koşulları kontrol et
    qualifying = []
    for p in product_blocks:
        if isinstance(p, dict) and "name" in p:
            name = p.get("name", "")
            price = p.get("price") if isinstance(p.get("price"), float) else parse_price(str(p.get("price", "")))
            discount_pct = p.get("discount_pct")
            basket_discount = p.get("basket_discount")
            link = p.get("link", "")
            category = p.get("category", cat_name)

            if not price or not name:
                continue

            qualifies = False
            reason = []

            # Koşul 1: İndirim yüzdesi %30+
            if discount_pct and discount_pct >= DISCOUNT_PCT_THRESHOLD:
                qualifies = True
                reason.append(f"indirim %{discount_pct:.1f}")

            # Koşul 2: Sepette indirim oranı %30+
            if basket_discount and price > 0:
                basket_ratio = (basket_discount / price) * 100
                if basket_ratio >= BASKET_DISCOUNT_RATIO_THRESHOLD:
                    qualifies = True
                    reason.append(f"sepette %{basket_ratio:.1f}")

            if qualifies:
                qualifying.append({
                    "name": name,
                    "price": price,
                    "discount_pct": discount_pct,
                    "basket_discount": basket_discount,
                    "link": link,
                    "category": category,
                    "reason": ", ".join(reason),
                })

    return qualifying


def format_message(product, is_new=True):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    price_str = f"{product['price']:,.0f} TL".replace(",", ".")

    lines = []
    lines.append(f"🔥 <b>MediaMarkt Fırsat!</b>")
    lines.append(f"📂 <b>{product['category']}</b>")
    lines.append(f"")
    lines.append(f"📦 {product['name'][:120]}")
    lines.append(f"")
    lines.append(f"💰 <b>{price_str}</b>")

    if product.get("discount_pct"):
        lines.append(f"📉 <b>%{product['discount_pct']:.1f} indirimli</b>")

    if product.get("basket_discount"):
        basket_ratio = (product["basket_discount"] / product["price"]) * 100
        lines.append(f"🛒 <b>Sepette -{product['basket_discount']:,.0f} TL (%{basket_ratio:.1f})</b>")

    lines.append(f"")
    lines.append(f"🔗 <a href=\"{product['link']}\">Ürüne Git</a>")
    lines.append(f"🕐 {now}")

    return "\n".join(lines)


def main():
    print(f"\n{'='*50}")
    print(f"MediaMarkt Takip – {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*50}")

    stock = load_stock()
    print(f"[Sistem] Kayıtlı ürün: {len(stock)}")

    all_qualifying = []
    for cat_name, url in CATEGORIES.items():
        products = scrape_category(cat_name, url)
        print(f"[{cat_name}] {len(products)} uygun ürün bulundu")
        all_qualifying.extend(products)
        time.sleep(random.uniform(1, 3))

    print(f"\n[Sistem] Toplam uygun: {len(all_qualifying)}")

    notified = 0
    now_str = datetime.now().isoformat()

    for product in all_qualifying:
        key = product["link"]

        if key not in stock:
            # Yeni ürün — bildirim gönder
            send_telegram(format_message(product, is_new=True))
            stock[key] = {
                "name": product["name"],
                "first_price": product["price"],
                "first_seen": now_str,
                "last_seen": now_str,
                "discount_pct": product.get("discount_pct"),
                "basket_discount": product.get("basket_discount"),
            }
            notified += 1
            time.sleep(1)
        else:
            # Daha önce görüldü — fiyat düştüyse bildirim gönder
            first_price = stock[key].get("first_price", product["price"])
            if product["price"] < first_price:
                product["reason"] += f" (ilk fiyattan daha ucuz: {first_price:,.0f} TL)"
                send_telegram(format_message(product))
                stock[key]["first_price"] = product["price"]
                notified += 1
                time.sleep(1)
            stock[key]["last_seen"] = now_str

    print(f"[Sistem] {notified} bildirim gönderildi.")
    save_stock(stock)


if __name__ == "__main__":
    main()
