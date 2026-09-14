"""Chinanews carries general world news, so G2's raw count is not the number
that matters -- the count AFTER the North Korea filter is. Run G2 on the
filtered subset and see whether it still clears the threshold."""
import feedparser, requests, re, sys

# the Windows console is cp949 here and cannot encode Chinese; replace rather
# than crash, so a printing problem never looks like a data problem
sys.stdout.reconfigure(errors="replace")
from datetime import datetime, timezone
from test_g2 import when, UA, DAILY_MIN, WEEKLY_MIN

URL = "https://www.chinanews.com.cn/rss/world.xml"
# 朝鲜 simplified / 朝鮮 traditional / 平壤 Pyongyang / 金正恩 Kim Jong Un
KEYS = ["朝鲜", "朝鮮", "平壤", "金正恩", "北韩", "韩朝", "半岛"]
PAT = re.compile("|".join(KEYS))

now = datetime.now(timezone.utc)
f = feedparser.parse(requests.get(URL, headers=UA, timeout=20).content)

hits, in14 = [], 0
for e in f.entries:
    text = f"{e.get('title','')} {e.get('summary','')}"
    m = PAT.findall(text)
    if not m:
        continue
    dt, _field = when(e)
    fresh = dt is not None and (now - dt).total_seconds() / 86400 <= 14
    in14 += 1 if fresh else 0
    hits.append((sorted(set(m)), fresh, e.get("title", "")[:50]))

print(f"entries={len(f.entries)}  keyword hits={len(hits)}  of those within 14d={in14}")
print(f"thresholds: daily 14d>={DAILY_MIN}, weekly 14d>={WEEKLY_MIN}")
print(f"verdict: daily={'PASS' if in14 >= DAILY_MIN else 'FAIL'}"
      f"  weekly={'PASS' if in14 >= WEEKLY_MIN else 'FAIL'}")
if hits:
    print("\nmatched:")
    for keys, fresh, title in hits:
        print(f"  {'14d' if fresh else 'old':<4} {','.join(keys):<12} {title}")
else:
    print("\nno entry in the current feed window mentions North Korea at all")
