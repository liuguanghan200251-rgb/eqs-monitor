import requests
import time
import hashlib
from datetime import datetime

BOT_TOKEN = "8681026360:AAEWL0f-vR5A6TZ_48joKDm5mfb7pL_7Nq4"
CHAT_ID = "8744993955"

# EQS 公开 API
API_ALL   = "https://www.eqs-news.com/api/v1/news?language=de&limit=20"
API_ADHOC = "https://www.eqs-news.com/api/v1/news?language=de&limit=20&category=ad-hoc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

INTERVAL = 60
known_all   = set()
known_adhoc = set()
is_first_run = True

def send_telegram(msg):
    try:
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram failed: " + str(e))

def get_items(api_url):
    resp = requests.get(api_url, headers=HEADERS, timeout=20)
    data = resp.json()
    items = []
    # 尝试不同的 JSON 结构
    news_list = []
    if isinstance(data, list):
        news_list = data
    elif isinstance(data, dict):
        for key in ["data", "news", "items", "results", "articles"]:
            if key in data:
                news_list = data[key]
                break
    for item in news_list[:30]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("headline") or item.get("name") or ""
        link  = item.get("url") or item.get("link") or item.get("href") or ""
        uid   = item.get("id") or item.get("news_id") or hashlib.md5((title+link).encode()).hexdigest()
        pub   = item.get("published_at") or item.get("date") or item.get("pub_date") or ""
        cat   = str(item.get("category") or item.get("type") or "").lower()
        is_adhoc = "adhoc" in cat or "ad-hoc" in cat or "pflicht" in cat
        if title:
            items.append({"id": str(uid), "title": str(title), "url": str(link), "pub": str(pub), "is_adhoc": is_adhoc})
    return items

def check():
    global is_first_run, known_all, known_adhoc
    now = datetime.now().strftime("%H:%M:%S")

    if is_first_run:
        print("[" + now + "] initializing...")
        try:
            items = get_items(API_ALL)
            known_all = set(it["id"] for it in items)
            print("  all news: " + str(len(items)))
            if items:
                print("  latest: " + items[0]["title"][:60])
        except Exception as e:
            print("  all news failed: " + str(e))
        try:
            items = get_items(API_ADHOC)
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
        all_items = get_items(API_ALL)
        new_all = [it for it in all_items if it["id"] not in known_all and not it.get("is_adhoc")]
        if new_all:
            found_any = True
            for it in new_all:
                known_all.add(it["id"])
                msg = "📢 新公告\n" + it["title"] + "\n" + it["url"]
                send_telegram(msg)
                print("\n  new: " + it["title"][:80])
    except Exception as e:
        print("\n  all failed: " + str(e))

    try:
        adhoc_items = get_items(API_ADHOC)
        new_adhoc = [it for it in adhoc_items if it["id"] not in known_adhoc and it.get("is_adhoc")]
        if new_adhoc:
            found_any = True
            for it in new_adhoc:
                known_adhoc.add(it["id"])
                known_all.add(it["id"])
                msg = "🚨 EQS Ad-hoc 新公告！\n\n标题：" + it["title"] + "\n时间：" + it["pub"][:16] + "\n链接：" + it["url"]
                send_telegram(msg)
                print("\n  AD-HOC: " + it["title"][:80])
    except Exception as e:
        print("\n  adhoc failed: " + str(e))

    if not found_any:
        print("ok, no new items")

print("EQS monitor starting...")
while True:
    check()
    time.sleep(INTERVAL)
