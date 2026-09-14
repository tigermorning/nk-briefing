import feedparser, requests, json, os, time
from datetime import datetime, timezone
from urllib.robotparser import RobotFileParser

# metrics live next to this script, not next to whatever directory you happen
# to run from -- a cwd-relative path silently starts a second, empty store
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
METRICS = os.path.join(STORE, "metrics.jsonl")

UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml", "https://www.yna.co.kr/robots.txt"),
    ("DailyNK", "https://www.dailynk.com/feed", "https://www.dailynk.com/robots.txt"),
    ("38North", "https://www.38north.org/feed/", "https://www.38north.org/robots.txt"),
]
now = datetime.now(timezone.utc)
out = {"ts": now.isoformat(), "g2_14d": {}, "g2_nodate": {}, "g3": {}}
t0 = time.time()
for name, feed_url, robots_url in SOURCES:
    f = feedparser.parse(requests.get(feed_url, headers=UA, timeout=20).content)
    in14, nodate = 0, 0
    for e in f.entries:
        t = e.get("published_parsed")
        if not t:
            nodate += 1
            continue
        age_d = (now - datetime(*t[:6], tzinfo=timezone.utc)).total_seconds() / 86400
        if age_d <= 14:
            in14 += 1
    out["g2_14d"][name] = in14
    out["g2_nodate"][name] = nodate
    rp = RobotFileParser()
    rp.parse(requests.get(robots_url, headers=UA, timeout=20).text.splitlines())
    links = [e.get("link", "") for e in f.entries[:3]]
    out["g3"][name] = [bool(rp.can_fetch("*", u)) for u in links]
    print(f"{name}: 14d={in14} nodate={nodate} robots={out['g3'][name]}")
out["elapsed_s"] = round(time.time() - t0, 1)
out["g1_pass_rate_prior"] = round(7 / 9, 3)
os.makedirs(STORE, exist_ok=True)
with open(METRICS, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(out, ensure_ascii=False) + "\n")
print("elapsed_s:", out["elapsed_s"], "-> store/metrics.jsonl append done")
