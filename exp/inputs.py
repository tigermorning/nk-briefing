# -*- coding: utf-8 -*-
"""Freeze the experiment inputs once, so every run judges the same articles.

candidates12.json  step 6: newest 4 each from Yonhap-NK, DailyNK, DailyNK-JP
pool.json          step 7: every daily-source item in 72h, shuffled (seed 7)
                   so a batch is not one outlet's block
bodies.json        step 8: 10 article bodies -- 4 Japanese (DailyNK-JP),
                   2 Japanese (AsiaPress), 2 English (38North), 2 Korean.
                   Full article text: kept out of git (.gitignore)
"""
import random
from datetime import datetime, timezone

import requests, trafilatura
from common import save, EXP
from collect_nk import collect

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"}

res = collect({"hours": 168})
now = datetime.now(timezone.utc)
items = sorted(res["items"], key=lambda i: i["at"], reverse=True)
age = lambda i: (now - datetime.fromisoformat(i["at"])).total_seconds() / 3600
by = lambda src: [i for i in items if i["source"] == src]

cands = []
for src in ("Yonhap-NK", "DailyNK", "DailyNK-JP"):
    cands += [{"source": i["source"], "title": i["title"], "link": i["link"]} for i in by(src)[:4]]
save("candidates12.json", cands)

pool = [{"source": i["source"], "title": i["title"], "link": i["link"]}
        for i in items if age(i) <= 72 and i["source"] not in ("38North", "AsiaPress")]
random.Random(7).shuffle(pool)
save("pool.json", pool)

picks = by("DailyNK-JP")[:4] + by("AsiaPress")[:2] + by("38North")[:2] + by("Yonhap-NK")[:1] + by("DailyNK")[:1]
bodies = []
for i in picks:
    r = requests.get(i["link"], headers=UA, timeout=25)
    body = trafilatura.extract(r.content) or "" if r.status_code == 200 else ""
    bodies.append({"source": i["source"], "title": i["title"], "link": i["link"],
                   "http": r.status_code, "body": body})
save("bodies.json", bodies)

print(f"measured {now.isoformat(timespec='seconds')}")
print(f"candidates12: {[c['source'] for c in cands]}")
print(f"pool 72h: {len(pool)} items · " + ", ".join(
    f"{s} {sum(1 for p in pool if p['source'] == s)}" for s in dict.fromkeys(p["source"] for p in pool)))
for b in bodies:
    print(f"body {b['source']:<11} http {b['http']} {len(b['body']):>6}자  {b['title'][:40]}")
