# -*- coding: utf-8 -*-
"""How often must we collect? A feed that holds N items overflows when the
outlet publishes N items faster than we come back. The feed itself tells us:
the span between its oldest and newest entry IS the window we get to see.

A window shorter than our collection interval means articles fall out unseen,
and nothing in the result says so -- the count just looks like a slow day.
"""
import sys, requests, feedparser
from datetime import datetime, timezone
from test_g1 import UA

sys.stdout.reconfigure(errors="replace")

SOURCES = [
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml"),
    ("38North", "https://www.38north.org/feed/"),
]

def stamps(url):
    f = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
    out = []
    for e in f.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            out.append(datetime(*t[:6], tzinfo=timezone.utc))
    return sorted(out), len(f.entries)

now = datetime.now(timezone.utc)
print(f"{'source':<11}{'items':>6}{'span_h':>8}{'per_day':>9}{'safe_gap_h':>12}  verdict")
print("-" * 72)
for name, url in SOURCES:
    ts, n = stamps(url)
    if len(ts) < 2:
        print(f"{name:<11}{n:>6}{'-':>8}{'-':>9}{'-':>12}  too few dated entries")
        continue
    span_h = (ts[-1] - ts[0]).total_seconds() / 3600
    per_day = len(ts) / (span_h / 24) if span_h else float("inf")
    # come back before the window empties, with room to spare
    safe = span_h / 2
    verdict = "24h collection LOSES articles" if span_h < 24 else "24h collection is enough"
    print(f"{name:<11}{n:>6}{span_h:>8.1f}{per_day:>9.1f}{safe:>12.1f}  {verdict}")

print()
# a WordPress feed usually pages; if DailyNK does, the 10-item window is not a hard limit
print("DailyNK paging check:")
seen = set()
for page in (1, 2, 3):
    u = "https://www.dailynk.com/feed" + ("" if page == 1 else f"?paged={page}")
    try:
        f = feedparser.parse(requests.get(u, headers=UA, timeout=20).content)
        links = [e.get("link", "") for e in f.entries]
        fresh = [l for l in links if l not in seen]
        seen.update(links)
        ts, _ = [], None
        dates = sorted(datetime(*e.published_parsed[:6]).strftime("%m-%d %H:%M")
                       for e in f.entries if e.get("published_parsed"))
        print(f"  paged={page}: entries={len(f.entries)} new={len(fresh)} "
              f"range={dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}")
    except Exception as exc:
        print(f"  paged={page}: {type(exc).__name__}: {exc}")
print(f"  distinct links across pages: {len(seen)}")
