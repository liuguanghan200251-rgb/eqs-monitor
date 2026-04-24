import requests
from bs4 import BeautifulSoup
import time
import hashlib
from datetime import datetime

BOT_TOKEN = "8681026360:AAEWL0f-vR5A6TZ_48joKDm5mfb7pL_7Nq4"
CHAT_ID = "8744993955"
URL_ALL = "https://www.eqs-news.com/de/"
URL_ADHOC = "https://www.eqs-news.com/de/?category=ad-hoc"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
INTERVAL = 60
known_all = set()
known_adhoc = set()
is_first_run = True

def send_telegram(msg):
    try:
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram failed: " + str(e))

def get_items(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if len(title) < 10:
            continue
        if any(k in href for k in ["#", "javascript", "mailto"]):
            continue
        if "eqs-news.com/news/" not in href:
            continue
        full_url = href if href.startswith("http") else "https://www.eqs-news.com" + href
        is_adhoc = any(k in full_url.lower() for k in ["adhoc", "ad-hoc", "pflichtmitteilung"])
        uid = hashlib.md5(full_url.encode()).hexdigest()
        items.append({"id": uid, "title": title[:200], "url": full_url, "is_adhoc": is_adhoc})
    seen = set()
    unique = []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            unique.append(it)
    return unique

def check():
    global is_first_run, known_all, known_adhoc
    now = datetime.now().strftime("%H:%M:%S")
    if is_first_run:
        print("[" + now + "] initializing...")
        try:
            items = get_items(URL_ALL)
            known_all = set(it["id"] for it in items)
            print("  all news: " + str(len(items)))
        except Exception as e:
            print("  all news failed: " + str(e))
        try:
            items = get_items(URL_ADHOC)
            known_adhoc = set(it["id"] for it in items)
            print("  adhoc: " + str(len(items)))
        except Exception as e:
            print("  adhoc failed: " + str(e))
        is_first_run = False
        send_telegram("EQS monitor started. Checking every 60 seconds.")
        print("  started, telegram sent\n")
        return
    print("[" + now + "] checking...", end=" ", flush=True)
    found_any = False
    try:
        all_items = get_items(URL_ALL)
        new_all = [it for it in all_items if it["id"] not in known_all and not it.get("is_adhoc")]
        if new_all:
            found_any = True
            for it in new_all:
                known_all.add(it["id"])
                send_telegram("New announcement:\n" + it["title"][:100] + "\n" + it["url"])
                print("\n  new: " + it["title"][:80])
    except Exception as e:
        print("\n  all failed: " + str(e))
    try:
        adhoc_items = get_items(URL_ADHOC)
        new_adhoc = [it for it in adhoc_items if it["id"] not in known_adhoc and it.get("is_adhoc")]
        if new_adhoc:
            found_any = True
            for it in new_adhoc:
                known_adhoc.add(it["id"])
                known_all.add(it["id"])
                send_telegram("AD-HOC NEW:\n" + it["title"][:100] + "\n" + it["url"])
                print("\n  AD-HOC: " + it["title"][:80])
    except Exception as e:
        print("\n  adhoc failed: " + str(e))
    if not found_any:
        print("ok, no new items")

print("EQS monitor starting...")
while True:
    check()
    time.sleep(INTERVAL)
