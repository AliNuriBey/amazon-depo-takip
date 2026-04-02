import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]

# Sadece tek bir ürünü debug et
TEST_ASIN = "B0FCMVXGCS"
TEST_URL = "https://www.amazon.com.tr/s?srs=44219324031&bbn=44219324031&s=date-desc-rank&fs=true&rh=n%3A44219324031%2Cn%3A21324944031"


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, json=payload, timeout=10)


def main():
    print("=== PRICE DEBUG ===")

    params = {
        "api_key": SCRAPER_API_KEY,
        "url": TEST_URL,
        "country_code": "tr",
        "render": "false",
    }

    r = requests.get("https://api.scraperapi.com", params=params, timeout=60)
    print(f"HTTP: {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Hedef ASIN'i bul
    target = soup.find("div", {"data-asin": TEST_ASIN})

    if not target:
        print(f"ASIN {TEST_ASIN} bu sayfada bulunamadı, ilk ürünü kullanıyoruz.")
        items = soup.select("div[data-asin]")
        target = next((i for i in items if i.get("data-asin")), None)

    if not target:
        print("Hiç ürün bulunamadı!")
        return

    asin = target.get("data-asin")
    print(f"\nASIN: {asin}")

    # Tüm class'ları içeren elementleri logla
    print("\n--- price class içeren tüm elementler ---")
    for tag in target.find_all(class_=lambda c: c and any("price" in x.lower() for x in c)):
        text = tag.get_text(strip=True)
        if text:
            print(f"  {tag.name} | {tag.get('class')} | '{text[:60]}'")

    print("\n--- TL içeren tüm elementler ---")
    for tag in target.find_all(["span", "div"]):
        text = tag.get_text(strip=True)
        if "TL" in text and any(c.isdigit() for c in text) and len(text) < 50:
            print(f"  {tag.name} | {tag.get('class')} | '{text}'")

    print("\n--- data-cy attribute içeren elementler ---")
    for tag in target.find_all(attrs={"data-cy": True}):
        print(f"  {tag.name} | data-cy={tag.get('data-cy')} | '{tag.get_text(strip=True)[:60]}'")

    # Telegram'a özet gönder
    msg = f"🔍 <b>Price Debug</b>\n\nASIN: {asin}\n\n"

    price_tags = []
    for tag in target.find_all(class_=lambda c: c and any("price" in x.lower() for x in c)):
        text = tag.get_text(strip=True)
        if text and len(text) < 50:
            price_tags.append(f"{tag.get('class')}: {text}")

    if price_tags:
        msg += "Price class'ları:\n" + "\n".join(price_tags[:10])
    else:
        msg += "❌ Hiç price class bulunamadı"

    tl_tags = []
    for tag in target.find_all(["span", "div"]):
        text = tag.get_text(strip=True)
        if "TL" in text and any(c.isdigit() for c in text) and len(text) < 50:
            tl_tags.append(f"{tag.name}.{tag.get('class', ['?'])[0]}: {text}")

    if tl_tags:
        msg += "\n\nTL içeren:\n" + "\n".join(tl_tags[:10])
    else:
        msg += "\n\n❌ TL içeren element bulunamadı"

    send_telegram(msg)
    print("\nTelegram'a debug mesajı gönderildi.")


if __name__ == "__main__":
    main()
