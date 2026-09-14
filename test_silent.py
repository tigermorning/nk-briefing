import feedparser, requests
from datetime import datetime, timezone, timedelta

UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
GOOD = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml"),
]
# same list, but RFA's URL is broken -- simulating a source that quietly dies
BROKEN = GOOD[:2] + [("RFA-KO", "https://www.rfa.org/korean/THIS-IS-GONE.xml")]

def collect(sources, hours, log_dead):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items, seen, dead = [], set(), []
    for name, url in sources:
        try:
            f = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
            if not f.entries:
                raise ValueError("empty feed")
            for e in f.entries:
                t = e.get("published_parsed")
                if not t:
                    continue
                if datetime(*t[:6], tzinfo=timezone.utc) < cutoff:
                    continue
                key = (e.get("link", "") or "").split("?")[0]
                if key in seen:
                    continue
                seen.add(key)
                items.append({"source": name})
        except Exception:
            if log_dead:
                dead.append(name)
            # log_dead=False -> the failure leaves no trace at all
    by_src = {}
    for it in items:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1
    return len(items), by_src, dead

print("hours=72\n")
for label, sources, log_dead in [
    ("1. all sources alive          ", GOOD,   True),
    ("2. RFA dead, NOT logged       ", BROKEN, False),
    ("3. RFA dead, logged           ", BROKEN, True),
]:
    n, by_src, dead = collect(sources, 72, log_dead)
    print(f"{label} total={n:<4} by_src={by_src}  dead={dead}")

print()
print("compare line 2 and line 3: same total, same by_src.")
print("only line 3 lets you tell a dead source from a quiet news day.")
