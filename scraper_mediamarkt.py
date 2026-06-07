from dotenv import load_dotenv
load_dotenv('/opt/scraper/.env')

import os, re, json, time, random
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STOCK_FILE = "/opt/scraper/stock_mediamarkt.json"
THRESHOLD = 30.0
CHROMIUM = '/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome'
MAX_PAGES = 200

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

def load_stock():
    if os.path.exists(STOCK_FILE):
        try:
            with open(STOCK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_stock(stock):
    tmp = STOCK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stock, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STOCK_FILE)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[Telegram] Hata: {e}")

def parse_price(html):
    # ₺ işaretli fiyatı bul: ₺5.249,–
    matches = re.findall(r'₺([\d.]+),', html)
    if matches:
        try:
            return float(matches[0].replace('.', ''))
        except:
            pass
    return None

def scrape_page(page, cat_name, url):
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        for _ in range(8):
            page.evaluate('window.scrollBy(0, 1000)')
            page.wait_for_timeout(400)
    except Exception as e:
        print(f"[{cat_name}] Hata: {e}")
        return [], False

    price_els = page.query_selector_all('[data-test="cofr-price product-price"]')
    name_els = page.query_selector_all('a[data-test="mms-router-link-product-list-item-link"]')

    if not price_els:
        return [], False

    results = []
    for p_el, n_el in zip(price_els, name_els):
        try:
            name = n_el.inner_text().strip()
            href = n_el.get_attribute('href')
            link = "https://www.mediamarkt.com.tr" + href if href else ""

            html = p_el.evaluate('el => el.parentElement?.parentElement?.parentElement?.parentElement?.innerHTML || ""')
            
            # Fiyatı ₺ işaretinden parse et
            price = parse_price(html)
            if not price:
                continue

            basket_raw = re.findall(r'>-(\d+(?:\.\d{3})*),</span>', html)
            discount_raw = re.findall(r'>-([\d]+[,.]\d+)%<|>-%\s*([\d]+[,.]\d+)<', html)

            basket = None
            if basket_raw:
                basket = float(basket_raw[0].replace('.', '').replace(',', '.'))

            # İndirim yüzdesi badge'i: -%48,84
            discount_pct = None
            disc_matches = re.findall(r'>-(%[\d]+[,.][\d]+)<', html)
            if disc_matches:
                d = disc_matches[0].replace('%', '').replace(',', '.')
                try:
                    discount_pct = float(d)
                except:
                    pass

            qualifies = False
            reasons = []

            if discount_pct and discount_pct >= THRESHOLD:
                qualifies = True
                reasons.append(f"%{discount_pct:.1f} indirim")

            if basket and price > 0:
                ratio = (basket / price) * 100
                if ratio >= THRESHOLD:
                    qualifies = True
                    reasons.append(f"sepette %{ratio:.1f}")

            if qualifies:
                results.append({
                    "name": name,
                    "price": price,
                    "discount_pct": discount_pct,
                    "basket": basket,
                    "link": link,
                    "category": cat_name,
                    "reason": ", ".join(reasons),
                })
        except Exception as e:
            continue

    return results, len(price_els) > 0

def scrape_category(page, cat_name, url):
    # marketplace=MediaMarkt filtresi ekle
    base_url = url + ("&" if "?" in url else "?") + "marketplace=MediaMarkt&sort=currentprice+asc"
    all_results = []
    for page_num in range(1, MAX_PAGES + 1):
        page_url = base_url if page_num == 1 else f"{base_url}&page={page_num}"
        results, has_products = scrape_page(page, cat_name, page_url)
        if has_products:
            print(f"[{cat_name}] Sayfa {page_num}: {len(results)} uygun")
        all_results.extend(results)
        if not has_products:
            print(f"[{cat_name}] Sayfa {page_num}: boş, duruyorum. Toplam: {len(all_results)}")
            break
        time.sleep(random.uniform(1, 2))
    return all_results

def format_msg(p):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    price_str = f"{p['price']:,.0f} TL".replace(",", ".")
    lines = [
        f"🔥 <b>MediaMarkt Fırsat!</b>",
        f"📂 <b>{p['category']}</b>",
        f"",
        f"📦 {p['name'][:120]}",
        f"",
        f"💰 <b>{price_str}</b>",
    ]
    if p.get("discount_pct"):
        lines.append(f"📉 <b>%{p['discount_pct']:.1f} indirimli</b>")
    if p.get("basket"):
        ratio = (p["basket"] / p["price"]) * 100
        lines.append(f"🛒 <b>Sepette -{p['basket']:,.0f} TL (%{ratio:.1f})</b>")
    lines += [f"", f"🔗 <a href=\"{p['link']}\">Ürüne Git</a>", f"🕐 {now}"]
    return "\n".join(lines)

def main():
    print(f"\n{'='*50}\nMediaMarkt Takip – {datetime.now().strftime('%d.%m.%Y %H:%M')}\n{'='*50}")
    stock = load_stock()
    print(f"[Sistem] Kayıtlı: {len(stock)}")

    all_results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=CHROMIUM,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        page = browser.new_page()
        for cat_name, url in CATEGORIES.items():
            results = scrape_category(page, cat_name, url)
            print(f"[{cat_name}] Toplam uygun: {len(results)}")
            all_results.extend(results)
            time.sleep(random.uniform(2, 4))
        browser.close()

    print(f"\n[Sistem] Toplam uygun: {len(all_results)}")
    notified = 0
    now_str = datetime.now().isoformat()

    for p in all_results:
        key = p["link"]
        if key not in stock:
            send_telegram(format_msg(p))
            stock[key] = {"name": p["name"], "price": p["price"], "first_seen": now_str, "last_seen": now_str}
            notified += 1
            time.sleep(1)
        else:
            old_price = stock[key].get("price", p["price"])
            if p["price"] < old_price:
                send_telegram(format_msg(p))
                stock[key]["price"] = p["price"]
                notified += 1
                time.sleep(1)
            stock[key]["last_seen"] = now_str

    print(f"[Sistem] {notified} bildirim gönderildi.")
    save_stock(stock)

if __name__ == "__main__":
    main()
