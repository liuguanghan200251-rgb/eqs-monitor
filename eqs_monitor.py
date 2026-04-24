import tkinter as tk
from tkinter import messagebox
from tkinter import scrolledtext, ttk
import threading
import time
import hashlib
import requests
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup
import winsound

VERSION = "1.0"
GITHUB_RAW = "https://raw.githubusercontent.com/liuguanghan200251-rgb/eqs-monitor/main/eqs_monitor_5.py"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/liuguanghan200251-rgb/eqs-monitor/main/version.txt"

URL_ALL   = "https://www.eqs-news.com/de/"
URL_ADHOC = "https://www.eqs-news.com/de/"
INTERVAL  = 60
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:32b"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
}

known_all   = set()
known_adhoc = set()
is_first_run = True
running = False
driver = None

VOICE_VOLUME = 100  # 0-100

def beep_alert():
    try:
        import subprocess
        msg = "有新的Ad-hoc刷新了"
        ps_cmd = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Volume = {VOICE_VOLUME}; "
            "$s.Rate = -1; "
            f"$s.Speak('{msg}')"
        )
        subprocess.Popen(
            ["powershell", "-Command", ps_cmd],
            creationflags=0x08000000
        )
    except:
        winsound.Beep(600, 350)
        time.sleep(0.1)
        winsound.Beep(900, 350)
        time.sleep(0.1)
        winsound.Beep(1200, 500)

def beep_startup():
    winsound.Beep(900, 200)

def translate(text):
    try:
        return GoogleTranslator(source='auto', target='zh-CN').translate(text[:300])
    except:
        return ""

def translate_full(text):
    try:
        chunks = [text[i:i+400] for i in range(0, min(len(text), 2000), 400)]
        results = []
        for chunk in chunks:
            t = GoogleTranslator(source='auto', target='zh-CN').translate(chunk)
            if t:
                results.append(t)
        return "\n".join(results)
    except Exception as e:
        return f"翻译失败: {e}"

def fetch_stock(query):
    try:
        # 先搜索股票代码
        search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&lang=en-US&region=US&quotesCount=1"
        r = requests.get(search_url, headers=HEADERS, timeout=8)
        results = r.json().get("quotes", [])
        if not results:
            return None
        symbol = results[0]["symbol"]
        name   = results[0].get("shortname") or results[0].get("longname") or symbol

        # 获取价格和历史数据
        chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
        r2 = requests.get(chart_url, headers=HEADERS, timeout=8)
        data = r2.json()
        meta = data["chart"]["result"][0]["meta"]
        price  = meta["regularMarketPrice"]
        prev   = meta["chartPreviousClose"]
        change = price - prev
        pct    = change / prev * 100
        # 历史价格点
        closes = data["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
        closes = [c for c in closes if c is not None]
        timestamps = data["chart"]["result"][0].get("timestamp", [])
        return {
            "symbol": symbol,
            "name": name,
            "price": price,
            "change": change,
            "pct": pct,
            "closes": closes,
            "timestamps": timestamps,
        }
    except Exception as e:
        return None

def fetch_index(symbol, name):
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d",
            headers=HEADERS, timeout=8
        )
        data = resp.json()
        meta  = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev  = meta["chartPreviousClose"]
        change = price - prev
        pct    = change / prev * 100
        sign   = "+" if change >= 0 else ""
        color  = "#3fb950" if change >= 0 else "#f85149"
        return f"{price:,.2f}  {sign}{pct:.2f}%", color
    except:
        return "获取失败", "#555"

def fetch_dax():
    return fetch_index("%5EGDAXI", "DAX")

def fetch_article(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script","style","nav","header","footer","aside"]):
            tag.decompose()
        for sel in ["div.news-detail__content","div.article__body","div.content","main","article"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator=" ", strip=True)
                if len(text) > 100:
                    return text[:3000]
        body = soup.find("body")
        if body:
            return body.get_text(separator=" ", strip=True)[:3000]
        return "无法获取文章内容"
    except Exception as e:
        return f"抓取失败: {e}"

def ai_analyze(title, desc, full_text=""):
    content_to_analyze = full_text if full_text else desc
    prompt = f"""你是一个专业的德语财经翻译和分析助手。

以下是一则德国上市公司公告的内容：
标题：{title}
内容：{content_to_analyze}

请将公告内容完整地用中文逐条整理，要求：
1. 保留所有具体数字、日期、公司名称、金额
2. 每个要点单独一行，用「·」开头
3. 不要省略任何重要信息
4. 最后加一行：【结论】利好/利空/中性 + 一句理由

直接输出整理结果，不要任何前言："""
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 600}
        }, timeout=120)
        return resp.json().get("response", "").strip()
    except Exception as e:
        return f"AI分析失败: {e}"

