import feedparser, requests, re
from trafilatura import fetch_url, extract

UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("38North", "https://www.38north.org/feed/"),
]

def rss_body(e):
    body = e.get("content", [{}])[0].get("value") if e.get("content") else e.get("summary", "")
    return re.sub(r"<[^>]+>", "", body or "").strip()

hdr = f"{'source':<10}{'rss':>7}{'A:fetch_url':>13}{'B:req+UA':>10}{'code':>6}"
print(hdr)
print("-" * len(hdr))
for name, url in SOURCES:
    f = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
    for e in f.entries[:3]:
        link = e.get("link", "")

        # A: what test_g1.py does now -- trafilatura's own downloader, default UA
        html_a = fetch_url(link)
        a = len(extract(html_a) or "") if html_a else 0

        # B: requests with an explicit UA, then hand the html to extract()
        try:
            r = requests.get(link, headers=UA, timeout=20)
            code = r.status_code
            b = len(extract(r.text) or "")
        except Exception:
            code, b = -1, 0

        print(f"{name:<10}{len(rss_body(e)):>7}{a:>13}{b:>10}{code:>6}")
