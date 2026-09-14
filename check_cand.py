import feedparser, requests, re
UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
CANDS = [
    ("NKNews", "https://www.nknews.org/feed/"),
    ("DailyNK-EN", "https://www.dailynk.com/english/rss-feed/"),
    ("Yonhap-JP-NK", "https://jp.yna.co.kr/RSS/nk.xml"),
    ("Chinanews-World", "https://www.chinanews.com.cn/rss/world.xml"),
]
for name, url in CANDS:
    try:
        r = requests.get(url, headers=UA, timeout=20)
        f = feedparser.parse(r.content)
        n = len(f.entries)
        e = f.entries[0] if n else {}
        body = e.get("content", [{}])[0].get("value") if e.get("content") else e.get("summary", "")
        text = re.sub(r"<[^>]+>", "", body or "").strip()
        print(f"{name}: status={r.status_code} count={n} newest={e.get('published','?')[:31]} sumlen={len(text)}")
    except Exception as ex:
        print(f"{name}: ERR {ex}")