def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    return webdriver.Chrome(options=opts)

def get_items(drv, url):
    drv.get(url)
    time.sleep(4)
    items = []
    all_links = drv.find_elements(By.TAG_NAME, "a")
    for a in all_links[:80]:
        try:
            href = a.get_attribute("href") or ""
            if not href.startswith("http"):
                continue
            if "eqs-news.com/news/" not in href:
                continue
            title = a.text.strip()
            if len(title) < 10:
                continue
            full_text = a.text.strip()
            lines = [l.strip() for l in full_text.split("\n") if l.strip()]
            clean_lines = []
            for l in lines:
                if any(x in l for x in ["€","♦","Add to","watchlist","FUNCTIONS","Share price","%"]):
                    continue
                if len(l) < 3:
                    continue
                clean_lines.append(l)
            is_adhoc = any("ad-hoc" in l.lower() for l in clean_lines[:5])
            desc = ""
            for l in clean_lines:
                if (len(l) > 30 and l != title and
                    not any(x in l.lower() for x in ["corporate","voting","directors","research","media","ad-hoc","announcements"]) and
                    not (len(l) <= 10 and ":" in l)):
                    desc = l[:200]
                    break
            uid = hashlib.md5(href.encode()).hexdigest()
            items.append({"id": uid, "title": title[:200], "desc": desc, "url": href, "is_adhoc": is_adhoc})
        except:
            continue
    seen = set()
    unique = []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            unique.append(it)
    return unique

def check_update(root):
    def run():
        try:
            resp = requests.get(GITHUB_VERSION_URL, timeout=8)
            latest = resp.text.strip()
            if latest and latest != VERSION:
                answer = messagebox.askyesno(
                    "发现新版本",
                    f"当前版本：v{VERSION}\n最新版本：v{latest}\n\n是否立即更新？",
                    parent=root
                )
                if answer:
                    new_code = requests.get(GITHUB_RAW, timeout=15).text
                    current_path = __file__
                    with open(current_path, "w", encoding="utf-8") as f:
                        f.write(new_code)
                    messagebox.showinfo("更新完成",
                        "更新成功！请重新启动程序。", parent=root)
        except Exception as e:
            pass  # 更新失败静默处理
    threading.Thread(target=run, daemon=True).start()

