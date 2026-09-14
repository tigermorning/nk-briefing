import feedparser, requests, re
UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("38North", "https://www.38north.org/feed/"),
]
for name, url in SOURCES:
    r = requests.get(url, headers=UA, timeout=20)
    f = feedparser.parse(r.content)
    print(f"== {name} status={r.status_code} count={len(f.entries)} ==")
    for e in f.entries[:3]:
        body = e.get("content", [{}])[0].get("value") if e.get("content") else e.get("summary", "")
        text = re.sub(r"<[^>]+>", "", body or "").strip()
        print("-", e.get("title", "")[:80])
        print(" ", e.get("published", ""), f"len={len(text)}")
