import requests
import time
import hashlib
from datetime import datetime

BOT_TOKEN = "8681026360:AAEWL0f-vR5A6TZ_48joKDm5mfb7pL_7Nq4"
CHAT_ID = "8744993955"

# BaFin 官方 Ad-hoc 公告接口（德国金融监管局，公开API）
API_URL = "https://www.bafin.de/SiteGlobals/Forms/Suche/Adhoc_Suche_Formular.html?input_=4038544&pageLocale=de&sortOrder=dateDesc&templateQueryString="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9",
}

INTERVAL = 60
known_ids = set()
is_first_run = True

def send_telegram(msg):
    try:
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram failed: " + str(e))

def get_items():
    from bs4 import BeautifulSoup
    resp = requests.get(API_URL, headers=HEADERS, timeout=30)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # BaFin 结果列表
    for el in soup.select(".c-result-list__item, .result-item, article, .c-teaser"):
        a = el.find("a", href=True)
        if not a:
            continue
        title = el.get_text(separator=" ", strip=True)[:200]
        href = a["href"]
        full_url = href if href.startswith("http") else "https://www.bafin.de" + href
        uid = hashlib.md5(full_url.encode()).hexdigest()
        if len(title) > 10:
            items.append({"id": uid, "title": title, "url": full_url})

    # fallback
    if not items:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            if len(title) < 15:
                continue
            if "adhoc" not in href.lower() and "ad-hoc" not in href.lower():
                continue
            full_url = href if href.startswith("http") else "https://www.bafin.de" + href
            uid = hashlib.md5(full_url.encode()).hexdigest()
            items.append({"id": uid, "title": title, "url": full_url})

    seen = set()
    unique = []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            unique.append(it)
    return unique

def check():
    global is_first_run, known_ids
    now = datetime.now().strftime("%H:%M:%S")

    if is_first_run:
        print("[" + now + "] initializing...")
        try:
            items = get_items()
            known_ids = set(it["id"] for it in items)
            print("  adhoc items found: " + str(len(items)))
            if items:
                print("  latest: " + items[0]["title"][:80])
        except Exception as e:
            print("  failed: " + str(e))
        is_first_run = False
        send_telegram("EQS Ad-hoc monitor started (BaFin source). Checking every 60s.")
        print("  started, telegram sent\n")
        return

    print("[" + now + "] checking...", end=" ", flush=True)
    try:
        items = get_items()
        new_items = [it for it in items if it["id"] not in known_ids]
        if new_items:
            for it in new_items:
                known_ids.add(it["id"])
                msg = "🚨 Ad-hoc 新公告！\n\n" + it["title"][:200] + "\n\n链接：" + it["url"]
                send_telegram(msg)
                print("\n  AD-HOC: " + it["title"][:80])
        else:
            print("ok, no new items (" + str(len(items)) + " total)")
    except Exception as e:
        print("\n  failed: " + str(e))

print("EQS Ad-hoc monitor starting (BaFin source)...")
while True:
    check()
    time.sleep(INTERVAL)