class App:
    def __init__(self, root):
        self.root = root
        root.title("EQS 公告监控")
        root.geometry("1000x680")
        root.configure(bg="#0f1117")
        root.resizable(True, True)

        # 启动时检查更新
        root.after(2000, lambda: check_update(root))

        self.bg_canvas = tk.Canvas(root, bg="#0f1117", highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._draw_stock_bg()
        root.bind("<Configure>", lambda e: self._draw_stock_bg())

        top = tk.Frame(root, bg="#0f1117")
        top.pack(fill="x", padx=16, pady=(14,6))
        tk.Label(top, text=f"📡 EQS 公告监控  v{VERSION}", font=("Segoe UI", 16, "bold"),
                 bg="#0f1117", fg="#e8eaf0").pack(side="left")
        self.status_var = tk.StringVar(value="未启动")
        self.status_dot = tk.Label(top, text="●", font=("Segoe UI", 14),
                                   bg="#0f1117", fg="#555")
        self.status_dot.pack(side="right", padx=(0,4))
        tk.Label(top, textvariable=self.status_var, font=("Segoe UI", 10),
                 bg="#0f1117", fg="#888").pack(side="right")

        # 指数实时价格栏
        idx_frame = tk.Frame(top, bg="#0f1117")
        idx_frame.pack(side="left", padx=(20,0))

        def make_index_widget(parent, name):
            f = tk.Frame(parent, bg="#161b27", padx=10, pady=4)
            f.pack(side="left", padx=(0,6))
            tk.Label(f, text=name, font=("Segoe UI", 9, "bold"),
                     bg="#161b27", fg="#555").pack(side="left", padx=(0,6))
            var   = tk.StringVar(value="加载中...")
            label = tk.Label(f, textvariable=var, font=("Segoe UI", 10, "bold"),
                             bg="#161b27", fg="#888")
            label.pack(side="left")
            return var, label

        self.dax_var,  self.dax_label  = make_index_widget(idx_frame, "DAX")
        self.ndx_var,  self.ndx_label  = make_index_widget(idx_frame, "NASDAQ")
        self.spx_var,  self.spx_label  = make_index_widget(idx_frame, "S&P500")
        self._update_dax()

        stats = tk.Frame(root, bg="#161b27", pady=8)
        stats.pack(fill="x", padx=16, pady=(0,8))
        self.stat_checks = tk.StringVar(value="检查次数: 0")
        self.stat_new    = tk.StringVar(value="新公告: 0")
        self.stat_adhoc  = tk.StringVar(value="Ad-hoc: 0")
        self.stat_time   = tk.StringVar(value="上次检查: --")
        for var, color in [(self.stat_checks,"#7c8cba"),(self.stat_new,"#5ba85a"),
                           (self.stat_adhoc,"#e06c6c"),(self.stat_time,"#7c8cba")]:
            tk.Label(stats, textvariable=var, font=("Segoe UI", 9),
                     bg="#161b27", fg=color, padx=14).pack(side="left")
        self.check_count = 0
        self.new_count   = 0
        self.adhoc_count = 0

        # 股票搜索栏
        search_frame = tk.Frame(root, bg="#0f1117")
        search_frame.pack(fill="x", padx=16, pady=(0,6))
        tk.Label(search_frame, text="🔍", font=("Segoe UI",11),
                 bg="#0f1117", fg="#555").pack(side="left", padx=(0,6))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                                bg="#161b27", fg="#c9d1d9", insertbackground="#c9d1d9",
                                font=("Segoe UI",10), relief="flat", width=20)
        search_entry.pack(side="left", padx=(0,6), ipady=4)
        search_entry.bind("<Return>", lambda e: self._search_stock())
        tk.Button(search_frame, text="搜索",
                  command=self._search_stock,
                  bg="#21262d", fg="#79c0ff", font=("Segoe UI",9),
                  relief="flat", padx=10, pady=4, cursor="hand2").pack(side="left")
        self.search_result = tk.Label(search_frame, text="",
                                      font=("Segoe UI",10, "bold"),
                                      bg="#0f1117", fg="#888")
        self.search_result.pack(side="left", padx=(12,0))
        # 迷你图画布
        self.mini_chart = tk.Canvas(search_frame, bg="#0f1117",
                                    highlightthickness=0, width=160, height=32)
        self.mini_chart.pack(side="left", padx=(10,0))

        # 左右可拖动分栏
        pane = tk.PanedWindow(root, orient="horizontal", bg="#21262d",
                              sashwidth=4, sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True, padx=16, pady=(0,8))

        left = tk.Frame(pane, bg="#0f1117")
        tk.Label(left, text="消息流", font=("Segoe UI", 9, "bold"),
                 bg="#0f1117", fg="#555").pack(anchor="w", pady=(0,4))
        self.log = scrolledtext.ScrolledText(
            left, bg="#0d1117", fg="#c9d1d9", font=("Consolas", 9),
            relief="flat", bd=0, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("time",   foreground="#555")
        self.log.tag_config("info",   foreground="#58a6ff")
        self.log.tag_config("ok",     foreground="#3fb950")
        self.log.tag_config("warn",   foreground="#d29922")
        self.log.tag_config("adhoc",  foreground="#f85149")
        self.log.tag_config("normal", foreground="#79c0ff")
        self.log.tag_config("desc",   foreground="#8b949e")
        self.log.tag_config("url",    foreground="#3fb950")
        self.log.tag_config("sep",    foreground="#21262d")
        pane.add(left, minsize=300, stretch="always")

        right = tk.Frame(pane, bg="#0f1117")
        tk.Label(right, text="内容", font=("Segoe UI", 9, "bold"),
                 bg="#0f1117", fg="#555").pack(anchor="w", pady=(0,4))
        self.ai_panel = scrolledtext.ScrolledText(
            right, bg="#0d1117", fg="#c9d1d9", font=("Consolas", 9),
            relief="flat", bd=0, wrap="word", state="disabled")
        self.ai_panel.pack(fill="both", expand=True)
        self.ai_panel.tag_config("ai_title", foreground="#f85149", font=("Consolas", 9, "bold"))
        self.ai_panel.tag_config("ai_text",  foreground="#bc8cff")
        self.ai_panel.tag_config("ai_meta",  foreground="#8b949e")
        self.ai_panel.tag_config("ai_sep",   foreground="#21262d")
        pane.add(right, minsize=200, stretch="always")
        root.update_idletasks()
        pane.sash_place(0, int(root.winfo_width() * 0.6), 0)

        btn_frame = tk.Frame(root, bg="#0f1117")
        btn_frame.pack(fill="x", padx=16, pady=(0,14))
        self.btn_start = tk.Button(btn_frame, text="▶  开始监控",
            command=self.start, bg="#238636", fg="white",
            font=("Segoe UI", 10, "bold"), relief="flat",
            padx=18, pady=7, cursor="hand2", activebackground="#2ea043")
        self.btn_start.pack(side="left", padx=(0,8))
        self.btn_stop = tk.Button(btn_frame, text="■  停止",
            command=self.stop, bg="#21262d", fg="#f85149",
            font=("Segoe UI", 10), relief="flat",
            padx=18, pady=7, cursor="hand2", state="disabled",
            activebackground="#30363d")
        self.btn_stop.pack(side="left", padx=(0,8))
        tk.Button(btn_frame, text="🗑 清空消息流",
            command=self.clear_log, bg="#21262d", fg="#8b949e",
            font=("Segoe UI", 10), relief="flat",
            padx=14, pady=7, cursor="hand2",
            activebackground="#30363d").pack(side="left", padx=(0,6))
        tk.Button(btn_frame, text="🗑 清空内容",
            command=self.clear_ai, bg="#21262d", fg="#8b949e",
            font=("Segoe UI", 10), relief="flat",
            padx=14, pady=7, cursor="hand2",
            activebackground="#30363d").pack(side="left")
        self.interval_var = tk.StringVar(value="60")
        tk.Label(btn_frame, text="间隔(秒):", bg="#0f1117",
                 fg="#555", font=("Segoe UI",9)).pack(side="right", padx=(0,4))
        ttk.Combobox(btn_frame, textvariable=self.interval_var,
                     values=["30","60","120","300"], width=5,
                     state="readonly").pack(side="right", padx=(0,16))

        # 音量控制
        tk.Label(btn_frame, text="音量:", bg="#0f1117",
                 fg="#555", font=("Segoe UI",9)).pack(side="right", padx=(0,4))
        self.vol_var = tk.IntVar(value=100)
        vol_slider = tk.Scale(btn_frame, from_=0, to=100, orient="horizontal",
                              variable=self.vol_var, bg="#0f1117", fg="#888",
                              troughcolor="#21262d", highlightthickness=0,
                              length=80, showvalue=False,
                              command=self._update_volume)
        vol_slider.pack(side="right", padx=(0,4))
        self.vol_label = tk.Label(btn_frame, text="100", bg="#0f1117",
                                  fg="#888", font=("Segoe UI",9), width=3)
        self.vol_label.pack(side="right")

        # 字体大小
        self.font_size = 9
        tk.Label(btn_frame, text="字号:", bg="#0f1117",
                 fg="#555", font=("Segoe UI",9)).pack(side="right", padx=(0,4))
        tk.Button(btn_frame, text="A+", command=self._font_up,
            bg="#21262d", fg="#8b949e", font=("Segoe UI",9), relief="flat",
            padx=8, pady=5, cursor="hand2").pack(side="right", padx=(0,2))
        tk.Button(btn_frame, text="A-", command=self._font_down,
            bg="#21262d", fg="#8b949e", font=("Segoe UI",9), relief="flat",
            padx=8, pady=5, cursor="hand2").pack(side="right", padx=(0,4))

    def log_line(self, parts):
        self.log.configure(state="normal")
        for text, tag in parts:
            self.log.insert("end", text, tag)
        self.log.insert("end", "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def clear_ai(self):
        self.ai_panel.configure(state="normal")
        self.ai_panel.delete("1.0", "end")
        self.ai_panel.configure(state="disabled")

    def set_status(self, text, color):
        self.status_var.set(text)
        self.status_dot.config(fg=color)

    def _add_buttons(self, item):
        url   = item["url"]
        title = item["title"]
        desc  = item.get("desc", "")

        btn_frame = tk.Frame(self.log, bg="#161b27", pady=3, padx=6)

        def do_translate():
            btn_translate.config(state="disabled", text="翻译中...")
            def run():
                self.ai_panel.configure(state="normal")
                self.ai_panel.insert("end", "─"*35+"\n", "ai_sep")
                self.ai_panel.insert("end", "📄 全文翻译\n" + title[:50] + "\n", "ai_title")
                self.ai_panel.insert("end", "抓取文章中...\n", "ai_meta")
                self.ai_panel.configure(state="disabled")
                self.ai_panel.see("end")
                text = fetch_article(url)
                translated = translate_full(text)
                self.ai_panel.configure(state="normal")
                self.ai_panel.delete("end-2l", "end-1l")
                self.ai_panel.insert("end", translated + "\n\n", "ai_text")
                self.ai_panel.configure(state="disabled")
                self.ai_panel.see("end")
                btn_translate.config(state="normal", text="📄 全文翻译")
            threading.Thread(target=run, daemon=True).start()

        def do_ai():
            btn_ai.config(state="disabled", text="分析中...")
            def run():
                self.ai_panel.configure(state="normal")
                self.ai_panel.insert("end", "─"*35+"\n", "ai_sep")
                self.ai_panel.insert("end", "🤖 AI分析\n" + title[:50] + "\n", "ai_title")
                self.ai_panel.insert("end", "正在抓取文章全文...\n", "ai_meta")
                self.ai_panel.configure(state="disabled")
                self.ai_panel.see("end")
                full_text = fetch_article(url)
                self.ai_panel.configure(state="normal")
                self.ai_panel.delete("end-2l", "end-1l")
                self.ai_panel.insert("end", "AI整理中...\n", "ai_meta")
                self.ai_panel.configure(state="disabled")
                analysis = ai_analyze(title, desc, full_text)
                self.ai_panel.configure(state="normal")
                self.ai_panel.delete("end-2l", "end-1l")
                for line in analysis.split("\n"):
                    if line.strip():
                        self.ai_panel.insert("end", line+"\n", "ai_text")
                self.ai_panel.insert("end", "\n", "ai_meta")
                self.ai_panel.configure(state="disabled")
                self.ai_panel.see("end")
                btn_ai.config(state="normal", text="🤖 AI分析")
            threading.Thread(target=run, daemon=True).start()

        btn_translate = tk.Button(btn_frame, text="📄 全文翻译",
            command=do_translate, bg="#21262d", fg="#79c0ff",
            font=("Segoe UI", 8), relief="flat", padx=8, pady=3,
            cursor="hand2", activebackground="#30363d")
        btn_translate.pack(side="left", padx=(0,6))
        btn_ai = tk.Button(btn_frame, text="🤖 AI分析",
            command=do_ai, bg="#21262d", fg="#bc8cff",
            font=("Segoe UI", 8), relief="flat", padx=8, pady=3,
            cursor="hand2", activebackground="#30363d")
        btn_ai.pack(side="left")

        self.log.configure(state="normal")
        self.log.window_create("end", window=btn_frame)
        self.log.insert("end", "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _draw_stock_bg(self):
        c = self.bg_canvas
        c.delete("bg")
        w = self.root.winfo_width() or 1000
        h = self.root.winfo_height() or 680
        import random
        configs = [
            {"color": "#1a2a1a", "points": 80, "amp": 60, "offset": h*0.3, "seed": 1},
            {"color": "#1a1a2a", "points": 60, "amp": 40, "offset": h*0.6, "seed": 2},
            {"color": "#2a1a1a", "points": 70, "amp": 50, "offset": h*0.8, "seed": 3},
        ]
        for cfg in configs:
            random.seed(cfg["seed"])
            pts = cfg["points"]
            amp = cfg["amp"]
            base = cfg["offset"]
            coords = []
            y = base
            for i in range(pts):
                x = i * w / pts
                y += random.uniform(-amp*0.3, amp*0.3)
                y = max(base - amp, min(base + amp, y))
                coords.extend([x, y])
            if len(coords) >= 4:
                c.create_line(coords, fill=cfg["color"], width=1.5, smooth=True, tags="bg")
        for i in range(0, w, 80):
            c.create_line(i, 0, i, h, fill="#111820", width=1, tags="bg")
        for i in range(0, h, 50):
            c.create_line(0, i, w, i, fill="#111820", width=1, tags="bg")

    def _search_stock(self):
        query = self.search_var.get().strip()
        if not query:
            return
        self.search_result.config(text="搜索中...", fg="#888")
        self.mini_chart.delete("all")
        def run():
            result = fetch_stock(query)
            if not result:
                self.search_result.config(text="未找到", fg="#f85149")
                return
            sign  = "+" if result["change"] >= 0 else ""
            color = "#3fb950" if result["change"] >= 0 else "#f85149"
            text  = f"{result['name']}  {result['price']:,.2f}  {sign}{result['pct']:.2f}%"
            self.search_result.config(text=text, fg=color)
            # 画迷你图
            closes = result["closes"]
            if len(closes) > 2:
                w, h = 160, 32
                mn, mx = min(closes), max(closes)
                rng = mx - mn if mx != mn else 1
                pts = []
                for i, c in enumerate(closes):
                    x = i * w / (len(closes)-1)
                    y = h - (c - mn) / rng * (h-4) - 2
                    pts.extend([x, y])
                self.mini_chart.delete("all")
                if len(pts) >= 4:
                    self.mini_chart.create_line(pts, fill=color, width=1.5, smooth=True)
        threading.Thread(target=run, daemon=True).start()

    def _update_dax(self):
        def run():
            t, c = fetch_index("%5EGDAXI", "DAX")
            self.dax_var.set(t); self.dax_label.config(fg=c)
            t, c = fetch_index("%5EIXIC", "NASDAQ")
            self.ndx_var.set(t); self.ndx_label.config(fg=c)
            t, c = fetch_index("%5EGSPC", "S&P500")
            self.spx_var.set(t); self.spx_label.config(fg=c)
            self.root.after(30000, self._update_dax)
        threading.Thread(target=run, daemon=True).start()

    def _update_volume(self, val):
        import builtins
        v = int(float(val))
        self.vol_label.config(text=str(v))
        # 更新全局音量
        import sys
        mod = sys.modules[__name__] if __name__ in sys.modules else None
        global VOICE_VOLUME
        VOICE_VOLUME = v

    def _font_up(self):
        self.font_size = min(self.font_size + 1, 20)
        self._apply_font()

    def _font_down(self):
        self.font_size = max(self.font_size - 1, 7)
        self._apply_font()

    def _apply_font(self):
        f_mono = ("Consolas", self.font_size)
        f_ui   = ("Segoe UI", self.font_size)
        # 内容面板
        self.log.configure(font=f_mono)
        self.ai_panel.configure(font=f_mono)
        # 所有 Label、Button 递归更新
        def update_widget(w):
            cls = w.__class__.__name__
            try:
                if cls in ("Label", "Button"):
                    w.configure(font=f_ui)
                elif cls == "Combobox":
                    w.configure(font=f_ui)
            except:
                pass
            for child in w.winfo_children():
                update_widget(child)
        update_widget(self.root)

    def start(self):
        global running, is_first_run, known_all, known_adhoc, driver
        running = True
        is_first_run = True
        known_all.clear()
        known_adhoc.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.set_status("启动中...", "#d29922")
        beep_startup()
        threading.Thread(target=self.monitor_loop, daemon=True).start()

    def stop(self):
        global running, driver
        running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.set_status("已停止", "#555")
        self.log_line([("── 监控已停止 ──\n", "sep")])
        if driver:
            try: driver.quit()
            except: pass
            driver = None

    def monitor_loop(self):
        global running, is_first_run, known_all, known_adhoc, driver
        try:
            self.log_line([("正在启动浏览器...", "info")])
            driver = make_driver()
            self.log_line([("浏览器已就绪\n", "ok")])
        except Exception as e:
            self.log_line([("浏览器启动失败: ", "adhoc"), (str(e), "desc")])
            self.stop()
            return

        while running:
            now = datetime.now().strftime("%H:%M:%S")
            try:
                if is_first_run:
                    self.log_line([("[", "sep"), (now, "time"), ("] ", "sep"),
                                   ("初始化中...", "info")])
                    all_items = get_items(driver, URL_ALL)
                    known_all   = set(it["id"] for it in all_items)
                    known_adhoc = set(it["id"] for it in all_items if it.get("is_adhoc"))
                    is_first_run = False
                    adhoc_cnt = len([it for it in all_items if it.get("is_adhoc")])
                    self.log_line([("  ✓ 全部公告: ", "ok"), (str(len(all_items))+" 条", "desc"),
                                   ("   其中Ad-hoc: ", "ok"), (str(adhoc_cnt)+" 条\n", "desc")])
                    self.set_status("监控中", "#3fb950")
                    self.status_dot.config(fg="#3fb950")
                else:
                    self.check_count += 1
                    self.stat_checks.set(f"检查次数: {self.check_count}")
                    self.stat_time.set(f"上次检查: {now}")
                    all_items = get_items(driver, URL_ALL)
                    new_all   = [it for it in all_items if it["id"] not in known_all and not it.get("is_adhoc")]
                    new_adhoc = [it for it in all_items if it["id"] not in known_adhoc and it.get("is_adhoc")]

                    for it in new_all:
                        known_all.add(it["id"])
                        self.new_count += 1
                        self.stat_new.set(f"新公告: {self.new_count}")
                        cn = translate(it["title"])
                        self.log_line([("─"*60+"\n", "sep")])
                        self.log_line([("[","sep"),(now,"time"),("] ","sep"),("📢 新公告\n","normal")])
                        self.log_line([("  标题: ","desc"),(it["title"][:100]+"\n","warn")])
                        if it.get("desc"):
                            self.log_line([("  描述: ","desc"),(it["desc"][:120]+"\n","desc")])
                        if cn:
                            self.log_line([("  中文: ","desc"),(cn+"\n","ok")])
                        self.log_line([("  链接: ","desc"),(it["url"]+"\n","url")])
                        self._add_buttons(it)

                    for it in new_adhoc:
                        known_adhoc.add(it["id"])
                        known_all.add(it["id"])
                        self.adhoc_count += 1
                        self.stat_adhoc.set(f"Ad-hoc: {self.adhoc_count}")
                        # 立刻播报，不等翻译
                        threading.Thread(target=beep_alert, daemon=True).start()
                        cn = translate(it["title"])
                        self.log_line([("═"*60+"\n","adhoc")])
                        self.log_line([("[","sep"),(now,"time"),("] ","sep"),("🚨 Ad-hoc 新公告！\n","adhoc")])
                        self.log_line([("  标题: ","desc"),(it["title"][:100]+"\n","adhoc")])
                        if it.get("desc"):
                            self.log_line([("  描述: ","desc"),(it["desc"][:120]+"\n","desc")])
                        if cn:
                            self.log_line([("  中文: ","desc"),(cn+"\n","ok")])
                        self.log_line([("  链接: ","desc"),(it["url"]+"\n","url")])
                        self._add_buttons(it)

                    if not new_all and not new_adhoc:
                        interval = int(self.interval_var.get())
                        self.log_line([("[","sep"),(now,"time"),("] ","sep"),
                                       ("✓ 无新增","ok"),(f"  (下次: {interval}秒后)\n","desc")])

            except Exception as e:
                self.log_line([("[","sep"),(now,"time"),("] ","sep"),
                               ("错误: ","adhoc"),(str(e)+"\n","desc")])

            interval = int(self.interval_var.get())
            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
