import requests
import time
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup

BOT_TOKEN = "8681026360:AAEWL0f-vR5A6TZ_48joKDm5mfb7pL_7Nq4"
CHAT_ID = "8744993955"

# 使用 Markuswire / DGAP 官方 XML 数据源
SOURCES = [
    "https://dgap.de/dgap/Public/adhoc/adhocList.php?format=xml",
    "https://www.dgap.de/dgap/Public/adhoc/list.xml",
    "https://www.finanzen.net/nachricht/dgap_adhoc.xml",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
}

INTERVAL = 60
known_ids = set()
is_first_run = True
working_url = None

def send_telegram(msg):
    try:
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram failed: " + str(e))

def try_fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    print("  status " + str(resp.status_code) + " from " + url[:60])
    print("  content preview: " + resp.text[:200])
    return resp

def get_items(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "lxml-xml")
    items = []
    for item in soup.find_all(["item", "news", "adhoc", "entry"])[:30]:
        title = ""
        link = ""
        pub = ""
        for t in ["title", "headline", "subject"]:
            el = item.find(t)
            if el:
                title = el.get_text(strip=True)
                break
        for l in ["link", "url", "href"]:
            el = item.find(l)
            if el:
                link = el.get_text(strip=True) or el.get("href", "")
                break
        for d in ["pubDate", "date", "published", "datetime"]:
            el = item.find(d)
            if el:
                pub = el.get_text(strip=True)
                break
        if not title:
            continue
        uid = hashlib.md5((title + link).encode()).hexdigest()
        items.append({"id": uid, "title": title, "url": link, "pub": pub})
    return items

def check():
    global is_first_run, known_ids, working_url
    now = datetime.now().strftime("%H:%M:%S")

    if is_first_run:
        print("[" + now + "] initializing, testing sources...")
        for url in SOURCES:
            try:
                resp = try_fetch(url)
                if resp.status_code == 200 and len(resp.text) > 100:
                    working_url = url
                    items = get_items(url)
                    known_ids = set(it["id"] for it in items)
                    print("  SUCCESS! items: " + str(len(items)))
                    if items:
                        print("  latest: " + items[0]["title"][:60])
                    break
            except Exception as e:
                print("  failed: " + str(e))
        is_first_run = False
        if working_url:
            send_telegram("EQS Ad-hoc monitor started. Source: " + working_url)
        else:
            send_telegram("Monitor started but all sources failed. Check logs.")
        print("  telegram sent\n")
        return

    if not working_url:
        print("[" + now + "] no working source")
        return

    print("[" + now + "] checking...", end=" ", flush=True)
    try:
        items = get_items(working_url)
        new_items = [it for it in items if it["id"] not in known_ids]
        if new_items:
            for it in new_items:
                known_ids.add(it["id"])
                msg = "AD-HOC NEW:\n" + it["title"] + "\n" + it["pub"] + "\n" + it["url"]
                send_telegram(msg)
                print("\n  NEW: " + it["title"][:80])
        else:
            print("ok, no new (" + str(len(items)) + " total)")
    except Exception as e:
        print("\n  failed: " + str(e))

print("EQS Ad-hoc monitor starting...")
while True:
    check()
    time.sleep(INTERVAL)
