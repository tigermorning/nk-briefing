import feedparser, requests, re
from trafilatura import fetch_url, extract

THRESHOLDS = [200, 600, 1500, 4000]
UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("38North", "https://www.38north.org/feed/"),
]

rows = []
for name, url in SOURCES:
    r = requests.get(url, headers=UA, timeout=20)
    f = feedparser.parse(r.content)
    for e in f.entries[:3]:
        body = e.get("content", [{}])[0].get("value") if e.get("content") else e.get("summary", "")
        rss_text = re.sub(r"<[^>]+>", "", body or "").strip()
        html = fetch_url(e.get("link", ""))
        ext = extract(html) if html else ""
        rows.append((name, len(rss_text), len(ext or "")))

hdr = f"{'source':<10}{'rss_len':>8}{'ext_len':>9}" + "".join(f"{'>=' + str(t):>8}" for t in THRESHOLDS)
print(hdr)
print("-" * len(hdr))
for name, rl, el in rows:
    marks = "".join(f"{('PASS' if el >= t else 'FAIL'):>8}" for t in THRESHOLDS)
    print(f"{name:<10}{rl:>8}{el:>9}{marks}")

print()
print("pass count by threshold:")
for t in THRESHOLDS:
    n = sum(1 for _, _, el in rows if el >= t)
    print(f"  >={t:<5} {n}/{len(rows)}")
