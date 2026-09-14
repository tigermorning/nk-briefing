# -*- coding: utf-8 -*-
"""How often does a 24h window come up short?

Honest simulation range is bounded by the SHORTEST feed: a window older than
a source's own span makes that source contribute 0 for reasons that have
nothing to do with the news. Counting those windows would invent lean days.
"""
import sys, requests, feedparser
from datetime import datetime, timezone, timedelta
from test_g1 import UA

sys.stdout.reconfigure(errors="replace")

SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("38North", "https://www.38north.org/feed/"),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml"),
]

pool, spans = [], {}
for name, url in SOURCES:
    f = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
    ts = []
    for e in f.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not t:
            continue
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        ts.append(dt)
        pool.append((dt, name, (e.get("link", "") or "").split("?")[0]))
    spans[name] = min(ts) if ts else None
    print(f"{name:<11} entries={len(ts):>3}  oldest={min(ts).strftime('%m-%d %H:%M') if ts else '-'}")

now = datetime.now(timezone.utc)
# every source must cover the whole simulated range, so the limit is the
# newest of the four "oldest" timestamps
limit = max(v for v in spans.values() if v)
hours_ok = (now - limit).total_seconds() / 3600
print(f"\nall four sources cover only the last {hours_ok:.1f}h "
      f"(bounded by {[k for k,v in spans.items() if v==limit][0]})")
print("windows older than that would invent lean days, so they are not simulated.\n")

print(f"{'window ending':<16}{'24h':>6}{'48h':>6}{'72h':>6}   sources in the 24h window")
print("-" * 74)
rows = []
step = 12
k = 0
while True:
    end = now - timedelta(hours=step * k)
    if (end - timedelta(hours=24)) < limit:
        break
    counts = {}
    for w in (24, 48, 72):
        start = end - timedelta(hours=w)
        if start < limit and w > 24:
            counts[w] = None      # not honestly simulatable at this depth
        else:
            counts[w] = len({l for d, n, l in pool if start <= d <= end})
    by = {}
    for d, n, l in pool:
        if end - timedelta(hours=24) <= d <= end:
            by[n] = by.get(n, 0) + 1
    fmt = lambda v: "-" if v is None else str(v)
    print(f"{end.strftime('%m-%d %H:%M'):<16}{fmt(counts[24]):>6}{fmt(counts[48]):>6}"
          f"{fmt(counts[72]):>6}   {by}")
    rows.append(counts[24])
    k += 1

if rows:
    print(f"\n24h windows simulated: {len(rows)}  min={min(rows)}  max={max(rows)}  "
          f"mean={sum(rows)/len(rows):.1f}")
    for bar in (3, 5, 8, 10):
        short = sum(1 for r in rows if r < bar)
        print(f"  below {bar:>2} items: {short}/{len(rows)} windows")
